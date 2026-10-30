"""Kaydedilmemiş şablon taslakları: bellekte, 10 dk boşta kalınca silinir, diske yazılmaz."""
from __future__ import annotations

import builtins
import io
import os
import pathlib
import threading
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bantvision.analyzer import Settings, create_app
from bantvision.live.drafts import FULL_MSG, MAX_DRAFTS, DraftsFull, DraftStore


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
    s = DraftStore(c, wall=c)
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


def test_drafts_never_touch_disk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Taslak işlemleri hiçbir dosya açmaz: dosya açan her yol (open, io.open, os.open, Path.open/write_*) patlar."""
    opened: list[str] = []

    def no_files(*a: Any, **k: Any) -> Any:
        opened.append(repr(a[:1]))
        raise AssertionError(f"taslak dosya açtı: {a[:1]!r}")

    for target, name in ((builtins, "open"), (io, "open"), (os, "open"), (pathlib.Path, "open"),
                         (pathlib.Path, "write_text"), (pathlib.Path, "write_bytes")):
        monkeypatch.setattr(target, name, no_files)
    s = DraftStore(Clock())
    d = s.create("1", [None])
    s.update(d["id"], "4", [None] * 4)
    s.get(d["id"])
    s.sweep()
    s.delete(d["id"])
    assert opened == []


def _files(root: pathlib.Path) -> dict[str, float]:
    return {str(p.relative_to(root)): p.stat().st_mtime for p in root.rglob("*") if p.is_file()}


def test_draft_endpoints_write_nothing_to_the_data_folder(tmp_path: pathlib.Path) -> None:
    """Uçtan uca: taslak açmak, güncellemek, durumunu sormak ve silmek veri klasöründe hiçbir dosya yazmaz/değiştirmez
    (şablonlar views.json'a yazılır; taslak oraya ya da başka bir yere yazılsa test kırılır)."""
    with TestClient(create_app(Settings(data_dir=tmp_path))) as c:
        before = _files(tmp_path)
        base = "/api/v1/live/views/drafts"
        d = c.post(base, json={"layout": "1", "tiles": [None]}).json()
        assert c.put(f"{base}/{d['id']}", json={"layout": "4", "tiles": [None] * 4}).status_code == 200
        assert c.get(f"/api/v1/live/views/{d['id']}/status").status_code == 200
        time.sleep(0.05)                                      # mtime çözünürlüğü: değişen dosya ayırt edilsin
        assert _files(tmp_path) == before
        assert c.delete(f"{base}/{d['id']}").status_code == 204
        assert _files(tmp_path) == before
        assert c.get("/api/v1/live/views").json() == []


def test_created_and_updated_at_are_epoch_seconds_like_templates() -> None:
    """Dışarıya verilen zaman, şablonlardaki gibi duvar saati (epoch sn); boşta silme ise monoton saatle ölçülür (duvar
    saati geri ya da ileri atlasa da taslak zamanında silinir)."""
    mono, wall = Clock(), Clock()
    wall.t = 1_760_000_000.0
    s = DraftStore(mono, wall=wall)
    d = s.create("1", [None])
    assert d["createdAt"] == d["updatedAt"] == 1_760_000_000.0
    mono.t += 5
    wall.t += 7
    u = s.update(d["id"], "1", [None])
    assert u is not None and u["updatedAt"] == 1_760_000_007.0 and u["createdAt"] == 1_760_000_000.0
    wall.t -= 10_000                                          # duvar saati geri atladı: silme etkilenmez
    mono.t += 599
    assert s.sweep() == 0
    mono.t += 1
    assert s.sweep() == 1


def test_api_draft_times_are_epoch_seconds(tmp_path: pathlib.Path) -> None:
    with TestClient(create_app(Settings(data_dir=tmp_path))) as c:
        t0 = time.time()
        d = c.post("/api/v1/live/views/drafts", json={"layout": "1", "tiles": [None]}).json()
        t1 = time.time()
        assert t0 - 1 <= d["createdAt"] <= t1 + 1 and t0 - 1 <= d["updatedAt"] <= t1 + 1


def test_at_most_32_drafts_the_33rd_is_refused_existing_ones_keep_working() -> None:
    s = DraftStore(Clock())
    assert MAX_DRAFTS == 32
    drafts = [s.create("1", [None]) for _ in range(32)]
    with pytest.raises(DraftsFull, match="^Çok fazla açık taslak var; biraz sonra yeniden deneyin.$"):
        s.create("1", [None])
    assert s.update(drafts[0]["id"], "4", [None] * 4) is not None
    assert s.get(drafts[-1]["id"]) is not None
    assert s.delete(drafts[1]["id"])
    s.create("1", [None])                                     # yer açıldı


def test_api_33rd_draft_is_503_turkish_and_existing_draft_still_works(tmp_path: pathlib.Path) -> None:
    base = "/api/v1/live/views/drafts"
    with TestClient(create_app(Settings(data_dir=tmp_path))) as c:
        ids = [c.post(base, json={"layout": "1", "tiles": [None]}).json()["id"] for _ in range(32)]
        r = c.post(base, json={"layout": "1", "tiles": [None]})
        assert r.status_code == 503 and r.json()["detail"] == FULL_MSG
        assert FULL_MSG == "Çok fazla açık taslak var; biraz sonra yeniden deneyin."
        assert c.put(f"{base}/{ids[0]}", json={"layout": "4", "tiles": [None] * 4}).status_code == 200
        assert c.get(f"/api/v1/live/views/{ids[0]}/status").json()["layout"] == "4"
        assert c.delete(f"{base}/{ids[1]}").status_code == 204
        assert c.post(base, json={"layout": "1", "tiles": [None]}).status_code == 201


def test_reaper_starts_on_first_create_and_stops_with_the_server(tmp_path: pathlib.Path) -> None:
    app = create_app(Settings(data_dir=tmp_path))
    mgr = app.state.live
    with TestClient(app) as c:
        assert mgr._drafts_reaper is None                     # taslak yokken iş parçacığı da yok
        c.post("/api/v1/live/views/drafts", json={"layout": "1", "tiles": [None]})
        reaper = mgr._drafts_reaper
        assert isinstance(reaper, threading.Thread) and reaper.is_alive()
        c.post("/api/v1/live/views/drafts", json={"layout": "1", "tiles": [None]})
        assert mgr._drafts_reaper is reaper                   # ikinci taslak yenisini açmaz
    reaper.join(timeout=5)
    assert not reaper.is_alive()                              # sunucu kapanınca hemen durur (30 sn beklemez)
