"""Canlı sayım oturumu (web paneli): ağ kamerası / kayıt cihazı → sayım hattı → işaretli canlı görüntü.

Telefondaki canlı sayımın (FrameProcessor + CountingViewModel) sunucu karşılığı. Görüntü yalnızca bu bilgisayarda
işlenir; tarayıcıya yerel ağdan işaretli kare gider, hiçbir yere kaydedilmez.

İki iş parçacığı:
- okuyucu: kaynaktan sürekli kare çeker, yalnızca en yenisini tutar (sayım hiçbir zaman eski kare kuyruğunda
  gecikmez); koparsa artan beklemeyle yeniden bağlanır, her bağlanışta adres yeniden alınır (TRASSIR jetonu);
- işleyici: en yeni kareyi sayım hattından geçirir, işaretli kareyi (en çok ~12/sn) JPEG olarak hazırlar.
"""
from __future__ import annotations

import contextlib
import csv
import dataclasses
import io
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from ..core import Pipeline, Profile
from ..core.pipeline import FrameResult
from ..core.staff_color import teach_bgr
from ..overlay import draw_detect, draw_safety
from ..video import draw, number_label, split_numbers

_LOG = logging.getLogger(__name__)

# Canlı akışta FFmpeg'e RTSP üzerinden TCP (kayıpsız, NVR'larla uyumlu) ve kısa zaman aşımı
# FFmpeg 5+ (OpenCV 4.6+): `timeout` = bağlanma ve okuma zaman aşımı (µs). Eski `stimeout` artık yok sayılıyor;
# kapalı kamerada açılış 30 sn takılıyordu.
_FFMPEG_OPTIONS = "rtsp_transport;tcp|timeout;5000000"


@dataclass
class SessionStatus:
    state: str = "connecting"               # connecting | live | reconnecting | ended | error | stopped
    message: str = ""
    fps: float = 0.0
    width: int = 0
    height: int = 0


@dataclass
class _Counts:
    total: int = 0
    total_out: int = 0
    per_minute: dict[int, int] = field(default_factory=dict)        # dakika (epoch // 60) → giriş/adet
    per_minute_out: dict[int, int] = field(default_factory=dict)
    events: list[tuple[float, int, str, int, int]] = field(default_factory=list)  # (epoch, iz, yön, toplam, çıkış)
    staff_in: int = 0                       # §4.10 eki: personel geçişleri (giriş/çıkışa eklenmez)
    staff_out: int = 0


@dataclass(frozen=True)
class _Snapshot:
    """İşlenen kare ve o karenin tanıma kutuları (normalize). Değişmez: başvuru takası atomiktir."""
    frame: np.ndarray
    boxes: tuple[tuple[float, float, float, float], ...]


def fps_from_stamps(stamps: list[float]) -> float:
    """İşlenen karelerin (en çok son 2 sn) damgalarından kare hızı. Windows saati kaba (~15 ms): hızlı işleme (sahte
    tanıyıcı, boş sahne) aynı damgayı üretebilir; sıfıra bölme çalışma iş parçacığını öldürürdü."""
    span = stamps[-1] - stamps[0] if stamps else 0.0
    return (len(stamps) - 1) / span if len(stamps) > 2 and span > 0 else 0.0


def open_capture(url: str) -> cv2.VideoCapture:
    """RTSP için FFmpeg seçenekleri; dosya/HTTP adresleri olduğu gibi açılır."""
    import os

    if url.lower().startswith("rtsp://"):
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = _FFMPEG_OPTIONS
    return cv2.VideoCapture(url, cv2.CAP_FFMPEG)


class LiveSession:
    """Bir kameranın canlı sayımı. Tüm genel yöntemler iş parçacığı güvenlidir."""

    def __init__(self, name: str, open_url: Callable[[], str], profile: Profile,
                 keep_alive: Callable[[str], None] | None = None, realtime_file: bool = True,
                 detector: Any | None = None, pose: Any | None = None,
                 alarm_sink: Callable[[LiveSession, list[Any], list[tuple[int, str, bool]], bytes | None], None]
                 | None = None) -> None:
        """`detector`: kişi tanıma modeli, `pose`: poz modeli (ikisi de birden çok kamerada ortak; yoksa ilk karede
        yüklenir). `alarm_sink(oturum, doğan alarmlar, biten bölümler, olay resmi)`: poz güvenlik alarmları (çalışma
        iş parçacığından, sayım kilidi dışında çağrılır); çalışma döngüsü biterken açık alarmların sonu da buradan gelir."""
        self.id = str(uuid.uuid4())
        self.name = name
        self.created = time.time()
        self._open_url = open_url
        self._keep_alive = keep_alive
        self._realtime_file = realtime_file
        self.loop_file = False                              # yerel video kaynağı bitince başa sarsın mı
        self._lock = threading.RLock()                       # sayım hattı ve durum
        self._frame_cv = threading.Condition(threading.Lock())  # kare alışverişi (okuyucu sayımı beklemesin)
        self.profile = profile
        self._pipe = Pipeline(profile)
        self._pipe.detect.enable_gate()                     # boş sahnede tanıma atlanır: çok kamerada işlemci paylaşımı
        self._detector = detector
        self._pose = pose
        self._alarm_sink = alarm_sink
        self._last_alarm_at: float | None = None
        if detector is not None:
            self._pipe.detect._detector = detector
        if profile.countMode == "safety":
            self._setup_safety()
        self._warm(profile)
        self.counting = False
        self.status = SessionStatus()
        self.calibrating: str | None = None         # "background" | "sample" | None
        self.calibration_message = ""
        self._counts = _Counts()
        self._latest: tuple[int, float, np.ndarray] | None = None   # (sıra, zaman, kare)
        self._seq = 0
        self._jpeg: bytes | None = None
        self._jpeg_seq = 0
        self._raw_jpeg_at = 0.0
        self._flash = 0.0
        self._flash_in = True
        self._numbers: dict[int, list[int]] = {}
        self._labels: dict[int, str] = {}
        # Personel rengi öğretme (§4.10 eki): işlenen kare ve o karenin tanıma kutuları tek çift olarak tutulur.
        # `raw_jpeg` son işlenen çiftin karesini verir ve onu "öğretme anlık görüntüsü" olarak hatırlar; öğretme o
        # çiftten örnekler — kullanıcının tıkladığı kare ile örneklenen pikseller/kutular aynıdır.
        self._processed: _Snapshot | None = None
        self._teach_snapshot: _Snapshot | None = None
        self._stop = threading.Event()
        self._switch = threading.Event()                    # akış değişti (alt/ana): okuyucu yeniden bağlansın
        self._reader = threading.Thread(target=self._read_loop, name=f"live-read-{self.id[:8]}", daemon=True)
        self._worker = threading.Thread(target=self._work_loop, name=f"live-work-{self.id[:8]}", daemon=True)
        self._reader.start()
        self._worker.start()

    # ------------------------------------------------------------------ kontrol

    def stop(self) -> None:
        self._stop.set()
        with self._frame_cv:
            self._frame_cv.notify_all()
        self._reader.join(timeout=5)
        self._worker.join(timeout=5)
        with self._lock:
            self.status.state = "stopped"
            self._pipe.detect._detector = None              # tanıma modeli ve iş parçacıkları bırakılsın

    def switch_source(self, open_url: Callable[[], str], keep_alive: Callable[[str], None] | None = None) -> None:
        """Görüntü kaynağını değiştirir (ör. alt ↔ ana akış). Sayaçlar, izler ve ayarlar korunur; okuyucu yeni
        adrese bağlanır. Kare boyutu değişirse bant sayımı arka planı yeniden öğrenir (sayaçlar yine korunur)."""
        with self._lock:
            self._open_url, self._keep_alive = open_url, keep_alive
            self.status.state, self.status.message = "reconnecting", "Görüntü akışı değiştiriliyor…"
        self._switch.set()

    def set_counting(self, on: bool) -> None:
        with self._lock:
            self.counting = on
            self._pipe.counting = on

    def reset(self) -> None:
        with self._lock:
            self._pipe.reset_count()
            self._counts = _Counts()
            self._numbers.clear()
            self._labels.clear()

    def set_profile(self, profile: Profile) -> None:
        """Alan, çizgi, yön, yöntem değişince: izler sıfırlanır, arka plan korunur (yöntem değişirse yenilenir)."""
        with self._lock:
            mode_changed = profile.countMode != self.profile.countMode
            self.profile = profile
            self._pipe.set_profile(profile, reset_background=mode_changed)
            if profile.countMode == "safety" and (mode_changed or self._pipe.safety is None):
                self._setup_safety()                        # güvenliğe geçiş: ortak modellerle taze analizör
            self._warm(profile)
            self._numbers.clear()
            self._labels.clear()
        if mode_changed:                                    # kutular eski yöntemle bulundu: öğretmede kullanılmasın
            with self._frame_cv:
                self._processed = self._teach_snapshot = None

    def _setup_safety(self) -> None:
        """Poz güvenlik analizörü: oturumun (ortak) tanıma ve poz modelleriyle; boş sahnede tanıma atlanır."""
        from ..core.safety import SafetyAnalyzer

        self._pipe.safety = SafetyAnalyzer(detector=self._detector, pose=self._pose)
        self._pipe.safety.enable_gate()

    def _warm(self, profile: Profile) -> None:
        """Ortak modeller ilk kişiyi/kareyi beklemeden arka planda yüklenmeye başlar: kişi sayımı ve güvenlik tanıma
        modelini, güvenlik ayrıca poz modelini kullanır (bant sayımı hiçbirini). Model hazırsa bir şey yapılmaz."""
        models = []
        if profile.countMode in ("detect", "safety"):
            models.append(self._detector)
        if profile.countMode == "safety":
            models.append(self._pose)
        for m in models:
            warm = getattr(m, "warm", None)
            if callable(warm):
                warm()

    def learn_background(self) -> None:
        with self._lock:
            self._pipe.start_background_learning(update_threshold=True)
            self.calibrating = "background"
            self.calibration_message = "Boş bant öğreniliyor… Bantta ürün olmasın."

    def learn_sample(self) -> None:
        with self._lock:
            self._pipe.start_sample_learning(8)
            self.calibrating = "sample"
            self.calibration_message = ("Ürün boyu öğreniliyor… Ürünler bantta normal akışında geçsin (bitişik olabilir)."
                                        if self.profile.countMode == "linescan"
                                        else "Ürünleri TEK TEK ve aralıklı geçir: 0/8")

    def cancel_calibration(self) -> None:
        with self._lock:
            self._pipe.cancel_calibration()
            self.calibrating = None
            self.calibration_message = ""

    def teach_staff_color(self, x: float, y: float) -> tuple[float, float, float] | None:
        """Tıklanan noktadaki kişinin gövde rengi (§4.10 eki). Çok karanlıksa None; henüz işlenen kare yoksa
        LookupError. Örnek, panelde gösterilen kareden (`raw_jpeg`'in son verdiği) ve o karenin kutularından alınır;
        hiç kare verilmediyse son işlenen kareden. Sayım hattının kilidi beklenmez."""
        with self._frame_cv:
            snap = self._teach_snapshot or self._processed
        if snap is None:
            raise LookupError("kare yok")
        return teach_bgr(snap.frame, list(snap.boxes), (x, y), self.profile.countAnchor)

    # ------------------------------------------------------------------ okuma

    def snapshot_status(self) -> dict[str, Any]:
        with self._lock:
            c = self._counts
            now_min = int(time.time() // 60)
            rate = c.per_minute.get(now_min, 0) + c.per_minute.get(now_min - 1, 0)
            return {
                "id": self.id, "name": self.name, "createdAt": self.created,
                "state": self.status.state, "message": self.status.message,
                "fps": round(self.status.fps, 1), "width": self.status.width, "height": self.status.height,
                "counting": self.counting, "total": c.total, "totalOut": c.total_out,
                "staffIn": c.staff_in, "staffOut": c.staff_out,
                "twoWay": self.profile.countMode == "detect",
                "safety": ({"active": [{"type": k, "trackId": tid, "seconds": round(sec, 1)}
                                       for tid, k, sec, _f in (self._pipe.safety.episodes.active()
                                                               if self._pipe.safety else [])],
                            "lastAlarmAt": self._last_alarm_at,
                            "model": getattr(self._pose, "state", "ready")}      # "loading" | "ready" | "error"
                           if self.profile.countMode == "safety" else None),
                "ratePerMinute": rate // 2 if rate else 0,
                "calibrating": self.calibrating, "calibrationMessage": self.calibration_message,
                "profile": self.profile.to_dict(),
            }

    def jpeg(self, after: int = 0, timeout: float = 2.0) -> tuple[int, bytes | None]:
        """`after`'dan yeni işaretli kare (MJPEG akışı); yoksa `timeout` kadar bekler."""
        deadline = time.monotonic() + timeout
        with self._frame_cv:
            while self._jpeg_seq <= after and not self._stop.is_set():
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                self._frame_cv.wait(left)
            return self._jpeg_seq, self._jpeg

    def raw_jpeg(self) -> bytes | None:
        """İşaretsiz son işlenen kare (kalibrasyon düzenleyicisinin arka planı). Verilen kare, kutularıyla birlikte
        personel rengi öğretmesinin örnekleyeceği kare olarak hatırlanır. Henüz işlenen kare yoksa son okunan kare
        (öğretme anlık görüntüsü değişmez)."""
        with self._frame_cv:
            snap = self._processed
            if snap is not None:
                self._teach_snapshot = snap
                img = snap.frame
            elif self._latest is not None:
                img = self._latest[2]
            else:
                return None
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return buf.tobytes() if ok else None

    def counts_csv(self) -> str:
        with self._lock:
            events = list(self._counts.events)
            two_way = self.profile.countMode == "detect"
        out = io.StringIO()
        w = csv.writer(out, delimiter=";")
        if two_way:
            w.writerow(["zaman", "iz", "yon", "giris_toplam", "cikis_toplam"])
            for ts, tid, direction, tin, tout in events:
                w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)), tid, direction, tin, tout])
        else:
            w.writerow(["zaman", "iz", "delta", "toplam"])
            for ts, tid, _, total, _ in events:
                w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)), tid, 1, total])
        return out.getvalue()

    # ------------------------------------------------------------------ iş parçacıkları

    def _read_loop(self) -> None:
        backoff = 1.0
        file_offset = 0.0                                    # dosya başa sarınca zaman geriye gitmesin
        while not self._stop.is_set():
            self._switch.clear()
            try:
                with self._lock:
                    open_url = self._open_url
                url = open_url()
            except Exception as e:  # noqa: BLE001 — adres alınamadı (kayıt cihazı yanıt vermedi); yeniden denenir
                self._set_state("reconnecting", f"Kaynağa ulaşılamadı: {e}")
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 15.0)
                continue
            cap = open_capture(url)
            if not cap.isOpened():
                cap.release()
                self._set_state("reconnecting", "Görüntü açılamadı; yeniden deneniyor.")
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 15.0)
                continue
            is_file = not url.lower().startswith(("rtsp://", "http://", "https://"))
            file_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            self._set_state("live", "")
            backoff = 1.0
            started = time.monotonic()
            last_ping = time.monotonic()
            n = 0
            while not self._stop.is_set() and not self._switch.is_set():
                ok, frame = cap.read()
                if not ok:
                    break
                n += 1
                ts = file_offset + n / file_fps if is_file else time.monotonic()
                with self._frame_cv:
                    self._seq += 1
                    self._latest = (self._seq, ts, frame)
                    self._frame_cv.notify_all()
                if is_file and self._realtime_file:          # dosya: gerçek zamanlı oynat (canlı kamera gibi)
                    lag = n / file_fps - (time.monotonic() - started)
                    if lag > 0:
                        self._stop.wait(lag)
                if self._keep_alive and time.monotonic() - last_ping > 5:
                    last_ping = time.monotonic()
                    threading.Thread(target=self._ping, args=(url,), daemon=True).start()
            cap.release()
            if self._stop.is_set():
                return
            if self._switch.is_set():                       # akış değişti: beklemeden yeni adrese
                continue
            if is_file:
                if self.loop_file:                          # test/gösterim: video başa sarar, canlı kamera gibi
                    file_offset += n / file_fps
                    continue
                self._set_state("ended", "Video bitti.")
                return
            self._set_state("reconnecting", "Görüntü kesildi; yeniden bağlanılıyor.")
            self._stop.wait(backoff)
            backoff = min(backoff * 2, 15.0)

    def _ping(self, url: str) -> None:
        # Canlı tutma isteği başarısızsa akış zaten kopar ve yeniden bağlanılır
        with contextlib.suppress(Exception):
            if self._keep_alive:
                self._keep_alive(url)

    def _set_state(self, state: str, message: str) -> None:
        with self._lock:
            self.status.state = state
            self.status.message = message

    def _work_loop(self) -> None:
        try:
            self._work()
        finally:
            self._end_safety()

    def _end_safety(self) -> None:
        """Çalışma döngüsü bitti (oturum durduruldu ya da döngü çöktü): alarm vermiş açık bölümler sona erer; alarm
        günlüğünde sonsuza dek "açık" kalmasın."""
        if self._alarm_sink is None:
            return
        with self._lock:
            an = self._pipe.safety
            ended = an.end_all() if an else []              # açık alarmlı bölümler + reset() ile kesilip bildirilmemişler
        if ended:
            try:
                self._alarm_sink(self, [], ended, None)
            except Exception:  # noqa: BLE001 — kapanışta alıcı hatası yutulur (günlüğe yazılır)
                _LOG.exception("Alarm alıcısı kapanışta hata verdi (oturum %s)", self.id[:8])

    def _notify_safety(self, r: FrameResult, frame: np.ndarray, profile: Profile) -> None:
        """Doğan alarmlar ve biten bölümler alarm alıcısına (sayım kilidi dışında). Resim ya da alıcı hatası oturumu
        düşürmez: resim alınamazsa alarm resimsiz iletilir."""
        sr = r.safety
        if sr is None or not (sr.fired or sr.ended) or self._alarm_sink is None:
            return
        jpeg: bytes | None = None
        if sr.fired:
            with self._lock:
                self._last_alarm_at = time.time()
            try:
                ok, buf = cv2.imencode(".jpg", self._render(frame.copy(), profile, r), [cv2.IMWRITE_JPEG_QUALITY, 85])
                jpeg = buf.tobytes() if ok else None
            except Exception:  # noqa: BLE001
                _LOG.exception("Alarm resmi hazırlanamadı (oturum %s)", self.id[:8])
        try:
            self._alarm_sink(self, sr.fired, sr.ended, jpeg)
        except Exception:  # noqa: BLE001
            _LOG.exception("Alarm alıcısı hata verdi (oturum %s)", self.id[:8])

    def _work(self) -> None:
        done = 0
        last_render = 0.0
        shape: tuple[int, ...] | None = None
        stamps: list[float] = []
        while not self._stop.is_set():
            with self._frame_cv:
                while (self._latest is None or self._latest[0] <= done) and not self._stop.is_set():
                    self._frame_cv.wait(0.5)
                if self._stop.is_set():
                    return
                assert self._latest is not None
                seq, ts, frame = self._latest
            done = seq
            with self._lock:
                profile = self.profile
                if shape is not None and frame.shape != shape and profile.countMode != "detect":
                    self._pipe.set_profile(profile, reset_background=True)   # akış değişti: arka plan yeni boyutta
                shape = frame.shape
                try:
                    r = self._pipe.process(frame, ts)
                except Exception as e:                       # noqa: BLE001 — tek karelik hata oturumu düşürmesin
                    self.status.message = f"İşleme hatası: {e}"
                    continue
                self._after_frame(r, frame)
            self._notify_safety(r, frame, profile)
            now = time.monotonic()
            stamps = [s for s in stamps if now - s < 2.0] + [now]
            with self._lock:
                self.status.fps = fps_from_stamps(stamps)
                self.status.height, self.status.width = frame.shape[:2]
            if now - last_render >= 1 / 12:
                last_render = now
                img = self._render(frame.copy(), profile, r)
                ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok:
                    with self._frame_cv:
                        self._jpeg = buf.tobytes()
                        self._jpeg_seq += 1
                        self._frame_cv.notify_all()

    def _after_frame(self, r: FrameResult, frame: np.ndarray) -> None:
        """Kalibrasyon olayları ve sayımlar (kilit altında)."""
        for kind, value in r.calibration:
            self._calibration_event(kind, value)
        now = time.time()
        minute = int(now // 60)
        c = self._counts
        if self.profile.countMode == "detect":
            n_in = self._pipe.total - len(r.counts)
            n_out = self._pipe.total_out - len(r.counts_out)
            for e in r.counts:
                n_in += 1
                self._labels[e.track_id] = f"G{n_in}"
                c.per_minute[minute] = c.per_minute.get(minute, 0) + 1
                c.events.append((now, e.track_id, "giris", n_in, n_out))
                self._flash, self._flash_in = 0.35, True
            for e in r.counts_out:
                n_out += 1
                self._labels[e.track_id] = f"Ç{n_out}"
                c.per_minute_out[minute] = c.per_minute_out.get(minute, 0) + 1
                c.events.append((now, e.track_id, "cikis", n_in, n_out))
                self._flash, self._flash_in = 0.35, False
            for tid, d in r.staff_events:
                self._labels[tid] = "P"
                if d > 0:
                    c.staff_in += 1
                else:
                    c.staff_out += 1
                c.events.append((now, tid, "personel_giris" if d > 0 else "personel_cikis", n_in, n_out))
            alive = {t.id for t in self._pipe.detect.tracker.tracks}
            self._labels = {i: lab for i, lab in self._labels.items() if i in alive}
        else:
            split_numbers(self._numbers, self._pipe.tracker.last_splits)
            running = self._pipe.total - sum(e.delta for e in r.counts)
            for e in r.counts:
                self._numbers.setdefault(e.track_id, []).extend(range(running + 1, running + e.delta + 1))
                running += e.delta
                c.per_minute[minute] = c.per_minute.get(minute, 0) + e.delta
                c.events.append((now, e.track_id, "", running, 0))
                self._flash, self._flash_in = 0.25, True
            live = {m.id for m in r.tracks}
            self._numbers = {tid: ns for tid, ns in self._numbers.items() if tid in live}
            self._labels = {tid: number_label(ns) for tid, ns in self._numbers.items()}
        c.total, c.total_out = self._pipe.total, self._pipe.total_out
        if len(c.events) > 20000:                            # uzun oturumda bellek sınırlı (CSV son 20 bin olay)
            del c.events[: len(c.events) - 20000]
        self._flash = max(0.0, self._flash - 1 / max(5.0, r.fps or 25.0))
        boxes = tuple((float(b[0]), float(b[1]), float(b[2]), float(b[3])) for b, _ in r.detect.detections)             if r.detect is not None else ()
        snap = _Snapshot(frame, boxes)
        with self._frame_cv:                                 # kısa kilit: öğretme sayım hattını beklemez
            self._processed = snap

    def _calibration_event(self, kind: str, value: Any) -> None:
        p = self.profile
        if kind == "background_progress":
            self.calibration_message = f"Boş bant öğreniliyor… %{int(float(value) * 100)}"
        elif kind == "background_done":
            self.calibrating = None
            if p.countMode == "blob":
                self.calibration_message = f"Arka plan hazır (eşik {value}). Şimdi örnek ürün geçir."
            else:
                self.calibration_message = ""
        elif kind == "background_rejected":
            self.calibrating = None
            self.calibration_message = ("Boş bant öğrenilemedi: bantta ürün ya da hareket vardı. Eşik değiştirilmedi; "
                                        "bant boşken tekrar dene.")
        elif kind == "sample_progress":
            done, target = value
            self.calibration_message = f"Ürünleri TEK TEK ve aralıklı geçir: {done}/{target}"
        elif kind == "sample_done":
            self.calibrating = None
            self.calibration_message = (
                f"Ürün boyu öğrenildi (alanın %{float(value) * 100:.0f}'i). Kontrol edip Kaydet'e bas."
                if p.countMode == "linescan" else "Ürün boyutu öğrenildi. Kontrol edip Kaydet'e bas.")

    def _render(self, frame: np.ndarray, profile: Profile, r: FrameResult) -> np.ndarray:
        with self._lock:
            labels = dict(self._labels)
            flash, flash_in = self._flash, self._flash_in
            total, total_out = self._pipe.total, self._pipe.total_out
        scale = np.ones(3)                                    # poz eklemleri piksel: büyütmeyle birlikte ölçeklenir
        if frame.shape[1] < 720:                              # alt akış (352–640 px): çizim tarayıcıda net görünsün
            h0, w0 = frame.shape[:2]
            frame = cv2.resize(frame, (720, round(h0 * 720 / w0)), interpolation=cv2.INTER_LINEAR)
            scale = np.array([frame.shape[1] / w0, frame.shape[0] / h0, 1.0])
        if profile.countMode == "safety":
            sr = r.safety
            if sr is not None and not np.all(scale == 1.0):
                sr = dataclasses.replace(sr, poses={tid: kp * scale for tid, kp in sr.poses.items()})
            img = draw_safety(frame, profile, sr)
        elif profile.countMode == "detect":
            img = draw_detect(frame, profile, r.detect, total, total_out, 0.0, flash, flash_in, labels, panel=False)
        else:
            img = draw(frame, profile, r, flash, labels, panel=False)   # sayılar panelin yan tarafında
        w = img.shape[1]
        if w > 1280:                                          # tarayıcıya yeterli; yerel ağ dostu
            img = cv2.resize(img, (1280, round(img.shape[0] * 1280 / w)), interpolation=cv2.INTER_AREA)
        return img
