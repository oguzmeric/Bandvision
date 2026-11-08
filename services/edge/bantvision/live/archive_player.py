"""Kayıttan izleme: arşiv oynatıcısı (`ArchivePlayer`) ve yöneticisi (`ArchiveManager`).

Bağdaştırıcılar `archive.py`'dedir; burası oynatma iş parçacığı, sınırlar ve önbellektir (plan R1–R5, R9).

- Tek kumanda yolu (R1): duraklat, sürdür, sar ve hız değişimi okumayı durdurur, yakalamayı kapatır (`archive.stop`
  ile; TRASSIR'da `archive_command stop`), yeni konum/hızla yeniden açar (yeni `stream_url`, yeni jeton). Duraklamada
  son kare ve `at` sabit kalır. Durumlar: `connecting | playing | paused | ended | error`.
- Konum (R2): `at = start + okunan / fps × hız`, `fps = CAP_PROP_FPS` (0 ya da > 120 ise 25). Hızı cihazda olmayan
  bağdaştırıcıda (`16 not in speeds`: Hikvision/Dahua/dosya) her kare çözülür, `hız`. karede bir yayımlanır; konum
  çözülen kareden (`okunan / fps`, yani yayımlanan / fps × hız). TRASSIR'da (`device_paced`) her kare yayımlanır.
- Sınırlar (R3): en çok MAX_PLAYERS oynatıcı (`TooManyPlayers`); IDLE_S boyunca sorulmayan oynatıcı kapanır (temizlik
  iş parçacığı REAP_EVERY_S'de bir, ilk açılışta başlar); NO_FRAME_S kare gelmezse `error` (kendiliğinden yeniden
  bağlanmaz, `resume()` yeniden dener); aynı anda tek dışa aktarma (`ExportBusy`).
- Açılış (R4) `open_gate.resolve_and_open(..., VIEWER)`; kare 960 px'e küçülür ve salt okunurdur.
- Takvim/çizelge (R5) kaynak başına kilitle sıralanır (TRASSIR `archive_status` jetonsuz) ve CACHE_S önbellekte;
  hata önbelleğe girmez.
- Dosya kaynağı (R9, yalnız `ANALYZER_ALLOW_FILE_SOURCES=1`): açılışta `CAP_PROP_POS_MSEC` ile konuma sarılır, gerçek
  zamanlı oynar; zaman ekseni dosya saniyesidir.

Şifre ve jeton günlüğe yazılmaz; `archive.stop`/`keep_alive`'a kimliksiz adres verilir.
"""
from __future__ import annotations

import contextlib
import logging
import os
import pathlib
import re
import threading
import time
import unicodedata
import urllib.parse
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, Self

import cv2
import numpy as np

from bantvision.live import open_gate
from bantvision.live.archive import ArchiveClient, FileArchive, make_archive
from bantvision.live.recorders import (
    RecorderBrand,
    RecorderChannel,
    RecorderClient,
    RecorderError,
    with_credentials,
)
from bantvision.live.viewer import MAX_WIDTH, _readonly, downscale
from bantvision.live.viewer import _detail as _viewer_detail

__all__ = [
    "ArchiveManager",
    "ArchivePlayer",
    "ChannelNotFound",
    "ExportBusy",
    "ManagerStopped",
    "MissingChannel",
    "NoArchive",
    "PlayerView",
    "SourceMissing",
    "TooManyPlayers",
    "UnsupportedSpeed",
    "file_source_path",
]

_LOG = logging.getLogger(__name__)

MAX_PLAYERS = 2
IDLE_S = 60.0
NO_FRAME_S = 20.0
CACHE_S = 60.0
REAP_EVERY_S = 10.0
KEEP_ALIVE_S = 5.0
DEAD_READ_S = 5.0           # ağ akışında `read` False son kareden bu kadar sonra geldiyse cihaz sustu (error), önce ise bitti
CLOSE_WAIT_S = 3.0
SWEEP_WAIT_S = 0.5
DEFAULT_FPS = 25.0
MAX_FPS = 120.0

TOO_MANY_MSG = "En çok 2 kayıt aynı anda izlenebilir."
EXPORT_BUSY_MSG = "Bir dışa aktarma sürüyor."
NO_FRAME_MSG = "Kayıt cihazından görüntü gelmedi."
OPEN_FAILED_MSG = "Kayıt açılamadı."
READ_FAILED_MSG = "Kayıt okunamadı."
UNREACHABLE_PREFIX = "Kayıt cihazına ulaşılamadı"
STOPPED_MSG = "Kayıttan izleme durduruldu."

_FILE_CHANNEL = RecorderChannel("file", "", None, False)
_ACTIVE = frozenset({"connecting", "playing"})

UrlFnFactory = Callable[[float, int, bool], Callable[[], str]]


class TooManyPlayers(Exception):
    """Aynı anda en çok MAX_PLAYERS oynatıcı (API: 429)."""

    def __init__(self, message: str = TOO_MANY_MSG) -> None:
        super().__init__(message)


class ExportBusy(Exception):
    """Bir dışa aktarma sürüyor (API: 409)."""

    def __init__(self, message: str = EXPORT_BUSY_MSG) -> None:
        super().__init__(message)


class SourceMissing(LookupError):
    """Kaynak bulunamadı (silinmiş) (API: 404)."""


class ChannelNotFound(LookupError):
    """Kanal kayıt cihazının listesinde yok (API: 404)."""

    def __init__(self, message: str = "Kamera kayıt cihazında bulunamadı.") -> None:
        super().__init__(message)


class UnsupportedSpeed(ValueError):
    """İstenen hız bu bağdaştırıcıda yok (API: 422)."""

    def __init__(self, message: str = "Bu hız desteklenmiyor.") -> None:
        super().__init__(message)


class MissingChannel(ValueError):
    """Kayıt cihazı kaynağında kanal seçilmemiş (API: 422)."""

    def __init__(self, message: str = "Kayıt cihazından bir kamera seçin.") -> None:
        super().__init__(message)


class NoArchive(ValueError):
    """Kaynak kayıt cihazı değil (ve dosya kaynağı da değil) (API: 422)."""

    def __init__(self, message: str = "Bu kaynakta kayıt arşivi yok.") -> None:
        super().__init__(message)


class ManagerStopped(RuntimeError):
    """Yönetici durduruldu (uygulama kapanıyor) (API: 503)."""

    def __init__(self, message: str = STOPPED_MSG) -> None:
        super().__init__(message)


class _Store(Protocol):
    def source(self, source_id: str) -> dict[str, Any] | None: ...

    def password(self, source_id: str) -> str: ...


@dataclass(frozen=True)
class PlayerView:
    id: str
    source_id: str
    channel_id: str | None
    name: str
    state: str                  # connecting | playing | paused | ended | error
    message: str
    at: float                   # epoch sn (dosya kaynağında dosya saniyesi)
    speed: int
    speeds: tuple[int, ...]
    fps: float
    can_export: bool


def _detail(e: BaseException) -> str:
    """`viewer._detail`'den tek farkı: `RecorderError`'da ham İngilizce `detail` ("invalid sid") yerine kullanıcıya
    gösterilecek Türkçe metin (`str(e)`) kullanılır; diğer istisnalar aynı yoldan geçer."""
    return str(e) if isinstance(e, RecorderError) else _viewer_detail(e)


def _bare(url: str) -> str:
    """Adresten `kullanıcı:şifre@` atılır (bağdaştırıcıya ve günlüğe kimlik gitmesin)."""
    if not open_gate.is_network(url):
        return url
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(parts._replace(netloc=parts.netloc.rsplit("@", 1)[-1]))


def _needs_keep_alive(archive: ArchiveClient) -> bool:
    """Bağdaştırıcı canlı tutma istiyor mu (yönlendirici `needs_keep_alive` verir; yoksa yöntem geçersiz kılınmış mı)."""
    wants = getattr(archive, "needs_keep_alive", None)
    if wants is not None:
        return bool(wants)
    return type(archive).keep_alive is not ArchiveClient.keep_alive


# MARK: - Oynatıcı


class ArchivePlayer:
    """Bir arşiv oynatması (kendi iş parçacığı). Genel yöntemler iş parçacığı güvenlidir ve beklemez (`close` hariç).

    `url_fn_factory(start, speed, substream)` bir açılışın adres üreticisini verir (her açılışta yeniden çağrılır).
    `name` dizgi ya da her görünümde sorulan çağrılabilir (kanal adı ilk bağlanışta öğrenilir)."""

    def __init__(self, player_id: str, archive: ArchiveClient, channel: str | None, url_fn_factory: UrlFnFactory,
                 open_capture: Callable[[str], Any], name: str | Callable[[], str], start: float, speed: int,
                 substream: bool, clock: Callable[[], float] = time.monotonic, *, source_id: str = "",
                 no_frame_s: float = NO_FRAME_S) -> None:
        if speed not in archive.speeds:
            raise UnsupportedSpeed()
        self.id, self.source_id, self.channel_id = player_id, source_id, channel
        self._archive, self._url_fn_factory, self._open_capture = archive, url_fn_factory, open_capture
        self._name, self._substream, self._clock, self._no_frame_s = name, substream, clock, no_frame_s
        self._cond = threading.Condition()
        self._gen = 0                       # her kumandada artar; eski okuma döngüsü yayımlamaz, çıkar
        self._pending = True                # iş parçacığı (_start, _speed) ile açılış yapacak
        self._closed = False
        self._start = self._at = float(start)
        self._speed = speed
        self._state, self._message = "connecting", ""
        self._seq = 0
        self._frame: np.ndarray | None = None
        self._fps = 0.0
        self._since = clock()               # kare bekleme ölçütü: son açılış isteği ya da son kare
        self.last_used = clock()
        self._pinging = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"arsiv-{player_id[:8]}", daemon=True)
        self._thread.start()

    # -- genel arayüz --------------------------------------------------------------------------------------------

    @property
    def device_paced(self) -> bool:
        """Hız cihazda mı (TRASSIR); değilse istemci kare atlar."""
        return 16 in self._archive.speeds

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def state(self) -> str:
        """Güncel durum (dokunmaz, denetlemez; akış ucu boşta süresini yalnız etkin durumda sayar)."""
        with self._cond:
            return self._state

    def touch(self) -> None:
        self.last_used = self._clock()

    def view(self) -> PlayerView:
        self.touch()
        self.check()
        name = self._name() if callable(self._name) else self._name
        with self._cond:
            return PlayerView(self.id, self.source_id, self.channel_id, name, self._state, self._message, self._at,
                              self._speed, tuple(self._archive.speeds), self._fps, self._archive.can_export)

    def frame(self, touch: bool = True) -> tuple[int, np.ndarray | None]:
        """Son kare. `touch=False`: yalnız bakar (akış ucunun yoklaması); kare gerçekten gönderilince çağıran
        `touch()` eder, böylece terk edilmiş bir bağlantı duraklatılmış oynatıcıyı canlı tutmaz."""
        if touch:
            self.touch()
        self.check()
        with self._cond:
            return self._seq, self._frame

    def check(self) -> None:
        """NO_FRAME_S boyunca kare gelmediyse `error` (okuma takılı kalsa da; yeniden bağlanılmaz)."""
        with self._cond:
            if self._closed or self._state not in _ACTIVE or self._clock() - self._since <= self._no_frame_s:
                return
            self._gen += 1
            self._pending = False
            self._state, self._message = "error", NO_FRAME_MSG
            self._cond.notify_all()

    def pause(self) -> None:
        self.touch()
        with self._cond:
            if self._closed or self._state not in _ACTIVE:
                return
            self._gen += 1
            self._pending = False
            self._state, self._message = "paused", ""
            self._cond.notify_all()

    def resume(self) -> None:
        """Duraklatılmış, bitmiş ya da hatalı oynatmayı `at`tan yeniden açar; oynarken/bağlanırken bir şey yapmaz."""
        self.touch()
        with self._cond:
            if not self._closed and self._state not in _ACTIVE:
                self._restart(self._at)

    def seek(self, at: float) -> None:
        """Yeni konumdan oynatır (duraklatılmışsa da)."""
        self.touch()
        with self._cond:
            if not self._closed:
                self._restart(max(0.0, float(at)))

    def set_speed(self, speed: int) -> None:
        """Oynuyorsa aynı konumdan yeni hızla yeniden açar; duraklatılmış/bitmişse yalnız hızı kaydeder."""
        if speed not in self._archive.speeds:
            raise UnsupportedSpeed()
        self.touch()
        with self._cond:
            if self._closed or speed == self._speed:
                return
            self._speed = speed
            if self._state in _ACTIVE:
                self._restart(self._at)

    def close(self, wait: float = CLOSE_WAIT_S) -> None:
        """Okuma durur, yakalama kapanır, `archive.stop` çağrılır (iş parçacığı en çok `wait` sn beklenir)."""
        with self._cond:
            if not self._closed:
                self._closed = True
                self._gen += 1
                self._pending = False
                self._cond.notify_all()
        self._thread.join(max(0.0, wait))

    # -- iş parçacığı --------------------------------------------------------------------------------------------

    def _restart(self, start: float) -> None:
        """Kilit altında: eski okuma bırakılır, `start`tan yeni açılış istenir."""
        self._gen += 1
        self._start = self._at = start
        self._pending = True
        self._state, self._message = "connecting", ""
        self._since = self._clock()
        self._cond.notify_all()

    def _current(self, gen: int) -> bool:
        return gen == self._gen and not self._closed

    def _set(self, gen: int, state: str, message: str = "") -> None:
        with self._cond:
            if self._current(gen):
                self._state, self._message = state, message

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._pending and not self._closed:
                    self._cond.wait()
                if self._closed:
                    return
                self._pending = False
                gen, start, speed = self._gen, self._start, self._speed
            try:
                self._play(gen, start, speed)
            except Exception as e:  # noqa: BLE001 — iş parçacığı ölmesin; hata gösterilir, "Sürdür" yeniden dener
                _LOG.warning("Arşiv oynatıcısı hatası (%s): %s", self.id[:8], type(e).__name__)
                self._set(gen, "error", READ_FAILED_MSG)

    def _play(self, gen: int, start: float, speed: int) -> None:
        issued: list[str] = []
        make = self._url_fn_factory(start, speed, self._substream)

        def url_fn() -> str:
            url = make()
            issued.append(url)
            return url

        try:
            url, cap = open_gate.resolve_and_open(url_fn, self._open_capture, open_gate.VIEWER)
        except open_gate.UrlError as e:                     # kayıt cihazı yanıt vermedi / kanal yok
            self._stop_urls(issued)
            self._set(gen, "error", f"{UNREACHABLE_PREFIX}: {_detail(e.__cause__ or e)}")
            return
        except Exception as e:  # noqa: BLE001 — açıcı hatası (FFmpeg)
            self._stop_urls(issued)
            _LOG.warning("Arşiv kaydı açılamadı (%s): %s", self.id[:8], type(e).__name__)
            self._set(gen, "error", OPEN_FAILED_MSG)
            return
        self._stop_urls([u for u in issued if u != url])   # kuyrukta tazelenen adresin eskisi
        try:
            self._read(gen, url, cap, start, speed)
        finally:
            with contextlib.suppress(Exception):
                cap.release()
            self._stop_urls([url])

    def _read(self, gen: int, url: str, cap: Any, start: float, speed: int) -> None:
        if not cap.isOpened():
            self._set(gen, "error", OPEN_FAILED_MSG)
            return
        is_file = not open_gate.is_network(url)
        if is_file:
            cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000.0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) if hasattr(cap, "get") else 0.0
        if not 0 < fps <= MAX_FPS:
            fps = DEFAULT_FPS
        paced = self.device_paced
        skip = 1 if paced else speed
        with self._cond:
            if self._current(gen):
                self._fps = fps
        ping = _needs_keep_alive(self._archive)
        bare = _bare(url)
        n, began, last_ping = 0, time.monotonic(), self._clock()
        last_frame = self._clock()
        while self._current(gen):
            ok, frame = cap.read()
            if not ok:
                # Kayıt sonu hemen gelir; susan cihazda FFmpeg okuma zaman aşımıyla (READ_TIMEOUT_MS) False döner
                if not is_file and self._clock() - last_frame >= DEAD_READ_S:
                    self._set(gen, "error", NO_FRAME_MSG)
                else:
                    self._set(gen, "ended")
                return
            n += 1
            at = start + (n / fps * speed if paced else n / fps)
            small = _readonly(downscale(frame, MAX_WIDTH["sub"])) if n % skip == 0 else None
            now = last_frame = self._clock()
            with self._cond:
                if not self._current(gen):
                    return
                self._at, self._since = at, now
                if small is not None:
                    self._seq += 1
                    self._frame = small
                self._state, self._message = "playing", ""
            if is_file:                                     # dosya gerçek zamanlı (hızla) oynar
                lag = n / (fps * speed) - (time.monotonic() - began)
                if lag > 0:
                    with self._cond:
                        self._cond.wait_for(lambda: not self._current(gen), lag)
            if ping and now - last_ping >= KEEP_ALIVE_S and not self._pinging.is_set():
                last_ping = now
                self._pinging.set()                         # uçuşta ping varken yenisi atılmaz
                threading.Thread(target=self._ping, args=(bare,), daemon=True).start()

    def _ping(self, url: str) -> None:
        try:
            with contextlib.suppress(Exception):
                self._archive.keep_alive(url)
        finally:
            self._pinging.clear()

    def _stop_urls(self, urls: list[str]) -> None:
        for url in urls:
            try:
                self._archive.stop(_bare(url))
            except Exception as e:  # noqa: BLE001 — kapanışta hata yutulur
                _LOG.debug("Arşiv oynatması durdurulamadı (%s): %s", self.id[:8], type(e).__name__)


# MARK: - Dışa aktarma akışı (kilitli)


class _LockedStream(Iterator[bytes]):
    """Dışa aktarma akışı; sonuna dek okununca, hata verince ya da `close()` ile kilidi bir kez bırakır."""

    def __init__(self, inner: Iterator[bytes], release: Callable[[], None]) -> None:
        self._inner, self._release = inner, release
        self._done = False
        self._lock = threading.Lock()

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> bytes:
        try:
            return next(self._inner)
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        with self._lock:
            if self._done:
                return
            self._done = True
        try:
            close = getattr(self._inner, "close", None)
            if close is not None:
                with contextlib.suppress(Exception):
                    close()
        finally:
            self._release()

    def __del__(self) -> None:
        self.close()


# MARK: - Yönetici


def file_source_path(src: dict[str, Any]) -> str | None:
    """Test kancası: yerel video dosyası "kamera" (yalnız `ANALYZER_ALLOW_FILE_SOURCES=1`), `LiveManager.camera_url`
    ile aynı koşul. Değilse None."""
    custom = str(src.get("customUrl", "")).strip()
    if (src.get("kind") == "camera" and src.get("brand") == "custom"
            and os.environ.get("ANALYZER_ALLOW_FILE_SOURCES") == "1" and custom and pathlib.Path(custom).is_file()):
        return custom
    return None


def _ascii(text: str) -> str:
    text = text.replace("ı", "i").replace("İ", "I")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-") or "kayit"


_UNSAFE_NAME = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]+')     # UTF-8 dosya adında yol/denetim karakterleri


def _require_channel(target: _Target, channel_id: str | None) -> None:
    """Kayıt cihazı kaynağında kanal zorunlu (oynatma, takvim, çizelge, dışa aktarma aynı denetim)."""
    if target.client is not None and not channel_id:
        raise MissingChannel()


class _Routed(ArchiveClient):
    """Oynatıcının arşivi. Her açılış kaynağın güncel istemcisiyle kurulan bağdaştırıcıdan adres alır
    (`ArchiveManager._url_factory`); `stop`/`keep_alive` o adresi veren bağdaştırıcıya yönlenir. Hızlar ve dışa
    aktarma yeteneği oynatıcı açılırkenki bağdaştırıcıdandır."""

    def __init__(self, first: ArchiveClient) -> None:
        self._first = first
        self.speeds = first.speeds
        self.can_export = first.can_export
        self.tz = first.tz
        self.needs_keep_alive = _needs_keep_alive(first)
        self._by_url: dict[str, ArchiveClient] = {}
        self._lock = threading.Lock()

    def remember(self, url: str, archive: ArchiveClient) -> None:
        with self._lock:
            self._by_url[url] = archive

    def stream_url(self, channel: RecorderChannel, start: float, end: float | None, substream: bool,
                   speed: int) -> str:
        return self._first.stream_url(channel, start, end, substream, speed)

    def stop(self, stream_url: str) -> None:
        with self._lock:
            archive = self._by_url.pop(stream_url, self._first)
        archive.stop(stream_url)

    def keep_alive(self, stream_url: str) -> None:
        with self._lock:
            archive = self._by_url.get(stream_url, self._first)
        archive.keep_alive(stream_url)

    def calendar(self, channel: RecorderChannel, year: int, month: int) -> set[int]:
        return self._first.calendar(channel, year, month)

    def timeline(self, channel: RecorderChannel, day: float) -> list[tuple[float, float]]:
        return self._first.timeline(channel, day)


@dataclass(frozen=True)
class _Target:
    archive: ArchiveClient
    client: RecorderClient | None       # dosya kaynağında None
    brand: RecorderBrand | None


class ArchiveManager:
    """Arşiv oynatıcıları, takvim/çizelge önbelleği ve dışa aktarma kilidi.

    `recorder_factory(src)` kaynağın canlı istemcisini verir (uygulamada `LiveManager.recorder`, önbellekli);
    `archive_factory(client, brand)` onu arşiv bağdaştırıcısıyla sarar (testler değiştirir)."""

    MAX_PLAYERS = MAX_PLAYERS
    IDLE_S = IDLE_S
    NO_FRAME_S = NO_FRAME_S
    CACHE_S = CACHE_S

    def __init__(self, store: _Store, recorder_factory: Callable[[dict[str, Any]], RecorderClient],
                 open_capture: Callable[[str], Any], clock: Callable[[], float] = time.monotonic, *,
                 archive_factory: Callable[[RecorderClient, str], ArchiveClient] = make_archive,
                 reaper: bool = True) -> None:
        self._store, self._recorder_factory, self._open_capture = store, recorder_factory, open_capture
        self._clock, self._archive_factory = clock, archive_factory
        self._lock = threading.Lock()
        self._players: dict[str, ArchivePlayer] = {}
        self._channels: dict[str, list[RecorderChannel]] = {}
        self._source_locks: dict[str, threading.Lock] = {}
        self._cache: dict[tuple[Any, ...], tuple[float, Any]] = {}
        self._files: dict[str, FileArchive] = {}
        self._export_lock = threading.Lock()
        self._stop = threading.Event()
        self._reaper_wanted = reaper
        self._reaper: threading.Thread | None = None

    # -- kaynak / kanal ------------------------------------------------------------------------------------------

    def _source(self, source_id: str) -> dict[str, Any]:
        src = self._store.source(source_id)
        if src is None:
            raise SourceMissing("Kaynak bulunamadı.")
        return src

    def _target(self, src: dict[str, Any]) -> _Target:
        path = file_source_path(src)
        if path is not None:
            with self._lock:
                archive = self._files.get(path)
                if archive is None:
                    archive = self._files[path] = FileArchive(path)
            return _Target(archive, None, None)
        if src.get("kind") != "recorder":
            raise NoArchive()
        try:
            brand = RecorderBrand(src.get("recorderBrand", "trassir"))
        except ValueError:
            raise RecorderError.unexpected("bilinmeyen marka") from None
        client = self._recorder_factory(src)
        return _Target(self._archive_factory(client, brand), client, brand)

    def _channel(self, source_id: str, target: _Target, channel_id: str | None) -> RecorderChannel:
        """Kanal (ağa çıkabilir: liste önbellekte yoksa ya da kanal listede yoksa bir kez yenilenir)."""
        _require_channel(target, channel_id)
        if target.client is None:
            return _FILE_CHANNEL
        for refresh in (False, True):
            with self._lock:
                chans = None if refresh else self._channels.get(source_id)
            if chans is None:
                chans = target.client.channels()
                with self._lock:
                    self._channels[source_id] = chans
            for c in chans:
                if c.id == channel_id:
                    return c
        raise ChannelNotFound()

    def _source_lock(self, source_id: str) -> threading.Lock:
        with self._lock:
            return self._source_locks.setdefault(source_id, threading.Lock())

    def name(self, source_id: str, channel_id: str | None) -> str:
        """Kaynak adı (+ kanal adı). Ağa çıkmaz: kanal adı önbellekte yoksa kanal kimliği yazılır."""
        src = self._store.source(source_id)
        if src is None:
            return "Silinmiş kamera"
        name = str(src.get("name") or "").strip() or "Kamera"
        if not channel_id:
            return name
        with self._lock:
            chans = list(self._channels.get(source_id, []))
        for c in chans:
            if c.id == channel_id:
                return f"{name} · {c.title.strip()}"
        return f"{name} · {channel_id}"

    # -- takvim / çizelge ----------------------------------------------------------------------------------------

    def _cached(self, key: tuple[Any, ...], source_id: str, channel_id: str | None,
                call: Callable[[ArchiveClient, RecorderChannel], Any]) -> Any:
        hit = self._cache_get(key)
        if hit is not None:
            return hit
        with self._source_lock(source_id):
            hit = self._cache_get(key)                      # beklerken başka istek doldurmuş olabilir
            if hit is not None:
                return hit
            src = self._source(source_id)
            target = self._target(src)
            value = call(target.archive, self._channel(source_id, target, channel_id))
            with self._lock:
                self._cache[key] = (self._clock() + self.CACHE_S, value)
            return value

    def _cache_get(self, key: tuple[Any, ...]) -> Any:
        """Önbellek kaydı ya da None; süresi dolan kayıtlar burada da atılır (temizliği beklemeden)."""
        now = self._clock()
        with self._lock:
            self._prune_cache(now)
            hit = self._cache.get(key)
        return None if hit is None else hit[1]

    def _prune_cache(self, now: float) -> None:
        """Kilit altında çağrılır."""
        for key in [k for k, (exp, _) in self._cache.items() if exp <= now]:
            del self._cache[key]

    def calendar(self, source_id: str, channel_id: str | None, year: int, month: int) -> set[int]:
        days = self._cached(("cal", source_id, channel_id, year, month), source_id, channel_id,
                            lambda a, ch: frozenset(a.calendar(ch, year, month)))
        return set(days)

    def timeline(self, source_id: str, channel_id: str | None, day: float) -> list[tuple[float, float]]:
        ranges = self._cached(("tl", source_id, channel_id, float(day)), source_id, channel_id,
                              lambda a, ch: tuple(a.timeline(ch, day)))
        return list(ranges)

    # -- oynatıcılar ---------------------------------------------------------------------------------------------

    def _url_factory(self, source_id: str, channel_id: str | None, routed: _Routed) -> UrlFnFactory:
        """Her açılışta kaynağın güncel kaydı okunur ve istemci ondan kurulur (adres/parola değişimi yeni açılışta
        etkili); adresi veren bağdaştırıcı `routed`'a yazılır (stop/keep_alive ona gider)."""
        def factory(start: float, speed: int, substream: bool) -> Callable[[], str]:
            def url_fn() -> str:
                src = self._source(source_id)
                target = self._target(src)
                channel = self._channel(source_id, target, channel_id)
                url = target.archive.stream_url(channel, start, None, substream, speed)
                routed.remember(url, target.archive)
                username = str(src.get("username") or "")
                if target.brand not in (None, RecorderBrand.TRASSIR) and username:
                    url = with_credentials(url, username, self._store.password(source_id))
                return url
            return url_fn
        return factory

    def open(self, source_id: str, channel_id: str | None, at: float, speed: int, substream: bool) -> PlayerView:
        """Oynatıcı açar (ağa çıkmaz; bağlantı oynatıcının iş parçacığında). `TooManyPlayers`, `SourceMissing`,
        `MissingChannel`, `NoArchive`, `UnsupportedSpeed`, `ManagerStopped`."""
        if self._stop.is_set():
            raise ManagerStopped()
        target = self._target(self._source(source_id))
        _require_channel(target, channel_id)
        if speed not in target.archive.speeds:
            raise UnsupportedSpeed()
        with self._lock:
            if self._stop.is_set():
                raise ManagerStopped()
            if len(self._players) >= self.MAX_PLAYERS:
                raise TooManyPlayers()
            pid = uuid.uuid4().hex
            routed = _Routed(target.archive)
            player = ArchivePlayer(pid, routed, channel_id, self._url_factory(source_id, channel_id, routed),
                                   self._open_capture, lambda: self.name(source_id, channel_id), float(at), speed,
                                   substream, clock=self._clock, source_id=source_id, no_frame_s=self.NO_FRAME_S)
            self._players[pid] = player
            self._ensure_reaper()
        return player.view()

    def get(self, player_id: str) -> ArchivePlayer | None:
        with self._lock:
            return self._players.get(player_id)

    def close(self, player_id: str) -> bool:
        with self._lock:
            player = self._players.pop(player_id, None)
        if player is None:
            return False
        player.close()
        return True

    def sweep(self) -> int:
        """Boşta kalan oynatıcıları kapatır, diğerlerinde kare bekleme süresini denetler, süresi dolan önbelleği siler."""
        now = self._clock()
        with self._lock:
            idle = [pid for pid, p in self._players.items() if now - p.last_used > self.IDLE_S]
            gone = [self._players.pop(pid) for pid in idle]
            alive = list(self._players.values())
            self._prune_cache(now)
        for p in gone:
            p.close(SWEEP_WAIT_S)
        for p in alive:
            p.check()
        return len(gone)

    def _ensure_reaper(self) -> None:
        if self._reaper_wanted and self._reaper is None:
            self._reaper = threading.Thread(target=self._reap, name="arsiv-temizlik", daemon=True)
            self._reaper.start()

    def _reap(self) -> None:
        while not self._stop.wait(REAP_EVERY_S):
            try:
                self.sweep()
            except Exception:  # noqa: BLE001 — temizlik iş parçacığı ölmesin
                _LOG.exception("Arşiv oynatıcısı temizliği başarısız")

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            players = list(self._players.values())
            self._players.clear()
            reaper = self._reaper
        deadline = time.monotonic() + CLOSE_WAIT_S
        for p in players:
            p.close(0)
        for p in players:
            p.close(deadline - time.monotonic())
        if reaper is not None:
            reaper.join(max(0.0, deadline - time.monotonic()))

    # -- dışa aktarma --------------------------------------------------------------------------------------------

    def export(self, source_id: str, channel_id: str | None, start: float,
               end: float) -> tuple[str, str, Iterator[bytes]]:
        """(ASCII dosya adı, UTF-8 dosya adı, akış). Adlar `<kamera adı>-<YYYYMMDD-HHMM>.mp4` (arşivin saat diliminde;
        TRASSIR/Dahua/dosya: bu bilgisayarın yerel saati). Aralık denetimi API'nindir. Tek görev: sürerken
        `ExportBusy`; akış sonuna dek okununca ya da `close()` ile kilit kalkar. Desteklemeyen cihazda
        `RecorderError.unsupported()`; kanalsız kayıt cihazında `MissingChannel`."""
        target = self._target(self._source(source_id))
        _require_channel(target, channel_id)
        if not target.archive.can_export:
            raise RecorderError.unsupported()
        channel = self._channel(source_id, target, channel_id)     # kanal adı dosya adına girer
        stamp = datetime.fromtimestamp(start, target.archive.tz).strftime("%Y%m%d-%H%M")
        name = self.name(source_id, channel_id)                     # kilitten önce: sızıntı olmasın
        filename = f"{_ascii(name)}-{stamp}.mp4"
        utf8_name = f"{_UNSAFE_NAME.sub('-', name).strip(' .-') or 'kayit'}-{stamp}.mp4"
        if not self._export_lock.acquire(blocking=False):
            raise ExportBusy()
        stream: Iterator[bytes] | None = None
        try:
            stream = target.archive.export(channel, start, end)
            return filename, utf8_name, _LockedStream(stream, self._export_lock.release)
        except BaseException:
            if stream is not None:
                with contextlib.suppress(Exception):
                    getattr(stream, "close", lambda: None)()
            self._export_lock.release()
            raise
