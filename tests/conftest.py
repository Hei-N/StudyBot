"""Test-session hooks."""

import os
import sys

_exit_status = 0


def pytest_sessionfinish(session, exitstatus):
    global _exit_status
    _exit_status = int(exitstatus)


def pytest_unconfigure(config):
    # PyMuPDF's native module crashes (SIGSEGV) during interpreter finalization on Python 3.14
    # when it was used from worker threads, after every test has already passed. That raises
    # a macOS "Python quit unexpectedly" dialog for each test run. The app's engine process
    # exits cleanly; only the test process is affected. When PyMuPDF was loaded, skip
    # finalization and exit with pytest's real status.
    if "pymupdf" in sys.modules:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(_exit_status)
