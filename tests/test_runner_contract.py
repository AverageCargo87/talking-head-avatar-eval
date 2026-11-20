"""The mock runner must pass the same contract check the real runner is held to."""
import os
import shutil
import socket
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "runner"))

from contract_check import check  # noqa: E402

PORT = int(os.environ.get("MOCK_TEST_PORT", "41601"))


def wait_port(port, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            if s.connect_ex(("localhost", port)) == 0:
                return True
        time.sleep(0.1)
    return False


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_mock_runner_passes_the_contract():
    env = dict(os.environ, MOCK_PORT=str(PORT), MOCK_HOST="localhost")
    proc = subprocess.Popen(["node", os.path.join(ROOT, "runner", "mock-runner.mjs")], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert wait_port(PORT), "mock runner did not start"
        results = check(f"http://localhost:{PORT}")
        failed = [(name, detail) for name, ok, detail in results if not ok]
        assert not failed, failed
        assert len(results) == 7
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
