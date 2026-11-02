"""Çekirdek testleri analiz sunucusu paketleri olmadan da çalışır: `.[dev]` fastapi kurmaz, conftest onu istememeli."""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

CODE = """
import sys
sys.modules["fastapi"] = None
sys.modules["starlette"] = None
import pytest
raise SystemExit(pytest.main(["-q", "-p", "no:cacheprovider", "tests/test_count_numbers.py"]))
"""


def test_core_tests_run_without_fastapi() -> None:
    r = subprocess.run([sys.executable, "-c", CODE], capture_output=True, text=True, encoding="utf-8", timeout=120,
                       cwd=pathlib.Path(__file__).resolve().parents[1], check=False,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "StarletteDeprecationWarning" not in r.stdout                # fastapi'siz oturumda bu uyarı da olmaz
