"""Analiz sunucusunun Python ortamı güncel mi (tools/panel_baslat.bat çağırır; yalnızca standart kütüphane).

Kullanım: `python tools/check_analyzer_deps.py` → eksik ya da eski paket yoksa 0, varsa 1 (eksikler Türkçe yazılır).

Denetim iki adımdır:
1. `services/edge/pyproject.toml`'daki çalışma bağımlılıkları (`dependencies` + `analyzer` eki) KAYNAK dosyadan okunur
   (kurulu paketin bilgisi değil: düzenlenebilir kurulumda o, kurulum anındaki listedir ve sonradan eklenen paketi
   bilmez). Her biri kurulu mu, `>=` alt sürümü karşılanıyor mu bakılır. İçe aktarmayı geciktirilen paketler (ör.
   psutil) de böylece yakalanır.
2. Analiz sunucusunun uygulama modülü (`bantvision.analyzer.app`) içe aktarılır: bildirilmemiş ama açılışta gereken
   bir şey de eksikse yakalanır.
Başlatıcı 1 görünce paketleri yeniden kurar (`pip install -e services/edge[analyzer]`).
"""
from __future__ import annotations

import importlib
import importlib.metadata
import pathlib
import re
import sys
import tomllib
from collections.abc import Callable

ROOT = pathlib.Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "services" / "edge" / "pyproject.toml"
EXTRA = "analyzer"
APP_MODULE = "bantvision.analyzer.app"

_REQ = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(.*)$")
_MIN = re.compile(r">=\s*([0-9][0-9A-Za-z.+!-]*)")
_NUM = re.compile(r"\d+")


def requirements(pyproject: pathlib.Path = PYPROJECT, extra: str = EXTRA) -> list[tuple[str, str | None]]:
    """(dağıtım adı, en düşük sürüm ya da None): `dependencies` ve `[project.optional-dependencies].<extra>`."""
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    out: list[tuple[str, str | None]] = []
    for spec in [*project.get("dependencies", []), *project.get("optional-dependencies", {}).get(extra, [])]:
        m = _REQ.match(spec.split(";", 1)[0])
        if m is None:
            continue
        low = _MIN.search(m.group(2))
        out.append((m.group(1), low.group(1) if low else None))
    return out


def _release(version: str) -> tuple[int, ...]:
    """Sürümün sayı kısmı ("1.18.0rc1" → (1, 18, 0)); sondaki sıfırlar karşılaştırmayı etkilemez."""
    head = re.match(r"\d+(?:\.\d+)*", version)
    parts = [int(x) for x in _NUM.findall(head.group(0))] if head else []
    while parts and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def problems(reqs: list[tuple[str, str | None]],
             version: Callable[[str], str] = importlib.metadata.version) -> list[str]:
    """Eksik ya da alt sürümün altında kalan paketler (Türkçe satırlar)."""
    out = []
    for name, low in reqs:
        try:
            have = version(name)
        except importlib.metadata.PackageNotFoundError:
            out.append(f"{name}: kurulu değil")
            continue
        if low is not None and _release(have) < _release(low):
            out.append(f"{name}: {have} kurulu, en az {low} gerekli")
    return out


def import_problem(module: str = APP_MODULE) -> str | None:
    """Modül içe aktarılamıyorsa nedeni (Türkçe), aktarılıyorsa None."""
    try:
        importlib.import_module(module)
    except Exception as e:  # noqa: BLE001 — her açılış hatası "ortam eksik" sayılır, başlatıcı yeniden kurar
        return f"{module} açılmıyor: {type(e).__name__}: {e}"
    return None


def main(pyproject: pathlib.Path = PYPROJECT, module: str = APP_MODULE) -> int:
    found = problems(requirements(pyproject))
    if not found:                                          # paket listesi tamam: uygulama modülü de açılıyor mu
        err = import_problem(module)
        if err:
            found.append(err)
    for line in found:
        print(line)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
