"""Kayıttan izleme API'si (`/api/v1/live/archive/…`): gerçek yığın (dosya kaynağı, TestClient) ve sahte arşivle
dışa aktarma, hata eşlemesi, alarm kaydındaki kaynak/kanal alanları ve kapanışta oynatıcıların durması."""
from __future__ import annotations

import asyncio
import contextlib
import pathlib
import threading
import time
import urllib.parse
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any

import cv2
import numpy as np
import pytest
from conftest import local_client
from fastapi.testclient import TestClient
from test_archive_player import CH, Rig

from bantvision.analyzer import Settings, create_app
from bantvision.live.archive_api import export_response
from bantvision.live.recorders import RecorderError

A = "/api/v1/live/archive"
SECRET = "Gizli-Sifre-42"
VIEW_KEYS = {"id", "sourceId", "channelId", "name", "state", "message", "at", "speed", "speeds", "fps", "canExport"}


def wait_for(fn: Callable[[], Any], timeout: float = 10.0) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        v = fn()
        if v:
            return v
        time.sleep(0.05)
    raise AssertionError("koşul zamanında sağlanmadı")


def write_video(path: pathlib.Path, seconds: float = 6.0, fps: int = 10) -> None:
    out = cv2.VideoWriter(str(path), cv2.VideoWriter.fourcc(*"mp4v"), fps, (160, 120))
    assert out.isOpened()
    for i in range(int(seconds * fps)):
        frame = np.full((120, 160, 3), (i * 4) % 250, np.uint8)
        cv2.putText(frame, str(i), (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        out.write(frame)
    out.release()


@pytest.fixture()
def client(tmp_path: pathlib.Path) -> Iterator[TestClient]:
    with local_client(create_app(Settings(data_dir=tmp_path))) as c:
        yield c


@pytest.fixture()
def filecam(client: TestClient, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("ANALYZER_ALLOW_FILE_SOURCES", "1")
    video = tmp_path / "kayit.mp4"
    write_video(video)
    r = client.post("/api/v1/live/sources", json={"kind": "camera", "brand": "custom", "name": "Dosya kamera",
                                                   "customUrl": str(video), "password": SECRET})
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def _clean(texts: list[str]) -> None:
    for t in texts:
        assert "password" not in t.lower() and "rtsp://" not in t and SECRET not in t, t


def test_file_source_player_real_stack(client: TestClient, filecam: str) -> None:
    texts: list[str] = []

    def keep(r: Any) -> Any:
        texts.append(r.text)
        return r

    r = keep(client.post(f"{A}/players", json={"sourceId": filecam, "at": 1.0}))
    assert r.status_code == 201, r.text
    v = r.json()
    assert set(v) == VIEW_KEYS
    assert v["sourceId"] == filecam and v["channelId"] is None and v["name"] == "Dosya kamera"
    assert v["speeds"] == [1, 2, 4] and v["speed"] == 1 and v["canExport"] is False
    pid = v["id"]

    s = client.get(f"{A}/players/{pid}/stream", params={"limit": 3})
    assert s.status_code == 200 and s.headers["content-type"].startswith("multipart/x-mixed-replace")
    assert s.content.count(b"--frame\r\nContent-Type: image/jpeg") == 3 and s.content.count(b"\xff\xd8") >= 3

    v = wait_for(lambda: (x := keep(client.get(f"{A}/players/{pid}")).json())["at"] > 1.05 and x)
    assert v["state"] == "playing" and v["fps"] == pytest.approx(10.0, abs=0.5)

    v = keep(client.post(f"{A}/players/{pid}/actions", json={"action": "seek", "at": 2.0})).json()
    assert v["at"] == pytest.approx(2.0, abs=0.3)
    v = wait_for(lambda: (x := client.get(f"{A}/players/{pid}").json())["state"] == "playing" and x)
    assert 2.0 <= v["at"] <= 2.6

    v = keep(client.post(f"{A}/players/{pid}/actions", json={"action": "pause"})).json()
    assert v["state"] == "paused"
    at = v["at"]
    time.sleep(0.5)
    v = client.get(f"{A}/players/{pid}").json()
    assert v["state"] == "paused" and v["at"] == at

    v = client.post(f"{A}/players/{pid}/actions", json={"action": "speed", "speed": 2}).json()
    assert v["speed"] == 2 and v["state"] == "paused"
    r = client.post(f"{A}/players/{pid}/actions", json={"action": "speed", "speed": 3})
    assert r.status_code == 422 and r.json()["detail"] == "Hız desteklenmiyor."
    r = client.post(f"{A}/players/{pid}/actions", json={"action": "speed"})
    assert r.status_code == 422
    r = client.post(f"{A}/players/{pid}/actions", json={"action": "seek"})
    assert r.status_code == 422
    v = client.post(f"{A}/players/{pid}/actions", json={"action": "resume"}).json()
    assert v["state"] in ("connecting", "playing")

    second = client.post(f"{A}/players", json={"sourceId": filecam, "at": 0.0})
    assert second.status_code == 201
    third = keep(client.post(f"{A}/players", json={"sourceId": filecam, "at": 0.0}))
    assert third.status_code == 429 and third.json()["detail"] == "En çok 2 kayıt aynı anda izlenebilir."

    assert client.delete(f"{A}/players/{pid}").status_code == 204
    r = client.get(f"{A}/players/{pid}")
    assert r.status_code == 404 and r.json()["detail"] == "Kayıt oynatıcısı bulunamadı."
    assert client.delete(f"{A}/players/{pid}").status_code == 404
    again = client.post(f"{A}/players", json={"sourceId": filecam, "at": 0.0})       # kapanan yerini bıraktı
    assert again.status_code == 201

    r = keep(client.post(f"{A}/export", json={"sourceId": filecam, "start": 0.0, "end": 2.0}))
    assert r.status_code == 501, r.text

    r = keep(client.get(f"{A}/calendar", params={"source": filecam, "year": 1970, "month": 1}))
    assert r.status_code == 200 and r.json() == {"days": [1]}
    assert client.get(f"{A}/calendar", params={"source": filecam, "year": 1970, "month": 2}).json() == {"days": []}
    r = keep(client.get(f"{A}/timeline", params={"source": filecam, "day": 0}))
    ranges = r.json()["ranges"]
    assert len(ranges) == 1 and ranges[0][0] == 0.0 and ranges[0][1] == pytest.approx(6.0, abs=0.2)
    assert client.get(f"{A}/timeline", params={"source": filecam, "day": 86400}).json() == {"ranges": []}
    _clean(texts)


def test_unknown_ids_and_validation(client: TestClient, filecam: str) -> None:
    for r in (client.post(f"{A}/players", json={"sourceId": "yok", "at": 0.0}),
              client.get(f"{A}/calendar", params={"source": "yok", "year": 2026, "month": 1}),
              client.get(f"{A}/timeline", params={"source": "yok", "day": 0}),
              client.post(f"{A}/export", json={"sourceId": "yok", "start": 0.0, "end": 10.0})):
        assert r.status_code == 404 and r.json()["detail"] == "Kaynak bulunamadı.", r.text
    for r in (client.get(f"{A}/players/yok"), client.get(f"{A}/players/yok/stream"),
              client.post(f"{A}/players/yok/actions", json={"action": "pause"}), client.delete(f"{A}/players/yok")):
        assert r.status_code == 404 and r.json()["detail"] == "Kayıt oynatıcısı bulunamadı.", r.text
    r = client.post(f"{A}/players", json={"sourceId": filecam, "at": 0.0, "speed": 3})
    assert r.status_code == 422 and r.json()["detail"] == "Hız desteklenmiyor."
    for body in ({"sourceId": filecam, "start": 10.0, "end": 10.0}, {"sourceId": filecam, "start": 10.0, "end": 5.0},
                 {"sourceId": filecam, "start": 0.0, "end": 1800.5}):
        r = client.post(f"{A}/export", json=body)
        assert r.status_code == 422 and isinstance(r.json()["detail"], str), r.text
    assert client.post(f"{A}/players", json={"sourceId": filecam, "at": 0.0, "extra": 1}).status_code == 422
    assert client.post(f"{A}/players/x/actions", json={"action": "rewind"}).status_code == 422
    assert client.get(f"{A}/calendar", params={"source": filecam, "year": 2026, "month": 13}).status_code == 422
    cam = client.post("/api/v1/live/sources", json={"kind": "camera", "brand": "hikvision", "host": "192.168.1.64",
                                                     "password": SECRET}).json()
    r = client.post(f"{A}/players", json={"sourceId": cam["id"], "at": 0.0})
    assert r.status_code == 422 and SECRET not in r.text


@pytest.fixture()
def rig(client: TestClient) -> Iterator[Rig]:
    r = Rig()
    live = client.app.state.live
    old, live.archive = live.archive, r.manager
    yield r
    live.archive = old
    r.manager.stop()


def test_export_streams_with_utf8_filename_and_releases_lock(client: TestClient, rig: Rig) -> None:
    start = time.mktime((2026, 11, 7, 14, 30, 0, 0, 0, -1))           # yerel saat
    body = {"sourceId": "nvr", "channelId": CH.id, "start": start, "end": start + 60}
    r = client.post(f"{A}/export", json=body)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "video/mp4"
    assert r.content == b"".join(rig.archive.export_chunks)
    cd = r.headers["content-disposition"]
    assert cd.startswith("attachment; ") and 'filename="NVR-Kapi-20261107-1430.mp4"' in cd
    assert "filename*=UTF-8''" + urllib.parse.quote("NVR · Kapı-20261107-1430.mp4", safe="") in cd
    assert client.post(f"{A}/export", json=body).status_code == 200          # kilit kalktı

    _, held = rig.manager.export("nvr", CH.id, start, start + 60)          # süren görev
    try:
        r = client.post(f"{A}/export", json=body)
        assert r.status_code == 409 and r.json()["detail"] == "Bir dışa aktarma sürüyor."
    finally:
        held.close()
    assert client.post(f"{A}/export", json=body).status_code == 200


def test_export_response_closes_stream_when_client_disconnects(rig: Rig) -> None:
    _, stream = rig.manager.export("nvr", CH.id, 0.0, 60.0)
    resp = export_response(stream, "a.mp4", "a.mp4")
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        await asyncio.Event().wait()
        return {}

    async def send(msg: dict[str, Any]) -> None:
        sent.append(msg)
        if msg["type"] == "http.response.body":
            raise OSError("istemci koptu")

    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}, "method": "POST", "headers": []}
    with contextlib.suppress(BaseException):
        asyncio.run(resp(scope, receive, send))
    assert any(m["type"] == "http.response.body" for m in sent)
    _, again = rig.manager.export("nvr", CH.id, 0.0, 60.0)               # ExportBusy değil: akış kapandı
    again.close()

    _, unstarted = rig.manager.export("nvr", CH.id, 0.0, 60.0)
    resp = export_response(unstarted, "a.mp4", "a.mp4")

    async def failing_send(msg: dict[str, Any]) -> None:
        raise OSError("başlık gönderilemedi")

    with contextlib.suppress(BaseException):
        asyncio.run(resp(scope, receive, failing_send))
    _, third = rig.manager.export("nvr", CH.id, 0.0, 60.0)
    third.close()


def test_recorder_errors_map_through_err(client: TestClient, rig: Rig) -> None:
    rig.archive.fail_next = [RecorderError.unauthorized()]
    r = client.get(f"{A}/calendar", params={"source": "nvr", "channel": CH.id, "year": 2026, "month": 11})
    assert r.status_code == 502 and r.json()["detail"] == "Kullanıcı adı ya da şifre hatalı."
    r = client.get(f"{A}/calendar", params={"source": "nvr", "channel": CH.id, "year": 2026, "month": 11})
    assert r.status_code == 200 and r.json() == {"days": [1, 11]}
    r = client.get(f"{A}/timeline", params={"source": "nvr", "channel": CH.id, "day": 1000.0})
    assert r.json() == {"ranges": [[1000.0, 1060.0]]}
    r = client.get(f"{A}/calendar", params={"source": "nvr", "channel": "yok", "year": 2026, "month": 11})
    assert r.status_code == 404 and r.json()["detail"] == "Kamera kayıt cihazında bulunamadı."
    r = client.post(f"{A}/players", json={"sourceId": "nvr", "at": 0.0})
    assert r.status_code == 422 and r.json()["detail"] == "Kayıt cihazından bir kamera seçin."
    v = client.post(f"{A}/players", json={"sourceId": "nvr", "channelId": CH.id, "at": 1000.0, "speed": 16,
                                         "substream": False}).json()
    assert v["speed"] == 16 and v["canExport"] is True and v["speeds"] == [1, 2, 4, 8, 16]
    assert v["name"] == "NVR · Kapı" and "rtsp://" not in str(v)


def test_shutdown_stops_players(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANALYZER_ALLOW_FILE_SOURCES", "1")
    video = tmp_path / "kayit.mp4"
    write_video(video, seconds=30.0)
    before = set(threading.enumerate())
    with local_client(create_app(Settings(data_dir=tmp_path / "data"))) as c:
        src = c.post("/api/v1/live/sources", json={"kind": "camera", "brand": "custom", "customUrl": str(video),
                                                    "password": ""}).json()
        v = c.post(f"{A}/players", json={"sourceId": src["id"], "at": 0.0}).json()
        wait_for(lambda: c.get(f"{A}/players/{v['id']}").json()["state"] == "playing")
        assert [t for t in threading.enumerate() if t.name.startswith("arsiv-")]
    left = [t for t in threading.enumerate() if t not in before and t.name.startswith("arsiv-") and t.is_alive()]
    assert left == []


def test_alarm_records_carry_source_and_channel(client: TestClient) -> None:
    from bantvision.core import Profile
    from bantvision.core.safety import SafetyAlarm

    mgr = client.app.state.live
    s = SimpleNamespace(id="x", name="Tezgah", profile=Profile.jeweler(), source_id="src", channel_id="ch-1")
    mgr.on_safety(s, [SafetyAlarm("hands_up", 1, (0, 0, 1, 1), 0.0, 3.0)], [], None)
    a = client.get("/api/v1/live/alarms").json()[0]
    assert a["sourceId"] == "src" and a["channelId"] == "ch-1"

    t = client.post("/api/v1/live/alarms/test", json={}).json()
    assert t["sourceId"] is None and t["channelId"] is None
    fake = SimpleNamespace(id="y", name="Kasa", profile=Profile.people(), source_id="src2", channel_id=None)
    mgr.sessions["y"] = fake
    try:
        t = client.post("/api/v1/live/alarms/test", json={"sessionId": "y"}).json()
    finally:
        del mgr.sessions["y"]
    assert t["sourceId"] == "src2" and t["channelId"] is None
