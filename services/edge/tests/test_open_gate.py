"""Ağ akışı açılış sırası: öncelik, iç içe giriş, adresin kapı içinde alınması, süre sınırı ve dosya istisnası."""
from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Iterator
from typing import Any

import cv2
import numpy as np
import pytest

from bantvision.core import Profile
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


@contextlib.contextmanager
def _held(gate: OpenGate) -> Iterator[threading.Event]:
    """Başka bir iş parçacığı kapıyı tutar (girdiği kesin); blok bitince bırakır."""
    entered, release = threading.Event(), threading.Event()

    def holder() -> None:
        with gate.hold(open_gate.VIEWER):
            entered.set()
            release.wait(5)

    h = threading.Thread(target=holder)
    h.start()
    assert entered.wait(5)
    try:
        yield release
    finally:
        release.set()
        h.join(5)


def _order_behind_holder(gate: OpenGate, items: list[tuple[str, int]]) -> list[str]:
    """Kapı tutulurken `items` sırasıyla sıraya girer; bırakılınca giriş sırası döner."""
    entered: list[str] = []

    def waiter(name: str, level: int) -> None:
        with gate.hold(level):
            entered.append(name)

    threads = []
    with _held(gate):
        for i, (name, level) in enumerate(items):
            t = threading.Thread(target=waiter, args=(name, level))
            t.start()
            threads.append(t)
            _wait(lambda n=i + 1: gate.waiting() == n)              # her biri sırada (geliş sırası belli)
    for t in threads:
        t.join(5)
    return entered


def test_priority_order_sessions_viewers_then_failed_sessions_then_failed_viewers() -> None:
    order = _order_behind_holder(OpenGate(), [("ölü izleme", open_gate.RETRY), ("izleme", open_gate.VIEWER),
                                              ("ölü oturum", open_gate.SESSION_RETRY),
                                              ("ölü izleme 2", open_gate.RETRY), ("oturum", open_gate.SESSION)])
    assert order == ["oturum", "izleme", "ölü oturum", "ölü izleme", "ölü izleme 2"]


def test_same_priority_keeps_arrival_order() -> None:
    order = _order_behind_holder(OpenGate(), [(n, open_gate.VIEWER) for n in "abc"])
    assert order == ["a", "b", "c"]


def test_holder_can_reenter_and_others_wait_for_the_outer_block() -> None:
    gate = OpenGate()
    other = threading.Event()

    def later() -> None:
        with gate.hold(open_gate.SESSION):
            other.set()

    with gate.hold(open_gate.VIEWER):
        with gate.hold(open_gate.SESSION):                         # iç içe: sıraya girmez, takılmaz
            assert gate.held_by_current_thread()
        t = threading.Thread(target=later)
        t.start()
        _wait(lambda: gate.waiting() == 1)
        assert not other.wait(0.1)                                 # iç blok bitti ama dış blok sürüyor
    t.join(5)
    assert other.is_set() and not gate.held_by_current_thread()


def test_gate_is_released_when_the_open_raises() -> None:
    gate = OpenGate()
    with pytest.raises(RuntimeError), gate.hold(open_gate.SESSION):
        raise RuntimeError("açılış patladı")
    with gate.hold(open_gate.RETRY):
        assert gate.held_by_current_thread()


def test_an_interrupted_waiter_leaves_the_queue_and_the_next_one_enters() -> None:
    gate = OpenGate()
    real_wait = gate._cv.wait

    def wait(timeout: float | None = None) -> bool:
        if threading.current_thread().name == "kesilen":
            raise KeyboardInterrupt
        return real_wait(timeout)

    gate._cv.wait = wait  # type: ignore[method-assign]
    errors: list[BaseException] = []
    entered = threading.Event()

    def interrupted() -> None:
        try:
            with gate.hold(open_gate.SESSION):
                pass
        except BaseException as e:  # noqa: BLE001 — testte beklenen kesinti
            errors.append(e)

    def next_one() -> None:
        with gate.hold(open_gate.RETRY):
            entered.set()

    with _held(gate):
        t = threading.Thread(target=interrupted, name="kesilen")
        t.start()
        t.join(5)
        assert isinstance(errors[0], KeyboardInterrupt) and gate.waiting() == 0
        threading.Thread(target=next_one).start()
    assert entered.wait(5)


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
    assert session.OPEN_TIMEOUT_MS < 10_000                        # TRASSIR jetonu (~10 sn) dolmadan açılış biter


def test_open_without_level_uses_the_thread_hint(rec: _Recorder) -> None:
    session.open_capture("http://kamera/akis")
    with open_gate.priority(open_gate.RETRY):
        session.open_capture("rtsp://nvr/kapali")
    assert [c[2] for c in rec.calls] == [open_gate.VIEWER, open_gate.RETRY]


def test_local_file_is_opened_directly(rec: _Recorder) -> None:
    session.open_capture("C:/videolar/test.mp4")
    assert rec.calls == [("C:/videolar/test.mp4", (cv2.CAP_FFMPEG,), None)]


class _Cap:
    """`frames` < 0: açılmaz; yoksa o kadar kare verip biter."""

    def __init__(self, frames: int) -> None:
        self._left = frames

    def isOpened(self) -> bool:
        return self._left >= 0

    def read(self) -> tuple[bool, Any]:
        if self._left <= 0:
            return False, None
        self._left -= 1
        time.sleep(0.005)
        return True, np.zeros((288, 352, 3), np.uint8)

    def get(self, prop: int) -> float:
        return 25.0

    def release(self) -> None:
        pass


def test_viewer_resolves_url_inside_the_gate_and_failed_viewer_retries_last(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(viewer_mod, "_pause", lambda stop, s: stop.wait(0.01))
    plan = [-1, -1, 3, -1]                                         # açılmadı, açılmadı, 3 kare, açılmadı
    seen: list[int] = []
    url_in_gate: list[bool] = []

    def open_url() -> str:
        url_in_gate.append(open_gate.GATE.held_by_current_thread())
        return "rtsp://nvr/1"

    def capture(url: str) -> _Cap:
        seen.append(open_gate.current_priority())
        return _Cap(plan[len(seen) - 1] if len(seen) <= len(plan) else -1)

    v = viewer_mod.CameraViewer(("nvr", "1", "sub"), open_url, None, capture, time.monotonic)
    try:
        _wait(lambda: len(seen) >= 5)
    finally:
        v.request_stop()
        v.join(2)
    assert seen[:5] == [open_gate.VIEWER, open_gate.RETRY, open_gate.RETRY, open_gate.VIEWER, open_gate.RETRY]
    assert url_in_gate and all(url_in_gate)                        # jeton kuyrukta beklerken dolmaz


def test_session_opens_first_and_a_session_without_frames_steps_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session.LiveSession, "_wait_reconnect", lambda self, s: self._stop.wait(0.01))
    plan = [-1, 3, -1]                                             # açılmadı, 3 kare, açılmadı
    levels: list[int | None] = []
    url_in_gate: list[bool] = []

    def open_url() -> str:
        url_in_gate.append(open_gate.GATE.held_by_current_thread())
        return "rtsp://nvr/1"

    def capture(url: str, level: int | None = None) -> _Cap:
        levels.append(level)
        return _Cap(plan[len(levels) - 1] if len(levels) <= len(plan) else -1)

    monkeypatch.setattr(session, "open_capture", capture)
    s = session.LiveSession("t", open_url, Profile.egg())
    try:
        _wait(lambda: len(levels) >= 4)
    finally:
        s.stop()
    assert levels[:4] == [open_gate.SESSION, open_gate.SESSION_RETRY, open_gate.SESSION, open_gate.SESSION_RETRY]
    assert url_in_gate and all(url_in_gate)


def test_abandoned_snapshot_does_not_open_after_its_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    from bantvision.live import api

    opened: list[str] = []
    monkeypatch.setattr(api, "open_capture", lambda url: opened.append(url) or _Cap(1))
    result: dict[str, bytes] = {}
    api._grab("rtsp://nvr/1", result, deadline=time.monotonic() - 1)
    assert opened == [] and result == {}
    api._grab("rtsp://nvr/1", result, deadline=time.monotonic() + 5)
    assert opened == ["rtsp://nvr/1"] and "jpeg" in result
