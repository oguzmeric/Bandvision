"""Güvenlik analiz alanları (`safety.areas`; tasarım docs/superpowers/specs/2026-11-17-alarm-penceresi-design.md §11):
profil gidiş-dönüşü ve doğrulama, `area_rules`, çözümleyicide alan süzgeci ve kural başına izin, alarmın alan adı,
alarm kaydı, Telegram metni ve çizim."""
from __future__ import annotations

import json
import pathlib
from typing import Any

import numpy as np
import pytest
from fakes_safety import FakePhoneDetector, FakePose, hands_up_kp
from jsonschema import Draft202012Validator

from bantvision.core import Profile
from bantvision.core.people_track import MotTrack
from bantvision.core.profile import SafetyArea
from bantvision.core.safety import RULE_OF_KIND, SafetyAlarm, SafetyAnalyzer, SafetyResult, area_rules
from bantvision.live.alarms import AlarmStore
from bantvision.overlay import CYAN, RED, AreaTag, SafetyTag, area_tags, draw_safety, safety_tags

CONTRACTS = pathlib.Path(__file__).resolve().parents[3] / "contracts"
FRAME = np.zeros((480, 640, 3), np.uint8)
PERSON = (280, 80, 360, 440)                    # piksel; normalize merkez (0,5, 0,54)
SQUARE = [(0.3, 0.3), (0.7, 0.3), (0.7, 0.8), (0.3, 0.8)]          # kişiyi içine alır
CORNER = [(0.0, 0.0), (0.2, 0.0), (0.2, 0.2), (0.0, 0.2)]          # kişinin uzağında
# hands_up_kp sol bileği (290, 100); kişi kırpıntısı %20 payla (264, 8)'den başlar → kırpıntıda (26, 92)
PHONE_AT_WRIST = (16.0, 82.0, 36.0, 102.0, 0.4)


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    schema = json.loads((CONTRACTS / "product-profile.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def _area(name: str = "Masa 3", points: list[Any] | None = None, rules: list[Any] | None = None) -> dict[str, Any]:
    return {"name": name, "points": [list(p) for p in (points or SQUARE)],
            "rules": ["handsUp", "lying", "phone"] if rules is None else rules}


def _jeweler_dict(areas: Any) -> dict[str, Any]:
    d = Profile.jeweler().to_dict()
    d["safety"] = {**d["safety"], "areas": areas}
    return d


# ---------------------------------------------------------------- profil ve sözleşme

def test_kind_mapping_matches_contract_rule_names() -> None:
    assert RULE_OF_KIND == {"hands_up": "handsUp", "lying": "lying", "phone": "phone"}


def test_areas_round_trip(validator: Draft202012Validator) -> None:
    d = _jeweler_dict([_area(), _area("Kasa", CORNER, ["handsUp"])])
    p = Profile.from_dict(d)
    assert p.safety.areas == [SafetyArea("Masa 3", SQUARE, ["handsUp", "lying", "phone"]),
                              SafetyArea("Kasa", CORNER, ["handsUp"])]
    out = p.to_dict()
    assert out["safety"]["areas"] == [_area(), _area("Kasa", CORNER, ["handsUp"])]
    assert Profile.from_dict(out).to_dict() == out
    assert [e.message for e in validator.iter_errors(out)] == []


def test_empty_areas_not_written_and_missing_reads_empty(validator: Draft202012Validator) -> None:
    out = Profile.jeweler().to_dict()
    assert "areas" not in out["safety"]
    assert Profile.from_dict(out).safety.areas == []
    assert Profile.from_dict(_jeweler_dict([])).safety.areas == []
    assert "areas" not in Profile.from_dict(_jeweler_dict([])).to_dict()["safety"]
    assert [e.message for e in validator.iter_errors(_jeweler_dict([]))] == []


def test_area_name_is_trimmed_and_length_checked_like_schema(validator: Draft202012Validator) -> None:
    """Şemadaki gibi: ham ad en çok 40 karakter (kırpmadan önce), kırpılmış ad boş olamaz; saklanan ad kırpılmıştır."""
    p = Profile.from_dict(_jeweler_dict([_area(" Masa 3 ")]))
    assert p.safety.areas[0].name == "Masa 3"
    assert Profile.from_dict(_jeweler_dict([_area("a" * 40)])).safety.areas[0].name == "a" * 40
    raw = _jeweler_dict([_area(" " + "a" * 39 + " ")])                  # ham 41, kırpılmış 39: ikisi de reddeder
    with pytest.raises(ValueError, match="alan adı 1–40 karakter"):
        Profile.from_dict(raw)
    assert list(validator.iter_errors(raw))


BAD_AREAS: list[tuple[str, Any]] = [
    ("2 köşe", [_area(points=SQUARE[:2])]),
    ("13 köşe", [_area(points=[(i / 20, 0.5 + (i % 2) / 10) for i in range(13)])]),
    ("1.2 koordinat", [_area(points=[(0.1, 0.1), (1.2, 0.1), (0.5, 0.5)])]),
    ("eksi koordinat", [_area(points=[(0.1, 0.1), (-0.1, 0.1), (0.5, 0.5)])]),
    ("17 alan", [_area(f"Alan {i}") for i in range(17)]),
    ("boş ad", [_area("")]),
    ("boşluk ad", [_area("   ")]),
    ("41 karakter ad", [_area("a" * 41)]),
    ("kırpınca 40 ama ham 42 ad", [_area(" " + "a" * 40 + " ")]),
    ("boş rules", [_area(rules=[])]),
    ("bilinmeyen kural", [_area(rules=["fire"])]),
    ("çekirdek adı kural", [_area(rules=["hands_up"])]),
    ("tekrarlı kural", [_area(rules=["phone", "phone"])]),
    ("liste değil", "x"),
    ("alan nesne değil", [["Masa"]]),
    ("ad yok", [{"points": [list(p) for p in SQUARE], "rules": ["phone"]}]),
    ("nokta sayı değil", [_area(points=[(0.1, 0.1), ("a", 0.1), (0.5, 0.5)])]),
    ("nokta mantıksal", [_area(points=[(0.1, 0.1), (True, 0.1), (0.5, 0.5)])]),
    ("3 değerli nokta", [_area(points=[(0.1, 0.1, 0.2), (0.4, 0.1), (0.5, 0.5)])]),
    ("fazla alan", [{**_area(), "color": "red"}]),
]


@pytest.mark.parametrize(("why", "areas"), BAD_AREAS, ids=[w for w, _ in BAD_AREAS])
def test_invalid_areas_rejected_when_reading_profile(why: str, areas: Any) -> None:
    with pytest.raises(ValueError):
        Profile.from_dict(_jeweler_dict(areas))


@pytest.mark.parametrize(("why", "areas"), BAD_AREAS, ids=[w for w, _ in BAD_AREAS])
def test_invalid_areas_rejected_by_schema(validator: Draft202012Validator, why: str, areas: Any) -> None:
    assert list(validator.iter_errors(_jeweler_dict(areas))), why


def test_live_api_rejects_invalid_areas_with_422(tmp_path: pathlib.Path) -> None:
    pytest.importorskip("fastapi")
    from conftest import local_client

    from bantvision.analyzer import Settings, create_app

    with local_client(create_app(Settings(data_dir=tmp_path))) as client:
        body = client.post("/api/v1/live/profiles", json={"preset": "jeweler"}).json()
        for why, areas in BAD_AREAS:
            r = client.post("/api/v1/live/profiles", json={**body, "safety": {**body["safety"], "areas": areas}})
            assert r.status_code == 422 and "Güvenlik" in r.json()["detail"], (why, r.text)
        r = client.put(f"/api/v1/live/profiles/{body['id']}",
                       json={**body, "safety": {**body["safety"], "areas": [_area(rules=[])]}})
        assert r.status_code == 422
        ok = [_area(" Masa 3 "), _area("Kasa", CORNER, ["phone"])]
        r = client.post("/api/v1/live/profiles", json={**body, "name": "Alanlı", "safety": {**body["safety"], "areas": ok}})
        assert r.status_code == 201, r.text
        assert r.json()["safety"]["areas"] == [_area(), _area("Kasa", CORNER, ["phone"])]


def test_stored_profile_with_bad_areas_gives_turkish_error_not_crash(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Diskte elle bozulmuş alanlı şablon profil: oturum açma 500 değil, nasıl düzeltileceğini söyleyen Türkçe 422;
    profil PUT ile düzeltilebilir. Yeniden başlatmada izlenen kameranın bozuk anlık görüntüsü "kaydı bozuk" diye
    günlüğe yazılır, sunucu açılır."""
    pytest.importorskip("fastapi")
    import logging

    from conftest import local_client
    from test_live import _app_with_fakes, _safety_session_with_fake, _watch

    monkeypatch.setenv("ANALYZER_ALLOW_FILE_SOURCES", "1")
    with local_client(_app_with_fakes(tmp_path)) as c:
        sess, _sid = _safety_session_with_fake(c, monkeypatch)
        src_id, prof_id = sess.source_id, sess.profile_id
        c.delete(f"/api/v1/live/sessions/{_sid}")
        f = tmp_path / "live" / "profiles.json"
        items = json.loads(f.read_text(encoding="utf-8"))
        good = next(p for p in items if p["id"] == prof_id)
        bad = {**good, "safety": {**good["safety"], "areas": [_area(rules=[])]}}
        f.write_text(json.dumps([bad if p["id"] == prof_id else p for p in items]), encoding="utf-8")
        r = c.post("/api/v1/live/sessions", json={"sourceId": src_id, "profileId": prof_id})
        assert r.status_code == 422, r.text
        assert r.json()["detail"] == ("Profil okunamadı: 1. alan kuralları eller yukarı, yerde yatma ve telefon "
                                      "kullanımından en az biri olmalı ve tekrar etmemeli. Profili panelde düzeltip "
                                      "yeniden kaydedin.")
        r = c.put(f"/api/v1/live/profiles/{prof_id}", json=good)      # düzeltilebilir (404/500 değil)
        assert r.status_code == 200, r.text
        assert c.post("/api/v1/live/sessions", json={"sourceId": src_id, "profileId": prof_id}).status_code < 300
    snap = _watch(tmp_path)[0]
    broken = {**snap, "channelId": "9", "name": "Bozuk alan",
              "profile": {**snap["profile"], "safety": {**snap["profile"]["safety"], "areas": [_area("a" * 41)]}}}
    (tmp_path / "live" / "watch.json").write_text(json.dumps([broken, snap]), encoding="utf-8")
    with caplog.at_level(logging.WARNING), local_client(_app_with_fakes(tmp_path)) as c:
        assert len(c.get("/api/v1/live/sessions").json()) == 1      # sağlam kamera açıldı
    assert "kaydı bozuk" in caplog.text and "Bozuk alan" in caplog.text


def test_bad_camera_setting_opens_with_template_and_is_fixed_by_saving(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Bu kameraya kaydedilmiş ayar bozuksa kamera şablonla açılır (izleme kesilmez) ve uyarı günlüğe yazılır;
    panelin Ayarla → Kaydet yolu (`PUT sessions/{id}/profile?save=true`) bozuk kaydın üstüne yazar."""
    pytest.importorskip("fastapi")
    import logging

    from conftest import local_client
    from test_live import _app_with_fakes, _safety_session_with_fake

    monkeypatch.setenv("ANALYZER_ALLOW_FILE_SOURCES", "1")
    with local_client(_app_with_fakes(tmp_path)) as c:
        sess, sid = _safety_session_with_fake(c, monkeypatch)
        src_id, prof_id = sess.source_id, sess.profile_id
        prof = c.get(f"/api/v1/live/sessions/{sid}").json()["profile"]
        mine = {**prof, "safety": {**prof["safety"], "areas": [_area()]}}
        assert c.put(f"/api/v1/live/sessions/{sid}/profile?save=true", json=mine).status_code == 200
        c.delete(f"/api/v1/live/sessions/{sid}")
        f = tmp_path / "live" / "camera_profiles.json"
        items = json.loads(f.read_text(encoding="utf-8"))
        (key,) = items
        items[key]["safety"]["areas"] = [_area(points=SQUARE[:2])]
        f.write_text(json.dumps(items), encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            r = c.post("/api/v1/live/sessions", json={"sourceId": src_id, "profileId": prof_id})
        assert r.status_code == 201, r.text
        assert "areas" not in r.json()["profile"]["safety"]                # şablon: bütün kare
        assert "Kameranın kayıtlı ayarı okunamadı" in caplog.text and "yeniden kaydedin" in caplog.text
        sid = r.json()["id"]
        assert c.put(f"/api/v1/live/sessions/{sid}/profile?save=true", json=mine).status_code == 200
        c.delete(f"/api/v1/live/sessions/{sid}")
        r = c.post("/api/v1/live/sessions", json={"sourceId": src_id, "profileId": prof_id})
        assert r.status_code == 201 and r.json()["profile"]["safety"]["areas"] == [_area()]


# ---------------------------------------------------------------- area_rules

def test_area_rules_without_areas_is_none() -> None:
    assert area_rules((0.4, 0.4, 0.6, 0.6), []) is None


def test_area_rules_centre_inside_and_outside() -> None:
    areas = [SafetyArea("Masa 3", SQUARE, ["phone"])]
    assert area_rules((0.4, 0.4, 0.6, 0.6), areas) == ({"phone"}, {"phone": "Masa 3"})
    assert area_rules((0.0, 0.0, 0.1, 0.1), areas) == (set(), {})
    # kutu alana taşsa da merkezi dışarıdaysa alanda değildir; merkez içerideyse kutu taşsa da alandadır
    assert area_rules((0.0, 0.2, 0.5, 0.3), areas) == (set(), {})
    assert area_rules((0.2, 0.2, 0.9, 0.9), areas) == ({"phone"}, {"phone": "Masa 3"})


def test_area_rules_union_in_overlap_first_area_wins() -> None:
    a = SafetyArea("A", [(0.0, 0.0), (0.6, 0.0), (0.6, 0.6), (0.0, 0.6)], ["handsUp", "phone"])
    b = SafetyArea("B", [(0.4, 0.4), (1.0, 0.4), (1.0, 1.0), (0.4, 1.0)], ["phone", "lying"])
    assert area_rules((0.45, 0.45, 0.55, 0.55), [a, b]) == (
        {"handsUp", "phone", "lying"}, {"handsUp": "A", "phone": "A", "lying": "B"})
    assert area_rules((0.45, 0.45, 0.55, 0.55), [b, a]) == (
        {"handsUp", "phone", "lying"}, {"handsUp": "A", "phone": "B", "lying": "B"})
    assert area_rules((0.8, 0.8, 0.9, 0.9), [a, b]) == ({"phone", "lying"}, {"phone": "B", "lying": "B"})


# ---------------------------------------------------------------- çözümleyici

def _profile(areas: list[SafetyArea], phone: bool = True) -> Profile:
    p = Profile.jeweler()
    p.safety.handsUp.enabled = True
    p.safety.phone.enabled = phone
    p.safety.phone.seconds = 10.0
    p.safety.areas = areas
    return p


def _analyzer(phones: list[tuple[float, float, float, float, float]] | None = None
              ) -> tuple[SafetyAnalyzer, FakePhoneDetector, FakePose]:
    det = FakePhoneDetector([PERSON], phones=[PHONE_AT_WRIST] if phones is None else phones)
    pose = FakePose(hands_up_kp())
    return SafetyAnalyzer(detector=det, pose=pose), det, pose


def _feed(an: SafetyAnalyzer, p: Profile, start: int, stop: int, fps: float = 10.0) -> list[SafetyResult]:
    return [an.process(FRAME, p, fps, k / fps) for k in range(start, stop)]


def test_person_outside_every_area_is_ignored() -> None:
    p = _profile([SafetyArea("Köşe", CORNER, ["handsUp", "lying", "phone"])])
    an, det, pose = _analyzer()
    res = _feed(an, p, 0, 150)
    assert not any(r.fired or r.active or r.tracks or r.poses for r in res)
    assert pose.calls == 0 and det.phone_calls == 0               # poz ve telefon araması hiç yapılmaz


def test_without_areas_whole_frame_and_area_is_none() -> None:
    an, _det, _pose = _analyzer(phones=[])
    fired = [a for r in _feed(an, _profile([]), 0, 50) for a in r.fired]
    assert [(a.kind, a.area) for a in fired] == [("hands_up", None)]


def test_area_rules_limit_alarms_to_allowed_rules() -> None:
    """`rules: ["phone"]` olan alandaki kişi eller yukarıdayken telefon alarmı üretir, eller yukarı üretmez."""
    p = _profile([SafetyArea("Masa 3", SQUARE, ["phone"])])
    an, _det, _pose = _analyzer()
    res = _feed(an, p, 0, 130)
    fired = [a for r in res for a in r.fired]
    assert [(a.kind, a.area) for a in fired] == [("phone", "Masa 3")]
    assert not any(a[1] == "hands_up" for r in res for a in r.active)
    assert all(len(r.tracks) == 1 for r in res if r.tracks) and any(r.poses for r in res)


def test_area_without_phone_rule_never_searches_phones() -> None:
    """Kamerada telefon açık ama kişinin alanı yalnız eller yukarıya izin veriyor: kırpıntıda telefon hiç aranmaz."""
    p = _profile([SafetyArea("Kasa", SQUARE, ["handsUp"])])
    an, det, _pose = _analyzer()
    fired = [a for r in _feed(an, p, 0, 130) for a in r.fired]
    assert det.phone_calls == 0
    assert [(a.kind, a.area) for a in fired] == [("hands_up", "Kasa")]


def test_person_walking_out_of_area_ends_episode_without_alarm() -> None:
    """Kişi süre dolmadan alandan çıkar: iz sonuçtan düşer, bölüm biter, sonradan alarm doğmaz."""
    p = _profile([SafetyArea("Kasa", SQUARE, ["handsUp"])], phone=False)
    an, det, _pose = _analyzer(phones=[])
    inside = _feed(an, p, 0, 20)                                     # 2 sn eller yukarı (eşik 3 sn)
    assert any(a[1] == "hands_up" for a in inside[-1].active)
    det.boxes = [(20, 20, 100, 100)]                                # merkez (0,09, 0,125): alanın dışında
    out = _feed(an, p, 20, 80)
    assert not any(r.fired for r in inside + out)
    assert any(k == "hands_up" for r in out for _t, k, _f in r.ended)
    assert not out[-1].active and not out[-1].tracks and not out[-1].poses


def test_alarm_area_is_first_area_with_that_rule() -> None:
    p = _profile([SafetyArea("Kapı", CORNER, ["handsUp"]), SafetyArea("Telefon", SQUARE, ["phone"]),
                  SafetyArea("Kasa", SQUARE, ["handsUp", "phone"])], phone=False)
    an, _det, _pose = _analyzer(phones=[])
    fired = [a for r in _feed(an, p, 0, 50) for a in r.fired]
    assert [(a.kind, a.area) for a in fired] == [("hands_up", "Kasa")]


def test_episode_ends_when_rule_no_longer_allowed() -> None:
    """Kişinin alanı artık eller yukarıya izin vermezse bölüm, görünmeyen kişininki gibi tolerans dolunca biter."""
    p = _profile([SafetyArea("Kasa", SQUARE, ["handsUp"])], phone=False)
    an, _det, _pose = _analyzer(phones=[])
    first = _feed(an, p, 0, 20)
    assert any(a[1] == "hands_up" for a in first[-1].active)
    p.safety.areas = [SafetyArea("Kasa", SQUARE, ["lying"])]
    rest = _feed(an, p, 20, 60)
    assert not any(r.fired for r in first + rest)
    assert any(k == "hands_up" and not f for r in rest for _t, k, f in r.ended)
    assert not any(a[1] == "hands_up" for a in rest[-1].active)
    assert rest[-1].tracks                                          # kişi alanda: görünmeye devam eder


# ---------------------------------------------------------------- alarm kaydı ve Telegram

def test_alarm_record_keeps_area(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    a = st.add("s", "Tezgah", "phone", 1.0, 2.0, None, "disabled", area="Masa 3")
    assert a["area"] == "Masa 3"
    assert AlarmStore(tmp_path).get(a["id"])["area"] == "Masa 3"     # type: ignore[index]
    assert st.add("s", "Tezgah", "test", 1.0, 2.0, None, "disabled")["area"] is None
    for bad in ("", "   ", "a" * 41, 5, ["Masa"]):
        assert st.add("s", "Tezgah", "phone", 1.0, 2.0, None, "disabled", area=bad)["area"] is None  # type: ignore[arg-type]


def test_old_alarm_record_without_area_reads_none(tmp_path: pathlib.Path) -> None:
    (tmp_path / "live").mkdir(parents=True, exist_ok=True)
    recs = [{"id": "a" * 32, "firedAt": 1.0, "type": "phone"}, {"id": "b" * 32, "firedAt": 1.0, "area": 7},
            {"id": "c" * 32, "firedAt": 1.0, "area": "Kasa"}]
    (tmp_path / "live" / "alarms.json").write_text(json.dumps(recs), encoding="utf-8")
    st = AlarmStore(tmp_path)
    assert [st.get(i)["area"] for i in ("a" * 32, "b" * 32, "c" * 32)] == [None, None, "Kasa"]  # type: ignore[index]


def test_alarm_area_reaches_record_and_telegram_text(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("fastapi")
    from types import SimpleNamespace

    from conftest import local_client

    from bantvision.analyzer import Settings, create_app

    with local_client(create_app(Settings(data_dir=tmp_path))) as client:
        mgr = client.app.state.live
        sent: list[str] = []
        monkeypatch.setattr(mgr.notifier, "configured", lambda: True)
        monkeypatch.setattr(mgr.notifier, "enqueue", lambda _id, text, _jpeg: sent.append(text))
        s = SimpleNamespace(id="x", name="Tezgah", profile=Profile.jeweler(), source_id="src", channel_id=None)
        (aid,) = mgr.on_alarm(s, [SafetyAlarm("phone", 1, (0.1, 0.1, 0.3, 0.9), 50.0, 60.0, area="Masa 3")], [], None)
        (bid,) = mgr.on_alarm(s, [SafetyAlarm("lying", 2, (0.1, 0.1, 0.3, 0.9), 50.0, 60.0)], [], None)
        assert mgr.alarms.get(aid)["area"] == "Masa 3" and mgr.alarms.get(bid)["area"] is None
        assert sent[0].startswith("🚨 TELEFON KULLANIMI — Tezgah · Alan: Masa 3 · ")
        assert sent[1].startswith("🚨 YERDE YATAN KİŞİ — Tezgah · ") and "Alan" not in sent[1]


# ---------------------------------------------------------------- çizim

BOX_IN = (0.4, 0.4, 0.6, 0.7)                   # merkez SQUARE içinde
BOX_OUT = (0.02, 0.02, 0.12, 0.18)              # merkez SQUARE dışında


def _track(i: int, box: tuple[float, float, float, float]) -> MotTrack:
    b = np.array(box, np.float64)
    return MotTrack(id=i, box=b, vel=np.zeros(4), last=b, score=0.9)


def _kp(box: tuple[float, float, float, float], w: int = 640, h: int = 360) -> np.ndarray:
    """Kutunun ortasında dikey bir gövde (omuz–kalça) ve kollar: iskelet çizgileri kutu içinde."""
    x1, y1, x2, y2 = box[0] * w, box[1] * h, box[2] * w, box[3] * h
    cx, top, bot = (x1 + x2) / 2, y1 + (y2 - y1) * 0.25, y1 + (y2 - y1) * 0.6
    kp = np.zeros((17, 3))
    for i, (x, y) in {5: (cx - 10, top), 6: (cx + 10, top), 11: (cx - 8, bot), 12: (cx + 8, bot)}.items():
        kp[i] = (x, y, 0.9)
    return kp


def test_tags_skip_people_outside_areas() -> None:
    p = _profile([SafetyArea("Masa 3", SQUARE, ["phone"])])
    r = SafetyResult(tracks=[_track(1, BOX_IN), _track(2, BOX_OUT)])
    assert safety_tags(p, r) == [SafetyTag(BOX_IN, "person", "Kişi", None)]
    # alan yoksa herkes
    assert len(safety_tags(_profile([]), r)) == 2


def test_counting_only_for_rules_allowed_in_area() -> None:
    p = _profile([SafetyArea("Masa 3", SQUARE, ["phone"])])
    r = SafetyResult(tracks=[_track(1, BOX_IN)], active=[(1, "hands_up", 2.0, False)])
    assert safety_tags(p, r) == [SafetyTag(BOX_IN, "person", "Kişi", None)]


def test_area_tags_count_people_by_box_centre() -> None:
    p = _profile([SafetyArea("Masa 3", SQUARE, ["phone"]), SafetyArea("Köşe", CORNER, ["handsUp"])])
    r = SafetyResult(tracks=[_track(1, BOX_IN), _track(2, (0.25, 0.25, 0.45, 0.45))])   # 2: merkez (0,35, 0,35)
    assert area_tags(p, r) == [AreaTag("Masa 3", tuple(SQUARE), "Masa 3: 2", False),
                               AreaTag("Köşe", tuple(CORNER), "Köşe: 0", False)]
    assert area_tags(_profile([]), r) == []


def test_draw_safety_draws_area_blue_and_hides_outside_person() -> None:
    p = _profile([SafetyArea("Masa 3", SQUARE, ["phone"])])
    r = SafetyResult(tracks=[_track(1, BOX_IN), _track(2, BOX_OUT)], poses={1: _kp(BOX_IN), 2: _kp(BOX_OUT)})
    img = draw_safety(np.zeros((360, 640, 3), np.uint8), p, r)
    from bantvision.overlay import AREA

    edge_x = int(0.7 * 640)                                         # alanın sağ kenarı, kutulardan uzakta
    assert AREA in {tuple(int(v) for v in img[250, x]) for x in range(edge_x - 2, edge_x + 3)}
    out = img[int(0.02 * 360):int(0.18 * 360) + 2, int(0.02 * 640) - 2:int(0.12 * 640) + 3]
    assert not out.any()                                           # alan dışındaki kişi: ne kutu ne iskelet
    inside = img[int(0.4 * 360):int(0.7 * 360), int(0.4 * 640):int(0.6 * 640)]
    b, g, red = inside[..., 0].astype(int), inside[..., 1].astype(int), inside[..., 2].astype(int)
    assert ((b > 150) & (g > 150) & (red < 80)).any()              # alandaki kişinin iskeleti (CYAN) çizilir
    assert CYAN == (255, 255, 0)


def test_clip_frames_keep_area_outlines_when_nobody_is_inside() -> None:
    """Olay kaydı: alanı olan profilde "kişi yok" sonucu da kareye eşlenir; alanlar (sayı 0) çizilir, önceki karenin
    iskeleti gelmez. Alansız profilde eski davranış: işaretsiz kare."""
    from bantvision.live import clips
    from bantvision.overlay import AREA

    p = _profile([SafetyArea("Masa 3", SQUARE, ["phone"])])
    busy = clips.ClipOverlay.from_result(SafetyResult(tracks=[_track(1, BOX_IN)], poses={1: _kp(BOX_IN)}),
                                         (360, 640, 3), p)
    nobody = clips.ClipOverlay.from_result(SafetyResult(), (360, 640, 3), p)
    assert not nobody.empty
    frames = [(0.0, 0.0, b"", None), (0.5, 0.5, b"", None)]
    matched = clips._match(frames, [(0.0, busy), (0.5, nobody)])
    assert matched[0][3] is busy and matched[1][3] is nobody
    img = clips.annotate(np.zeros((360, 640, 3), np.uint8), matched[1][3])
    edge_x = int(0.7 * 640)
    assert AREA in {tuple(int(v) for v in img[250, x]) for x in range(edge_x - 2, edge_x + 3)}
    inside = img[int(0.45 * 360):int(0.65 * 360), int(0.42 * 640):int(0.58 * 640)]
    assert not inside.any()                                         # iskelet ya da kişi kutusu yok
    plain = clips.ClipOverlay.from_result(SafetyResult(), (360, 640, 3), _profile([]))
    assert plain.empty and clips._match(frames[1:], [(0.5, plain)])[0][3] is None


def test_area_with_active_alarm_drawn_red() -> None:
    p = _profile([SafetyArea("Masa 3", SQUARE, ["phone"]), SafetyArea("Köşe", CORNER, ["phone"])])
    r = SafetyResult(tracks=[_track(1, BOX_IN)], active=[(1, "phone", 30.0, True)])
    tags = area_tags(p, r)
    assert [(t.name, t.text, t.alarm) for t in tags] == [("Masa 3", "Masa 3: 1", True), ("Köşe", "Köşe: 0", False)]
    gone = SafetyResult(active=[(1, "phone", 30.0, True)], boxes={1: BOX_IN})   # alarmlı kişi bu karede görülmedi
    assert [t.alarm for t in area_tags(p, gone)] == [True, False]
    img = draw_safety(np.zeros((360, 640, 3), np.uint8), p, r)
    edge_x = int(0.7 * 640)
    row = [tuple(int(v) for v in img[250, x]) for x in range(edge_x - 4, edge_x + 5)]
    assert sum(c == RED for c in row) >= 2                          # kalın kırmızı kenar
    corner_edge = [tuple(int(v) for v in img[30, x]) for x in range(int(0.2 * 640) - 3, int(0.2 * 640) + 4)]
    assert RED not in corner_edge                                   # alarmsız alan mavi kalır
