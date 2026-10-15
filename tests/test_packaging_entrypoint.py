"""The packaged engine is the regular API server, with nothing extra baked in."""

from __future__ import annotations

import runpy
from pathlib import Path

import studybot.api.__main__ as api_main
from studybot.api.auth import resolve_startup_token
from studybot.config.settings import Settings

PACKAGING = Path(__file__).resolve().parent.parent / "packaging" / "macos"


def test_packaged_entry_point_runs_the_existing_api_main(monkeypatch):
    calls = []
    monkeypatch.setattr(api_main, "main", lambda: calls.append("main"))

    runpy.run_path(str(PACKAGING / "backend_entry.py"), run_name="__main__")

    assert calls == ["main"]


def test_server_still_binds_loopback_only():
    assert api_main._HOST == "127.0.0.1"


def test_data_dir_and_token_come_from_the_environment(tmp_path):
    settings = Settings.from_env({"STUDYBOT_DATA_DIR": str(tmp_path / "data")})

    assert settings.data_dir == tmp_path / "data"


def test_pinned_token_is_used_when_the_launcher_provides_one(monkeypatch):
    monkeypatch.setenv("STUDYBOT_API_TOKEN", "launcher-token")

    assert resolve_startup_token() == "launcher-token"


def test_packaging_files_hardcode_no_personal_paths():
    for path in [*PACKAGING.glob("*"), PACKAGING.parent.parent / "scripts" / "build_macos_app.sh"]:
        if path.is_file():
            assert "/Users/" not in path.read_text(), path
