"""Poz güvenlik alarmı doğruluğu (kabul: tür başına ≥ %95 yakalama, kamera başına 8 saatte ≤ 1 yanlış alarm).

İki kullanım:
- Tek video: python tools/eval_pose.py VIDEO --profile PROFİL.json --labels VIDEO.pose.json [--every N]
- Manifest (birden çok kayıt, birden çok kamera): python tools/eval_pose.py --manifest MANIFEST.json [--every N]

Etiket: [{"t": saniye, "type": "hands_up"|"lying", "end": saniye (isteğe bağlı)}] — olayın başladığı an (`t`) ve
istenirse bittiği an (`end`). Alarm, aynı türde t ile t + süre + 2 sn arasında gelirse yakalanmış sayılır (sınır dahil);
her alarm en çok bir etikete eşlenir. Bir etiket yakalandıktan sonra AYNI olayın içinde gelen aynı türdeki başka
alarmlar `tekrar` sayılır: ayrı yazılır, yanlış alarm değildir ve kapıyı etkilemez. Olay `end` varsa t'den end + 2 sn'ye,
yoksa t'den t + süre + 2 + 10 sn'ye kadar sürer. Yakalanmamış bir etiketin yakınındaki alarm (geç gelen) ve hiçbir
olaya ait olmayan alarm yanlış alarmdır.

Manifest: [{"video": "yol", "labels": "yol", "profile": "yol", "camera": "ad (isteğe bağlı)"}]; yollar manifest
dosyasının klasörüne göredir. Kamera adı yoksa video dosyasının adıdır. Yakalama tüm kayıtlar toplanarak tür başına
hesaplanır. Yanlış alarm KAMERA BAŞINA hesaplanır (aynı kameranın kayıtlarında yanlış alarm ve saatler toplanır, 8 saate
çevrilir): HER kameranın kayıtları birlikte en az 1 saat sürmeli ve 8 saatte ≤ 1 yanlış alarm olmalı; kamera tablosu
yazılır. 1 saatten kısa bir kamera sonucu KALDI yapar ("yetersiz süre: <kamera> <dk> dk (en az 60 dk)"); süreler
kameralar arasında toplanmaz. Tek video kipinde video en az 1 saat olmalı. Her kaydın etiket/profil/video girdisi hiçbir
video işlenmeden önce denetlenir.

Profil: güvenlik (`countMode = "safety"`) profili JSON'u; web panelinde kameranın kayıtlı ayarı
(<ANALYZER_DATA_DIR>/live/camera_profiles.json içindeki ilgili kaydın kendisi) ya da GET /api/v1/live/sessions/{id}
yanıtı (içindeki "profile" alınır). Bu araç Python/web yolunu ölçer: video canlıdaki gibi `Pipeline` ile işlenir, yalnızca
boş sahnede tanıma atlama açık değildir (her işlenen karede tanıma). `--every N`: her N. kare işlenir (canlıda yoğun
yükte kare atlamayı taklit eder); zaman ve kare hızı kare zaman damgalarından gelir, bu yüzden doğru çalışır.
Çıkış kodu: 0 geçti, 1 kaldı, 2 girdi hatası (etiket/profil/manifest/video). Kayıtlar kullanıcınındır; repoya konmaz.
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
MIN_HOURS = 1.0                 # normal hareket kaydı en az bu kadar saat (tek videoda video, manifestte HER kamera)
MAX_FALSE_PER_8H = 1.0
TOLERANCE_S = 2.0
EVENT_EXTRA_S = 10.0            # `end` yokken olay, yakalama penceresinin bitiminden bu kadar daha sürer
KINDS = ("hands_up", "lying")
NAMES = {"hands_up": "Eller yukarı", "lying": "Yerde yatan kişi"}
LABEL_FORMAT = '[{"t": saniye, "type": "hands_up"|"lying", "end": saniye (isteğe bağlı)}]'
MANIFEST_FORMAT = '[{"video": "yol", "labels": "yol", "profile": "yol", "camera": "ad (isteğe bağlı)"}]'
MANIFEST_KEYS = ("video", "labels", "profile", "camera")
TEKRAR = "Tekrar (aynı olayın içinde, yanlış alarm sayılmaz)"


class InputError(Exception):
    """Ölçüme başlanamaz (etiket/profil/manifest/video); ileti kullanıcıya gösterilir."""


def event_end(lab: dict, seconds: float, tol: float = TOLERANCE_S) -> float:
    """Olayın son anı: `end` varsa end + tol, yoksa t + kural süresi + tol + `EVENT_EXTRA_S`."""
    end = lab.get("end")
    return end + tol if end is not None else lab["t"] + seconds + tol + EVENT_EXTRA_S


def match_pose(labels: list[dict], alarms: list[tuple[float, str]], seconds: dict[str, float],
               tol: float = TOLERANCE_S) -> dict:
    """Etiketleri alarmlara eşler: aynı tür, `t ≤ alarm ≤ t + seconds[tür] + tol`; her alarm en çok bir etikete.
    Önce bütün etiketler yakalanır; sonra yakalanan etiketlerin olayı içinde kalan aynı türdeki kullanılmamış alarmlar
    `repeat` olur (ayrı sayılır, yanlış alarm değil). Geriye kalanlar yanlış alarmdır."""
    alarms = sorted(alarms)                                    # sıra bağımsız: en erken uygun alarm eşlenir
    used: set[int] = set()
    r: dict = {"hands_up": {"labels": 0, "caught": 0}, "lying": {"labels": 0, "caught": 0}, "false": 0,
               "repeat": 0, "hours": 0.0}
    caught: list[dict] = []
    for lab in sorted(labels, key=lambda x: x["t"]):
        kind = lab["type"]
        r[kind]["labels"] += 1
        for k, (ts, ak) in enumerate(alarms):
            if k not in used and ak == kind and lab["t"] <= ts <= lab["t"] + seconds[kind] + tol:
                used.add(k)
                r[kind]["caught"] += 1
                caught.append(lab)
                break
    for lab in caught:                                         # olay içi tekrar: yakalamalar bittikten SONRA
        last = event_end(lab, seconds[lab["type"]], tol)
        for k, (ts, ak) in enumerate(alarms):
            if k not in used and ak == lab["type"] and lab["t"] <= ts <= last:
                used.add(k)
                r["repeat"] += 1
    r["false"] = len(alarms) - len(used)
    return r


def aggregate(parts: list[tuple[str, dict]]) -> dict:
    """Kayıtların `match_pose` sonuçlarını (kamera adı, sonuç + `hours`) birleştirir: yakalama ve tekrar tüm kayıtlardan
    toplanır; yanlış alarm ve saat KAMERA BAŞINA toplanır (`cameras`, ilk görülme sırasıyla)."""
    r: dict = {"hands_up": {"labels": 0, "caught": 0}, "lying": {"labels": 0, "caught": 0}, "false": 0,
               "repeat": 0, "hours": 0.0, "cameras": {}}
    for camera, p in parts:
        for kind in KINDS:
            r[kind]["labels"] += p[kind]["labels"]
            r[kind]["caught"] += p[kind]["caught"]
        r["false"] += p["false"]
        r["repeat"] += p.get("repeat", 0)
        r["hours"] += p["hours"]
        c = r["cameras"].setdefault(camera, {"false": 0, "hours": 0.0})
        c["false"] += p["false"]
        c["hours"] += p["hours"]
    return r


def check_labels(labels: Any) -> list[dict]:
    """Etiket dosyasının içeriğini doğrular; geçersizse hangi kaydın neden geçersiz olduğunu Türkçe söyler."""
    if not isinstance(labels, list):
        raise InputError(f"Etiket dosyası geçersiz: {LABEL_FORMAT} biçiminde bir liste olmalı.")
    for i, lab in enumerate(labels, 1):
        if not isinstance(lab, dict):
            raise InputError(f"Etiket dosyası geçersiz: {i}. kayıt bir nesne değil; {LABEL_FORMAT} olmalı.")
        t, kind, end = lab.get("t"), lab.get("type"), lab.get("end")
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0:
            raise InputError(f"Etiket dosyası geçersiz: {i}. kaydın zamanı (t) 0 ya da daha büyük bir sayı "
                             "(saniye) olmalı.")
        if not isinstance(kind, str) or kind not in KINDS:
            raise InputError(f"Etiket dosyası geçersiz: {i}. kaydın türü (type) \"hands_up\" ya da \"lying\" "
                             f"olmalı; bulunan: {kind!r}.")
        if end is not None and (isinstance(end, bool) or not isinstance(end, (int, float))
                                or not math.isfinite(end) or end < t):
            raise InputError(f"Etiket dosyası geçersiz: {i}. kaydın bitişi (end) başlangıçtan (t) küçük olmayan bir "
                             "sayı (saniye) olmalı; olay bitiş zamanı bilinmiyorsa yazılmamalı.")
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


def check_manifest(data: Any, base: pathlib.Path) -> list[dict[str, str]]:
    """Manifest içeriğini doğrular; yollar `base`'e (manifestin klasörü) göre çözülür. Her kayıt: video, labels, profile
    (çözülmüş yollar), camera, name (iletilerde: videonun manifestte yazıldığı hali)."""
    if not isinstance(data, list) or not data:
        raise InputError(f"Manifest geçersiz: {MANIFEST_FORMAT} biçiminde, boş olmayan bir liste olmalı.")
    out: list[dict[str, str]] = []
    for i, e in enumerate(data, 1):
        if not isinstance(e, dict):
            raise InputError(f"Manifest geçersiz: {i}. kayıt bir nesne değil; {MANIFEST_FORMAT} olmalı.")
        unknown = sorted(set(e) - set(MANIFEST_KEYS))
        if unknown:
            raise InputError(f"Manifest geçersiz: {i}. kayıtta bilinmeyen alan: {', '.join(unknown)} "
                             f"(izin verilenler: {', '.join(MANIFEST_KEYS)}).")
        for key in ("video", "labels", "profile"):
            v = e.get(key)
            if not isinstance(v, str) or not v.strip():
                raise InputError(f"Manifest geçersiz: {i}. kayıtta \"{key}\" (dosya yolu) eksik ya da boş; "
                                 f"{MANIFEST_FORMAT} olmalı.")
        cam = e.get("camera")
        if cam is not None and (not isinstance(cam, str) or not cam.strip()):
            raise InputError(f"Manifest geçersiz: {i}. kayıtta \"camera\" boş olmayan bir metin (kamera adı) olmalı "
                             "ya da hiç yazılmamalı.")
        out.append({"video": str(base / e["video"]), "labels": str(base / e["labels"]),
                    "profile": str(base / e["profile"]), "name": e["video"],
                    "camera": cam.strip() if cam else pathlib.Path(e["video"]).name})
    return out


def read_manifest(path: str) -> list[dict[str, str]]:
    p = pathlib.Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise InputError(f"Manifest dosyası okunamadı: {e}") from e
    return check_manifest(data, p.resolve().parent)


def warn_disabled_rules(profile: Any, labels: list[dict], prefix: str = "") -> None:
    for kind, rule in (("hands_up", profile.safety.handsUp), ("lying", profile.safety.lying)):
        if not rule.enabled and any(lab["type"] == kind for lab in labels):
            print(f"UYARI: {prefix}profilde {NAMES[kind]} kuralı kapalı; bu türdeki etiketler yakalanamaz.",
                  file=sys.stderr)


def evaluate_manifest(entries: list[dict[str, str]], every: int) -> dict:
    """Önce her kaydın etiket/profil/video girdisi denetlenir (saatlerce video işledikten sonra sondaki kaydın bozuk
    çıkması boşa gitmesin), sonra videolar sırayla işlenir ve sonuçlar `aggregate` ile birleştirilir."""
    prepared = []
    for i, e in enumerate(entries, 1):
        where = f"Manifest {i}. kayıt ({e['name']})"
        try:
            labels = read_labels(e["labels"])
            profile = load_profile(e["profile"])
        except InputError as err:
            raise InputError(f"{where}: {err}") from err
        if not pathlib.Path(e["video"]).is_file():
            raise InputError(f"{where}: video bulunamadı.")
        warn_disabled_rules(profile, labels, f"{e['name']}: ")
        prepared.append((e, labels, profile))
    parts: list[tuple[str, dict]] = []
    for i, (e, labels, profile) in enumerate(prepared, 1):
        print(f"[{i}/{len(prepared)}] {e['name']} işleniyor…", file=sys.stderr, flush=True)
        try:
            alarms, hours, seconds = run(e["video"], profile, every)
        except InputError as err:
            raise InputError(f"Manifest {i}. kayıt ({e['name']}): {err}") from err
        r = match_pose(labels, alarms, seconds)
        r["hours"] = hours
        parts.append((e["camera"], r))
    return aggregate(parts)


def duration_text(hours: float) -> str:
    """1 saatten kısa süre dakikayla (aşağı yuvarlanır: 59,6 dk "60 dk" olmaz), uzunu saatle."""
    return f"{hours:.2f} saat" if hours >= MIN_HOURS else f"{math.floor(hours * 60)} dk"


def report_cameras(r: dict) -> bool:
    """Manifest: kamera tablosu ve yanlış alarm kapısı. Geçerse True: HER kamera en az 1 saat videoya sahip ve 8 saatte
    ≤ 1 yanlış alarmda. 1 saatten kısa kamera KALDI yapar (süreler kameralar arasında toplanmaz)."""
    cams: dict[str, dict] = r["cameras"]
    width = max(len(name) for name in cams)
    print(f"Kamera başına yanlış alarm (sınır: 8 saatte en çok {MAX_FALSE_PER_8H:g}; her kamera en az {MIN_HOURS:.0f} saat):")
    ok = True
    short: list[str] = []
    for name, c in cams.items():
        h, n = c["hours"], c["false"]
        head = f"  {name:<{width}}  {duration_text(h):>10}  {n:>3} yanlış alarm"
        if h < MIN_HOURS:
            ok = False
            short.append(f"yetersiz süre: {name} {math.floor(h * 60)} dk (en az {math.floor(MIN_HOURS * 60)} dk)")
            print(f"{head}  yetersiz süre  KALDI")
            continue
        per8 = n / h * 8
        passed = per8 <= MAX_FALSE_PER_8H
        ok &= passed
        print(f"{head}  ({per8:.2f} / 8 saat)  {'geçti' if passed else 'KALDI'}")
    for line in short:
        print(line)
    return ok


def report(r: dict) -> bool:
    """Sonucu Türkçe yazar; kabul ölçütleri tutuyorsa True. `r` kamera tablosu (`cameras`, manifest) taşıyorsa yanlış
    alarm kamera başına sınanır; taşımıyorsa (tek video) videonun tamamı tek kameradır."""
    ok = True
    for kind in KINDS:
        n, c = r[kind]["labels"], r[kind]["caught"]
        enough = n >= MIN_LABELS
        passed = enough and 100 * c >= CAPTURE_MIN_PCT * n
        ok &= passed
        print(f"{NAMES[kind]}: %{100 * c / n if n else 0.0:.1f} ({c}/{n})"
              f"{'' if enough else f' — en az {MIN_LABELS} etiket gerekli'}")
    if "cameras" in r:
        ok &= report_cameras(r)
    else:
        hours = r["hours"]
        if hours >= MIN_HOURS:
            per8 = r["false"] / hours * 8
            print(f"Yanlış alarm: {r['false']} ({per8:.2f} / 8 saat)")
            ok &= per8 <= MAX_FALSE_PER_8H
        else:
            print(f"Yanlış alarm: {r['false']} — yetersiz süre: video {math.floor(hours * 60)} dk, "
                  f"en az {MIN_HOURS:.0f} saat normal hareket gerekli")
            ok = False
    if r.get("repeat"):
        print(f"{TEKRAR}: {r['repeat']}")
    print("GEÇTİ" if ok else "KALDI")
    return ok


def evaluate_single(a: argparse.Namespace, every: int) -> dict:
    labels = read_labels(a.labels)
    profile = load_profile(a.profile)
    warn_disabled_rules(profile, labels)
    alarms, hours, seconds = run(a.video, profile, every)
    r = match_pose(labels, alarms, seconds)
    r["hours"] = hours
    return r


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Poz güvenlik alarmı doğruluğu (docs/03-algorithm.md §4.11)",
        usage="eval_pose.py VIDEO --profile PROFİL.json --labels ETİKET.json [--every N]\n"
              "       eval_pose.py --manifest MANIFEST.json [--every N]")
    ap.add_argument("video", nargs="?", help="tek video (--profile ve --labels ile)")
    ap.add_argument("--profile", help="güvenlik profili JSON'u (tek video)")
    ap.add_argument("--labels", help="etiket dosyası (tek video)")
    ap.add_argument("--manifest", help=f"çok kayıt, çok kamera: {MANIFEST_FORMAT}")
    ap.add_argument("--every", type=int, default=1, help="her N. kare işlenir (varsayılan 1)")
    a = ap.parse_args(argv)
    every = max(1, a.every)
    try:
        if a.manifest is not None:
            if a.video or a.profile or a.labels:
                raise InputError("--manifest ile VIDEO/--profile/--labels birlikte verilemez.")
            r = evaluate_manifest(read_manifest(a.manifest), every)
        else:
            if not a.video:
                raise InputError("VIDEO (--profile ve --labels ile) ya da --manifest gerekli.")
            for flag, v in (("--profile", a.profile), ("--labels", a.labels)):
                if not v:
                    raise InputError(f"{flag} gerekli (tek video ölçümü: VIDEO --profile PROFİL.json --labels ETİKET.json).")
            r = evaluate_single(a, every)
    except InputError as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 2
    return 0 if report(r) else 1


if __name__ == "__main__":
    raise SystemExit(main())
