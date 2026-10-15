"""The engine started by a launcher exits when the launcher's stdin closes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

import pytest


def _start_engine(data_dir: str, **extra_env: str) -> subprocess.Popen:
    env = {
        **os.environ,
        "STUDYBOT_DATA_DIR": data_dir,
        "STUDYBOT_API_PORT": "0",
        "STUDYBOT_API_TOKEN": "lifecycle-test-token",
        "STUDYBOT_MODEL_PROVIDER": "mock",
        **extra_env,
    }
    return subprocess.Popen(
        [sys.executable, "-m", "studybot.api"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
        text=True,
    )


def _read_ready(proc: subprocess.Popen) -> dict:
    line = proc.stdout.readline()
    event = json.loads(line)
    assert event["event"] == "studybot_api_ready"
    return event


def test_engine_exits_when_launcher_closes_stdin():
    with tempfile.TemporaryDirectory() as data_dir:
        proc = _start_engine(data_dir, STUDYBOT_EXIT_WHEN_STDIN_CLOSES="1")
        try:
            event = _read_ready(proc)
            assert event["port"] > 0
            assert proc.poll() is None
            proc.stdin.close()
            assert proc.wait(timeout=20) == 0
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.stdout.close()


def test_engine_ignores_stdin_unless_asked_to_watch_it():
    with tempfile.TemporaryDirectory() as data_dir:
        proc = _start_engine(data_dir)
        try:
            _read_ready(proc)
            proc.stdin.close()
            with pytest.raises(subprocess.TimeoutExpired):
                proc.wait(timeout=1.5)
        finally:
            proc.kill()
            proc.wait()
            proc.stdout.close()
