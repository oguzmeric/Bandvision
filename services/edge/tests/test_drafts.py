"""Kaydedilmemiş şablon taslakları: bellekte, 10 dk boşta kalınca silinir, diske yazılmaz."""
from __future__ import annotations

import pathlib

import pytest

from bantvision.live.drafts import DraftStore


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def tile(i: int) -> dict[str, str | None]:
    return {"sourceId": f"s{i}", "channelId": None}


def test_create_get_round_trip() -> None:
    s = DraftStore(Clock())
    d = s.create("4", [tile(1), None, tile(2), None])
    assert d["id"].startswith("draft-") and len(d["id"]) == len("draft-") + 12
    assert d["name"] == "Taslak" and d["layout"] == "4" and d["createdAt"] == d["updatedAt"]
    assert s.get(d["id"]) == d and s.get("draft-yok") is None


def test_update_changes_layout_and_tiles_and_bumps_updated_at() -> None:
    c = Clock()
    s = DraftStore(c)
    d = s.create("4", [None] * 4)
    c.t += 5
    u = s.update(d["id"], "1", [tile(1)])
    assert u is not None and u["layout"] == "1" and u["tiles"] == [tile(1)]
    assert u["updatedAt"] == d["updatedAt"] + 5 and u["createdAt"] == d["createdAt"]
    assert s.update("draft-yok", "1", [None]) is None


def test_invalid_layout_or_tile_count_raise_turkish_value_error() -> None:
    s = DraftStore(Clock())
    with pytest.raises(ValueError, match="^Düzen bulunamadı.$"):
        s.create("zz", [])
    with pytest.raises(ValueError, match="^Bu düzende 4 kutu var; 3 kutu gönderildi.$"):
        s.create("4", [None] * 3)
    with pytest.raises(ValueError, match="^Aynı kamera bir şablonda yalnızca bir kez yer alabilir.$"):
        s.create("2", [tile(1), tile(1)])
    d = s.create("4", [None] * 4)
    with pytest.raises(ValueError, match="Düzen bulunamadı"):
        s.update(d["id"], "zz", [])
    with pytest.raises(ValueError, match="kutu var"):
        s.update(d["id"], "4", [None])


def test_idle_draft_is_swept_but_a_get_keeps_it_alive() -> None:
    c = Clock()
    s = DraftStore(c)
    keep, drop = s.create("1", [None]), s.create("1", [None])
    c.t += 599
    assert s.get(keep["id"]) is not None and s.sweep() == 0
    c.t += 2                                                    # drop: 601 sn boşta, keep: 2 sn
    assert s.sweep() == 1
    assert s.get(drop["id"]) is None and s.get(keep["id"]) is not None


def test_delete() -> None:
    s = DraftStore(Clock())
    d = s.create("1", [None])
    assert s.delete(d["id"]) is True and s.delete(d["id"]) is False and s.get(d["id"]) is None


def test_drafts_never_touch_disk(tmp_path: pathlib.Path) -> None:
    s = DraftStore(Clock())
    d = s.create("1", [None])
    s.update(d["id"], "4", [None] * 4)
    assert list(tmp_path.iterdir()) == []
