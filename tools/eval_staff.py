"""Personel rengi doğruluğu (§4.10 eki, kabul ölçütü: her kamera açısında ≥ %95).

Kullanım:
    python tools/eval_staff.py VIDEO --profile PROFİL.json --labels VIDEO.staff.json --angle tepeden [--every N]
                               [--camera ANAHTAR]

Bu araç **Python/web yolunu** onaylar (canlı oturumdaki sayım hattı: `Pipeline`, boş sahnede tanıma atlama açık).
iPhone yolu ayrıca denetlenir: aynı videolar iPhone uygulamasının video modunda aynı profille oynatılır ve sayaçlar
(Giriş, Çıkış, Personel) etiketlerle karşılaştırılır (protokol: docs/12-durum.md "Personel rengi").

Profil (`--profile`): personel renkleri (`staffColors`) öğretilmiş kişi sayımı profili. Şunlardan biri olabilir:
- düz profil JSON'u;
- web panelinin oturum görünümü: `GET /api/v1/live/sessions/{id}` yanıtı (içindeki `profile` alınır);
- kamera başına kaydedilmiş ayarlar: `<ANALYZER_DATA_DIR>/live/camera_profiles.json` (`kaynak|kanal|profil` →
  profil). Birden çok kayıt varsa `--camera` ile anahtarın bir parçası verilir.

Etiket (`--labels`): `[{"t": saniye, "dir": "in"|"out", "staff": true|false}]` — her gerçek geçiş elle etiketlenir.
Ölçüm için sınıf başına **en az 20 etiket** (20 personel + 20 müşteri) gerekir; az ise araç ölçmeden çıkar (kod 2).

Eşleme: etiketler zaman sırasıyla, aynı yönde ±1,5 sn içindeki (sınır dahil) henüz kullanılmamış en yakın tahmine
eşlenir; tahminin personel/müşteri olması eşlemeyi etkilemez. Sonuç:
- yakalama = personel sayılan personel etiketleri / tüm personel etiketleri. Hiç tahmine eşlenmeyen (kaçan) personel
  etiketi yakalanmamış sayılır (oranı düşürür) ve ayrıca "kaçan" olarak yazılır;
- yanlış hariç tutma = personel sayılan müşteri etiketleri / tüm müşteri etiketleri. Kaçan müşteri etiketi hariç
  tutulmuş sayılmaz; sayım kaçağı olarak ayrıca yazılır (personel renginin değil sayımın hatası);
- fazla tahmin = hiçbir etikete eşlenmeyen tahminler, personel/müşteri diye ayrı yazılır.
Geçti: yakalama ≥ %95 ve yanlış hariç tutma ≤ %5. Çıkış kodu: 0 geçti, 1 kaldı, 2 girdi hatası.

`--every N`: her N. kare işlenir (canlıda yoğun yükte kare atlamayı taklit eder; varsayılan 1 = her kare).
Kayıtlar kullanıcınındır; public repoya konmaz. Görüntü kaydedilmez.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "edge"))

MIN_LABELS = 20                 # sınıf başına (personel, müşteri) en az etiket
TOLERANCE_S = 1.5
CAPTURE_MIN = 0.95
FALSE_EXCLUSION_MAX = 0.05

Pred = tuple[float, str, bool]  # (saniye, "in"|"out", personel mi)


class InputError(Exception):
    """Ölçüme başlanamaz (etiket/profil/video); ileti kullanıcıya gösterilir."""


def match(labels: list[dict[str, Any]], preds: list[Pred], tol: float = TOLERANCE_S) -> dict[str, int]:
    """Etiketleri tahminlere eşler; sınıf başına eşlenen/kaçan ve sınıfa göre fazla tahmin sayıları."""
    used: set[int] = set()
    r = {"staff": 0, "staff_ok": 0, "staff_as_customer": 0, "staff_missed": 0,
         "customer": 0, "customer_ok": 0, "customer_excluded": 0, "customer_missed": 0,
         "extra_staff": 0, "extra_customer": 0}
    for lab in sorted(labels, key=lambda x: x["t"]):
        cls = "staff" if lab["staff"] else "customer"
        r[cls] += 1
        best = None
        for k, (t, d, _) in enumerate(preds):
            if k not in used and d == lab["dir"] and abs(t - lab["t"]) <= tol and (
                    best is None or abs(t - lab["t"]) < abs(preds[best][0] - lab["t"])):
                best = k
        if best is None:
            r[f"{cls}_missed"] += 1
            continue
        used.add(best)
        predicted_staff = preds[best][2]
        if lab["staff"]:
            r["staff_ok" if predicted_staff else "staff_as_customer"] += 1
        else:
            r["customer_excluded" if predicted_staff else "customer_ok"] += 1
    for k, (_, _, staff) in enumerate(preds):
        if k not in used:
            r["extra_staff" if staff else "extra_customer"] += 1
    return r


def rates(r: dict[str, int]) -> tuple[float, float]:
    """(yakalama, yanlış hariç tutma). Kaçan personel yakalamayı düşürür; kaçan müşteri hariç tutma sayılmaz."""
    return r["staff_ok"] / max(1, r["staff"]), r["customer_excluded"] / max(1, r["customer"])


def check_labels(labels: Any) -> None:
    if not isinstance(labels, list) or not all(
            isinstance(x, dict) and isinstance(x.get("t"), (int, float)) and x.get("dir") in ("in", "out")
            and isinstance(x.get("staff"), bool) for x in labels):
        raise InputError('Etiket dosyası geçersiz: [{"t": saniye, "dir": "in"|"out", "staff": true|false}] olmalı.')
    staff = sum(1 for x in labels if x["staff"])
    customer = len(labels) - staff
    if staff < MIN_LABELS or customer < MIN_LABELS:
        raise InputError(f"Ölçüm için yetersiz etiket: {staff} personel, {customer} müşteri geçişi var; her biri için "
                         f"en az {MIN_LABELS} gerekli. Daha uzun kayıt etiketleyin.")


def load_profile(path: str, camera: str | None = None) -> Any:
    """Düz profil, oturum görünümü (`profile`) ya da camera_profiles.json (`--camera` ile seçilen kayıt)."""
    from bantvision.core import Profile

    try:
        d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise InputError(f"Profil dosyası okunamadı: {e}") from e
    if isinstance(d, dict) and "countMode" not in d and isinstance(d.get("profile"), dict):
        d = d["profile"]
    elif isinstance(d, dict) and "countMode" not in d:
        entries = {k: v for k, v in d.items() if isinstance(v, dict) and "countMode" in v
                   and (camera is None or camera in k)}
        if len(entries) != 1:
            keys = ", ".join(entries) or "yok"
            raise InputError(f"Profil seçilemedi: {len(entries)} kamera kaydı uyuyor ({keys}). "
                             "--camera ile kaynak|kanal|profil anahtarının bir parçasını verin.")
        d = next(iter(entries.values()))
    try:
        p = Profile.from_dict(d)
    except (KeyError, TypeError, ValueError) as e:
        raise InputError(f"Profil geçersiz: {e}") from e
    if p.countMode != "detect" or not p.staffColors:
        raise InputError("Profil kişi sayımı (detect) olmalı ve öğretilmiş personel rengi (staffColors) içermeli.")
    return p


def run(video: str, profile: Any, every: int = 1) -> list[Pred]:
    """Videoyu canlı oturumdaki gibi işler (boş sahnede tanıma atlanır); her N. kare."""
    import cv2

    from bantvision.core import Pipeline

    cap = cv2.VideoCapture(video)
    try:
        if not cap.isOpened():
            raise InputError(f"Video açılamadı: {video}")
        pipe = Pipeline(profile)
        pipe.detect.enable_gate()
        pipe.counting = True
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        preds: list[Pred] = []
        k = -1
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            k += 1
            if k % every:
                continue
            ts = k / fps
            r = pipe.process(frame, ts)
            preds += [(ts, "in", False)] * len(r.counts) + [(ts, "out", False)] * len(r.counts_out)
            preds += [(ts, "in" if d > 0 else "out", True) for _, d in r.staff_events]
        return preds
    finally:
        cap.release()


def report(angle: str, r: dict[str, int]) -> bool:
    cap, fx = rates(r)
    ok = cap >= CAPTURE_MIN and fx <= FALSE_EXCLUSION_MAX
    print(f"{angle}: personel yakalama %{100 * cap:.1f} ({r['staff_ok']}/{r['staff']}; müşteri sayılan "
          f"{r['staff_as_customer']}, kaçan {r['staff_missed']})")
    print(f"{angle}: yanlış hariç tutma %{100 * fx:.1f} ({r['customer_excluded']}/{r['customer']}; doğru "
          f"{r['customer_ok']}, sayım kaçağı {r['customer_missed']})")
    print(f"{angle}: fazla tahmin — personel {r['extra_staff']}, müşteri {r['extra_customer']}")
    print(f"{angle}: {'GEÇTİ' if ok else 'KALDI'} (yakalama ≥ %{100 * CAPTURE_MIN:.0f}, "
          f"yanlış hariç tutma ≤ %{100 * FALSE_EXCLUSION_MAX:.0f})")
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Personel rengi doğruluğu (§4.10 eki)")
    ap.add_argument("video")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--angle", required=True)
    ap.add_argument("--every", type=int, default=1, help="her N. kare işlenir (varsayılan 1)")
    ap.add_argument("--camera", help="camera_profiles.json'da kaydın anahtar parçası (kaynak|kanal|profil)")
    a = ap.parse_args(argv)
    try:
        if a.every < 1:
            raise InputError("--every en az 1 olmalı.")
        try:
            labels = json.loads(pathlib.Path(a.labels).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise InputError(f"Etiket dosyası okunamadı: {e}") from e
        check_labels(labels)
        profile = load_profile(a.profile, a.camera)
        preds = run(a.video, profile, a.every)
    except InputError as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 2
    return 0 if report(a.angle, match(labels, preds)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
