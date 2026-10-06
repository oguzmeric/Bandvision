"""Analiz sunucusu başlatıcısı: `--log` ile tüm çıktı konsol yerine dosyaya gider (konsolda seçim sunucuyu dondurmasın)."""
from __future__ import annotations

import pathlib
import subprocess
import sys


def test_redirect_output_captures_python_and_native_writes(tmp_path: pathlib.Path) -> None:
    log = tmp_path / "logs" / "analyzer.log"
    code = (
        "import os, sys, pathlib\n"
        "from bantvision.analyzer.__main__ import redirect_output\n"
        f"redirect_output(pathlib.Path({str(log)!r}))\n"
        "print('python-stdout')\n"
        "print('python-stderr', file=sys.stderr)\n"
        "os.write(2, b'native-fd2\\n')\n"           # FFmpeg gibi yerel kodun doğrudan yazdığı
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8",
                       cwd=pathlib.Path(__file__).resolve().parents[1], check=False)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "" and r.stderr == ""                     # konsola hiçbir şey gitmez
    text = log.read_text(encoding="utf-8")
    assert "python-stdout" in text and "python-stderr" in text and "native-fd2" in text


def test_log_option_is_documented() -> None:
    r = subprocess.run([sys.executable, "-m", "bantvision.analyzer", "--help"], capture_output=True, text=True,
                       encoding="utf-8", cwd=pathlib.Path(__file__).resolve().parents[1], check=False)
    assert r.returncode == 0 and "--log" in r.stdout
