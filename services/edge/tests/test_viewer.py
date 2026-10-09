"""İzleme okuyucuları: paylaşım, boşta kapanma, oturum karesi, sınırlar, hata ve yeniden deneme (ağsız, sahte açıcı)."""
from __future__ import annotations

import pathlib
import threading
import time
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from bantvision.analyzer import Settings, create_app
from bantvision.live import viewer as viewer_mod
from bantvision.live.viewer import IDLE_S, MAX_MAIN, MAX_SUB, REJECT_TTL_S, SourceGone, ViewHub


class FakeCap:
    """Okundukça kare veren sahte akış; `opened=False` hiç açılmaz; `frames` kare sonra akış biter."""

    def __init__(self, opened: bool = True, frames: int = 10_000, w: int = 1920, h: int = 1080) -> None:
        self._opened, self._left, self.w, self.h = opened, frames, w, h

    def isOpened(self) -> bool:
        return self._opened

    def read(self) -> tuple[bool, Any]:
        if self._left <= 0:
            return False, None
        self._left -= 1
        time.sleep(0.005)
        return True, np.full((self.h, self.w, 3), 100, np.uint8)

    def release(self) -> None:
        pass


class GateCap(FakeCap):
    """`gate` açılana dek hiç kare vermez (okuyucunun ilk karesinden önceki anı yakalamak için)."""

    def __init__(self, gate: threading.Event) -> None:
        super().__init__()
        self._gate = gate

    def read(self) -> tuple[bool, Any]:
        self._gate.wait(10)
        return super().read()


class FakeSession:
    """`LiveSession` yerine: son kare + durum. `frame=None` henüz kare gelmedi demektir."""

    def __init__(self, frame: np.ndarray | None = None, seq: int = 7, state: str = "live") -> None:
        self.frame, self.seq = frame, seq
        self.status = type("St", (), {"state": state, "message": "", "fps": 12.0})()

    def latest_frame(self) -> tuple[int, np.ndarray] | None:
        return None if self.frame is None else (self.seq, self.frame)


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def make_hub(caps: Any = None, sessions: dict[tuple[str, str | None], Any] | None = None,
             gone: set[str] | None = None, clock: Any = time.monotonic, env: dict[str, str] | None = None,
             reaper: bool = False) -> tuple[ViewHub, list[str]]:
    opened: list[str] = []

    def opener(source_id: str, channel_id: str | None, sub: bool) -> tuple[Any, Any]:
        if gone and source_id in gone:
            raise SourceGone("Kamera silinmiş.")
        ver = (env or {}).get("v", "")
        return (lambda: f"rtsp://{source_id}{ver}/{channel_id}/{'sub' if sub else 'main'}"), None

    def capture(url: str) -> Any:
        opened.append(url)
        return caps(url) if caps else FakeCap()

    hub = ViewHub(opener, lambda s, c: (sessions or {}).get((s, c)), capture=capture, clock=clock, reaper=reaper)
    return hub, opened


def wait(fn: Any, timeout: float = 5.0) -> Any:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.02)
    raise AssertionError("zaman aşımı")


def fast_pause(monkeypatch: pytest.MonkeyPatch, delay: float = 0.01) -> list[float]:
    """Yeniden deneme beklemelerini kaydeder ve kısaltır (istenen süre `waits`'e yazılır)."""
    waits: list[float] = []

    def pause(stop: threading.Event, seconds: float) -> None:
        waits.append(seconds)
        stop.wait(delay)

    monkeypatch.setattr(viewer_mod, "_pause", pause)
    return waits


def test_one_reader_per_camera_shared_and_downscaled() -> None:
    hub, opened = make_hub()
    try:
        t = wait(lambda: (x := hub.tile("a", "1")).frame is not None and x)
        assert t.state == "live" and t.frame.shape[1] == 960                    # alt akış 960 px'e küçültülür
        hub.tile("a", "1")
        hub.tile("a", "1")
        assert opened == ["rtsp://a/1/sub"]                                      # aynı kamera tek bağlantı
    finally:
        hub.stop()


def test_idle_reader_closes_after_30s() -> None:
    clock = Clock()
    hub, _ = make_hub(clock=clock)
    try:
        hub.tile("a", None)
        assert hub.open_count("sub") == 1
        clock.t += IDLE_S - 1
        assert hub.sweep() == 0
        clock.t += 2
        assert hub.sweep() == 1 and hub.open_count("sub") == 0
    finally:
        hub.stop()


def test_running_session_frame_is_reused_without_second_connection() -> None:
    class Sess:
        status = type("St", (), {"state": "live", "message": "", "fps": 12.0})()

        def latest_frame(self) -> tuple[int, np.ndarray]:
            return 7, np.zeros((480, 640, 3), np.uint8)

    sessions: dict[tuple[str, str | None], Any] = {("a", "1"): Sess()}
    hub, opened = make_hub(sessions=sessions)
    try:
        t = hub.tile("a", "1")
        assert t.seq == 7 and t.frame is not None and t.state == "live" and opened == []
        sessions.clear()                                                         # oturum kapandı: kendi okuyucusu açılır
        wait(lambda: hub.tile("a", "1").frame is not None)
        assert opened == ["rtsp://a/1/sub"]
    finally:
        hub.stop()


def test_limit_16_sub_readers() -> None:
    hub, _ = make_hub()
    try:
        for i in range(MAX_SUB):
            assert hub.tile(f"s{i}", None).message == ""
        t = hub.tile("fazla", None)
        assert t.state == "error" and "Sınır aşıldı" in t.message
        assert hub.open_count("sub") == MAX_SUB
    finally:
        hub.stop()


def test_limit_2_main_readers_with_separate_sub_limit() -> None:
    hub, _ = make_hub(caps=lambda url: FakeCap(w=2560, h=1440))
    try:
        for i in range(MAX_MAIN):
            assert hub.tile(f"m{i}", None, "main").message == ""
        t = hub.tile("fazla", None, "main")
        assert t.state == "error" and "Sınır aşıldı" in t.message and "2" in t.message
        assert hub.open_count("main") == MAX_MAIN
        assert hub.tile("alt", None).message == ""                               # alt akış sınırı ayrı sayılır
        f = wait(lambda: (x := hub.tile("m0", None, "main")).frame is not None and x)
        assert f.frame.shape[1] == 1920                                          # ana akış 1920 px'e küçültülür
    finally:
        hub.stop()


def test_deleted_source_and_unopenable_stream_are_turkish_errors_with_backoff() -> None:
    hub, opened = make_hub(caps=lambda url: FakeCap(opened=False), gone={"silindi"})
    try:
        assert hub.tile("silindi", None).message == "Kamera silinmiş."
        t = wait(lambda: (x := hub.tile("kapali", None)).state == "error" and x)
        assert "açılamadı" in t.message
        time.sleep(1.5)
        assert 1 <= len([u for u in opened if "kapali" in u]) <= 2               # sıkı döngü yok: 1 sn, 2 sn bekleme
    finally:
        hub.stop()


def test_backoff_doubles_to_30s_and_a_single_frame_does_not_reset_it(monkeypatch: pytest.MonkeyPatch) -> None:
    waits = fast_pause(monkeypatch)
    hub, _ = make_hub(caps=lambda url: FakeCap(frames=1))                        # her bağlantı 1 kare verip kopar
    try:
        hub.tile("a", None)
        wait(lambda: len(waits) >= 7)
        assert waits[:7] == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0]
    finally:
        hub.stop()


def test_backoff_resets_after_stream_delivered_frames_long_enough(monkeypatch: pytest.MonkeyPatch) -> None:
    waits = fast_pause(monkeypatch)
    monkeypatch.setattr(viewer_mod, "GOOD_AFTER_S", 0.01)                        # 5 sn yerine 10 ms (kısa test)
    hub, _ = make_hub(caps=lambda url: FakeCap(frames=6))                        # her bağlantı ~30 ms kare verir
    try:
        hub.tile("a", None)
        wait(lambda: len(waits) >= 4)
        assert waits[:4] == [1.0, 1.0, 1.0, 1.0]
    finally:
        hub.stop()


def test_file_source_that_opens_but_gives_no_frames_waits_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    waits = fast_pause(monkeypatch)
    opened: list[str] = []

    def capture(url: str) -> Any:
        opened.append(url)
        return FakeCap(frames=0)

    hub = ViewHub(lambda s, c, sub: ((lambda: "C:/video/yok.mp4"), None), lambda s, c: None,
                  capture=capture, reaper=False)
    try:
        hub.tile("a", None)
        wait(lambda: len(waits) >= 3)
        assert waits[:3] == [1.0, 2.0, 4.0]                                      # sıkı döngü yok
    finally:
        hub.stop()


def test_file_source_with_frames_rewinds_without_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    waits = fast_pause(monkeypatch)
    opened: list[str] = []

    def capture(url: str) -> Any:
        opened.append(url)
        return FakeCap(frames=3)

    hub = ViewHub(lambda s, c, sub: ((lambda: "C:/video/klip.mp4"), None), lambda s, c: None,
                  capture=capture, reaper=False)
    try:
        hub.tile("a", None)
        wait(lambda: len(opened) >= 3)
        assert waits == []                                                       # dosya başa sarar, bekleme yok
    finally:
        hub.stop()


def test_exception_in_capture_or_read_does_not_kill_the_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    waits = fast_pause(monkeypatch, delay=0.15)
    calls = {"n": 0}

    class BadRead(FakeCap):
        def read(self) -> tuple[bool, Any]:
            raise RuntimeError("bozuk akış")

    def caps(url: str) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("açılamadı")
        if calls["n"] == 2:
            return BadRead()
        return FakeCap()

    hub, _ = make_hub(caps=caps)
    try:
        hub.tile("a", None)
        err = wait(lambda: (x := hub.tile("a", None)).state == "error" and x)
        assert "okunamadı" in err.message                                       # Türkçe, ham istisna metni yok
        t = wait(lambda: (x := hub.tile("a", None)).state == "live" and x)      # üçüncü denemede akış gelir
        assert t.frame is not None and calls["n"] == 3 and waits[:2] == [1.0, 2.0]
    finally:
        hub.stop()


def test_open_url_error_shows_detail_without_status_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    fast_pause(monkeypatch, delay=0.15)

    class Boom(Exception):
        detail = "Kayıt cihazı yanıt vermedi."

        def __init__(self) -> None:
            super().__init__("502: Kayıt cihazı yanıt vermedi.")

    def opener(source_id: str, channel_id: str | None, sub: bool) -> tuple[Any, Any]:
        if source_id == "hemen":
            raise Boom()                                                         # adres üretici hiç kurulamadı

        def open_url() -> str:
            raise Boom()                                                         # ilk bağlanışta kayıt cihazı sustu
        return open_url, None

    hub = ViewHub(opener, lambda s, c: None, capture=lambda url: FakeCap(), reaper=False)
    try:
        assert hub.tile("hemen", None).message == "Kaynağa ulaşılamadı: Kayıt cihazı yanıt vermedi."
        hub.tile("sonra", None)
        t = wait(lambda: (x := hub.tile("sonra", None)).state == "error" and x)
        assert t.message == "Kaynağa ulaşılamadı: Kayıt cihazı yanıt vermedi."
    finally:
        hub.stop()


def test_errored_stream_does_not_keep_last_fps(monkeypatch: pytest.MonkeyPatch) -> None:
    fast_pause(monkeypatch, delay=0.3)
    hub, _ = make_hub(caps=lambda url: FakeCap(frames=40))
    try:
        hub.tile("a", None)
        wait(lambda: hub.tile("a", None).fps > 0)
        err = wait(lambda: (x := hub.tile("a", None)).state == "error" and x)
        assert err.fps == 0.0 and err.frame is not None                          # son kare kalır, eski fps kalmaz
    finally:
        hub.stop()


def test_peek_does_not_open_a_reader() -> None:
    hub, opened = make_hub()
    try:
        t = hub.peek("a", None)
        assert t.state == "connecting" and opened == [] and hub.open_count("sub") == 0
    finally:
        hub.stop()


def test_stop_joins_reader_threads() -> None:
    hub, _ = make_hub()
    hub.tile("a", None)
    viewer = hub._viewers[("a", None, "sub")]
    before = threading.active_count()
    hub.stop()
    wait(lambda: threading.active_count() < before)
    assert not viewer.is_alive()                                                 # okuyucunun kendi iş parçacığı bitti


def test_stop_waits_for_all_readers_against_one_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(viewer_mod, "CLOSE_WAIT_S", 0.5)
    release = threading.Event()

    class HungCap(FakeCap):
        def read(self) -> tuple[bool, Any]:
            release.wait(10)
            return False, None

    hub, opened = make_hub(caps=lambda url: HungCap())
    for i in range(4):
        hub.tile(f"h{i}", None)
    wait(lambda: len(opened) == 4)                                               # dördü de takılı okumada
    t0 = time.monotonic()
    hub.stop()
    elapsed = time.monotonic() - t0
    release.set()
    assert elapsed < 1.2                                                         # sırayla bekleseydi 4 × 0.5 = 2 sn


def test_tile_after_stop_opens_no_reader() -> None:
    hub, opened = make_hub()
    hub.stop()
    t = hub.tile("a", None)
    assert t.state == "error" and t.message == "İzleme durduruldu."
    assert opened == [] and hub.open_count("sub") == 0


def test_reaper_thread_starts_with_first_reader_only() -> None:
    hub, _ = make_hub(reaper=True)
    try:
        assert hub._reaper is None                                               # hiçbir şey izlenmedi: iş parçacığı yok
        hub.tile("a", None)
        assert hub._reaper is not None and hub._reaper.is_alive()
    finally:
        reaper = hub._reaper
        hub.stop()
    assert reaper is not None and not reaper.is_alive()


# ------------------------------------------------------------ kaynak silinir / düzenlenir


def test_drop_stops_running_reader_and_next_tile_reports_deleted_camera() -> None:
    gone: set[str] = set()
    hub, _ = make_hub(gone=gone)
    try:
        wait(lambda: hub.tile("a", "1").frame is not None)
        wait(lambda: hub.tile("b", None).frame is not None)
        reader = hub._viewers[("a", "1", "sub")]
        gone.add("a")                                                            # kaynak silindi
        assert hub.drop("a") == 1
        assert not reader.is_alive() and hub.open_count("sub") == 1              # b dokunulmadı
        t = hub.tile("a", "1")
        assert t.state == "error" and t.message == "Kamera silinmiş." and t.frame is None
        assert hub.open_count("sub") == 1                                        # yeniden açılmadı
    finally:
        hub.stop()


def test_drop_after_update_recreates_reader_with_new_opener() -> None:
    env: dict[str, str] = {}
    hub, opened = make_hub(env=env)
    try:
        wait(lambda: hub.tile("a", "1").frame is not None)
        assert opened == ["rtsp://a/1/sub"]
        env["v"] = "-yeni"                                                       # kaynak düzenlendi: adres değişti
        assert hub.drop("a") == 1 and hub.open_count("sub") == 0
        wait(lambda: hub.tile("a", "1").frame is not None)
        assert opened == ["rtsp://a/1/sub", "rtsp://a-yeni/1/sub"]
    finally:
        hub.stop()


def test_source_endpoints_drop_viewers(tmp_path: pathlib.Path) -> None:
    """PUT/DELETE /sources: çalışan izleme okuyucusu kapanır; düzenlemede yeni adresle açılır, silmede açılmaz."""
    body = {"kind": "camera", "brand": "hikvision", "host": "10.9.9.1", "username": "u", "password": "p"}
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        live = client.app.state.live
        opened: list[str] = []

        def capture(url: str) -> Any:
            opened.append(url)
            return FakeCap()

        live.viewers = ViewHub(live._view_opener, live._session_for, capture=capture, reaper=False)
        sid = client.post("/api/v1/live/sources", json=body).json()["id"]
        wait(lambda: live.viewers.tile(sid, None).frame is not None)
        reader = live.viewers._viewers[(sid, None, "sub")]
        assert "10.9.9.1" in opened[0]

        assert client.put(f"/api/v1/live/sources/{sid}", json={**body, "host": "10.9.9.2"}).status_code == 200
        assert not reader.is_alive() and live.viewers.open_count("sub") == 0
        wait(lambda: live.viewers.tile(sid, None).frame is not None)
        assert "10.9.9.2" in opened[-1]

        reader = live.viewers._viewers[(sid, None, "sub")]
        assert client.delete(f"/api/v1/live/sources/{sid}").status_code == 204
        assert not reader.is_alive() and live.viewers.open_count("sub") == 0
        t = live.viewers.tile(sid, None)
        assert t.state == "error" and t.message == "Kamera silinmiş." and live.viewers.open_count("sub") == 0


# ------------------------------------------------------------ reddedilen istek durum uç noktalarında görünür


def test_peek_reports_limit_rejection_and_recovers_when_a_slot_frees() -> None:
    hub, _ = make_hub()
    try:
        for i in range(MAX_SUB):
            hub.tile(f"s{i}", None)
        assert hub.tile("fazla", None).state == "error"
        p = hub.peek("fazla", None)
        assert p.state == "error" and "Sınır aşıldı (en çok 16 kamera)." in p.message
        assert hub.drop("s0") == 1                                               # bir yer açıldı
        t = hub.tile("fazla", None)
        assert t.state != "error" and hub.open_count("sub") == MAX_SUB
        p = hub.peek("fazla", None)
        assert p.state in ("connecting", "live") and p.message == ""             # red silindi, okuyucunun durumu görünür
    finally:
        hub.stop()


def test_peek_reports_deleted_source_until_the_message_expires() -> None:
    clock = Clock()
    hub, opened = make_hub(clock=clock, gone={"silindi"})
    try:
        assert hub.peek("silindi", None).state == "connecting"                   # henüz istenmedi
        hub.tile("silindi", None)
        p = hub.peek("silindi", None)
        assert p.state == "error" and p.message == "Kamera silinmiş."
        clock.t += REJECT_TTL_S + 1
        assert hub.peek("silindi", None).state == "connecting"                   # eski red süresi doldu
        assert opened == [] and hub.open_count("sub") == 0
    finally:
        hub.stop()


# ------------------------------------------------------------ oturum ↔ okuyucu geçişi karoyu bozmaz


def test_viewer_frames_continue_while_new_session_has_no_frame_yet() -> None:
    sessions: dict[tuple[str, str | None], Any] = {}
    hub, opened = make_hub(sessions=sessions)
    try:
        wait(lambda: hub.tile("a", "1").frame is not None)
        reader = hub._viewers[("a", "1", "sub")]
        s = FakeSession(frame=None, state="connecting")                          # yeni oturum, ilk kare yok
        sessions[("a", "1")] = s
        t = hub.tile("a", "1")
        assert t.frame is not None and t.state == "live" and t.frame.shape[1] == 960   # okuyucunun karesi sürer
        assert hub.open_count("sub") == 1

        s.frame = np.zeros((480, 640, 3), np.uint8)                              # oturum ilk karesini verdi
        t = hub.tile("a", "1")
        assert t.seq == 7 and t.frame.shape[1] == 640
        assert hub.open_count("sub") == 0                                        # ikinci bağlantı bırakıldı
        wait(lambda: not reader.is_alive())
        assert opened == ["rtsp://a/1/sub"]
    finally:
        hub.stop()


def test_session_removed_keeps_last_frame_until_the_reader_has_one() -> None:
    gate = threading.Event()
    sessions: dict[tuple[str, str | None], Any] = {("a", "1"): FakeSession(np.zeros((480, 640, 3), np.uint8))}
    hub, opened = make_hub(caps=lambda url: GateCap(gate), sessions=sessions)
    try:
        assert hub.tile("a", "1").frame is not None
        sessions.clear()                                                         # oturum kapandı
        t = hub.tile("a", "1")                                                   # okuyucu açıldı, kare henüz yok
        assert t.frame is not None and t.frame.shape[1] == 640 and t.state == "connecting"
        gate.set()
        t = wait(lambda: (x := hub.tile("a", "1")).state == "live" and x)
        assert t.frame.shape[1] == 960                                           # artık okuyucunun karesi
        assert opened == ["rtsp://a/1/sub"]
    finally:
        gate.set()
        hub.stop()


def test_stopped_session_is_treated_as_absent() -> None:
    sessions: dict[tuple[str, str | None], Any] = {
        ("a", "1"): FakeSession(np.zeros((480, 640, 3), np.uint8), state="stopped")}
    hub, opened = make_hub(sessions=sessions)
    try:
        t = wait(lambda: (x := hub.tile("a", "1")).frame is not None and x)
        assert t.frame.shape[1] == 960 and opened == ["rtsp://a/1/sub"]          # oturum karesi değil, okuyucu
        assert hub.peek("a", "1").frame.shape[1] == 960
    finally:
        hub.stop()


def test_frames_are_read_only_for_session_and_reader() -> None:
    raw = np.zeros((480, 640, 3), np.uint8)
    sessions: dict[tuple[str, str | None], Any] = {("s", None): FakeSession(raw)}
    hub, _ = make_hub(sessions=sessions)
    try:
        t = hub.tile("s", None)
        assert t.frame is not None and not t.frame.flags.writeable
        with pytest.raises(ValueError):
            t.frame[0, 0, 0] = 1                                                 # yanlışlıkla üzerine çizen kod patlar
        assert raw.flags.writeable                                               # oturumun kendi karesi dokunulmadı
        r = wait(lambda: (x := hub.tile("k", None)).frame is not None and x)
        assert not r.frame.flags.writeable
    finally:
        hub.stop()


def test_session_frame_is_downscaled_once_per_sequence() -> None:
    s = FakeSession(np.zeros((1080, 1920, 3), np.uint8), seq=5)
    sessions: dict[tuple[str, str | None], Any] = {("a", "1"): s}
    hub, _ = make_hub(sessions=sessions)
    try:
        t1, t2 = hub.tile("a", "1"), hub.tile("a", "1")
        assert t1.frame.shape[1] == 960 and t1.frame is t2.frame                 # aynı kare yeniden küçültülmedi
        s.seq = 6
        assert hub.tile("a", "1").frame is not t1.frame                          # yeni kare
        sessions[("a", "1")] = FakeSession(np.full((1080, 1920, 3), 9, np.uint8), seq=6)
        assert hub.tile("a", "1").frame[0, 0, 0] == 9                            # başka oturum, aynı sıra: eski kare dönmez
    finally:
        hub.stop()
