"""Ağ akışı açılış sırası: öncelik (analiz oturumu > izleme > görüntü vermemiş izleme), süre sınırı ve dosya istisnası."""
from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Iterator
from typing import Any

import cv2
import pytest

from bantvision.live import open_gate, session
from bantvision.live import viewer as viewer_mod
from bantvision.live.open_gate import OpenGate


def _wait(fn: Any, timeout: float = 5.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if fn():
            return
        time.sleep(0.01)
    raise AssertionError("zaman aşımı")


def _queue_behind_holder(gate: OpenGate, levels: list[int]) -> list[int]:
    """Kapı tutulurken `levels` sırasıyla bekleyenler dizilir; bırakılınca giriş sırası döner."""
    entered: list[int] = []
    release = threading.Event()

    def holder() -> None:
        with gate.hold(open_gate.VIEWER):
            release.wait(5)

    def waiter(level: int) -> None:
        with gate.hold(level):
            entered.append(level)

    h = threading.Thread(target=holder)
    h.start()
    _wait(lambda: gate.waiting() == 0 and not release.is_set() and h.is_alive())
    threads = []
    for i, level in enumerate(levels):
        t = threading.Thread(target=waiter, args=(level,))
        t.start()
        threads.append(t)
        _wait(lambda n=i + 1: gate.waiting() == n)                 # her biri sıraya girdi (geliş sırası belli)
    release.set()
    for t in [h, *threads]:
        t.join(5)
    return entered


def test_session_opens_before_viewers_and_failed_viewers_go_last() -> None:
    order = _queue_behind_holder(OpenGate(), [open_gate.RETRY, open_gate.VIEWER, open_gate.RETRY, open_gate.SESSION])
    assert order == [open_gate.SESSION, open_gate.VIEWER, open_gate.RETRY, open_gate.RETRY]


def test_same_priority_keeps_arrival_order() -> None:
    gate = OpenGate()
    entered: list[str] = []
    release = threading.Event()

    def holder() -> None:
        with gate.hold(open_gate.VIEWER):
            release.wait(5)

    def waiter(name: str) -> None:
        with gate.hold(open_gate.VIEWER):
            entered.append(name)

    h = threading.Thread(target=holder)
    h.start()
    time.sleep(0.05)
    threads = []
    for i, name in enumerate("abc"):
        t = threading.Thread(target=waiter, args=(name,))
        t.start()
        threads.append(t)
        _wait(lambda n=i + 1: gate.waiting() == n)
    release.set()
    for t in [h, *threads]:
        t.join(5)
    assert entered == ["a", "b", "c"]


def test_gate_is_released_when_the_open_raises() -> None:
    gate = OpenGate()
    with pytest.raises(RuntimeError), gate.hold(open_gate.SESSION):
        raise RuntimeError("açılış patladı")
    done = threading.Event()

    def after() -> None:
        with gate.hold(open_gate.RETRY):
            done.set()

    threading.Thread(target=after).start()
    assert done.wait(2)


def test_priority_hint_is_per_thread_and_restored() -> None:
    assert open_gate.current_priority() == open_gate.VIEWER
    seen: list[int] = []
    with open_gate.priority(open_gate.RETRY):
        seen.append(open_gate.current_priority())
        t = threading.Thread(target=lambda: seen.append(open_gate.current_priority()))
        t.start()
        t.join()
    seen.append(open_gate.current_priority())
    assert seen == [open_gate.RETRY, open_gate.VIEWER, open_gate.VIEWER]


class _Recorder:
    """`cv2.VideoCapture` ve kapının yerine: hangi seçeneklerle, hangi öncelikle açıldığını kaydeder."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], int | None]] = []
        self.level: int | None = None

    @contextlib.contextmanager
    def hold(self, level: int) -> Iterator[None]:
        self.level = level
        try:
            yield
        finally:
            self.level = None

    def capture(self, url: str, *args: Any) -> str:
        self.calls.append((url, args, self.level))
        return "cap"


@pytest.fixture
def rec(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    r = _Recorder()
    monkeypatch.setattr(session.open_gate, "GATE", r)
    monkeypatch.setattr(session.cv2, "VideoCapture", r.capture)
    return r


def test_network_open_is_time_limited_and_goes_through_the_gate(rec: _Recorder) -> None:
    session.open_capture("rtsp://nvr/kanal", open_gate.SESSION)
    url, args, level = rec.calls[0]
    assert url == "rtsp://nvr/kanal" and level == open_gate.SESSION
    assert args == (cv2.CAP_FFMPEG, [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, session.OPEN_TIMEOUT_MS,
                                     cv2.CAP_PROP_READ_TIMEOUT_MSEC, session.READ_TIMEOUT_MS])
    assert session.OPEN_TIMEOUT_MS <= 10_000                       # OpenCV'nin 30 sn'lik varsayılanı değil


def test_open_without_level_uses_the_thread_hint(rec: _Recorder) -> None:
    session.open_capture("http://kamera/akis")
    with open_gate.priority(open_gate.RETRY):
        session.open_capture("rtsp://nvr/kapali")
    assert [c[2] for c in rec.calls] == [open_gate.VIEWER, open_gate.RETRY]


def test_local_file_is_opened_directly(rec: _Recorder) -> None:
    session.open_capture("C:/videolar/test.mp4")
    assert rec.calls == [("C:/videolar/test.mp4", (cv2.CAP_FFMPEG,), None)]


class _Cap:
    def __init__(self, frames: int) -> None:
        self._left = frames

    def isOpened(self) -> bool:
        return self._left >= 0

    def read(self) -> tuple[bool, Any]:
        if self._left <= 0:
            return False, None
        self._left -= 1
        import numpy as np

        return True, np.zeros((288, 352, 3), np.uint8)

    def release(self) -> None:
        pass


def test_viewer_without_frames_retries_at_the_lowest_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(viewer_mod, "_pause", lambda stop, s: stop.wait(0.01))
    plan = [-1, -1, 3, -1]                                         # açılmadı, açılmadı, 3 kare, açılmadı
    seen: list[int] = []

    def capture(url: str) -> _Cap:
        seen.append(open_gate.current_priority())
        return _Cap(plan[len(seen) - 1] if len(seen) <= len(plan) else -1)

    v = viewer_mod.CameraViewer(("nvr", "1", "sub"), lambda: "rtsp://nvr/1", None, capture, time.monotonic)
    try:
        _wait(lambda: len(seen) >= 5)
    finally:
        v.request_stop()
        v.join(2)
    assert seen[:5] == [open_gate.VIEWER, open_gate.RETRY, open_gate.RETRY, open_gate.VIEWER, open_gate.RETRY]
