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
    assert presets == {"egg", "flour", "box", "generic", "people", "jeweler"}   # jeweler: tohumlanmaz, "+ ekle" ile


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


def test_catalog_has_safety_preset(client: TestClient) -> None:
    cat = {c["id"]: c for c in client.get("/api/v1/live/catalog").json()}
    assert cat["safety"]["available"] and cat["safety"]["presets"] == [{"key": "jeweler", "name": "Kuyumcu güvenliği"}]
    p = client.post("/api/v1/live/profiles", json={"preset": "jeweler"}).json()
    assert p["countMode"] == "safety" and p["name"] == "Kuyumcu güvenliği"


# ---------------------------------------------------------------------- poz güvenlik: oturum, alarm günlüğü, Telegram

def _safety_session_with_fake(client: TestClient, monkeypatch: pytest.MonkeyPatch, send_image: bool = False,
                              pose: Any = None) -> tuple[Any, str]:
    """Kuyumcu profiliyle dosya kaynağı; analizör sahte tanıyıcı + sahte pozla (eller yukarı) çalışır.

    Sahteler oturum açılmadan ÖNCE yöneticiye konur: oturum analizörünü onlardan kurar (çalışan iş parçacığının
    altından analizör değiştirilmez, model yüklenmez/indirilmez)."""
    from fakes_safety import FakeDetector, FakePose, hands_up_kp

    monkeypatch.setenv("ANALYZER_ALLOW_FILE_SOURCES", "1")
    mgr = client.app.state.live
    mgr.detector = FakeDetector([(280, 80, 360, 440)])
    mgr.pose = pose or FakePose(hands_up_kp())
    src = client.post("/api/v1/live/sources", json=camera(brand="custom", customUrl=str(CLIP), password="",
                                                          name="Tezgah")).json()
    prof = client.post("/api/v1/live/profiles", json={"preset": "jeweler"}).json()
    if send_image:
        prof = client.put(f"/api/v1/live/profiles/{prof['id']}",
                          json={**prof, "safety": {**prof["safety"], "sendImage": True}}).json()
    s = client.post("/api/v1/live/sessions", json={"sourceId": src["id"], "profileId": prof["id"]}).json()
    return mgr.sessions[s["id"]], s["id"]


def _mock_telegram(client: TestClient) -> None:
    """Testte Telegram'a gerçek istek gitmesin: bildirim istemcisi sahte sunucuya bağlanır."""
    import httpx

    client.app.state.live.notifier._client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True})))


def _fake_safety_session(**over: Any) -> Any:
    from types import SimpleNamespace

    from bantvision.core import Profile

    return SimpleNamespace(**{"id": "x", "name": "Tezgah", "profile": Profile.jeweler(), "source_id": "src",
                              "channel_id": None, **over})


def test_safety_alarm_reaches_store_status_and_queue(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Olay resmi her zaman bu bilgisayarda saklanır (Ruling 17); sendImage kapalıyken Telegram'a yalnızca metin gider."""
    import httpx

    paths: list[str] = []

    def telegram(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(200, json={"ok": True})

    mgr = client.app.state.live
    mgr.notifier._client = httpx.Client(transport=httpx.MockTransport(telegram))
    client.put("/api/v1/live/notify", json={"enabled": True, "chatId": "-1001", "token": "123:GIZLI"})
    _sess, sid = _safety_session_with_fake(client, monkeypatch)
    alarms = wait_for(lambda: client.get("/api/v1/live/alarms?active=1").json(), timeout=30)
    a = alarms[0]
    assert a["type"] == "hands_up" and a["camera"].startswith("Tezgah") and a["sessionId"] == sid
    assert a["notify"] in ("queued", "sent") and a["image"] is True        # sendImage kapalı: resim yine yerelde
    img = client.get(f"/api/v1/live/alarms/{a['id']}/image.jpg")
    assert img.status_code == 200 and img.content[:2] == b"\xff\xd8"
    mgr.notifier.flush()
    assert paths and set(paths) == {"sendMessage"} and mgr.alarms.get(a["id"])["notify"] == "sent"
    st = client.get(f"/api/v1/live/sessions/{sid}").json()
    assert st["safety"]["lastAlarmAt"] is not None
    assert client.post(f"/api/v1/live/alarms/{a['id']}/ack").status_code == 200
    assert all(x["id"] != a["id"] for x in client.get("/api/v1/live/alarms?active=1").json())
    assert "GIZLI" not in client.get("/api/v1/live/notify").text


def test_safety_alarm_with_image_is_stored_and_sent_as_photo(client: TestClient,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    paths: list[str] = []

    def telegram(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(200, json={"ok": True})

    mgr = client.app.state.live
    mgr.notifier._client = httpx.Client(transport=httpx.MockTransport(telegram))
    client.put("/api/v1/live/notify", json={"enabled": True, "chatId": "-1001", "token": "123:GIZLI"})
    _sess, _sid = _safety_session_with_fake(client, monkeypatch, send_image=True)
    a = wait_for(lambda: client.get("/api/v1/live/alarms?active=1").json(), timeout=30)[0]
    assert a["image"] is True
    img = client.get(f"/api/v1/live/alarms/{a['id']}/image.jpg")
    assert img.status_code == 200 and img.content[:2] == b"\xff\xd8"
    mgr.notifier.flush()
    assert paths == ["sendPhoto"] and mgr.alarms.get(a["id"])["notify"] == "sent"


def test_safety_notifications_suppressed_within_cooldown(client: TestClient) -> None:
    from types import SimpleNamespace

    from bantvision.core import Profile
    from bantvision.core.safety import SafetyAlarm

    mgr = client.app.state.live
    _mock_telegram(client)
    fake_session = SimpleNamespace(id="x", name="Tezgah", profile=Profile.jeweler(), source_id="src", channel_id=None)
    client.put("/api/v1/live/notify", json={"enabled": True, "chatId": "-1", "token": "1:T"})
    mgr.on_safety(fake_session, [SafetyAlarm("hands_up", 1, (0, 0, 1, 1), 0.0, 3.0)], [], None)
    mgr.on_safety(fake_session, [SafetyAlarm("hands_up", 2, (0, 0, 1, 1), 5.0, 8.0)], [], None)
    st = [a["notify"] for a in client.get("/api/v1/live/alarms").json()]
    assert "suppressed" in st and len(st) == 2 and set(st) <= {"queued", "sent", "suppressed"}


def test_test_alarm_and_notify_endpoints(client: TestClient) -> None:
    r = client.post("/api/v1/live/alarms/test", json={})
    assert r.status_code == 200 and r.json()["type"] == "test" and r.json()["notify"] == "disabled"
    assert client.get("/api/v1/live/alarms?active=1").json()[0]["type"] == "test"
    img = client.get(f"/api/v1/live/alarms/{r.json()['id']}/image.jpg")
    assert img.status_code == 404 and img.json()["detail"] == "Olay resmi yok (7 günü geçti ya da alınamadı)."
    r = client.post("/api/v1/live/notify/test")
    assert r.status_code == 422 and "eksik" in r.json()["detail"]
    cfg = client.put("/api/v1/live/notify", json={"enabled": False, "chatId": " -100 ", "token": "9:Z"}).json()
    assert cfg == {"enabled": False, "chatId": "-100", "hasToken": True, "lastError": None}


def test_test_alarm_is_queued_and_sent_when_configured(client: TestClient) -> None:
    mgr = client.app.state.live
    _mock_telegram(client)
    client.put("/api/v1/live/notify", json={"enabled": True, "chatId": "-1", "token": "1:T"})
    rec = client.post("/api/v1/live/alarms/test", json={}).json()
    assert rec["notify"] == "queued"
    mgr.notifier.flush()
    assert mgr.alarms.get(rec["id"])["notify"] == "sent"
    assert client.post("/api/v1/live/notify/test").json() == {"ok": True}
    assert client.get("/api/v1/live/alarms", params={"since": time.time() + 60}).json() == []
    assert client.post("/api/v1/live/alarms/yok/ack").status_code == 404


def test_alarms_endpoint_filters_by_session_id(client: TestClient) -> None:
    mgr = client.app.state.live
    mine = mgr.alarms.add("s1", "Tezgah", "hands_up", 1.0, 1.0, None, "disabled")
    for i in range(55):                                      # başka kameranın daha yeni alarmları genel 50 sınırını aşar
        mgr.alarms.add("s2", "Depo", "lying", 10.0 + i, 10.0 + i, None, "disabled")
    assert mine["id"] not in [a["id"] for a in client.get("/api/v1/live/alarms").json()]
    got = client.get("/api/v1/live/alarms", params={"sessionId": "s1"}).json()
    assert [a["id"] for a in got] == [mine["id"]]
    assert client.get("/api/v1/live/alarms", params={"sessionId": "s1", "active": 1}).json() == got
    assert client.get("/api/v1/live/alarms", params={"sessionId": "yok"}).json() == []
    assert client.post(f"/api/v1/live/alarms/{mine['id']}/ack").status_code == 200
    assert client.get("/api/v1/live/alarms", params={"sessionId": "s1", "active": 1}).json() == []


def test_notify_rejects_malformed_token_without_echo(client: TestClient) -> None:
    secret = "BIÇİMSİZANAHTAR"
    r = client.put("/api/v1/live/notify", json={"enabled": True, "chatId": "-1", "token": secret})
    assert r.status_code == 422 and "Telegram" in r.json()["detail"]
    assert secret not in r.text
    assert client.get("/api/v1/live/notify").json()["hasToken"] is False        # hiçbir şey yazılmadı


def test_notify_test_reports_rejection_without_token(client: TestClient) -> None:
    import httpx

    mgr = client.app.state.live
    replies = [httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"})]
    mgr.notifier._client = httpx.Client(transport=httpx.MockTransport(
        lambda r: replies.pop(0) if replies else httpx.Response(200, json={"ok": True})))
    client.put("/api/v1/live/notify", json={"enabled": True, "chatId": "-1", "token": "123:GIZLI"})
    r = client.post("/api/v1/live/notify/test")
    assert r.status_code == 422 and "GIZLI" not in r.text
    assert r.json()["detail"] == "Sohbet / grup kimliği bulunamadı; botu gruba ekleyin."
    got = client.get("/api/v1/live/notify").json()
    assert got["lastError"]["text"] == r.json()["detail"] and abs(got["lastError"]["at"] - time.time()) < 60
    assert "GIZLI" not in client.get("/api/v1/live/notify").text
    assert client.post("/api/v1/live/notify/test").json() == {"ok": True}
    assert client.get("/api/v1/live/notify").json()["lastError"] is None      # başarılı gönderim temizler
    replies.append(httpx.Response(401, json={"ok": False, "description": "Unauthorized"}))
    assert client.post("/api/v1/live/notify/test").status_code == 422
    assert client.get("/api/v1/live/notify").json()["lastError"]["text"] == "Bot anahtarı geçersiz."
    r = client.put("/api/v1/live/notify", json={"enabled": True, "chatId": "-1", "token": "123:YENI"})
    assert r.json()["lastError"] is None                                      # yeni anahtar: eski hata silinir


def test_alarm_image_endpoint_serves_stored_image(client: TestClient) -> None:
    from bantvision.core.safety import SafetyAlarm

    s = _fake_safety_session()
    s.profile.safety.sendImage = True
    jpeg = b"\xff\xd8\xff\xe0fake-jpeg"
    client.app.state.live.on_safety(s, [SafetyAlarm("lying", 3, (0, 0, 1, 1), 0.0, 10.0)], [], jpeg)
    a = client.get("/api/v1/live/alarms").json()[0]
    assert a["image"] is True and a["type"] == "lying"
    r = client.get(f"/api/v1/live/alarms/{a['id']}/image.jpg")
    assert r.status_code == 200 and r.content == jpeg and r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "no-store"
    assert client.get("/api/v1/live/alarms/..%2F..%2Fsecrets/image.jpg").status_code == 404


def test_on_safety_ends_old_episode_before_registering_new_one(client: TestClient) -> None:
    """Aynı karede aynı (iz, tür) için eski bölümün sonu ve yeni alarm gelirse eski kapanır, yeni açık kalır."""
    from bantvision.core.safety import SafetyAlarm

    mgr, s = client.app.state.live, _fake_safety_session()
    mgr.on_safety(s, [SafetyAlarm("hands_up", 1, (0, 0, 1, 1), 0.0, 3.0)], [], None)
    old = mgr.alarms.list()[0]["id"]
    mgr.on_safety(s, [SafetyAlarm("hands_up", 1, (0, 0, 1, 1), 20.0, 23.0)], [(1, "hands_up", True)], None)
    by_id = {a["id"]: a for a in mgr.alarms.list()}
    assert len(by_id) == 2 and by_id[old]["endedAt"] is not None
    assert [a for a in by_id.values() if a["endedAt"] is None] != []
    mgr.close_alarms("x")
    assert all(a["endedAt"] is not None for a in mgr.alarms.list())


def test_on_safety_cooldown_is_atomic_across_threads(client: TestClient) -> None:
    """Birden çok oturum iş parçacığı aynı kamera/tür için aynı anda alarm verirse yalnız biri bildirim alır."""
    import threading

    from bantvision.core.safety import SafetyAlarm

    mgr, s = client.app.state.live, _fake_safety_session()
    _mock_telegram(client)
    client.put("/api/v1/live/notify", json={"enabled": True, "chatId": "-1", "token": "1:T"})
    barrier = threading.Barrier(8)

    def fire(tid: int) -> None:
        barrier.wait()
        mgr.on_safety(s, [SafetyAlarm("hands_up", tid, (0, 0, 1, 1), 0.0, 3.0)], [], None)

    threads = [threading.Thread(target=fire, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    states = [a["notify"] for a in mgr.alarms.list()]
    assert len(states) == 8 and sum(1 for n in states if n != "suppressed") == 1


def test_deleting_safety_session_closes_its_alarm(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _sess, sid = _safety_session_with_fake(client, monkeypatch)
    a = wait_for(lambda: client.get("/api/v1/live/alarms?active=1").json(), timeout=30)[0]
    assert a["endedAt"] is None
    assert client.delete(f"/api/v1/live/sessions/{sid}").status_code == 204
    mgr = client.app.state.live
    assert mgr.alarms.get(a["id"])["endedAt"] is not None
    assert not mgr._alarm_of


def test_stopping_safety_session_closes_its_alarm(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Çalışma döngüsü biterken (stop; kaynak silme / aynı kamerayı yeniden açma dahil) açık alarm kapanır."""
    sess, _sid = _safety_session_with_fake(client, monkeypatch)
    a = wait_for(lambda: client.get("/api/v1/live/alarms?active=1").json(), timeout=30)[0]
    sess.stop()
    assert client.app.state.live.alarms.get(a["id"])["endedAt"] is not None


def test_switching_session_away_from_safety_closes_its_alarm(
        client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from bantvision.core import Profile

    _sess, sid = _safety_session_with_fake(client, monkeypatch)
    a = wait_for(lambda: client.get("/api/v1/live/alarms?active=1").json(), timeout=30)[0]
    r = client.put(f"/api/v1/live/sessions/{sid}/profile", json=Profile.people().to_dict())
    assert r.status_code == 200 and r.json()["safety"] is None
    assert client.app.state.live.alarms.get(a["id"])["endedAt"] is not None


def test_app_shutdown_closes_open_alarms(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bantvision.live.alarms import AlarmStore

    with TestClient(create_app(Settings(data_dir=tmp_path))) as c:
        _sess, _sid = _safety_session_with_fake(c, monkeypatch)
        a = wait_for(lambda: c.get("/api/v1/live/alarms?active=1").json(), timeout=30)[0]
    assert AlarmStore(tmp_path).get(a["id"])["endedAt"] is not None


def test_session_builds_safety_analyzer_from_shared_models() -> None:
    from fakes_safety import FakeDetector, FakePose, hands_up_kp

    from bantvision.core import Profile
    from bantvision.live.session import LiveSession

    det, pose = FakeDetector([]), FakePose(hands_up_kp())
    s = LiveSession("t", lambda: "yok.mp4", Profile.jeweler(), detector=det, pose=pose)
    try:
        an = s._pipe.safety
        assert an is not None and an._pose is pose and an.dc._detector is det and an.dc._gate is not None
        sf = s.snapshot_status()["safety"]
        assert {k: sf[k] for k in ("active", "lastAlarmAt", "model", "modelError", "detector", "detectorError")} == {
            "active": [], "lastAlarmAt": None, "model": "ready", "modelError": None,                # sahte: durumsuz
            "detector": "ready", "detectorError": None}
        assert sf["healthy"] is False and sf["reason"] in ("Kameraya bağlanılıyor", "Kamera bağlantısı yok")
        s.set_profile(Profile.people())
        assert s.snapshot_status()["safety"] is None
        s.set_profile(Profile.jeweler())                       # yeniden güvenliğe: ortak modellerle yeni analizör
        an2 = s._pipe.safety
        assert an2 is not None and an2 is not an and an2._pose is pose and an2.dc._detector is det
        assert an2.dc._gate is not None
        plain = LiveSession("t2", lambda: "yok.mp4", Profile.people(), detector=det, pose=pose)
        try:
            assert plain._pipe.safety is None and plain.snapshot_status()["safety"] is None
        finally:
            plain.stop()
    finally:
        s.stop()


def test_safety_overlay_follows_upscaled_frame() -> None:
    """Alt akış (<720 px) büyütülerek çizilir: eklemler (piksel) aynı oranda büyür, iskelet yerinde kalır."""
    import numpy as np

    from bantvision.core import Profile
    from bantvision.core.safety import SafetyResult

    s = _offline_session(Profile.jeweler())
    try:
        kp = np.zeros((17, 3))
        kp[5], kp[6] = (150, 100, 0.9), (210, 100, 0.9)        # omuz çizgisi 360×288 karede y = 100
        track = type("T", (), {"id": 1, "box": np.array([0.3, 0.1, 0.7, 0.9])})()
        r = type("R", (), {"safety": SafetyResult(tracks=[track], poses={1: kp})})()
        img = s._render(np.zeros((288, 360, 3), np.uint8), s.profile, r)
        assert img.shape[1] == 720 and img[200, 360].any() and not img[100, 180].any()
    finally:
        s.stop()


def test_fps_from_stamps_never_divides_by_zero() -> None:
    """Windows saati kaba: hızlı işlenen ardışık kareler aynı damgayı alabilir; fps hesabı sıfıra bölünmemeli
    (bölünürse çalışma iş parçacığı ölür, oturum sessizce durur, alarm da gelmez)."""
    from bantvision.live.session import fps_from_stamps

    assert fps_from_stamps([]) == 0.0 and fps_from_stamps([5.0]) == 0.0 and fps_from_stamps([5.0, 5.1]) == 0.0
    assert fps_from_stamps([7.0, 7.0, 7.0]) == 0.0                                   # aynı damga: bölme yok
    assert fps_from_stamps([7.0] * 40) == 0.0
    assert fps_from_stamps([1.0, 1.1, 1.2, 1.3, 1.4, 1.5]) == pytest.approx(10.0)    # 5 aralık / 0,5 sn
    assert fps_from_stamps([0.0, 0.5, 1.0]) == pytest.approx(2.0)


@pytest.mark.parametrize("safety", [
    5, "x", [], {"handsUp": 5}, {"handsUp": None}, {"lying": []},
    {"handsUp": {"enabled": "false"}}, {"handsUp": {"enabled": 1}}, {"lying": {"enabled": None}},
    {"handsUp": {"seconds": "3"}}, {"handsUp": {"seconds": True}}, {"lying": {"seconds": None}},
    {"handsUp": {"seconds": 2.9}}, {"handsUp": {"seconds": 5.1}}, {"lying": {"seconds": 4.9}},
    {"lying": {"seconds": 30.1}}, {"handsUp": {"seconds": -3}}, {"sendImage": "evet"}, {"sendImage": 1},
])
def test_profile_rejects_malformed_safety_block(client: TestClient, safety: Any) -> None:
    body = client.post("/api/v1/live/profiles", json={"preset": "jeweler"}).json()
    body["safety"] = safety
    r = client.post("/api/v1/live/profiles", json=body)
    assert r.status_code == 422 and "Güvenlik" in r.json()["detail"], r.text


@pytest.mark.parametrize("seconds", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_profile_rejects_non_finite_safety_seconds(client: TestClient, seconds: str) -> None:
    body = client.post("/api/v1/live/profiles", json={"preset": "jeweler"}).json()
    raw = json.dumps({**body, "safety": {"handsUp": {"enabled": True, "seconds": "@"}}}).replace('"@"', seconds)
    r = client.post("/api/v1/live/profiles", content=raw, headers={"content-type": "application/json"})
    assert r.status_code == 422 and "Güvenlik" in r.json()["detail"], r.text


def test_profile_accepts_valid_safety_block_and_session_put_validates(
        client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    body = client.post("/api/v1/live/profiles", json={"preset": "jeweler"}).json()
    ok = {"handsUp": {"enabled": False, "seconds": 5}, "lying": {"enabled": True, "seconds": 30}, "sendImage": True}
    r = client.post("/api/v1/live/profiles", json={**body, "safety": ok, "name": "Yeni kuyumcu"})
    assert r.status_code == 201 and r.json()["safety"]["lying"]["seconds"] == 30.0 and r.json()["safety"]["sendImage"]
    assert client.post("/api/v1/live/profiles", json={**body, "safety": {}, "name": "Boş"}).status_code == 201
    assert client.post("/api/v1/live/profiles", json={**body, "safety": None, "name": "Yok"}).status_code == 201
    bad = {**body, "safety": {"lying": {"seconds": 99}}}
    assert client.put(f"/api/v1/live/profiles/{body['id']}", json=bad).status_code == 422
    # oturum: yerel video dosyası + sahte tanıyıcı/poz (LAN'daki gerçek cihaza bağlanılmaz, model yüklenmez)
    _sess, s_id = _safety_session_with_fake(client, monkeypatch)
    live_profile = client.get(f"/api/v1/live/sessions/{s_id}").json()["profile"]
    r = client.put(f"/api/v1/live/sessions/{s_id}/profile", json={**live_profile, "safety": bad["safety"]})
    assert r.status_code == 422 and "Güvenlik" in r.json()["detail"]
    r = client.put(f"/api/v1/live/sessions/{s_id}/profile", json={**live_profile, "safety": ok})
    assert r.status_code == 200 and r.json()["profile"]["safety"]["lying"]["seconds"] == 30.0


def test_cleanup_loop_survives_failures(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Saatlik temizlikte bir hata döngüyü öldürmez; sonraki turda iş yine denenir."""
    import threading

    from bantvision.analyzer import app as app_mod
    from bantvision.analyzer.jobs import JobStore
    from bantvision.live.alarms import AlarmStore

    monkeypatch.setattr(app_mod, "CLEANUP_INTERVAL_S", 0.05)
    calls = {"jobs": 0, "alarms": 0}
    real_expire = JobStore.expire

    def jobs_expire(self: Any) -> Any:
        calls["jobs"] += 1
        if calls["jobs"] > 1:                                  # ilk çağrı açılışta; sonrakiler döngüden
            raise OSError("disk hatası")
        return real_expire(self)

    def alarms_expire(self: Any, now: float, days: float = 7) -> int:
        calls["alarms"] += 1
        raise RuntimeError("alarm günlüğü bozuk")

    monkeypatch.setattr(JobStore, "expire", jobs_expire)
    monkeypatch.setattr(AlarmStore, "expire", alarms_expire)
    with TestClient(create_app(Settings(data_dir=tmp_path))):
        wait_for(lambda: calls["jobs"] >= 4, timeout=10)
        assert any(t.name == "analiz-temizlik" and t.is_alive() for t in threading.enumerate())
        wait_for(lambda: calls["alarms"] >= 2, timeout=10)           # iş hatasına rağmen alarm temizliği de denenir


# ---------------------------------------------------------------------- düzeltme turu 1

def test_validation_error_does_not_echo_secrets(client: TestClient) -> None:
    """FastAPI'nin varsayılan 422'si girilen değeri (`input`) yankılar; anahtar/şifre yanıta sızmamalı."""
    secret = "GIZLIANAHTAR" * 25                                                     # 300 karakter > sınır
    r = client.put("/api/v1/live/notify", json={"enabled": True, "chatId": "-1", "token": secret})
    assert r.status_code == 422 and "GIZLIANAHTAR" not in r.text
    err = r.json()["detail"][0]
    assert err["type"] == "string_too_long" and err["loc"][-1] == "token"           # panelin okuduğu alanlar korunur
    assert not {"input", "ctx", "url"} & err.keys()
    for bad in (123456789012, ["GIZLIDEGER"], {"k": "GIZLIDEGER"}):                  # dize olmayan anahtar
        r = client.put("/api/v1/live/notify", json={"enabled": True, "chatId": "-1", "token": bad})
        assert r.status_code == 422 and "GIZLIDEGER" not in r.text and "123456789012" not in r.text, r.text
        assert r.json()["detail"][0]["type"] == "string_type" and "input" not in r.json()["detail"][0]
    r = client.post("/api/v1/live/sources", json=camera(password="SIFRE" * 60))     # kamera şifresi de sızmaz
    assert r.status_code == 422 and "SIFRE" not in r.text
    r = client.post("/api/v1/live/sources", json={**camera(), "extra": 1})
    assert r.status_code == 422 and r.json()["detail"][0]["type"] == "extra_forbidden"


def test_cooldown_bookkeeping_uses_monotonic_clock(client: TestClient) -> None:
    from bantvision.core.safety import SafetyAlarm

    mgr = client.app.state.live
    _mock_telegram(client)
    client.put("/api/v1/live/notify", json={"enabled": True, "chatId": "-1", "token": "1:T"})
    mgr.on_safety(_fake_safety_session(), [SafetyAlarm("hands_up", 1, (0, 0, 1, 1), 0.0, 3.0)], [], None)
    (stamp,) = mgr._last_sent.values()
    assert abs(stamp - time.monotonic()) < 5 and abs(stamp - time.time()) > 1e6      # tekdüze saat, duvar saati değil
    assert abs(mgr.alarms.list()[0]["firedAt"] - time.time()) < 5                    # alarm zamanı duvar saati


def test_on_safety_ends_open_alarm_whenever_an_entry_exists(client: TestClient) -> None:
    from bantvision.core.safety import SafetyAlarm

    mgr, s = client.app.state.live, _fake_safety_session()
    mgr.on_safety(s, [SafetyAlarm("hands_up", 1, (0, 0, 1, 1), 0.0, 3.0)], [], None)
    aid = mgr.alarms.list()[0]["id"]
    mgr.on_safety(s, [], [(1, "hands_up", False)], None)                            # was_fired bayrağı önemsiz
    assert mgr.alarms.get(aid)["endedAt"] is not None and not mgr._alarm_of


def test_on_safety_new_alarm_ends_open_one_with_same_key(client: TestClient) -> None:
    from bantvision.core.safety import SafetyAlarm

    mgr, s = client.app.state.live, _fake_safety_session()
    mgr.on_safety(s, [SafetyAlarm("hands_up", 1, (0, 0, 1, 1), 0.0, 3.0)], [], None)
    first = mgr.alarms.list()[0]["id"]
    mgr.on_safety(s, [SafetyAlarm("hands_up", 1, (0, 0, 1, 1), 20.0, 23.0)], [], None)   # eskisinin sonu bildirilmedi
    by_id = {a["id"]: a for a in mgr.alarms.list()}
    second = next(i for i in by_id if i != first)
    assert by_id[first]["endedAt"] is not None and by_id[second]["endedAt"] is None
    assert list(mgr._alarm_of.values()) == [second]


def test_in_flight_alarm_after_leaving_safety_is_recorded_and_closed(client: TestClient) -> None:
    from bantvision.core import Profile
    from bantvision.core.safety import SafetyAlarm

    mgr = client.app.state.live
    s = _fake_safety_session(profile=Profile.people())                              # oturum güvenlikten çıkmış
    mgr.on_safety(s, [SafetyAlarm("lying", 4, (0, 0, 1, 1), 0.0, 10.0)], [], None)
    (a,) = mgr.alarms.list()
    assert a["type"] == "lying" and a["endedAt"] is not None and not mgr._alarm_of


def test_session_stop_reports_alarms_cut_by_reset() -> None:
    """Alarmlı bölüm `reset()` ile kesilmiş ama sonu bir sonraki karede bildirilecekken oturum durursa o son da iletilir."""
    import numpy as np
    from fakes_safety import FakeDetector, FakePose, hands_up_kp

    from bantvision.core import Profile
    from bantvision.core.safety import SafetyAnalyzer
    from bantvision.live.session import LiveSession

    calls: list[Any] = []
    det, pose = FakeDetector([(280, 80, 360, 440)]), FakePose(hands_up_kp())
    s = LiveSession("t", lambda: "yok.mp4", Profile.jeweler(), detector=det, pose=pose,
                    alarm_sink=lambda *a: calls.append(a))
    try:
        an = SafetyAnalyzer(detector=det, pose=pose)             # kare akmayan oturumda kapısız analizör: elle sürülür
        with s._lock:
            s._pipe.safety = an
            frame = np.zeros((480, 640, 3), np.uint8)
            fired = [a for k in range(50) for a in an.process(frame, s.profile, 10.0, k / 10.0).fired]
            assert len(fired) == 1
            s._pipe.reset_count()                                # bölüm kesilir; sonu henüz hiçbir sonuçta bildirilmedi
            assert not an.episodes.active()
    finally:
        s.stop()
    assert [c[2] for c in calls] == [[(fired[0].track_id, "hands_up", True)]] and calls[0][1] == []


def test_shared_pose_loads_in_background_and_never_blocks() -> None:
    import threading

    from bantvision.live.api import SharedPose

    gate, started, calls = threading.Event(), threading.Event(), []

    class Model:
        def estimate(self, *_a: Any, **_k: Any) -> str:
            return "kp"

    def loader() -> Model:
        calls.append(1)
        started.set()
        assert gate.wait(30)
        return Model()

    pose = SharedPose(loader=loader)
    assert pose.state == "loading" and pose.error == ""
    t0 = time.monotonic()
    assert pose.estimate("bgr", (0, 0, 1, 1)) is None                                # engellemez
    assert time.monotonic() - t0 < 1.0 and started.wait(5) and pose.state == "loading"
    assert pose.estimate("bgr", (0, 0, 1, 1)) is None and len(calls) == 1            # yükleme sürerken ikinci iş parçacığı yok
    gate.set()
    wait_for(lambda: pose.state == "ready", timeout=10)
    assert pose.estimate("bgr", (0, 0, 1, 1)) == "kp" and pose.error == "" and len(calls) == 1


def test_shared_pose_failure_is_logged_and_retried_only_after_60_seconds(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    from bantvision.live.api import SharedPose

    now, calls = [1000.0], []

    class Model:
        def estimate(self, *_a: Any, **_k: Any) -> str:
            return "kp"

    def loader() -> Model:
        calls.append(1)
        if len(calls) == 1:
            raise OSError("ağ yok")
        return Model()

    pose = SharedPose(loader=loader, clock=lambda: now[0])
    with caplog.at_level(logging.ERROR):
        assert pose.estimate("bgr", (0, 0, 1, 1)) is None
        wait_for(lambda: pose.state == "error", timeout=10)
    assert pose.error.startswith("Poz modeli yüklenemedi") and "ağ yok" in pose.error
    assert any("Poz modeli yüklenemedi" in r.getMessage() for r in caplog.records)
    for _ in range(5):                                                              # her karede yeniden denenmez
        assert pose.estimate("bgr", (0, 0, 1, 1)) is None
    now[0] += 59.0
    assert pose.estimate("bgr", (0, 0, 1, 1)) is None
    time.sleep(0.3)
    assert len(calls) == 1 and pose.state == "error"
    now[0] += 2.0                                                                    # toplam 61 sn: yeniden denenir
    assert pose.estimate("bgr", (0, 0, 1, 1)) is None
    wait_for(lambda: pose.state == "ready", timeout=10)
    assert len(calls) == 2 and pose.error == "" and pose.estimate("bgr", (0, 0, 1, 1)) == "kp"


def test_session_status_reports_pose_model_state() -> None:
    import threading

    from bantvision.core import Profile
    from bantvision.live.api import SharedPose
    from bantvision.live.session import LiveSession

    gate = threading.Event()

    def broken() -> Any:
        assert gate.wait(30)
        raise OSError("ağ yok")

    pose = SharedPose(loader=broken)
    s = LiveSession("t", lambda: "yok.mp4", Profile.jeweler(), pose=pose)           # ısınma yüklemeyi başlatır
    try:
        assert s.snapshot_status()["safety"]["model"] == "loading"
        gate.set()
        wait_for(lambda: s.snapshot_status()["safety"]["model"] == "error", timeout=10)
    finally:
        gate.set()
        s.stop()


def test_shared_pose_does_not_reload_a_ready_model() -> None:
    """Okuyucu `_inner`'ı None görüp yükleme biterken kilide gelirse model yeniden yüklenmemeli (durum "ready" kalır)."""
    from bantvision.live.api import SharedPose

    calls: list[int] = []

    class Model:
        def estimate(self, *_a: Any, **_k: Any) -> str:
            return "kp"

    def loader() -> Model:
        calls.append(1)
        return Model()

    pose = SharedPose(loader=loader)
    assert pose.estimate("bgr", (0, 0, 1, 1)) is None
    wait_for(lambda: pose.state == "ready", timeout=10)
    pose._start_loading()                                  # gecikmiş okuyucu: yükleme zaten bitti
    pose.warm()
    if pose._thread is not None:
        pose._thread.join(5)
    assert calls == [1] and pose.state == "ready" and pose.estimate("bgr", (0, 0, 1, 1)) == "kp"


def test_shared_pose_logs_failure_before_publishing_error_state(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    from bantvision.live.api import SharedPose

    def broken() -> Any:
        raise OSError("ağ yok")

    pose = SharedPose(loader=broken)
    seen: list[str] = []

    class Spy(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(pose.state)                        # günlük yazılırken durum henüz "error" olmamalı

    logger = logging.getLogger("bantvision.live.api")
    spy = Spy(level=logging.ERROR)
    logger.addHandler(spy)
    try:
        with caplog.at_level(logging.ERROR):
            pose.warm()
            wait_for(lambda: pose.state == "error", timeout=10)
    finally:
        logger.removeHandler(spy)
    assert seen == ["loading"] and any("Poz modeli yüklenemedi" in r.getMessage() for r in caplog.records)


def test_safety_session_warms_up_pose_model_without_any_person_or_frame() -> None:
    """Model ilk kişi görününce değil, oturum güvenliğe geçer geçmez yüklenmeye başlar (sahte yükleyici, kare yok)."""
    import threading

    from bantvision.core import Profile
    from bantvision.live.api import SharedPose
    from bantvision.live.session import LiveSession

    gate, started = threading.Event(), threading.Event()
    calls: list[int] = []

    def loader() -> Any:
        calls.append(1)
        started.set()
        assert gate.wait(30)
        return object()

    pose = SharedPose(loader=loader)
    other = LiveSession("d", lambda: "yok.mp4", Profile.people(), pose=pose)         # güvenlik değil: ısınma yok
    sessions = [other]
    try:
        time.sleep(0.3)
        assert not started.is_set() and pose.state == "loading"
        other.set_profile(Profile.jeweler())                                          # güvenliğe geçiş ısıtır
        assert started.wait(5) and calls == [1]
        sessions.append(LiveSession("s", lambda: "yok.mp4", Profile.jeweler(), pose=pose))   # ikinci oturum: yeniden yok
        time.sleep(0.3)
        assert calls == [1]
        gate.set()
        wait_for(lambda: pose.state == "ready", timeout=10)
        sessions.append(LiveSession("s2", lambda: "yok.mp4", Profile.jeweler(), pose=pose))
        assert calls == [1] and pose.state == "ready"
    finally:
        gate.set()
        for s in sessions:
            s.stop()


def test_safety_session_keeps_streaming_while_pose_model_loads(
        client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Poz modeli yüklenirken (indirme) görüntü akar ve durum "loading" der; model gelince alarm doğar."""
    import threading

    from fakes_safety import FakePose, hands_up_kp

    from bantvision.live.api import SharedPose

    gate = threading.Event()

    def loader() -> Any:
        assert gate.wait(60)
        return FakePose(hands_up_kp())

    _sess, sid = _safety_session_with_fake(client, monkeypatch, pose=SharedPose(loader=loader))
    base = f"/api/v1/live/sessions/{sid}"
    v = wait_for(lambda: (v := client.get(base).json())["state"] == "live" and v["fps"] > 0 and v, timeout=30)
    assert v["safety"]["model"] == "loading" and client.get("/api/v1/live/alarms").json() == []
    assert wait_for(lambda: client.get(f"{base}/frame.jpg").status_code == 200, timeout=10)
    gate.set()
    a = wait_for(lambda: client.get("/api/v1/live/alarms?active=1").json(), timeout=30)[0]
    assert a["type"] == "hands_up" and client.get(base).json()["safety"]["model"] == "ready"


# ---------------------------------------------------------------------- son düzeltme dalgası A: ortak tanıma modeli (I6)

def test_shared_detector_loads_in_background_and_returns_no_detections_meanwhile() -> None:
    """YOLOX (indirme dahil) arka planda yüklenir: o sürece `detect` engellemeden "kişi yok" döner; çıkarım kilidi
    yükleme sırasında tutulmaz (eskiden ilk kare indirme bitene dek tüm kameraları bekletiyordu)."""
    import threading

    from bantvision.live.api import SharedDetector

    gate, started, calls = threading.Event(), threading.Event(), []

    class Model:
        def detect(self, *_a: Any, **_k: Any) -> list[str]:
            return ["kişi"]

    def loader() -> Model:
        calls.append(1)
        started.set()
        assert gate.wait(30)
        return Model()

    det = SharedDetector(loader=loader)
    assert det.state == "loading" and det.error == ""
    t0 = time.monotonic()
    assert det.detect("bgr", ["person"]) == []
    assert time.monotonic() - t0 < 1.0 and started.wait(5) and det.state == "loading"
    out = det.detect("bgr", ["person"])
    assert out == [] and len(calls) == 1
    out.append("x")                                                                 # her çağrı yeni boş liste
    assert det.detect("bgr", ["person"]) == []
    gate.set()
    wait_for(lambda: det.state == "ready", timeout=10)
    assert det.detect("bgr", ["person"]) == ["kişi"] and det.error == "" and len(calls) == 1


def test_shared_detector_failure_is_turkish_logged_and_retried_after_60_seconds(
        caplog: pytest.LogCaptureFixture) -> None:
    import logging
    import urllib.error

    from bantvision.live.api import SharedDetector

    now, calls = [1000.0], []

    class Model:
        def detect(self, *_a: Any, **_k: Any) -> list[str]:
            return ["kişi"]

    def loader() -> Model:
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.URLError("getaddrinfo failed")
        return Model()

    det = SharedDetector(loader=loader, clock=lambda: now[0])
    with caplog.at_level(logging.ERROR):
        det.warm()
        wait_for(lambda: det.state == "error", timeout=10)
    assert det.error == "Kişi tanıma modeli yüklenemedi: internete ulaşılamadı (bağlantıyı kontrol edin)"
    assert any("getaddrinfo" in r.getMessage() for r in caplog.records)             # asıl ileti günlükte
    for _ in range(5):
        assert det.detect("bgr", ["person"]) == []
    now[0] += 59.0
    det.warm()
    time.sleep(0.3)
    assert len(calls) == 1 and det.state == "error"
    now[0] += 2.0
    assert det.detect("bgr", ["person"]) == []
    wait_for(lambda: det.state == "ready", timeout=10)
    assert len(calls) == 2 and det.error == "" and det.detect("bgr", ["person"]) == ["kişi"]


def test_shared_detector_serialises_inference_and_never_reloads_ready_model() -> None:
    import threading

    from bantvision.live.api import SharedDetector

    calls: list[int] = []
    inside, peak = [0], [0]
    lock = threading.Lock()

    class Model:
        def detect(self, *_a: Any, **_k: Any) -> list[str]:
            with lock:
                inside[0] += 1
                peak[0] = max(peak[0], inside[0])
            time.sleep(0.02)
            with lock:
                inside[0] -= 1
            return []

    def loader() -> Model:
        calls.append(1)
        return Model()

    det = SharedDetector(loader=loader)
    det.warm()
    wait_for(lambda: det.state == "ready", timeout=10)
    det._start_loading()                                       # hazır modeli yeniden yüklemez
    threads = [threading.Thread(target=det.detect, args=("bgr", ["person"])) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert calls == [1] and peak[0] == 1                       # kareler sırayla


def test_detect_counting_does_not_count_while_detector_loads() -> None:
    """Kişi sayımı model yüklenirken saymaz ve çökmez (tanıma "kişi yok" döner)."""
    import threading

    import numpy as np

    from bantvision.core import Pipeline, Profile
    from bantvision.live.api import SharedDetector

    gate = threading.Event()
    det = SharedDetector(loader=lambda: gate.wait(30) and None)
    pipe = Pipeline(Profile.people())
    pipe.detect._detector = det
    pipe.counting = True
    still = np.full((288, 352, 3), 90, np.uint8)
    try:
        for k in range(40):                                    # alanda hareket eden koyu leke (kişi gibi)
            f = still.copy()
            f[60 + k * 5:180 + k * 5, 150:190] = 20
            r = pipe.process(f, k / 10)
        assert pipe.total == 0 and pipe.total_out == 0 and r.detect is not None and r.detect.tracks == []
    finally:
        gate.set()


def test_detect_and_safety_sessions_warm_the_shared_detector() -> None:
    """Kişi sayımı ve güvenlik oturumu açılınca (ya da o yönteme geçilince) tanıma modeli ilk kareyi beklemeden yüklenir;
    bant sayımı (blob/linescan) yüklemez."""
    import threading

    from bantvision.core import Profile
    from bantvision.live.api import SharedDetector
    from bantvision.live.session import LiveSession

    gate, started = threading.Event(), threading.Event()

    def loader() -> Any:
        started.set()
        assert gate.wait(30)
        return object()

    det = SharedDetector(loader=loader)
    egg = LiveSession("bant", lambda: "yok.mp4", Profile.egg(), detector=det)
    sessions = [egg]
    try:
        time.sleep(0.3)
        assert not started.is_set()
        egg.set_profile(Profile.people())                     # kişi sayımına geçiş ısıtır
        assert started.wait(5)
        det2, started2 = SharedDetector(loader=lambda: started2.set() or gate.wait(30)), threading.Event()
        sessions.append(LiveSession("kuyumcu", lambda: "yok.mp4", Profile.jeweler(), detector=det2))
        assert started2.wait(5)
    finally:
        gate.set()
        for s in sessions:
            s.stop()


# ---------------------------------------------------------------------- son düzeltme dalgası A: izleme sağlığı (I2)

def test_safety_health_gives_first_failing_condition_in_turkish() -> None:
    from bantvision.live.session import safety_health

    ok = {"state": "live", "model": "ready", "model_error": "", "detector": "ready", "detector_error": "",
          "processing_error": None, "last_ok_at": 100.0, "now": 105.0}
    assert safety_health(**ok) == (True, None)
    cases = [
        ({"state": "connecting"}, "Kameraya bağlanılıyor"),
        ({"state": "reconnecting"}, "Kamera bağlantısı yok"),
        ({"state": "error", "model": "error"}, "Kamera bağlantısı yok"),               # ilk tutmayan koşul
        ({"model": "loading"}, "Poz modeli yükleniyor"),
        ({"model": "error", "model_error": "Poz modeli yüklenemedi: ağ yok"}, "Poz modeli yüklenemedi: ağ yok"),
        ({"detector": "loading"}, "Kişi tanıma modeli yükleniyor"),
        ({"detector": "error", "detector_error": "Kişi tanıma modeli yüklenemedi: x"},
         "Kişi tanıma modeli yüklenemedi: x"),
        ({"processing_error": "bozuk kare"}, "Görüntü işlenemiyor: bozuk kare"),
        ({"last_ok_at": None}, "Görüntü işlenemiyor: henüz kare işlenmedi"),
        ({"last_ok_at": 94.0}, "Görüntü işlenemiyor: 10 sn'dir yeni kare yok"),     # 11 sn eski
    ]
    for over, reason in cases:
        assert safety_health(**{**ok, **over}) == (False, reason), over
    assert safety_health(**{**ok, "last_ok_at": 95.5})[0]                           # 9,5 sn: sağlıklı


def test_processing_error_is_reported_and_cleared_on_next_good_frame() -> None:
    from fakes_safety import FakeDetector, FakePose, hands_up_kp

    from bantvision.core import Profile
    from bantvision.live.session import LiveSession

    s = LiveSession("t", lambda: str(CLIP), Profile.jeweler(), detector=FakeDetector([]), pose=FakePose(hands_up_kp()))
    s.loop_file = True
    real, fail = s._pipe.process, [True]

    def process(frame: Any, ts: float) -> Any:
        if fail[0]:
            raise RuntimeError("bozuk kare")
        return real(frame, ts)

    s._pipe.process = process                                                        # type: ignore[method-assign]
    try:
        st = wait_for(lambda: (v := s.snapshot_status())["safety"]["processingError"] and v)
        assert st["message"] == "İşleme hatası: bozuk kare" and st["safety"]["lastOkAt"] is None
        assert st["safety"]["healthy"] is False and st["safety"]["reason"] == "Görüntü işlenemiyor: bozuk kare"
        fail[0] = False
        st = wait_for(lambda: (v := s.snapshot_status())["safety"]["processingError"] is None and v)
        assert st["message"] == "" and abs(st["safety"]["lastOkAt"] - time.time()) < 5
        st = wait_for(lambda: (v := s.snapshot_status())["safety"]["healthy"] and v)
        assert st["safety"]["reason"] is None and st["safety"]["unhealthyFor"] is None
    finally:
        s.stop()


def test_safety_status_reports_model_and_detector_errors() -> None:
    from fakes_safety import FakeDetector, FakePose, hands_up_kp

    from bantvision.core import Profile
    from bantvision.live.session import LiveSession

    pose = FakePose(hands_up_kp())
    pose.state, pose.error = "error", "Poz modeli yüklenemedi: internete ulaşılamadı (bağlantıyı kontrol edin)"  # type: ignore[attr-defined]
    det = FakeDetector([])
    det.state, det.error = "loading", ""                                            # type: ignore[attr-defined]
    s = LiveSession("t", lambda: str(CLIP), Profile.jeweler(), detector=det, pose=pose)
    s.loop_file = True
    try:
        st = wait_for(lambda: (v := s.snapshot_status())["state"] == "live" and v["safety"]["lastOkAt"] and v)
        sf = st["safety"]
        assert sf["model"] == "error" and sf["modelError"] == pose.error                # type: ignore[attr-defined]
        assert sf["detector"] == "loading" and sf["detectorError"] is None
        assert sf["healthy"] is False and sf["reason"] == pose.error                   # type: ignore[attr-defined]
        assert sf["unhealthyFor"] is not None and sf["unhealthyFor"] >= 0
        pose.state, pose.error = "ready", ""                                            # type: ignore[attr-defined]
        assert s.snapshot_status()["safety"]["reason"] == "Kişi tanıma modeli yükleniyor"
        det.state, det.error = "error", "Kişi tanıma modeli yüklenemedi: x"             # type: ignore[attr-defined]
        sf = s.snapshot_status()["safety"]
        assert sf["detectorError"] == "Kişi tanıma modeli yüklenemedi: x" and sf["reason"] == sf["detectorError"]
        det.state, det.error = "ready", ""                                              # type: ignore[attr-defined]
        assert s.snapshot_status()["safety"]["healthy"] is True
    finally:
        s.stop()


# ---------------------------------------------------------------------- son düzeltme dalgası A: yeniden başlatma (I1, I3)

def _app_with_fakes(tmp_path: pathlib.Path) -> Any:
    """Analiz sunucusu (aynı veri klasörü = yeniden başlatma); sahte modeller ömür başlamadan (geri yüklemeden) önce."""
    from fakes_safety import FakeDetector, FakePose, hands_up_kp

    app = create_app(Settings(data_dir=tmp_path))
    app.state.live.detector = FakeDetector([(280, 80, 360, 440)])
    app.state.live.pose = FakePose(hands_up_kp())
    return app


def _watch(tmp_path: pathlib.Path) -> list[dict[str, Any]]:
    p = tmp_path / "live" / "watch.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def test_safety_session_is_restored_after_analyzer_restart(tmp_path: pathlib.Path,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANALYZER_ALLOW_FILE_SOURCES", "1")
    with TestClient(_app_with_fakes(tmp_path)) as c:
        sess, sid = _safety_session_with_fake(c, monkeypatch)
        src_id, prof_id = sess.source_id, sess.profile_id
        prof = c.get(f"/api/v1/live/sessions/{sid}").json()["profile"]
        prof["safety"]["handsUp"]["seconds"] = 5                    # bu kamera için kaydedilen ayar da geri gelir
        assert c.put(f"/api/v1/live/sessions/{sid}/profile", params={"save": "true"}, json=prof).status_code == 200
        (w,) = _watch(tmp_path)
        assert (w["sourceId"], w["channelId"], w["profileId"], w["name"]) == (src_id, None, prof_id, "Tezgah")
        other = c.post("/api/v1/live/sources", json=camera(brand="custom", customUrl=str(CLIP), password="")).json()
        egg = next(p for p in c.get("/api/v1/live/profiles").json() if p["name"] == "Yumurta")
        assert c.post("/api/v1/live/sessions", json={"sourceId": other["id"], "profileId": egg["id"]}).status_code == 201
        assert len(_watch(tmp_path)) == 1                           # güvenlik dışı oturum saklanmaz
    assert len(_watch(tmp_path)) == 1                               # kapanış kaydı silmez: sonraki açılışta geri gelir

    app = _app_with_fakes(tmp_path)
    with TestClient(app) as c:
        (v,) = c.get("/api/v1/live/sessions").json()                # yalnızca güvenlik oturumu geri geldi
        assert (v["sourceId"], v["channelId"], v["profileId"], v["name"]) == (src_id, None, prof_id, "Tezgah")
        assert v["profile"]["countMode"] == "safety" and v["profile"]["safety"]["handsUp"]["seconds"] == 5
        s = app.state.live.sessions[v["id"]]
        assert s._pipe.safety.dc._detector is app.state.live.detector and s._pipe.safety._pose is app.state.live.pose
        a = wait_for(lambda: c.get("/api/v1/live/alarms?active=1").json(), timeout=30)[0]
        assert a["sessionId"] == v["id"] and a["type"] == "hands_up"           # yeniden izliyor: alarm verir


def test_deleted_or_switched_away_safety_sessions_are_not_restored(tmp_path: pathlib.Path,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    from bantvision.core import Profile

    monkeypatch.setenv("ANALYZER_ALLOW_FILE_SOURCES", "1")
    with TestClient(_app_with_fakes(tmp_path)) as c:
        _s1, sid1 = _safety_session_with_fake(c, monkeypatch)
        _s2, sid2 = _safety_session_with_fake(c, monkeypatch)
        assert len(_watch(tmp_path)) == 2
        assert c.delete(f"/api/v1/live/sessions/{sid1}").status_code == 204          # kapatıldı
        assert c.put(f"/api/v1/live/sessions/{sid2}/profile", json=Profile.people().to_dict()).status_code == 200
        assert _watch(tmp_path) == []                                                 # güvenlikten çıktı
        r = c.put(f"/api/v1/live/sessions/{sid2}/profile", json=Profile.jeweler().to_dict())
        assert r.status_code == 200 and len(_watch(tmp_path)) == 1                    # güvenliğe geri döndü
        c.put(f"/api/v1/live/sessions/{sid2}/profile", json=Profile.people().to_dict())
    with TestClient(_app_with_fakes(tmp_path)) as c:
        assert c.get("/api/v1/live/sessions").json() == []


def test_switched_into_safety_without_saving_is_restored_as_safety(tmp_path: pathlib.Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """Şablonu güvenlik olmayan oturum (kaydetmeden) güvenliğe geçirildiyse geri yüklemede kayıttaki profil kullanılır."""
    from bantvision.core import Profile

    monkeypatch.setenv("ANALYZER_ALLOW_FILE_SOURCES", "1")
    with TestClient(_app_with_fakes(tmp_path)) as c:
        src = c.post("/api/v1/live/sources", json=camera(brand="custom", customUrl=str(CLIP), password="",
                                                          name="Kasa")).json()
        egg = next(p for p in c.get("/api/v1/live/profiles").json() if p["name"] == "Yumurta")
        sid = c.post("/api/v1/live/sessions", json={"sourceId": src["id"], "profileId": egg["id"]}).json()["id"]
        assert _watch(tmp_path) == []
        assert c.put(f"/api/v1/live/sessions/{sid}/profile", json=Profile.jeweler().to_dict()).status_code == 200
        assert len(_watch(tmp_path)) == 1
    with TestClient(_app_with_fakes(tmp_path)) as c:
        (v,) = c.get("/api/v1/live/sessions").json()
        assert v["profile"]["countMode"] == "safety" and v["profileId"] == egg["id"] and v["name"] == "Kasa"


def test_watched_camera_whose_source_was_deleted_is_dropped_and_app_starts(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    import logging

    monkeypatch.setenv("ANALYZER_ALLOW_FILE_SOURCES", "1")
    with TestClient(_app_with_fakes(tmp_path)) as c:
        _safety_session_with_fake(c, monkeypatch)
    good = _watch(tmp_path)[0]
    gone = {**good, "sourceId": "silinmis-kaynak", "name": "Eski kamera"}
    broken = {**good, "channelId": "9", "profileId": "yok", "profile": None, "name": "Profilsiz"}   # profil yok
    (tmp_path / "live" / "watch.json").write_text(json.dumps([gone, broken, good]), encoding="utf-8")
    with caplog.at_level(logging.WARNING), TestClient(_app_with_fakes(tmp_path)) as c:
        (v,) = c.get("/api/v1/live/sessions").json()                  # diğer kayıtlar engel olmadı
        assert v["sourceId"] == good["sourceId"] and v["profile"]["countMode"] == "safety"
        assert c.get("/healthz").json()["ok"]
    assert [w["name"] for w in _watch(tmp_path)] == ["Profilsiz", "Tezgah"]          # silinen kaynak listeden çıktı
    text = caplog.text
    assert "Eski kamera" in text and "Profilsiz" in text


def test_restored_recorder_camera_connects_lazily_without_blocking_start(tmp_path: pathlib.Path) -> None:
    """Kayıt cihazı kamerası geri yüklenirken kanal listesi açılışta istenmez (cihaz geç açılabilir): oturum hemen
    oluşur, bağlantıyı okuyucu yeniden dener; durum panelde görünür."""
    from bantvision.core import Profile
    from bantvision.live import recorders as rec
    from bantvision.live.api import LiveManager
    from bantvision.live.store import LiveStore

    store = LiveStore(tmp_path)
    src = store.save_source({"kind": "recorder", "recorderBrand": "hikvision", "host": "127.0.0.1", "httpPort": 9,
                             "username": "admin", "name": "NVR"}, "x")
    prof = store.save_profile(Profile.jeweler())
    mgr = LiveManager(store, tmp_path)
    calls: list[str] = []

    def unreachable(_src: dict[str, Any], channel_id: str) -> Any:
        calls.append(channel_id)
        raise rec.RecorderError.unreachable("127.0.0.1:9 yanıt vermedi")

    mgr.channel = unreachable                                                          # type: ignore[method-assign]
    s = mgr.open_session(src["id"], "101", prof["id"], None, name="NVR · Kasa", lazy=True)
    try:
        assert s.name == "NVR · Kasa" and mgr.sessions[s.id] is s
        st = wait_for(lambda: (v := s.snapshot_status())["state"] == "reconnecting" and v, timeout=10)
        assert "Kaynağa ulaşılamadı" in st["message"] and calls
        assert st["safety"]["healthy"] is False and st["safety"]["reason"] == "Kamera bağlantısı yok"
    finally:
        s.stop()


def test_stale_open_alarms_are_closed_at_start(tmp_path: pathlib.Path) -> None:
    from bantvision.live.alarms import AlarmStore
    from bantvision.live.api import LiveManager
    from bantvision.live.store import LiveStore

    st = AlarmStore(tmp_path)
    open_ = st.add("eski", "Tezgah", "hands_up", 1.0, 2.0, None, "disabled")        # temiz kapanış olmadı (çökme)
    done = st.add("eski", "Tezgah", "lying", 1.0, 2.0, None, "disabled")
    st.end(done["id"], 5.0)
    test = st.add(None, "Deneme", "test", 3.0, 3.0, None, "disabled")
    before = time.time()
    mgr = LiveManager(LiveStore(tmp_path), tmp_path)
    got = {a["id"]: a for a in mgr.alarms.list()}
    assert got[open_["id"]]["endedAt"] >= before and got[done["id"]]["endedAt"] == 5.0
    assert got[test["id"]]["endedAt"] is None                                         # deneme alarmının sonu yok
    assert AlarmStore(tmp_path).get(open_["id"])["endedAt"] >= before                # diske de yazıldı


# ---------------------------------------------------------------------- son düzeltme dalgası A: olay resmi her zaman yerelde (I5)

@pytest.mark.parametrize("send_image", [False, True])
def test_test_alarm_stores_camera_frame_and_sends_photo_only_when_enabled(
        client: TestClient, monkeypatch: pytest.MonkeyPatch, send_image: bool) -> None:
    """Kameranın yan panelindeki "Deneme alarmı": o kameranın karesi her zaman saklanır; Telegram'a resim yalnızca o
    kamerada "Olay resmini Telegram'a gönder" açıksa gider."""
    import httpx
    from fakes_safety import FakePose

    paths: list[str] = []

    def telegram(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(200, json={"ok": True})

    mgr = client.app.state.live
    mgr.notifier._client = httpx.Client(transport=httpx.MockTransport(telegram))
    client.put("/api/v1/live/notify", json={"enabled": True, "chatId": "-1", "token": "1:T"})
    # poz yok: oturum kendisi alarm vermez, Telegram'a giden tek istek deneme alarmı
    sess, sid = _safety_session_with_fake(client, monkeypatch, send_image=send_image, pose=FakePose(None))
    wait_for(lambda: sess.raw_jpeg() is not None)
    rec = client.post("/api/v1/live/alarms/test", json={"sessionId": sid}).json()
    assert rec["type"] == "test" and rec["sessionId"] == sid and rec["image"] is True
    assert client.get(f"/api/v1/live/alarms/{rec['id']}/image.jpg").content[:2] == b"\xff\xd8"
    assert rec["id"] in [a["id"] for a in client.get("/api/v1/live/alarms", params={"sessionId": sid}).json()]
    mgr.notifier.flush()                                    # arka plan iş parçacığı da göndermiş olabilir
    assert paths == ["sendPhoto" if send_image else "sendMessage"]
    assert mgr.alarms.get(rec["id"])["notify"] == "sent"
