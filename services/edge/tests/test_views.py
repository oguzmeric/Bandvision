"""Şablon deposu ve uç noktaları (ağsız)."""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bantvision.analyzer import Settings, create_app
from bantvision.live import recorders as rec
from bantvision.live.views import ViewsBusy, ViewStore


@pytest.fixture()
def client(tmp_path: pathlib.Path) -> TestClient:
    with TestClient(create_app(Settings(data_dir=tmp_path))) as c:
        yield c


def _camera(c: TestClient, name: str = "Kapı") -> str:
    r = c.post("/api/v1/live/sources", json={"kind": "camera", "brand": "custom", "customUrl": "rtsp://kamera/akis",
                                             "name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_layouts_endpoint_lists_contract_catalog(client: TestClient) -> None:
    ids = [x["id"] for x in client.get("/api/v1/live/view-layouts").json()]
    assert ids == ["1", "2", "3", "4", "6", "8", "9", "12", "16"]


def test_create_update_delete_view(client: TestClient, tmp_path: pathlib.Path) -> None:
    sid = _camera(client)
    r = client.post("/api/v1/live/views", json={"name": " Giriş ", "layout": "2",
                                                 "tiles": [{"sourceId": sid, "channelId": None}, None]})
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["name"] == "Giriş" and v["layout"] == "2" and len(v["tiles"]) == 2
    assert json.loads((tmp_path / "live" / "views.json").read_text(encoding="utf-8"))[0]["id"] == v["id"]
    r = client.put(f"/api/v1/live/views/{v['id']}", json={"name": "Giriş katı", "layout": "4",
                                                          "tiles": [None, {"sourceId": sid, "channelId": None}, None, None]})
    assert r.status_code == 200 and r.json()["layout"] == "4" and r.json()["updatedAt"] >= v["updatedAt"]
    assert [x["name"] for x in client.get("/api/v1/live/views").json()] == ["Giriş katı"]
    assert client.delete(f"/api/v1/live/views/{v['id']}").status_code == 204
    assert client.get("/api/v1/live/views").json() == []
    assert client.delete(f"/api/v1/live/views/{v['id']}").status_code == 404


@pytest.mark.parametrize(("body", "msg"), [
    ({"name": "", "layout": "1", "tiles": [None]}, "ad"),
    ({"name": "x" * 61, "layout": "1", "tiles": [None]}, None),
    ({"name": "A", "layout": "5", "tiles": [None]}, "Düzen"),
    ({"name": "A", "layout": "2", "tiles": [None]}, "kutu"),
    ({"name": "A", "layout": "2", "tiles": [{"sourceId": "s1", "channelId": None}, {"sourceId": "s1", "channelId": None}]},
     "bir kez"),
    ({"name": "A", "layout": "1", "tiles": [{"sourceId": "../x", "channelId": None}]}, None),
])
def test_view_validation_is_422_turkish(client: TestClient, body: dict[str, Any], msg: str | None) -> None:
    r = client.post("/api/v1/live/views", json=body)
    assert r.status_code == 422
    if msg:
        assert msg in r.json()["detail"]


def test_from_recorder_picks_smallest_layout_and_caps_16(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    r = client.post("/api/v1/live/sources", json={"kind": "recorder", "recorderBrand": "hikvision",
                                                  "host": "nvr.example", "username": "u", "password": "p",
                                                  "name": "Ofis NVR"})
    sid = r.json()["id"]
    mgr = client.app.state.live
    for n, want, cut in ((7, "8", False), (20, "16", True)):
        chans = [rec.RecorderChannel(id=str(i), name=f"K{i}", number=i, has_substream=True) for i in range(1, n + 1)]
        monkeypatch.setattr(mgr, "channels", lambda src, refresh=False, c=chans: c)
        v = client.post("/api/v1/live/views/from-recorder", json={"sourceId": sid}).json()
        assert v["layout"] == want and v["truncated"] is cut
        assert [t["channelId"] for t in v["tiles"] if t][:3] == ["1", "2", "3"]
        assert sum(1 for t in v["tiles"] if t) == min(n, 16)
    names = [x["name"] for x in client.get("/api/v1/live/views").json()]
    assert names == ["Ofis NVR · tüm kanallar", "Ofis NVR · tüm kanallar 2"]


def test_from_recorder_rejects_plain_camera(client: TestClient) -> None:
    sid = _camera(client)
    assert client.post("/api/v1/live/views/from-recorder", json={"sourceId": sid}).status_code == 400


def test_corrupt_views_file_is_quarantined(tmp_path: pathlib.Path) -> None:
    (tmp_path / "live").mkdir()
    (tmp_path / "live" / "views.json").write_text("{bozuk", encoding="utf-8")
    store = ViewStore(tmp_path)
    assert store.list() == []
    assert (tmp_path / "live" / "views.json.corrupt").exists()


def test_locked_views_file_is_never_overwritten(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bantvision.live import views as views_mod

    (tmp_path / "live").mkdir()
    f = tmp_path / "live" / "views.json"
    f.write_text(json.dumps([{"id": "eski", "name": "Eski", "layout": "1", "tiles": [None],
                              "createdAt": 1.0, "updatedAt": 1.0}]), encoding="utf-8")
    real = views_mod.read_json
    locked = {"on": True}

    def fake(path: pathlib.Path, delays: Any = None) -> Any:
        if locked["on"]:
            return views_mod.JsonRead(None, "unreadable")
        return real(path, ())

    monkeypatch.setattr(views_mod, "read_json", fake)
    store = ViewStore(tmp_path)
    assert store.list() == []                                    # okunamadı: boş görünür ama dosyaya dokunulmaz
    with pytest.raises(ViewsBusy):
        store.create("Yeni", "1", [None])
    assert "eski" in f.read_text(encoding="utf-8")
    locked["on"] = False
    store.create("Yeni", "1", [None])                            # okunabilince diskteki liste korunur
    assert [v["name"] for v in store.list()] == ["Eski", "Yeni"]


def test_camera_name_uses_cached_channel_title_without_network(client: TestClient) -> None:
    mgr = client.app.state.live
    sid = _camera(client, "Kapı")
    assert mgr.camera_name(sid, None) == "Kapı"
    assert mgr.camera_name("yok", None) == "Silinmiş kamera"
    nvr = client.post("/api/v1/live/sources", json={"kind": "recorder", "recorderBrand": "hikvision",
                                                    "host": "nvr.example", "username": "u", "password": "p",
                                                    "name": "Ofis NVR"}).json()["id"]
    assert mgr.camera_name(nvr, "3") == "Ofis NVR · 3"                 # önbellekte yok: kanal kimliği (ağa çıkılmaz)
    mgr._channels[nvr] = [rec.RecorderChannel(id="3", name="Kasa", number=3, has_substream=True)]
    assert mgr.camera_name(nvr, "3") == "Ofis NVR · Kasa"
