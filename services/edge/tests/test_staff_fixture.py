"""iOS eşdeğerlik dosyası (apps/ios/BantSayacTests/staff_parity.json) Python'un güncel davranışını mı gösteriyor?"""
from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]


def test_staff_parity_fixture_is_current() -> None:
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "make_staff_fixture.py"), "--check"],
                       capture_output=True, text=True, encoding="utf-8", check=False)
    assert r.returncode == 0, r.stdout + r.stderr
