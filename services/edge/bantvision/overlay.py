"""Tanıma tabanlı sayım (§4.10) için video bindirmesi: Giriş · Çıkış paneli, giriş oku, kişi kutuları; poz güvenlik
iskeletleri, kişi etiketleri ve analiz alanları; yangın/duman kutuları.

Türkçe karakterler (ı, ş, ç, ğ, İ) OpenCV yazısında çıkmaz; Pillow ve sistem yazı tipiyle çizilir. Pillow ya da
yazı tipi yoksa ASCII'ye çevrilip OpenCV ile yazılır (çıktı yine okunur).
"""
from __future__ import annotations

import functools
import math
import os
import pathlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from .core.detect_count import DetectResult, side_function
from .core.fire import FireResult
from .core.fire_rules import KINDS, TRACK_IDS, Box
from .core.pose_rules import KP_CONF
from .core.profile import Profile
from .core.safety import RULE_OF_KIND, SafetyResult, area_rules, in_area

# BGR
GREEN, RED, ORANGE, WHITE, DARK = (80, 200, 60), (60, 60, 230), (0, 140, 255), (255, 255, 255), (30, 30, 30)
GRAY = (170, 170, 170)
CYAN = (255, 255, 0)                            # poz güvenlik: iskelet çizgileri
SMOKE = (200, 200, 200)                         # yangın/duman: duman kutusu (alev kutusu ORANGE)
AREA = (250, 200, 130)                          # poz güvenlik: analiz alanı (açık mavi; sarı/kırmızı etiketlerden ayrı)

_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
)
_ASCII = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


@functools.lru_cache(maxsize=16)
def _font(size: int) -> Any:
    try:
        from PIL import ImageFont
    except ImportError:
        return None
    for path in (os.environ.get("BANTVISION_FONT"), *_FONTS):
        if path and pathlib.Path(path).exists():
            return ImageFont.truetype(path, size)
    return None


def text_size(text: str, size: int) -> tuple[int, int]:
    f = _font(size)
    if f is None:
        (w, h), _ = cv2.getTextSize(text.translate(_ASCII), cv2.FONT_HERSHEY_SIMPLEX, size / 30, max(1, size // 14))
        return w, h
    _, _, x1, y1 = f.getbbox(text)
    return x1, y1


def put_text(img: np.ndarray, text: str, org: tuple[int, int], size: int, color: tuple[int, int, int]) -> None:
    """`org`: yazının sol üst köşesi (piksel)."""
    f = _font(size)
    x, y = org
    if f is None:
        cv2.putText(img, text.translate(_ASCII), (x, y + size), cv2.FONT_HERSHEY_SIMPLEX, size / 30, color,
                    max(1, size // 14), cv2.LINE_AA)
        return
    from PIL import Image, ImageDraw

    tw, th = text_size(text, size)
    h, w = img.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(w, x + tw + 2), min(h, y + th + 4)
    if x1 <= x0 or y1 <= y0:
        return
    crop = Image.fromarray(np.ascontiguousarray(img[y0:y1, x0:x1, ::-1]))
    ImageDraw.Draw(crop).text((x - x0, y - y0), text, font=f, fill=(color[2], color[1], color[0]))
    img[y0:y1, x0:x1] = np.asarray(crop)[..., ::-1]


def entry_arrow(profile: Profile, w: int, h: int, line: tuple[tuple[float, float], tuple[float, float]]
                ) -> tuple[tuple[int, int], tuple[int, int]]:
    """Çizginin ortasından giriş tarafına bakan ok (piksel)."""
    side_of, _ = side_function(profile, w, h)
    (ax, ay), (bx, by) = line
    mx, my = (ax + bx) / 2, (ay + by) / 2
    dx, dy = (bx - ax) * w, (by - ay) * h
    ln = max(1e-6, math.hypot(dx, dy))
    nx, ny = -dy / ln, dx / ln                          # piksel uzayında çizgiye dik birim
    eps = 0.02
    if side_of(mx + nx * eps * ln / w, my + ny * eps * ln / h) < 0:
        nx, ny = -nx, -ny
    mid = (int(mx * w), int(my * h))
    size = 0.08 * min(w, h)
    return mid, (int(mid[0] + nx * size), int(mid[1] + ny * size))


def draw_detect(frame: np.ndarray, profile: Profile, det: DetectResult | None, entries: int, exits: int,
                ts: float, flash: float, flash_in: bool, labels: dict[int, str], panel: bool = True) -> np.ndarray:
    """`panel=False`: sayaç kutusu çizilmez (canlı panelde sayılar yan tarafta)."""
    h, w = frame.shape[:2]
    s = max(0.6, w / 960)                       # yazı ve çizgiler görüntüyle orantılı (alt akış 640 px'te küçülür)
    th = max(1, round(2 * s))
    if det is not None:
        (ax, ay), (bx, by) = det.line
        pa, pb = (int(ax * w), int(ay * h)), (int(bx * w), int(by * h))
        cv2.line(frame, pa, pb, ORANGE, th * 2, cv2.LINE_AA)
        mid, tip = entry_arrow(profile, w, h, det.line)
        cv2.arrowedLine(frame, mid, tip, ORANGE, th * 2, cv2.LINE_AA, tipLength=0.3)
        put_text(frame, "GİRİŞ", (tip[0] + int(6 * s), tip[1] - int(10 * s)), int(18 * s), ORANGE)
        for t in det.tracks:
            x1, y1, x2, y2 = (int(t.box[0] * w), int(t.box[1] * h), int(t.box[2] * w), int(t.box[3] * h))
            lab = labels.get(t.id)
            col = GRAY if lab == "P" else (GREEN if lab and lab.startswith("G") else (RED if lab else WHITE))
            cv2.rectangle(frame, (x1, y1), (x2, y2), col, th, cv2.LINE_AA)
            if len(t.trail) > 1:
                pts = np.array([[int(px * w), int(py * h)] for px, py in t.trail], np.int32)
                cv2.polylines(frame, [pts], False, col, max(1, th - 1), cv2.LINE_AA)
            tag = lab or f"#{t.id}"
            size = int((22 if lab else 15) * s)
            tw, tht = text_size(tag, size)
            ty = max(0, y1 - tht - int(8 * s))
            cv2.rectangle(frame, (x1, ty), (x1 + tw + int(8 * s), ty + tht + int(8 * s)), col, -1)
            put_text(frame, tag, (x1 + int(4 * s), ty + int(2 * s)), size, DARK)
    if not panel:
        return frame
    # panel: yeni girişte kısa süre yeşil, çıkışta turuncu yanar
    bg = (GREEN if flash_in else ORANGE) if flash > 0 else DARK
    pw, ph = int(380 * s), int(84 * s)
    roi = frame[0:ph, 0:pw]
    roi[:] = (0.25 * roi + 0.75 * np.array(bg, np.float32)).astype(np.uint8)
    put_text(frame, f"Giriş {entries}", (int(14 * s), int(8 * s)), int(36 * s), WHITE)
    put_text(frame, f"Çıkış {exits}", (int(200 * s), int(8 * s)), int(36 * s), WHITE)
    put_text(frame, f"{int(ts // 60):02d}:{ts % 60:04.1f}", (int(14 * s), int(56 * s)), int(15 * s), GRAY)
    return frame


_SKELETON = [(5, 6), (5, 7), (7, 9), (6, 8), (8, 10), (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14),
             (14, 16), (0, 5), (0, 6)]
_SAFETY_LABELS = {"hands_up": "ELLER YUKARI", "lying": "YERDE", "phone": "TELEFON"}

_COUNTING = (30, 190, 245)                      # poz güvenlik: süre doluyor (sarı)
_MAX_NAMED_PEOPLE = 6                           # bundan kalabalıkta "Kişi" yazısı bırakılır (kutular kalır)


@dataclass(frozen=True)
class SafetyTag:
    """Kişi üstü etiket: normalize kutu, durum ("person" | "counting" | "alarm"), yazı, süre ilerlemesi (yalnız counting)."""
    box: tuple[float, float, float, float]
    state: str
    text: str
    progress: float | None


def _clock(sec: float) -> str:
    n = int(sec)
    return f"{n // 60}:{n % 60:02d}"


def _in_areas(profile: Profile, r: SafetyResult) -> dict[int, set[str] | None]:
    """Analiz alanı içindeki gözlenen izler → alanlarının izin verdiği kurallar (alan yoksa her iz, None: hepsi).
    Çözümleyici alan dışındaki izi zaten sonuca koymaz; bindirme aynı kuralı kendisi de uygular."""
    out: dict[int, set[str] | None] = {}
    for t in r.tracks:
        allowed = area_rules(t.box, profile.safety.areas)
        if allowed is None or allowed[0]:
            out[t.id] = None if allowed is None else allowed[0]
    return out


def safety_tags(profile: Profile, r: SafetyResult) -> list[SafetyTag]:
    """Çizilecek etiketler (sıra: person, counting, alarm). Analiz alanı içinde gözlenen her kişi (alan yoksa herkes)
    bir etiket alır: alarm vermiş bölümü varsa alarm; yoksa kamerada açık ve alanında izinli kuralı sayan en dolu bölüm
    varsa counting; yoksa person. Alarmlı iz gözlenmese de `r.boxes` kutusuyla çıkar."""
    allowed = _in_areas(profile, r)
    people = len(allowed) <= _MAX_NAMED_PEOPLE
    obs = {t.id: tuple(float(v) for v in t.box) for t in r.tracks if t.id in allowed}
    person: list[SafetyTag] = []
    counting: list[SafetyTag] = []
    alarm: list[SafetyTag] = []
    ids = sorted(set(obs) | {tid for tid, _k, _s, fired in r.active if fired})
    for tid in ids:
        box = obs.get(tid) or (tuple(float(v) for v in r.boxes[tid]) if tid in r.boxes else None)
        if box is None:
            continue
        fired = [(k, sec) for i, k, sec, f in r.active if i == tid and f]
        if fired:
            names = " / ".join(_SAFETY_LABELS[k] for k in sorted({k for k, _ in fired}))
            alarm.append(SafetyTag(box, "alarm", f"{names} · ALARM {_clock(max(sec for _, sec in fired))}", None))
            continue
        best: tuple[float, str, float, float] | None = None              # (ilerleme, tür, sn, eşik)
        for i, kind, sec, f in r.active:
            name = RULE_OF_KIND[kind]
            rule = getattr(profile.safety, name, None) if i == tid else None
            ok = allowed.get(tid)
            if rule is None or not rule.enabled or rule.seconds <= 0 or (ok is not None and name not in ok):
                continue
            prog = min(1.0, max(0.0, sec / rule.seconds))
            if best is None or prog > best[0]:
                best = (prog, kind, sec, rule.seconds)
        if best is not None:
            prog, kind, sec, thr = best
            counting.append(SafetyTag(box, "counting", f"{_SAFETY_LABELS[kind]} {int(sec)} / {thr:g} sn", prog))
        elif tid in obs:
            person.append(SafetyTag(box, "person", "Kişi" if people else "", None))
    return person + counting + alarm


_TAG_STYLE = {"person": (GRAY, DARK), "counting": (_COUNTING, DARK), "alarm": (RED, WHITE)}   # (kutu/zemin, yazı)


@dataclass(frozen=True)
class AreaTag:
    """Analiz alanı çizimi: ad, köşeler (normalize), yazı "<ad>: <kişi sayısı>", içinde alarmı süren kişi var mı."""
    name: str
    points: tuple[tuple[float, float], ...]
    text: str
    alarm: bool


def _area_tags(profile: Profile, r: SafetyResult, tags: list[SafetyTag]) -> list[AreaTag]:
    alarms = [t.box for t in tags if t.state == "alarm"]
    obs = [tuple(float(v) for v in t.box) for t in r.tracks]
    out: list[AreaTag] = []
    for a in profile.safety.areas:
        n = sum(in_area(b, a) for b in obs)
        out.append(AreaTag(a.name, tuple(a.points), f"{a.name}: {n}", any(in_area(b, a) for b in alarms)))
    return out


def area_tags(profile: Profile, r: SafetyResult) -> list[AreaTag]:
    """Çizilecek analiz alanları (profil sırasıyla; alan yoksa boş). Kişi sayısı: kutu merkezi alanda olan gözlenen
    izler. Alarm: alarm etiketi (`safety_tags`; gözlenmeyen alarmlı izin son kutusu dahil) merkezi alanda."""
    return _area_tags(profile, r, safety_tags(profile, r))


def draw_safety(frame: np.ndarray, profile: Profile, r: SafetyResult | None) -> np.ndarray:
    """Poz güvenlik: analiz alanları (`area_tags`: ince açık mavi çizgi, ilk köşede "<ad>: <kişi sayısı>"; içinde alarmı
    süren kişi olan alan kalın kırmızı), iskeletler ve kişi üstü etiketler (`safety_tags`): ince gri "Kişi", süresi
    dolan kural için sarı kutu ve ilerleme çubuğu, alarm veren iz için kalın kırmızı kutu ve süre. Alarmlı iz bu karede
    gözlenmese de (tanıma bir kare kaçırdı) son bilinen kutusu (`r.boxes`) çizilir. Alan dışındaki kişiye etiket ve
    iskelet çizilmez."""
    if r is None:
        return frame
    h, w = frame.shape[:2]
    s = max(0.6, w / 960)
    th = max(1, round(2 * s))
    tags = safety_tags(profile, r)
    for at in _area_tags(profile, r, tags):
        pts = np.array([(int(x * w), int(y * h)) for x, y in at.points], np.int32)
        col, ink = (RED, WHITE) if at.alarm else (AREA, DARK)
        cv2.polylines(frame, [pts], True, col, th * 3 if at.alarm else 1, cv2.LINE_8)
        size = int(16 * s)
        tw, tht = text_size(at.text, size)
        lw, lh = tw + int(8 * s), tht + int(6 * s)
        x0, y0 = int(pts[0][0]), int(pts[0][1])
        x0 = max(0, min(x0, w - lw))                             # yazı karenin içinde kalsın
        ty = y0 - lh if y0 - lh >= 0 else y0                     # köşenin üstünde yer yoksa altında
        cv2.rectangle(frame, (x0, ty), (x0 + lw, ty + lh), col, -1)
        put_text(frame, at.text, (x0 + int(4 * s), ty + int(2 * s)), size, ink)
    shown = _in_areas(profile, r)
    for t in r.tracks:
        kp = r.poses.get(t.id) if t.id in shown else None
        if kp is not None:
            for a, b in _SKELETON:
                if kp[a, 2] >= KP_CONF and kp[b, 2] >= KP_CONF:
                    cv2.line(frame, (int(kp[a, 0]), int(kp[a, 1])), (int(kp[b, 0]), int(kp[b, 1])), CYAN, th,
                             cv2.LINE_AA)
    for tag in tags:
        col, ink = _TAG_STYLE[tag.state]
        x1, y1, x2, y2 = (int(tag.box[0] * w), int(tag.box[1] * h), int(tag.box[2] * w), int(tag.box[3] * h))
        cv2.rectangle(frame, (x1, y1), (x2, y2), col, {"person": 1, "counting": th * 2, "alarm": th * 3}[tag.state],
                      cv2.LINE_AA)
        if tag.text:
            size = int(18 * s)
            tw, tht = text_size(tag.text, size)
            lh = tht + int(8 * s)
            ty = y1 - lh if y1 - lh >= 0 else y1                 # üstte yer yoksa kutunun içinde, üst kenarda
            cv2.rectangle(frame, (x1, ty), (x1 + tw + int(8 * s), ty + lh), col, -1)
            put_text(frame, tag.text, (x1 + int(4 * s), ty + int(2 * s)), size, ink)
        if tag.progress is not None:
            bh = max(3, int(5 * s))
            by2 = min(h - 1, y2)
            cv2.rectangle(frame, (x1, by2 - bh), (x2, by2), DARK, -1)
            cv2.rectangle(frame, (x1, by2 - bh), (x1 + int((x2 - x1) * tag.progress), by2), col, -1)
    return frame


FireBox = tuple[str, Box, bool]                 # (tür "fire"|"smoke", normalize kutu, alarmlı mı)
_FIRE_STYLE = {"fire": (ORANGE, "YANGIN"), "smoke": (SMOKE, "DUMAN")}
_KIND_OF_TRACK = {tid: kind for kind, tid in TRACK_IDS.items()}


def fire_boxes(r: FireResult | None) -> list[FireBox]:
    """Çizilecek yangın/duman kutuları: bu karede hareketi geçen tespitler (ince) ve alarm vermiş açık bölümlerin kutusu
    (kalın; iz 0 alev, 1 duman). Hareketsiz tespit (sabit alev resmi, lamba) çizilmez."""
    if r is None:
        return []
    out: list[FireBox] = [(kind, box, False) for kind, box, _score, moved in r.detections if moved]
    for tid, box in sorted(r.boxes.items()):
        kind = _KIND_OF_TRACK.get(tid)
        if kind is not None:
            out.append((kind, box, True))
    return out


def draw_fire(frame: np.ndarray, boxes: Iterable[tuple[str, Sequence[float], bool]]) -> np.ndarray:
    """Yangın/duman: alev turuncu "YANGIN", duman gri "DUMAN"; alarmlı kutu 3 px, diğerleri 1 px. Kutular normalize
    (0–1): önizleme, alarm resmi ve olay kaydı hangi boyutta olursa olsun yerinde çizilir. Önce ince, sonra kalın kutular
    (alarm kutusu üstte kalır)."""
    h, w = frame.shape[:2]
    s = max(0.6, w / 960)
    for kind, box, alarmed in sorted(boxes, key=lambda b: (b[2], KINDS.index(b[0]) if b[0] in KINDS else 9)):
        style = _FIRE_STYLE.get(kind)
        if style is None:
            continue
        color, label = style
        x1, y1, x2, y2 = (int(box[0] * w), int(box[1] * h), int(box[2] * w), int(box[3] * h))
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3 if alarmed else 1, cv2.LINE_8)
        size = int((20 if alarmed else 16) * s)
        put_text(frame, label, (x1, max(0, y1 - size - int(6 * s))), size, color)
    return frame
