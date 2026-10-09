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


# ---------------------------------------------------------------- düzeltme turu 1


def _locked_store(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, content: str
                  ) -> tuple[ViewStore, dict[str, bool], pathlib.Path]:
    """Açılışta kilitli (okunamayan) `views.json` ile bir depo; `locked["on"] = False` dosyayı okunur yapar."""
    from bantvision.live import views as views_mod

    (tmp_path / "live").mkdir()
    f = tmp_path / "live" / "views.json"
    f.write_text(content, encoding="utf-8")
    real = views_mod.read_json
    locked = {"on": True}

    def fake(path: pathlib.Path, delays: Any = None) -> Any:
        if locked["on"]:
            return views_mod.JsonRead(None, "unreadable")
        return real(path, ())

    monkeypatch.setattr(views_mod, "read_json", fake)
    return ViewStore(tmp_path), locked, f


@pytest.mark.parametrize("bad", ['[{"id": "a", "na', '{"bir": 1}', '"metin"'])
def test_locked_then_corrupt_file_is_quarantined_not_overwritten(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    store, locked, f = _locked_store(tmp_path, monkeypatch, "[]")
    f.write_text(bad, encoding="utf-8")                          # kilit kalktığında dosya bozuk (ya da liste değil)
    locked["on"] = False
    v = store.create("Yeni", "1", [None])
    corrupt = tmp_path / "live" / "views.json.corrupt"
    assert corrupt.read_text(encoding="utf-8") == bad              # bozuk içerik kaybolmadı
    assert [x["id"] for x in json.loads(f.read_text(encoding="utf-8"))] == [v["id"]]
    assert [x["name"] for x in store.list()] == ["Yeni"]


def test_reads_adopt_file_once_it_becomes_readable(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rec_ = {"id": "eski", "name": "Eski", "layout": "1", "tiles": [None], "createdAt": 1.0, "updatedAt": 1.0}
    store, locked, _ = _locked_store(tmp_path, monkeypatch, json.dumps([rec_]))
    assert store.list() == [] and store.get("eski") is None       # hâlâ kilitli: boş, ama hata yok
    locked["on"] = False
    assert store.get("eski") == rec_                              # yazma beklemeden okunur
    assert store.list() == [rec_]


def test_reads_quarantine_corrupt_file_that_was_locked(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, locked, f = _locked_store(tmp_path, monkeypatch, "[]")
    f.write_text("{bozuk", encoding="utf-8")
    locked["on"] = False
    assert store.list() == []
    assert (tmp_path / "live" / "views.json.corrupt").read_text(encoding="utf-8") == "{bozuk"


def test_invalid_records_are_dropped_with_warning(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    ok = {"id": "iyi", "name": "İyi", "layout": "1", "tiles": [None], "createdAt": 1.0, "updatedAt": 2}
    bad = [
        {k: v for k, v in ok.items() if k != "createdAt"} | {"id": "a"},       # createdAt yok
        {**ok, "id": "b", "updatedAt": "dün"},                                  # sayı değil
        {**ok, "id": "c", "createdAt": True},                                   # mantıksal değer sayı sayılmaz
        {**ok, "id": "d", "layout": 1},                                         # düzen kimliği metin olmalı
        {**ok, "id": 5},                                                        # kimlik metin olmalı
        {**ok, "id": "e", "name": None},
        "kayıt değil",
    ]
    (tmp_path / "live").mkdir()
    (tmp_path / "live" / "views.json").write_text(json.dumps([ok, *bad]), encoding="utf-8")
    with caplog.at_level("WARNING", logger="bantvision.live.views"):
        store = ViewStore(tmp_path)
    assert [v["id"] for v in store.list()] == ["iyi"]
    assert any("7 geçersiz kayıt" in m for m in caplog.messages)


def test_failed_save_rolls_back_memory(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bantvision.live import views as views_mod

    store = ViewStore(tmp_path)
    a = store.create("A", "1", [None])
    b = store.create("B", "2", [None, None])
    before = store.list()
    on_disk = (tmp_path / "live" / "views.json").read_text(encoding="utf-8")

    def boom(*_a: Any, **_k: Any) -> None:
        raise OSError("disk dolu")

    monkeypatch.setattr(views_mod, "write_json_atomic", boom)
    with pytest.raises(ViewsBusy):
        store.create("C", "1", [None])
    with pytest.raises(ViewsBusy):
        store.update(a["id"], "A2", "2", [None, None])
    with pytest.raises(ViewsBusy):
        store.delete(b["id"])
    assert store.list() == before                                  # bellek diskle aynı kaldı
    assert store.get(a["id"]) == a
    assert (tmp_path / "live" / "views.json").read_text(encoding="utf-8") == on_disk


def _recorder(c: TestClient, name: str = "NVR") -> str:
    r = c.post("/api/v1/live/sources", json={"kind": "recorder", "recorderBrand": "hikvision", "host": "nvr.example",
                                             "username": "u", "password": "p", "name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_api_maps_busy_store_to_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = client.app.state.live
    ok = client.post("/api/v1/live/views", json={"name": "A", "layout": "1", "tiles": [None]}).json()

    def busy(*_a: Any, **_k: Any) -> Any:
        raise ViewsBusy("Şablon dosyası şu an okunamıyor; biraz sonra yeniden deneyin.")

    for fn in ("create", "update", "delete"):
        monkeypatch.setattr(mgr.views, fn, busy)
    body = {"name": "B", "layout": "1", "tiles": [None]}
    r = client.post("/api/v1/live/views", json=body)
    assert r.status_code == 503 and "okunamıyor" in r.json()["detail"]
    assert client.put(f"/api/v1/live/views/{ok['id']}", json=body).status_code == 503
    assert client.delete(f"/api/v1/live/views/{ok['id']}").status_code == 503
    nvr = _recorder(client)
    monkeypatch.setattr(mgr, "channels", lambda src, refresh=False: [rec.RecorderChannel("1", "K", 1, True)])
    assert client.post("/api/v1/live/views/from-recorder", json={"sourceId": nvr}).status_code == 503


def test_update_missing_view_is_404(client: TestClient) -> None:
    r = client.put("/api/v1/live/views/yok", json={"name": "A", "layout": "1", "tiles": [None]})
    assert r.status_code == 404 and "Şablon" in r.json()["detail"]


def test_seventeen_tiles_is_422(client: TestClient) -> None:
    r = client.post("/api/v1/live/views", json={"name": "A", "layout": "16", "tiles": [None] * 17})
    assert r.status_code == 422


def test_from_recorder_with_no_channels_is_422(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    nvr = _recorder(client)
    monkeypatch.setattr(client.app.state.live, "channels", lambda src, refresh=False: [])
    r = client.post("/api/v1/live/views/from-recorder", json={"sourceId": nvr})
    assert r.status_code == 422 and "kamera bulunamadı" in r.json()["detail"]
    assert client.get("/api/v1/live/views").json() == []


def test_from_recorder_names_stay_unique_within_60_chars(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    long_name = "Çok uzun adlı merkez depo kayıt cihazı - kuzey kanat - zemin kat - 2. blok"      # 74 karakter
    nvr = _recorder(client, long_name)
    monkeypatch.setattr(client.app.state.live, "channels",
                        lambda src, refresh=False: [rec.RecorderChannel("1", "K", 1, True)])
    names = [client.post("/api/v1/live/views/from-recorder", json={"sourceId": nvr}).json()["name"] for _ in range(3)]
    assert len(set(names)) == 3 and all(len(n) <= 60 for n in names)
    assert [n.rsplit("tüm kanallar", 1)[1] for n in names] == ["", " 2", " 3"]      # ek ve sıra numarası kesilmedi
    assert [x["name"] for x in client.get("/api/v1/live/views").json()] == names
