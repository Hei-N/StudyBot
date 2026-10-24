"""Starts a built engine in isolation and checks health, auth, a PDF import and shutdown.

Usage: smoke_test.py /path/to/studybot-backend
Uses a temporary data directory, a throwaway token and an OS-assigned port.
"""

import base64
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid

TOKEN = "smoke-test-token"

# A minimal one-page PDF with the text "Smoke test page".
_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 44>>stream\nBT /F1 12 Tf 20 100 Td (Smoke test page) Tj ET\nendstream endobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\ntrailer<</Root 1 0 R/Size 6>>\n%%EOF\n"
)


def request(port: int, method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read())


def import_a_pdf(port: int, data_dir: str) -> tuple[str, int]:
    """Authorize a source with a dummy grant, stage a PDF and import it; returns (state, pages)."""
    source = request(port, "POST", "/api/v1/library/sources/local-folder", {
        "displayName": "smoke", "locator": "/smoke",
        "authorization": {"platform": "macos", "kind": "security_scoped_bookmark",
                          "payload": base64.b64encode(b"dummy").decode()},
    })
    staging = os.path.join(data_dir, "ingest_staging")
    os.makedirs(staging, exist_ok=True)
    staging_id = str(uuid.uuid4())
    with open(os.path.join(staging, f"{staging_id}.pdf"), "wb") as handle:
        handle.write(_PDF)
    result = request(port, "POST", f"/api/v1/library/sources/{source['id']}/imports/pdf",
                     {"stagingId": staging_id, "relativePath": "smoke.pdf"})
    return result["file"]["processingState"], result["file"]["pageCount"] or 0


def get(port: int, token: str | None) -> int:
    request = urllib.request.Request(f"http://127.0.0.1:{port}/api/v1/health")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def upload_a_pdf(port: int, data_dir: str) -> tuple[str, int]:
    """Upload a staged PDF directly; returns (outcome, private copies stored)."""
    staging = os.path.join(data_dir, "ingest_staging")
    os.makedirs(staging, exist_ok=True)
    staging_id = str(uuid.uuid4())
    with open(os.path.join(staging, f"{staging_id}.pdf"), "wb") as handle:
        handle.write(_PDF)
    result = request(port, "POST", "/api/v1/library/uploads/pdf",
                     {"stagingId": staging_id, "displayName": "smoke-upload.pdf"})
    stored = os.listdir(os.path.join(data_dir, "library_files"))
    return result["outcome"], len(stored)


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
            pdf_state, pdf_pages = import_a_pdf(event["port"], data_dir)
            upload_outcome, stored_copies = upload_a_pdf(event["port"], data_dir)
            process.stdin.close()
            exit_code = process.wait(timeout=20)
        finally:
            if process.poll() is None:
                process.kill()
    print(
        f"health={authorized} no_token={anonymous} pdf={pdf_state}/{pdf_pages}p "
        f"upload={upload_outcome}/{stored_copies} exit={exit_code}"
    )
    ok = (authorized, anonymous, pdf_state, pdf_pages, upload_outcome, stored_copies, exit_code) == (
        200, 401, "ready", 1, "uploaded", 1, 0,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
