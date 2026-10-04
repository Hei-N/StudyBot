"""Audit (and, only on explicit request, repair) stored assistant replies
that contain leaked model reasoning (Stage 6.3).

Replies saved before the provider-boundary fix may hold a thinking model's
chain-of-thought ahead of the real answer. `ChatService` already keeps that
reasoning out of every new model request without touching storage (see
`core.output_integrity.strip_confident_reasoning`); this module is for the
user who also wants the stored text itself cleaned up.

* `audit_database` is strictly read-only: it opens SQLite with
  `mode=ro`, so it cannot write even by accident, and its report holds ids
  and counts only — never message content.
* `repair_database` changes only replies classified CONTAMINATED, only
  after writing a full backup copy of the database, in one transaction,
  and returns a manifest (message ids only) that `rollback_repair` uses
  to restore exactly those rows from the backup. Nothing calls it
  automatically; it exists for `scripts/audit_reasoning_contamination.py
  --apply`, which the user runs deliberately.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from studybot.core.output_integrity import HistoryVerdict, assess_stored_reply


@dataclass
class ChatFindings:
    chat_id: str
    contaminated_message_ids: list[int] = field(default_factory=list)
    ambiguous_message_ids: list[int] = field(default_factory=list)
    removable_chars: int = 0


@dataclass
class AuditReport:
    assistant_messages_scanned: int
    chats: list[ChatFindings]

    @property
    def contaminated_count(self) -> int:
        return sum(len(c.contaminated_message_ids) for c in self.chats)

    @property
    def ambiguous_count(self) -> int:
        return sum(len(c.ambiguous_message_ids) for c in self.chats)

    def to_dict(self) -> dict:
        return {
            "assistant_messages_scanned": self.assistant_messages_scanned,
            "contaminated_messages": self.contaminated_count,
            "ambiguous_messages": self.ambiguous_count,
            "chats": [
                {
                    "chat_id": c.chat_id,
                    "contaminated_message_ids": c.contaminated_message_ids,
                    "ambiguous_message_ids": c.ambiguous_message_ids,
                    "removable_chars": c.removable_chars,
                }
                for c in self.chats
            ],
        }


def _connect_read_only(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file():
        raise FileNotFoundError(f"No database at {db_path}")
    return sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)


def audit_database(db_path: Path) -> AuditReport:
    """Classify every stored assistant reply. Read-only."""
    connection = _connect_read_only(db_path)
    try:
        rows = connection.execute(
            "SELECT id, chat_id, content FROM messages WHERE role = 'assistant' ORDER BY chat_id, id"
        ).fetchall()
    finally:
        connection.close()

    findings: dict[str, ChatFindings] = {}
    for message_id, chat_id, content in rows:
        assessment = assess_stored_reply(content)
        if assessment.verdict is HistoryVerdict.CLEAN:
            continue
        chat = findings.setdefault(chat_id, ChatFindings(chat_id))
        if assessment.verdict is HistoryVerdict.CONTAMINATED:
            chat.contaminated_message_ids.append(message_id)
            chat.removable_chars += assessment.removed_chars
        else:
            chat.ambiguous_message_ids.append(message_id)
    return AuditReport(assistant_messages_scanned=len(rows), chats=list(findings.values()))


@dataclass(frozen=True)
class RepairManifest:
    database: str
    backup: str
    repaired_message_ids: list[int]
    created_at: str

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(self.__dict__, indent=2) + "\n", encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> "RepairManifest":
        return cls(**json.loads(path.read_text(encoding="utf-8")))


def repair_database(db_path: Path, backup_dir: Path) -> RepairManifest:
    """Replace each CONTAMINATED reply with its answer alone.

    Order: full backup first (SQLite's online backup API, so it's a
    consistent copy), then every update in a single transaction that
    re-classifies each row inside it — a reply that changed since the
    audit is judged on its current content. AMBIGUOUS replies are never
    touched. The returned manifest is also written next to the backup.
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"{db_path.stem}.pre-reasoning-repair-{stamp}{db_path.suffix}"
    if backup_path.exists():
        raise FileExistsError(f"Backup already exists: {backup_path}")

    source = sqlite3.connect(db_path)
    try:
        destination = sqlite3.connect(backup_path)
        try:
            source.backup(destination)
        finally:
            destination.close()

        repaired: list[int] = []
        with source:  # one transaction: all updates commit together or not at all
            rows = source.execute("SELECT id, content FROM messages WHERE role = 'assistant' ORDER BY id").fetchall()
            for message_id, content in rows:
                assessment = assess_stored_reply(content)
                if assessment.verdict is HistoryVerdict.CONTAMINATED and assessment.repaired:
                    source.execute("UPDATE messages SET content = ? WHERE id = ?", (assessment.repaired, message_id))
                    repaired.append(message_id)
    finally:
        source.close()

    manifest = RepairManifest(
        database=str(db_path.resolve()),
        backup=str(backup_path.resolve()),
        repaired_message_ids=repaired,
        created_at=stamp,
    )
    manifest.write(backup_path.with_suffix(".manifest.json"))
    return manifest


def rollback_repair(manifest: RepairManifest) -> int:
    """Restore exactly the rows a repair changed, from its backup. Returns
    the number of rows restored. Rows deleted since (e.g. the chat was
    deleted) are skipped, never re-created."""
    backup = _connect_read_only(Path(manifest.backup))
    try:
        originals = {
            message_id: content
            for message_id, content in backup.execute(
                f"SELECT id, content FROM messages WHERE id IN ({','.join('?' * len(manifest.repaired_message_ids))})",
                manifest.repaired_message_ids,
            ).fetchall()
        } if manifest.repaired_message_ids else {}
    finally:
        backup.close()

    target = sqlite3.connect(manifest.database)
    restored = 0
    try:
        with target:
            for message_id, content in originals.items():
                restored += target.execute(
                    "UPDATE messages SET content = ? WHERE id = ?", (content, message_id)
                ).rowcount
    finally:
        target.close()
    return restored
