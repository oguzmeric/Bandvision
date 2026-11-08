"""Yanlış alarm → zor örnek (R9): yangın/duman alarmı "Yanlış alarm" işaretlenince resmi ve olay kaydı
`<data>/live/hard-negatives/<id>/` altına kopyalanır; geri alınınca silinir; sonradan yazılan kayıt da kopyalanır; en çok
500 alarm; kopya hatası alarm işlemini bozmaz. Ağ yok, model yok."""
from __future__ import annotations

import json
import logging
import pathlib
from typing import Any

import pytest
from conftest import local_client
from fastapi.testclient import TestClient

from bantvision.analyzer import Settings, create_app
from bantvision.live import hard_negatives
from bantvision.live.alarms import AlarmStore
from bantvision.live.hard_negatives import MAX_HARD_NEGATIVES, HardNegatives

JPEG = b"\xff\xd8resim\xff\xd9"
CLIP = b"webm-kaydi"


def _alarm(st: AlarmStore, kind: str = "fire", fired: float = 2000.0, clip: bool = True,
           pending: bool = False) -> dict[str, Any]:
    a = st.add("s1", "Depo", kind, fired - 3.0, fired, JPEG, "disabled", clip_pending=pending, source_id="src1",
               channel_id="2")
    if clip:
        _write_clip(st, a["id"])
    return a


def _write_clip(st: AlarmStore, aid: str) -> None:
    (st.clips / f"{aid}.webm").write_bytes(CLIP)
    assert st.set_clip(aid, 1234.0)


def _folder(st: AlarmStore, aid: str) -> pathlib.Path:
    return st.root / "hard-negatives" / aid


def test_fire_false_alarm_copies_image_clip_and_meta(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    a = _alarm(st)
    assert st.mark_false_alarm(a["id"])
    d = _folder(st, a["id"])
    assert d == tmp_path / "live" / "hard-negatives" / a["id"]
    assert sorted(p.name for p in d.iterdir()) == ["clip.webm", "image.jpg", "meta.json"]
    assert (d / "image.jpg").read_bytes() == JPEG and (d / "clip.webm").read_bytes() == CLIP
    assert json.loads((d / "meta.json").read_text("utf-8")) == {
        "id": a["id"], "type": "fire", "camera": "Depo", "firedAt": 2000.0, "sourceId": "src1", "channelId": "2"}
    rec = st.get(a["id"])
    assert rec is not None and rec["falseAlarm"] is True and rec["acked"] is True


def test_smoke_alarm_is_copied_too_and_marking_twice_is_harmless(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    a = _alarm(st, "smoke")
    assert st.mark_false_alarm(a["id"]) and st.mark_false_alarm(a["id"])
    meta = json.loads((_folder(st, a["id"]) / "meta.json").read_text("utf-8"))
    assert meta["type"] == "smoke" and (_folder(st, a["id"]) / "clip.webm").is_file()


def test_undo_removes_the_folder_and_clears_the_flag(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    a = _alarm(st)
    assert st.mark_false_alarm(a["id"]) and _folder(st, a["id"]).is_dir()
    assert st.set_false_alarm(a["id"], False)
    assert not _folder(st, a["id"]).exists()
    rec = st.get(a["id"])
    assert rec is not None and rec["falseAlarm"] is False and rec["acked"] is True     # onay geri alınmaz
    assert not st.set_false_alarm("b" * 32, False) and not st.set_false_alarm("b" * 32, True)


def test_clip_written_later_is_copied_when_it_is_written(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    a = _alarm(st, clip=False, pending=True)
    assert st.mark_false_alarm(a["id"])
    d = _folder(st, a["id"])
    assert sorted(p.name for p in d.iterdir()) == ["image.jpg", "meta.json"]           # kayıt henüz yazılmadı
    _write_clip(st, a["id"])
    assert (d / "clip.webm").read_bytes() == CLIP


def test_clip_written_after_undo_does_not_recreate_the_folder(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    a = _alarm(st, clip=False, pending=True)
    assert st.mark_false_alarm(a["id"]) and st.set_false_alarm(a["id"], False)
    _write_clip(st, a["id"])
    assert not _folder(st, a["id"]).exists()
    b = _alarm(st, clip=False, pending=True)                                              # hiç işaretlenmemiş
    _write_clip(st, b["id"])
    assert not _folder(st, b["id"]).exists()


@pytest.mark.parametrize("kind", ["hands_up", "lying", "test"])
def test_other_alarm_types_are_not_copied(tmp_path: pathlib.Path, kind: str) -> None:
    st = AlarmStore(tmp_path)
    a = _alarm(st, kind)
    assert st.mark_false_alarm(a["id"])
    assert not _folder(st, a["id"]).exists()
    assert st.set_false_alarm(a["id"], False) and st.get(a["id"])["falseAlarm"] is False   # type: ignore[index]


def test_folder_keeps_at_most_cap_alarms_and_drops_the_oldest(tmp_path: pathlib.Path) -> None:
    assert MAX_HARD_NEGATIVES == 500
    st = AlarmStore(tmp_path)
    st.hard_negatives = HardNegatives(st.root / "hard-negatives", cap=3)
    old = [_alarm(st, fired=1000.0 + i) for i in range(4)]
    for a in (old[1], old[0], old[3], old[2]):                    # işaretleme sırası değil, alarm zamanı belirler
        assert st.mark_false_alarm(a["id"])
    root = st.root / "hard-negatives"
    assert sorted(p.name for p in root.iterdir()) == sorted(a["id"] for a in old[1:])
    stray = root / "notlar.txt"                                   # tanımadığı dosyalara dokunmaz, saymaz
    stray.write_text("x", "utf-8")
    new = _alarm(st, fired=5000.0)
    assert st.mark_false_alarm(new["id"])
    assert sorted(p.name for p in root.iterdir()) == sorted([*(a["id"] for a in old[2:]), new["id"], stray.name])


def test_just_marked_old_alarm_is_kept_even_when_it_is_the_oldest(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    st.hard_negatives = HardNegatives(st.root / "hard-negatives", cap=2)
    a, b = _alarm(st, fired=3000.0), _alarm(st, fired=3001.0)
    assert st.mark_false_alarm(a["id"]) and st.mark_false_alarm(b["id"])
    oldest = _alarm(st, fired=100.0)
    assert st.mark_false_alarm(oldest["id"])
    assert sorted(p.name for p in (st.root / "hard-negatives").iterdir()) == sorted([b["id"], oldest["id"]])


def test_copy_failure_never_breaks_the_false_alarm(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                                   caplog: pytest.LogCaptureFixture) -> None:
    st = AlarmStore(tmp_path)
    a = _alarm(st)

    def boom(*_a: Any, **_k: Any) -> None:
        raise OSError("disk dolu")

    monkeypatch.setattr(hard_negatives.shutil, "copyfile", boom)
    with caplog.at_level(logging.WARNING, logger="bantvision.live.hard_negatives"):
        assert st.mark_false_alarm(a["id"])
    rec = st.get(a["id"])
    assert rec is not None and rec["falseAlarm"] is True and rec["acked"] is True
    assert not _folder(st, a["id"]).exists()                      # yarım örnek kalmaz
    assert any("Zor örnek" in r.getMessage() and r.levelno == logging.WARNING for r in caplog.records)


def test_late_clip_copy_failure_keeps_the_sample_and_the_clip_record(tmp_path: pathlib.Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    st = AlarmStore(tmp_path)
    a = _alarm(st, clip=False, pending=True)
    assert st.mark_false_alarm(a["id"])

    def boom(*_a: Any, **_k: Any) -> None:
        raise OSError("kilitli")

    monkeypatch.setattr(hard_negatives.shutil, "copyfile", boom)
    _write_clip(st, a["id"])                                      # set_clip yine True: kayıt işaretlendi
    rec = st.get(a["id"])
    assert rec is not None and rec["clip"] is True
    d = _folder(st, a["id"])
    assert sorted(p.name for p in d.iterdir()) == ["image.jpg", "meta.json"]


def test_undo_failure_is_logged_and_the_flag_still_clears(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                                          caplog: pytest.LogCaptureFixture) -> None:
    st = AlarmStore(tmp_path)
    a = _alarm(st)
    assert st.mark_false_alarm(a["id"])

    def boom(*_a: Any, **_k: Any) -> None:
        raise OSError("kilitli")

    monkeypatch.setattr(hard_negatives.shutil, "rmtree", boom)
    with caplog.at_level(logging.WARNING, logger="bantvision.live.hard_negatives"):
        assert st.set_false_alarm(a["id"], False)
    assert st.get(a["id"])["falseAlarm"] is False                 # type: ignore[index]
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_missing_image_still_makes_a_sample_with_what_exists(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    a = st.add("s1", "Depo", "fire", 1.0, 2.0, None, "disabled")
    assert st.mark_false_alarm(a["id"])
    assert sorted(p.name for p in _folder(st, a["id"]).iterdir()) == ["meta.json"]


def test_expired_alarm_keeps_its_hard_negative(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    a = _alarm(st, fired=1000.0)
    assert st.mark_false_alarm(a["id"])
    assert st.expire(1000.0 + 8 * 86400) == 1
    assert (_folder(st, a["id"]) / "image.jpg").read_bytes() == JPEG       # eğitim için cihazda kalır


# ---------------------------------------------------------------------- uç (POST /alarms/{id}/false-alarm)

@pytest.fixture()
def client(tmp_path: pathlib.Path) -> TestClient:
    with local_client(create_app(Settings(data_dir=tmp_path))) as c:
        yield c


def test_endpoint_marks_copies_and_undoes(client: TestClient) -> None:
    st: AlarmStore = client.app.state.live.alarms
    a = _alarm(st)
    url = f"/api/v1/live/alarms/{a['id']}/false-alarm"
    r = client.post(url)                                          # gövdesiz: eski panel aynen çalışır
    assert r.status_code == 200 and r.json()["falseAlarm"] is True
    assert (_folder(st, a["id"]) / "meta.json").is_file()
    r = client.post(url, json={"falseAlarm": False})
    assert r.status_code == 200 and r.json()["falseAlarm"] is False and r.json()["acked"] is True
    assert not _folder(st, a["id"]).exists()
    r = client.post(url, json={"falseAlarm": True})
    assert r.status_code == 200 and _folder(st, a["id"]).is_dir()
    assert client.post(url, json={"falseAlarm": "evet"}).status_code == 422
    r = client.post(f"/api/v1/live/alarms/{'b' * 32}/false-alarm", json={"falseAlarm": False})
    assert r.status_code == 404 and r.json()["detail"] == "Alarm bulunamadı."
