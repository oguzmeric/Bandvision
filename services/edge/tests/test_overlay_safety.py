"""Poz güvenlik çizimi: kişi üstü etiketler (Kişi · süre doluyor · alarm)."""
from __future__ import annotations

import numpy as np
import pytest

from bantvision.core.people_track import MotTrack
from bantvision.core.profile import Profile, SafetyRule
from bantvision.core.safety import SafetyResult
from bantvision.overlay import DARK, GRAY, RED, SafetyTag, draw_safety, safety_tags

BOX = (0.3, 0.3, 0.5, 0.9)


def _track(i: int, box: tuple[float, float, float, float] = BOX) -> MotTrack:
    b = np.array(box, np.float64)
    return MotTrack(id=i, box=b, vel=np.zeros(4), last=b, score=0.9)


def _profile(hands: bool = True, lying: bool = True, phone: bool = True) -> Profile:
    p = Profile.jeweler()
    p.safety.handsUp = SafetyRule(hands, 3.0)
    p.safety.lying = SafetyRule(lying, 10.0)
    p.safety.phone = SafetyRule(phone, 15.0)
    return p


def test_observed_person_gets_person_tag() -> None:
    tags = safety_tags(_profile(), SafetyResult(tracks=[_track(1)]))
    assert tags == [SafetyTag(BOX, "person", "Kişi", None)]


def test_more_than_six_people_drop_person_text() -> None:
    tags = safety_tags(_profile(), SafetyResult(tracks=[_track(i) for i in range(1, 8)]))
    assert len(tags) == 7 and all(t.state == "person" and t.text == "" for t in tags)


def test_counting_phone_shows_seconds_and_progress() -> None:
    r = SafetyResult(tracks=[_track(1), _track(2, (0.6, 0.3, 0.8, 0.9))], active=[(1, "phone", 9.7, False)])
    tags = safety_tags(_profile(), r)
    assert [t.state for t in tags] == ["person", "counting"]          # çizim sırası: önce person
    assert tags[0].box == (0.6, 0.3, 0.8, 0.9)                          # iz 1 için person etiketi yok
    c = tags[1]
    assert c.box == BOX and c.text == "TELEFON 9 / 15 sn" and c.progress == pytest.approx(9.7 / 15)


def test_counting_seconds_never_read_past_threshold() -> None:
    """Telefon kanıtı dilimli: bölüm eşiği geçip henüz alarm vermemiş olabilir; yazı "17 / 15" değil "15 / 15"."""
    r = SafetyResult(tracks=[_track(1)], active=[(1, "phone", 17.4, False)])
    (c,) = safety_tags(_profile(), r)
    assert (c.state, c.text, c.progress) == ("counting", "TELEFON 15 / 15 sn", 1.0)


def test_counting_picks_rule_closest_to_firing() -> None:
    r = SafetyResult(tracks=[_track(1)], active=[(1, "hands_up", 1.0, False), (1, "phone", 12.0, False)])
    tags = safety_tags(_profile(), r)
    assert [(t.state, t.text) for t in tags] == [("counting", "TELEFON 12 / 15 sn")]


def test_fired_alarm_shows_duration() -> None:
    r = SafetyResult(tracks=[_track(1)], active=[(1, "phone", 81.2, True)])
    (t,) = safety_tags(_profile(), r)
    assert (t.state, t.text, t.progress) == ("alarm", "TELEFON · ALARM 1:21", None)
    gone = SafetyResult(active=[(1, "phone", 81.2, True)], boxes={1: BOX})     # iz bu karede gözlenmedi
    assert safety_tags(_profile(), gone) == [SafetyTag(BOX, "alarm", "TELEFON · ALARM 1:21", None)]


def test_disabled_rule_not_counted() -> None:
    r = SafetyResult(tracks=[_track(1)], active=[(1, "phone", 9.0, False)])
    assert safety_tags(_profile(phone=False), r) == [SafetyTag(BOX, "person", "Kişi", None)]


def test_labels_are_turkish() -> None:
    p = _profile()
    (a,) = safety_tags(p, SafetyResult(tracks=[_track(1)], active=[(1, "hands_up", 1.0, False)]))
    assert a.text == "ELLER YUKARI 1 / 3 sn"
    (b,) = safety_tags(p, SafetyResult(tracks=[_track(1)], active=[(1, "lying", 4.0, False)]))
    assert b.text == "YERDE 4 / 10 sn"
    p.safety.lying = SafetyRule(True, 3.0)
    (c,) = safety_tags(p, SafetyResult(tracks=[_track(1)], active=[(1, "lying", 2.0, False)]))
    assert c.text == "YERDE 2 / 3 sn"


def test_draw_safety_smoke() -> None:
    frame = np.zeros((360, 640, 3), np.uint8)
    r = SafetyResult(tracks=[_track(1), _track(2, (0.6, 0.3, 0.8, 0.9)), _track(3, (0.05, 0.0, 0.2, 0.5))],
                     active=[(1, "phone", 9.0, False), (2, "phone", 81.0, True)])
    img = draw_safety(frame.copy(), _profile(), r)
    px = lambda x, y: tuple(int(v) for v in img[y, x])
    yellow = (30, 190, 245)
    assert px(int(0.3 * 640), 200) == yellow                            # sayan kutu sol kenarı
    assert px(int(0.6 * 640), 200) == RED                                # alarm kutusu sol kenarı (kalın)
    # Kişi kutusu: ince (1 px) kenar yumuşatmalı gri çizgi; tepe pikseli nötr gri, GRAY'e yakın, iki yanı sönük
    row = [px(x, 100) for x in range(int(0.05 * 640) - 3, int(0.05 * 640) + 4)]
    peak = max(row)
    assert peak[0] == peak[1] == peak[2] and GRAY[0] - 30 <= peak[0] <= GRAY[0]
    assert sum(c[0] >= 100 for c in row) == 1 and row[0] == row[-1] == (0, 0, 0)
    assert GRAY in {px(x, 5) for x in range(40, 60)}                     # y1=0: etiket zemini kutunun içinde


def test_progress_bar_sits_under_the_label_on_the_box_top() -> None:
    """Süre çubuğu (onaylı tasarım §10): etiketin hemen altında, etiket ile kutunun üst kenarı arasında; dolu kısım
    sarı, kalanı koyu. Kutunun altında çubuk yok."""
    # Kutu, etiketten belirgin geniş: etiketin genişliği yazı tipine bağlı (Windows Segoe, Linux DejaVu daha geniş);
    # geniş kutuda "etiket kutu kadar geniş değil" denetimi hangi yazı tipiyle de geçerli.
    box = (0.3, 0.3, 0.8, 0.9)
    img = draw_safety(np.zeros((360, 640, 3), np.uint8), _profile(),
                      SafetyResult(tracks=[_track(1, box)], active=[(1, "phone", 9.0, False)]))
    px = lambda x, y: tuple(int(v) for v in img[y, x])
    yellow = (30, 190, 245)
    x1, y1, x2, y2 = int(box[0] * 640), int(box[1] * 360), int(box[2] * 640), int(box[3] * 360)
    filled = x1 + int((x2 - x1) * 9 / 15)
    bar = [y for y in range(y1 - 12, y1) if px(x2 - 3, y) == DARK]       # çubuğun dolmamış kısmı
    assert bar and max(bar) == y1 - 1                                     # kutunun üst kenarına dayalı
    by = bar[0]
    assert px(x1 + 3, by) == yellow and px(filled - 2, by) == yellow      # dolu kısım
    assert px(filled + 2, by) == DARK
    assert px(x1 + 1, by - 1) == yellow                                   # hemen üstünde etiket zemini
    assert px(x2 - 3, by - 1) == (0, 0, 0)                                # etiket kutu kadar geniş değil
    assert DARK not in {px(x, y) for x in range(x1 + 3, x2 - 3) for y in range(y2 - 8, y2)}   # altta çubuk yok


def test_progress_bar_inside_the_box_when_no_room_above() -> None:
    """Kutu karenin üst kenarındaysa etiket kutunun içinde üst kenarda, çubuk yine etiketin hemen altında."""
    box = (0.3, 0.0, 0.5, 0.9)
    img = draw_safety(np.zeros((360, 640, 3), np.uint8), _profile(),
                      SafetyResult(tracks=[_track(1, box)], active=[(1, "phone", 9.0, False)]))
    px = lambda x, y: tuple(int(v) for v in img[y, x])
    x1, x2 = int(0.3 * 640), int(0.5 * 640)
    bar = [y for y in range(40) if px(x2 - 3, y) == DARK]
    assert bar and bar[0] > 5                                             # etiketin altında, en üstte değil
    assert px(x1 + 5, bar[0] - 1) == (30, 190, 245)                       # hemen üstünde etiket zemini
