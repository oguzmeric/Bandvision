"""Birleştirici: kareler doğru hücreye oran korunarak; abonesiz durur; iki boyut aynı anda; şablon değişince hemen."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import cv2
import numpy as np
import pytest

from bantvision.live import mosaic
from bantvision.live.layouts import cell_rects, layout_by_id
from bantvision.live.mosaic import SUB_TTL_S, Composer, MosaicHub, compose, fit_canvas
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


def test_compose_bad_frame_greys_only_its_cell() -> None:
    lay = layout_by_id("2")
    assert lay is not None
    good = np.full((90, 160, 3), 200, np.uint8)
    bad = np.zeros((90, 160, 4), np.uint8)                   # 4 kanallı: tuvale yazılamaz
    img = compose(lay, 640, 360, [bad, good], log_key="compose-bad")
    (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = cell_rects(lay, 640, 360)
    assert tuple(img[(ay0 + ay1) // 2, (ax0 + ax1) // 2]) == (40, 40, 40)             # bozuk kutu gri
    assert tuple(img[(by0 + by1) // 2, (bx0 + bx1) // 2]) == (200, 200, 200)          # komşu etkilenmedi


class FakeHub:
    def __init__(self) -> None:
        self.asked: list[tuple[str, str | None]] = []

    def tile(self, source_id: str, channel_id: str | None, quality: str = "sub") -> TileFrame:
        self.asked.append((source_id, channel_id))
        return TileFrame(1, np.full((90, 160, 3), 200, np.uint8), "live", "", 10.0)


class FakeClock:
    """Elle ilerletilen saat (abone zaman aşımı ve boşta durma bunu kullanır)."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _views(view: dict[str, Any]) -> Any:
    return lambda vid: dict(view) if vid == view["id"] else None


def _wait(cond: Any, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return bool(cond())


def _idle_stop(clock: FakeClock, comp: Composer, timeout: float = 10.0) -> bool:
    """Saati ilerleterek abone zaman aşımı + boşta durmayı bekler."""
    deadline = time.monotonic() + timeout
    while comp.running() and time.monotonic() < deadline:
        clock.now += 1.0
        time.sleep(0.05)
    return not comp.running()


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
        c2, t2 = mh.acquire("v", 368, 592)
        assert c1 is not c2
        c1.jpeg(t1, 0, 3.0)
        _, jpeg2 = c2.jpeg(t2, 0, 3.0)
        assert jpeg2 is not None
        img2 = cv2.imdecode(np.frombuffer(jpeg2, np.uint8), cv2.IMREAD_COLOR)
        assert img2.shape[:2] == (592, 368)                   # ikinci boyut kendi tuvalinde (yükseklik, genişlik)
        view["tiles"] = [{"sourceId": "b", "channelId": "4"}]   # şablon düzenlendi: yeniden bağlanmadan
        hub.asked.clear()
        assert _wait(lambda: ("b", "4") in hub.asked, timeout=3.0)
    finally:
        mh.stop()


def test_deleted_view_ends_stream() -> None:
    hub = FakeHub()
    mh = MosaicHub(lambda vid: None, hub)
    with pytest.raises(LookupError):
        mh.acquire("yok", 640, 360)
    mh.stop()


def test_template_deleted_mid_stream_marks_composer_gone() -> None:
    views: dict[str, dict[str, Any]] = {
        "v": {"id": "v", "layout": "1", "tiles": [{"sourceId": "a", "channelId": None}]}}
    mh = MosaicHub(lambda vid: dict(views[vid]) if vid in views else None, FakeHub())
    try:
        comp, tok = mh.acquire("v", 640, 360)
        seq, jpeg = comp.jpeg(tok, 0, 3.0)
        assert jpeg is not None and not comp.gone
        del views["v"]                                       # şablon silindi
        seq2, jpeg2 = comp.jpeg(tok, seq, 3.0)
        assert jpeg2 is None and comp.gone and seq2 >= seq    # akış bitirilir (uç nokta `gone` görünce döner)
        with pytest.raises(LookupError):
            mh.acquire("v", 640, 360)
        views["v"] = {"id": "v", "layout": "1", "tiles": [{"sourceId": "a", "channelId": None}]}
        comp2, tok2 = mh.acquire("v", 640, 360)              # aynı kimlikle yeniden oluşturulursa yeni birleştirici
        assert comp2 is not comp and comp2.jpeg(tok2, 0, 3.0)[1] is not None
    finally:
        mh.stop()


# ---------------------------------------------------------------------- yaşam döngüsü

def test_subscriber_ttl_expiry_with_injected_clock_stops_thread() -> None:
    view = {"id": "v", "layout": "1", "tiles": [{"sourceId": "a", "channelId": None}]}
    clock = FakeClock()
    mh = MosaicHub(_views(view), FakeHub(), clock=clock)
    try:
        comp, tok = mh.acquire("v", 320, 240)
        assert comp.jpeg(tok, 0, 3.0)[1] is not None and comp.running()
        time.sleep(0.5)
        assert comp.running()                                # saat ilerlemedi: abone hâlâ taze
        assert _idle_stop(clock, comp)                       # istemeyen abone düşer, sonra iş parçacığı durur
        assert comp._jpeg is None                            # eski tuval bir sonraki aboneye verilmez
    finally:
        mh.stop()


def test_resume_after_idle_stop_restarts_with_old_token_and_with_reacquire() -> None:
    view = {"id": "v", "layout": "1", "tiles": [{"sourceId": "a", "channelId": None}]}
    clock = FakeClock()
    mh = MosaicHub(_views(view), FakeHub(), clock=clock)
    try:
        comp, tok = mh.acquire("v", 320, 240)
        seq1, jpeg = comp.jpeg(tok, 0, 3.0)
        assert jpeg is not None
        assert _idle_stop(clock, comp)                       # uyuyan telefon / arka plan sekmesi: kare istemedi
        seq2, jpeg2 = comp.jpeg(tok, seq1, 5.0)              # uyandı: AYNI jeton kare ister
        assert jpeg2 is not None and seq2 > seq1 and comp.running()
        assert _idle_stop(clock, comp)
        comp3, tok3 = mh.acquire("v", 320, 240)              # yeniden bağlanma: aynı anahtar, yeniden başlar
        assert comp3 is comp
        seq3, jpeg3 = comp3.jpeg(tok3, seq2, 5.0)
        assert jpeg3 is not None and seq3 > seq2             # sıra numarası geri sarmaz (eski istemci takılmaz)
    finally:
        mh.stop()


def test_concurrent_subscribe_starts_exactly_one_thread() -> None:
    vid = "tek-iplik-1"
    view = {"id": vid, "layout": "1", "tiles": [{"sourceId": "a", "channelId": None}]}
    comp = Composer(vid, 320, 240, _views(view), FakeHub(), time.monotonic)
    n = 8
    barrier = threading.Barrier(n)
    tokens: list[int] = []

    def go() -> None:
        barrier.wait()
        tokens.append(comp.subscribe())

    threads = [threading.Thread(target=go) for _ in range(n)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(5.0)
        assert len(tokens) == n and len(set(tokens)) == n
        mine = [t for t in threading.enumerate() if t.name == f"mozaik-{vid[:8]}"]
        assert len(mine) == 1                                # çift iş parçacığı = saniyede 20 tuval
    finally:
        comp.stop()


def test_acquire_prunes_idle_and_gone_composers_and_retires_them() -> None:
    views: dict[str, dict[str, Any]] = {
        k: {"id": k, "layout": "1", "tiles": [{"sourceId": "a", "channelId": None}]} for k in ("v1", "v2", "v3")}
    clock = FakeClock()
    mh = MosaicHub(lambda vid: dict(views[vid]) if vid in views else None, FakeHub(), clock=clock)
    try:
        c1, t1 = mh.acquire("v1", 320, 240)
        c1.jpeg(t1, 0, 3.0)
        assert _idle_stop(clock, c1)
        c2, t2 = mh.acquire("v2", 320, 240)                  # v1 boşta ve abonesiz: ayıklanır
        assert ("v1", 320, 240) not in mh._comps and c1.stopped    # sahipsiz kalıp yeniden canlanmaz
        c2.jpeg(t2, 0, 3.0)
        del views["v2"]                                      # v2 silinir: birleştirici `gone` olur
        assert _wait(lambda: c2.gone)
        c3, t3 = mh.acquire("v3", 320, 240)
        assert ("v2", 320, 240) not in mh._comps
        assert list(mh._comps) == [("v3", 320, 240)] and c3.jpeg(t3, 0, 3.0)[1] is not None
    finally:
        mh.stop()


def test_stopped_composer_and_stopped_hub() -> None:
    view = {"id": "v", "layout": "1", "tiles": [{"sourceId": "a", "channelId": None}]}
    mh = MosaicHub(_views(view), FakeHub())
    comp, tok = mh.acquire("v", 320, 240)
    seq, _ = comp.jpeg(tok, 0, 3.0)
    mh.stop()
    assert comp.stopped and not comp.running()
    t0 = time.monotonic()
    seq2, _ = comp.jpeg(tok, seq, 3.0)                       # durmuş: bekletmez (uç nokta akışı bitirir, dönmez)
    assert time.monotonic() - t0 < 1.0 and seq2 == seq
    with pytest.raises(mosaic.MosaicStopped):
        mh.acquire("v", 320, 240)
    mh.stop()                                                # ikinci kapatma zararsız


def test_bad_tile_greys_only_itself_and_logs_at_most_once_per_minute(caplog: pytest.LogCaptureFixture) -> None:
    class Hub(FakeHub):
        def tile(self, source_id: str, channel_id: str | None, quality: str = "sub") -> TileFrame:
            if source_id == "bad":
                raise RuntimeError("okuyucu patladı")
            return super().tile(source_id, channel_id, quality)

    view = {"id": "kotu-kutu", "layout": "2",
            "tiles": [{"sourceId": "bad", "channelId": None}, {"sourceId": "a", "channelId": None}]}
    mh = MosaicHub(_views(view), Hub())
    try:
        with caplog.at_level(logging.WARNING, logger="bantvision.live.mosaic"):
            comp, tok = mh.acquire("kotu-kutu", 640, 368)
            seq = 0
            jpeg: bytes | None = None
            for _ in range(5):
                seq, jpeg = comp.jpeg(tok, seq, 3.0)
                assert jpeg is not None                      # bir kutunun hatası tuvali öldürmez
        assert jpeg is not None
        img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        lay = layout_by_id("2")
        assert lay is not None
        (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = cell_rects(lay, 640, 368)
        assert abs(int(img[(ay0 + ay1) // 2, (ax0 + ax1) // 2, 1]) - 40) <= 8            # bozuk kutu gri
        assert abs(int(img[(by0 + by1) // 2, (bx0 + bx1) // 2, 1]) - 200) <= 8           # sağlam kutu çalışıyor
        warns = [r for r in caplog.records if r.name == "bantvision.live.mosaic" and r.levelno >= logging.WARNING]
        assert len(warns) == 1                               # dakikada en çok bir günlük satırı (şablon başına)
    finally:
        mh.stop()
