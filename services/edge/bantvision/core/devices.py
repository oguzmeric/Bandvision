"""Cihazlar: ekran kartı listesi (DXGI), seçim çözümü ve işlemciye düşebilen ONNX oturumu.

- Windows'ta ONNX Runtime DirectML ile NVIDIA / Intel / AMD kartları tek pakette çalışır (onnxruntime-directml).
  Diğer platformlarda ekran kartı listesi boştur ve her şey işlemcide çalışır.
- Kart kimliği `gpu-<satıcı>-<aygıt>` (aynı karttan ikincisi `-2`, ...): DXGI sırası değişse de kayıtlı seçim geçerli
  kalır; oturum açılırken o anki DXGI sırasına çevrilir.
- Seçim "auto" | "cpu" | kart kimliği. Bulunamayan kart / eksik DirectML / açılış ya da çalışma hatası sessizce işlemciye
  düşer; kullanıcıya gösterilecek Türkçe not `Used.note` içindedir (hiçbir düşüş gizlenmez).
- onnxruntime yalnız işlevlerin içinde içe aktarılır (kurulu olmayan ortamda modül yine yüklenir).
"""
from __future__ import annotations

import ctypes
import logging
import os
import re
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("bantvision.devices")

CHOICE_RE = re.compile(r"^(?:auto|cpu|gpu-[0-9a-f]{4}-[0-9a-f]{4}(?:-[0-9]+)?)$")   # fullmatch ile kullanın

CPU_ID = "cpu"
CPU_NAME = "İşlemci"
DML = "DmlExecutionProvider"
CPU_EP = "CPUExecutionProvider"

DXGI_FLAG_SOFTWARE = 2
VENDOR_MICROSOFT = 0x1414
CACHE_TTL_S = 30.0
REASON_MAX = 160

# DXGI ham satırı: (dizin, açıklama, satıcı, aygıt, ayrılmış bellek bayt, bayraklar, luid_high, luid_low)
DxgiRow = tuple[int, str, int, int, int, int, int, int]


@dataclass(frozen=True)
class Gpu:
    id: str
    name: str
    memory_mb: int
    index: int          # DXGI sırası; yalnız içeride (DirectML device_id), API'ye çıkmaz
    luid: str           # "0x<high:08x>_0x<low:08x>"; yalnız içeride (GPU yükü eşlemesi)


@dataclass(frozen=True)
class Used:
    """Gerçekte çalışan cihaz; `id` "cpu" ya da gerçekten çalışan kartın kimliği."""
    kind: str           # "cpu" | "gpu"
    id: str
    name: str
    note: str | None

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "name": self.name, "note": self.note}


def cpu_used(note: str | None = None) -> Used:
    return Used("cpu", CPU_ID, CPU_NAME, note)


def valid_choice(choice: object) -> bool:
    return isinstance(choice, str) and CHOICE_RE.fullmatch(choice) is not None


def _is_windows() -> bool:
    return sys.platform == "win32"


# ---------------------------------------------------------------- DXGI listesi

def _dxgi_rows() -> list[DxgiRow]:
    """Windows DXGI: IDXGIFactory1::EnumAdapters1 + IDXGIAdapter1::GetDesc1 (ctypes). Her COM nesnesi (fabrika dahil)
    Release edilir; hata fırlatabilir (çağıran yutar)."""
    from ctypes import wintypes

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class DESC1(ctypes.Structure):
        _fields_ = [("Description", wintypes.WCHAR * 128), ("VendorId", wintypes.UINT),
                    ("DeviceId", wintypes.UINT), ("SubSysId", wintypes.UINT), ("Revision", wintypes.UINT),
                    ("DedicatedVideoMemory", ctypes.c_size_t), ("DedicatedSystemMemory", ctypes.c_size_t),
                    ("SharedSystemMemory", ctypes.c_size_t), ("AdapterLuid", LUID), ("Flags", wintypes.UINT)]

    class GUID(ctypes.Structure):
        _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD),
                    ("d4", ctypes.c_ubyte * 8)]

    def vtable(obj: ctypes.c_void_p) -> Any:
        return ctypes.cast(ctypes.cast(obj, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))

    release_t = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)       # IUnknown::Release = vtable[2]

    import uuid
    u = uuid.UUID("770aae78-f26f-4dba-a829-253c83d1b387")                  # IID_IDXGIFactory1
    iid = GUID(u.fields[0], u.fields[1], u.fields[2])
    for i, b in enumerate(u.bytes[8:]):
        iid.d4[i] = b

    dxgi = ctypes.WinDLL("dxgi")
    factory = ctypes.c_void_p()
    hr = dxgi.CreateDXGIFactory1(ctypes.byref(iid), ctypes.byref(factory))
    if hr != 0 or not factory.value:
        raise OSError(f"CreateDXGIFactory1 başarısız (0x{hr & 0xFFFFFFFF:08x})")
    rows: list[DxgiRow] = []
    fvt = vtable(factory)
    try:
        enum_adapters1 = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.UINT,
                                            ctypes.POINTER(ctypes.c_void_p))(fvt[12])
        for i in range(64):                                                 # üst sınır: sonsuz döngü olmasın
            adapter = ctypes.c_void_p()
            if enum_adapters1(factory, i, ctypes.byref(adapter)) != 0 or not adapter.value:
                break
            avt = vtable(adapter)
            try:
                get_desc1 = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(DESC1))(avt[10])
                d = DESC1()
                if get_desc1(adapter, ctypes.byref(d)) == 0:
                    rows.append((i, d.Description, d.VendorId, d.DeviceId, d.DedicatedVideoMemory, d.Flags,
                                 d.AdapterLuid.HighPart, d.AdapterLuid.LowPart))
            finally:
                release_t(avt[2])(adapter)
    finally:
        release_t(fvt[2])(factory)
    return rows


def _gpus_from_rows(rows: Sequence[DxgiRow]) -> list[Gpu]:
    """Yazılım (WARP / Microsoft Basic Render) bağdaştırıcıları atlanır; kimlik çakışmaları DXGI sırasıyla -2, -3."""
    gpus: list[Gpu] = []
    seen: dict[str, int] = {}
    for index, desc, vendor, device, dedicated, flags, luid_high, luid_low in rows:
        if flags & DXGI_FLAG_SOFTWARE or vendor == VENDOR_MICROSOFT:
            continue
        base = f"gpu-{vendor:04x}-{device:04x}"
        seen[base] = seen.get(base, 0) + 1
        gid = base if seen[base] == 1 else f"{base}-{seen[base]}"
        gpus.append(Gpu(gid, desc.strip(), dedicated // 2**20, index,
                        f"0x{luid_high & 0xFFFFFFFF:08x}_0x{luid_low & 0xFFFFFFFF:08x}"))
    return gpus


_cache_lock = threading.Lock()
_cache: tuple[float, list[Gpu]] | None = None
_dxgi_warned = False


def list_gpus(*, refresh: bool = False, _enum: Callable[[], list[DxgiRow]] | None = None) -> list[Gpu]:
    """Ekran kartları (yazılım bağdaştırıcılar hariç), 30 sn önbellekli. Windows dışı ya da DXGI hatasında boş liste
    (hata bir kez uyarı olarak günlüğe yazılır). `_enum` yalnız test içindir ve önbelleği kullanmaz."""
    global _cache, _dxgi_warned
    if _enum is not None:
        return _gpus_from_rows(_enum())
    if not _is_windows():
        return []
    with _cache_lock:
        now = time.monotonic()
        if not refresh and _cache is not None and now - _cache[0] < CACHE_TTL_S:
            return list(_cache[1])
        try:
            gpus = _gpus_from_rows(_dxgi_rows())
        except Exception:
            if not _dxgi_warned:
                _dxgi_warned = True
                log.warning("DXGI ekran kartı listesi alınamadı; ekran kartı yok sayılıyor", exc_info=True)
            gpus = []
        _cache = (now, gpus)
        return list(gpus)


# ---------------------------------------------------------------- destek ve seçim

def _import_ort() -> Any:
    import onnxruntime
    return onnxruntime


_dml_warned = False


def dml_available(*, _ort: Any = None) -> bool:
    """R4: DirectML sağlayıcısı onnxruntime'da var mı? onnxruntime yüklenemez ya da sağlayıcı sorgusu hata verirse
    False (hatanın türü ve iletisi bir kez uyarı olarak günlüğe yazılır)."""
    global _dml_warned
    try:
        ort = _ort if _ort is not None else _import_ort()
        return DML in ort.get_available_providers()
    except Exception as e:  # noqa: BLE001 — onnxruntime yüklenemiyor ya da bozuk: DirectML yok say
        if not _dml_warned:
            _dml_warned = True
            log.warning("DirectML sorgulanamadı, ekran kartı yok sayılıyor: %s: %s", type(e).__name__, e)
        return False


def _n1() -> str:
    if not _is_windows():
        return "Ekran kartı desteği yalnız Windows'ta var; işlemci kullanılıyor."
    return "Ekran kartı desteği kurulu değil (onnxruntime-directml); işlemci kullanılıyor."


def gpu_support(*, _ort: Any = None) -> tuple[bool, str | None]:
    """(kullanılabilir, neden): neden N1'in "; işlemci kullanılıyor." öncesi kısmıdır."""
    if not _is_windows():
        return False, "Ekran kartı desteği yalnız Windows'ta var"
    if not dml_available(_ort=_ort):
        return False, "Ekran kartı desteği kurulu değil (onnxruntime-directml)"
    return True, None


def _best(gpus: Sequence[Gpu]) -> Gpu | None:
    """En büyük bellek; eşitlikte en küçük DXGI sırası."""
    return min(gpus, key=lambda g: (-g.memory_mb, g.index), default=None)


def auto_choice(gpus: Sequence[Gpu] | None = None, *, _ort: Any = None) -> str:
    gpus = list_gpus() if gpus is None else gpus
    best = _best(gpus)
    if best is None or not dml_available(_ort=_ort):
        return CPU_ID
    return best.id


def resolve(choice: str, gpus: Sequence[Gpu] | None = None, *, _ort: Any = None) -> tuple[Gpu | None, str | None]:
    """Seçimi çözer: (kullanılacak kart ya da işlemci için None, not). "cpu" ve ekran kartı olmadığı için işlemciye
    çözülen "auto" nottan muaftır (beklenen sonuç)."""
    if choice == CPU_ID:
        return None, None
    gpus = list_gpus() if gpus is None else gpus
    if choice == "auto":
        best = _best(gpus)
        if best is None or not dml_available(_ort=_ort):
            return None, None
        return best, None
    if not dml_available(_ort=_ort):
        return None, _n1()
    for g in gpus:
        if g.id == choice:
            return g, None
    return None, "Seçilen ekran kartı bulunamadı; işlemci kullanılıyor."


# ---------------------------------------------------------------- varsayılan seçim

_default_lock = threading.Lock()
_default_choice = CPU_ID


def default_choice() -> str:
    """Model sınıflarının `device=None` iken kullandığı süreç varsayılanı; başlangıçta "cpu"."""
    with _default_lock:
        return _default_choice


def set_default_choice(choice: str) -> None:
    global _default_choice
    if not valid_choice(choice):
        raise ValueError(f"Geçersiz cihaz seçimi: {choice!r}")
    with _default_lock:
        _default_choice = choice


# ---------------------------------------------------------------- oturum

def _reason(e: BaseException) -> str:
    """Hatanın ilk (boş olmayan) satırı, en çok 160 karakter; kullanıcıya gösterilen nota girer."""
    for line in str(e).splitlines():
        line = line.strip()
        if line:
            return line[:REASON_MAX]
    return type(e).__name__


def _n3(reason: str) -> str:
    return f"Ekran kartında açılamadı ({reason}); işlemci kullanılıyor."


def _n4(reason: str) -> str:
    return f"Ekran kartı çalışırken hata verdi ({reason}); işlemci kullanılıyor."


def _cpu_session(ort: Any, path: str, configure: Callable[[Any], None]) -> Any:
    so = ort.SessionOptions()
    configure(so)
    return ort.InferenceSession(path, so, providers=[CPU_EP])


def _gpu_session(ort: Any, path: str, configure: Callable[[Any], None], gpu: Gpu) -> Any:
    so = ort.SessionOptions()
    configure(so)
    so.enable_mem_pattern = False                         # DirectML şartı
    so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL  # DirectML şartı
    return ort.InferenceSession(path, so, providers=[(DML, {"device_id": gpu.index}), CPU_EP])


class GuardedSession:
    """ONNX oturumu sarmalayıcısı: ekran kartında çalışırken hata çıkarsa (sürücü sıfırlanması, kart kapanması)
    aynı model işlemcide yeniden kurulur, aynı çağrı yeniden denenir ve `used` N4 notunu alır. Düştükten sonra
    kendiliğinden ekran kartına dönmez. İşlemci oturumunun hataları aynen yayılır."""

    def __init__(self, ort: Any, path: str, configure: Callable[[Any], None], session: Any, used: Used) -> None:
        self._ort = ort
        self._path = path
        self._configure = configure
        self._lock = threading.Lock()
        self._broken: str | None = None                       # işlemci yeniden kurulumu da başarısız: kalıcı hata
        self._state: tuple[Any, Used] = (session, used)       # tek atamayla değişir: oturum ve used birlikte

    @property
    def used(self) -> Used:
        return self._state[1]

    @property
    def broken(self) -> str | None:
        """Kalıcı hata (ekran kartı hata verdi, işlemci oturumu da kurulamadı): kullanıcıya gösterilecek Türkçe ileti;
        oturum çalışıyorsa None."""
        return None if self._broken is None else str(self._broken_error())

    def get_inputs(self) -> list[Any]:
        return self._state[0].get_inputs()

    def get_outputs(self) -> list[Any]:
        return self._state[0].get_outputs()

    def _broken_error(self) -> RuntimeError:
        return RuntimeError(f"Model kullanılamıyor: ekran kartı hata verdi ve işlemci oturumu kurulamadı "
                            f"({self._broken})")

    def run(self, output_names: Any, feeds: Mapping[str, Any]) -> Any:
        if self._broken is not None:                          # kalıcı hata: yeniden deneme ve günlük seli yok
            raise self._broken_error()
        state = self._state
        session, used = state
        try:
            return session.run(output_names, feeds)
        except Exception as e:
            if used.kind != "gpu":
                raise
            if self._broken is not None:                      # başka bir çağrı yeniden kurulumu zaten bozdu
                raise self._broken_error() from None
            log.exception("Ekran kartında çalışırken hata; işlemciye geçiliyor (%s)", used.name)
            reason = _reason(e)
        with self._lock:
            if self._broken is not None:
                raise self._broken_error()
            if self._state is state:                          # başka bir çağrı zaten düşürmediyse
                try:
                    cpu = _cpu_session(self._ort, self._path, self._configure)
                except Exception as e2:
                    self._broken = _reason(e2)
                    log.exception("İşlemci oturumu kurulamadı; model kullanılamıyor")
                    raise
                self._state = (cpu, cpu_used(_n4(reason)))
            session = self._state[0]
        return session.run(output_names, feeds)


def open_session(model_path: str | os.PathLike[str], configure: Callable[[Any], None], choice: str, *,
                 _ort: Any = None, _gpus: Sequence[Gpu] | None = None) -> GuardedSession:
    """Seçimi çözüp oturumu açar. `configure(so)` çağıranın kendi seçeneklerini taze bir `SessionOptions`'a uygular;
    her deneme (işlemciye düşüş dahil) için yeni seçenek kurulur. Ekran kartı oturumu açılamazsa ya da ONNX Runtime
    sessizce işlemciye düşerse (get_providers()[0] DirectML değil) işlemci oturumu + N3 notu döner."""
    ort = _ort if _ort is not None else _import_ort()
    path = os.fspath(model_path)
    if _gpus is not None:
        gpus = _gpus
    else:
        gpus = [] if choice == CPU_ID else list_gpus()        # "cpu" iken DXGI hiç sorgulanmaz
    gpu, note = resolve(choice, gpus, _ort=ort)
    if gpu is None:
        return GuardedSession(ort, path, configure, _cpu_session(ort, path, configure), cpu_used(note))
    providers: list[str] | None = None
    try:
        session = _gpu_session(ort, path, configure, gpu)
        providers = list(session.get_providers())
        if not providers or providers[0] != DML:
            raise RuntimeError("DirectML etkinleşmedi")
    except Exception as e:
        log.exception("Ekran kartı oturumu açılamadı (%s); işlemci kullanılıyor (ONNX Runtime'ın bildirdiği "
                      "sağlayıcılar: %s)", gpu.name, providers)
        cpu = _cpu_session(ort, path, configure)
        return GuardedSession(ort, path, configure, cpu, cpu_used(_n3(_reason(e))))
    return GuardedSession(ort, path, configure, session, Used("gpu", gpu.id, gpu.name, None))
