"""Analiz sunucusunun Python ortamı güncel mi (tools/panel_baslat.bat çağırır; yalnızca standart kütüphane).

Kullanım: `python tools/check_analyzer_deps.py` → çıkış kodu:
  0  her şey tamam;
  1  eksik ya da eski paket var (Türkçe yazılır) → başlatıcı paketleri yeniden kurar;
  3  paket çakışması (Windows'ta işlemci `onnxruntime` ile `onnxruntime-directml` aynı klasörü kullanır) ya da yarım
     kalmış DirectML kurulumu (kayıt var, dosyaları yok) → başlatıcı işlemci sürümünü kaldırıp DirectML'i zorla yeniden
     kurar. 3, 1'den önceliklidir (çakışma çözülmeden eksik kurmak boşuna).

Denetim iki adımdır:
1. `services/edge/pyproject.toml`'daki çalışma bağımlılıkları (`dependencies` + `analyzer` eki) KAYNAK dosyadan okunur
   (kurulu paketin bilgisi değil: düzenlenebilir kurulumda o, kurulum anındaki listedir ve sonradan eklenen paketi
   bilmez). Her biri kurulu mu, `>=` alt sürümü karşılanıyor mu bakılır. İçe aktarmayı geciktirilen paketler (ör.
   psutil) de böylece yakalanır.
2. Analiz sunucusunun uygulama modülü (`bantvision.analyzer.app`) içe aktarılır: bildirilmemiş ama açılışta gereken
   bir şey de eksikse yakalanır.
Başlatıcı 1 görünce paketleri yeniden kurar (`pip install -e services/edge[analyzer]`).

Ortam işaretleri: yalnız `sys_platform == '<x>'` / `!= '<x>'` değerlendirilir (Windows'ta ekran kartı sürümü, öbür
platformlarda işlemci sürümü istenir). Başka her işaret (ör. `python_version`, `and`/`or` ile bileşik işaret,
`extra == '…'`) doğru sayılır; işareti yanlış çıkan bağımlılık atlanır.
"""
from __future__ import annotations

import csv
import importlib
import importlib.metadata
import pathlib
import re
import sys
import tomllib
from collections.abc import Callable, Mapping

ROOT = pathlib.Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "services" / "edge" / "pyproject.toml"
EXTRA = "analyzer"
APP_MODULE = "bantvision.analyzer.app"

_REQ = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(.*)$")
_MIN = re.compile(r">=\s*([0-9][0-9A-Za-z.+!-]*)")
_NUM = re.compile(r"\d+")
_PLATFORM_MARKER = re.compile(r"""^\s*sys_platform\s*(==|!=)\s*(['"])([^'"]*)\2\s*$""")

CPU_RUNTIME = "onnxruntime"
GPU_RUNTIME = "onnxruntime-directml"
CONFLICT_EXIT = 3


def _marker_applies(marker: str, platform: str) -> bool:
    """`sys_platform == 'x'` / `!= 'x'` değerlendirilir; başka her işaret (ya da işaretsiz) doğru sayılır."""
    m = _PLATFORM_MARKER.match(marker)
    if m is None:
        return True
    return (platform == m.group(3)) == (m.group(1) == "==")


def requirements(pyproject: pathlib.Path = PYPROJECT, extra: str = EXTRA,
                 platform: str = sys.platform) -> list[tuple[str, str | None]]:
    """(dağıtım adı, en düşük sürüm ya da None): `dependencies` ve `[project.optional-dependencies].<extra>`;
    ortam işareti bu `platform` için yanlış olanlar atlanır."""
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    out: list[tuple[str, str | None]] = []
    for spec in [*project.get("dependencies", []), *project.get("optional-dependencies", {}).get(extra, [])]:
        body, _, marker = spec.partition(";")
        if not _marker_applies(marker, platform):
            continue
        m = _REQ.match(body)
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


def conflicts(reqs: list[tuple[str, str | None]], installed: Mapping[str, str] | None = None,
              platform: str = sys.platform) -> list[str]:
    """Windows'ta işlemci `onnxruntime` ile istenen `onnxruntime-directml` birlikte kuruluysa çakışma (Türkçe satır):
    ikisi de `onnxruntime` klasörüne yazar, biri ötekinin dosyalarını bozar. `installed`: dağıtım adı → sürüm (verilmezse
    kurulu paketlere bakılır). DirectML henüz kurulu değilse çakışma yoktur (önce eksik olarak 1 döner)."""
    if platform != "win32" or GPU_RUNTIME not in {n for n, _ in reqs}:
        return []
    have = installed if installed is not None else _installed((CPU_RUNTIME, GPU_RUNTIME))
    if CPU_RUNTIME in have and GPU_RUNTIME in have:
        return [(f"{CPU_RUNTIME} (işlemci sürümü) ekran kartı sürümüyle ({GPU_RUNTIME}) aynı klasörü kullanıyor; "
                 "kaldırılmalı")]
    return []


def dist_files_present(name: str) -> bool:
    """Kurulu dağıtımın kayıtlı yerel kitaplık dosyaları (.pyd, .dll) diskte duruyor mu. Kayıt (dist-info) ile dosyalar
    ayrışabilir: işlemci `onnxruntime`'ı kaldırmak ortak `onnxruntime/` klasörünü siler, ardından DirectML'in zorla
    yeniden kurulması yarıda kalırsa DirectML kaydı kalır ama dosyaları yoktur. RECORD dosyası doğrudan okunur
    (`Distribution.files` Python 3.12'de diskte olmayan dosyaları atlar, eksikliği göstermez). RECORD yoksa ya da yerel
    kitaplık içermiyorsa karar verilemez: tamam sayılır. RECORD okunamıyorsa (erişim, bozuk kodlama ya da CSV) da
    tamam sayılır: denetim her açılışta çökmesin."""
    try:
        dist = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return True
    try:
        record = dist.read_text("RECORD")
        if not record:
            return True
        paths = [row[0] for row in csv.reader(record.splitlines())
                 if row and row[0].lower().endswith((".pyd", ".dll"))]
        return all(dist.locate_file(pth).exists() for pth in paths)
    except (OSError, csv.Error, UnicodeDecodeError):
        return True


def damaged(reqs: list[tuple[str, str | None]], installed: Mapping[str, str],
            platform: str = sys.platform,
            files_present: Callable[[str], bool] = dist_files_present) -> list[str]:
    """Windows'ta istenen `onnxruntime-directml` kayıtlı ama dosyaları eksikse onarım satırı (Türkçe). Başlatıcı bunu
    çakışma gibi çözer (kaldırma boşa geçer, DirectML zorla yeniden kurulur)."""
    if platform != "win32" or GPU_RUNTIME not in {n for n, _ in reqs} or GPU_RUNTIME not in installed:
        return []
    if files_present(GPU_RUNTIME):
        return []
    return [f"{GPU_RUNTIME}: kayıtlı ama dosyaları eksik (kurulum yarım kalmış); yeniden kurulmalı"]


def _installed(names: tuple[str, ...], version: Callable[[str], str] = importlib.metadata.version) -> dict[str, str]:
    """Verilen dağıtımlardan kurulu olanlar (ad → sürüm)."""
    out: dict[str, str] = {}
    for name in names:
        try:
            out[name] = version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    return out


def import_problem(module: str = APP_MODULE) -> str | None:
    """Modül içe aktarılamıyorsa nedeni (Türkçe), aktarılıyorsa None."""
    try:
        importlib.import_module(module)
    except Exception as e:  # noqa: BLE001 — her açılış hatası "ortam eksik" sayılır, başlatıcı yeniden kurar
        return f"{module} açılmıyor: {type(e).__name__}: {e}"
    return None


def main(pyproject: pathlib.Path = PYPROJECT, module: str = APP_MODULE,
         version: Callable[[str], str] = importlib.metadata.version, platform: str = sys.platform,
         files_present: Callable[[str], bool] = dist_files_present) -> int:
    """Çıkış kodu: 0 tamam, 1 eksik/eski/açılmıyor, 3 çakışma ya da yarım DirectML kurulumu (1'den önceliklidir)."""
    reqs = requirements(pyproject, platform=platform)
    found = problems(reqs, version)
    have = _installed((CPU_RUNTIME, GPU_RUNTIME), version)
    clash = [*conflicts(reqs, have, platform), *damaged(reqs, have, platform, files_present)]
    if not found and not clash:                            # paket listesi tamam: uygulama modülü de açılıyor mu
        err = import_problem(module)
        if err:
            found.append(err)
    for line in [*found, *clash]:
        print(line)
    return CONFLICT_EXIT if clash else 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
