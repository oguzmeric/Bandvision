"""Ekrandaki sayım sıra numaraları: her ürün kendi numarasını taşır (iPhone FrameProcessor ile aynı kural)."""
from __future__ import annotations

from bantvision.core.segmenter import Blob
from bantvision.core.tracker import BlobTracker
from bantvision.video import number_label, split_numbers


def blob(cx: float, cy: float, w: float, h: float, mult: int) -> Blob:
    return Blob(cx=cx, cy=cy, bbox=(cx - w / 2, cy - h / 2, w, h), area=w * h, label=1, multiplicity=mult)


def test_number_label() -> None:
    assert number_label([]) == ""
    assert number_label([34]) == "34"
    assert number_label([34, 35]) == "34·35"
    assert number_label([1, 2, 3]) == "1·2·3"
    assert number_label([34, 35, 36, 37]) == "34…37"


def test_split_hands_last_numbers_to_child() -> None:
    numbers = {7: [12, 13]}
    split_numbers(numbers, [(7, 9, 1)])
    assert numbers == {7: [12], 9: [13]}
    # Sayılmamış çocuk numara almaz; bilinmeyen ebeveyn yok sayılır
    split_numbers(numbers, [(7, 10, 0), (99, 11, 1)])
    assert numbers == {7: [12], 9: [13]}
    # Ebeveynin tüm numaraları çocuğa geçerse ebeveyn listeden çıkar
    split_numbers(numbers, [(9, 12, 3)])
    assert numbers == {7: [12], 12: [13]}


def test_touching_pair_counted_then_split_records_child() -> None:
    """Çizgiyi ×2 leke olarak geçen çift, sonra ayrılır: çocuk 1 sayılmış ürünü devralır, yeni olay yok."""
    tr = BlobTracker()
    args = {"vertical": True, "sign": 1.0, "line": 0.5, "max_distance": 0.2, "min_hits": 2}
    events = []
    for y in (0.30, 0.38, 0.46, 0.54, 0.62):
        events += tr.update([blob(0.5, y, 0.2, 0.12, 2)], **args)
        assert tr.last_splits == []
    assert sum(e.delta for e in events) == 2
    parent = events[0].track_id

    split = tr.update([blob(0.45, 0.70, 0.08, 0.06, 1), blob(0.55, 0.70, 0.08, 0.06, 1)], **args)
    assert split == []
    assert len(tr.last_splits) == 1
    p, child, counted = tr.last_splits[0]
    assert (p, counted) == (parent, 1) and child != parent

    numbers = {parent: [1, 2]}
    split_numbers(numbers, tr.last_splits)
    assert numbers == {parent: [1], child: [2]}

    # Sonraki güncelleme bölünme listesini temizler
    tr.update([blob(0.45, 0.78, 0.08, 0.06, 1), blob(0.55, 0.78, 0.08, 0.06, 1)], **args)
    assert tr.last_splits == []
