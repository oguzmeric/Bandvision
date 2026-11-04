"""Ağ akışı açılışlarının öncelikli sırası.

OpenCV'nin FFmpeg arka ucu bir süreçteki tüm açılışları (bağlanma + akış bilgisi) tek bir genel kilitle sırayla yapar.
Kapalı kanal açılırken (zaman aşımına dek) aynı süreçteki her açılış bekler: izleme duvarında çok sayıda sinyalsiz
kanal sürekli yeniden denenince sayım/güvenlik oturumunun kamerası sıra hiç alamıyordu. Kilit zaten tek; bu kapı
sırayı biz belirleriz: analiz oturumu önce, izleme sonra, son denemesi görüntü vermemiş izleme en son. Böylece bir
analiz oturumu en çok bir açılış süresi bekler.

Öncelik açılışı yapan iş parçacığına ipucu olarak verilir (`priority(...)`): izleme okuyucusunun açıcısı
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
RETRY = 2            # izleme: son denemesi görüntü vermedi (kapalı / sinyalsiz kanal olabilir)

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
    """Tek tutuculu kapı: bekleyenler önceliğe (küçük önce), eşitse geliş sırasına göre girer."""

    def __init__(self) -> None:
        self._cv = threading.Condition()
        self._queue: list[tuple[int, int]] = []
        self._order = itertools.count()
        self._busy = False

    @contextlib.contextmanager
    def hold(self, level: int) -> Iterator[None]:
        ticket = (level, next(self._order))
        with self._cv:
            heapq.heappush(self._queue, ticket)
            try:
                while self._busy or self._queue[0] != ticket:
                    self._cv.wait()
            except BaseException:
                self._queue.remove(ticket)
                heapq.heapify(self._queue)
                self._cv.notify_all()
                raise
            heapq.heappop(self._queue)
            self._busy = True
        try:
            yield
        finally:
            with self._cv:
                self._busy = False
                self._cv.notify_all()

    def waiting(self) -> int:
        with self._cv:
            return len(self._queue)


GATE = OpenGate()
