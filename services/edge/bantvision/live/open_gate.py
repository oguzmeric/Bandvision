"""Ağ akışı açılışlarının öncelikli sırası.

OpenCV'nin FFmpeg arka ucu bir süreçteki tüm açılışları (bağlanma + akış bilgisi) tek bir genel kilitle sırayla yapar.
Kapalı kanal açılırken (zaman aşımına dek) aynı süreçteki her açılış bekler: izleme duvarında çok sayıda sinyalsiz
kanal sürekli yeniden denenince sayım/güvenlik oturumunun kamerası sıra hiç alamıyordu. Kilit zaten tek; bu kapı
sırayı biz belirleriz:
1. analiz oturumu (ilk deneme ya da son denemesi görüntü verdi);
2. izleme ve küçük resim (aynı koşulla);
3. görüntü vermemiş analiz oturumu (kapalı kamerada gece boyu bekleyen güvenlik oturumu duvarı tıkamasın);
4. görüntü vermemiş izleme okuyucusu.

Adres (TRASSIR'da ~10 sn geçerli jeton) kapıya girdikten SONRA alınır: kuyrukta beklerken jeton dolmasın. Bunun için
çağıran `GATE.hold(...)` içinde adresi alıp açar; kapı aynı iş parçacığında iç içe girilebilir (`open_capture` yine
kapıdan geçer).

Öncelik açılışı yapan iş parçacığına ipucu olarak da verilebilir (`priority(...)`): izleme okuyucusunun açıcısı
değiştirilebilir (testler sahte açıcı verir) ve imzası değişmez.
"""
from __future__ import annotations

import contextlib
import heapq
import itertools
import threading
from collections.abc import Iterator

SESSION = 0          # sayım / güvenlik oturumu
VIEWER = 1           # izleme (ilk deneme ya da son denemesi görüntü verdi), anlık görüntü
SESSION_RETRY = 2    # oturum: son denemesi görüntü vermedi
RETRY = 3            # izleme: son denemesi görüntü vermedi (kapalı / sinyalsiz kanal olabilir)

_hint = threading.local()


@contextlib.contextmanager
def priority(level: int) -> Iterator[None]:
    """Bu iş parçacığında yapılacak açılışların önceliği (blok süresince)."""
    old = getattr(_hint, "level", None)
    _hint.level = level
    try:
        yield
    finally:
        _hint.level = old


def current_priority() -> int:
    level = getattr(_hint, "level", None)
    return VIEWER if level is None else level


class OpenGate:
    """Tek tutuculu kapı: bekleyenler önceliğe (küçük önce), eşitse geliş sırasına göre girer. Tutan iş parçacığı
    kapıya yeniden girebilir (sıraya girmez)."""

    def __init__(self) -> None:
        self._cv = threading.Condition()
        self._queue: list[tuple[int, int]] = []
        self._order = itertools.count()
        self._owner: int | None = None
        self._depth = 0

    @contextlib.contextmanager
    def hold(self, level: int) -> Iterator[None]:
        me = threading.get_ident()
        with self._cv:
            if self._owner == me:
                self._depth += 1
            else:
                ticket = (level, next(self._order))
                heapq.heappush(self._queue, ticket)
                try:
                    while self._owner is not None or self._queue[0] != ticket:
                        self._cv.wait()
                except BaseException:
                    self._queue.remove(ticket)
                    heapq.heapify(self._queue)
                    self._cv.notify_all()
                    raise
                heapq.heappop(self._queue)
                self._owner, self._depth = me, 1
        try:
            yield
        finally:
            with self._cv:
                self._depth -= 1
                if self._depth == 0:
                    self._owner = None
                    self._cv.notify_all()

    def waiting(self) -> int:
        with self._cv:
            return len(self._queue)

    def held_by_current_thread(self) -> bool:
        with self._cv:
            return self._owner == threading.get_ident()


GATE = OpenGate()
