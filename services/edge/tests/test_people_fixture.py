"""iOS eşdeğerlik dosyası (apps/ios/BantSayacTests/people_parity.json) Python izleyicisinin güncel davranışını mı
gösteriyor? İzleyici değişip dosya yeniden üretilmezse Swift testi eski davranışı doğrulamış olur."""
from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]


def test_people_parity_fixture_is_current() -> None:
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "make_people_fixture.py"), "--check"],
                       capture_output=True, text=True, encoding="utf-8", check=False)
    assert r.returncode == 0, r.stdout + r.stderr
