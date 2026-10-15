"""Tests for the stored-reply contamination audit (read-only) and the opt-in repair/rollback."""

import hashlib
import json
import sqlite3

import pytest

from scripts.audit_reasoning_contamination import main as audit_main
from studybot.core.messages import Role
from studybot.core.reasoning_mode import ReasoningMode
from studybot.core.teaching_mode import TeachingMode
from studybot.storage.database import open_database
from studybot.storage.reasoning_audit import (
    RepairManifest,
    audit_database,
    repair_database,
    rollback_repair,
)
from studybot.storage.sqlite_repository import SQLiteChatRepository

SECRET = "SECRET-REASONING-7f3a"
CONTAMINATED = f"Okay, {SECRET} planning.\n</think>\n\nHello! Which topic?"
AMBIGUOUS = f"{SECRET} one</think>two"
CLEAN = "Density is mass over volume."
CODE = "```\n<think>\n</think>\n```"


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "studybot.db"
    connection = open_database(path)
    repository = SQLiteChatRepository(connection)
    repository.create_chat("chat-a", None, None, TeachingMode.TEACH, ReasoningMode.FAST)
    repository.create_chat("chat-b", None, None, TeachingMode.PRACTICE, ReasoningMode.DEEP)
    for chat_id, reply in (("chat-a", CONTAMINATED), ("chat-a", CLEAN), ("chat-b", AMBIGUOUS), ("chat-b", CODE)):
        repository.append_message(chat_id, Role.USER, "question")
        repository.append_message(chat_id, Role.ASSISTANT, reply)
    connection.close()
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contents(path):
    connection = sqlite3.connect(path)
    try:
        return [row[0] for row in connection.execute("SELECT content FROM messages WHERE role='assistant' ORDER BY id")]
    finally:
        connection.close()


def test_audit_classifies_and_reports_ids_only(db):
    report = audit_database(db)
    assert report.assistant_messages_scanned == 4
    assert report.contaminated_count == 1
    assert report.ambiguous_count == 1
    by_chat = {c.chat_id: c for c in report.chats}
    assert len(by_chat["chat-a"].contaminated_message_ids) == 1
    assert len(by_chat["chat-b"].ambiguous_message_ids) == 1
    serialized = json.dumps(report.to_dict())
    assert SECRET not in serialized and "Hello" not in serialized


def test_audit_never_modifies_the_database(db):
    before = digest(db)
    audit_database(db)
    assert digest(db) == before


def test_audit_opens_read_only(db):
    from studybot.storage import reasoning_audit

    connection = reasoning_audit._connect_read_only(db)
    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM messages")
    finally:
        connection.close()


def test_audit_missing_database_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        audit_database(tmp_path / "nope.db")


def test_repair_backs_up_then_changes_only_contaminated(db, tmp_path):
    manifest = repair_database(db, tmp_path / "backups")
    assert len(manifest.repaired_message_ids) == 1
    assert contents(db) == ["Hello! Which topic?", CLEAN, AMBIGUOUS, CODE]
    assert contents(tmp_path / "backups" / manifest.backup.split("/")[-1]) == [CONTAMINATED, CLEAN, AMBIGUOUS, CODE]
    manifest_file = (tmp_path / "backups").glob("*.manifest.json")
    saved = json.loads(next(manifest_file).read_text())
    assert SECRET not in json.dumps(saved)


def test_rollback_restores_exactly_the_repaired_rows(db, tmp_path):
    manifest = repair_database(db, tmp_path / "backups")
    assert rollback_repair(manifest) == 1
    assert contents(db) == [CONTAMINATED, CLEAN, AMBIGUOUS, CODE]


def test_repair_is_idempotent(db, tmp_path):
    repair_database(db, tmp_path / "b1")
    second = repair_database(db, tmp_path / "b2")
    assert second.repaired_message_ids == []


def test_manifest_round_trips(db, tmp_path):
    manifest = repair_database(db, tmp_path / "backups")
    path = tmp_path / "m.json"
    manifest.write(path)
    assert RepairManifest.read(path) == manifest


def test_script_dry_run_changes_nothing_and_prints_no_content(db, capsys):
    before = digest(db)
    assert audit_main(["--db", str(db)]) == 0
    output = capsys.readouterr()
    assert digest(db) == before
    assert "Contaminated (repairable): 1" in output.out
    assert SECRET not in output.out + output.err


def test_script_refuses_apply_without_confirmation(db, tmp_path):
    before = digest(db)
    assert audit_main(["--db", str(db), "--apply", "--backup-dir", str(tmp_path / "b")]) == 2
    assert audit_main(["--db", str(db), "--apply", "--yes"]) == 2
    assert digest(db) == before


def test_script_apply_and_rollback(db, tmp_path, capsys):
    assert audit_main(["--db", str(db), "--apply", "--backup-dir", str(tmp_path / "b"), "--yes"]) == 0
    assert contents(db)[0] == "Hello! Which topic?"
    manifest = next((tmp_path / "b").glob("*.manifest.json"))
    assert audit_main(["--rollback", str(manifest)]) == 2  # needs --yes
    assert audit_main(["--rollback", str(manifest), "--yes"]) == 0
    assert contents(db)[0] == CONTAMINATED
