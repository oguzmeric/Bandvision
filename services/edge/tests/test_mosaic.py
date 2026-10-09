"""Birleştirici: kareler doğru hücreye oran korunarak; abonesiz durur; iki boyut aynı anda; şablon değişince hemen."""
from __future__ import annotations

import time
from typing import Any

import numpy as np
import pytest

from bantvision.live.layouts import cell_rects, layout_by_id
from bantvision.live.mosaic import SUB_TTL_S, MosaicHub, compose, fit_canvas
from bantvision.live.viewer import TileFrame


def test_fit_canvas_caps_to_1920x1080_and_multiples_of_16() -> None:
    assert fit_canvas(3840, 2160) == (1920, 1072)          # 1080 → 16'nın katı 1072
    assert fit_canvas(375, 600) == (368, 592)
    assert fit_canvas(10, 10) == (16, 16)


def test_compose_puts_each_frame_in_its_cell_letterboxed() -> None:
    lay = layout_by_id("4")
    assert lay is not None
    red = np.zeros((90, 160, 3), np.uint8)
    red[:, :, 2] = 255                                       # 16:9 kırmızı
    tall = np.zeros((160, 90, 3), np.uint8)
    tall[:, :, 1] = 255                                      # dikey yeşil: yanlarda siyah pay
    img = compose(lay, 640, 360, [red, None, tall, None])
    (x0, y0, x1, y1), (bx0, by0, bx1, by1), (cx0, cy0, cx1, cy1) = cell_rects(lay, 640, 360)[:3]
    assert tuple(img[(y0 + y1) // 2, (x0 + x1) // 2]) == (0, 0, 255)
    assert tuple(img[(by0 + by1) // 2, (bx0 + bx1) // 2]) == (40, 40, 40)            # boş kutu koyu gri
    assert tuple(img[(cy0 + cy1) // 2, (cx0 + cx1) // 2]) == (0, 255, 0)
    assert tuple(img[(cy0 + cy1) // 2, cx0 + 3]) == (0, 0, 0)                          # oran korundu: yan pay siyah


class FakeHub:
    def __init__(self) -> None:
        self.asked: list[tuple[str, str | None]] = []

    def tile(self, source_id: str, channel_id: str | None, quality: str = "sub") -> TileFrame:
        self.asked.append((source_id, channel_id))
        return TileFrame(1, np.full((90, 160, 3), 200, np.uint8), "live", "", 10.0)


def _views(view: dict[str, Any]) -> Any:
    return lambda vid: dict(view) if vid == view["id"] else None


def test_composer_streams_and_stops_without_subscribers() -> None:
    view = {"id": "v", "layout": "2", "tiles": [{"sourceId": "a", "channelId": None}, None]}
    hub = FakeHub()
    mh = MosaicHub(_views(view), hub)
    try:
        comp, tok = mh.acquire("v", 640, 360)
        seq, jpeg = comp.jpeg(tok, 0, timeout=3.0)
        assert jpeg is not None and jpeg[:2] == b"\xff\xd8" and seq >= 1
        assert ("a", None) in hub.asked
        mh.release(comp, tok)
        deadline = time.monotonic() + SUB_TTL_S + 6
        while comp.running() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not comp.running()                            # abonesiz: durdu, iş parçacığı sızmadı
    finally:
        mh.stop()


def test_same_view_two_sizes_and_template_edits_apply_live() -> None:
    view = {"id": "v", "layout": "1", "tiles": [{"sourceId": "a", "channelId": None}]}
    hub = FakeHub()
    mh = MosaicHub(_views(view), hub)
    try:
        c1, t1 = mh.acquire("v", 1280, 720)
        c2, _t2 = mh.acquire("v", 368, 592)
        assert c1 is not c2
        c1.jpeg(t1, 0, 3.0)
        view["tiles"] = [{"sourceId": "b", "channelId": "4"}]   # şablon düzenlendi: yeniden bağlanmadan
        hub.asked.clear()
        time.sleep(0.4)
        assert ("b", "4") in hub.asked
    finally:
        mh.stop()


def test_deleted_view_ends_stream() -> None:
    hub = FakeHub()
    mh = MosaicHub(lambda vid: None, hub)
    with pytest.raises(LookupError):
        mh.acquire("yok", 640, 360)
    mh.stop()
