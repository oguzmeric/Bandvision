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
    saved = next(p for p in client.get("/api/v1/live/profiles").json() if p["id"] == egg["id"])
    assert saved["linePosition"] == 0.4

    csv = client.get(f"{base}/counts.csv")
    assert csv.status_code == 200 and "attachment" in csv.headers["content-disposition"]

    # Aynı kamera ikinci kez açılırsa eski oturum kapanır (kamera iki kez okunmaz)
    r2 = client.post("/api/v1/live/sessions", json={"sourceId": src["id"], "profileId": egg["id"]}).json()
    assert [s["id"] for s in client.get("/api/v1/live/sessions").json()] == [r2["id"]]
    assert client.get(base).status_code == 404

    assert client.delete(f"/api/v1/live/sources/{src['id']}").status_code == 204    # kaynağın oturumu da kapanır
    assert client.get("/api/v1/live/sessions").json() == []
