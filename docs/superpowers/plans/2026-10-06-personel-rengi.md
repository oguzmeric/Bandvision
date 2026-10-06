# Personel Rengi Uygulama Planı

> **Ajanlar için:** GEREKLİ ALT BECERİ: görev görev uygulamak için superpowers:subagent-driven-development (önerilen) ya da superpowers:executing-plans. Adımlar onay kutusu (`- [ ]`) ile izlenir.

**Amaç:** Kişi sayımında öğretilen üniforma rengini giyen kişilerin geçişlerini müşteri giriş/çıkışından ayırıp "personel geçişi" olarak saymak; her kamera açısında ≥ %95 doğruluk.

**Mimari:**
- Saf renk modülü (`staff_color`) ve izleyiciye karar kuralı eklenir.
  - Gövde bölgesinden örneklenen noktalar sRGB → Lab'a çevrilir.
  - Kare başına oy, iz başına oy birikimi; geçiş anında çoğunluk kararı.
- Python referansı ile Swift birebir aynı kuralları uygular; eşdeğerlik fikstürle denetlenir.
- Web canlı API'si ve paneli, iPhone arayüzü öğretme ve gösterme ekler.

**Teknoloji:**
- Python 3.11 (numpy, OpenCV, FastAPI, pytest, ruff).
- Swift 5 / SwiftUI (iOS 17, XCTest).
- Next.js 15 + Playwright.

**Tasarım belgesi:** `docs/superpowers/specs/2026-10-06-personel-rengi-design.md` (uygulayıcı önce bunu okur).

## Genel kısıtlar
- Sabitler (iki dilde aynı):
  - `GRID = 12`, `MATCH_DIST = 20`, `MIN_FRACTION = 0,25`, `MIN_POINTS = 36`, `DARK_L = 8`.
  - `MIN_VOTES = 3`, `ACHROMATIC_C = 15`, `TEACH_PATCH = 0,06`, `MAX_COLORS = 3`.
  - En küçük kutu 8 × 16 piksel.
- Gövde bölgesi:
  - `bottom`: x 0,30–0,70 · y 0,15–0,45.
  - `center`: x 0,30–0,70 · y 0,30–0,70 (kutuya göre oran).
- Renk uzaklığı `√((0,5 ΔL)² + Δa² + Δb²)`; `L < 8` nokta eşleşmez.
- Renk yokken davranış **birebir** bugünkü gibi; mevcut testler ve `people_parity.json` değişmeden geçer.
- Kullanıcıya görünen metinler Türkçe; kod tanımlayıcıları İngilizce (CLAUDE.md).
- Sözleşme: `staffColors` isteğe bağlı, `v1` kalır; olay şeması değişmez; personel geçişi sunucuya gönderilmez.
- Kullanıcı videoları public repoya konmaz.
- iOS: strict concurrency denetiminde 0 uyarı (CI `ios.yml`).

## İnceleme odağı
1. **Yan yana grupta personel + müşteri:** örtüşen kutuda komşunun rengi diğerine geçmemeli → Görev 3 (`others` dışlama testi) ve Görev 6 (grup senaryosu).
2. **Koyu/siyah giyimli müşteri, koyu lacivert üniforma:** akromatik renkte yanlış hariç tutma → Görev 3 (akromatik uyarı) ve Görev 12 (ölçümde koyu giyimli müşteri zorunlu).
3. **Kamera açısı değişince gövde bölgesi yanlış yere düşmesi** (tepeden omuz, yandan göğüs) → Görev 3 (iki konum noktası testi), Görev 12 (3 açı ölçümü).
4. **Kişi kısa görünüp geçiyor (3'ten az oy):** müşteri sayılmalı (güvenli yön) → Görev 4 testi.
5. **Öğretmede karanlık yere tıklama ya da 4. renk:** anlaşılır Türkçe ret → Görev 7 (API) ve Görev 8/10 (arayüz).

---

### Görev 1: Swift eşdeğerlik düzeltmesi — hareket desteği yalnızca tepeden kamerada

Python `detect_count.py` hareket lekelerini yalnızca `countAnchor == "center"` iken izleyiciye verir; Swift `PeopleCounter` her zaman veriyor (önceden kalan fark).

**Dosyalar:**
- Değiştir: `apps/ios/BantSayac/Vision/PeopleCounter.swift` (`process`)

**Arayüzler:** yok (davranış düzeltmesi).

- [ ] **Adım 1: Düzelt**

```swift
        let dets = detector.detect(pb, profile: profile)
        // Hareket desteği yalnızca tepeden kamerada (Python detect_count.py ile aynı): yatık/yandan kamerada tanıyıcı
        // kişiyi zaten bulur; kapı, ekran, gölge hareketi hayalet iz üretir.
        let blobs: [NBox]? = profile.anchor == .center ? motion.detect(small, profile: profile) : nil
```

- [ ] **Adım 2: Commit**

```bash
git add apps/ios/BantSayac/Vision/PeopleCounter.swift
git commit -m "iOS: hareket desteği yalnızca tepeden kamerada (Python ile eşdeğerlik)"
```

---

### Görev 2: Sözleşme — `staffColors` (şema, doküman, Python/Swift/TS modelleri)

**Dosyalar:**
- Değiştir:
  - `contracts/product-profile.schema.json` (`countAnchor`'dan sonra)
  - `docs/02-contracts.md` (profil tablosu, `countAnchor` satırından sonra)
  - `services/edge/bantvision/core/profile.py`
  - `apps/ios/BantSayac/Core/ProductProfile.swift`
  - `apps/dashboard/src/lib/live.ts`
- Oluştur: `apps/ios/BantSayac/Vision/StaffColor.swift` (yalnızca `LabColor` tipi; fonksiyonlar Görev 9'da)
- Test: `services/edge/tests/test_profile_contract.py`

**Arayüzler:**
- Üretir:
  - Python `Profile.staffColors: list[tuple[float, float, float]]` (varsayılan `[]`).
  - Swift `ProductProfile.staffColors: [LabColor]?`, `struct LabColor { L, a, b: Double }`.
  - TS `interface LabColor { L: number; a: number; b: number }` ve `Profile.staffColors?: LabColor[]`.

- [ ] **Adım 1: Başarısız testi yaz** (`test_profile_contract.py` sonuna)

```python
def test_staff_colors_round_trip_and_validate(validator: Draft202012Validator) -> None:
    p = Profile.people()
    assert "staffColors" not in p.to_dict()                       # boşsa yazılmaz
    p.staffColors = [(62.5, 48.25, 63.0), (30.0, -12.5, -40.0)]
    d = p.to_dict()
    assert d["staffColors"] == [{"L": 62.5, "a": 48.25, "b": 63.0}, {"L": 30.0, "a": -12.5, "b": -40.0}]
    assert_valid(validator, d)
    assert Profile.from_dict(d).staffColors == p.staffColors
    d["staffColors"] = d["staffColors"] * 2                         # 4 renk: şema reddeder
    assert list(validator.iter_errors(d))
```

- [ ] **Adım 2: Testin başarısız olduğunu gör**

Çalıştır: `cd services/edge && .venv/Scripts/python -m pytest tests/test_profile_contract.py -k staff -q`
Beklenen: FAIL (`Profile` nesnesinde `staffColors` yok). Yerelde jsonschema yoksa test toplanamaz; CI'da (edge-core) koşar. O durumda bu adımda CI'ya güvenilir ve Adım 6'daki yerel gidiş-dönüş denetimi kullanılır.

- [ ] **Adım 3: Şemayı güncelle** (`countAnchor` özelliğinden sonra)

```json
    "staffColors": {
      "description": "detect (kişi): personel üniforma renkleri, CIE Lab (D65). Bu renkteki kişilerin geçişleri giriş/çıkışa eklenmez, personel geçişi sayılır (algoritma §4.10 eki). Yoksa ya da boşsa kapalı.",
      "type": "array", "maxItems": 3,
      "items": {
        "type": "object", "additionalProperties": false, "required": ["L", "a", "b"],
        "properties": {
          "L": { "type": "number", "minimum": 0, "maximum": 100 },
          "a": { "type": "number", "minimum": -128, "maximum": 127 },
          "b": { "type": "number", "minimum": -128, "maximum": 127 }
        }
      }
    },
```

- [ ] **Adım 4: `docs/02-contracts.md` profil tablosuna satır ekle** (`countAnchor` satırından sonra)

```markdown
| `staffColors` | dizi (en çok 3) `{L, a, b}`, isteğe bağlı | `detect`: personel üniforma renkleri (CIE Lab, D65). Bu renkteki kişilerin geçişi giriş/çıkışa eklenmez, ayrı "personel geçişi" sayılır (§4.10 eki). Yoksa/boşsa kapalı; boş dizi yazılmaz |
```

- [ ] **Adım 5: Python `Profile`**

`countAnchor` alanından sonra:

```python
    # Personel üniforma renkleri (CIE Lab; §4.10 eki): bu renkteki kişinin geçişi müşteri sayılmaz. Boş = kapalı
    staffColors: list[tuple[float, float, float]] = field(default_factory=list)
```

`from_dict` içinde `if d.get("countLine"):` bloğundan önce:

```python
        if d.get("staffColors"):
            p.staffColors = [(float(c["L"]), float(c["a"]), float(c["b"])) for c in d["staffColors"]]
```

`to_dict` içinde `if self.roiPolygon:` satırından önce:

```python
        if self.staffColors:
            d["staffColors"] = [{"L": L, "a": a, "b": b} for L, a, b in self.staffColors]
```

- [ ] **Adım 6: Yerel gidiş-dönüş denetimi** (jsonschema'sız)

Çalıştır:

```bash
cd services/edge && .venv/Scripts/python -c "from bantvision.core import Profile; p=Profile.people(); p.staffColors=[(60.0,40.0,50.0)]; assert Profile.from_dict(p.to_dict()).staffColors==p.staffColors; print('ok')"
```

Beklenen: `ok`

- [ ] **Adım 7: Swift tipi** — `apps/ios/BantSayac/Vision/StaffColor.swift` oluştur

```swift
import Foundation

/// Öğretilen personel üniforma rengi: CIE Lab (D65). Sözleşme `staffColors` öğesi (algoritma §4.10 eki).
struct LabColor: Codable, Equatable, Hashable, Sendable {
    var L: Double
    var a: Double
    var b: Double
}
```

`ProductProfile` içinde `countAnchor` alanından sonra:

```swift
    /// Tanıma (kişi): personel üniforma renkleri (en çok 3). nil/boş = kapalı; bu renkteki kişinin geçişi müşteri sayılmaz
    var staffColors: [LabColor]? = nil
```

- [ ] **Adım 8: TS tipleri** (`apps/dashboard/src/lib/live.ts`)

`Profile` arayüzünün öncesine:

```ts
/** Personel üniforma rengi (CIE Lab, D65; sözleşme `staffColors`) */
export interface LabColor { L: number; a: number; b: number }
```

`Profile` arayüzüne:

```ts
  /** Kişi sayımı: personel renkleri (en çok 3); yoksa kapalı */
  staffColors?: LabColor[];
```

- [ ] **Adım 9: Doğrula ve commit**

Çalıştır:

```bash
cd services/edge && .venv/Scripts/ruff check . && cd ../../apps/dashboard && npx tsc --noEmit
```

Beklenen: hata yok.

```bash
git add contracts/product-profile.schema.json docs/02-contracts.md services/edge/bantvision/core/profile.py services/edge/tests/test_profile_contract.py apps/ios/BantSayac/Vision/StaffColor.swift apps/ios/BantSayac/Core/ProductProfile.swift apps/dashboard/src/lib/live.ts
git commit -m "Sözleşme: profilde isteğe bağlı staffColors (personel üniforma renkleri, Lab)"
```

---

### Görev 3: Python renk modülü `core/staff_color.py`

**Dosyalar:**
- Oluştur: `services/edge/bantvision/core/staff_color.py`
- Test: `services/edge/tests/test_staff_color.py`

**Arayüzler:**
- Üretir:
  - `LabColor = tuple[float, float, float]`
  - `srgb_to_lab(r: int, g: int, b: int) -> LabColor`
  - `labs_from_rgb(rgb: np.ndarray) -> np.ndarray` (N×3 uint8 RGB → N×3 Lab)
  - `torso_region(box: Box, anchor: str) -> Box`
  - `grid_points(region: Box) -> list[tuple[float, float]]` (satır satır: `j` dış, `i` iç)
  - `to_pixel(x: float, y: float, w: int, h: int) -> tuple[int, int]`
  - `color_distance(p: LabColor, q: LabColor) -> float`
  - `vote_labs(labs: np.ndarray, colors: Sequence[LabColor]) -> bool | None`
  - `vote_bgr(bgr: np.ndarray, box: Box, others: Sequence[Box], anchor: str, colors: Sequence[LabColor]) -> bool | None`
  - `is_staff(votes: int, staff_votes: int) -> bool`
  - `is_achromatic(c: LabColor) -> bool`
  - `dominant_color(labs: np.ndarray) -> LabColor | None`
  - `teach_bgr(bgr: np.ndarray, boxes: Sequence[Box], point: tuple[float, float], anchor: str) -> LabColor | None`
  - Sabitler `GRID, MATCH_DIST, MIN_FRACTION, MIN_POINTS, DARK_L, MIN_VOTES, ACHROMATIC_C, TEACH_PATCH, MAX_COLORS`.

- [ ] **Adım 1: Başarısız testleri yaz** — `tests/test_staff_color.py`

```python
"""Personel rengi (§4.10 eki): renk çevirisi, gövde bölgesi, kare oyu, öğretme."""
from __future__ import annotations

import numpy as np
import pytest

from bantvision.core import staff_color as sc

ORANGE = (240, 120, 20)          # RGB yelek
NAVY = (25, 35, 80)


def frame_with(person_rgb: tuple[int, int, int], box: tuple[float, float, float, float], vest: float = 1.0,
               shirt: tuple[int, int, int] = (200, 200, 200), size: tuple[int, int] = (640, 360),
               shade: float = 1.0) -> np.ndarray:
    """Gri zemin; kutuda kişi: gövdenin `vest` kadarlık orta şeridi `person_rgb`, kalan gövde `shirt`."""
    w, h = size
    img = np.full((h, w, 3), 128, np.uint8)
    x1, y1, x2, y2 = (int(box[0] * w), int(box[1] * h), int(box[2] * w), int(box[3] * h))
    img[y1:y2, x1:x2] = np.array(shirt[::-1], np.uint8)
    bw = x2 - x1
    vx1, vx2 = x1 + int(bw * (0.5 - vest / 2)), x1 + int(bw * (0.5 + vest / 2))
    img[y1:y2, vx1:vx2] = np.array(person_rgb[::-1], np.uint8)
    return np.clip(img.astype(np.float64) * shade, 0, 255).astype(np.uint8)


def lab_of(rgb: tuple[int, int, int]) -> sc.LabColor:
    return sc.srgb_to_lab(*rgb)


def test_srgb_to_lab_reference_values() -> None:
    for rgb, ref in [((255, 255, 255), (100.0, 0.0, 0.0)), ((0, 0, 0), (0.0, 0.0, 0.0)),
                     ((255, 0, 0), (53.24, 80.09, 67.20)), ((0, 255, 0), (87.73, -86.18, 83.18)),
                     ((0, 0, 255), (32.30, 79.19, -107.86)), ((128, 128, 128), (53.59, 0.0, 0.0))]:
        got = sc.srgb_to_lab(*rgb)
        assert got == pytest.approx(ref, abs=0.02), rgb


def test_torso_region_depends_on_camera_mount() -> None:
    box = (0.2, 0.1, 0.4, 0.9)
    assert sc.torso_region(box, "bottom") == pytest.approx((0.26, 0.22, 0.34, 0.46))
    assert sc.torso_region(box, "center") == pytest.approx((0.26, 0.34, 0.34, 0.66))


def test_grid_points_row_major_and_pixel_clamp() -> None:
    pts = sc.grid_points((0.0, 0.0, 1.0, 1.0))
    assert len(pts) == 144 and pts[0] == pytest.approx((1 / 24, 1 / 24)) and pts[1][1] == pts[0][1]
    assert sc.to_pixel(1.0, 1.0, 640, 360) == (639, 359) and sc.to_pixel(-0.1, 0.5, 640, 360) == (0, 180)


def test_vote_full_uniform_partial_vest_shade_and_other_colour() -> None:
    box = (0.4, 0.1, 0.5, 0.9)
    colors = [lab_of(ORANGE)]
    assert sc.vote_bgr(frame_with(ORANGE, box), box, [], "bottom", colors) is True
    assert sc.vote_bgr(frame_with(ORANGE, box, vest=0.35), box, [], "bottom", colors) is True      # yelek
    assert sc.vote_bgr(frame_with(ORANGE, box, shade=0.85), box, [], "bottom", colors) is True     # hafif gölge
    assert sc.vote_bgr(frame_with(NAVY, box), box, [], "bottom", colors) is False


def test_vote_ignores_points_inside_neighbour_box() -> None:
    """Yan yana grup: müşterinin gövdesine giren personel kutusunun noktaları sayılmaz."""
    w, h = 640, 360
    img = np.full((h, w, 3), 128, np.uint8)
    cust, staff = (0.40, 0.1, 0.50, 0.9), (0.45, 0.1, 0.55, 0.9)
    img[int(0.1 * h):int(0.9 * h), int(0.40 * w):int(0.50 * w)] = NAVY[::-1]
    img[int(0.1 * h):int(0.9 * h), int(0.45 * w):int(0.55 * w)] = ORANGE[::-1]     # öndeki personel örtüyor
    colors = [lab_of(ORANGE)]
    assert sc.vote_bgr(img, cust, [], "bottom", colors) is True                     # dışlamasız: karışır
    assert sc.vote_bgr(img, cust, [staff], "bottom", colors) is False               # komşunun noktaları dışlandı


def test_vote_none_for_tiny_box_and_dark_points_never_match() -> None:
    colors = [lab_of(ORANGE)]
    assert sc.vote_bgr(frame_with(ORANGE, (0.5, 0.5, 0.505, 0.52)), (0.5, 0.5, 0.505, 0.52), [], "bottom",
                       colors) is None
    dark = sc.labs_from_rgb(np.array([[3, 3, 3]] * 144, np.uint8))
    assert sc.vote_labs(dark, [(2.0, 0.0, 0.0)]) is False


def test_is_staff_needs_three_votes_and_majority() -> None:
    assert not sc.is_staff(2, 2)
    assert sc.is_staff(3, 2) and sc.is_staff(4, 2) and not sc.is_staff(5, 2)


def test_achromatic_warning() -> None:
    assert sc.is_achromatic(lab_of((20, 20, 20))) and sc.is_achromatic(lab_of(NAVY))
    assert not sc.is_achromatic(lab_of(ORANGE))


def test_teach_from_box_patch_and_dark() -> None:
    box = (0.4, 0.1, 0.5, 0.9)
    img = frame_with(ORANGE, box, vest=0.6)
    c = sc.teach_bgr(img, [box], (0.45, 0.4), "bottom")
    assert c is not None and sc.color_distance(c, lab_of(ORANGE)) < 3
    c2 = sc.teach_bgr(img, [], (0.45, 0.3), "bottom")                     # kutusuz: tıklanan yerin çevresi
    assert c2 is not None and sc.color_distance(c2, lab_of(ORANGE)) < 3
    black = np.zeros((360, 640, 3), np.uint8)
    assert sc.teach_bgr(black, [], (0.5, 0.5), "bottom") is None
```

- [ ] **Adım 2: Testlerin başarısız olduğunu gör**

Çalıştır: `cd services/edge && .venv/Scripts/python -m pytest tests/test_staff_color.py -q`
Beklenen: FAIL (`ModuleNotFoundError: bantvision.core.staff_color`)

- [ ] **Adım 3: Modülü yaz** — `bantvision/core/staff_color.py`

```python
"""Personel rengi (algoritma §4.10 eki): öğretilen üniforma rengini giyen kişinin geçişi müşteri sayılmaz.

Kişi kutusunun gövde bölgesinden 12×12 nokta örneklenir, sRGB → CIE Lab (D65) çevrilir; noktaların ≥ %25'i
öğretilen renge yakınsa (ΔL yarım ağırlıklı uzaklık < 20) o kare personel oyu verir. İz başına oylar birikir; geçiş
anında ≥ 3 oy ve çoğunluk personelse geçiş personel geçişidir. Swift: apps/ios/BantSayac/Vision/StaffColor.swift —
davranış birebir aynı (staff_parity.json). Görüntü saklanmaz; öğretilen renk yalnızca 3 sayıdır.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from statistics import median

import numpy as np

LabColor = tuple[float, float, float]
Box = tuple[float, float, float, float]

GRID = 12
MATCH_DIST = 20.0
MIN_FRACTION = 0.25
MIN_POINTS = 36                 # ızgaranın %25'i: komşu kutular çıkarıldıktan sonra kalan en az nokta
DARK_L = 8.0
MIN_VOTES = 3
ACHROMATIC_C = 15.0
TEACH_PATCH = 0.06              # kutusuz öğretmede kare kenarı (görüntü genişliğine oran)
MAX_COLORS = 3
MIN_BOX_PX = (8.0, 16.0)

_M = np.array([[0.4124564, 0.3575761, 0.1804375],
               [0.2126729, 0.7151522, 0.0721750],
               [0.0193339, 0.1191920, 0.9503041]])
_WHITE = np.array([0.95047, 1.0, 1.08883])


def labs_from_rgb(rgb: np.ndarray) -> np.ndarray:
    """N×3 sRGB (0–255) → N×3 Lab."""
    c = np.asarray(rgb, np.float64).reshape(-1, 3) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    xyz = (lin[:, 0:1] * _M[:, 0] + lin[:, 1:2] * _M[:, 1] + lin[:, 2:3] * _M[:, 2]) / _WHITE
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16.0 / 116.0)
    return np.stack([116.0 * f[:, 1] - 16.0, 500.0 * (f[:, 0] - f[:, 1]), 200.0 * (f[:, 1] - f[:, 2])], axis=1)


def srgb_to_lab(r: int, g: int, b: int) -> LabColor:
    L, a, bb = labs_from_rgb(np.array([[r, g, b]]))[0]
    return float(L), float(a), float(bb)


def torso_region(box: Box, anchor: str) -> Box:
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    ty0, ty1 = (0.15, 0.45) if anchor == "bottom" else (0.30, 0.70)
    return (x1 + 0.30 * w, y1 + ty0 * h, x1 + 0.70 * w, y1 + ty1 * h)


def grid_points(region: Box) -> list[tuple[float, float]]:
    x0, y0, x1, y1 = region
    rw, rh = x1 - x0, y1 - y0
    return [(x0 + (i + 0.5) / GRID * rw, y0 + (j + 0.5) / GRID * rh) for j in range(GRID) for i in range(GRID)]


def to_pixel(x: float, y: float, w: int, h: int) -> tuple[int, int]:
    return min(max(math.floor(x * w), 0), w - 1), min(max(math.floor(y * h), 0), h - 1)


def color_distance(p: LabColor, q: LabColor) -> float:
    return math.sqrt((0.5 * (p[0] - q[0])) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2)


def vote_labs(labs: np.ndarray, colors: Sequence[LabColor]) -> bool | None:
    """Kalan noktaların ≥ %25'i öğretilen renklerden birine yakınsa personel oyu; < 36 nokta: oy yok."""
    n = len(labs)
    if n < MIN_POINTS or not colors:
        return None
    c = np.asarray(colors, np.float64)
    d = np.sqrt((0.5 * (labs[:, None, 0] - c[None, :, 0])) ** 2 + (labs[:, None, 1] - c[None, :, 1]) ** 2
                + (labs[:, None, 2] - c[None, :, 2]) ** 2)
    hit = (d.min(axis=1) < MATCH_DIST) & (labs[:, 0] >= DARK_L)
    return bool(int(hit.sum()) >= MIN_FRACTION * n)


def _inside(o: Box, x: float, y: float) -> bool:
    return o[0] <= x <= o[2] and o[1] <= y <= o[3]


def vote_bgr(bgr: np.ndarray, box: Box, others: Sequence[Box], anchor: str,
             colors: Sequence[LabColor]) -> bool | None:
    """Bu karede tanımayla gözlenen kutunun oyu. `others`: aynı karedeki diğer tanıma kutuları (noktaları dışlanır)."""
    h, w = bgr.shape[:2]
    if (box[2] - box[0]) * w < MIN_BOX_PX[0] or (box[3] - box[1]) * h < MIN_BOX_PX[1]:
        return None
    pts = [to_pixel(x, y, w, h) for x, y in grid_points(torso_region(box, anchor))
           if not any(_inside(o, x, y) for o in others)]
    if len(pts) < MIN_POINTS:
        return None
    xs = np.array([p[0] for p in pts])
    ys = np.array([p[1] for p in pts])
    return vote_labs(labs_from_rgb(bgr[ys, xs, ::-1]), colors)


def is_staff(votes: int, staff_votes: int) -> bool:
    return votes >= MIN_VOTES and 2 * staff_votes >= votes


def is_achromatic(c: LabColor) -> bool:
    return math.hypot(c[1], c[2]) < ACHROMATIC_C


def dominant_color(labs: np.ndarray) -> LabColor | None:
    """(⌊a/8⌋, ⌊b/8⌋) kutucuklarından en kalabalığı (eşitlikte ilk görülen); o kutucuğun L, a, b medyanı."""
    if len(labs) == 0:
        return None
    counts: dict[tuple[int, int], list[int]] = {}
    for k, (_, a, b) in enumerate(labs):
        counts.setdefault((math.floor(a / 8), math.floor(b / 8)), []).append(k)
    best = max(counts.values(), key=len)            # max ilk görülen en büyüğü verir (sözlük ekleme sırası)
    sel = labs[best]
    c = (float(median(sel[:, 0])), float(median(sel[:, 1])), float(median(sel[:, 2])))
    return None if c[0] < DARK_L else c


def teach_bgr(bgr: np.ndarray, boxes: Sequence[Box], point: tuple[float, float], anchor: str) -> LabColor | None:
    """Tıklanan noktayı içeren en küçük kutunun gövdesi; kutu yoksa tıklanan yer çevresi. Çok karanlıksa None."""
    h, w = bgr.shape[:2]
    x, y = point
    inside = [b for b in boxes if _inside(b, x, y)]
    if inside:
        region = torso_region(min(inside, key=lambda b: (b[2] - b[0]) * (b[3] - b[1])), anchor)
    else:
        hx, hy = TEACH_PATCH / 2, TEACH_PATCH / 2 * w / h
        region = (max(0.0, x - hx), max(0.0, y - hy), min(1.0, x + hx), min(1.0, y + hy))
    pts = [to_pixel(px, py, w, h) for px, py in grid_points(region)]
    xs = np.array([p[0] for p in pts])
    ys = np.array([p[1] for p in pts])
    return dominant_color(labs_from_rgb(bgr[ys, xs, ::-1]))
```

- [ ] **Adım 4: Testlerin geçtiğini gör**

Çalıştır: `cd services/edge && .venv/Scripts/python -m pytest tests/test_staff_color.py -q && .venv/Scripts/ruff check .`
Beklenen: tümü PASS, ruff temiz.

Not: `test_torso_region_depends_on_camera_mount` kutuya göre oranları sınar (`0,2 + 0,3 · 0,2 = 0,26`, …). `test_vote_ignores_points_inside_neighbour_box`'ta komşu kutu gövde ızgarasının sağ yarısını (6 sütun) kaplar; kalan 72 nokta lacivert → `False`.

- [ ] **Adım 5: Commit**

```bash
git add services/edge/bantvision/core/staff_color.py services/edge/tests/test_staff_color.py
git commit -m "edge: personel rengi modülü (Lab, gövde bölgesi, kare oyu, öğretme)"
```

---

### Görev 4: Python izleyici — iz başına oy ve personel geçişi

**Dosyalar:**
- Değiştir: `services/edge/bantvision/core/people_track.py`
- Test: `services/edge/tests/test_people_track.py` (sona ekle)

**Arayüzler:**
- Tüketir: `staff_color.is_staff(votes, staff_votes)`.
- Üretir:
  - `MotTrack.votes: int`, `MotTrack.staff_votes: int`, `MotTrack.staff_crossings: int`.
  - `MotTracker.update(..., staff_vote: Callable[[np.ndarray, list[np.ndarray]], bool | None] | None = None)`; dönüş değişmez `(entered, exited)` (yalnızca müşteri).
  - `MotTracker.staff_entered`, `MotTracker.staff_exited: list[MotTrack]` (her `update` başında boşalır).
  - `staff_vote(box, others)`: `others` = bu karede bastırma sonrası **diğer** tespit kutuları.

- [ ] **Adım 1: Başarısız testleri yaz** (`tests/test_people_track.py` sonuna)

```python
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
```

- [ ] **Adım 2: Testlerin başarısız olduğunu gör**

Çalıştır: `cd services/edge && .venv/Scripts/python -m pytest tests/test_people_track.py -q -k "staff or vote"`
Beklenen: FAIL (`unexpected keyword argument 'staff_vote'`)

- [ ] **Adım 3: Uygula** — `people_track.py`

İçe aktarmalara:

```python
from collections.abc import Callable

from .staff_color import is_staff
```

`MotTrack` alanlarına (`last_det`'ten sonra):

```python
    votes: int = 0                                  # personel rengi oyu verilen kare sayısı (§4.10 eki)
    staff_votes: int = 0                            # bunların personel oyu olanları
    staff_crossings: int = 0                        # personel geçişleri (giriş/çıkışa eklenmez)
```

`MotTracker.__init__` ve `reset` sonuna:

```python
        self.staff_entered: list[MotTrack] = []
        self.staff_exited: list[MotTrack] = []
```

`update` imzası ve gövde başı:

```python
    def update(self, dets: list[tuple[Box, float]], side_of: object, anchor_mode: str = "center",
               motion: list[Box] | None = None, bounds: Box = (0.0, 0.0, 1.0, 1.0),
               staff_vote: Callable[[np.ndarray, list[np.ndarray]], bool | None] | None = None
               ) -> tuple[list[MotTrack], list[MotTrack]]:
        """... `staff_vote(kutu, diğer kutular)`: tanımayla gözlenen kutunun personel oyu (§4.10 eki; None: oy yok).
        Personel geçişleri dönüşe girmez, `staff_entered` / `staff_exited`'a yazılır."""
        p = self.p
        self.staff_entered, self.staff_exited = [], []
```

Eşleşen tespit döngüsünde `self._update(t, boxes[di], True, ...)` çağrısından hemen önce:

```python
                self._vote(t, di, boxes, staff_vote)
```

Yeni iz döngüsü:

```python
        for di in high:
            if di not in used:
                self._new(boxes[di], scores[di], True, side_of, anchor_mode, entered, exited,
                          lambda t, di=di: self._vote(t, di, boxes, staff_vote))
```

Yardımcılar ve `_new` imzası:

```python
    def _vote(self, t: MotTrack, di: int, boxes: list[np.ndarray],
              staff_vote: Callable[[np.ndarray, list[np.ndarray]], bool | None] | None) -> None:
        if staff_vote is None:
            return
        v = staff_vote(boxes[di], [b for k, b in enumerate(boxes) if k != di])
        if v is not None:
            t.votes += 1
            t.staff_votes += int(v)

    def _new(self, box: np.ndarray, score: float, verified: bool, side_of: object, anchor_mode: str,
             entered: list[MotTrack], exited: list[MotTrack],
             before_observe: Callable[[MotTrack], None] | None = None) -> None:
        t = MotTrack(self.next_id, box, np.zeros(4), box, score, verified=verified, born=self.frame,
                     last_det=self.frame)
        t.hist.append((self.frame, box))
        self.next_id += 1
        self.tracks.append(t)
        if before_observe is not None:
            before_observe(t)
        self._observe(t, side_of, anchor_mode, entered, exited)
```

`_observe` içinde onaylı bekleyen geçişlerin sayıldığı blok:

```python
        if t.confirmed and t.pending:
            staff = is_staff(t.votes, t.staff_votes)
            for x in t.pending:
                if staff:                                        # §4.10 eki: personel, müşteri sayısına girmez
                    t.staff_crossings += 1
                    (self.staff_entered if x > 0 else self.staff_exited).append(t)
                elif x > 0:
                    t.entries += 1
                    entered.append(t)
                else:
                    t.exits += 1
                    exited.append(t)
            t.pending = []
```

- [ ] **Adım 4: Tüm izleyici testleri ve eşdeğerlik fikstürü**

Çalıştır:

```bash
cd services/edge && .venv/Scripts/python -m pytest tests/test_people_track.py tests/test_people_groups.py tests/test_people_fixture.py -q
```

Beklenen: tümü PASS (`people_parity.json` değişmeden güncel: oy yokken davranış aynı).

- [ ] **Adım 5: Commit**

```bash
git add services/edge/bantvision/core/people_track.py services/edge/tests/test_people_track.py
git commit -m "edge: izleyicide personel oyu ve ayrı personel geçişi (§4.10 eki)"
```

---

### Görev 5: Eşdeğerlik fikstürü `staff_parity.json`

**Dosyalar:**
- Oluştur:
  - `tools/make_staff_fixture.py`
  - `apps/ios/BantSayacTests/staff_parity.json` (üretilir)
  - `services/edge/tests/test_staff_fixture.py`

**Arayüzler:**
- Tüketir: Görev 3–4 fonksiyonları.
- Üretir JSON biçimi:

```
{"lab": [[r,g,b,L,a,b], ...],
 "points": [{"w","h","box":[4],"anchor","pts":[[px,py],...144]}],
 "votes": [{"rgb":[[r,g,b],...], "colors":[[L,a,b],...], "vote": true|false|null}],
 "dominant": [{"rgb":[[r,g,b],...], "lab":[L,a,b]|null}],
 "tracker": [{"name","frames":[{"d":[[x1,y1,x2,y2,s],...], "v":[1|0|-1,...]}], "events":[[k,id,dir,staff]]}]}
```

`v`: bastırma **öncesi** tespit sırasıyla oy (1 personel, 0 değil, −1 oy yok). Swift ve Python kutu koordinatından sırayı bulur (bastırma koordinat değiştirmez).

- [ ] **Adım 1: Aracı yaz** — `tools/make_staff_fixture.py`

```python
"""iOS ↔ Python eşdeğerliği: personel rengi (§4.10 eki).

Kullanım: python tools/make_staff_fixture.py [--check]
Üretir: apps/ios/BantSayacTests/staff_parity.json — renk çevirisi, ızgara noktaları, kare oyu, öğretme (baskın renk),
izleyicide personel kararı. Girdiler sabit tohumlu; Lab 6 ondalık (Swift testi 1e-4 toleransla karşılaştırır).
Eşiğe 1e-3'ten yakın oy durumları üretilmez (iki dilde son basamak farkı kararı değiştirmesin).
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "apps" / "ios" / "BantSayacTests" / "staff_parity.json"
sys.path.insert(0, str(ROOT / "services" / "edge"))

from bantvision.core import staff_color as sc
from bantvision.core.people_track import MotParams, MotTracker
from bantvision.core.sim_people import LINE, Faults, scenario


def r6(v: float) -> float:
    return round(float(v), 6)


def build() -> dict:
    rng = np.random.default_rng(7)
    rgbs = [(0, 0, 0), (255, 255, 255), (255, 0, 0), (0, 255, 0), (0, 0, 255), (128, 128, 128), (10, 10, 10)]
    rgbs += [tuple(int(v) for v in rng.integers(0, 256, 3)) for _ in range(200)]
    lab = [[*c, *(r6(v) for v in sc.srgb_to_lab(*c))] for c in rgbs]

    points = []
    for w, h, box, anchor in [(640, 360, (0.2, 0.1, 0.4, 0.9), "bottom"), (352, 288, (0.0, 0.0, 1.0, 1.0), "center"),
                              (1920, 1080, (0.71, 0.33, 0.79, 0.97), "bottom")]:
        pts = [list(sc.to_pixel(x, y, w, h)) for x, y in sc.grid_points(sc.torso_region(box, anchor))]
        points.append({"w": w, "h": h, "box": list(box), "anchor": anchor, "pts": pts})

    votes = []
    while len(votes) < 60:
        base = rng.integers(0, 256, 3)
        n = int(rng.integers(30, 145))
        rgb = np.clip(base + rng.normal(0, 25, (n, 3)), 0, 255).astype(np.uint8)
        colors = [sc.srgb_to_lab(*(int(v) for v in rng.integers(0, 256, 3))) for _ in range(int(rng.integers(1, 4)))]
        if rng.random() < 0.5:
            colors[0] = sc.srgb_to_lab(*(int(v) for v in base))
        labs = sc.labs_from_rgb(rgb)
        c = np.asarray(colors)
        d = np.sqrt((0.5 * (labs[:, None, 0] - c[None, :, 0])) ** 2 + (labs[:, None, 1] - c[None, :, 1]) ** 2
                    + (labs[:, None, 2] - c[None, :, 2]) ** 2)
        if np.any(np.abs(d - sc.MATCH_DIST) < 1e-3) or np.any(np.abs(labs[:, 0] - sc.DARK_L) < 1e-3):
            continue
        hits = int(((d.min(axis=1) < sc.MATCH_DIST) & (labs[:, 0] >= sc.DARK_L)).sum())
        if n >= sc.MIN_POINTS and abs(hits - sc.MIN_FRACTION * n) < 1e-9:
            continue
        votes.append({"rgb": rgb.tolist(), "colors": [[r6(v) for v in col] for col in colors],
                      "vote": sc.vote_labs(sc.labs_from_rgb(rgb), [tuple(r6(v) for v in col) for col in colors])})

    dominant = []
    for _ in range(20):
        base = rng.integers(0, 256, 3)
        rgb = np.clip(base + rng.normal(0, 30, (144, 3)), 0, 255).astype(np.uint8)
        c = sc.dominant_color(sc.labs_from_rgb(rgb))
        dominant.append({"rgb": rgb.tolist(), "lab": None if c is None else [r6(v) for v in c]})

    tracker = []
    for seed in (0, 1, 2):
        dets, _, _ = scenario(seed, Faults(miss=0.15, part=0.1))
        frames, vote_of = [], {}
        for k, fd in enumerate(dets):
            d = [[round(float(v), 5) for v in (*b, s)] for b, s in fd]
            v = [int(rng.choice([1, 1, 1, 0, -1])) if b[0] < 0.5 else int(rng.choice([0, 0, 0, 1, -1]))
                 for b in d]                                            # soldakiler çoğunlukla personel
            frames.append({"d": d, "v": v})
            vote_of[k] = {tuple(b[:4]): (None if x < 0 else bool(x)) for b, x in zip(d, v)}
        t = MotTracker(MotParams(max_age=25))
        events = []
        for k, fr in enumerate(frames):
            ins, outs = t.update([((b[0], b[1], b[2], b[3]), b[4]) for b in fr["d"]], lambda _x, y: y - LINE,
                                 staff_vote=lambda box, _o, k=k: vote_of[k].get(tuple(float(v) for v in box)))
            events += [[k, tr.id, 1, 0] for tr in ins] + [[k, tr.id, -1, 0] for tr in outs]
            events += [[k, tr.id, 1, 1] for tr in t.staff_entered] + [[k, tr.id, -1, 1] for tr in t.staff_exited]
        tracker.append({"name": f"personel-{seed}", "line": LINE, "maxAge": 25, "frames": frames, "events": events})
    return {"lab": lab, "points": points, "votes": votes, "dominant": dominant, "tracker": tracker}


def main() -> int:
    text = json.dumps(build(), separators=(",", ":")) + "\n"
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print("staff_parity.json güncel değil: python tools/make_staff_fixture.py")
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    data = json.loads(text)
    staff = sum(e[3] for s in data["tracker"] for e in s["events"])
    print(f"{OUT.name}: {len(data['lab'])} renk, {len(data['votes'])} oy, {staff} personel geçişi")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Adım 2: Üret ve güncellik testini yaz**

Çalıştır: `cd services/edge && .venv/Scripts/python ../../tools/make_staff_fixture.py`
Beklenen: `staff_parity.json: 207 renk, 60 oy, N personel geçişi` (N > 0 olmalı; 0 ise oy dağılımı yeniden ayarlanır).

`services/edge/tests/test_staff_fixture.py`:

```python
"""iOS eşdeğerlik dosyası (apps/ios/BantSayacTests/staff_parity.json) Python'un güncel davranışını mı gösteriyor?"""
from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]


def test_staff_parity_fixture_is_current() -> None:
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "make_staff_fixture.py"), "--check"],
                       capture_output=True, text=True, encoding="utf-8", check=False)
    assert r.returncode == 0, r.stdout + r.stderr
```

- [ ] **Adım 3: Doğrula**

Çalıştır: `cd services/edge && .venv/Scripts/python -m pytest tests/test_staff_fixture.py -q && .venv/Scripts/ruff check . ../../tools`
Beklenen: PASS, ruff temiz.

- [ ] **Adım 4: Commit**

```bash
git add tools/make_staff_fixture.py apps/ios/BantSayacTests/staff_parity.json services/edge/tests/test_staff_fixture.py
git commit -m "tools: personel rengi eşdeğerlik fikstürü (Python ↔ Swift)"
```

---

### Görev 6: Python tanıma sayacı, hat (pipeline) ve çizim

**Dosyalar:**
- Değiştir:
  - `services/edge/bantvision/core/detect_count.py` (`DetectResult`, `process`)
  - `services/edge/bantvision/core/pipeline.py` (`FrameResult`, `Pipeline`)
  - `services/edge/bantvision/overlay.py` (`draw_detect`)
- Test: `services/edge/tests/test_staff_color.py` (sona ekle)

**Arayüzler:**
- Tüketir:
  - `vote_bgr`.
  - `MotTracker.update(..., staff_vote=)`, `staff_entered/staff_exited`.
- Üretir:
  - `DetectResult.staff_entries`, `DetectResult.staff_exits: list[MotTrack]` (varsayılan boş).
  - `FrameResult.staff_events: list[tuple[int, int]]` (iz kimliği, +1 giriş / −1 çıkış; yalnızca sayım açıkken).
  - `Pipeline.total_staff_in`, `Pipeline.total_staff_out`; `reset_count` sıfırlar.
  - Çizimde personel izinin etiketi `"P"` → gri kutu.

- [ ] **Adım 1: Başarısız testi yaz** (`test_staff_color.py` sonuna)

```python
class _FakeDetector:
    """Karedeki renkli dikdörtgenleri kişi kutusu olarak döndürür (tanıma modeli gerekmez)."""

    def __init__(self, boxes_per_frame: list[list[tuple[float, float, float, float]]]) -> None:
        self.frames = boxes_per_frame
        self.k = 0

    def detect(self, crop: np.ndarray, _classes: object, conf: float = 0.15) -> list[object]:
        from types import SimpleNamespace

        h, w = crop.shape[:2]
        out = [SimpleNamespace(x1=b[0] * w, y1=b[1] * h, x2=b[2] * w, y2=b[3] * h, score=0.9)
               for b in self.frames[self.k]]
        self.k += 1
        return out


def _run(people: list[tuple[tuple[int, int, int], float]], colors: list[sc.LabColor]) -> tuple[int, int, int]:
    """Yan yana kişiler (renk, x merkezi) yukarıdan aşağı geçer; (giriş, personel giriş, personel çıkış)."""
    from bantvision.core import Pipeline, Profile

    p = Profile.people()
    p.direction, p.linePosition, p.countAnchor, p.staffColors = "down", 0.55, "bottom", colors
    n = 40
    frames, boxes = [], []
    for k in range(n):
        y = 0.05 + 0.6 * k / (n - 1)
        img = np.full((360, 640, 3), 128, np.uint8)
        fb = []
        for rgb, cx in people:
            b = (cx - 0.04, y, cx + 0.04, y + 0.33)
            img[int(b[1] * 360):int(b[3] * 360), int(b[0] * 640):int(b[2] * 640)] = rgb[::-1]
            fb.append(b)
        frames.append(img)
        boxes.append(fb)
    pipe = Pipeline(p)
    pipe.detect._detector = _FakeDetector(boxes)            # type: ignore[assignment]
    pipe.detect.motion = None
    pipe.counting = True
    for k, img in enumerate(frames):
        pipe.process(img, k / 10)
    return pipe.total, pipe.total_staff_in, pipe.total_staff_out


def test_pipeline_counts_staff_separately_in_group() -> None:
    staff = [lab_of(ORANGE)]
    assert _run([(ORANGE, 0.40)], staff) == (0, 1, 0)
    assert _run([(NAVY, 0.40)], staff) == (1, 0, 0)
    assert _run([(ORANGE, 0.40), (NAVY, 0.52)], staff) == (1, 1, 0)       # yan yana: personel + müşteri
    assert _run([(ORANGE, 0.40), (NAVY, 0.52)], []) == (2, 0, 0)          # renk yok: bugünkü davranış
```

- [ ] **Adım 2: Testin başarısız olduğunu gör**

Çalıştır: `cd services/edge && .venv/Scripts/python -m pytest tests/test_staff_color.py -q -k pipeline`
Beklenen: FAIL (`Pipeline` nesnesinde `total_staff_in` yok)

- [ ] **Adım 3: `detect_count.py`**

İçe aktarma: `from .staff_color import vote_bgr`

`DetectResult` alanlarına:

```python
    staff_entries: list[MotTrack] = field(default_factory=list)     # §4.10 eki: personel geçişleri
    staff_exits: list[MotTrack] = field(default_factory=list)
```

`process` içinde tracker çağrısı:

```python
        colors = profile.staffColors
        anchor_mode = profile.countAnchor

        def staff_vote(box: np.ndarray, others: list[np.ndarray]) -> bool | None:
            return vote_bgr(bgr, tuple(float(v) for v in box), [tuple(float(v) for v in o) for o in others],
                            anchor_mode, colors)

        ins, outs = self.tracker.update(dets, side_of, profile.countAnchor, blobs,
                                        (r.x, r.y, r.x + r.width, r.y + r.height),
                                        staff_vote if colors else None)
        seen = [t for t in self.tracker.tracks if t.confirmed and t.misses == 0]
        return DetectResult(seen, dets, ins, outs, line, blobs or [],
                            list(self.tracker.staff_entered), list(self.tracker.staff_exited))
```

- [ ] **Adım 4: `pipeline.py`**

`FrameResult`'a:

```python
    staff_events: list[tuple[int, int]] = field(default_factory=list)   # detect: personel (iz, +1 giriş/−1 çıkış)
```

`Pipeline.__init__` ve `reset_count` (her ikisinde `self.total_out = 0` satırının yanına):

```python
        self.total_staff_in = 0                 # detect §4.10 eki: personel geçişleri (giriş/çıkışa eklenmez)
        self.total_staff_out = 0
```

`_process_detect` içinde `outs = ...` satırından sonra:

```python
        staff = ([(t.id, 1) for t in r.staff_entries] + [(t.id, -1) for t in r.staff_exits]) if self.counting else []
        self.total_staff_in += sum(1 for _, d in staff if d > 0)
        self.total_staff_out += sum(1 for _, d in staff if d < 0)
```

`if r.tracks or ins or outs:` → `if r.tracks or ins or outs or staff:`; `res.detect = r` satırından önce `res.staff_events = staff`.

- [ ] **Adım 5: `overlay.py` `draw_detect`** — kutu rengi

```python
            col = GRAY if lab == "P" else (GREEN if lab and lab.startswith("G") else (RED if lab else WHITE))
```

- [ ] **Adım 6: Doğrula**

Çalıştır:

```bash
cd services/edge && .venv/Scripts/python -m pytest tests/test_staff_color.py tests/test_people_track.py tests/test_people_groups.py tests/test_live.py -q && .venv/Scripts/ruff check .
```

Beklenen: tümü PASS.

Gerçek videolarda renk yokken değişmezlik (yerel, kayıtlar repoda değil):

```bash
cd "$TEMP/claude/C--Users-MSI-LAPTOP-bantvision/fc59a332-3fdb-403a-9e10-e3750b4d51ca/scratchpad" && PYTHONPATH=/c/Users/MSI-LAPTOP/bantvision/services/edge /c/Users/MSI-LAPTOP/bantvision/services/edge/.venv/Scripts/python eval_people.py kisi/v.mp4 0.58 up 46.4 0
```

Beklenen: `giriş 3 çıkış 3` (v2 için `giriş 9 çıkış 3`).

- [ ] **Adım 7: Commit**

```bash
git add services/edge/bantvision/core/detect_count.py services/edge/bantvision/core/pipeline.py services/edge/bantvision/overlay.py services/edge/tests/test_staff_color.py
git commit -m "edge: tanıma sayacında personel rengi; hatta ayrı personel toplamı; çizimde P"
```

---

### Görev 7: Canlı oturum ve API (durum, CSV, öğretme uç noktası)

**Dosyalar:**
- Değiştir:
  - `services/edge/bantvision/live/session.py`
  - `services/edge/bantvision/live/api.py`
- Test: `services/edge/tests/test_live.py` (sona ekle)

**Arayüzler:**
- Tüketir: `FrameResult.staff_events`, `Pipeline.total_staff_in/out`, `staff_color.teach_bgr`, `is_achromatic`, `MAX_COLORS`.
- Üretir:
  - Durumda `staffIn`, `staffOut`.
  - CSV satırı `yon = personel_giris | personel_cikis`.
  - `LiveSession.teach_staff_color(x: float, y: float) -> tuple[float, float, float] | None` (kare yoksa `LookupError`).
  - `POST /api/v1/live/sessions/{id}/staff-color {x, y}` → `{L, a, b, achromatic}`; 422 karanlık, 503 kare yok.
  - Profil gövdesinde `staffColors` > 3 → 422.

- [ ] **Adım 1: Başarısız testleri yaz** (`test_live.py` sonuna)

```python
def test_staff_teach_endpoint_and_status(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Personel rengi öğretme: tıklanan yerin rengi döner; durumda staffIn/staffOut; en çok 3 renk."""
    monkeypatch.setenv("ANALYZER_ALLOW_FILE_SOURCES", "1")
    src = client.post("/api/v1/live/sources", json=camera(brand="custom", customUrl=str(CLIP), password="")).json()
    egg = next(p for p in client.get("/api/v1/live/profiles").json() if p["name"] == "Yumurta")
    s = client.post("/api/v1/live/sessions", json={"sourceId": src["id"], "profileId": egg["id"]}).json()
    base = f"/api/v1/live/sessions/{s['id']}"
    wait_for(lambda: client.get(f"{base}/frame.jpg").status_code == 200)
    st = client.get(base).json()
    assert st["staffIn"] == 0 and st["staffOut"] == 0

    r = client.post(f"{base}/staff-color", json={"x": 0.5, "y": 0.5})
    assert r.status_code == 200, r.text
    c = r.json()
    assert set(c) == {"L", "a", "b", "achromatic"} and 0 <= c["L"] <= 100
    assert client.post(f"{base}/staff-color", json={"x": 1.5, "y": 0.5}).status_code == 422

    prof = dict(st["profile"], staffColors=[{"L": 50, "a": 10, "b": 10}] * 4)
    assert client.put(f"{base}/profile", json=prof).status_code == 422
    prof["staffColors"] = [{"L": c["L"], "a": c["a"], "b": c["b"]}]
    assert client.put(f"{base}/profile", json=prof).json()["profile"]["staffColors"][0]["L"] == c["L"]


def test_staff_teach_rejects_dark_spot() -> None:
    import numpy as np

    from bantvision.core import Profile
    from bantvision.live.session import LiveSession

    s = LiveSession("test", lambda: "yok.mp4", Profile.egg())          # okuyucu açamaz: sahte kare ezilmez
    try:
        with s._frame_cv:
            s._latest = (1, 0.0, np.zeros((288, 352, 3), np.uint8))
        assert s.teach_staff_color(0.5, 0.5) is None
    finally:
        s.stop()
```

- [ ] **Adım 2: Testlerin başarısız olduğunu gör**

Çalıştır: `cd services/edge && .venv/Scripts/python -m pytest tests/test_live.py -q -k staff`
Beklenen: FAIL (`KeyError: 'staffIn'` / 404).

- [ ] **Adım 3: `session.py`**

İçe aktarma: `from ..core.staff_color import teach_bgr`

`_Counts`'a:

```python
    staff_in: int = 0                       # §4.10 eki: personel geçişleri (giriş/çıkışa eklenmez)
    staff_out: int = 0
```

`__init__` içinde `self._labels` satırından sonra:

```python
        self._last_boxes: list[tuple[float, float, float, float]] = []   # son karedeki tanıma kutuları (öğretme)
```

`_after_frame` içinde `if self.profile.countMode == "detect":` bloğunda `alive = ...` satırından önce:

```python
            for tid, d in r.staff_events:
                self._labels[tid] = "P"
                if d > 0:
                    c.staff_in += 1
                else:
                    c.staff_out += 1
                c.events.append((now, tid, "personel_giris" if d > 0 else "personel_cikis", n_in, n_out))
            if r.detect is not None:
                self._last_boxes = [tuple(float(v) for v in b) for b, _ in r.detect.detections]
```

`snapshot_status` sözlüğüne: `"staffIn": c.staff_in, "staffOut": c.staff_out,`

Yeni yöntem (`cancel_calibration`'dan sonra):

```python
    def teach_staff_color(self, x: float, y: float) -> tuple[float, float, float] | None:
        """Tıklanan noktadaki kişinin gövde rengi (§4.10 eki). Çok karanlıksa None; henüz kare yoksa LookupError."""
        with self._frame_cv:
            latest = self._latest
        if latest is None:
            raise LookupError("kare yok")
        return teach_bgr(latest[2], list(self._last_boxes), (x, y), self.profile.countAnchor)
```

- [ ] **Adım 4: `api.py`**

İçe aktarma: `from ..core.staff_color import MAX_COLORS, is_achromatic`

Modeller:

```python
class StaffColorIn(_Strict):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
```

`_profile_from` içinde `return` öncesi:

```python
    try:
        p = Profile.from_dict(body)
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(422, f"Profil geçersiz: {e}") from e
    if len(p.staffColors) > MAX_COLORS:
        raise HTTPException(422, f"En fazla {MAX_COLORS} personel rengi öğretilebilir.")
    return p
```

Uç nokta (`set_stream`'den sonra):

```python
    @r.post("/sessions/{session_id}/staff-color")
    def teach_staff_color(session_id: str, body: StaffColorIn) -> dict[str, Any]:
        """Personel rengini öğret: tıklanan kişinin gövde rengi (Lab). Profile eklemek panelin işi (PUT profile)."""
        s = session_or_404(session_id)
        try:
            c = s.teach_staff_color(body.x, body.y)
        except LookupError as e:
            raise HTTPException(503, "Henüz görüntü yok.") from e
        if c is None:
            raise HTTPException(422, "Burası çok karanlık; personelin üstüne tıklayın.")
        return {"L": round(c[0], 2), "a": round(c[1], 2), "b": round(c[2], 2), "achromatic": is_achromatic(c)}
```

- [ ] **Adım 5: Doğrula**

Çalıştır: `cd services/edge && .venv/Scripts/python -m pytest tests/test_live.py -q && .venv/Scripts/ruff check .`
Beklenen: tümü PASS.

- [ ] **Adım 6: Commit**

```bash
git add services/edge/bantvision/live/session.py services/edge/bantvision/live/api.py services/edge/tests/test_live.py
git commit -m "Canlı API: personel rengi öğretme, durumda ve CSV'de personel geçişleri"
```

---

### Görev 8: Web paneli — Personel rengi bölümü ve sayaç

**Dosyalar:**
- Oluştur:
  - `apps/dashboard/src/lib/staff.ts`
  - `apps/dashboard/src/components/live/StaffColors.tsx`
- Değiştir:
  - `apps/dashboard/src/lib/live.ts` (`LiveSession`)
  - `apps/dashboard/src/components/live/LiveView.tsx`
  - `apps/dashboard/e2e/live.spec.ts`

**Arayüzler:**
- Tüketir: `POST sessions/{id}/staff-color`, durumdaki `staffIn/staffOut`, `Profile.staffColors`.
- Üretir:
  - `labToCss(c: LabColor): string` (`#rrggbb`), `isAchromatic(c: LabColor): boolean`, `MAX_STAFF_COLORS = 3`.
  - `<StaffColors colors teaching onTeach onRemove />`.

- [ ] **Adım 1: e2e testini yaz** (`live.spec.ts`, ilk oturumu kapatmadan önce, yumurta yerine kişi profiliyle ayrı test)

```ts
test("kişi sayımı: personel rengi öğret, örnek görünür, sil", async ({ page }) => {
  page.on("dialog", (d) => d.accept());
  await login(page);
  await page.getByRole("radio", { name: "IP kamera" }).click();
  await page.getByLabel("Kamera markası").selectOption("custom");
  await page.getByLabel("RTSP adresi").fill(CLIP);
  await page.getByRole("textbox", { name: /^Ad/ }).fill("Giriş kamerası");
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();
  await page.getByTestId("source-card").filter({ hasText: "Giriş kamerası" }).getByRole("button", { name: "Canlı sayım" }).click();
  const dialog = page.getByRole("dialog", { name: "Canlı sayımı başlat" });
  await dialog.getByRole("button", { name: /^Mağaza girişi/ }).click();
  await dialog.getByRole("button", { name: "Başlat", exact: true }).click();
  await expect(page.getByTestId("live-state")).toContainText("Canlı", { timeout: 30_000 });

  await page.getByRole("button", { name: "Ayarla" }).click();
  const staff = page.getByRole("group", { name: "Personel rengi" });
  await expect(staff.getByText("Kapalı — tüm geçişler sayılır.")).toBeVisible();
  await staff.getByRole("button", { name: "Personel rengini öğret" }).click();
  await page.getByRole("button", { name: "Görüntüde personelin üstüne tıklayın" }).click({ position: { x: 200, y: 200 } });
  await expect(staff.getByTestId("staff-swatch")).toHaveCount(1);
  await staff.getByRole("button", { name: "1. personel rengini sil" }).click();
  await expect(staff.getByTestId("staff-swatch")).toHaveCount(0);
  await page.getByRole("button", { name: "İptal" }).click();
  await page.getByRole("button", { name: "Canlı sayımı kapat" }).click();
  await expect(page.getByText("Açık canlı sayım yok")).toBeVisible();
  await page.getByRole("link", { name: "Kameralara git" }).click();
  await page.getByTestId("source-card").filter({ hasText: "Giriş kamerası" }).getByRole("button", { name: "Sil" }).click();
});
```

Not: kişi oturumu CI'da tanıma modelini ilk karede indirir. Öğretme modelden bağımsızdır (kutu yoksa tıklanan yer çevresi).

- [ ] **Adım 2: `lib/staff.ts`**

```ts
import type { LabColor } from "./live";

export const MAX_STAFF_COLORS = 3;

/** Lab (D65) → ekranda gösterilecek sRGB (#rrggbb); Python/Swift çevirisinin tersi */
export function labToCss(c: LabColor): string {
  const fy = (c.L + 16) / 116, fx = fy + c.a / 500, fz = fy - c.b / 200;
  const inv = (t: number) => (t ** 3 > 0.008856 ? t ** 3 : (t - 16 / 116) / 7.787);
  const X = 0.95047 * inv(fx), Y = inv(fy), Z = 1.08883 * inv(fz);
  const lin = [
    3.2404542 * X - 1.5371385 * Y - 0.4985314 * Z,
    -0.969266 * X + 1.8760108 * Y + 0.041556 * Z,
    0.0556434 * X - 0.2040259 * Y + 1.0572252 * Z,
  ];
  const hex = lin.map((v) => {
    const s = v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055;
    return Math.round(Math.min(1, Math.max(0, s)) * 255).toString(16).padStart(2, "0");
  });
  return `#${hex.join("")}`;
}

/** Siyah, beyaz, gri, lacivert gibi renkler müşterilerde de sık görülür (Python is_achromatic ile aynı eşik) */
export const isAchromatic = (c: LabColor) => Math.hypot(c.a, c.b) < 15;
```

- [ ] **Adım 3: `components/live/StaffColors.tsx`**

```tsx
"use client";

import type { LabColor } from "@/lib/live";
import { isAchromatic, labToCss, MAX_STAFF_COLORS } from "@/lib/staff";

/** Kişi sayımı ayarı: personel üniforma renkleri (§4.10 eki). Öğretmede görüntüde personelin üstüne tıklanır. */
export default function StaffColors({ colors, teaching, onTeach, onRemove }: {
  colors: LabColor[]; teaching: boolean; onTeach: (on: boolean) => void; onRemove: (i: number) => void;
}) {
  const full = colors.length >= MAX_STAFF_COLORS;
  return (
    <div role="group" aria-label="Personel rengi">
      <div className="mb-1.5 flex items-center justify-between">
        <p className="text-xs font-medium text-muted">Personel rengi</p>
        <button type="button" onClick={() => onTeach(!teaching)} disabled={!teaching && full}
                className="h-8 rounded-[9px] border border-line px-2.5 text-[12.5px] font-medium hover:border-brand-100 disabled:opacity-50">
          {teaching ? "Vazgeç" : "Personel rengini öğret"}
        </button>
      </div>
      {teaching && <p className="mb-1.5 rounded-lg bg-warn-50 px-2.5 py-1.5 text-[12px] text-warn-700">Görüntüde bir personelin gövdesine tıklayın.</p>}
      {colors.length === 0 ? (
        <p className="text-[11.5px] text-faint">Kapalı — tüm geçişler sayılır.</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {colors.map((c, i) => (
            <span key={i} data-testid="staff-swatch" className="inline-flex items-center gap-1 rounded-full border border-line py-0.5 pl-0.5 pr-1.5">
              <span aria-hidden="true" className="h-6 w-6 rounded-full border border-black/10" style={{ background: labToCss(c) }} />
              <button type="button" aria-label={`${i + 1}. personel rengini sil`} onClick={() => onRemove(i)}
                      className="grid h-5 w-5 place-items-center rounded-full text-muted hover:bg-nok-50 hover:text-nok-600">×</button>
            </span>
          ))}
        </div>
      )}
      {colors.some(isAchromatic) && (
        <p className="mt-1.5 text-[11.5px] text-warn-700">Bu renk müşterilerde de sık görülür; müşteri yanlışlıkla düşülebilir.</p>
      )}
      {full && !teaching && <p className="mt-1 text-[11.5px] text-faint">En fazla {MAX_STAFF_COLORS} renk.</p>}
      <p className="mt-1 text-[11.5px] text-faint">Bu renkte giyinenlerin geçişi giriş/çıkışa eklenmez, ayrı sayılır.</p>
    </div>
  );
}
```

- [ ] **Adım 4: `lib/live.ts` — `LiveSession`'a**

```ts
  /** Kişi sayımı: personel geçişleri (giriş/çıkışa eklenmez) */
  staffIn: number;
  staffOut: number;
```

- [ ] **Adım 5: `LiveView.tsx`**

İçe aktarma: `import StaffColors from "./StaffColors";`

Durum (diğer `useState`'lerin yanına): `const [teaching, setTeaching] = useState(false);`

Öğretme işlevi (`flipEntry`'den sonra):

```tsx
  async function teachAt(e: React.MouseEvent<HTMLButtonElement>) {
    if (!session || !draft) return;
    const r = e.currentTarget.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
    try {
      const c = await api<LabColor & { achromatic: boolean }>(`sessions/${session.id}/staff-color`, { method: "POST", json: { x, y } });
      edit({ ...draft, staffColors: [...(draft.staffColors ?? []), { L: c.L, a: c.a, b: c.b }] });
      setTeaching(false);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }
```

(`LabColor` tipini `@/lib/live`'den içe aktar.) `finishCalibration` başına `setTeaching(false);` ekle.

`RoiEditor` çağrısı:

```tsx
            <RoiEditor src={`/api/live/sessions/${session.id}/frame.jpg?t=${frameTick}`} aspect={aspect}
                       value={g} onChange={(ng: Geometry) => edit(withGeometry(p, ng))} twoWay={twoWay} editable={!teaching}>
              {teaching && (
                <button type="button" aria-label="Görüntüde personelin üstüne tıklayın" onClick={teachAt}
                        className="absolute inset-0 cursor-crosshair outline-none ring-2 ring-inset ring-warn-500" />
              )}
            </RoiEditor>
```

Ayarla panelinde, `twoWay` dalında "Kamera" bölümünün altına:

```tsx
                    <div className="mt-3">
                      <StaffColors colors={p.staffColors ?? []} teaching={teaching} onTeach={setTeaching}
                                   onRemove={(i) => edit({ ...p, staffColors: (p.staffColors ?? []).filter((_, k) => k !== i) })} />
                    </div>
```

Sayım bölümünde, `twoWay` sayaçlarının altına:

```tsx
              {twoWay && (p.staffColors?.length ?? 0) > 0 && (
                <p className="mt-2 text-center text-[12.5px] text-muted" data-testid="live-staff">
                  Personel geçişi: <b className="tabular-nums text-ink">{int(session.staffIn + session.staffOut)}</b>
                </p>
              )}
```

- [ ] **Adım 6: Doğrula**

Çalıştır:

```bash
cd apps/dashboard && npx eslint src e2e && npx tsc --noEmit && npm run build && PYTHON=../../services/edge/.venv/Scripts/python npx playwright test
```

Beklenen: lint/tip temiz, tüm e2e PASS.

- [ ] **Adım 7: Commit**

```bash
git add apps/dashboard/src/lib/staff.ts apps/dashboard/src/components/live/StaffColors.tsx apps/dashboard/src/lib/live.ts apps/dashboard/src/components/live/LiveView.tsx apps/dashboard/e2e/live.spec.ts
git commit -m "Panel: kişi sayımında personel rengi öğretme ve personel geçişi sayacı"
```

---

### Görev 9: Swift çekirdeği — `StaffColor` ve izleyici

**Dosyalar:**
- Değiştir:
  - `apps/ios/BantSayac/Vision/StaffColor.swift` (Görev 2'deki tipin altına)
  - `apps/ios/BantSayac/Vision/PeopleTracker.swift`
- Test: `apps/ios/BantSayacTests/StaffColorTests.swift` (yeni; `staff_parity.json` aynı klasörde, XcodeGen kaynak olarak paketler)

**Arayüzler:**
- Tüketir: `staff_parity.json` biçimi (Görev 5).
- Üretir:
  - `enum StaffColor` (sabitler, `lab(_:_:_:)`, `labs(_:)`, `torsoRegion`, `gridPoints`, `pixel`, `distance`, `voteLabs`, `vote(box:others:anchor:colors:width:height:rgbAt:)`, `isStaff`, `isAchromatic`, `dominant`, `teach(...)`, `srgb(from:)`).
  - `MotTrack.votes/staffVotes/staffCrossings`.
  - `MotTracker.update(..., staffVote: ((NBox, [NBox]) -> Bool?)? = nil)`, `staffEntered/staffExited`.

- [ ] **Adım 1: Başarısız testi yaz** — `StaffColorTests.swift`

```swift
import XCTest
@testable import BantSayac

/// Personel rengi (§4.10 eki): Python referansıyla eşdeğerlik — staff_parity.json (tools/make_staff_fixture.py)
final class StaffColorTests: XCTestCase {
    private struct Fixture: Decodable {
        struct Points: Decodable { let w: Int; let h: Int; let box: [Double]; let anchor: String; let pts: [[Int]] }
        struct Vote: Decodable { let rgb: [[Int]]; let colors: [[Double]]; let vote: Bool? }
        struct Dominant: Decodable { let rgb: [[Int]]; let lab: [Double]? }
        struct Frame: Decodable { let d: [[Double]]; let v: [Int] }
        struct Scenario: Decodable { let name: String; let line: Double; let maxAge: Int; let frames: [Frame]; let events: [[Int]] }
        let lab: [[Double]]
        let points: [Points]
        let votes: [Vote]
        let dominant: [Dominant]
        let tracker: [Scenario]
    }

    private func fixture() throws -> Fixture {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "staff_parity", withExtension: "json"))
        return try JSONDecoder().decode(Fixture.self, from: Data(contentsOf: url))
    }

    private func labs(_ rgb: [[Int]]) -> [LabColor] { rgb.map { StaffColor.lab(UInt8($0[0]), UInt8($0[1]), UInt8($0[2])) } }

    func testLabConversionMatchesPython() throws {
        for row in try fixture().lab {
            let c = StaffColor.lab(UInt8(row[0]), UInt8(row[1]), UInt8(row[2]))
            XCTAssertEqual(c.L, row[3], accuracy: 1e-4); XCTAssertEqual(c.a, row[4], accuracy: 1e-4); XCTAssertEqual(c.b, row[5], accuracy: 1e-4)
        }
    }

    func testGridPointsMatchPython() throws {
        for p in try fixture().points {
            let box = NBox(x1: p.box[0], y1: p.box[1], x2: p.box[2], y2: p.box[3])
            let got = StaffColor.gridPoints(StaffColor.torsoRegion(box, CountAnchor(rawValue: p.anchor)!))
                .map { StaffColor.pixel($0.x, $0.y, width: p.w, height: p.h) }.map { [$0.0, $0.1] }
            XCTAssertEqual(got, p.pts)
        }
    }

    func testVotesMatchPython() throws {
        for v in try fixture().votes {
            let colors = v.colors.map { LabColor(L: $0[0], a: $0[1], b: $0[2]) }
            XCTAssertEqual(StaffColor.voteLabs(labs(v.rgb), colors: colors), v.vote)
        }
    }

    func testDominantMatchesPython() throws {
        for d in try fixture().dominant {
            let c = StaffColor.dominant(labs(d.rgb))
            if let ref = d.lab {
                let got = try XCTUnwrap(c)
                XCTAssertEqual(got.L, ref[0], accuracy: 1e-4); XCTAssertEqual(got.a, ref[1], accuracy: 1e-4); XCTAssertEqual(got.b, ref[2], accuracy: 1e-4)
            } else {
                XCTAssertNil(c)
            }
        }
    }

    func testTrackerStaffDecisionsMatchPython() throws {
        for s in try fixture().tracker {
            var params = MotParams()
            params.maxAge = s.maxAge
            let tracker = MotTracker(params: params)
            var got: [[Int]] = []
            for (k, f) in s.frames.enumerated() {
                let dets = f.d.map { Detection(box: NBox(x1: $0[0], y1: $0[1], x2: $0[2], y2: $0[3]), score: $0[4]) }
                var voteOf: [NBox: Bool?] = [:]
                for (d, v) in zip(dets, f.v) { voteOf[d.box] = v < 0 ? nil : (v == 1) }
                let (ins, outs) = tracker.update(dets, sideOf: { _, y in y - s.line },
                                                 staffVote: { box, _ in voteOf[box] ?? nil })
                got += ins.map { [k, $0.id, 1, 0] } + outs.map { [k, $0.id, -1, 0] }
                got += tracker.staffEntered.map { [k, $0.id, 1, 1] } + tracker.staffExited.map { [k, $0.id, -1, 1] }
            }
            XCTAssertEqual(got, s.events, "\(s.name): Swift ve Python personel kararları farklı")
        }
    }

    func testSafetyRules() {
        XCTAssertFalse(StaffColor.isStaff(votes: 2, staffVotes: 2))
        XCTAssertTrue(StaffColor.isStaff(votes: 4, staffVotes: 2))
        XCTAssertTrue(StaffColor.isAchromatic(StaffColor.lab(25, 35, 80)))
        XCTAssertFalse(StaffColor.isAchromatic(StaffColor.lab(240, 120, 20)))
    }
}
```

`NBox` sözlük anahtarı olacağı için `PeopleTracker.swift`'te `struct NBox: Equatable` → `struct NBox: Equatable, Hashable`.

- [ ] **Adım 2: `StaffColor.swift` fonksiyonları** (`LabColor` tipinin altına)

```swift
/// Personel rengi (algoritma §4.10 eki). Python referansı: services/edge/bantvision/core/staff_color.py —
/// davranış birebir aynı (BantSayacTests/StaffColorTests + staff_parity.json).
enum StaffColor {
    static let grid = 12
    static let matchDist = 20.0
    static let minFraction = 0.25
    static let minPoints = 36
    static let darkL = 8.0
    static let minVotes = 3
    static let achromaticC = 15.0
    static let teachPatch = 0.06
    static let maxColors = 3
    static let minBoxPx = (w: 8.0, h: 16.0)

    private static func lin(_ v: UInt8) -> Double {
        let c = Double(v) / 255
        return c <= 0.04045 ? c / 12.92 : pow((c + 0.055) / 1.055, 2.4)
    }

    private static func f(_ t: Double) -> Double { t > 0.008856 ? cbrt(t) : 7.787 * t + 16.0 / 116.0 }

    static func lab(_ r: UInt8, _ g: UInt8, _ b: UInt8) -> LabColor {
        let R = lin(r), G = lin(g), B = lin(b)
        let x = (R * 0.4124564 + G * 0.3575761 + B * 0.1804375) / 0.95047
        let y = (R * 0.2126729 + G * 0.7151522 + B * 0.0721750) / 1.0
        let z = (R * 0.0193339 + G * 0.1191920 + B * 0.9503041) / 1.08883
        let fx = f(x), fy = f(y), fz = f(z)
        return LabColor(L: 116 * fy - 16, a: 500 * (fx - fy), b: 200 * (fy - fz))
    }

    /// Lab → sRGB (0–1), yalnızca ekranda örnek göstermek için
    static func srgb(from c: LabColor) -> (r: Double, g: Double, b: Double) {
        let fy = (c.L + 16) / 116, fx = fy + c.a / 500, fz = fy - c.b / 200
        func inv(_ t: Double) -> Double { t * t * t > 0.008856 ? t * t * t : (t - 16.0 / 116.0) / 7.787 }
        let X = 0.95047 * inv(fx), Y = inv(fy), Z = 1.08883 * inv(fz)
        func gamma(_ v: Double) -> Double { min(1, max(0, v <= 0.0031308 ? 12.92 * v : 1.055 * pow(v, 1 / 2.4) - 0.055)) }
        return (gamma(3.2404542 * X - 1.5371385 * Y - 0.4985314 * Z),
                gamma(-0.969266 * X + 1.8760108 * Y + 0.041556 * Z),
                gamma(0.0556434 * X - 0.2040259 * Y + 1.0572252 * Z))
    }

    static func torsoRegion(_ box: NBox, _ anchor: CountAnchor) -> NBox {
        let w = box.x2 - box.x1, h = box.y2 - box.y1
        let (t0, t1) = anchor == .bottom ? (0.15, 0.45) : (0.30, 0.70)
        return NBox(x1: box.x1 + 0.30 * w, y1: box.y1 + t0 * h, x2: box.x1 + 0.70 * w, y2: box.y1 + t1 * h)
    }

    static func gridPoints(_ r: NBox) -> [(x: Double, y: Double)] {
        let rw = r.x2 - r.x1, rh = r.y2 - r.y1, n = Double(grid)
        var out: [(x: Double, y: Double)] = []
        out.reserveCapacity(grid * grid)
        for j in 0..<grid {
            let y = r.y1 + (Double(j) + 0.5) / n * rh
            for i in 0..<grid { out.append((r.x1 + (Double(i) + 0.5) / n * rw, y)) }
        }
        return out
    }

    static func pixel(_ x: Double, _ y: Double, width: Int, height: Int) -> (Int, Int) {
        (min(max(Int(floor(x * Double(width))), 0), width - 1), min(max(Int(floor(y * Double(height))), 0), height - 1))
    }

    static func distance(_ p: LabColor, _ q: LabColor) -> Double {
        let dl = 0.5 * (p.L - q.L), da = p.a - q.a, db = p.b - q.b
        return (dl * dl + da * da + db * db).squareRoot()
    }

    static func voteLabs(_ labs: [LabColor], colors: [LabColor]) -> Bool? {
        guard labs.count >= minPoints, !colors.isEmpty else { return nil }
        let hits = labs.filter { p in p.L >= darkL && colors.contains { distance(p, $0) < matchDist } }.count
        return Double(hits) >= minFraction * Double(labs.count)
    }

    private static func inside(_ o: NBox, _ x: Double, _ y: Double) -> Bool { o.x1 <= x && x <= o.x2 && o.y1 <= y && y <= o.y2 }

    /// Bu karede tanımayla gözlenen kutunun oyu; `others`: aynı karedeki diğer tanıma kutuları (noktaları dışlanır)
    static func vote(box: NBox, others: [NBox], anchor: CountAnchor, colors: [LabColor], width: Int, height: Int,
                     rgbAt: (Int, Int) -> (UInt8, UInt8, UInt8)) -> Bool? {
        guard (box.x2 - box.x1) * Double(width) >= minBoxPx.w, (box.y2 - box.y1) * Double(height) >= minBoxPx.h else { return nil }
        let pts = gridPoints(torsoRegion(box, anchor)).filter { p in !others.contains { inside($0, p.x, p.y) } }
        guard pts.count >= minPoints else { return nil }
        let labs = pts.map { p -> LabColor in
            let (px, py) = pixel(p.x, p.y, width: width, height: height)
            let c = rgbAt(px, py)
            return lab(c.0, c.1, c.2)
        }
        return voteLabs(labs, colors: colors)
    }

    static func isStaff(votes: Int, staffVotes: Int) -> Bool { votes >= minVotes && 2 * staffVotes >= votes }

    static func isAchromatic(_ c: LabColor) -> Bool { hypot(c.a, c.b) < achromaticC }

    private static func median(_ v: [Double]) -> Double {
        let s = v.sorted(), n = s.count
        return n % 2 == 1 ? s[n / 2] : (s[n / 2 - 1] + s[n / 2]) / 2
    }

    /// (⌊a/8⌋, ⌊b/8⌋) kutucuklarından en kalabalığı (eşitlikte ilk görülen); o kutucuğun L, a, b medyanı
    static func dominant(_ labs: [LabColor]) -> LabColor? {
        guard !labs.isEmpty else { return nil }
        var order: [[Int]] = []
        var bins: [[Int]: [Int]] = [:]
        for (k, c) in labs.enumerated() {
            let key = [Int(floor(c.a / 8)), Int(floor(c.b / 8))]
            if bins[key] == nil { order.append(key) }
            bins[key, default: []].append(k)
        }
        var best = order[0]
        for key in order where bins[key]!.count > bins[best]!.count { best = key }
        let sel = bins[best]!.map { labs[$0] }
        let c = LabColor(L: median(sel.map(\.L)), a: median(sel.map(\.a)), b: median(sel.map(\.b)))
        return c.L < darkL ? nil : c
    }

    /// Tıklanan noktayı içeren en küçük kutunun gövdesi; kutu yoksa tıklanan yer çevresi. Çok karanlıksa nil
    static func teach(boxes: [NBox], point: (x: Double, y: Double), anchor: CountAnchor, width: Int, height: Int,
                      rgbAt: (Int, Int) -> (UInt8, UInt8, UInt8)) -> LabColor? {
        let containing = boxes.filter { inside($0, point.x, point.y) }
        let region: NBox
        if let b = containing.min(by: { $0.area < $1.area }) {
            region = torsoRegion(b, anchor)
        } else {
            let hx = teachPatch / 2, hy = teachPatch / 2 * Double(width) / Double(height)
            region = NBox(x1: max(0, point.x - hx), y1: max(0, point.y - hy), x2: min(1, point.x + hx), y2: min(1, point.y + hy))
        }
        let labs = gridPoints(region).map { p -> LabColor in
            let (px, py) = pixel(p.x, p.y, width: width, height: height)
            let c = rgbAt(px, py)
            return lab(c.0, c.1, c.2)
        }
        return dominant(labs)
    }
}
```

Not: Python `min(inside, key=alan)` eşitlikte ilkini, Swift `min(by:)` de ilkini döndürür.

- [ ] **Adım 3: `PeopleTracker.swift` — Python Görev 4'ün aynısı**

`MotTrack`'a (`lastDet`'ten sonra):

```swift
    /// Personel rengi oyu verilen kare sayısı ve bunların personel oyu olanları (§4.10 eki)
    var votes = 0
    var staffVotes = 0
    /// Personel geçişleri (giriş/çıkışa eklenmez)
    var staffCrossings = 0
```

`MotTracker`'a özellikler:

```swift
    /// Son karede personel geçişi yapan izler (§4.10 eki; `update` dönüşüne girmez)
    private(set) var staffEntered: [MotTrack] = []
    private(set) var staffExited: [MotTrack] = []
```

`update` imzası:

```swift
    func update(_ input: [Detection], sideOf: (Double, Double) -> Double, anchor: CountAnchor = .center,
                motion: [NBox]? = nil, bounds: NBox = NBox(x1: 0, y1: 0, x2: 1, y2: 1),
                staffVote: ((NBox, [NBox]) -> Bool?)? = nil)
        -> (entered: [MotTrack], exited: [MotTrack]) {
        staffEntered = []
        staffExited = []
```

Eşleşen tespitte `observeUpdate(t, dets[di].box, fromDet: true, ...)` öncesi:

```swift
                vote(t, di, dets, staffVote)
```

Yeni iz döngüsü ve `newTrack`:

```swift
        for di in high where !used.contains(di) {
            newTrack(dets[di].box, dets[di].score, verified: true, sideOf, anchor, &entered, &exited) { t in
                self.vote(t, di, dets, staffVote)
            }
        }
```

```swift
    private func vote(_ t: MotTrack, _ di: Int, _ dets: [Detection], _ staffVote: ((NBox, [NBox]) -> Bool?)?) {
        guard let staffVote else { return }
        let others = dets.indices.filter { $0 != di }.map { dets[$0].box }
        if let v = staffVote(dets[di].box, others) {
            t.votes += 1
            if v { t.staffVotes += 1 }
        }
    }

    private func newTrack(_ box: NBox, _ score: Double, verified: Bool, _ sideOf: (Double, Double) -> Double,
                          _ anchor: CountAnchor, _ entered: inout [MotTrack], _ exited: inout [MotTrack],
                          beforeObserve: ((MotTrack) -> Void)? = nil) {
        let t = MotTrack(id: nextId, box: box, vel: .zero, last: box, score: score, verified: verified, born: frame)
        t.hist.append((frame, box))
        nextId += 1
        tracks.append(t)
        beforeObserve?(t)
        observe(t, sideOf, anchor, &entered, &exited)
    }
```

`observe` içindeki sayım bloğu:

```swift
        if t.confirmed && !t.pending.isEmpty {
            let staff = StaffColor.isStaff(votes: t.votes, staffVotes: t.staffVotes)
            for x in t.pending {
                if staff {                                              // §4.10 eki: personel müşteri sayılmaz
                    t.staffCrossings += 1
                    if x > 0 { staffEntered.append(t) } else { staffExited.append(t) }
                } else if x > 0 {
                    t.entries += 1
                    entered.append(t)
                } else {
                    t.exits += 1
                    exited.append(t)
                }
            }
            t.pending = []
        }
```

`dets` burada bastırma sonrası dizi (Python `boxes` ile aynı) — `vote` çağrıları `dets` değişkenini kullanır, `input`'u değil.

- [ ] **Adım 4: CI'da doğrula** (Xcode yerelde yok)

```bash
git add apps/ios/BantSayac/Vision/StaffColor.swift apps/ios/BantSayac/Vision/PeopleTracker.swift apps/ios/BantSayacTests/StaffColorTests.swift
git commit -m "iOS: personel rengi çekirdeği ve izleyicide personel geçişi (Python ile eşdeğer)"
git push
gh run watch $(gh run list --workflow ios --limit 1 --json databaseId -q '.[0].databaseId') --exit-status
```

Beklenen: `ios` işi yeşil (derleme, strict concurrency 0 uyarı, `StaffColorTests` ve `PeopleTrackerTests` geçer).

---

### Görev 10: iPhone hattı ve arayüzü

**Dosyalar:**
- Değiştir:
  - `apps/ios/BantSayac/Vision/PeopleCounter.swift`
  - `apps/ios/BantSayac/Vision/FrameProcessor.swift`
  - `apps/ios/BantSayac/UI/CountingViewModel.swift`
  - `apps/ios/BantSayac/UI/CalibrationPanel.swift`
  - `apps/ios/BantSayac/UI/PeopleViews.swift`
  - `apps/ios/BantSayac/UI/OverlayView.swift`
  - `apps/ios/BantSayac/UI/ContentView.swift`

**Arayüzler:**
- Tüketir: `StaffColor.vote/teach`, `MotTracker.staffEntered/staffExited`.
- Üretir:
  - `PeopleFrame.staffEntered/staffExited`.
  - `PeopleCounter.lastBoxes`.
  - `FrameProcessor.onStaff: (@MainActor (Int, Int) -> Void)?`, `onStaffColor: (@MainActor (LabColor?) -> Void)?`, `teachStaffColor(at:)`, `setStaffTotals(in:out:)`.
  - VM `staffIn`, `staffOut`, `teachingStaff`, `teachStaffColor(at:)`, `removeStaffColor(at:)`.
  - `PersonMarker.isStaff`.

- [ ] **Adım 1: YUV örnekleyici ve sayaç** — `PeopleCounter.swift`

Dosya sonuna:

```swift
/// 420f/420v piksel tamponundan tek noktada sRGB (yalnızca örnek noktalarında; tüm kare çevrilmez).
/// Matris tampondaki eke göre (BT.709 ya da BT.601).
enum YUVSampler {
    /// `body`'nin aldığı okuyucu yalnızca `body` süresince geçerlidir (tampon kilitli); izleyiciye oy kapanışı içinde
    /// verildiği için `@escaping` (optional kapanış parametresi kaçan sayılır), ama `body` dışında saklanmaz.
    static func with<T>(_ pb: CVPixelBuffer, _ body: (Int, Int, @escaping (Int, Int) -> (UInt8, UInt8, UInt8)) -> T) -> T? {
        let format = CVPixelBufferGetPixelFormatType(pb)
        guard format == kCVPixelFormatType_420YpCbCr8BiPlanarFullRange
                || format == kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange,
              CVPixelBufferGetPlaneCount(pb) == 2 else { return nil }
        let full = format == kCVPixelFormatType_420YpCbCr8BiPlanarFullRange
        let matrix = CVBufferCopyAttachment(pb, kCVImageBufferYCbCrMatrixKey, nil) as? String
        let bt709 = matrix == (kCVImageBufferYCbCrMatrix_ITU_R_709_2 as String)
        CVPixelBufferLockBaseAddress(pb, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pb, .readOnly) }
        guard let yBase = CVPixelBufferGetBaseAddressOfPlane(pb, 0),
              let cBase = CVPixelBufferGetBaseAddressOfPlane(pb, 1) else { return nil }
        let w = CVPixelBufferGetWidth(pb), h = CVPixelBufferGetHeight(pb)
        let yStride = CVPixelBufferGetBytesPerRowOfPlane(pb, 0), cStride = CVPixelBufferGetBytesPerRowOfPlane(pb, 1)
        let yp = yBase.assumingMemoryBound(to: UInt8.self), cp = cBase.assumingMemoryBound(to: UInt8.self)
        let rgb: (Int, Int) -> (UInt8, UInt8, UInt8) = { x, y in
            var Y = Double(yp[y * yStride + x])
            var cb = Double(cp[(y / 2) * cStride + (x / 2) * 2]) - 128
            var cr = Double(cp[(y / 2) * cStride + (x / 2) * 2 + 1]) - 128
            if !full { Y = (Y - 16) * 255 / 219; cb *= 255 / 224; cr *= 255 / 224 }
            let r, g, b: Double
            if bt709 { r = Y + 1.5748 * cr; g = Y - 0.1873 * cb - 0.4681 * cr; b = Y + 1.8556 * cb }
            else { r = Y + 1.402 * cr; g = Y - 0.344136 * cb - 0.714136 * cr; b = Y + 1.772 * cb }
            func u8(_ v: Double) -> UInt8 { UInt8(min(255, max(0, v.rounded()))) }
            return (u8(r), u8(g), u8(b))
        }
        return body(w, h, rgb)
    }
}
```

`PeopleFrame`'e:

```swift
    var staffEntered: [MotTrack] = []
    var staffExited: [MotTrack] = []
```

`PeopleCounter`'a `private(set) var lastBoxes: [NBox] = []`.

`process` içinde `tracker.update` çağrısı:

```swift
        lastBoxes = dets.map(\.box)
        let colors = profile.staffColors ?? []
        let anchor = profile.anchor
        let update = { (vote: ((NBox, [NBox]) -> Bool?)?) in
            self.tracker.update(dets, sideOf: side, anchor: anchor, motion: blobs,
                                bounds: NBox(x1: Double(r.minX), y1: Double(r.minY), x2: Double(r.maxX), y2: Double(r.maxY)),
                                staffVote: vote)
        }
        let result: (entered: [MotTrack], exited: [MotTrack])
        if colors.isEmpty {
            result = update(nil)
        } else {
            result = YUVSampler.with(pb) { w, h, rgbAt in
                update { box, others in
                    StaffColor.vote(box: box, others: others, anchor: anchor, colors: colors, width: w, height: h, rgbAt: rgbAt)
                }
            } ?? update(nil)
        }
        let seen = tracker.tracks.filter { $0.confirmed && $0.misses == 0 }
        return PeopleFrame(tracks: seen, entered: result.entered, exited: result.exited, line: line,
                           staffEntered: tracker.staffEntered, staffExited: tracker.staffExited)
```

- [ ] **Adım 2: `FrameProcessor.swift`**

`PersonMarker`'a: `var isStaff: Bool { label == "P" }`

Özellikler (`totalOut` yanına):

```swift
    private var staffIn = 0
    private var staffOut = 0
    /// Personel rengi öğretme isteği: sonraki kişi karesinde bu noktadan renk alınır (normalize)
    private var pendingTeach: CGPoint?
```

Geri çağrılar (`onCrossing`'den sonra):

```swift
    /// Kişi sayımı §4.10 eki: personel geçişi toplamları (giriş, çıkış)
    var onStaff: (@MainActor (_ staffIn: Int, _ staffOut: Int) -> Void)?
    /// Personel rengi öğretme sonucu (çok karanlıksa nil)
    var onStaffColor: (@MainActor (LabColor?) -> Void)?
```

Denetim:

```swift
    func setStaffTotals(in sIn: Int, out sOut: Int) { queue.async { self.staffIn = sIn; self.staffOut = sOut } }
    func teachStaffColor(at p: CGPoint) { queue.async { self.pendingTeach = p } }
```

`processPeople` içinde `if counting && ...` bloğundan sonra:

```swift
        if counting && (!r.staffEntered.isEmpty || !r.staffExited.isEmpty) {
            for t in r.staffEntered + r.staffExited { personLabels[t.id] = "P" }
            staffIn += r.staffEntered.count
            staffOut += r.staffExited.count
            let sIn = staffIn, sOut = staffOut
            DispatchQueue.main.async { [weak self] in self?.onStaff?(sIn, sOut) }
        }
        if let p = pendingTeach {
            pendingTeach = nil
            let boxes = people.lastBoxes, anchor = profile.anchor
            let color = YUVSampler.with(pb) { w, h, rgbAt in
                StaffColor.teach(boxes: boxes, point: (Double(p.x), Double(p.y)), anchor: anchor, width: w, height: h, rgbAt: rgbAt)
            } ?? nil
            DispatchQueue.main.async { [weak self] in self?.onStaffColor?(color) }
        }
```

- [ ] **Adım 3: `CountingViewModel.swift`**

Özellikler:

```swift
    /// Kişi sayımı: personel geçişleri (giriş/çıkışa eklenmez; yalnızca ekranda)
    @Published private(set) var staffIn = 0
    @Published private(set) var staffOut = 0
    /// Personel rengi öğretme modu: görüntüde dokunulan kişinin gövde rengi alınır
    @Published var teachingStaff = false
```

`init` içindeki geri çağrılara:

```swift
        processor.onStaff = { [weak self] sIn, sOut in
            self?.staffIn = sIn
            self?.staffOut = sOut
        }
        processor.onStaffColor = { [weak self] color in
            guard let self else { return }
            guard let color else {
                self.calibrationMessage = "Burası çok karanlık; personelin üstüne dokunun."
                return
            }
            var colors = self.profile.staffColors ?? []
            guard colors.count < StaffColor.maxColors else { return }
            colors.append(color)
            self.profile.staffColors = colors
        }
```

Yöntemler:

```swift
    func teachStaffColor(at p: CGPoint) {
        teachingStaff = false
        processor.teachStaffColor(at: p)
    }

    func removeStaffColor(at i: Int) {
        guard var colors = profile.staffColors, colors.indices.contains(i) else { return }
        colors.remove(at: i)
        profile.staffColors = colors.isEmpty ? nil : colors
    }
```

`reset()` içine:

```swift
        staffIn = 0
        staffOut = 0
        processor.setStaffTotals(in: 0, out: 0)
```

`saveCalibration()` ve kalibrasyondan çıkış yollarına (`finishCalibration`): `teachingStaff = false`.

- [ ] **Adım 4: Arayüz**

`CalibrationPanel.swift`, `if vm.profile.isTwoWay {` dalında `lineModePicker`'dan sonra `staffSection` ve özellik:

```swift
    /// Kişi sayımı §4.10 eki: personel üniforma renkleri (en çok 3)
    private var staffSection: some View {
        let colors = vm.profile.staffColors ?? []
        return VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("Personel rengi").font(.subheadline.weight(.semibold))
                Spacer()
                Button(vm.teachingStaff ? "Vazgeç" : "Personel rengini öğret") { vm.teachingStaff.toggle() }
                    .disabled(!vm.teachingStaff && colors.count >= StaffColor.maxColors)
                    .accessibilityIdentifier("teachStaff")
            }
            if vm.teachingStaff {
                Text("Görüntüde bir personelin gövdesine dokunun.").font(.caption2).foregroundStyle(.yellow)
            }
            if colors.isEmpty {
                Text("Kapalı — tüm geçişler sayılır.").font(.caption2).foregroundStyle(.secondary)
            } else {
                HStack(spacing: 8) {
                    ForEach(Array(colors.enumerated()), id: \.offset) { i, c in
                        let s = StaffColor.srgb(from: c)
                        Button { vm.removeStaffColor(at: i) } label: {
                            HStack(spacing: 4) {
                                Circle().fill(Color(red: s.r, green: s.g, blue: s.b)).frame(width: 22, height: 22)
                                Image(systemName: "xmark.circle.fill").font(.caption)
                            }
                        }
                        .accessibilityLabel("\(i + 1). personel rengini sil")
                    }
                }
                if colors.contains(where: StaffColor.isAchromatic) {
                    Text("Bu renk müşterilerde de sık görülür; müşteri yanlışlıkla düşülebilir.")
                        .font(.caption2).foregroundStyle(.orange)
                }
            }
            Text("Bu renkte giyinenlerin geçişi giriş/çıkışa eklenmez, ayrı sayılır.")
                .font(.caption2).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
        }
    }
```

`PeopleViews.swift` `PeopleCounters.body`:

```swift
    var body: some View {
        VStack(spacing: 6) {
            HStack(spacing: 10) {
                CounterTile(title: "Giriş", value: vm.total, icon: "figure.walk.arrival", color: .green,
                            compact: compact, identifier: "countIn")
                CounterTile(title: "Çıkış", value: vm.totalOut, icon: "figure.walk.departure", color: .orange,
                            compact: compact, identifier: "countOut")
            }
            if !(vm.profile.staffColors ?? []).isEmpty {
                Text("Personel geçişi: \(vm.staffIn + vm.staffOut)")
                    .font(.caption).foregroundStyle(.secondary)
                    .accessibilityIdentifier("staffCount")
            }
        }
    }
```

`OverlayView.swift` kişi kutusu rengi:

```swift
                let color: Color = m.label == nil ? .white.opacity(0.85) : (m.isStaff ? .gray : (m.isEntry ? .green : .orange))
```

`ContentView.swift`, `OverlayView(...)` satırının altına (aynı katman yığınında):

```swift
                    if vm.teachingStaff {
                        Color.clear
                            .contentShape(Rectangle())
                            .frame(width: geo.size.width, height: geo.size.height)
                            .onTapGesture(coordinateSpace: .local) { loc in
                                let x = (loc.x - fit.minX) / fit.width, y = (loc.y - fit.minY) / fit.height
                                guard (0...1).contains(x), (0...1).contains(y) else { return }
                                vm.teachStaffColor(at: CGPoint(x: x, y: y))
                            }
                            .accessibilityIdentifier("staffTeachLayer")
                    }
```

- [ ] **Adım 5: CI ve commit**

```bash
git add apps/ios/BantSayac
git commit -m "iOS: personel rengi öğretme (dokun), personel geçişi sayacı ve P etiketi"
git push
gh run watch $(gh run list --workflow ios --limit 1 --json databaseId -q '.[0].databaseId') --exit-status
```

Beklenen: `ios` yeşil (strict concurrency 0 uyarı).

---

### Görev 11: Ölçüm aracı ve dokümanlar

**Dosyalar:**
- Oluştur:
  - `tools/eval_staff.py`
  - `tools/tests/test_eval_staff.py`
- Değiştir:
  - `docs/03-algorithm.md` (§4.10 sonuna "§4.10 eki: personel rengi")
  - `docs/13-web-platform.md` (canlı API tablosu, durum alanları)
  - `docs/12-durum.md` (bölüm 5e altına satır)

**Arayüzler:**
- Tüketir: `Pipeline`, `Profile`, `FrameResult.staff_events`, `counts`, `counts_out`.
- Üretir: `match(labels, preds, tol=1.5) -> dict` (saf, test edilebilir); komut satırı:

```bash
python tools/eval_staff.py VIDEO --profile profil.json --labels VIDEO.staff.json --angle tepeden
```

- [ ] **Adım 1: Başarısız testi yaz** — `tools/tests/test_eval_staff.py`

```python
from __future__ import annotations

import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location("eval_staff", pathlib.Path(__file__).resolve().parents[1] / "eval_staff.py")
ev = importlib.util.module_from_spec(spec)                      # type: ignore[arg-type]
spec.loader.exec_module(ev)                                     # type: ignore[union-attr]


def test_match_counts_capture_and_false_exclusion() -> None:
    labels = [{"t": 2.0, "dir": "in", "staff": True}, {"t": 5.0, "dir": "in", "staff": False},
              {"t": 9.0, "dir": "out", "staff": True}, {"t": 12.0, "dir": "out", "staff": False}]
    preds = [(2.4, "in", True), (5.2, "in", True), (9.1, "out", False)]        # 12.0 kaçırıldı
    r = ev.match(labels, preds)
    assert r == {"staff": 2, "staff_ok": 1, "customer": 2, "customer_excluded": 1, "missed": 1, "extra": 0}
```

- [ ] **Adım 2: Aracı yaz** — `tools/eval_staff.py`

```python
"""Personel rengi doğruluğu (§4.10 eki, kabul ölçütü: her kamera açısında ≥ %95).

Kullanım: python tools/eval_staff.py VIDEO --profile PROFİL.json --labels VIDEO.staff.json --angle tepeden
Etiket: [{"t": saniye, "dir": "in"|"out", "staff": true|false}] — her gerçek geçiş elle etiketlenir.
Her etiket aynı yönde ±1,5 sn içindeki en yakın tahmine eşlenir. Sonuç:
- yakalama = personel etiketlerinden personel sayılan oranı;
- yanlış hariç tutma = müşteri etiketlerinden personel sayılan oranı.
Kayıtlar kullanıcınındır; public repoya konmaz.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "edge"))


def match(labels: list[dict], preds: list[tuple[float, str, bool]], tol: float = 1.5) -> dict[str, int]:
    used: set[int] = set()
    r = {"staff": 0, "staff_ok": 0, "customer": 0, "customer_excluded": 0, "missed": 0, "extra": 0}
    for lab in sorted(labels, key=lambda x: x["t"]):
        r["staff" if lab["staff"] else "customer"] += 1
        best = None
        for k, (t, d, _) in enumerate(preds):
            if k not in used and d == lab["dir"] and abs(t - lab["t"]) <= tol and (
                    best is None or abs(t - lab["t"]) < abs(preds[best][0] - lab["t"])):
                best = k
        if best is None:
            r["missed"] += 1
            continue
        used.add(best)
        if lab["staff"] and preds[best][2]:
            r["staff_ok"] += 1
        if not lab["staff"] and preds[best][2]:
            r["customer_excluded"] += 1
    r["extra"] = len(preds) - len(used)
    return r


def run(video: str, profile_path: str) -> list[tuple[float, str, bool]]:
    import cv2

    from bantvision.core import Pipeline, Profile

    p = Profile.from_dict(json.loads(pathlib.Path(profile_path).read_text(encoding="utf-8")))
    pipe = Pipeline(p)
    pipe.counting = True
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    preds: list[tuple[float, str, bool]] = []
    k = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        ts = k / fps
        r = pipe.process(frame, ts)
        preds += [(ts, "in", False)] * len(r.counts) + [(ts, "out", False)] * len(r.counts_out)
        preds += [(ts, "in" if d > 0 else "out", True) for _, d in r.staff_events]
        k += 1
    return preds


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--angle", required=True)
    a = ap.parse_args()
    labels = json.loads(pathlib.Path(a.labels).read_text(encoding="utf-8"))
    r = match(labels, run(a.video, a.profile))
    cap = r["staff_ok"] / r["staff"] if r["staff"] else 1.0
    fx = r["customer_excluded"] / r["customer"] if r["customer"] else 0.0
    ok = cap >= 0.95 and fx <= 0.05
    print(f"{a.angle}: personel yakalama %{100 * cap:.1f} ({r['staff_ok']}/{r['staff']}), "
          f"yanlış hariç tutma %{100 * fx:.1f} ({r['customer_excluded']}/{r['customer']}), "
          f"kaçan geçiş {r['missed']}, fazla {r['extra']} → {'GEÇTİ' if ok else 'KALDI'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Adım 3: Testi çalıştır**

Çalıştır: `cd services/edge && .venv/Scripts/python -m pytest ../../tools/tests/test_eval_staff.py -q && .venv/Scripts/ruff check ../../tools`
Beklenen: PASS.

- [ ] **Adım 4: Dokümanlar**

`docs/03-algorithm.md` §4.10'un sonuna:
- Tasarım belgesindeki "Algoritma" bölümü olduğu gibi: gövde bölgesi, örtüşme dışlama, örnekleme, sRGB → Lab, eşleşme, kare oyu, geçiş kararı, öğretme.
- Sabitler, Python/Swift dosya adları.
- Doğrulama: `test_staff_color.py`, `staff_parity.json`, `eval_staff.py`; kabul ölçütü ≥ %95 her açıda.

`docs/13-web-platform.md` canlı API tablosuna:

```markdown
| `POST` | `/sessions/{id}/staff-color` | `{x, y}` (0–1): tıklanan kişinin gövde rengi `{L, a, b, achromatic}`; 422 çok karanlık, 503 kare yok. Profile eklemek `PUT profile` ile (en çok 3) |
```

Ayrıca durum alanlarına `staffIn`, `staffOut` ve CSV'deki `personel_giris/personel_cikis` satırları eklenir.

`docs/12-durum.md` 5e bölümüne: personel rengi özeti; ölçüm sonuçları Görev 12'den sonra eklenecek satır.

- [ ] **Adım 5: Commit**

```bash
git add tools/eval_staff.py tools/tests/test_eval_staff.py docs/03-algorithm.md docs/13-web-platform.md docs/12-durum.md
git commit -m "Personel rengi: ölçüm aracı (açı başına ≥%95) ve dokümanlar"
```

---

### Görev 12: Gerçek ölçüm (kabul kapısı — kullanıcı yardımıyla)

**Dosyalar:**
- Değiştir: `docs/12-durum.md` (sonuçlar)
- Kayıtlar ve etiketler yerelde kalır (repoya konmaz).

- [ ] **Adım 1: Kayıt protokolünü kullanıcıya ilet** (Türkçe, sohbette)
  - **3 açı:** tepeden, eğik (~45°), yandan.
  - **Her açıda en az 20 personel geçişi:** belirgin renkli yelek/tişört; giriş ve çıkış; tek başına ve bir müşteriyle yan yana.
  - **Her açıda en az 20 müşteri geçişi:** en az 5'i koyu/siyah giyimli, en az 3'ü personel rengine yakın olmayan canlı renk.
  - **Kaynak:** ofis NVR'ı (canlı oturumdan kayıt) ya da telefon videosu.
- [ ] **Adım 2: Etiketle** — her video için `video.staff.json` (geçiş zamanı, yön, personel mi), işaretli videodan saniyeler okunarak.
- [ ] **Adım 3: Ölç**

```bash
python tools/eval_staff.py tepeden.mp4 --profile magaza.json --labels tepeden.staff.json --angle tepeden
```

Aynısı eğik ve yandan için. Beklenen: üç açıda da `GEÇTİ`.

- [ ] **Adım 4: Tutmazsa** — yalnızca ölçümle ayar.
  - Hangi açı/durum kalıyor? Gövde bölgesi mi, eşik mi, örtüşme mi?
  - Sabit iki dilde birlikte değişir; fikstür yeniden üretilir (`tools/make_staff_fixture.py`); Görev 3/5/9 testleri güncellenir.
  - Ölçüm yeniden çalışır.
- [ ] **Adım 5: Sonuçları yaz ve commit** — `docs/12-durum.md`'ye açı başına yakalama / yanlış hariç tutma oranları.

```bash
git add docs/12-durum.md
git commit -m "docs: personel rengi gerçek ölçüm sonuçları (açı başına)"
```
