"""Alarm olay kaydı (bantvision/live/clips.py): bellek içi ön kayıt (halka), alarm anında yakalama ve arka planda WebM
yazımı. Ağ yok, gerçek model yok: sentetik kareler ve sahte modeller."""
from __future__ import annotations

import logging
import pathlib
import threading
import time
from typing import Any

import cv2
import numpy as np
import pytest

from bantvision.live import clips
from bantvision.live.alarms import AlarmStore
from bantvision.live.clips import ClipBuffer, ClipJob, ClipWriter

ROOT = pathlib.Path(__file__).resolve().parents[3]
CLIP = ROOT / "apps" / "ios" / "BantSayacUITests" / "ui_test_clip.mp4"


def _frame(i: int, w: int = 320, h: int = 240) -> np.ndarray:
    f = np.full((h, w, 3), (i * 7) % 255, np.uint8)
    cv2.putText(f, str(i), (10, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 255), 3)
    return f


def _feed(buf: ClipBuffer, t0: float, t1: float, src_fps: float = 25.0, start: int = 0) -> int:
    """`t0`..`t1` (dahil değil) arasında `src_fps` hızında kare iter (okuyucu gibi); verilen kare sayısını döndürür."""
    n = 0
    t = t0
    while t < t1 - 1e-9:
        buf.push(_frame(start + n), t, 1_000_000.0 + t)          # duvar saati = 1e6 + tekdüze
        n += 1
        t = t0 + n / src_fps
    return n


def _count_frames(path: pathlib.Path) -> int:
    cap = cv2.VideoCapture(str(path))
    n = 0
    while True:
        ok, _ = cap.read()
        if not ok:
            break
        n += 1
    cap.release()
    return n


# ---------------------------------------------------------------------- halka (ön kayıt)

def test_ring_keeps_only_the_last_pre_seconds() -> None:
    buf = ClipBuffer(lambda _j: None)
    _feed(buf, 0.0, 20.0)
    ts = [t for t, _w, _j in buf.frames()]
    assert ts[-1] > 19.8
    assert ts[-1] - ts[0] <= clips.PRE_S + 1e-6                 # en eski kareler zamana göre düşer
    assert ts[-1] - ts[0] >= clips.PRE_S - 0.2


def test_ring_downsamples_reader_frames_to_clip_fps() -> None:
    buf = ClipBuffer(lambda _j: None)
    given = _feed(buf, 0.0, 8.0, src_fps=30.0)
    kept = buf.frames()
    assert given == 240
    assert 78 <= len(kept) <= 82                                 # ≤ 10 kare/sn (8 sn)
    gaps = np.diff([t for t, _w, _j in kept])
    assert gaps.min() >= 0.5 / clips.CLIP_FPS - 1e-6             # art arda iki kare yarım periyottan sık değil
    slow = ClipBuffer(lambda _j: None)                           # kaynak yavaşsa her kare tutulur
    assert _feed(slow, 0.0, 4.0, src_fps=5.0) == len(slow.frames()) == 20


def test_ring_stores_jpeg_scaled_down_to_1280_wide() -> None:
    buf = ClipBuffer(lambda _j: None)
    buf.push(_frame(1, 1920, 1080), 0.0, 5.0)
    buf.push(_frame(2, 640, 360), 1.0, 6.0)
    (t1, w1, j1), (t2, w2, j2) = buf.frames()
    assert (t1, w1, t2, w2) == (0.0, 5.0, 1.0, 6.0)
    assert j1[:2] == b"\xff\xd8" and j2[:2] == b"\xff\xd8"       # JPEG (bellek sınırlı)
    big = cv2.imdecode(np.frombuffer(j1, np.uint8), cv2.IMREAD_COLOR)
    small = cv2.imdecode(np.frombuffer(j2, np.uint8), cv2.IMREAD_COLOR)
    assert big.shape[:2] == (720, 1280) and small.shape[:2] == (360, 640)
    assert len(j1) < big.nbytes // 5                             # sıkıştırılmış


# ---------------------------------------------------------------------- yakalama

def test_capture_keeps_pre_buffer_and_collects_post_seconds_then_emits_once() -> None:
    jobs: list[ClipJob] = []
    buf = ClipBuffer(jobs.append)
    _feed(buf, 0.0, 10.0)
    buf.capture(["a" * 32, "b" * 32], 10.0)                       # aynı karede iki alarm: tek yakalama
    assert jobs == []                                            # sonrası henüz toplanmadı
    _feed(buf, 10.0, 13.9, start=1000)
    assert jobs == []
    _feed(buf, 13.9, 20.0, start=2000)
    assert len(jobs) == 1                                        # bir kez
    job = jobs[0]
    assert job.ids == ("a" * 32, "b" * 32)
    ts = [t for t, _w, _j in job.frames]
    assert ts == sorted(ts)
    assert abs(ts[0] - (10.0 - clips.PRE_S)) <= 0.2              # alarmdan 8 sn önce
    assert abs(ts[-1] - (10.0 + clips.POST_S)) <= 0.2            # alarmdan 4 sn sonra
    expected = (clips.PRE_S + clips.POST_S) * clips.CLIP_FPS
    assert abs(len(job.frames) - expected) <= 4
    assert job.frames[0][1] == pytest.approx(1_000_000.0 + ts[0])  # duvar saati kayıt başlangıcı için


def test_capture_without_post_part_emits_the_pre_buffer_at_once() -> None:
    jobs: list[ClipJob] = []
    buf = ClipBuffer(jobs.append)
    assert buf.capture(["c" * 32], 0.0, post_s=0.0) is False      # henüz kare yok: kayıt yok
    _feed(buf, 0.0, 5.0)
    assert buf.capture(["c" * 32], 5.0, post_s=0.0) is True
    assert len(jobs) == 1 and abs(len(jobs[0].frames) - 50) <= 2


def test_flush_emits_pending_capture_with_what_it_has() -> None:
    jobs: list[ClipJob] = []
    buf = ClipBuffer(jobs.append)
    _feed(buf, 0.0, 3.0)
    buf.capture(["d" * 32], 3.0)
    _feed(buf, 3.0, 4.0, start=500)
    buf.flush_due(4.0)                                           # süresi dolmadı: beklemede kalır
    assert jobs == []
    buf.flush_due(3.0 + clips.POST_S + 0.1)                      # kamera koptu, süre doldu: elindekiyle yazılır
    assert len(jobs) == 1 and abs(len(jobs[0].frames) - 40) <= 2
    buf.capture(["e" * 32], 4.0)
    buf.flush()                                                  # oturum durdu: hemen
    assert len(jobs) == 2 and jobs[1].ids == ("e" * 32,)


def test_sink_failure_never_reaches_the_reader(caplog: pytest.LogCaptureFixture) -> None:
    def boom(_j: ClipJob) -> None:
        raise RuntimeError("kuyruk bozuk")

    buf = ClipBuffer(boom)
    _feed(buf, 0.0, 2.0)
    with caplog.at_level(logging.ERROR):
        assert buf.capture(["f" * 32], 2.0, post_s=0.0) is True
    _feed(buf, 2.0, 3.0)                                         # okuyucu devam eder
    assert "kaydı" in caplog.text


# ---------------------------------------------------------------------- yazıcı

def _job(ids: tuple[str, ...], seconds: float = 12.0, fps: float = 10.0, w: int = 320, h: int = 240,
         jitter: float = 0.0) -> ClipJob:
    rng = np.random.default_rng(1)
    frames = []
    n = round(seconds * fps) + 1
    for i in range(n):
        t = i / fps + (rng.uniform(-jitter, jitter) if 0 < i < n - 1 else 0.0)
        ok, buf = cv2.imencode(".jpg", _frame(i, w, h), [cv2.IMWRITE_JPEG_QUALITY, 80])
        assert ok
        frames.append((t, 2_000_000.0 + t, buf.tobytes()))
    return ClipJob(ids, tuple(frames))


def test_writer_writes_readable_webm_and_marks_the_record(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    a = st.add("s1", "Tezgah", "hands_up", 1.0, 2.0, None, "disabled")
    assert a["clip"] is False and a["clipStartedAt"] is None
    w = ClipWriter(st)
    try:
        assert w.submit(_job((a["id"],), jitter=0.03))
        assert w.drain(30)
    finally:
        w.stop(10)
    path = st.clips / f"{a['id']}.webm"
    assert path.is_file() and path.stat().st_size > 1000
    n = _count_frames(path)
    expected = (clips.PRE_S + clips.POST_S) * clips.CLIP_FPS
    assert abs(n - expected) <= 3                                # sabit 10 kare/sn: süre duvar saatine eşit
    rec = st.get(a["id"])
    assert rec["clip"] is True and rec["clipStartedAt"] == pytest.approx(2_000_000.0)
    assert rec["clipPending"] is False and rec["clipFailed"] is False
    assert list(st.clips.glob("*.tmp.webm")) == []               # geçici dosya kalmadı
    assert AlarmStore(tmp_path).get(a["id"])["clip"] is True    # diske yazıldı


def test_alarms_of_the_same_frame_share_one_encode(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    st = AlarmStore(tmp_path)
    a = st.add("s1", "Tezgah", "hands_up", 1.0, 2.0, None, "disabled")
    b = st.add("s1", "Tezgah", "lying", 1.0, 2.0, None, "disabled")
    calls: list[pathlib.Path] = []
    real = clips.encode_webm

    def counting(path: pathlib.Path, frames: Any, fps: float) -> None:
        calls.append(path)
        real(path, frames, fps)

    monkeypatch.setattr(clips, "encode_webm", counting)
    w = ClipWriter(st)
    try:
        w.submit(_job((a["id"], b["id"]), seconds=2.0))
        assert w.drain(30)
    finally:
        w.stop(10)
    assert len(calls) == 1                                       # tek kodlama
    for x in (a, b):
        assert (st.clips / f"{x['id']}.webm").is_file() and st.get(x["id"])["clip"] is True


def test_resized_stream_mid_clip_is_written_at_first_frame_size(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    a = st.add("s1", "Tezgah", "hands_up", 1.0, 2.0, None, "disabled")
    first, second = _job(("x",), seconds=1.0, w=320, h=240), _job(("x",), seconds=1.0, w=640, h=360)
    frames = first.frames + tuple((t + 1.1, wall + 1.1, j) for t, wall, j in second.frames)
    w = ClipWriter(st)
    try:
        w.submit(ClipJob((a["id"],), frames))
        assert w.drain(30)
    finally:
        w.stop(10)
    cap = cv2.VideoCapture(str(st.clips / f"{a['id']}.webm"))
    ok, f = cap.read()
    cap.release()
    assert ok and f.shape[:2] == (240, 320) and st.get(a["id"])["clip"] is True


@pytest.mark.parametrize("failure", ["raise", "not_opened", "disk_full"])
def test_encoder_failure_leaves_clip_false_and_never_raises(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                                            caplog: pytest.LogCaptureFixture, failure: str) -> None:
    st = AlarmStore(tmp_path)
    a = st.add("s1", "Tezgah", "hands_up", 1.0, 2.0, None, "disabled")
    if failure == "raise":
        def broken(_p: pathlib.Path, _f: Any, _fps: float) -> None:
            raise RuntimeError("kodlayıcı çöktü")
        monkeypatch.setattr(clips, "encode_webm", broken)
    elif failure == "not_opened":
        class Closed:
            def __init__(self, *_a: Any) -> None: ...
            def isOpened(self) -> bool: return False
            def release(self) -> None: ...
        monkeypatch.setattr(clips.cv2, "VideoWriter", Closed)
    else:
        def full(_src: Any, _dst: Any) -> None:
            raise OSError(28, "No space left on device")
        monkeypatch.setattr(clips.os, "replace", full)
    w = ClipWriter(st)
    try:
        with caplog.at_level(logging.ERROR):
            assert w.submit(_job((a["id"],), seconds=1.0))
            assert w.drain(30)
        assert w.submit(_job((a["id"],), seconds=0.5))           # iş parçacığı yaşıyor
        assert w.drain(30)
    finally:
        w.stop(10)
    rec = st.get(a["id"])
    assert rec["clip"] is False and rec["clipStartedAt"] is None
    assert rec["clipFailed"] is True and rec["clipPending"] is False             # panel "Kayıt alınamadı" der
    assert "Olay kaydı yazılamadı" in caplog.text
    assert not (st.clips / f"{a['id']}.webm").exists()
    assert list(st.clips.glob("*.tmp.webm")) == []


def test_writer_queue_is_bounded_and_submit_never_blocks(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                                         caplog: pytest.LogCaptureFixture) -> None:
    st = AlarmStore(tmp_path)
    gate = threading.Event()

    def slow(path: pathlib.Path, frames: Any, fps: float) -> None:
        gate.wait(10)
        raise RuntimeError("yavaş")

    monkeypatch.setattr(clips, "encode_webm", slow)
    w = ClipWriter(st, max_queue=2)
    try:
        t = time.monotonic()
        with caplog.at_level(logging.WARNING):
            results = [w.submit(_job((f"{i:032x}",), seconds=0.2)) for i in range(6)]
        assert time.monotonic() - t < 1.0
        assert results[:3] == [True, True, True] or results.count(True) >= 2
        assert results[-1] is False and "kuyruğu dolu" in caplog.text
    finally:
        gate.set()
        w.stop(10)


def test_job_for_a_deleted_record_leaves_no_clip_file(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    w = ClipWriter(st)
    try:
        w.submit(_job(("9" * 32,), seconds=0.5))                 # kayıt yok (süresi doldu/silindi)
        assert w.drain(30)
    finally:
        w.stop(10)
    assert list(st.clips.iterdir()) == []


# ---------------------------------------------------------------------- oturum: okuyucudan dolar

def test_counting_sessions_keep_no_clip_buffer_and_safety_sessions_do() -> None:
    from fakes_safety import FakeDetector, FakePose

    from bantvision.core import Profile
    from bantvision.live.session import LiveSession

    sink: list[ClipJob] = []
    det, pose = FakeDetector([]), FakePose(None)
    s = LiveSession("t", lambda: "yok.mp4", Profile.people(), detector=det, pose=pose, clip_sink=sink.append)
    try:
        assert s._clips is None                                  # sayım: ek iş yok
        s.set_profile(Profile.jeweler())
        assert s._clips is not None                              # güvenliğe geçti
        s.set_profile(Profile.people())
        assert s._clips is None
    finally:
        s.stop()
    s2 = LiveSession("t", lambda: "yok.mp4", Profile.jeweler(), detector=det, pose=pose)
    try:
        assert s2._clips is None                                 # yazıcı yoksa tampon da yok
    finally:
        s2.stop()


def test_clip_buffer_is_filled_by_the_reader_not_the_slower_analysis() -> None:
    """Analiz yavaş (≈3 kare/sn) olsa da kayıt okuyucudan ≈10 kare/sn dolar: görüntü akıcı."""
    from fakes_safety import FakeDetector, FakePose

    from bantvision.core import Profile
    from bantvision.live.session import LiveSession

    class SlowPose(FakePose):
        def estimate(self, bgr: np.ndarray, box: object) -> np.ndarray | None:
            time.sleep(0.3)
            return super().estimate(bgr, box)

    s = LiveSession("t", lambda: str(CLIP), Profile.jeweler(), detector=FakeDetector([(280, 80, 360, 440)]),
                    pose=SlowPose(None), clip_sink=lambda _j: None)
    s.loop_file = True
    try:
        time.sleep(4.0)
        frames = s._clips.frames()
        span = frames[-1][0] - frames[0][0]
        assert span > 3.0
        assert len(frames) / span > 8.0                          # okuyucu hızında (≤ 10)
        assert len(frames) / span <= 11.0
        assert s.snapshot_status()["fps"] < 5.0                  # analiz çok daha yavaş
    finally:
        s.stop()


# ---------------------------------------------------------------------- düzeltme turu 1

def test_threaded_buffer_push_only_hands_over_the_frame_and_keeps_the_latest() -> None:
    """Canlı oturumda JPEG'e çevirme ayrı tek yuvalı iş parçacığında: okuyucunun `push`'u beklemez; çevirici meşgulken
    gelen kareler yuvada en yenisiyle değişir (aradakiler düşer), sıra korunur."""
    import time as _time

    buf = ClipBuffer(lambda _j: None, threaded=True)
    real = buf._encode
    started = threading.Event()

    def slow(frame: np.ndarray) -> bytes | None:
        started.set()
        _time.sleep(0.3)
        return real(frame)

    buf._encode = slow                                                            # type: ignore[method-assign]
    try:
        t0 = _time.monotonic()
        buf.push(_frame(0), 0.0, 100.0)
        assert started.wait(2)                                                    # çevirici ilk karede meşgul
        for i in range(1, 5):                                                     # 4 kare (zamanı gelmiş) daha
            buf.push(_frame(i), i * 0.2, 100.0 + i * 0.2)
        assert _time.monotonic() - t0 < 0.25                                      # okuyucu hiç beklemedi
        assert buf.wait_idle(5)
        ts = [t for t, _w, _j in buf.frames()]
        assert ts == [0.0, 0.8]                                                   # ilk ve en yeni; aradakiler düştü
    finally:
        buf.close()
    assert buf._thread is not None and not buf._thread.is_alive()


def test_threaded_buffer_feeds_captures_in_order_and_completes() -> None:
    jobs: list[ClipJob] = []
    buf = ClipBuffer(jobs.append, threaded=True)
    try:
        for i in range(50):                                                       # 5 sn, 10 kare/sn (gerçek zamanlı gibi)
            buf.push(_frame(i), i / 10, 1000 + i / 10)
            buf.wait_idle(2)
        buf.capture(["a" * 32], 5.0, post_s=1.0)
        for i in range(50, 65):
            buf.push(_frame(i), i / 10, 1000 + i / 10)
            buf.wait_idle(2)
        assert len(jobs) == 1
        ts = [t for t, _w, _j in jobs[0].frames]
        assert ts == sorted(ts) and ts[0] >= 5.0 - clips.PRE_S - 1e-9 and abs(ts[-1] - 6.0) < 1e-6
    finally:
        buf.close()


def test_capture_that_gets_no_frames_is_reported_failed() -> None:
    """Yakalama alınamazsa (görüntü yok, yazıcıya verilemedi) kayıt "alınamadı" olarak bildirilir."""
    failed: list[tuple[list[str], str]] = []
    buf = ClipBuffer(lambda _j: None, state=lambda ids, st: failed.append((list(ids), st)))
    assert buf.capture(["a" * 32], 1.0, post_s=0.0) is False                    # ön kayıt boş, sonrası yok
    buf.capture(["b" * 32], 1.0, post_s=1.0)
    buf.flush_due(3.0)                                                            # kare hiç gelmedi
    assert failed == [(["a" * 32], "failed"), (["b" * 32], "failed")]

    def boom(_j: ClipJob) -> None:
        raise RuntimeError("yazıcı yok")

    bad = ClipBuffer(boom, state=lambda ids, st: failed.append((list(ids), st)))
    _feed(bad, 0.0, 1.0)
    bad.capture(["c" * 32], 1.0, post_s=0.0)
    assert failed[-1] == (["c" * 32], "failed")


def test_full_writer_queue_marks_the_record_failed(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    st = AlarmStore(tmp_path)
    gate = threading.Event()

    def slow(path: pathlib.Path, frames: Any, fps: float) -> None:
        gate.wait(10)
        raise RuntimeError("yavaş")

    monkeypatch.setattr(clips, "encode_webm", slow)
    recs = [st.add("s", "Tezgah", "hands_up", 1.0, 2.0, None, "disabled", clip_pending=True) for _ in range(5)]
    w = ClipWriter(st, max_queue=1)
    try:
        results = [w.submit(_job((r["id"],), seconds=0.2)) for r in recs]
        dropped = [r["id"] for r, ok in zip(recs, results, strict=True) if not ok]
        assert dropped
        for aid in dropped:
            got = st.get(aid)
            assert got["clipPending"] is False and got["clipFailed"] is True
    finally:
        gate.set()
        w.stop(10)
