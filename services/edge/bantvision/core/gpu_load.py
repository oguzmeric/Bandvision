"""Ekran kartı yükü: Windows performans sayaçları (PDH) `\\GPU Engine(*)\\Utilization Percentage` (ctypes).

- Görev Yöneticisi ile aynı hesap: aynı karta ve aynı motora (`luid_..._phys_N_eng_M`) ait süreçlerin değerleri toplanır,
  motorlar arasında en büyüğü alınır, 100'e kısılır (`aggregate`, saf işlev).
- Windows dışında `GpuLoad.percent` hep None döner ve hiçbir Windows modülü içe aktarılmaz. PDH'nin herhangi bir hatası
  (sayaç yok, kütüphane yok, okuma hatası) None verir; uyarı günlüğe bir kez yazılır, durum ucu yine çalışır.
- Sayaç bir oran sayacıdır: iki toplama arasındaki farkı ölçer. Süreç boyunca tek sorgu açık kalır; ilk çağrı 100 ms arayla
  iki kez toplar, sonrakiler bir kez toplayıp bir önceki çağrıdan bu yana değeri verir.
"""
from __future__ import annotations

import logging
import re
import sys
import threading
import time
from collections.abc import Callable, Iterable
from typing import Protocol

log = logging.getLogger("bantvision.gpu_load")

COUNTER_PATH = r"\GPU Engine(*)\Utilization Percentage"
FIRST_SAMPLE_GAP_S = 0.1
RETRY_AFTER_S = 30.0            # PDH hatasından sonra bu kadar süre yeniden denenmez (uyarı yine bir kez yazılır)
REUSE_WINDOW_S = 0.5            # bu kadar yakın ikinci çağrı aynı örneği kullanır (çok kısa aralıkta oran gürültülüdür)

PDH_FMT_DOUBLE = 0x00000200
PDH_MORE_DATA = 0x800007D2
PDH_CSTATUS_VALID_DATA = 0x0
PDH_CSTATUS_NEW_DATA = 0x1

_INSTANCE_RE = re.compile(r"luid_(0x[0-9a-f]{8})_(0x[0-9a-f]{8})_phys_(\d+)_eng_(\d+)", re.IGNORECASE)


def aggregate(samples: Iterable[tuple[str, float]], luid: str) -> float | None:
    """(örnek adı, değer) çiftlerinden `luid` kartının yükü. Aynı motorda (phys, eng) süreçler toplanır, motorlar arasında
    en büyüğü alınır, 0..100'e kısılır. Kartın hiç örneği yoksa None. LUID büyük/küçük harf duyarsız (PDH adları büyük
    harfle yazar: `luid_0x00000000_0x000132D5`); `luid` "0x<high:08x>_0x<low:08x>" biçimindedir."""
    want = luid.lower()
    engines: dict[tuple[str, str], float] = {}
    for name, value in samples:
        m = _INSTANCE_RE.search(name)
        if m is None or f"{m.group(1)}_{m.group(2)}".lower() != want:
            continue
        key = (m.group(3), m.group(4))
        engines[key] = engines.get(key, 0.0) + float(value)
    if not engines:
        return None
    return min(100.0, max(0.0, max(engines.values())))


class PdhBackend(Protocol):
    def collect(self) -> None: ...
    def read(self) -> list[tuple[str, float]]: ...
    def close(self) -> None: ...


class _Pdh:
    """Gerçek PDH sorgusu (yalnız Windows). Hata fırlatabilir; `GpuLoad` yutar."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        class Item(ctypes.Structure):                                   # PDH_FMT_COUNTERVALUE_ITEM_W (double kipi)
            _fields_ = [("name", ctypes.c_void_p), ("status", wintypes.DWORD), ("value", ctypes.c_double)]

        self._ct, self._item = ctypes, Item
        pdh = ctypes.WinDLL("pdh")
        vp, dw = ctypes.c_void_p, wintypes.DWORD
        pdh.PdhOpenQueryW.argtypes = [wintypes.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(vp)]
        pdh.PdhAddEnglishCounterW.argtypes = [vp, wintypes.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(vp)]
        pdh.PdhCollectQueryData.argtypes = [vp]
        pdh.PdhGetFormattedCounterArrayW.argtypes = [vp, dw, ctypes.POINTER(dw), ctypes.POINTER(dw), vp]
        pdh.PdhCloseQuery.argtypes = [vp]
        for fn in (pdh.PdhOpenQueryW, pdh.PdhAddEnglishCounterW, pdh.PdhCollectQueryData,
                   pdh.PdhGetFormattedCounterArrayW, pdh.PdhCloseQuery):
            fn.restype = dw
        self._pdh = pdh
        self._query, self._counter = vp(), vp()
        self._check(pdh.PdhOpenQueryW(None, 0, ctypes.byref(self._query)), "PdhOpenQueryW")
        try:
            self._check(pdh.PdhAddEnglishCounterW(self._query, COUNTER_PATH, 0, ctypes.byref(self._counter)),
                        "PdhAddEnglishCounterW")
        except Exception:
            pdh.PdhCloseQuery(self._query)
            raise

    @staticmethod
    def _check(status: int, what: str) -> None:
        if status != 0:
            raise OSError(f"{what} başarısız (0x{status & 0xFFFFFFFF:08x})")

    def collect(self) -> None:
        self._check(self._pdh.PdhCollectQueryData(self._query), "PdhCollectQueryData")

    def read(self) -> list[tuple[str, float]]:
        from ctypes import wintypes
        ct = self._ct
        size, count = wintypes.DWORD(0), wintypes.DWORD(0)
        status = self._pdh.PdhGetFormattedCounterArrayW(self._counter, PDH_FMT_DOUBLE, ct.byref(size), ct.byref(count),
                                                        None)
        for _ in range(3):                                               # örnek sayısı iki çağrı arasında büyüyebilir
            if status != PDH_MORE_DATA:
                break
            buf = ct.create_string_buffer(size.value)                    # Python'a ait arabellek: ayrıca serbest bırakılmaz
            status = self._pdh.PdhGetFormattedCounterArrayW(self._counter, PDH_FMT_DOUBLE, ct.byref(size),
                                                            ct.byref(count), ct.cast(buf, ct.c_void_p))
            if status == 0:
                items = ct.cast(buf, ct.POINTER(self._item))
                out: list[tuple[str, float]] = []
                for i in range(count.value):
                    it = items[i]
                    if it.name and it.status in (PDH_CSTATUS_VALID_DATA, PDH_CSTATUS_NEW_DATA):
                        out.append((ct.wstring_at(it.name), float(it.value)))
                return out
        if status == 0:
            return []                                                    # hiç örnek yok (count == 0)
        self._check(status, "PdhGetFormattedCounterArrayW")
        return []

    def close(self) -> None:
        self._pdh.PdhCloseQuery(self._query)


class GpuLoad:
    """Süreç başına tek örnek: `percent(luid)` kartın yükünü (0..100) ya da bilinmiyorsa None verir. Eşzamanlı çağrılar
    (durum ucu iş parçacığı havuzunda koşar) kilitle sıralanır."""

    def __init__(self, *, _backend_factory: Callable[[], PdhBackend] | None = None,
                 _clock: Callable[[], float] = time.monotonic, _sleep: Callable[[float], None] = time.sleep) -> None:
        self._factory = _backend_factory
        self._clock, self._sleep = _clock, _sleep
        self._lock = threading.Lock()
        self._backend: PdhBackend | None = None
        self._retry_at = 0.0
        self._warned = False
        self._closed = False
        self._samples: list[tuple[str, float]] = []
        self._at = 0.0
        self._have = False

    def percent(self, luid: str) -> float | None:
        if self._factory is None and sys.platform != "win32":
            return None
        with self._lock:
            if self._closed or self._clock() < self._retry_at:
                return None
            try:
                samples = self._latest()
            except Exception as e:  # noqa: BLE001 — PDH hatası durum ucunu bozmaz; yük bilinmiyor
                self._fail(e)
                return None
            return aggregate(samples, luid)

    def _latest(self) -> list[tuple[str, float]]:
        if self._backend is None:
            factory = self._factory if self._factory is not None else _Pdh
            self._backend = factory()
        now = self._clock()
        if self._have and now - self._at < REUSE_WINDOW_S:
            return self._samples
        self._backend.collect()
        if not self._have:                                               # oran sayacı: ilk örnek için iki toplama
            self._sleep(FIRST_SAMPLE_GAP_S)
            self._backend.collect()
        self._samples = self._backend.read()
        self._at, self._have = self._clock(), True
        return self._samples

    def _fail(self, e: Exception) -> None:
        self._retry_at = self._clock() + RETRY_AFTER_S
        self._have = False
        if not self._warned:
            self._warned = True
            log.warning("Ekran kartı yükü okunamadı (%s: %s); yük gösterilmeyecek", type(e).__name__, e)
        backend, self._backend = self._backend, None
        if backend is not None:
            try:
                backend.close()
            except Exception:
                log.debug("PDH sorgusu kapatılamadı", exc_info=True)

    def close(self) -> None:
        with self._lock:
            backend, self._backend = self._backend, None
            self._closed = True
        if backend is not None:
            try:
                backend.close()
            except Exception:
                log.debug("PDH sorgusu kapatılamadı", exc_info=True)

