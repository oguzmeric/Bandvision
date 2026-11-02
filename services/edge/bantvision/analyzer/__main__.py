"""`python -m bantvision.analyzer [--host 127.0.0.1] [--port 8090] [--log DOSYA]`

`--host` geri döngü adı (`127.0.0.1`, `localhost`, `::1`) değilse ANALYZER_TOKEN zorunludur: anahtarsız analiz sunucusu
ağa açılmaz (yalnızca bu bilgisayarın adlarıyla konuşur, ağdan gelen her istek 403 alırdı; hostcheck.py).
"""
from __future__ import annotations

import argparse
import contextlib
import os
import pathlib
import sys
from typing import NoReturn

import uvicorn

from .app import create_app
from .hostcheck import LOOPBACK_NAMES
from .jobs import token_from_env

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


def refuse_launch(log: pathlib.Path | None) -> NoReturn:
    """Reddedilen açılış sessiz kalmaz: ileti gerçek hata çıktısına (konsol), `--log` verildiyse günlük dosyasına da
    yazılır; çıkış kodu 2, sunucu başlamaz. Günlük yazılamasa da ileti konsoldadır ve çıkış kodu değişmez."""
    print(LAUNCH_REFUSED, file=sys.stderr)
    if log is not None:
        with contextlib.suppress(OSError):
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a", encoding="utf-8") as f:
                print(LAUNCH_REFUSED, file=f)
    raise SystemExit(2)


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m bantvision.analyzer", description="BantVision video analiz sunucusu")
    ap.add_argument("--host", default="127.0.0.1",
                    help="Dinlenecek adres; 127.0.0.1, localhost ve ::1 dışındaki her adres ANALYZER_TOKEN ister")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--log", type=pathlib.Path, default=None,
                    help="Günlük dosyası: çıktı konsol yerine buraya yazılır (arka planda çalışırken önerilir)")
    a = ap.parse_args()
    # Anahtarsız sunucu ağa açılmaz: yalnızca bu bilgisayarın adlarını kabul ettiği için (hostcheck.py) ağdan gelen her
    # istek 403 alırdı (panelin "şifresiz yerel ağ asla açılmaz" kuralının karşılığı). Anahtar create_app'in okuduğu
    # yerden okunur (token_from_env). Denetim yönlendirmeden önce: ret iletisi konsola da gitsin.
    if not token_from_env() and a.host.lower() not in LOOPBACK_NAMES:
        refuse_launch(a.log)
    if a.log is not None:
        redirect_output(a.log)
    # Erişim günlüğü kapalı: canlı panel saniyede birkaç istek atar, günlüğü boğuyordu
    uvicorn.run(create_app(), host=a.host, port=a.port, access_log=a.log is None)


if __name__ == "__main__":
    main()
