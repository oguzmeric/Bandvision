"""Poz güvenlik alarmı doğruluğu (kabul: tür başına ≥ %95 yakalama, kamera başına 8 saatte ≤ 1 yanlış alarm).

Kullanım: python tools/eval_pose.py VIDEO --profile PROFİL.json --labels VIDEO.pose.json [--every N]
Etiket: [{"t": saniye, "type": "hands_up"|"lying"}] — olayın başladığı an. Alarm, aynı türde t ile t + süre + 2 sn
arasında gelirse yakalanmış sayılır (sınır dahil); her alarm en çok bir etikete eşlenir, eşleşmeyen alarmlar yanlış
alarmdır. Profil: güvenlik (`countMode = "safety"`) profili JSON'u; web panelinde kameranın kayıtlı ayarı
(<ANALYZER_DATA_DIR>/live/camera_profiles.json içindeki ilgili kaydın kendisi) ya da GET /api/v1/live/sessions/{id}
yanıtı (içindeki "profile" alınır). Bu araç Python/web yolunu ölçer: video canlıdaki gibi `Pipeline` ile işlenir, yalnızca
boş sahnede tanıma atlama açık değildir (her işlenen karede tanıma). `--every N`: her N. kare işlenir (canlıda yoğun
yükte kare atlamayı taklit eder); zaman ve kare hızı kare zaman damgalarından gelir, bu yüzden doğru çalışır.
Çıkış kodu: 0 geçti, 1 kaldı, 2 girdi hatası (etiket/profil/video). Kayıtlar kullanıcınındır; repoya konmaz.
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "edge"))

MIN_LABELS = 20                 # tür başına en az etiket
CAPTURE_MIN_PCT = 95            # tür başına yakalama (%), tam sayı karşılaştırması: 19/20 geçer
MIN_HOURS = 1.0                 # normal hareket kaydı en az bu kadar saat
MAX_FALSE_PER_8H = 1.0
TOLERANCE_S = 2.0
KINDS = ("hands_up", "lying")
NAMES = {"hands_up": "Eller yukarı", "lying": "Yerde yatan kişi"}
LABEL_FORMAT = '[{"t": saniye, "type": "hands_up"|"lying"}]'


class InputError(Exception):
    """Ölçüme başlanamaz (etiket/profil/video); ileti kullanıcıya gösterilir."""


def match_pose(labels: list[dict], alarms: list[tuple[float, str]], seconds: dict[str, float],
               tol: float = TOLERANCE_S) -> dict:
    """Etiketleri alarmlara eşler: aynı tür, `t ≤ alarm ≤ t + seconds[tür] + tol`; her alarm en çok bir etikete."""
    alarms = sorted(alarms)                                    # sıra bağımsız: en erken uygun alarm eşlenir
    used: set[int] = set()
    r: dict = {"hands_up": {"labels": 0, "caught": 0}, "lying": {"labels": 0, "caught": 0}, "false": 0, "hours": 0.0}
    for lab in sorted(labels, key=lambda x: x["t"]):
        kind = lab["type"]
        r[kind]["labels"] += 1
        for k, (ts, ak) in enumerate(alarms):
            if k not in used and ak == kind and lab["t"] <= ts <= lab["t"] + seconds[kind] + tol:
                used.add(k)
                r[kind]["caught"] += 1
                break
    r["false"] = len(alarms) - len(used)
    return r


def check_labels(labels: Any) -> list[dict]:
    """Etiket dosyasının içeriğini doğrular; geçersizse hangi kaydın neden geçersiz olduğunu Türkçe söyler."""
    if not isinstance(labels, list):
        raise InputError(f"Etiket dosyası geçersiz: {LABEL_FORMAT} biçiminde bir liste olmalı.")
    for i, lab in enumerate(labels, 1):
        if not isinstance(lab, dict):
            raise InputError(f"Etiket dosyası geçersiz: {i}. kayıt bir nesne değil; {LABEL_FORMAT} olmalı.")
        t, kind = lab.get("t"), lab.get("type")
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0:
            raise InputError(f"Etiket dosyası geçersiz: {i}. kaydın zamanı (t) 0 ya da daha büyük bir sayı "
                             "(saniye) olmalı.")
        if not isinstance(kind, str) or kind not in KINDS:
            raise InputError(f"Etiket dosyası geçersiz: {i}. kaydın türü (type) \"hands_up\" ya da \"lying\" "
                             f"olmalı; bulunan: {kind!r}.")
    return labels


def read_labels(path: str) -> list[dict]:
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:                         # UnicodeDecodeError da ValueError'dır
        raise InputError(f"Etiket dosyası okunamadı: {e}") from e
    return check_labels(data)


def load_profile(path: str) -> Any:
    """Düz güvenlik profili ya da oturum görünümü (`profile`); güvenlik yöntemi değilse ölçüm anlamsızdır."""
    from bantvision.core import Profile

    try:
        d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise InputError(f"Profil dosyası okunamadı: {e}") from e
    if isinstance(d, dict) and "countMode" not in d and isinstance(d.get("profile"), dict):
        d = d["profile"]
    if not isinstance(d, dict):
        raise InputError("Profil geçersiz: JSON nesnesi olmalı.")
    try:
        p = Profile.from_dict(d)
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise InputError(f"Profil geçersiz: {e}") from e
    if p.countMode != "safety":
        raise InputError("Profil güvenlik (safety) yöntemi olmalı: web panelinde güvenlik kamerasının kayıtlı ayarı "
                         "ya da oturum yanıtındaki 'profile' verilir (camera_profiles.json'da tek kameranın kaydı).")
    return p


def run(video: str, profile: Any, every: int = 1) -> tuple[list[tuple[float, str]], float, dict[str, float]]:
    """Videoyu işler (her N. kare); (alarmlar [(video saniyesi, tür)], video süresi saat, tür başına kural süresi)."""
    import cv2

    from bantvision.core import Pipeline

    cap = cv2.VideoCapture(video)
    try:
        if not cap.isOpened():
            raise InputError(f"Video açılamadı: {video}")
        pipe = Pipeline(profile)           # `SafetyAnalyzer` ilk karede tembel oluşur (tanıma + poz modeli eşzamanlı yüklenir)
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not fps > 0:                    # 0, negatif ya da NaN: akış kare hızı bildirmiyor
            fps = 25.0
        alarms: list[tuple[float, str]] = []
        k = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if k % every == 0:
                r = pipe.process(frame, k / fps)
                if r.safety is not None:
                    alarms += [(a.ts, a.kind) for a in r.safety.fired]
            k += 1
    finally:
        cap.release()
    seconds = {"hands_up": profile.safety.handsUp.seconds, "lying": profile.safety.lying.seconds}
    return alarms, k / fps / 3600, seconds


def report(r: dict) -> bool:
    """Sonucu Türkçe yazar; kabul ölçütleri tutuyorsa True."""
    ok = True
    for kind in KINDS:
        n, c = r[kind]["labels"], r[kind]["caught"]
        enough = n >= MIN_LABELS
        passed = enough and 100 * c >= CAPTURE_MIN_PCT * n
        ok &= passed
        print(f"{NAMES[kind]}: %{100 * c / n if n else 0.0:.1f} ({c}/{n})"
              f"{'' if enough else f' — en az {MIN_LABELS} etiket gerekli'}")
    hours = r["hours"]
    if hours >= MIN_HOURS:
        per8 = r["false"] / hours * 8
        print(f"Yanlış alarm: {r['false']} ({per8:.2f} / 8 saat)")
        ok &= per8 <= MAX_FALSE_PER_8H
    else:
        print(f"Yanlış alarm: {r['false']} — yetersiz süre: video {math.floor(hours * 60)} dk, "
              f"en az {MIN_HOURS:.0f} saat normal hareket gerekli")
        ok = False
    print("GEÇTİ" if ok else "KALDI")
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Poz güvenlik alarmı doğruluğu (docs/03-algorithm.md §4.11)")
    ap.add_argument("video")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--every", type=int, default=1, help="her N. kare işlenir (varsayılan 1)")
    a = ap.parse_args(argv)
    try:
        labels = read_labels(a.labels)
        profile = load_profile(a.profile)
        for kind, rule in (("hands_up", profile.safety.handsUp), ("lying", profile.safety.lying)):
            if not rule.enabled and any(lab["type"] == kind for lab in labels):
                print(f"UYARI: profilde {NAMES[kind]} kuralı kapalı; bu türdeki etiketler yakalanamaz.", file=sys.stderr)
        alarms, hours, seconds = run(a.video, profile, max(1, a.every))
    except InputError as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 2
    r = match_pose(labels, alarms, seconds)
    r["hours"] = hours
    return 0 if report(r) else 1


if __name__ == "__main__":
    raise SystemExit(main())
