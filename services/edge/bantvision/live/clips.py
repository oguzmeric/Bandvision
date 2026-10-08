"""Poz güvenlik alarmının olay kaydı (video klip): ihlal anının görüntüsü panelde oynatılır.

- **Ön kayıt** (`ClipBuffer`, yalnızca güvenlik oturumunda): okuyucu iş parçacığı kameradan okuduğu HER kareyi verir
  (analizden bağımsız, daha akıcı); en çok `CLIP_FPS` (10) kare/sn tutulur, işaretsiz, en çok 1280 px genişlikte,
  JPEG (kalite 80) olarak bellekte. Son `PRE_S` (8) sn kalır, eskiler zamana göre düşer (bellek sınırlı). Canlı
  oturumda JPEG'e çevirme tek yuvalı ayrı bir iş parçacığında yapılır: okuyucu yalnızca kare başvurusunu bırakır;
  çevirici meşgulse yuvadaki kare en yenisiyle değiştirilir (sıra ve zaman sınırı korunur).
- **Yakalama:** alarm anında ön kayıt alınır, ardından `POST_S` (4) sn daha toplanır; aynı karede doğan alarmlar tek
  yakalamayı paylaşır. Kamera koparsa ya da oturum durursa yakalama elindeki karelerle yazılır.
- **Yazım** (`ClipWriter`): tek arka plan iş parçacığı, sınırlı kuyruk — okuyucu ve işleyici hiç beklemez. Kareler sabit
  `CLIP_FPS` ile (videodaki zaman duvar saatine eşit; boşluk önceki kareyle dolar) OpenCV `VideoWriter` + VP8 ile
  `<data>/live/alarm-clips/<alarmId>.webm` olarak geçici adla yazılır, sonra atomik olarak yeniden adlandırılır. Başarıda
  kayıt `clip: true` ve `clipStartedAt` (ilk karenin duvar saati) alır. Her hata Türkçe günlüğe yazılır, kayıt
  `clip: false` kalır; hiçbir hata oturuma ulaşmaz. Kayıt durumu kayda yansır: yakalama planlanınca `clipPending`,
  yazılınca `clip`, alınamazsa (görüntü yok, kuyruk dolu, kodlayıcı/disk hatası) `clipFailed`.

Kayıt yalnızca bu bilgisayarda durur (Telegram'a gitmez); alarm kaydıyla birlikte 7 gün, en çok `MAX_CLIPS` dosya.
"""
from __future__ import annotations

import logging
import os
import queue
import shutil
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np

if TYPE_CHECKING:
    from .alarms import AlarmStore

_LOG = logging.getLogger(__name__)

PRE_S = 8.0                     # alarmdan önceki saniyeler (bellekte sürekli tutulur)
POST_S = 4.0                    # alarmdan sonra toplanan saniyeler
CLIP_FPS = 10.0                 # kayıt kare hızı (okuyucu kareleri bu hıza seyreltilir)
MAX_WIDTH = 1280                # daha geniş kare bu genişliğe küçültülür
JPEG_QUALITY = 80
QUEUE_MAX = 8                   # yazılmayı bekleyen en çok yakalama (her biri ≈ 120 JPEG)
STOP_WAIT_S = 60.0              # kapanışta bekleyen kayıtların yazılması için en çok bu kadar beklenir

Frame = tuple[float, float, bytes]      # (tekdüze saat, duvar saati, JPEG)


@dataclass(frozen=True)
class ClipJob:
    """Yazılacak bir kayıt: aynı karede doğan alarmların kimlikleri (ilki kodlanır, diğerleri kopyalanır) ve kareler."""
    ids: tuple[str, ...]
    frames: tuple[Frame, ...]


@dataclass
class _Capture:
    ids: tuple[str, ...]
    until: float                        # bu tekdüze saate kadar kare toplanır
    frames: list[Frame]


ClipState = Callable[[Sequence[str], str], None]    # (alarm kimlikleri, "failed") — yakalama alınamadı


class ClipBuffer:
    """Bir güvenlik oturumunun ön kaydı ve süren yakalamaları. `push` okuyucudan, `capture` işleyiciden (ya da deneme
    alarmında API'den) çağrılır; iş parçacığı güvenlidir. Biten yakalama `sink`'e verilir (kilit dışında; `sink`
    engellememeli). `sink` hatası yutulur ve günlüğe yazılır; yakalama alınamazsa `state(ids, "failed")`.

    `threaded=True` (canlı oturum): JPEG'e çevirme tek yuvalı ayrı iş parçacığında — `push` yalnızca kareyi yuvaya
    koyar (çevirici meşgulse yuvadaki eski kare en yenisiyle değişir); `close()` iş parçacığını durdurur.
    `threaded=False` (varsayılan): `push` kareyi hemen çevirir (testlerde belirlenimli)."""

    def __init__(self, sink: Callable[[ClipJob], None], pre_s: float | None = None, fps: float | None = None,
                 max_width: int = MAX_WIDTH, quality: int = JPEG_QUALITY, state: ClipState | None = None,
                 threaded: bool = False) -> None:
        self._sink = sink
        self._state = state
        self._pre = PRE_S if pre_s is None else pre_s
        self._period = 1.0 / (CLIP_FPS if fps is None else fps)
        self._max_width, self._quality = max_width, quality
        self._lock = threading.Lock()
        self._ring: deque[Frame] = deque()
        self._pending: list[_Capture] = []
        self._due = float("-inf")
        # tek yuvalı çevirici (threaded): yuvadaki çevrilmemiş kare, çevirici meşgul mü, kapandı mı
        self._slot_cv = threading.Condition(threading.Lock())
        self._slot: tuple[np.ndarray, float, float] | None = None
        self._busy = False
        self._closed = False
        self._thread: threading.Thread | None = None
        if threaded:
            self._thread = threading.Thread(target=self._run, name="kayit-jpeg", daemon=True)
            self._thread.start()

    def frames(self) -> list[Frame]:
        with self._lock:
            return list(self._ring)

    def push(self, frame: np.ndarray, t: float, wall: float) -> None:
        """Okuyucunun yeni karesi (`t` tekdüze saat, `wall` duvar saati). Seyreltme: kare yalnızca zamanı geldiyse
        JPEG'e çevrilir (uzun vadede en çok `CLIP_FPS`/sn; kaynak yavaşsa her kare). Ayrı çeviricide okuyucu yalnızca
        başvuruyu bırakır (kopya yok: okuyucu her karede yeni dizi alır)."""
        with self._lock:
            keep = t >= self._due
            if keep:
                self._due = max(self._due + self._period, t + self._period / 2)
        if not keep:
            return
        if self._thread is None:
            self._add(frame, t, wall)
            return
        with self._slot_cv:
            self._slot = (frame, t, wall)                   # meşgulse önceki çevrilmemiş kare düşer: en yenisi kalır
            self._slot_cv.notify_all()

    def wait_idle(self, timeout: float = 2.0) -> bool:
        """Yuvadaki kare çevrilip eklenene dek bekler (en çok `timeout` sn); boşta ise True."""
        deadline = time.monotonic() + timeout
        with self._slot_cv:
            while self._slot is not None or self._busy:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._slot_cv.wait(left)
        return True

    def close(self) -> None:
        """Ayrı çeviriciyi durdurur (yuvadaki son kare önce eklenir)."""
        with self._slot_cv:
            self._closed = True
            self._slot_cv.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        while True:
            with self._slot_cv:
                while self._slot is None and not self._closed:
                    self._slot_cv.wait()
                if self._slot is None:
                    return
                frame, t, wall = self._slot
                self._slot, self._busy = None, True
            try:
                self._add(frame, t, wall)
            except Exception:  # noqa: BLE001 — çevirici ölmesin
                _LOG.exception("Kayıt karesi eklenemedi")
            finally:
                with self._slot_cv:
                    self._busy = False
                    self._slot_cv.notify_all()

    def _add(self, frame: np.ndarray, t: float, wall: float) -> None:
        """Kareyi JPEG'e çevirip ön kayda ve süren yakalamalara ekler; süresi dolan yakalamaları yazar."""
        jpeg = self._encode(frame)
        with self._lock:
            if jpeg is not None:
                item = (t, wall, jpeg)
                self._ring.append(item)
                while self._ring and self._ring[0][0] < t - self._pre:
                    self._ring.popleft()
                for c in self._pending:
                    if t <= c.until:
                        c.frames.append(item)
            done = self._take(lambda c: t >= c.until)
        self._emit(done)

    def capture(self, ids: Sequence[str], t: float, post_s: float | None = None) -> bool:
        """Alarm: ön kayıt alınır ve `post_s` (varsayılan `POST_S`) sn daha toplanır; 0 ise hemen yazılır (deneme
        alarmı). Kare yoksa False (kayıt olmaz; `state(ids, "failed")`)."""
        post = POST_S if post_s is None else post_s
        with self._lock:
            pre = [f for f in self._ring if f[0] >= t - self._pre]
            empty = not pre and post <= 0
            cap = _Capture(tuple(ids), t + post, pre)
            if post > 0:
                self._pending.append(cap)
        if empty:
            self._failed(ids)                               # kayıt yazımı (JSON) kilit dışında
            return False
        if post <= 0:
            self._emit([cap])
        return True

    def flush_due(self, t: float) -> None:
        """Süresi dolmuş yakalamaları elindeki karelerle yazar (kamera koptu: yeni kare gelmiyor)."""
        with self._lock:
            done = self._take(lambda c: t >= c.until)
        self._emit(done)

    def flush(self) -> None:
        """Tüm süren yakalamaları hemen yazar (oturum durdu ya da güvenlikten çıktı); çevirideki son kare beklenir."""
        if self._thread is not None:
            self.wait_idle(1.0)
        with self._lock:
            done = self._take(lambda _c: True)
        self._emit(done)

    def _take(self, due: Callable[[_Capture], bool]) -> list[_Capture]:
        done = [c for c in self._pending if due(c)]
        if done:
            self._pending = [c for c in self._pending if not due(c)]
        return done

    def _emit(self, done: list[_Capture]) -> None:
        for c in done:
            if not c.frames:
                _LOG.warning("Olay kaydı alınamadı: kamerada görüntü yok (%s)", ", ".join(c.ids))
                self._failed(c.ids)
                continue
            try:
                self._sink(ClipJob(c.ids, tuple(c.frames)))
            except Exception:  # noqa: BLE001 — kayıt hatası okuyucuyu/işleyiciyi durdurmaz
                _LOG.exception("Olay kaydı yazıcıya verilemedi (%s)", ", ".join(c.ids))
                self._failed(c.ids)

    def _failed(self, ids: Sequence[str]) -> None:
        if self._state is None:
            return
        try:
            self._state(list(ids), "failed")
        except Exception:  # noqa: BLE001
            _LOG.exception("Olay kaydı durumu yazılamadı (%s)", ", ".join(ids))

    def _encode(self, frame: np.ndarray) -> bytes | None:
        try:
            w = frame.shape[1]
            if w > self._max_width:
                frame = cv2.resize(frame, (self._max_width, round(frame.shape[0] * self._max_width / w)),
                                   interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self._quality])
            return buf.tobytes() if ok else None
        except Exception:  # noqa: BLE001 — bozuk kare kayda girmez, okuyucu sürer
            _LOG.debug("Kayıt karesi JPEG'e çevrilemedi", exc_info=True)
            return None


def encode_webm(path: Path, frames: Sequence[Frame], fps: float) -> None:
    """Kareleri sabit `fps` ile VP8 WebM olarak yazar. Video zamanı duvar saatine eşittir: her çıktı anı için zamana
    en yakın (yarım periyot toleranslı) son kare yazılır; boşluk önceki kareyle dolar. Boyutu değişen kare ilk karenin
    boyutuna getirilir. Hata `RuntimeError`/`OSError` fırlatır."""
    if not frames:
        raise RuntimeError("kare yok")
    t0, t_end = frames[0][0], frames[-1][0]
    n = int((t_end - t0) * fps + 1e-6) + 1
    first = _decode(frames[0][2])
    h, w = first.shape[:2]
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"VP80"), fps, (w, h))
    if not writer.isOpened():
        writer.release()
        raise RuntimeError("VP8 kodlayıcı açılamadı")
    try:
        idx, img = 0, first
        for k in range(n):
            slot = t0 + k / fps
            nxt = idx
            while nxt + 1 < len(frames) and frames[nxt + 1][0] <= slot + 0.5 / fps:
                nxt += 1
            if nxt != idx:
                idx = nxt
                img = _decode(frames[idx][2])
                if img.shape[:2] != (h, w):
                    img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
            writer.write(img)
    finally:
        writer.release()


def _decode(jpeg: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("kayıt karesi çözülemedi")
    return img


class ClipWriter:
    """Kayıtları arka planda yazar: tek iş parçacığı (ilk işte başlar), en çok `max_queue` bekleyen iş. `submit`
    asla engellemez; kuyruk doluysa iş düşer (günlüğe yazılır, kayıt `clip: false` kalır)."""

    def __init__(self, alarms: AlarmStore, fps: float | None = None, max_queue: int = QUEUE_MAX) -> None:
        self._alarms = alarms
        self._fps = CLIP_FPS if fps is None else fps
        self._q: queue.Queue[ClipJob | None] = queue.Queue(max_queue)
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._busy = 0                                  # kuyruktaki + yazılmakta olan işler
        self._thread: threading.Thread | None = None

    def submit(self, job: ClipJob) -> bool:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="olay-kaydi", daemon=True)
                self._thread.start()
            try:
                self._q.put_nowait(job)
                self._busy += 1
                return True
            except queue.Full:
                _LOG.warning("Olay kaydı kuyruğu dolu; kayıt yazılmayacak (%s)", ", ".join(job.ids))
        self._alarms.clip_failed(job.ids)
        return False

    def state(self, ids: Sequence[str], state: str) -> None:
        """Oturumun yakalama durumu: "failed" → kayıtlar `clipFailed` (bekleme biter)."""
        if state == "failed":
            self._alarms.clip_failed(ids)

    def drain(self, timeout: float) -> bool:
        """Bekleyen tüm işler bitene dek bekler (en çok `timeout` sn); bittiyse True."""
        deadline = time.monotonic() + timeout
        with self._idle:
            while self._busy:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._idle.wait(left)
        return True

    def stop(self, timeout: float = STOP_WAIT_S) -> None:
        """Bekleyen kayıtları yazmayı (en çok `timeout` sn) bekler, sonra iş parçacığını durdurur."""
        self.drain(timeout)
        with self._lock:
            t = self._thread
        if t is not None and t.is_alive():
            try:
                self._q.put(None, timeout=1)
            except queue.Full:
                return
            t.join(timeout=2)

    def _run(self) -> None:
        while True:
            job = self._q.get()
            if job is None:
                return
            try:
                self._write(job)
            except Exception:  # noqa: BLE001 — beklenmeyen hata: iş parçacığı ölmez
                _LOG.exception("Olay kaydı yazılamadı (%s)", ", ".join(job.ids))
            finally:
                with self._idle:
                    self._busy -= 1
                    self._idle.notify_all()

    def _write(self, job: ClipJob) -> None:
        """İlk kimlik için kodlar, diğerlerine kopyalar (geçici ad + atomik yeniden adlandırma); kayıtları işaretler,
        kaydı silinmiş kimliğin dosyasını kaldırır, en çok `MAX_CLIPS` sınırını uygular."""
        folder: Path = self._alarms.clips
        written: list[str] = []
        tmp: Path | None = None
        try:
            folder.mkdir(parents=True, exist_ok=True)
            first = job.ids[0]
            tmp = folder / f"{first}.tmp.webm"
            encode_webm(tmp, job.frames, self._fps)
            if not tmp.is_file() or tmp.stat().st_size == 0:
                raise RuntimeError("kodlayıcı boş dosya üretti")
            final = folder / f"{first}.webm"
            os.replace(tmp, final)
            written.append(first)
            for other in job.ids[1:]:
                tmp = folder / f"{other}.tmp.webm"
                shutil.copyfile(final, tmp)
                os.replace(tmp, folder / f"{other}.webm")
                written.append(other)
            tmp = None
        except Exception as e:  # noqa: BLE001 — disk dolu, kodlayıcı hatası…: kayıt clip: false kalır
            _LOG.error("Olay kaydı yazılamadı (%s): %s", ", ".join(job.ids), e)
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
            self._alarms.clip_failed([i for i in job.ids if i not in written])
        started = job.frames[0][1]
        for aid in written:
            if not self._alarms.set_clip(aid, started):         # kayıt bu arada silinmiş: dosya kalmasın
                try:
                    (folder / f"{aid}.webm").unlink(missing_ok=True)
                except OSError:
                    pass
        if written:
            self._alarms.enforce_clip_cap()
