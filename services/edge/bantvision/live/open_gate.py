"""Ağ akışı açılışlarının öncelikli sırası.

OpenCV'nin FFmpeg arka ucu bir süreçteki tüm açılışları (bağlanma + akış bilgisi) tek bir genel kilitle sırayla yapar.
Kapalı kanal açılırken (zaman aşımına dek) aynı süreçteki her açılış bekler: izleme duvarında çok sayıda sinyalsiz
kanal sürekli yeniden denenince sayım/güvenlik oturumunun kamerası sıra hiç alamıyordu. Kilit zaten tek; bu kapı
sırayı biz belirleriz:
1. analiz oturumu (ilk deneme ya da son denemesi görüntü verdi);
2. izleme ve küçük resim (aynı koşulla);
3. görüntü vermemiş analiz oturumu (kapalı kamerada gece boyu bekleyen güvenlik oturumu duvarı tıkamasın);
4. görüntü vermemiş izleme okuyucusu.

Adres (TRASSIR'da ~10 sn geçerli jeton) önce kapı dışında alınır, kuyrukta uzun beklendiyse kapı içinde tazelenir
(`resolve_and_open`): ulaşılamayan kayıt cihazının HTTP zaman aşımı sırayı tutmaz, jeton da kuyrukta dolmaz. Kapı aynı
iş parçacığında iç içe girilebilir (`open_capture` yine kapıdan geçer).

Öncelik açılışı yapan iş parçacığına ipucu olarak da verilebilir (`priority(...)`): izleme okuyucusunun açıcısı
değiştirilebilir (testler sahte açıcı verir) ve imzası değişmez.
"""
from __future__ import annotations

import contextlib
import heapq
import itertools
import threading
import time
from collections.abc import Callable, Iterator
from typing import TypeVar

T = TypeVar("T")

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

FRESH_URL_S = 5.0    # kuyrukta bundan uzun beklendiyse adres (jeton) kapı içinde yeniden alınır


def is_network(url: str) -> bool:
    return url.lower().startswith(("rtsp://", "http://", "https://"))


class UrlError(Exception):
    """Adres alınamadı (kayıt cihazı yanıt vermedi): asıl hata `__cause__`'da; açıcının hatası bununla sarılmaz."""


def _url(open_url: Callable[[], str]) -> str:
    try:
        return open_url()
    except Exception as e:
        raise UrlError(str(e)) from e


SUB_FALLBACK_MSG = "Alt akış görüntü vermiyor; ana akış kullanılıyor."


class StreamUrl:
    """Kayıt cihazı kanalının adres üreticisi (alt akış istenmişse ana akışa düşebilir).

    Bazı kanallarda alt akış "açılır" ama hiç kare vermez (kayıt cihazı yine alt akış var der). Okuyucu bir alt akış
    denemesi açılıp 0 kare verince sonraki denemeyi `prefer_main=True` ile yapar; ana akış kare verirse
    `mark_sub_dead()` çağırır ve kanal bir süre (yönetici belleği) doğrudan ana akışla açılır. `sub_dead` her çağrıda
    sorulur: işaret yeni bağlanışta etkili olur, okuyucu/oturum yeniden kurulmaz.

    `make(alt_istendi_mi) -> (adres, kanalın alt akışı var mı)`; düz `Callable[[], str]` gibi de çağrılabilir."""

    def __init__(self, make: Callable[[bool], tuple[str, bool]], sub: bool, sub_dead: Callable[[], bool],
                 mark_sub_dead: Callable[[], None]) -> None:
        self._make, self.sub, self._sub_dead, self._mark = make, sub, sub_dead, mark_sub_dead

    def resolve(self, prefer_main: bool = False) -> tuple[str, bool, bool]:
        """(adres, alt akış mı, alt akış istendiği halde ana akışa düşüldü mü)."""
        want_sub = self.sub and not prefer_main and not self._sub_dead()
        url, has_sub = self._make(want_sub)
        return url, want_sub and has_sub, self.sub and has_sub and not want_sub

    def __call__(self, prefer_main: bool = False) -> str:
        return self.resolve(prefer_main)[0]

    def bind(self, prefer_main: bool) -> BoundUrl:
        return BoundUrl(self, prefer_main)

    def mark_sub_dead(self) -> None:
        self._mark()


class BoundUrl:
    """Bir bağlantı denemesinin adres üreticisi: son alınan adres alt akış mı (`sub`), ana akışa düşüldü mü
    (`fell_back`)."""

    def __init__(self, owner: StreamUrl, prefer_main: bool) -> None:
        self.owner, self.prefer_main = owner, prefer_main
        self.sub = False
        self.fell_back = False

    def __call__(self) -> str:
        url, self.sub, self.fell_back = self.owner.resolve(self.prefer_main)
        return url


def resolve_and_open(open_url: Callable[[], str], open_fn: Callable[[str], T], level: int,
                     clock: Callable[[], float] = time.monotonic) -> tuple[str, T]:
    """Adresi al ve aç: (adres, açılan). Adres önce kapı DIŞINDA alınır (ulaşılamayan kayıt cihazının HTTP zaman aşımı
    sırayı tutmaz); kuyrukta FRESH_URL_S'den uzun beklendiyse sıra gelince yeniden alınır (TRASSIR jetonu ~10 sn).
    Dosya kaynağı kapıya girmez. Adres hatası `UrlError` olur; açıcının hatası olduğu gibi geçer."""
    url = _url(open_url)
    if not is_network(url):
        return url, open_fn(url)
    asked = clock()
    with GATE.hold(level), priority(level):
        if clock() - asked > FRESH_URL_S:
            url = _url(open_url)
        return url, open_fn(url)
