"""Yangın/duman canlı yolu (R7): oturum, ortak model, alarm kaydı/bildirim/olay kaydı, durum, izleme listesi, doğrulama.

Sahte yangın dedektörü (model yok, ağ yok) oturum açılmadan ÖNCE `manager.fire`'a konur. Dosya kaynağı sentetik bir
videodur: gri zeminde kutu içi her kare değişen gürültü ("hareketli alev"); dosya başa sararak canlı kamera gibi akar.
"""
from __future__ import annotations

import json
import pathlib
import threading
import time
from types import SimpleNamespace
from typing import Any

import cv2
import numpy as np
import pytest
from conftest import local_client
from fastapi.testclient import TestClient

from bantvision.analyzer import Settings, create_app
from bantvision.core import Profile
from bantvision.core.detector import Detection
from bantvision.core.fire import FireAlarm
from bantvision.core.fire_model import FireModelMissing
from bantvision.core.fire_rules import MAX_FPS
from bantvision.core.safety import SafetyAlarm

W, H, FPS = 640, 480, 25.0
FLAME = (280.0, 200.0, 360.0, 280.0)
MISSING = "Yangın/duman modeli kurulu değil."
CHECK = "Görüntüyü hemen kontrol edin."


class ConstFire:
    """Her karede aynı piksel kutusunu verir (`cls` kuralı kapalıysa hiç); `calls` çağrı sayısı. `fail` doluysa o hatayı
    fırlatır (model dosyası yok)."""

    def __init__(self, cls: str = "fire", box: tuple[float, float, float, float] = FLAME) -> None:
        self.cls, self.box = cls, box
        self.calls = 0
        self.fail: BaseException | None = None

    def detect(self, _bgr: np.ndarray, conf: dict[str, float]) -> list[Detection]:
        self.calls += 1
        if self.fail is not None:
            raise self.fail
        return [Detection(*self.box, 0.9, self.cls)] if self.cls in conf else []


def noise_video(path: pathlib.Path, seconds: float = 4.0) -> pathlib.Path:
    rng = np.random.default_rng(0)
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    x1, y1, x2, y2 = (int(v) for v in FLAME)
    for _ in range(int(FPS * seconds)):
        f = np.full((H, W, 3), 110, np.uint8)
        f[y1:y2, x1:x2] = rng.integers(0, 256, (y2 - y1, x2 - x1, 3), dtype=np.uint8)
        w.write(f)
    w.release()
    return path


def wait_for(fn: Any, timeout: float = 30.0) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        v = fn()
        if v:
            return v
        time.sleep(0.1)
    raise AssertionError("koşul zamanında sağlanmadı")


@pytest.fixture()
def client(tmp_path: pathlib.Path) -> TestClient:
    with local_client(create_app(Settings(data_dir=tmp_path))) as c:
        yield c


@pytest.fixture()
def video(tmp_path: pathlib.Path) -> pathlib.Path:
    return noise_video(tmp_path / "alev.mp4")


def _mock_telegram(client: TestClient, paths: list[str] | None = None) -> None:
    import httpx

    def reply(request: httpx.Request) -> httpx.Response:
        if paths is not None:
            paths.append(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(200, json={"ok": True})

    client.app.state.live.notifier._client = httpx.Client(transport=httpx.MockTransport(reply))
    client.put("/api/v1/live/notify", json={"enabled": True, "chatId": "-1", "token": "1:T"})


def _fire_profile(client: TestClient, **fire: Any) -> dict[str, Any]:
    prof = client.post("/api/v1/live/profiles", json={"preset": "fire"}).json()
    block = {**prof["fire"], "fire": {"enabled": True, "seconds": 2}, **fire}
    r = client.put(f"/api/v1/live/profiles/{prof['id']}", json={**prof, "fire": block})
    assert r.status_code == 200, r.text
    return r.json()


def _fire_session(client: TestClient, monkeypatch: pytest.MonkeyPatch, video: pathlib.Path, det: Any = None,
                  name: str = "Depo", **fire: Any) -> tuple[Any, str]:
    monkeypatch.setenv("ANALYZER_ALLOW_FILE_SOURCES", "1")
    mgr = client.app.state.live
    if det is not None:
        mgr.fire = det
    src = client.post("/api/v1/live/sources", json={"kind": "camera", "brand": "custom", "customUrl": str(video),
                                                     "host": "", "username": "", "password": "", "name": name}).json()
    prof = _fire_profile(client, **fire)
    r = client.post("/api/v1/live/sessions", json={"sourceId": src["id"], "profileId": prof["id"]})
    assert r.status_code == 201, r.text
    return mgr.sessions[r.json()["id"]], r.json()["id"]


def _fake_session(profile: Profile | None = None, **over: Any) -> Any:
    return SimpleNamespace(**{"id": "x", "name": "Depo", "profile": profile or Profile.fire_watch(),
                              "source_id": "src", "channel_id": None, **over})


def _inject(s: Any, ts: float, frame: np.ndarray) -> int:
    """İşleyiciye okuyucu gibi kare verir; önizleme karesinin sırasını döndürür (yeni kare beklemek için)."""
    with s._frame_cv:
        seq = s._jpeg_seq
        s._seq += 1
        s._latest = (s._seq, ts, frame)
        s._latest_mono = time.monotonic()
        s._frame_cv.notify_all()
    return seq


def _scene(rng: np.random.Generator) -> np.ndarray:
    f = np.full((H, W, 3), 110, np.uint8)
    x1, y1, x2, y2 = (int(v) for v in FLAME)
    f[y1:y2, x1:x2] = rng.integers(0, 256, (y2 - y1, x2 - x1, 3), dtype=np.uint8)
    return f


# ---------------------------------------------------------------------- oturum kurulumu

def test_fire_session_builds_analyzer_from_shared_model_and_keeps_clip_buffer_only_in_alarm_modes() -> None:
    from bantvision.live.session import LiveSession

    det = ConstFire()
    s = LiveSession("t", lambda: "yok.mp4", Profile.fire_watch(), fire=det, clip_sink=lambda _j: None)
    try:
        an = s._pipe.fire
        assert an is not None and an._detector is det and s.records_clips
        st = s.snapshot_status()
        assert st["safety"] is None and set(st["fire"]) >= {"active", "lastAlarmAt", "model", "healthy", "reason",
                                                              "unhealthyFor"}
        assert st["fire"]["model"] == "ready" and st["fire"]["active"] == [] and st["fire"]["lastAlarmAt"] is None
        s.set_profile(Profile.people())
        assert s.snapshot_status()["fire"] is None and not s.records_clips
        s.set_profile(Profile.fire_watch())
        an2 = s._pipe.fire
        assert an2 is not None and an2 is not an and an2._detector is det and s.records_clips
        clips = s._clips
        s.set_profile(Profile.jeweler())                     # yangından güvenliğe: taze ön kayıt (eski işaret kalmaz)
        assert s.records_clips and s._clips is not clips and s.snapshot_status()["fire"] is None
    finally:
        s.stop()


def test_fire_session_warms_the_shared_fire_model_only() -> None:
    from bantvision.live.session import LiveSession

    class Warm:
        def __init__(self) -> None:
            self.warms = 0

        def warm(self) -> None:
            self.warms += 1

    det, pose, fire = Warm(), Warm(), Warm()
    s = LiveSession("t", lambda: "yok.mp4", Profile.fire_watch(), detector=det, pose=pose, fire=fire)
    try:
        assert (det.warms, pose.warms, fire.warms) == (0, 0, 1)
    finally:
        s.stop()


# ---------------------------------------------------------------------- analiz hızı sınırı (MAX_FPS)

def test_fire_mode_skips_analysis_faster_than_max_fps_but_keeps_preview() -> None:
    from bantvision.live.session import LiveSession

    det = ConstFire()
    s = LiveSession("t", lambda: "yok.mp4", Profile.fire_watch(), fire=det)
    rng = np.random.default_rng(1)
    step = 1 / MAX_FPS
    try:
        times = [100.0, 100.0 + step * 0.25, 100.0 + step * 0.9, 100.0 + step, 100.0 + step * 1.5,
                 100.0 + step * 2.05]
        want = [1, 1, 1, 2, 2, 3]                     # yalnızca son analizden ≥ 1/MAX_FPS sonra gelen kare işlenir
        for ts, n in zip(times, want, strict=True):
            seq = _inject(s, ts, _scene(rng))
            s.jpeg(after=seq, timeout=5.0)             # her kare önizlemeye gider (atlananlar da)
            assert s._jpeg_seq > seq
            assert det.calls == n, (ts, det.calls)
            time.sleep(0.1)                            # önizleme ≤ 12/sn: sonraki kare de çizilsin
    finally:
        s.stop()


def test_people_mode_is_not_throttled() -> None:
    from bantvision.live.session import LiveSession

    s = LiveSession("t", lambda: "yok.mp4", Profile.people())
    try:
        assert s._fire_due(1.0) and s._fire_due(1.01)          # yalnızca yangın modunda sınır uygulanır
    finally:
        s.stop()


# ---------------------------------------------------------------------- model yok / sonradan yüklenir (Review Focus 5)

def test_fire_health_gives_first_failing_condition_in_turkish() -> None:
    from bantvision.live.session import STALE_S, fire_health

    assert fire_health("connecting", "ready", "", None, 1.0, 2.0) == (False, "Kameraya bağlanılıyor")
    assert fire_health("reconnecting", "ready", "", None, 1.0, 2.0) == (False, "Kamera bağlantısı yok")
    assert fire_health("live", "loading", "", None, 1.0, 2.0) == (False, "Yangın/duman modeli yükleniyor")
    assert fire_health("live", "error", MISSING, None, 1.0, 2.0) == (False, MISSING)
    assert fire_health("live", "error", "", None, 1.0, 2.0) == (False, "Yangın/duman modeli yüklenemedi")
    assert fire_health("live", "ready", "", "bozuk", 1.0, 2.0) == (False, "Görüntü işlenemiyor: bozuk")
    assert fire_health("live", "ready", "", None, None, 2.0) == (False, "Görüntü işlenemiyor: henüz kare işlenmedi")
    assert fire_health("live", "ready", "", None, 1.0, 1.0 + STALE_S + 1)[0] is False
    assert fire_health("live", "ready", "", None, 1.0, 2.0) == (True, None)


def test_shared_fire_reports_missing_model_in_turkish_without_download() -> None:
    from bantvision.live.api import SharedFire

    fire = SharedFire()                                  # gerçek yükleyici: model klasörü boş, adres yok
    assert fire.detect(np.zeros((8, 8, 3), np.uint8), {"fire": 0.5}) == []
    wait_for(lambda: fire.state == "error", timeout=10)
    assert fire.error == MISSING and fire.status() == {"state": "error", "device": None, "note": MISSING}


def test_missing_fire_model_logs_warning_once_then_debug_and_other_errors_stay_error(
        caplog: pytest.LogCaptureFixture) -> None:
    import logging

    from bantvision.live.api import SharedFire, SharedPose

    now, errors = [1000.0], [FireModelMissing(MISSING), FireModelMissing(MISSING), RuntimeError("bozuk dosya")]

    def loader(_choice: str) -> Any:
        raise errors.pop(0)

    fire = SharedFire(loader=loader, clock=lambda: now[0])
    pose = SharedPose(loader=lambda _c: (_ for _ in ()).throw(RuntimeError("bozuk")), clock=lambda: now[0])
    frame = np.zeros((8, 8, 3), np.uint8)
    with caplog.at_level(logging.DEBUG, logger="bantvision.live.api"):
        for _ in range(3):
            fire.detect(frame, {"fire": 0.5})
            wait_for(lambda: fire.state == "error" and not fire._loading, timeout=10)
            now[0] += 61.0                                       # yeniden deneme süresi geçti
        assert pose.estimate(frame) is None
        wait_for(lambda: pose.state == "error" and not pose._loading, timeout=10)
    levels = [(r.levelno, r.getMessage().split(" [")[0]) for r in caplog.records if r.name == "bantvision.live.api"
              and ("Yangın/duman" in r.getMessage() or "Poz modeli" in r.getMessage())]
    assert fire.error.startswith("Yangın/duman modeli yüklenemedi: ")
    assert levels == [(logging.WARNING, MISSING), (logging.DEBUG, MISSING), (logging.ERROR, fire.error),
                      (logging.ERROR, pose.error)]                # başka hata ve diğer modeller ERROR kalır


def test_missing_model_session_runs_unhealthy_then_starts_when_model_appears(
        client: TestClient, monkeypatch: pytest.MonkeyPatch, video: pathlib.Path) -> None:
    """Model yokken oturum canlı ama sağlıksız ("kurulu değil"); model sonradan kurulunca (ortak model yeniden denenip
    hazır olunca) analiz kendiliğinden başlar ve alarm gelir — oturum yeniden açılmaz."""
    from bantvision.live.api import SharedFire

    now, calls = [1000.0], []
    det = ConstFire()

    def loader(_choice: str) -> Any:
        calls.append(1)
        if len(calls) == 1:
            raise FireModelMissing(MISSING)
        return det

    shared = SharedFire(loader=loader, clock=lambda: now[0])
    sess, sid = _fire_session(client, monkeypatch, video, det=shared)
    st = wait_for(lambda: (v := client.get(f"/api/v1/live/sessions/{sid}").json())["state"] == "live"
                  and v["fire"]["model"] == "error" and v)
    assert st["fire"]["healthy"] is False and st["fire"]["reason"] == MISSING and st["fire"]["modelError"] == MISSING
    time.sleep(1.5)
    assert len(calls) == 1 and sess._worker.is_alive()           # bekleme süresinde yeniden denenmez, çökme yok
    assert client.get("/api/v1/live/alarms").json() == []
    now[0] += 61.0                                               # 1 dakika geçti: kareler modeli yeniden dener
    a = wait_for(lambda: client.get("/api/v1/live/alarms?active=1").json(), timeout=30)[0]
    assert a["type"] == "fire" and a["sessionId"] == sid and len(calls) == 2
    fire = wait_for(lambda: (v := client.get(f"/api/v1/live/sessions/{sid}").json()["fire"])["healthy"] and v)
    assert fire["model"] == "ready" and fire["reason"] is None and fire["unhealthyFor"] is None


def test_direct_detector_missing_model_is_reported_as_model_state_and_recovers() -> None:
    """Ortak model dışında (dedektör doğrudan `FireModelMissing` fırlatır) da oturum düşmez: durum "kurulu değil",
    işleme hatası değil; dedektör çalışınca kendiliğinden düzelir."""
    from bantvision.live.session import LiveSession

    det = ConstFire()
    det.fail = FireModelMissing(MISSING)
    s = LiveSession("t", lambda: "yok.mp4", Profile.fire_watch(), fire=det)
    rng = np.random.default_rng(2)
    try:
        for k in range(3):
            seq = _inject(s, 10.0 + k, _scene(rng))
            s.jpeg(after=seq, timeout=5.0)
        f = s.snapshot_status()["fire"]
        assert (f["model"], f["modelError"], f["processingError"]) == ("error", MISSING, None)
        assert s._worker.is_alive()
        det.fail = None
        seq = _inject(s, 20.0, _scene(rng))
        s.jpeg(after=seq, timeout=5.0)
        f = s.snapshot_status()["fire"]
        assert (f["model"], f["modelError"]) == ("ready", None) and f["lastOkAt"] is not None
    finally:
        s.stop()


# ---------------------------------------------------------------------- alarm yolu (uçtan uca)

def test_fire_alarm_reaches_store_queue_status_and_clip(client: TestClient, monkeypatch: pytest.MonkeyPatch,
                                                        video: pathlib.Path) -> None:
    from bantvision.live import clips

    monkeypatch.setattr(clips, "PRE_S", 2.0)
    monkeypatch.setattr(clips, "POST_S", 1.0)
    paths: list[str] = []
    _mock_telegram(client, paths)
    mgr = client.app.state.live
    texts: list[tuple[str, bytes | None]] = []
    real = mgr.notifier.enqueue
    monkeypatch.setattr(mgr.notifier, "enqueue", lambda aid, text, img: texts.append((text, img)) or real(aid, text, img))
    sess, sid = _fire_session(client, monkeypatch, video, det=ConstFire())
    a = wait_for(lambda: client.get("/api/v1/live/alarms?active=1").json(), timeout=30)[0]
    assert a["type"] == "fire" and a["camera"] == "Depo" and a["sessionId"] == sid and a["image"] is True
    assert a["notify"] in ("queued", "sent") and a["firedAt"] - a["startedAt"] >= 2.0 - 0.05
    assert a["clipPending"] is True or a["clip"] is True                          # olay kaydı yakalanıyor
    rec = wait_for(lambda: (r := mgr.alarms.get(a["id"]))["clip"] and r, timeout=30)
    assert rec["clipFailed"] is False and rec["clipPending"] is False
    assert client.get(f"/api/v1/live/alarms/{a['id']}/clip.webm").status_code == 200
    mgr.notifier.flush()
    assert paths == ["sendMessage"]                                               # sendImage kapalı: yalnızca metin
    (text, img), = texts
    first, second = text.split("\n")
    assert first.startswith("🔥 YANGIN — Depo · ") and second == CHECK and img is None
    st = client.get(f"/api/v1/live/sessions/{sid}").json()
    assert st["safety"] is None and st["fire"]["lastAlarmAt"] is not None
    assert st["fire"]["active"] == [{"type": "fire", "trackId": 0, "seconds": pytest.approx(
        st["fire"]["active"][0]["seconds"])}] and st["fire"]["healthy"] is True
    assert [x["id"] for x in client.get("/api/v1/live/alarms", params={"type": "fire"}).json()] == [a["id"]]
    assert client.get("/api/v1/live/alarms", params={"type": "smoke"}).json() == []
    sess.stop()                                                                   # durunca açık alarm kapanır
    assert mgr.alarms.get(a["id"])["endedAt"] is not None


def test_fire_alarm_photo_follows_fire_send_image(client: TestClient, monkeypatch: pytest.MonkeyPatch,
                                                  video: pathlib.Path) -> None:
    paths: list[str] = []
    _mock_telegram(client, paths)
    _sess, _sid = _fire_session(client, monkeypatch, video, det=ConstFire(), sendImage=True)
    a = wait_for(lambda: client.get("/api/v1/live/alarms?active=1").json(), timeout=30)[0]
    client.app.state.live.notifier.flush()
    assert a["image"] is True and paths == ["sendPhoto"]


def test_switching_away_from_fire_closes_open_alarm_and_unwatches(client: TestClient, monkeypatch: pytest.MonkeyPatch,
                                                                   video: pathlib.Path, tmp_path: pathlib.Path) -> None:
    from fakes_safety import FakeDetector

    client.app.state.live.detector = FakeDetector([])         # kişi sayımına geçiş tanıma modelini ısıtır
    _sess, sid = _fire_session(client, monkeypatch, video, det=ConstFire())
    assert len(_watch(tmp_path)) == 1
    a = wait_for(lambda: client.get("/api/v1/live/alarms?active=1").json(), timeout=30)[0]
    r = client.put(f"/api/v1/live/sessions/{sid}/profile", json=Profile.people().to_dict())
    assert r.status_code == 200 and r.json()["fire"] is None
    mgr = client.app.state.live
    assert mgr.alarms.get(a["id"])["endedAt"] is not None and not mgr._alarm_of
    assert _watch(tmp_path) == []


def test_switching_fire_to_safety_closes_fire_alarm_and_keeps_watching(
        client: TestClient, monkeypatch: pytest.MonkeyPatch, video: pathlib.Path, tmp_path: pathlib.Path) -> None:
    from fakes_safety import FakeDetector, FakePose

    mgr = client.app.state.live
    mgr.detector, mgr.pose = FakeDetector([]), FakePose(None)
    _sess, sid = _fire_session(client, monkeypatch, video, det=ConstFire())
    a = wait_for(lambda: client.get("/api/v1/live/alarms?active=1").json(), timeout=30)[0]
    r = client.put(f"/api/v1/live/sessions/{sid}/profile", json=Profile.jeweler().to_dict())
    assert r.status_code == 200 and r.json()["fire"] is None and r.json()["safety"] is not None
    assert mgr.alarms.get(a["id"])["endedAt"] is not None
    (w,) = _watch(tmp_path)
    assert w["profile"]["countMode"] == "safety"


# ---------------------------------------------------------------------- alarm alıcısı (birim)

def test_titles_and_second_line_for_fire_and_smoke(client: TestClient) -> None:
    mgr = client.app.state.live
    ts = time.mktime((2026, 11, 8, 14, 30, 5, 0, 0, -1))
    assert mgr._text("fire", "Depo", ts) == f"🔥 YANGIN — Depo · 08.11.2026 14:30:05\n{CHECK}"
    assert mgr._text("smoke", "Depo", ts) == f"💨 DUMAN — Depo · 08.11.2026 14:30:05\n{CHECK}"
    assert mgr._text("hands_up", "Tezgah", ts) == "🚨 ELLER YUKARI — Tezgah · 08.11.2026 14:30:05"   # değişmedi


def test_on_alarm_and_on_safety_alias_register_fire_with_cooldown_per_kind(client: TestClient) -> None:
    mgr = client.app.state.live
    _mock_telegram(client)
    s = _fake_session()
    assert mgr.on_safety.__func__ is mgr.on_alarm.__func__                     # eski ad takma ad
    ids = mgr.on_alarm(s, [FireAlarm("fire", 0, (0.1, 0.1, 0.2, 0.2), 0.0, 3.0)], [], b"\xff\xd8jpeg")
    mgr.on_alarm(s, [], [(0, "fire", True)], None)                             # bölüm bitti
    mgr.on_alarm(s, [FireAlarm("fire", 0, (0.1, 0.1, 0.2, 0.2), 20.0, 23.0)], [], None)   # soğuma içinde
    mgr.on_alarm(s, [FireAlarm("smoke", 1, (0.1, 0.1, 0.5, 0.5), 20.0, 28.0)], [], None)  # başka tür: soğuma ayrı
    by = sorted(mgr.alarms.list(), key=lambda a: a["firedAt"])
    assert [(a["type"], a["notify"]) for a in by] == [("fire", "queued"), ("fire", "suppressed"), ("smoke", "queued")]
    assert by[0]["id"] == ids[0] and by[0]["endedAt"] is not None and by[0]["startedAt"] == pytest.approx(
        by[0]["firedAt"] - 3.0)
    assert {k[2] for k in mgr._alarm_of} == {"fire", "smoke"}                   # açık bölümler izleniyor
    mgr.close_alarms("x")
    assert all(a["endedAt"] is not None for a in mgr.alarms.list())


def test_fire_send_image_comes_from_the_fire_block_only(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = client.app.state.live
    _mock_telegram(client)
    sent: list[bytes | None] = []
    monkeypatch.setattr(mgr.notifier, "enqueue", lambda _aid, _text, img: sent.append(img))
    jpeg = b"\xff\xd8jpeg"
    p = Profile.fire_watch()
    p.safety.sendImage = True                                                   # güvenlik bloğu yangını etkilemez
    mgr.on_alarm(_fake_session(p, id="a", source_id="s1"), [FireAlarm("fire", 0, (0, 0, 1, 1), 0.0, 3.0)], [], jpeg)
    p2 = Profile.fire_watch()
    p2.fire.sendImage = True
    mgr.on_alarm(_fake_session(p2, id="b", source_id="s2"), [FireAlarm("smoke", 1, (0, 0, 1, 1), 0.0, 8.0)], [], jpeg)
    assert sent == [None, jpeg]


def test_in_flight_fire_alarm_after_leaving_fire_is_recorded_and_closed(client: TestClient) -> None:
    mgr = client.app.state.live
    mgr.on_alarm(_fake_session(Profile.people()), [FireAlarm("fire", 0, (0, 0, 1, 1), 0.0, 3.0)], [], None)
    (a,) = mgr.alarms.list()
    assert a["type"] == "fire" and a["endedAt"] is not None and not mgr._alarm_of


def test_in_flight_safety_alarm_in_a_fire_session_is_closed(client: TestClient) -> None:
    """Güvenlikten yangına geçilirken gelen eller yukarı alarmı açık kalmaz (yangın oturumu o bölümün sonunu vermez)."""
    mgr = client.app.state.live
    mgr.on_alarm(_fake_session(Profile.fire_watch()), [SafetyAlarm("hands_up", 1, (0, 0, 1, 1), 0.0, 3.0)], [], None)
    (a,) = mgr.alarms.list()
    assert a["endedAt"] is not None and not mgr._alarm_of


def test_alarms_type_filter_accepts_fire_and_smoke(client: TestClient) -> None:
    mgr = client.app.state.live
    f = mgr.alarms.add("s", "Depo", "fire", 1.0, 1.0, None, "disabled")
    s = mgr.alarms.add("s", "Depo", "smoke", 2.0, 2.0, None, "disabled")
    assert [a["id"] for a in client.get("/api/v1/live/alarms", params={"type": "fire"}).json()] == [f["id"]]
    assert [a["id"] for a in client.get("/api/v1/live/alarms", params={"type": "smoke"}).json()] == [s["id"]]
    assert client.get("/api/v1/live/alarms", params={"type": "alev"}).status_code == 422


def test_test_alarm_on_fire_session_stores_frame_and_follows_fire_send_image(
        client: TestClient, monkeypatch: pytest.MonkeyPatch, video: pathlib.Path) -> None:
    sess, sid = _fire_session(client, monkeypatch, video, det=ConstFire("smoke"), sendImage=True)
    wait_for(lambda: sess.raw_jpeg() is not None)
    sent: list[bytes | None] = []
    mgr = client.app.state.live
    _mock_telegram(client)
    monkeypatch.setattr(mgr.notifier, "enqueue", lambda _aid, _text, img: sent.append(img))
    rec = client.post("/api/v1/live/alarms/test", json={"sessionId": sid}).json()
    assert rec["image"] is True and rec["clipPending"] is True and sent and sent[0] is not None


# ---------------------------------------------------------------------- durum, karo rozeti, cihaz ayarları

def test_tile_badge_reports_fire_mode_health(client: TestClient, monkeypatch: pytest.MonkeyPatch,
                                             video: pathlib.Path) -> None:
    from bantvision.live.api import _analysis

    sess, sid = _fire_session(client, monkeypatch, video, det=ConstFire("smoke"))
    a = wait_for(lambda: (x := _analysis(client.app.state.live, sess))["healthy"] and x)
    assert a["mode"] == "fire" and a["sessionId"] == sid and a["reason"] is None and "total" not in a


def test_devices_report_and_apply_the_fire_model(client: TestClient) -> None:
    mgr = client.app.state.live
    j = client.get("/api/v1/live/devices").json()
    assert j["inUse"]["fire"] == {"state": "idle", "device": None, "note": None}
    body = {**j["choices"], "fire": "cpu"}
    assert client.put("/api/v1/live/devices", json={"choices": body}).status_code == 200
    assert mgr.fire.choice == "cpu"


# ---------------------------------------------------------------------- izleme listesi (yeniden başlatma)

def _watch(tmp_path: pathlib.Path) -> list[dict[str, Any]]:
    p = tmp_path / "live" / "watch.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def _app(tmp_path: pathlib.Path) -> Any:
    app = create_app(Settings(data_dir=tmp_path))
    app.state.live.fire = ConstFire()
    return app


def test_fire_session_is_restored_after_restart(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                                video: pathlib.Path) -> None:
    with local_client(_app(tmp_path)) as c:
        _fire_session(c, monkeypatch, video)
        (w,) = _watch(tmp_path)
        assert w["profile"]["countMode"] == "fire" and w["name"] == "Depo"
    app = _app(tmp_path)
    with local_client(app) as c:
        (v,) = c.get("/api/v1/live/sessions").json()
        assert v["profile"]["countMode"] == "fire" and v["profile"]["fire"]["fire"]["seconds"] == 2.0
        s = app.state.live.sessions[v["id"]]
        assert s._pipe.fire._detector is app.state.live.fire
        a = wait_for(lambda: c.get("/api/v1/live/alarms?active=1").json(), timeout=30)[0]
        assert a["sessionId"] == v["id"] and a["type"] == "fire"


def test_switched_into_fire_without_saving_is_restored_as_fire(tmp_path: pathlib.Path,
                                                               monkeypatch: pytest.MonkeyPatch,
                                                               video: pathlib.Path) -> None:
    monkeypatch.setenv("ANALYZER_ALLOW_FILE_SOURCES", "1")
    with local_client(_app(tmp_path)) as c:
        src = c.post("/api/v1/live/sources", json={"kind": "camera", "brand": "custom", "customUrl": str(video),
                                                   "host": "", "username": "", "password": "", "name": "Mutfak"}).json()
        egg = next(p for p in c.get("/api/v1/live/profiles").json() if p["name"] == "Yumurta")
        sid = c.post("/api/v1/live/sessions", json={"sourceId": src["id"], "profileId": egg["id"]}).json()["id"]
        assert _watch(tmp_path) == []
        assert c.put(f"/api/v1/live/sessions/{sid}/profile", json=Profile.fire_watch().to_dict()).status_code == 200
        assert len(_watch(tmp_path)) == 1
    with local_client(_app(tmp_path)) as c:
        (v,) = c.get("/api/v1/live/sessions").json()
        assert v["profile"]["countMode"] == "fire" and v["profileId"] == egg["id"] and v["name"] == "Mutfak"


# ---------------------------------------------------------------------- doğrulama (422)

@pytest.mark.parametrize("fire", [
    5, "x", [], {"fire": 5}, {"smoke": None}, {"fire": {"enabled": "false"}}, {"smoke": {"enabled": 1}},
    {"fire": {"seconds": "3"}}, {"fire": {"seconds": True}}, {"fire": {"seconds": 1.9}}, {"fire": {"seconds": 10.1}},
    {"smoke": {"seconds": 4.9}}, {"smoke": {"seconds": 30.1}}, {"sensitivity": "max"}, {"sensitivity": 1},
    {"sendImage": "evet"}, {"ignoreZones": "x"}, {"ignoreZones": [[[0, 0], [1, 0]]]},
    {"ignoreZones": [[[0, 0]] * 13]}, {"ignoreZones": [[[0, 0], [1, 0], [1, 1.5]]]},
    {"ignoreZones": [[[0, 0], [1, 0], [-0.1, 1]]]}, {"ignoreZones": [[[0, 0], [1, 0], [1]]]},
    {"ignoreZones": [[[0, 0], [1, 0], ["a", 1]]]}, {"ignoreZones": [[[0, 0], [1, 0], [True, 1]]]},
    {"ignoreZones": [[[0, 0], [1, 0], [1, 1]]] * 9}, {"ignoreZones": ["abc"]},
])
def test_profile_rejects_malformed_fire_block(client: TestClient, fire: Any) -> None:
    body = client.post("/api/v1/live/profiles", json={"preset": "fire"}).json()
    r = client.post("/api/v1/live/profiles", json={**body, "fire": fire})
    assert r.status_code == 422 and r.json()["detail"].startswith("Yangın/duman ayarı geçersiz: "), r.text


def test_fire_seconds_message_names_the_rule_like_panel_and_video(client: TestClient) -> None:
    body = client.post("/api/v1/live/profiles", json={"preset": "fire"}).json()
    for block, msg in (({"fire": {"seconds": 1}}, "Yangın süresi 2–10 sn arasında bir sayı olmalı."),
                       ({"smoke": {"seconds": 31}}, "Duman süresi 5–30 sn arasında bir sayı olmalı.")):
        r = client.post("/api/v1/live/profiles", json={**body, "fire": block})
        assert r.status_code == 422 and r.json()["detail"] == f"Yangın/duman ayarı geçersiz: {msg}", r.text


@pytest.mark.parametrize("seconds", ["NaN", "Infinity", "1e999"])
def test_profile_rejects_non_finite_fire_values(client: TestClient, seconds: str) -> None:
    body = client.post("/api/v1/live/profiles", json={"preset": "fire"}).json()
    for block in ({"fire": {"enabled": True, "seconds": "@"}}, {"ignoreZones": [[[0, 0], [1, 0], ["@", 1]]]}):
        raw = json.dumps({**body, "fire": block}).replace('"@"', seconds)
        r = client.post("/api/v1/live/profiles", content=raw, headers={"content-type": "application/json"})
        assert r.status_code == 422 and "Yangın/duman" in r.json()["detail"], r.text


def test_fire_profile_needs_one_enabled_rule(client: TestClient, monkeypatch: pytest.MonkeyPatch,
                                             video: pathlib.Path) -> None:
    body = client.post("/api/v1/live/profiles", json={"preset": "fire"}).json()
    off = {**body["fire"], "fire": {"enabled": False, "seconds": 3}, "smoke": {"enabled": False, "seconds": 8}}
    r = client.post("/api/v1/live/profiles", json={**body, "fire": off})
    assert r.status_code == 422 and r.json()["detail"] == "Yangın/duman ayarı geçersiz: En az bir kural açık olmalı."
    _sess, sid = _fire_session(client, monkeypatch, video, det=ConstFire())
    live = client.get(f"/api/v1/live/sessions/{sid}").json()["profile"]
    r = client.put(f"/api/v1/live/sessions/{sid}/profile", json={**live, "fire": off})
    assert r.status_code == 422 and "En az bir kural açık olmalı." in r.json()["detail"]
    # sayım profilinde yangın bloğu kural denetimine girmez (yalnızca yangın modunda anlamlı)
    people = Profile.people().to_dict()
    assert client.post("/api/v1/live/profiles", json={**people, "fire": off, "name": "Kişi"}).status_code == 201


def test_profile_accepts_valid_fire_block(client: TestClient) -> None:
    body = client.post("/api/v1/live/profiles", json={"preset": "fire"}).json()
    zones = [[[0.0, 0.0], [0.5, 0.0], [0.5, 0.5]]] * 8
    ok = {"fire": {"enabled": False, "seconds": 10}, "smoke": {"enabled": True, "seconds": 30}, "sensitivity": "high",
          "ignoreZones": zones, "sendImage": True}
    r = client.post("/api/v1/live/profiles", json={**body, "fire": ok, "name": "Yeni yangın"})
    assert r.status_code == 201, r.text
    got = r.json()["fire"]
    assert got["smoke"]["seconds"] == 30.0 and got["sensitivity"] == "high" and len(got["ignoreZones"]) == 8
    assert client.post("/api/v1/live/profiles", json={**body, "fire": {}, "name": "Boş"}).status_code == 201
    assert client.post("/api/v1/live/profiles", json={**body, "fire": None, "name": "Yok"}).status_code == 201
    twelve = [[[i / 12, 0.0] for i in range(12)]]
    assert client.post("/api/v1/live/profiles", json={**body, "fire": {"ignoreZones": twelve},
                                                       "name": "Oniki"}).status_code == 201


def test_alarm_threads_register_fire_cooldown_atomically(client: TestClient) -> None:
    mgr = client.app.state.live
    _mock_telegram(client)
    s = _fake_session()
    barrier = threading.Barrier(6)

    def go(i: int) -> None:
        barrier.wait()
        mgr.on_alarm(_fake_session(id=f"s{i}"), [FireAlarm("fire", 0, (0, 0, 1, 1), 0.0, 3.0)], [], None)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert s.source_id == "src"
    states = [a["notify"] for a in mgr.alarms.list()]
    assert len(states) == 6 and sum(1 for n in states if n != "suppressed") == 1


# ---------------------------------------------------------------------- önizleme, alarm resmi ve klip işareti (R8)

WIDE = (FLAME[0] - 20, FLAME[1] - 20, FLAME[2] + 20, FLAME[3] + 20)    # kutu gürültünün dışında: kenarı gri zeminde


def _orange(img: np.ndarray, box: tuple[float, float, float, float], src_w: int = W) -> int:
    """`box` (kaynak piksel) üst kenarı boyunca turuncumsu piksel sayısı (JPEG'e dayanıklı: R ≫ G ≫ B)."""
    k = img.shape[1] / src_w
    y, x1, x2 = round(box[1] * k), round(box[0] * k), round(box[2] * k)
    band = img[max(0, y - 4): y + 5, x1 + 5: x2 - 5].astype(int)
    b, g, r = band[..., 0], band[..., 1], band[..., 2]
    return int(((r - g > 50) & (g - b > 40)).sum())


def test_fire_preview_draws_the_latest_result_also_on_skipped_frames() -> None:
    from bantvision.core.fire import FireResult
    from bantvision.live.session import LiveSession

    s = LiveSession("t", lambda: "yok.mp4", Profile.fire_watch(), fire=ConstFire())
    try:
        frame = np.full((H, W, 3), 110, np.uint8)
        box = tuple(v / d for v, d in zip(WIDE, (W, H, W, H), strict=True))
        r = SimpleNamespace(fire=FireResult(boxes={0: box}))
        assert _orange(s._render(frame.copy(), s.profile, r), WIDE) > 50              # alarm resmi de bu yoldan
        assert np.array_equal(s._render(frame.copy(), s.profile, None), cv2.resize(frame, (720, 540)))
        s._fire_last = r.fire                                                          # atlanan kare: son sonuç
        assert _orange(s._render(frame.copy(), s.profile, None), WIDE) > 50
    finally:
        s.stop()


def test_fire_session_publishes_clip_overlays_only_for_analysed_frames() -> None:
    from bantvision.live.session import LiveSession

    det = ConstFire(box=WIDE)
    s = LiveSession("t", lambda: "yok.mp4", Profile.fire_watch(), fire=det, clip_sink=lambda _j: None)
    rng = np.random.default_rng(2)
    try:
        for i in range(12):                                   # 2,4 sn, 5 kare/sn analiz + arada atlanan kareler
            for ts in (100.0 + i * 0.2, 100.0 + i * 0.2 + 0.05):
                seq = _inject(s, ts, _scene(rng))
                s.jpeg(after=seq, timeout=5.0)
                time.sleep(0.09)
        assert s._clips is not None
        ovs = [ov for _t, ov in s._clips._overlays]
        assert len(ovs) == det.calls == 12 and all(ov.kind == "fire" for ov in ovs)
        assert not ovs[-1].empty and ovs[0].empty                     # ilk karede hareket kıyası yok: kutu oy vermez
        assert _orange(cv2.imdecode(np.frombuffer(s.jpeg()[1] or b"", np.uint8), cv2.IMREAD_COLOR), WIDE) > 20
    finally:
        s.stop()


def test_fire_alarm_image_has_the_alarm_box(client: TestClient, monkeypatch: pytest.MonkeyPatch,
                                            video: pathlib.Path) -> None:
    mgr = client.app.state.live
    _sess, _sid = _fire_session(client, monkeypatch, video, det=ConstFire(box=WIDE))
    a = wait_for(lambda: client.get("/api/v1/live/alarms?active=1").json(), timeout=30)[0]
    img = cv2.imdecode(np.frombuffer(mgr.alarms.image_bytes(a["id"]) or b"", np.uint8), cv2.IMREAD_COLOR)
    assert img is not None and _orange(img, WIDE) > 50


def test_fire_alarm_keeps_an_undrawn_frame_beside_the_image_and_expire_removes_it(
        client: TestClient, monkeypatch: pytest.MonkeyPatch, video: pathlib.Path) -> None:
    mgr = client.app.state.live
    sess, _sid = _fire_session(client, monkeypatch, video, det=ConstFire(box=WIDE))
    a = wait_for(lambda: client.get("/api/v1/live/alarms?active=1").json(), timeout=30)[0]
    sess.stop()
    raw_path = mgr.alarms.images / f"{a['id']}.raw.jpg"
    raw = cv2.imdecode(np.frombuffer(raw_path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    drawn = cv2.imdecode(np.frombuffer(mgr.alarms.image_bytes(a["id"]) or b"", np.uint8), cv2.IMREAD_COLOR)
    assert raw.shape[:2] == (H, W)                                     # kaynak çözünürlüğü, ölçeklenmemiş
    assert _orange(drawn, WIDE) > 50 and _orange(raw, WIDE) == 0       # resim çizili, kare çizimsiz
    assert "raw" not in json.dumps(mgr.alarms.get(a["id"]))            # kayıtta yeni alan yok
    assert mgr.alarms.mark_false_alarm(a["id"])
    sample = mgr.alarms.root / "hard-negatives" / a["id"]
    assert (sample / "frame.jpg").read_bytes() == raw_path.read_bytes()
    assert mgr.alarms.expire(a["firedAt"] + 8 * 86400) == 1
    assert not raw_path.exists() and mgr.alarms.image_bytes(a["id"]) is None
    assert (sample / "frame.jpg").is_file()                             # zor örnek saklamadan bağımsız


def test_safety_alarm_sink_is_called_without_raw_frame() -> None:
    """Poz güvenlik yolu değişmez: alıcı eski 4 argümanla çağrılır; çizimsiz kareyi yalnız yangın/duman verir."""
    from bantvision.core.fire import FireResult
    from bantvision.core.safety import SafetyResult
    from bantvision.live.session import LiveSession

    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    s = LiveSession("t", lambda: "yok.mp4", Profile.fire_watch(),
                    alarm_sink=lambda *a, **k: calls.append((a, k)) or [])
    frame = np.zeros((H, W, 3), np.uint8)
    try:
        s._render = lambda f, _p, _r: f                                 # type: ignore[method-assign]
        safety = SimpleNamespace(safety=SafetyResult(fired=[SafetyAlarm("hands_up", 1, (0, 0, 1, 1), 0.0, 3.0)]),
                                 fire=None)
        fire = SimpleNamespace(safety=None, fire=FireResult(fired=[FireAlarm("fire", 0, (0, 0, 1, 1), 0.0, 3.0)]))
        s._notify_alarms(safety, frame, s.profile)                      # type: ignore[arg-type]
        s._notify_alarms(fire, frame, s.profile)                        # type: ignore[arg-type]
    finally:
        s.stop()
    (sa, sk), (fa, fk) = calls
    assert len(sa) == 4 and sk == {}                                    # güvenlik: eski çağrı biçimi aynen
    assert len(fa) == 4 and set(fk) == {"raw_jpeg"} and fk["raw_jpeg"][:2] == b"\xff\xd8"
