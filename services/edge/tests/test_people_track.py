"""Kişi takibi ve tampon bantlı çizgi geçişi (§4.10): sentetik yörüngelerle kesin senaryolar."""
from __future__ import annotations

import math

from bantvision.core.people_track import MotParams, MotTracker

LINE = 0.55


def side(x: float, y: float) -> float:          # aşağı = giriş
    return y - LINE


def box(cx: float, cy: float, w: float = 0.08, h: float = 0.16) -> tuple[float, float, float, float]:
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def run(frames: list[list[tuple[tuple[float, float, float, float], float]]],
        params: MotParams | None = None) -> tuple[int, int, MotTracker]:
    t = MotTracker(params or MotParams(max_age=30))
    ins = outs = 0
    for dets in frames:
        a, b = t.update(dets, side)
        ins += len(a)
        outs += len(b)
    return ins, outs, t


def walk(y0: float, y1: float, n: int, x: float = 0.5, score: float = 0.8) -> list[list]:
    return [[(box(x, y0 + (y1 - y0) * k / (n - 1)), score)] for k in range(n)]


def test_enter_and_exit() -> None:
    assert run(walk(0.2, 0.9, 40))[:2] == (1, 0)
    assert run(walk(0.9, 0.2, 40))[:2] == (0, 1)


def test_loitering_on_line_is_not_counted() -> None:
    frames = [[(box(0.5, LINE + 0.015 * math.sin(k / 3)), 0.8)] for k in range(150)]
    assert run(frames)[:2] == (0, 0)


def test_turn_back_counts_one_entry_one_exit() -> None:
    assert run(walk(0.2, 0.8, 30) + walk(0.8, 0.2, 30))[:2] == (1, 1)


def test_approach_and_turn_back_before_line_counts_nothing() -> None:
    assert run(walk(0.2, LINE - 0.01, 25) + walk(LINE - 0.01, 0.2, 25))[:2] == (0, 0)


def test_detection_dropout_mid_crossing_keeps_identity() -> None:
    frames = walk(0.2, 0.9, 40)
    for k in range(15, 27):                          # çizgi civarında 12 kare tespit yok
        frames[k] = []
    ins, outs, t = run(frames)
    assert (ins, outs) == (1, 0)
    assert t.next_id == 2                            # tek iz, kimlik kopmadı


def test_low_confidence_frames_continue_track() -> None:
    frames = walk(0.2, 0.9, 40)
    for k in range(10, 30):
        frames[k] = [(frames[k][0][0], 0.2)]          # silik tespit: yalnızca mevcut izi sürdürür
    ins, _, t = run(frames)
    assert ins == 1 and t.next_id == 2


def test_low_confidence_alone_never_starts_a_track() -> None:
    assert run([[(box(0.5, 0.2 + 0.7 * k / 39), 0.2)] for k in range(40)])[:2] == (0, 0)


def test_person_stopping_while_occluded_is_reacquired() -> None:
    frames = walk(0.2, 0.45, 15) + [[] for _ in range(10)] + walk(0.45, 0.9, 20)
    ins, _, t = run(frames)
    assert ins == 1 and t.next_id == 2


def test_new_person_far_away_does_not_steal_lost_identity() -> None:
    # A çizginin üstünde kaybolur; aynı anda çizginin altında uzakta B belirir → hayalet giriş yok
    frames = walk(0.2, 0.4, 10, x=0.3) + [[(box(0.75, 0.75), 0.8)] for _ in range(15)]
    assert run(frames)[:2] == (0, 0)


def test_single_frame_false_positive_is_ignored() -> None:
    frames: list[list] = [[] for _ in range(30)]
    frames[10] = [(box(0.5, 0.5), 0.9)]
    frames[11] = [(box(0.5, 0.6), 0.9)]               # 2 kare: onaydan önce kaybolur
    assert run(frames)[:2] == (0, 0)


def test_group_side_by_side() -> None:
    n = 40
    frames = [[(box(x, 0.2 + 0.7 * k / (n - 1), w=0.07), 0.8) for x in (0.3, 0.45, 0.6)] for k in range(n)]
    assert run(frames)[:2] == (3, 0)


def test_people_crossing_paths_in_opposite_directions() -> None:
    n = 50
    frames = []
    for k in range(n):
        f = k / (n - 1)
        frames.append([(box(0.42, 0.15 + 0.8 * f), 0.8), (box(0.58, 0.95 - 0.8 * f), 0.8)])
    assert run(frames)[:2] == (1, 1)


def test_fast_motion_low_fps_uses_center_gate() -> None:
    # 6 karede çizgiyi geçen hızlı kişi (kareler arası IoU < eşik): merkez yakınlığı + hız tahminiyle eşleşir
    ins, outs, t = run(walk(0.25, 0.85, 6))
    assert (ins, outs) == (1, 0) and t.next_id == 2


def test_crossing_before_confirmation_is_counted_on_confirmation() -> None:
    # 3. gözlemde çizgiyi geçer, 4. gözlemde onaylanır: geçiş kaybolmaz, onayla birlikte sayılır
    frames = [[(box(0.5, y), 0.8)] for y in (0.47, 0.52, 0.58, 0.62, 0.65)]
    t = MotTracker(MotParams(min_hits=4, max_age=30))
    got = [len(t.update(f, side)[0]) for f in frames]
    assert got == [0, 0, 0, 1, 0]


# ---------------------------------------------------------------- hareket desteği (tepeden kamera)

def run_motion(frames: list[tuple[list, list]]) -> tuple[int, int, MotTracker]:
    t = MotTracker(MotParams(max_age=30))
    ins = outs = 0
    for dets, blobs in frames:
        a, b = t.update(dets, side, "center", blobs)
        ins += len(a)
        outs += len(b)
    return ins, outs, t


def test_undetected_below_camera_then_detected_counts_entry() -> None:
    # kişi çizgiden önce yalnızca hareket lekesi (tanıyıcı görmüyor), çizgiden sonra tanınıyor → giriş sayılır
    frames = []
    for k in range(40):
        y = 0.2 + 0.7 * k / 39
        b = box(0.5, y)
        frames.append(([(b, 0.8)] if y > LINE + 0.1 else [], [b]))
    assert run_motion(frames)[:2] == (1, 0)


def test_detected_then_lost_under_camera_counts_exit_via_motion() -> None:
    frames = []
    for k in range(40):
        y = 0.9 - 0.7 * k / 39
        b = box(0.5, y)
        frames.append(([(b, 0.8)] if y > LINE + 0.1 else [], [b]))   # çizgiye yaklaşınca tanıma kaybolur
    assert run_motion(frames)[:2] == (0, 1)


def test_motion_only_object_is_never_counted() -> None:
    # kapı, gölge, araba: hareket var, kişi tanıması hiç yok → sayılmaz
    frames = [([], [box(0.5, 0.2 + 0.7 * k / 39)]) for k in range(40)]
    assert run_motion(frames)[:2] == (0, 0)


def test_motion_and_detection_of_same_person_counted_once() -> None:
    # tanıma ve hareket lekesi her karede birlikte (lekesi biraz kaymış ve büyük): tek kişi, tek sayım
    frames = []
    for k in range(40):
        y = 0.2 + 0.7 * k / 39
        frames.append(([(box(0.5, y), 0.8)], [box(0.51, y + 0.02, w=0.11, h=0.2)]))
    assert run_motion(frames)[:2] == (1, 0)


def test_group_merged_into_one_blob_both_counted() -> None:
    # yan yana iki kişi tanınıyor; çizgi civarında tanıma ikisini de kaçırıyor, hareket tek birleşik leke
    frames = []
    for k in range(40):
        y = 0.2 + 0.7 * k / 39
        a, b = box(0.45, y), box(0.55, y)
        merged = (0.41, y - 0.08, 0.59, y + 0.08)
        if abs(y - LINE) < 0.12:
            frames.append(([], [merged]))
        else:
            frames.append(([(a, 0.8), (b, 0.8)], [merged]))
    assert run_motion(frames)[:2] == (2, 0)


def test_motion_track_verified_late_counts_pending_entry_once() -> None:
    # hareket izi çizgiyi geçer, çok sonra tanınır: bekleyen giriş bir kez sayılır, sonraki karelerde tekrar sayılmaz
    frames = []
    for k in range(50):
        y = 0.2 + 0.7 * min(k, 39) / 39
        b = box(0.5, y)
        frames.append(([(b, 0.8)] if k >= 42 else [], [b]))
    assert run_motion(frames)[:2] == (1, 0)


def test_single_frame_edge_spikes_near_line_are_not_crossings() -> None:
    # kişi çizginin hemen önünde bekliyor; kutu kenarı arada bir karelik çizginin ötesine zıplıyor (bacak kapanması)
    frames = []
    for k in range(120):
        y = LINE - 0.05 + (0.09 if k % 7 == 3 else 0.0)
        frames.append([(box(0.5, y), 0.8)])
    assert run(frames)[:2] == (0, 0)


def test_large_near_person_jitter_uses_size_relative_band() -> None:
    # kameraya yakın büyük kişi (boy 0.5) çizgi üstünde ±0.035 titriyor: bant boyla genişler, sayılmaz
    frames = [[(box(0.5, LINE + (0.035 if k % 2 else -0.035), w=0.2, h=0.5), 0.8)] for k in range(80)]
    assert run(frames)[:2] == (0, 0)


def _walk_staff(n: int, vote_of: dict[int, bool | None]) -> tuple[int, int, int, int]:
    """Tek kişi yukarıdan aşağı yürür; kare k'deki oy vote_of[k] (yoksa None). (giriş, çıkış, p_giriş, p_çıkış)."""
    t = MotTracker(MotParams(max_age=30))
    ins = outs = s_in = s_out = 0
    for k in range(n):
        y = 0.2 + 0.7 * k / (n - 1)
        box = (0.46, y - 0.08, 0.54, y + 0.08)
        e, x = t.update([(box, 0.8)], lambda _x, yy: yy - 0.55,
                        staff_vote=lambda _b, _o, k=k: vote_of.get(k))
        ins, outs = ins + len(e), outs + len(x)
        s_in, s_out = s_in + len(t.staff_entered), s_out + len(t.staff_exited)
    return ins, outs, s_in, s_out


def test_staff_crossing_is_counted_separately() -> None:
    assert _walk_staff(40, {k: True for k in range(40)}) == (0, 0, 1, 0)


def test_customer_with_few_or_minority_staff_votes_counts_as_entry() -> None:
    assert _walk_staff(40, {0: True, 1: True}) == (1, 0, 0, 0)                        # < 3 oy
    assert _walk_staff(40, {k: k % 3 == 0 for k in range(40)}) == (1, 0, 0, 0)         # azınlık
    assert _walk_staff(40, {}) == (1, 0, 0, 0)                                         # oy yok (renk yok gibi)


def test_vote_receives_other_boxes_of_the_frame() -> None:
    seen: list[int] = []
    t = MotTracker(MotParams(max_age=30))
    a, b = (0.30, 0.1, 0.38, 0.3), (0.60, 0.1, 0.68, 0.3)
    t.update([(a, 0.8), (b, 0.8)], lambda _x, y: y - 0.55, staff_vote=lambda _bx, o: seen.append(len(o)))
    assert seen == [1, 1]
