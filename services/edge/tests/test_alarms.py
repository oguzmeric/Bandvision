from __future__ import annotations

import os
import pathlib
from unittest.mock import patch

from bantvision.live.alarms import AlarmStore


def test_add_list_ack_end_and_image(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    a = st.add("s1", "Tezgah", "hands_up", 100.0, 103.0, b"\xff\xd8jpeg", "queued")
    b = st.add("s1", "Tezgah", "lying", 200.0, 210.0, None, "disabled")
    assert [x["id"] for x in st.list()] == [b["id"], a["id"]]
    assert a["image"] and not b["image"] and st.image_path(a["id"]).read_bytes() == b"\xff\xd8jpeg"
    assert st.image_path(b["id"]) is None
    st.end(a["id"], 105.0)
    st.set_notify(a["id"], "sent")
    assert st.ack(a["id"]) and not st.ack("yok")
    assert [x["id"] for x in st.list(active_only=True)] == [b["id"]]
    got = {x["id"]: x for x in AlarmStore(tmp_path).list()}
    assert got[a["id"]]["endedAt"] == 105.0 and got[a["id"]]["notify"] == "sent" and got[a["id"]]["acked"]
    assert [x["id"] for x in st.list(since=150.0)] == [b["id"]]


def test_expire_removes_old_records_and_images(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    old = st.add(None, "Deneme", "test", 0.0, 0.0, b"x", "disabled")
    new = st.add(None, "Deneme", "test", 9 * 86400.0, 9 * 86400.0, b"y", "disabled")
    assert st.expire(now=9 * 86400.0 + 1, days=7) == 1
    assert [x["id"] for x in st.list()] == [new["id"]] and st.image_path(old["id"]) is None


def test_path_traversal_protection(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    assert st.image_path("..\\x") is None
    assert st.image_path(str(tmp_path / "other")) is None
    assert st.image_path("a\x00b") is None
    assert st.image_path("g" * 32) is None
    assert st.image_path("a" * 32) is None


def test_add_resilience_on_image_write_error(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    original_write = pathlib.Path.write_bytes
    call_count = [0]

    def failing_write(self: pathlib.Path, data: bytes) -> None:
        call_count[0] += 1
        if call_count[0] == 1:
            raise PermissionError("Mocked permission error")
        original_write(self, data)

    with patch.object(pathlib.Path, "write_bytes", failing_write):
        a = st.add("s1", "Cam", "test", 0.0, 0.0, b"test", "disabled")
        assert a["image"] is False
        assert st.get(a["id"]) is not None
        assert [x["id"] for x in st.list()] == [a["id"]]
        st2 = AlarmStore(tmp_path)
        assert [x["id"] for x in st2.list()] == [a["id"]]


def test_add_resilience_on_save_error(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    call_count = [0]
    original_replace = os.replace

    def fail_once(src: str, dst: str) -> None:
        call_count[0] += 1
        if call_count[0] == 1:
            raise PermissionError("Mocked permission error")
        original_replace(src, dst)

    with patch("os.replace", side_effect=fail_once):
        a = st.add("s1", "Cam", "test", 0.0, 0.0, b"img", "disabled")
        assert st.get(a["id"]) is not None
        b = st.add("s1", "Cam", "test", 1.0, 1.0, b"img2", "disabled")
        st2 = AlarmStore(tmp_path)
        ids = [x["id"] for x in st2.list()]
        assert set(ids) == {a["id"], b["id"]}


def test_expire_resilience_on_unlink_error(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    old = st.add(None, "Cam", "test", 0.0, 0.0, b"old", "disabled")
    new = st.add(None, "Cam", "test", 9 * 86400.0, 9 * 86400.0, b"new", "disabled")
    call_count = [0]
    original_unlink = pathlib.Path.unlink

    def fail_once(self: pathlib.Path, *args, **kwargs) -> None:
        call_count[0] += 1
        if call_count[0] == 1 and self.name == f"{old['id']}.jpg":
            raise PermissionError("Mocked permission error")
        original_unlink(self, *args, **kwargs)

    with patch.object(pathlib.Path, "unlink", fail_once):
        count = st.expire(now=9 * 86400.0 + 1, days=7)
        assert count == 0
        assert st.get(old["id"]) is not None
        assert st.get(new["id"]) is not None


def test_orphan_images_cleanup(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    a = st.add(None, "Cam", "test", 0.0, 0.0, b"orphan", "disabled")
    b = st.add(None, "Cam", "test", 9 * 86400.0, 9 * 86400.0, b"new", "disabled")
    st._items = [x for x in st._items if x["id"] != a["id"]]
    st._save()
    orphan_path = st.images / f"{a['id']}.jpg"
    assert orphan_path.exists()
    cutoff_time = 100000.0
    os.utime(orphan_path, (cutoff_time, cutoff_time))
    count = st.expire(now=9 * 86400.0 + 1, days=7)
    assert count == 0
    assert not orphan_path.exists()
    assert st.get(b["id"]) is not None


def test_corrupt_json_recovery(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    st.add(None, "Cam", "test", 0.0, 0.0, None, "disabled")
    json_file = tmp_path / "live" / "alarms.json"
    json_file.write_text("{ invalid json }", encoding="utf-8")
    st2 = AlarmStore(tmp_path)
    assert len(st2.list()) == 0
    assert (json_file.with_suffix(".json.corrupt")).exists()


def test_invalid_json_structures(tmp_path: pathlib.Path) -> None:
    json_file = tmp_path / "live"
    json_file.mkdir(parents=True, exist_ok=True)
    json_file = json_file / "alarms.json"
    json_file.write_text("{}", encoding="utf-8")
    st = AlarmStore(tmp_path)
    assert len(st.list()) == 0
    json_file.write_text("null", encoding="utf-8")
    st = AlarmStore(tmp_path)
    assert len(st.list()) == 0
    json_file.write_text('[{"id": "abc"}]', encoding="utf-8")
    st = AlarmStore(tmp_path)
    assert len(st.list()) == 0


def test_image_bytes_method(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    a = st.add("s1", "Cam", "test", 0.0, 0.0, b"test_data", "disabled")
    assert st.image_bytes(a["id"]) == b"test_data"
    assert st.image_bytes("..\\x") is None
    assert st.image_bytes("invalid") is None
    valid_id = "b" * 32
    assert st.image_bytes(valid_id) is None


def test_get_returns_copy(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    a = st.add("s1", "Cam", "test", 0.0, 0.0, None, "disabled")
    got = st.get(a["id"])
    assert got is not None
    got["acked"] = True
    original = st.get(a["id"])
    assert original is not None
    assert not original["acked"]


def test_list_limit(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    for i in range(10):
        st.add(None, "Cam", "test", float(i), float(i), None, "disabled")
    assert len(st.list()) == 10
    assert len(st.list(limit=5)) == 5
    assert len(st.list(limit=1)) == 1


def test_expire_persists_to_disk(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    st.add(None, "Cam", "test", 0.0, 0.0, b"x", "disabled")
    new = st.add(None, "Cam", "test", 9 * 86400.0, 9 * 86400.0, b"y", "disabled")
    st.expire(now=9 * 86400.0 + 1, days=7)
    st2 = AlarmStore(tmp_path)
    ids = [x["id"] for x in st2.list()]
    assert ids == [new["id"]]
