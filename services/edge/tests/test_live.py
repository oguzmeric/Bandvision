"""Canlı sayım (web paneli, bantvision/live): kalıcı ayarlar, şifre gizliliği ve uçtan uca oturum."""
from __future__ import annotations

import json
import pathlib
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bantvision.analyzer import Settings, create_app
from bantvision.live.power import disable_power_throttling
from bantvision.live.store import CATALOG, LiveStore

ROOT = pathlib.Path(__file__).resolve().parents[3]
CLIP = ROOT / "apps" / "ios" / "BantSayacUITests" / "ui_test_clip.mp4"
SECRET = "Gizli-Sifre-42"


@pytest.fixture()
def client(tmp_path: pathlib.Path) -> TestClient:
    with TestClient(create_app(Settings(data_dir=tmp_path))) as c:
        yield c


def camera(**over: Any) -> dict[str, Any]:
    return {"kind": "camera", "brand": "hikvision", "host": "192.168.1.64", "username": "admin",
            "password": SECRET, **over}


def wait_for(fn: Any, timeout: float = 30.0) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        v = fn()
        if v:
            return v
        time.sleep(0.2)
    raise AssertionError("koşul zamanında sağlanmadı")


# ---------------------------------------------------------------------- depo

def test_store_seeds_profiles_like_phone_catalog(tmp_path: pathlib.Path) -> None:
    store = LiveStore(tmp_path)
    names = [p["name"] for p in store.profiles()]
    assert "Mağaza girişi" in names and len(names) == 5
    people = next(p for p in store.profiles() if p["name"] == "Mağaza girişi")
    assert people["countMode"] == "detect"
    presets = {k["key"] for c in CATALOG for k in c["presets"]}
    assert presets == {"egg", "flour", "box", "generic", "people"}


def test_store_keeps_password_out_of_sources(tmp_path: pathlib.Path) -> None:
    store = LiveStore(tmp_path)
    src = store.save_source({"kind": "camera", "host": "10.0.0.5", "password": "x"}, SECRET)
    assert src["hasPassword"] and "password" not in src
    assert SECRET not in (store.root / "sources.json").read_text(encoding="utf-8")
    assert store.password(src["id"]) == SECRET

    store.save_source({"kind": "camera", "host": "10.0.0.6"}, None, src["id"])      # None: şifre korunur
    assert store.password(src["id"]) == SECRET and store.source(src["id"])["host"] == "10.0.0.6"
    store.save_source({"kind": "camera", "host": "10.0.0.6"}, "", src["id"])        # "": şifre silinir
    assert store.password(src["id"]) == "" and not store.source(src["id"])["hasPassword"]

    store.save_source({"kind": "camera"}, SECRET, src["id"])
    assert store.delete_source(src["id"])
    assert json.loads((store.root / "secrets.json").read_text(encoding="utf-8")) == {}
    assert not store.delete_source(src["id"])


def test_store_never_deletes_last_profile(tmp_path: pathlib.Path) -> None:
    store = LiveStore(tmp_path)
    ids = [p["id"] for p in store.profiles()]
    for pid in ids[:-1]:
        assert store.delete_profile(pid)
    assert not store.delete_profile(ids[-1]) and len(store.profiles()) == 1


def test_power_throttling_opt_out_is_safe() -> None:
    assert disable_power_throttling() in (True, False)      # Windows dışında False, hata atmaz


# ---------------------------------------------------------------------- API

def test_api_never_returns_password(client: TestClient) -> None:
    r = client.post("/api/v1/live/sources", json=camera())
    assert r.status_code == 201, r.text
    src = r.json()
    assert src["hasPassword"] and src["name"] == "Hikvision · 192.168.1.64"

    r = client.put(f"/api/v1/live/sources/{src['id']}", json={**camera(host="192.168.1.65"), "password": None})
    assert r.status_code == 200 and r.json()["hasPassword"]           # düzenlemede şifre korunur

    # Panelin kaynağın kendi görünümünü geri göndermesi (kimlik, zaman, hasPassword) reddedilmez (eski hata: 3× 422)
    view = {**r.json(), "name": "Ofis NVR", "password": None}
    r = client.put(f"/api/v1/live/sources/{src['id']}", json=view)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Ofis NVR" and r.json()["hasPassword"] and r.json()["id"] == src["id"]

    for path in ("sources", "sessions", "profiles"):
        assert SECRET not in client.get(f"/api/v1/live/{path}").text
    assert SECRET not in r.text

    assert client.delete(f"/api/v1/live/sources/{src['id']}").status_code == 204
    assert client.get("/api/v1/live/sources").json() == []


def test_api_validates_input(client: TestClient) -> None:
    assert client.post("/api/v1/live/sources", json={**camera(), "port": 70000}).status_code == 422
    assert client.post("/api/v1/live/sources", json={**camera(), "extra": 1}).status_code == 422
    assert client.post("/api/v1/live/profiles", json={"preset": "nope"}).status_code == 422
    assert client.get("/api/v1/live/sessions/yok").status_code == 404
    assert client.post("/api/v1/live/sessions", json={"sourceId": "yok", "profileId": "yok"}).status_code == 404
    cam = client.post("/api/v1/live/sources", json=camera()).json()
    r = client.get(f"/api/v1/live/sources/{cam['id']}/channels")
    assert r.status_code == 400                                       # kamera kayıt cihazı değil


def test_api_profiles_from_preset(client: TestClient) -> None:
    r = client.post("/api/v1/live/profiles", json={"preset": "people", "name": "Arka kapı"})
    assert r.status_code == 201
    p = r.json()
    assert p["name"] == "Arka kapı" and p["countMode"] == "detect"
    p["direction"] = "down"
    assert client.put(f"/api/v1/live/profiles/{p['id']}", json=p).json()["direction"] == "down"
    assert client.delete(f"/api/v1/live/profiles/{p['id']}").status_code == 204


def test_file_source_needs_test_flag(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Yerel dosya yalnızca test bayrağıyla "kamera" olur; aksi halde sunucu dosya okumaz."""
    monkeypatch.delenv("ANALYZER_ALLOW_FILE_SOURCES", raising=False)
    src = client.post("/api/v1/live/sources", json=camera(brand="custom", customUrl=str(CLIP), password="")).json()
    profile = client.get("/api/v1/live/profiles").json()[0]
    r = client.post("/api/v1/live/sessions", json={"sourceId": src["id"], "profileId": profile["id"]})
    assert r.status_code == 400, r.text


def test_live_session_end_to_end(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Dosya kaynağıyla canlı oturum: kare akar, eylemler ve profil değişikliği çalışır, oturum kapanır."""
    monkeypatch.setenv("ANALYZER_ALLOW_FILE_SOURCES", "1")
    src = client.post("/api/v1/live/sources", json=camera(brand="custom", customUrl=str(CLIP), password="")).json()
    egg = next(p for p in client.get("/api/v1/live/profiles").json() if p["name"] == "Yumurta")
    r = client.post("/api/v1/live/sessions", json={"sourceId": src["id"], "profileId": egg["id"]})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    base = f"/api/v1/live/sessions/{sid}"

    live = wait_for(lambda: (v := client.get(base).json())["state"] == "live" and v["fps"] > 0 and v)
    assert live["width"] == 720 and live["height"] == 1280 and not live["twoWay"]
    frame = wait_for(lambda: (f := client.get(f"{base}/frame.jpg")).status_code == 200 and f)
    assert frame.content[:2] == b"\xff\xd8" and frame.headers["cache-control"] == "no-store"

    assert client.post(f"{base}/actions", json={"action": "start"}).json()["counting"]
    assert client.post(f"{base}/actions", json={"action": "learnBackground"}).json()["calibrating"] == "background"
    assert client.post(f"{base}/actions", json={"action": "cancelCalibration"}).json()["calibrating"] is None
    assert client.post(f"{base}/actions", json={"action": "reset"}).json()["total"] == 0
    assert client.post(f"{base}/actions", json={"action": "fly"}).status_code == 422

    prof = dict(live["profile"], linePosition=0.4)
    v = client.put(f"{base}/profile", params={"save": "true"}, json=prof).json()
    assert v["profile"]["linePosition"] == 0.4 and v["profile"]["id"] == egg["id"]
    template = next(p for p in client.get("/api/v1/live/profiles").json() if p["id"] == egg["id"])
    assert template["linePosition"] == egg["linePosition"]           # şablon değişmez; ayar bu kameraya kaydedildi

    csv = client.get(f"{base}/counts.csv")
    assert csv.status_code == 200 and "attachment" in csv.headers["content-disposition"]

    # Aynı kamera ikinci kez açılırsa eski oturum kapanır (kamera iki kez okunmaz); kayıtlı kamera ayarı gelir
    r2 = client.post("/api/v1/live/sessions", json={"sourceId": src["id"], "profileId": egg["id"]}).json()
    assert r2["profile"]["linePosition"] == 0.4
    assert [s["id"] for s in client.get("/api/v1/live/sessions").json()] == [r2["id"]]
    assert client.get(base).status_code == 404

    assert client.delete(f"/api/v1/live/sources/{src['id']}").status_code == 204    # kaynağın oturumu da kapanır
    assert client.get("/api/v1/live/sessions").json() == []


def test_session_stream_choice_overrides_source(client: TestClient) -> None:
    """Alt/ana akış oturum başına seçilir; kaynağın kayıtlı ayarı değişmez."""
    src = client.post("/api/v1/live/sources", json=camera(substream=True)).json()
    manager = client.app.state.live
    sub_url = manager.opener(manager.source_or_404(src["id"]), None)[0]()
    main_url = manager.opener(manager.source_or_404(src["id"]), None, False)[0]()
    assert sub_url != main_url and SECRET in main_url                      # kimlik bilgisi yalnızca sunucu içinde
    assert manager.opener(manager.source_or_404(src["id"]), None, True)[0]() == sub_url
    assert client.get("/api/v1/live/sources").json()[0]["substream"] is True


def test_live_view_hides_counter_box(tmp_path: pathlib.Path) -> None:
    """Canlı görüntüde sayaç kutusu yok (sayılar panelde); yazılar alt akışta (640 px) küçük."""
    import numpy as np

    from bantvision.core import Profile
    from bantvision.overlay import draw_detect

    frame = np.full((360, 640, 3), 200, np.uint8)
    with_box = draw_detect(frame.copy(), Profile.people(), None, 3, 1, 0.0, 0.0, True, {})
    without = draw_detect(frame.copy(), Profile.people(), None, 3, 1, 0.0, 0.0, True, {}, panel=False)
    assert (without == 200).all() and not (with_box == 200).all()
    dark = (with_box[:, :, :] < 120).all(axis=2)                              # kutu: sol üstte koyu alan
    assert dark[:, :].any(axis=0).sum() < 0.45 * 640                          # 640 px'te genişliğin yarısından az


def test_failed_thumbnail_is_not_retried_for_a_minute(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Kapalı kamera: küçük resim bir kez denenir; 1 dk içinde yeniden RTSP açılmaz (kayıt cihazı boğulmasın)."""
    from fastapi import HTTPException

    src = client.post("/api/v1/live/sources", json=camera()).json()
    manager = client.app.state.live
    calls: list[str | None] = []

    def failing(_src: dict[str, Any], channel_id: str | None) -> bytes:
        calls.append(channel_id)
        raise HTTPException(502, "yok")

    monkeypatch.setattr(manager, "_snapshot", failing)
    for _ in range(3):
        assert client.get(f"/api/v1/live/sources/{src['id']}/snapshot").status_code == 502
    assert len(calls) == 1
    monkeypatch.setattr(manager, "_snapshot", lambda _s, _c: b"\xff\xd8jpeg")
    manager._snap_failed.clear()                                   # süre doldu gibi
    assert client.get(f"/api/v1/live/sources/{src['id']}/snapshot").content == b"\xff\xd8jpeg"


def test_rtsp_uses_ffmpeg7_timeout_option() -> None:
    """FFmpeg 5+ `stimeout`'u yok sayar (kapalı kamerada 30 sn takılma); `timeout` kullanılmalı."""
    from bantvision.live import session

    opts = dict(o.split(";") for o in session._FFMPEG_OPTIONS.split("|"))
    assert opts["rtsp_transport"] == "tcp" and "stimeout" not in opts and int(opts["timeout"]) <= 10_000_000


def test_stream_switch_keeps_counts() -> None:
    """Alt ↔ ana akış değişince oturum aynı kalır: sayaçlar sıfırlanmaz, okuyucu yeni adrese bağlanır."""
    from bantvision.core import Profile
    from bantvision.live.session import LiveSession

    opened: list[str] = []

    def url_a() -> str:
        opened.append("a")
        return str(CLIP)

    def url_b() -> str:
        opened.append("b")
        return str(CLIP)

    s = LiveSession("test", url_a, Profile.egg())
    try:
        wait_for(lambda: s.snapshot_status()["state"] == "live" and s.snapshot_status()["fps"] > 0)
        with s._lock:                                                  # sayım sürmüş gibi
            s._pipe.total = s._counts.total = 7
        sid = s.id
        s.switch_source(url_b)
        assert s.snapshot_status()["message"] == "Görüntü akışı değiştiriliyor…"
        wait_for(lambda: opened[-1:] == ["b"] and s.snapshot_status()["state"] == "live")
        seq = s._seq
        wait_for(lambda: s._seq > seq + 3)                             # yeni akıştan kare geliyor
        st = s.snapshot_status()
        assert st["id"] == sid and st["total"] == 7 and s._pipe.total >= 7
    finally:
        s.stop()


def test_sessions_share_one_detector_and_custom_url_has_no_stream_choice(
        client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANALYZER_ALLOW_FILE_SOURCES", "1")
    egg = next(p for p in client.get("/api/v1/live/profiles").json() if p["name"] == "Yumurta")
    ids = []
    for name in ("Kamera 1", "Kamera 2"):
        src = client.post("/api/v1/live/sources",
                          json=camera(name=name, brand="custom", customUrl=str(CLIP), password="")).json()
        r = client.post("/api/v1/live/sessions", json={"sourceId": src["id"], "profileId": egg["id"]})
        assert r.status_code == 201 and r.json()["substream"] is None
        ids.append(r.json()["id"])
    manager = client.app.state.live
    assert len(client.get("/api/v1/live/sessions").json()) == 2                     # iki kamera aynı anda
    assert all(manager.sessions[i]._pipe.detect._detector is manager.detector for i in ids)
    r = client.put(f"/api/v1/live/sessions/{ids[0]}/stream", json={"substream": False})
    assert r.status_code == 400


def test_idle_scene_skips_detection_but_rechecks_every_second() -> None:
    """Canlı: hareket ve iz yokken tanıma atlanır (saniyede bir yine çalışır); hareket olunca her karede."""
    import numpy as np

    from bantvision.core import Profile
    from bantvision.core.detect_count import DetectCounter

    class Fake:
        calls = 0

        def detect(self, *_a: Any, **_k: Any) -> list[Any]:
            Fake.calls += 1
            return []

    dc = DetectCounter(detector=Fake())               # type: ignore[arg-type]
    dc.enable_gate()
    p = Profile.people()
    still = np.full((288, 352, 3), 90, np.uint8)
    for _ in range(60):                                # 10 fps'te 6 sn boş sahne
        dc.process(still, p, 10.0)
    assert 4 <= Fake.calls <= 8, Fake.calls           # yaklaşık saniyede bir

    Fake.calls = 0
    for k in range(20):                                # alanda hareket eden koyu leke (kişi gibi)
        f = still.copy()
        x = 60 + k * 10
        f[100:220, x:x + 40] = 20
        dc.process(f, p, 10.0)
    assert Fake.calls >= 17, Fake.calls

    plain = DetectCounter(detector=Fake())            # varsayılan (video, iPhone eşdeğeri): her karede tanıma
    Fake.calls = 0
    for _ in range(10):
        plain.process(still, p, 10.0)
    assert Fake.calls == 10


def test_area_and_line_are_saved_per_camera(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Aynı profil iki kamerada: birinde ayarlanıp kaydedilen alan/çizgi diğerini ve şablonu etkilemez."""
    monkeypatch.setenv("ANALYZER_ALLOW_FILE_SOURCES", "1")
    people = next(p for p in client.get("/api/v1/live/profiles").json() if p["name"] == "Mağaza girişi")
    srcs = [client.post("/api/v1/live/sources", json=camera(name=n, brand="custom", customUrl=str(CLIP), password="")
                        ).json() for n in ("Hol", "Dış cephe")]
    hol = client.post("/api/v1/live/sessions", json={"sourceId": srcs[0]["id"], "profileId": people["id"]}).json()
    poly = [{"x": 0.1, "y": 0.0}, {"x": 0.5, "y": 0.0}, {"x": 0.5, "y": 0.8}, {"x": 0.1, "y": 0.8}]
    edited = dict(hol["profile"], roiPolygon=poly, direction="up",
                  roi={"x": 0.1, "y": 0.0, "width": 0.4, "height": 0.8})
    r = client.put(f"/api/v1/live/sessions/{hol['id']}/profile", params={"save": "true"}, json=edited)
    assert r.status_code == 200 and r.json()["profile"]["direction"] == "up"

    cephe = client.post("/api/v1/live/sessions", json={"sourceId": srcs[1]["id"], "profileId": people["id"]}).json()
    assert cephe["profile"]["direction"] == people["direction"] and not cephe["profile"].get("roiPolygon")
    template = next(p for p in client.get("/api/v1/live/profiles").json() if p["id"] == people["id"])
    assert template["direction"] == people["direction"] and not template.get("roiPolygon")

    again = client.post("/api/v1/live/sessions", json={"sourceId": srcs[0]["id"], "profileId": people["id"]}).json()
    assert again["profile"]["direction"] == "up" and len(again["profile"]["roiPolygon"]) == 4

    store = client.app.state.live.store                       # kaynak silinince kamera ayarı da silinir
    assert client.delete(f"/api/v1/live/sources/{srcs[0]['id']}").status_code == 204
    assert store.camera_profile(srcs[0]["id"], None, people["id"]) is None


def test_profile_names_rename_and_delete_rules(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Aynı hazır profil ikinci kez eklenince "Yumurta 2"; yeniden adlandırma boş/çakışan adı reddeder;
    açık canlı sayımı olan profil silinmez."""
    monkeypatch.setenv("ANALYZER_ALLOW_FILE_SOURCES", "1")
    second = client.post("/api/v1/live/profiles", json={"preset": "egg"}).json()
    third = client.post("/api/v1/live/profiles", json={"preset": "egg"}).json()
    assert (second["name"], third["name"]) == ("Yumurta 2", "Yumurta 3")

    base = f"/api/v1/live/profiles/{second['id']}"
    assert client.put(base, json={**second, "name": "  "}).status_code == 422
    assert client.put(base, json={**second, "name": "Yumurta"}).status_code == 409
    r = client.put(base, json={**second, "name": " Hat 2 yumurta "})
    assert r.status_code == 200 and r.json()["name"] == "Hat 2 yumurta"

    src = client.post("/api/v1/live/sources", json=camera(brand="custom", customUrl=str(CLIP), password="")).json()
    s = client.post("/api/v1/live/sessions", json={"sourceId": src["id"], "profileId": second["id"]}).json()
    assert s["profile"]["name"] == "Hat 2 yumurta"
    r = client.delete(base)
    assert r.status_code == 409 and "açık canlı sayım" in r.json()["detail"]
    assert client.delete(f"/api/v1/live/sessions/{s['id']}").status_code == 204
    assert client.delete(base).status_code == 204
    assert client.delete(f"/api/v1/live/profiles/{third['id']}").status_code == 204
    assert [p["name"] for p in client.get("/api/v1/live/profiles").json()].count("Yumurta") == 1


def test_staff_teach_endpoint_and_status(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Personel rengi öğretme: tıklanan yerin rengi döner; durumda staffIn/staffOut; en çok 3 renk."""
    monkeypatch.setenv("ANALYZER_ALLOW_FILE_SOURCES", "1")
    src = client.post("/api/v1/live/sources", json=camera(brand="custom", customUrl=str(CLIP), password="")).json()
    egg = next(p for p in client.get("/api/v1/live/profiles").json() if p["name"] == "Yumurta")
    s = client.post("/api/v1/live/sessions", json={"sourceId": src["id"], "profileId": egg["id"]}).json()
    base = f"/api/v1/live/sessions/{s['id']}"
    wait_for(lambda: client.get(f"{base}/frame.jpg").status_code == 200)
    st = client.get(base).json()
    assert st["staffIn"] == 0 and st["staffOut"] == 0

    r = wait_for(lambda: (q := client.post(f"{base}/staff-color", json={"x": 0.5, "y": 0.5})).status_code != 503 and q)
    assert r.status_code == 200, r.text
    c = r.json()
    assert set(c) == {"L", "a", "b", "achromatic"} and 0 <= c["L"] <= 100
    assert client.post(f"{base}/staff-color", json={"x": 1.5, "y": 0.5}).status_code == 422

    prof = dict(st["profile"], staffColors=[{"L": 50, "a": 10, "b": 10}] * 4)
    assert client.put(f"{base}/profile", json=prof).status_code == 422
    for bad in ({"L": 101, "a": 0, "b": 0}, {"L": -1, "a": 0, "b": 0}, {"L": 50, "a": 128, "b": 0},
                {"L": 50, "a": 0, "b": -129}):
        r = client.put(f"{base}/profile", json=dict(prof, staffColors=[bad]))
        assert r.status_code == 422 and "Personel rengi geçersiz" in r.json()["detail"], (bad, r.text)
    edge = [{"L": 0, "a": -128, "b": 127}, {"L": 100, "a": 127, "b": -128}]      # sınırlar geçerli
    assert client.put(f"{base}/profile", json=dict(prof, staffColors=edge)).status_code == 200
    prof["staffColors"] = [{"L": c["L"], "a": c["a"], "b": c["b"]}]
    assert client.put(f"{base}/profile", json=prof).json()["profile"]["staffColors"][0]["L"] == c["L"]


# ---------------------------------------------------------------------- personel rengi (oturum içi)

def _offline_session(profile: Any) -> Any:
    """Okuyucusu kaynak açamayan oturum ("yok.mp4"): işleyici kare almaz; kareler `_after_frame` ile elle verilir."""
    from bantvision.live.session import LiveSession

    return LiveSession("test", lambda: "yok.mp4", profile)


def _detect_result(boxes: list[tuple[float, float, float, float]], counts: list[int] | None = None,
                   counts_out: list[int] | None = None, staff: list[tuple[int, int]] | None = None) -> Any:
    """Kişi sayımı (detect) için sahte kare sonucu: verilen tanıma kutuları, giriş/çıkış ve personel olayları."""
    from bantvision.core.detect_count import DetectResult
    from bantvision.core.pipeline import FrameResult
    from bantvision.core.tracker import CountEvent

    ins = [CountEvent(t, 1, True, 0.0, None) for t in counts or []]
    outs = [CountEvent(t, 1, True, 0.0, None) for t in counts_out or []]
    r = FrameResult(0.0, [], [], ins, [], [], None, 10.0, 0, (352, 288), None)
    r.counts_out = outs
    r.staff_events = list(staff or [])
    r.detect = DetectResult([], [(b, 0.9) for b in boxes], [], [])
    return r


def _feed(s: Any, r: Any, frame: Any) -> None:
    with s._lock:                                       # işleyici gibi: kilit altında
        s._after_frame(r, frame)


def _decode(jpeg: bytes) -> Any:
    import cv2
    import numpy as np

    return cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)


def test_staff_teach_rejects_dark_spot() -> None:
    import numpy as np

    from bantvision.core import Profile

    s = _offline_session(Profile.egg())
    try:
        with pytest.raises(LookupError):
            s.teach_staff_color(0.5, 0.5)                 # henüz işlenen kare yok
        r = _detect_result([])
        r.detect = None
        _feed(s, r, np.zeros((288, 352, 3), np.uint8))
        assert s.teach_staff_color(0.5, 0.5) is None
    finally:
        s.stop()


ORANGE_BGR = (30, 120, 230)
BLUE_BGR = (200, 60, 20)
GRAY_BGR = (128, 128, 128)
PERSON = (0.30, 0.10, 0.60, 0.95)               # normalize kişi kutusu; gövdesi turuncu
CLICK = (0.45, 0.80)                            # kutunun bacak bölgesi: kutusuz örneklenseydi gri


def _person_frame() -> Any:
    """Gri sahne; kişi kutusunun gövde bölgesi turuncu (tıklama noktası kutu içinde ama gövde dışında: gri)."""
    import numpy as np

    from bantvision.core import Profile
    from bantvision.core.staff_color import torso_region

    h, w = 288, 352
    f = np.full((h, w, 3), GRAY_BGR, np.uint8)
    x0, y0, x1, y1 = torso_region(PERSON, Profile.people().countAnchor)
    f[int(y0 * h):int(y1 * h) + 1, int(x0 * w):int(x1 * w) + 1] = ORANGE_BGR
    return f


def test_staff_teach_uses_served_frame_and_its_boxes() -> None:
    """Panel `frame.jpg` ile hangi kareyi gösterdiyse öğretme onu ve onun kutularını örnekler — sonra daha yeni
    kareler işlense de. Daha yeni karenin pikselleri (mavi) ya da kutuları (yok → tıklanan yer: gri) kullanılsaydı
    turuncu çıkmazdı."""
    import numpy as np

    from bantvision.core import Profile
    from bantvision.core.staff_color import color_distance, srgb_to_lab

    orange = srgb_to_lab(*ORANGE_BGR[::-1])
    blue = srgb_to_lab(*BLUE_BGR[::-1])
    s = _offline_session(Profile.people())
    try:
        assert s.raw_jpeg() is None                                 # kare yok
        _feed(s, _detect_result([PERSON]), _person_frame())
        served = s.raw_jpeg()
        assert served is not None
        assert _decode(served)[int(0.5 * 288), int(0.45 * 352)][2] > 180     # verilen kare: turuncu gövde
        _feed(s, _detect_result([]), np.full((288, 352, 3), BLUE_BGR, np.uint8))       # daha yeni kareler
        _feed(s, _detect_result([(0.0, 0.0, 0.2, 0.3)]), np.full((288, 352, 3), BLUE_BGR, np.uint8))
        c = s.teach_staff_color(*CLICK)
        assert c is not None and color_distance(c, orange) < 1.0, c
        assert s.teach_staff_color(*CLICK) == c                     # tekrar öğretme aynı kareden

        s.raw_jpeg()                                                # yeni kare verildi: öğretme artık onu örnekler
        c2 = s.teach_staff_color(*CLICK)
        assert c2 is not None and color_distance(c2, blue) < 1.0, c2
    finally:
        s.stop()


def test_staff_teach_without_served_frame_uses_latest_processed() -> None:
    import numpy as np

    from bantvision.core import Profile
    from bantvision.core.staff_color import color_distance, srgb_to_lab

    s = _offline_session(Profile.people())
    try:
        _feed(s, _detect_result([]), np.full((288, 352, 3), BLUE_BGR, np.uint8))
        _feed(s, _detect_result([PERSON]), _person_frame())
        c = s.teach_staff_color(*CLICK)                             # son işlenen kare ve kendi kutusu
        assert c is not None and color_distance(c, srgb_to_lab(*ORANGE_BGR[::-1])) < 1.0
        s.raw_jpeg()
        s.set_profile(Profile.people())                             # aynı yöntem (ör. renk eklendi): kare korunur
        assert s.teach_staff_color(*CLICK) == c
        s.set_profile(Profile.egg())                                # yöntem değişti: eski kutular kullanılmaz
        with pytest.raises(LookupError):
            s.teach_staff_color(*CLICK)
    finally:
        s.stop()


def test_staff_events_reach_status_csv_and_labels() -> None:
    """Personel geçişleri (§4.10 eki) web çıkışında: durumda staffIn/staffOut, CSV'de personel_giris/cikis, iz
    etiketi "P"; giriş/çıkış toplamları personelden etkilenmez."""
    import types

    import numpy as np

    from bantvision.core import Profile

    s = _offline_session(Profile.people())
    try:
        s._pipe.detect.tracker.tracks = [types.SimpleNamespace(id=i) for i in (3, 4, 7, 8)]   # canlı izler
        frame = np.full((288, 352, 3), GRAY_BGR, np.uint8)
        with s._lock:
            s._pipe.total, s._pipe.total_out = 1, 1           # sayım hattı bu karede 1 giriş, 1 çıkış saydı
        _feed(s, _detect_result([], counts=[3], counts_out=[4], staff=[(7, 1), (8, -1)]), frame)
        st = s.snapshot_status()
        assert (st["staffIn"], st["staffOut"], st["total"], st["totalOut"]) == (1, 1, 1, 1)
        assert s._labels == {3: "G1", 4: "Ç1", 7: "P", 8: "P"}

        _feed(s, _detect_result([], staff=[(7, 1)]), frame)  # yalnızca personel: toplamlar değişmez
        st = s.snapshot_status()
        assert (st["staffIn"], st["staffOut"], st["total"], st["totalOut"]) == (2, 1, 1, 1)

        rows = [line.split(";") for line in s.counts_csv().strip().splitlines()]
        assert rows[0] == ["zaman", "iz", "yon", "giris_toplam", "cikis_toplam"]
        assert [tuple(r[1:]) for r in rows[1:]] == [
            ("3", "giris", "1", "0"), ("4", "cikis", "1", "1"),
            ("7", "personel_giris", "1", "1"), ("8", "personel_cikis", "1", "1"),
            ("7", "personel_giris", "1", "1")]

        s.reset()
        st = s.snapshot_status()
        assert (st["staffIn"], st["staffOut"]) == (0, 0)
    finally:
        s.stop()
