"""Starts a built engine in isolation and checks health, auth and shutdown.

Usage: smoke_test.py /path/to/studybot-backend
Uses a temporary data directory, a throwaway token and an OS-assigned port.
"""

import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

TOKEN = "smoke-test-token"


def get(port: int, token: str | None) -> int:
    request = urllib.request.Request(f"http://127.0.0.1:{port}/api/v1/health")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def main(executable: str) -> int:
    with tempfile.TemporaryDirectory() as data_dir:
        env = {
            **os.environ,
            "STUDYBOT_DATA_DIR": data_dir,
            "STUDYBOT_API_TOKEN": TOKEN,
            "STUDYBOT_API_PORT": "0",
            "STUDYBOT_MODEL_PROVIDER": "mock",
            "STUDYBOT_EXIT_WHEN_STDIN_CLOSES": "1",
        }
        process = subprocess.Popen(
            [executable], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env
        )
        try:
            event = json.loads(process.stdout.readline())
            assert event["event"] == "studybot_api_ready" and event["host"] == "127.0.0.1", event
            authorized = get(event["port"], TOKEN)
            anonymous = get(event["port"], None)
            process.stdin.close()
            exit_code = process.wait(timeout=20)
        finally:
            if process.poll() is None:
                process.kill()
    print(f"health={authorized} no_token={anonymous} exit={exit_code}")
    return 0 if (authorized, anonymous, exit_code) == (200, 401, 0) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
