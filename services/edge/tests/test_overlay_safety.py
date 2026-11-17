"""Poz güvenlik çizimi: kişi üstü etiketler (Kişi · süre doluyor · alarm)."""
from __future__ import annotations

import numpy as np
import pytest

from bantvision.core.people_track import MotTrack
from bantvision.core.profile import Profile, SafetyRule
from bantvision.core.safety import SafetyResult
from bantvision.overlay import RED, SafetyTag, draw_safety, safety_tags

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
    assert px(int(0.3 * 640), 200) == (30, 190, 245)                    # sayan kutu sol kenarı
    assert RED in {px(x, 200) for x in range(int(0.6 * 640) - 3, int(0.6 * 640) + 4)}
    grey = [px(x, 100) for x in range(int(0.05 * 640) - 2, int(0.05 * 640) + 3)]       # ince çizgi kenar yumuşatmalı
    assert any(c[0] == c[1] == c[2] >= 100 for c in grey)
    assert (170, 170, 170) in {px(x, 5) for x in range(40, 60)}          # y1=0: etiket zemini kutunun içinde
