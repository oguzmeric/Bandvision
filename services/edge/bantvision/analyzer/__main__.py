"""`python -m bantvision.analyzer [--host 127.0.0.1] [--port 8090] [--log DOSYA]`

`--host` geri döngü adı (`127.0.0.1`, `localhost`, `::1`) değilse ANALYZER_TOKEN zorunludur: anahtarsız analiz sunucusu
ağa açılmaz (yalnızca bu bilgisayarın adlarıyla konuşur, ağdan gelen her istek 403 alırdı; hostcheck.py).
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

import uvicorn

from .app import create_app
from .hostcheck import LOOPBACK_NAMES
from .jobs import Settings

LAUNCH_REFUSED = ("Erişim anahtarı (ANALYZER_TOKEN) olmadan analiz sunucusu yalnızca bu bilgisayarda (127.0.0.1) "
                  "açılabilir; ağa açmak için ANALYZER_TOKEN tanımlayın.")


def redirect_output(path: pathlib.Path) -> None:
    """Tüm çıktıyı (Python, uvicorn, FFmpeg'in yerel yazdıkları) konsol yerine dosyaya yönlendirir.

    Windows'ta konsol penceresinde metin seçilince (hızlı düzenleme) o konsola yazan süreç durur: sunucu ilk günlük
    satırında donup hiçbir isteğe yanıt vermiyordu. Arka planda çalışan sunucu günlüğünü dosyaya yazmalı.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a", buffering=1, encoding="utf-8")  # noqa: SIM115 — süreç boyunca açık kalır
    os.dup2(f.fileno(), 1)
    os.dup2(f.fileno(), 2)
    sys.stdout = sys.stderr = f


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m bantvision.analyzer", description="BantVision video analiz sunucusu")
    ap.add_argument("--host", default="127.0.0.1",
                    help="Dinlenecek adres; 127.0.0.1, localhost ve ::1 dışındaki her adres ANALYZER_TOKEN ister")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--log", type=pathlib.Path, default=None,
                    help="Günlük dosyası: çıktı konsol yerine buraya yazılır (arka planda çalışırken önerilir)")
    a = ap.parse_args()
    if a.log is not None:
        redirect_output(a.log)
    # Anahtar create_app'in okuduğu yerden (Settings.from_env: ANALYZER_TOKEN, boş = yok) okunur ve aynı ayar uygulamaya
    # verilir. Anahtarsız sunucu ağa açılmaz: yalnızca bu bilgisayarın adlarını kabul ettiği için (hostcheck.py) ağdan
    # gelen her istek 403 alırdı (panelin "şifresiz yerel ağ asla açılmaz" kuralının karşılığı).
    settings = Settings.from_env()
    if not settings.token and a.host.lower() not in LOOPBACK_NAMES:
        print(LAUNCH_REFUSED, file=sys.stderr)          # --log verildiyse günlük dosyasına
        raise SystemExit(2)
    # Erişim günlüğü kapalı: canlı panel saniyede birkaç istek atar, günlüğü boğuyordu
    uvicorn.run(create_app(settings), host=a.host, port=a.port, access_log=a.log is None)


if __name__ == "__main__":
    main()
