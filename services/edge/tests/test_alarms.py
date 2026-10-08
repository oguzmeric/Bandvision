from __future__ import annotations

import json
import logging
import os
import pathlib
from unittest.mock import patch

import pytest

from bantvision.live.alarms import AlarmStore


def test_add_list_ack_end_and_image(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    a = st.add("s1", "Tezgah", "hands_up", 100.0, 103.0, b"\xff\xd8jpeg", "queued")
    b = st.add("s1", "Tezgah", "lying", 200.0, 210.0, None, "disabled")
    assert [x["id"] for x in st.list()] == [b["id"], a["id"]]
    assert a["image"] and not b["image"] and st.image_bytes(a["id"]) == b"\xff\xd8jpeg"
    assert st.image_bytes(b["id"]) is None
    st.end(a["id"], 105.0)
    st.set_notify(a["id"], "sent")
    assert st.ack(a["id"]) and not st.ack("yok")
    assert [x["id"] for x in st.list(active_only=True)] == [b["id"]]
    got = {x["id"]: x for x in AlarmStore(tmp_path).list()}
    assert got[a["id"]]["endedAt"] == 105.0 and got[a["id"]]["notify"] == "sent" and got[a["id"]]["acked"]
    assert [x["id"] for x in st.list(since=150.0)] == [b["id"]]


def test_list_filters_by_session_before_limit(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    mine = st.add("s1", "Tezgah", "hands_up", 1.0, 1.0, None, "disabled")
    for i in range(60):                                      # başka kameranın daha yeni alarmları 50 sınırını doldurur
        st.add("s2", "Depo", "lying", 10.0 + i, 10.0 + i, None, "disabled")
    assert mine["id"] not in [x["id"] for x in st.list()]
    assert [x["id"] for x in st.list(session_id="s1")] == [mine["id"]]
    assert len(st.list(session_id="s2")) == 50 and st.list(session_id="yok") == []
    assert [x["id"] for x in st.list(active_only=True, session_id="s1")] == [mine["id"]]
    st.ack(mine["id"])
    assert st.list(active_only=True, session_id="s1") == []


def test_expire_removes_old_records_and_images(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    old = st.add(None, "Deneme", "test", 0.0, 0.0, b"x", "disabled")
    new = st.add(None, "Deneme", "test", 9 * 86400.0, 9 * 86400.0, b"y", "disabled")
    assert st.expire(now=9 * 86400.0 + 1, days=7) == 1
    assert [x["id"] for x in st.list()] == [new["id"]] and st.image_bytes(old["id"]) is None
    assert not (st.images / f"{old['id']}.jpg").exists()


def test_path_traversal_protection(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    (tmp_path / "other.jpg").write_bytes(b"gizli")
    assert st.image_bytes("..\\x") is None
    assert st.image_bytes(str(tmp_path / "other")) is None
    assert st.image_bytes("../../other") is None
    assert st.image_bytes("a\x00b") is None
    assert st.image_bytes("g" * 32) is None
    assert st.image_bytes("a" * 32) is None


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


# ---------------------------------------------------------------- son düzeltme dalgası A: yükleme dayanıklılığı


def _write(tmp_path: pathlib.Path, items: object) -> pathlib.Path:
    live = tmp_path / "live"
    live.mkdir(parents=True, exist_ok=True)
    f = live / "alarms.json"
    f.write_text(json.dumps(items), encoding="utf-8")
    return f


def _rec(i: str, fired: float = 9 * 86400.0, **over: object) -> dict[str, object]:
    return {"id": i, "sessionId": None, "camera": "Cam", "type": "hands_up", "startedAt": fired, "firedAt": fired,
            "endedAt": fired, "acked": False, "notify": "disabled", "image": True, **over}


def test_load_keeps_only_records_with_valid_ids(tmp_path: pathlib.Path) -> None:
    """Elle bozulmuş dosya: kimliği 32 küçük onaltılık olmayan kayıt yüklenmez (temizlik onunla dosya yolu silemez)."""
    secret = tmp_path / "secrets.jpg"                                         # images/../../secrets.jpg
    secret.write_bytes(b"gizli")
    good = "c" * 32
    _write(tmp_path, [_rec("../../secrets", 0.0), _rec("C" * 32, 0.0), _rec(good, 0.0), _rec("d" * 31, 0.0)])
    st = AlarmStore(tmp_path)
    assert [a["id"] for a in st.list()] == [good]
    assert st.expire(now=9 * 86400.0, days=7) == 1 and secret.exists()


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_fired_at_is_removed_on_next_expire(tmp_path: pathlib.Path, raw: str) -> None:
    f = _write(tmp_path, [_rec("a" * 32, 0.0), _rec("b" * 32)])
    f.write_text(f.read_text(encoding="utf-8").replace('"firedAt": 0.0', f'"firedAt": {raw}', 1), encoding="utf-8")
    st = AlarmStore(tmp_path)
    assert len(st.list()) == 2
    assert st.expire(now=9 * 86400.0 + 1, days=7) == 1
    assert [a["id"] for a in st.list()] == ["b" * 32]


def _flaky_read(monkeypatch: pytest.MonkeyPatch, name: str, failures: int) -> list[int]:
    """`name` dosyasının okunması önce `failures` kez PermissionError verir (Windows: virüs tarayıcı kilidi)."""
    real = pathlib.Path.read_text
    calls = [0]

    def read_text(self: pathlib.Path, *a: object, **k: object) -> str:
        if self.name == name:
            calls[0] += 1
            if calls[0] <= failures:
                raise PermissionError(13, "Erişim engellendi", str(self))
        return real(self, *a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(pathlib.Path, "read_text", read_text)
    return calls


def test_locked_file_is_retried_then_loaded(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = _write(tmp_path, [_rec("a" * 32)])
    calls = _flaky_read(monkeypatch, "alarms.json", 2)
    st = AlarmStore(tmp_path)
    assert [a["id"] for a in st.list()] == ["a" * 32] and calls[0] == 3
    assert f.exists() and not f.with_suffix(".json.corrupt").exists()


def test_still_locked_file_starts_empty_without_rename_and_is_not_clobbered(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    from bantvision.live import jsonfile

    monkeypatch.setattr(jsonfile, "READ_RETRY_DELAYS_S", (0.0,) * 5)
    f = _write(tmp_path, [_rec("a" * 32, endedAt=None)])
    before = f.read_text(encoding="utf-8")
    calls = _flaky_read(monkeypatch, "alarms.json", 10**6)
    with caplog.at_level(logging.ERROR):
        st = AlarmStore(tmp_path)
    assert st.list() == [] and calls[0] == 6                                  # 1 + 5 yeniden deneme
    assert "okunamadı" in caplog.text and not f.with_suffix(".json.corrupt").exists()
    new = st.add("s", "Cam", "lying", 1.0, 1.0, None, "disabled")             # hâlâ kilitli: geçmiş ezilmez
    assert _REAL_READ(f, encoding="utf-8") == before and st.get(new["id"]) is not None
    monkeypatch.setattr(pathlib.Path, "read_text", _REAL_READ)               # kilit kalktı
    st.add("s", "Cam", "test", 2.0, 2.0, None, "disabled")
    got = {a["id"]: a for a in AlarmStore(tmp_path).list()}
    assert "a" * 32 in got and new["id"] in got and len(got) == 3            # eski geçmiş + yeniler birleşti
    assert got["a" * 32]["endedAt"] is not None                               # önceki çalışmadan açık kalan kapandı


def test_missing_file_is_not_a_warning(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        AlarmStore(tmp_path)
    assert caplog.text == ""


_REAL_READ = pathlib.Path.read_text


# ---------------------------------------------------------------- görev 13: olay kaydı, yanlış alarm, süzgeçler

def _clip(st: AlarmStore, aid: str, data: bytes = b"\x1aE\xdf\xa3webm", started: float = 1.0) -> pathlib.Path:
    p = st.clips / f"{aid}.webm"
    p.write_bytes(data)
    assert st.set_clip(aid, started)
    return p


def test_old_records_get_clip_and_false_alarm_defaults(tmp_path: pathlib.Path) -> None:
    _write(tmp_path, [_rec("a" * 32)])                       # önceki sürümün kaydı: clip/falseAlarm alanı yok
    got = AlarmStore(tmp_path).get("a" * 32)
    assert got is not None and (got["clip"], got["clipStartedAt"], got["falseAlarm"]) == (False, None, False)
    new = AlarmStore(tmp_path).add("s", "Tezgah", "lying", 1.0, 2.0, None, "disabled")
    assert (new["clip"], new["clipStartedAt"], new["falseAlarm"]) == (False, None, False)


def test_mark_false_alarm_acks_and_persists(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    a = st.add("s", "Tezgah", "hands_up", 1.0, 2.0, None, "disabled")
    assert st.mark_false_alarm(a["id"]) and not st.mark_false_alarm("b" * 32)
    got = AlarmStore(tmp_path).get(a["id"])
    assert got["falseAlarm"] is True and got["acked"] is True
    assert st.list(active_only=True) == []


def test_list_filters_by_type_and_until(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    h1 = st.add("s", "Tezgah", "hands_up", 10.0, 10.0, None, "disabled")
    ly = st.add("s", "Tezgah", "lying", 20.0, 20.0, None, "disabled")
    h2 = st.add("s", "Kasa", "hands_up", 30.0, 30.0, None, "disabled")
    assert [x["id"] for x in st.list(kind="hands_up")] == [h2["id"], h1["id"]]
    assert [x["id"] for x in st.list(until=20.0)] == [ly["id"], h1["id"]]          # sınır dahil
    assert [x["id"] for x in st.list(since=15.0, until=25.0)] == [ly["id"]]
    assert [x["id"] for x in st.list(kind="hands_up", until=29.0)] == [h1["id"]]
    assert len(st.list(limit=2)) == 2 and st.list(kind="test") == []


def test_expire_deletes_clips_with_their_records(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    old = st.add(None, "Tezgah", "hands_up", 0.0, 0.0, b"x", "disabled")
    new = st.add(None, "Tezgah", "hands_up", 9 * 86400.0, 9 * 86400.0, b"y", "disabled")
    old_clip, new_clip = _clip(st, old["id"]), _clip(st, new["id"])
    assert st.clip_file(old["id"]) == old_clip
    assert st.expire(now=9 * 86400.0 + 1, days=7) == 1
    assert not old_clip.exists() and st.clip_file(old["id"]) is None
    assert new_clip.exists() and st.get(new["id"])["clip"] is True


def test_record_whose_clip_cannot_be_deleted_stays_for_next_cleanup(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    old = st.add(None, "Tezgah", "hands_up", 0.0, 0.0, None, "disabled")
    _clip(st, old["id"])
    real = pathlib.Path.unlink

    def locked(self: pathlib.Path, *a: object, **k: object) -> None:
        if self.suffix == ".webm":
            raise PermissionError("kilitli (oynatılıyor)")
        real(self, *a, **k)                                                        # type: ignore[arg-type]

    with patch.object(pathlib.Path, "unlink", locked):
        assert st.expire(now=9 * 86400.0, days=7) == 0
    assert st.get(old["id"]) is not None
    assert st.expire(now=9 * 86400.0, days=7) == 1 and not (st.clips / f"{old['id']}.webm").exists()


def test_orphan_clips_and_stale_temp_files_are_cleaned(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    keep = st.add(None, "Tezgah", "hands_up", 9 * 86400.0, 9 * 86400.0, None, "disabled")
    _clip(st, keep["id"])
    orphan_old = st.clips / f"{'c' * 32}.webm"                # kaydı yok, eski: silinir
    orphan_new = st.clips / f"{'d' * 32}.webm"                # kaydı yok ama yeni (yazılıyor olabilir): kalır
    temp_old = st.clips / f"{'e' * 32}.tmp.webm"              # çökmeden kalan yarım dosya: silinir
    temp_new = st.clips / f"{'f' * 32}.tmp.webm"              # şu an yazılıyor: kalır
    for f in (orphan_old, orphan_new, temp_old, temp_new):
        f.write_bytes(b"x")
    now = 9 * 86400.0 + 1
    os.utime(orphan_old, (100000.0, 100000.0))
    os.utime(orphan_new, (now - 60, now - 60))
    os.utime(temp_old, (now - 7200, now - 7200))
    os.utime(temp_new, (now - 60, now - 60))
    st.expire(now=now, days=7)
    assert not orphan_old.exists() and not temp_old.exists()
    assert orphan_new.exists() and temp_new.exists() and st.clip_file(keep["id"]) is not None


def test_clip_cap_deletes_oldest_files_and_clears_their_records(tmp_path: pathlib.Path,
                                                                caplog: pytest.LogCaptureFixture) -> None:
    st = AlarmStore(tmp_path)
    recs = [st.add(None, "Tezgah", "hands_up", float(i), float(i), None, "disabled") for i in range(5)]
    for i, r in enumerate(recs):
        p = _clip(st, r["id"])
        os.utime(p, (1000.0 + i, 1000.0 + i))               # 0 en eski
    with caplog.at_level(logging.WARNING):
        assert st.enforce_clip_cap(max_clips=3) == 2
    assert "sınırı" in caplog.text
    for i, r in enumerate(recs):
        got = st.get(r["id"])
        assert got["clip"] is (i >= 2) and (st.clip_file(r["id"]) is not None) is (i >= 2)
        assert got["clipStartedAt"] is None if i < 2 else got["clipStartedAt"] == 1.0
    assert AlarmStore(tmp_path).get(recs[0]["id"])["clip"] is False             # diske yazıldı
    assert st.enforce_clip_cap(max_clips=3) == 0


def test_clip_file_rejects_bad_ids(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    decoy = st.clips.parent / "gizli.webm"                    # alarm-clips/../gizli.webm tam buraya çözülür
    decoy.write_bytes(b"x")
    assert (st.clips / "../gizli.webm").resolve() == decoy.resolve()
    for bad in ("../gizli", r"..\gizli", "g" * 32, "a" * 31, "a" * 32 + ".tmp"):
        assert st.clip_file(bad) is None


def test_clip_pending_and_failed_flags(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    a = st.add("s", "Tezgah", "hands_up", 1.0, 2.0, None, "disabled", clip_pending=True)
    b = st.add("s", "Tezgah", "lying", 1.0, 2.0, None, "disabled", clip_pending=True)
    c = st.add(None, "Deneme", "test", 1.0, 2.0, None, "disabled")             # kamerasız: yakalama yok
    assert (a["clipPending"], c["clipPending"], c["clipFailed"]) == (True, False, False)
    assert st.set_clip(a["id"], 5.0)
    st.clip_failed([b["id"], a["id"]])                                         # yazılmış kayda dokunulmaz
    got = {x["id"]: x for x in AlarmStore(tmp_path).list()}
    assert (got[a["id"]]["clip"], got[a["id"]]["clipPending"], got[a["id"]]["clipFailed"]) == (True, False, False)
    assert (got[b["id"]]["clipPending"], got[b["id"]]["clipFailed"]) == (False, True)
    _write(tmp_path, [_rec("d" * 32)])                                         # eski kayıt: alanlar varsayılan
    old = AlarmStore(tmp_path).get("d" * 32)
    assert (old["clipPending"], old["clipFailed"]) == (False, False)


def test_stale_clip_pending_is_marked_failed_at_start(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    a = st.add("s", "Tezgah", "hands_up", 1.0, 2.0, None, "disabled", clip_pending=True)   # yazılırken kapandı
    again = AlarmStore(tmp_path)
    assert again.clear_clip_pending() == 1 and again.clear_clip_pending() == 0
    got = AlarmStore(tmp_path).get(a["id"])
    assert (got["clipPending"], got["clipFailed"]) == (False, True)


def test_clip_cap_scans_the_folder_without_holding_the_store_lock(tmp_path: pathlib.Path) -> None:
    """500 dosyalık tarama ve silme alarm kaydını bekletmez: kilit yalnızca kayıtlar güncellenirken tutulur."""
    import threading

    st = AlarmStore(tmp_path)
    recs = [st.add(None, "Tezgah", "hands_up", float(i), float(i), None, "disabled") for i in range(3)]
    for r in recs:
        _clip(st, r["id"])
    free: list[bool] = []
    real_glob = pathlib.Path.glob

    def glob(self: pathlib.Path, pattern: str) -> object:
        if self == st.clips:
            t = threading.Thread(target=lambda: free.append(st._lock.acquire(timeout=1) and (st._lock.release() or True)))
            t.start()
            t.join()
        return real_glob(self, pattern)

    with patch.object(pathlib.Path, "glob", glob):
        assert st.enforce_clip_cap(max_clips=1) == 2
    assert free == [True]


def test_locked_file_merge_marks_stale_clip_pending_failed(tmp_path: pathlib.Path,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    """alarms.json açılışta kilitliyse açılış temizliği boş listeyle çalışır: dosya okunup birleştirilince önceki
    çalışmadan "kayıt yazılıyor" kalmış kayıt alınamadı sayılır (panel sonsuza dek "hazırlanıyor" demez)."""
    from bantvision.live import jsonfile

    monkeypatch.setattr(jsonfile, "READ_RETRY_DELAYS_S", (0.0,) * 5)
    _write(tmp_path, [_rec("a" * 32, clipPending=True)])
    _flaky_read(monkeypatch, "alarms.json", 10**6)
    st = AlarmStore(tmp_path)
    assert st.clear_clip_pending() == 0                                       # boş liste (kilitli)
    monkeypatch.setattr(pathlib.Path, "read_text", _REAL_READ)               # kilit kalktı
    st.add("s", "Cam", "test", 2.0, 2.0, None, "disabled")                    # yazımda birleşir
    got = AlarmStore(tmp_path).get("a" * 32)
    assert (got["clipPending"], got["clipFailed"]) == (False, True)


def test_clip_failed_leaves_records_that_never_waited_for_a_clip(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    plain = st.add(None, "Deneme", "test", 1.0, 1.0, None, "disabled")       # kamerasız: kayıt beklenmedi
    st.clip_failed([plain["id"]])
    got = st.get(plain["id"])
    assert (got["clipPending"], got["clipFailed"]) == (False, False)          # "Bu alarmın kaydı yok", hata değil
