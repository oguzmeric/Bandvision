from __future__ import annotations

import pathlib

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
    got = {x["id"]: x for x in AlarmStore(tmp_path).list()}                  # diske yazıldı
    assert got[a["id"]]["endedAt"] == 105.0 and got[a["id"]]["notify"] == "sent" and got[a["id"]]["acked"]
    assert [x["id"] for x in st.list(since=150.0)] == [b["id"]]


def test_expire_removes_old_records_and_images(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    old = st.add(None, "Deneme", "test", 0.0, 0.0, b"x", "disabled")
    new = st.add(None, "Deneme", "test", 9 * 86400.0, 9 * 86400.0, b"y", "disabled")
    assert st.expire(now=9 * 86400.0 + 1, days=7) == 1
    assert [x["id"] for x in st.list()] == [new["id"]] and st.image_path(old["id"]) is None
