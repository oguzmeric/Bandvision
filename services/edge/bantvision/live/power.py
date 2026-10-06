"""Windows güç kısması (EcoQoS) dışında kalma: canlı sayım gerçek zamanlıdır.

Windows 11, ön planda olmayan süreçleri "verimlilik modu"na alıp işlemci hızını düşürebiliyor; arka planda çalışan
analiz sunucusunda tanıma kare başına 65 ms'den ~350 ms'ye çıkıyor, canlı sayım 13'ten 2–3 kare/sn'ye düşüyordu.
Süreç kendini bu kısmadan çıkarır (SetProcessInformation / ProcessPowerThrottling). Sistem ayarı değişmez; yalnızca
bu süreç etkilenir. Windows dışında hiçbir şey yapmaz.
"""
from __future__ import annotations

import ctypes
import sys

_PROCESS_POWER_THROTTLING = 4                    # PROCESS_INFORMATION_CLASS.ProcessPowerThrottling
_EXECUTION_SPEED = 0x1                           # PROCESS_POWER_THROTTLING_EXECUTION_SPEED
_VERSION = 1


class _State(ctypes.Structure):
    _fields_ = [("Version", ctypes.c_ulong), ("ControlMask", ctypes.c_ulong), ("StateMask", ctypes.c_ulong)]


def disable_power_throttling() -> bool:
    """Bu sürecin güç kısmasını kapatır. Başarılıysa True (Windows dışı ya da eski sürümde False)."""
    if sys.platform != "win32":
        return False
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p             # HANDLE işaretçi boyutunda
        kernel32.SetProcessInformation.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
        kernel32.SetProcessInformation.restype = ctypes.c_int
        state = _State(_VERSION, _EXECUTION_SPEED, 0)       # denetim: yürütme hızı; durum 0 = kısma kapalı
        ok = kernel32.SetProcessInformation(kernel32.GetCurrentProcess(), _PROCESS_POWER_THROTTLING,
                                            ctypes.byref(state), ctypes.sizeof(state))
        return bool(ok)
    except (AttributeError, OSError):
        return False
