# Poz Güvenlik Alarmı Uygulama Planı

> **Ajanlar için:** GEREKLİ ALT BECERİ: görev görev uygulamak için superpowers:subagent-driven-development (önerilen) ya da superpowers:executing-plans. Adımlar onay kutusu (`- [ ]`) ile izlenir.

**Amaç:** Web analiz sunucusundaki canlı kameralarda "eller yukarı" ve yerde yatan kişiyi poz analiziyle algılayıp panelde ve Telegram'da sessiz alarm vermek.

**Mimari:**
- **Algılama hattı:** mevcut kişi tanıma (YOLOX) ve izleyici (`MotTracker`) kişileri bulur. Her onaylı kişinin kutusunda MoveNet SinglePose Thunder (ONNX) 17 eklem çıkarır.
- **Kurallar:** saf kural fonksiyonları ve iz başına bölüm durum makinesi alarmı üretir.
- **Alarm yolu:** alarmlar yerel günlüğe ve olay resmine (7 gün) yazılır. Telegram'a çevrimdışı kuyrukla gider. Panel her sayfada alarm şeridi gösterir.

**Teknoloji:**
- Python 3.11+: numpy, OpenCV, ONNX Runtime, FastAPI, httpx, pytest, ruff.
- Next.js 15 + Playwright.
- Swift (yalnızca sözleşme tanıma).
- Model çevirme için ayrı ortamda TensorFlow + tf2onnx.

**Tasarım belgesi:** `docs/superpowers/specs/2026-10-06-poz-guvenlik-design.md` (uygulayıcı önce bunu okur).

## Genel kısıtlar
- **Kural sabitleri** (`core/pose_rules.py`):
  - `KP_CONF = 0,3`, `GRACE_S = 0,5`, `COOLDOWN_S = 60`.
  - Eller yukarı: `bilek.y ≤ omuz.y − 0,35·s`; dirsek görünürse `dirsek.y ≤ omuz.y + 0,15·s`.
  - Yerde yatma: `θ ≥ 60°` ya da `baş.y ≥ kalça_orta.y − 0,1·s`.
- **Ölçek `s`:** iki kalça görünürse gövde boyu; değilse `2,5 · |baş − omuz_orta|`. Baş = burun, yoksa görünen göz/kulak ortalaması. Omuzlardan biri görünmezse karar yok.
- **Süreler:**
  - Eller yukarı varsayılan 3 sn (3–5).
  - Yerde yatma varsayılan 10 sn (5–30).
  - Bölüm başına tek alarm; iz kaybı ya da > `GRACE_S` kopma bölümü bitirir.
- **COCO-17 eklem indeksleri:**
  - 0 burun; 1–2 göz; 3–4 kulak; 5–6 omuz; 7–8 dirsek;
  - 9–10 bilek; 11–12 kalça; 13–14 diz; 15–16 ayak bileği.
- **Poz modeli:** MoveNet SinglePose Thunder (Apache-2.0), ONNX.
  - Girdi 1×256×256×3 `int32` RGB; çıkış 1×1×17×3 (y, x, güven) girdiye göre normalize.
  - Kırpma: kişi kutusu 1,25× genişletilir, kareye (uzun kenar) çevrilir, dışı siyah doldurulur.
- **Sözleşme:**
  - `countMode` enum'una `safety`.
  - `safety = {handsUp: {enabled, seconds 3–5}, lying: {enabled, seconds 5–30}, sendImage}`.
  - Varsayılanlar: açık, açık, 3, 10, `false`. `v1` kalır, olay şeması değişmez.
- **Gizlilik:** olay resmi yalnızca bu bilgisayarda 7 gün; Telegram'a resim yalnızca `sendImage` açıksa. Bot anahtarı yalnızca `secrets.json`'da, hiçbir API yanıtında yok, hata metinlerinde maskeli.
- **Bildirim:** Telegram `sendPhoto`/`sendMessage`. Çevrimdışı kuyruk: bekleme 5 sn → 5 dk (iki katı), 24 saatte `failed`. Aynı kamera + tür için 60 sn içinde ikinci bildirim `suppressed`.
- **Arayüz:** metinler Türkçe, ses yok. Kod tanımlayıcıları İngilizce (CLAUDE.md).
- **Yerel komutlar:**
  - Python: `C:/Users/MSI-LAPTOP/bantvision/services/edge/.venv/Scripts/python`, uygulama klasörünün `services/edge`'inden, `PYTHONIOENCODING=utf-8`.
  - Ruff: `ruff check . ../../tools`.
  - Panel: `npx eslint src e2e`, `npx tsc --noEmit`, `npm run build`, `PYTHON=<venv python> npx playwright test`.
  - Swift yalnızca CI'da derlenir.
- **Süreç kuralı:** hiçbir zaman işlem adıyla toplu sonlandırma yapılmaz (`taskkill /IM`, `pkill python`). Kullanıcının canlı sunucuları çalışıyor.

## İnceleme odağı
1. **Tezgah arkasındaki ayakta personel** (kalça görünmüyor) yerde yatma alarmı vermemeli → Görev 3 testi (`lying` kalçasız `None`) ve Görev 5 testi (kalçasız iz alarm üretmez).
2. **Kısa süreli kopmalar:** poz bir kare kaçarsa bölüm sürmeli; 0,5 sn'den uzun kopma bitirmeli → Görev 3 `EpisodeTracker` testleri.
3. **Aynı kişi aynı duruşu sürdürürken tekrar tekrar alarm** gelmemeli; yeni bölümde yeniden gelmeli → Görev 3 ve Görev 8 (bildirim 60 sn sınırı) testleri.
4. **Telegram anahtarı yanlış ya da internet yok:** panel alarmı yine görünmeli; anahtar hiçbir yerde sızmamalı → Görev 7 ve Görev 8 testleri.
5. **Görüntü kenarındaki kişi** (kırpma kutusu görüntüden taşıyor): eklemler doğru piksele geri çevrilmeli → Görev 4 testi.

---

### Görev 1: MoveNet Thunder'ı ONNX'e çevir, doğrula ve yayınla

**Dosyalar:**
- Oluştur:
  - `tools/convert_movenet.py`
  - `services/edge/bantvision/core/pose_model.py`
  - `tools/models/MOVENET-NOTICE.md`
- Test: `services/edge/tests/test_pose_model.py`
- Yayın (dış eylem, plan onayıyla): GitHub sürümü `models-v1` (depo `oguzmeric/Bandvision`), dosyalar `movenet_thunder.onnx`, `LICENSE-APACHE-2.0.txt`, `MOVENET-NOTICE.md`.

**Arayüzler:**
- Üretir: `bantvision.core.pose_model` içinde:
  - `MODEL_NAME = "movenet_thunder.onnx"`
  - `MODEL_URL` (sürüm dosyasının doğrudan adresi)
  - `MODEL_SHA256` (64 küçük hex)
  - `INPUT_SIZE = 256`

- [ ] **Adım 1: Çevirme ortamı** (depo dışında, kazıma alanında)

```bash
cd "$TEMP/claude/C--Users-MSI-LAPTOP-bantvision/fc59a332-3fdb-403a-9e10-e3750b4d51ca/scratchpad"
python -m venv .venv-movenet
.venv-movenet/Scripts/python -m pip install -q "tensorflow==2.16.*" tensorflow-hub tf2onnx onnxruntime numpy opencv-python
```

Beklenen: kurulum hatasız. `tf2onnx` bu TensorFlow sürümüyle çalışmazsa `tensorflow==2.15.*` ile yeniden kur ve raporda belirt.

- [ ] **Adım 2: Betiği yaz** — `tools/convert_movenet.py`

```python
"""MoveNet SinglePose Thunder (Google, Apache-2.0) → ONNX, orijinal modelle eşdeğerlik doğrulaması.

Kullanım (ayrı ortamda: tensorflow, tensorflow-hub, tf2onnx, onnxruntime, numpy, opencv-python):
  python tools/convert_movenet.py --out movenet_thunder.onnx [--video yerel.mp4]
Kaynak: TF Hub google/movenet/singlepose/thunder/4 (SavedModel, imza serving_default; girdi "input" int32 1×256×256×3,
çıkış "output_0" 1×1×17×3 = y, x, güven). Doğrulama: rastgele ve (verilirse) videodan alınan 256×256 karelerde TF ve
ONNX çıktıları arasındaki en büyük fark < 0,01 olmalı. Çıktının SHA-256'sı yazdırılır (core/pose_model.py'ye girer).
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import subprocess
import sys

import numpy as np

HUB_URL = "https://tfhub.dev/google/movenet/singlepose/thunder/4"


def frames(video: str | None, n: int = 8) -> list[np.ndarray]:
    rng = np.random.default_rng(0)
    out = [rng.integers(0, 256, (256, 256, 3), dtype=np.int32) for _ in range(n)]
    if video:
        import cv2

        cap = cv2.VideoCapture(video)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        for k in range(n):
            cap.set(cv2.CAP_PROP_POS_FRAMES, k * total // n)
            ok, f = cap.read()
            if ok:
                f = cv2.resize(f, (256, 256))[:, :, ::-1]
                out.append(np.ascontiguousarray(f).astype(np.int32))
        cap.release()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--video", default=None)
    a = ap.parse_args()
    import tensorflow as tf
    import tensorflow_hub as hub

    saved = hub.resolve(HUB_URL)
    subprocess.run([sys.executable, "-m", "tf2onnx.convert", "--saved-model", saved, "--signature_def",
                    "serving_default", "--opset", "13", "--output", a.out], check=True)
    import onnxruntime as ort

    model = hub.load(HUB_URL).signatures["serving_default"]
    sess = ort.InferenceSession(a.out, providers=["CPUExecutionProvider"])
    name = sess.get_inputs()[0].name
    worst = 0.0
    for f in frames(a.video):
        ref = model(input=tf.constant(f[None]))["output_0"].numpy()
        got = sess.run(None, {name: f[None]})[0]
        worst = max(worst, float(np.abs(ref - got).max()))
    print(f"en büyük fark: {worst:.6f}")
    if worst >= 0.01:
        print("HATA: ONNX çıktısı orijinalden farklı")
        return 1
    digest = hashlib.sha256(pathlib.Path(a.out).read_bytes()).hexdigest()
    print(f"girdi adı: {name}; boyut: {pathlib.Path(a.out).stat().st_size} bayt")
    print(f"SHA-256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Adım 3: Çevir ve doğrula**

```bash
.venv-movenet/Scripts/python /c/Users/MSI-LAPTOP/bantvision/tools/convert_movenet.py --out movenet_thunder.onnx --video kisi/v.mp4
```

Beklenen: `en büyük fark: 0.00xxxx` (< 0,01) ve `SHA-256: <hex>`. Fark ≥ 0,01 ise opset 15 ile yeniden dene. Yine tutmazsa BLOCKED raporla; modeli yayınlama.

- [ ] **Adım 4: Lisans notu** — `tools/models/MOVENET-NOTICE.md`

```markdown
# MoveNet SinglePose Thunder — kaynak ve lisans

- Kaynak: Google, TF Hub `google/movenet/singlepose/thunder/4` (Kaggle: google/movenet), Apache License 2.0.
- Değişiklik: SavedModel `tools/convert_movenet.py` ile ONNX'e (opset 13, tf2onnx) çevrildi; ağırlıklar değiştirilmedi.
  Çeviri orijinal modelle karşılaştırıldı (en büyük çıktı farkı < 0,01).
- Bu dosya BandVision tarafından yalnızca dağıtım kolaylığı için yeniden yayınlanır; lisans metni: LICENSE-APACHE-2.0.txt.
```

`LICENSE-APACHE-2.0.txt` = Apache 2.0 tam metni (https://www.apache.org/licenses/LICENSE-2.0.txt), kazıma alanına indir.

- [ ] **Adım 5: GitHub sürümünü oluştur** (genel depoya yeni dosya; plan onayı bu adımı kapsar)

```bash
cd /c/Users/MSI-LAPTOP/bantvision
gh release create models-v1 "<kazıma>/movenet_thunder.onnx" "<kazıma>/LICENSE-APACHE-2.0.txt" tools/models/MOVENET-NOTICE.md \
  --title "Modeller v1" --notes "MoveNet SinglePose Thunder (Google, Apache-2.0) ONNX çevirisi. Kaynak ve değişiklik: MOVENET-NOTICE.md."
gh release view models-v1 --json assets -q '.assets[].url'
```

Beklenen: üç dosya listelenir. `movenet_thunder.onnx` indirme adresi:
`https://github.com/oguzmeric/Bandvision/releases/download/models-v1/movenet_thunder.onnx`

- [ ] **Adım 6: Sabitler ve test**

`services/edge/bantvision/core/pose_model.py` (SHA-256, Adım 3'ün yazdırdığı değer):

```python
"""Poz modeli: MoveNet SinglePose Thunder (Google, Apache-2.0), ONNX çevirisi (tools/convert_movenet.py).

GitHub sürümü models-v1'den indirilir, SHA-256 doğrulanır. Kaynak ve lisans: tools/models/MOVENET-NOTICE.md.
"""
from __future__ import annotations

MODEL_NAME = "movenet_thunder.onnx"
MODEL_URL = "https://github.com/oguzmeric/Bandvision/releases/download/models-v1/movenet_thunder.onnx"
MODEL_SHA256 = "ADIM-3-SHA256"          # Adım 3 çıktısındaki 64 karakterlik değerle değiştirilir
INPUT_SIZE = 256
```

`"ADIM-3-SHA256"` gerçek değerle değiştirilmeden commit edilmez.

`services/edge/tests/test_pose_model.py`:

```python
import re

from bantvision.core import pose_model as pm


def test_pose_model_constants() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", pm.MODEL_SHA256)
    assert pm.MODEL_URL.startswith("https://github.com/oguzmeric/Bandvision/releases/download/models-v1/")
    assert pm.MODEL_URL.endswith(pm.MODEL_NAME) and pm.INPUT_SIZE == 256
```

Çalıştır: `-m pytest tests/test_pose_model.py -q` → PASS.

- [ ] **Adım 7: Commit**

```bash
git add tools/convert_movenet.py tools/models/MOVENET-NOTICE.md services/edge/bantvision/core/pose_model.py services/edge/tests/test_pose_model.py
git commit -m "Poz modeli: MoveNet Thunder ONNX çevirisi, doğrulama ve models-v1 sürümü"
```

---

### Görev 2: Sözleşme — `countMode: safety` ve `safety` ayarları (Python, TS, şema, doküman, hazır profil)

**Dosyalar:**
- Değiştir:
  - `contracts/product-profile.schema.json`
  - `docs/02-contracts.md`
  - `services/edge/bantvision/core/profile.py`
  - `services/edge/bantvision/live/store.py` (`CATALOG`, `make_preset`)
  - `apps/dashboard/src/lib/live.ts`
  - `apps/dashboard/src/components/live/StartSessionDialog.tsx` (`categoryOf`, `profileStatus`)
- Test: `services/edge/tests/test_profile_contract.py`, `services/edge/tests/test_live.py`

**Arayüzler:**
- Üretir:
  - Python `SafetyRule(enabled: bool, seconds: float)`, `SafetyConfig(handsUp, lying, sendImage)`, `Profile.safety: SafetyConfig`, `Profile.jeweler()`.
  - `make_preset("jeweler")`.
  - Katalog kategorisi `safety`.
  - TS `SafetyConfig`, `CountMode` içinde `"safety"`, `Profile.safety?`.

- [ ] **Adım 1: Başarısız testler**

`test_profile_contract.py` sonuna:

```python
def test_safety_profile_round_trip_and_validate(validator: Draft202012Validator) -> None:
    p = Profile.jeweler()
    d = p.to_dict()
    assert d["countMode"] == "safety" and d["safety"] == {
        "handsUp": {"enabled": True, "seconds": 3.0}, "lying": {"enabled": True, "seconds": 10.0}, "sendImage": False}
    assert d["detectClasses"] == ["person"] and d["countAnchor"] == "bottom"
    assert_valid(validator, d)
    q = Profile.from_dict({**d, "safety": {"handsUp": {"enabled": False, "seconds": 5}, "lying": {"enabled": True,
                                                                                               "seconds": 30},
                                          "sendImage": True}})
    assert (q.safety.handsUp.enabled, q.safety.handsUp.seconds, q.safety.lying.seconds, q.safety.sendImage) == \
        (False, 5.0, 30.0, True)
    bad = {**d, "safety": {**d["safety"], "handsUp": {"enabled": True, "seconds": 6}}}
    assert list(validator.iter_errors(bad))
```

`test_live.py` sonuna:

```python
def test_catalog_has_safety_preset(client: TestClient) -> None:
    cat = {c["id"]: c for c in client.get("/api/v1/live/catalog").json()}
    assert cat["safety"]["available"] and cat["safety"]["presets"] == [{"key": "jeweler", "name": "Kuyumcu güvenliği"}]
    p = client.post("/api/v1/live/profiles", json={"preset": "jeweler"}).json()
    assert p["countMode"] == "safety" and p["name"] == "Kuyumcu güvenliği"
```

- [ ] **Adım 2: Başarısız olduğunu gör**

Çalıştır: `-m pytest tests/test_live.py -q -k safety_preset`
Beklenen: FAIL (`KeyError: 'safety'`). Şema testi yerelde jsonschema yoksa toplanamaz; CI'da koşar.

- [ ] **Adım 3: Şema** — `countMode` enum'una `"safety"` ekle; açıklamaya "`safety` = poz güvenlik alarmı (eller yukarı, yerde yatan kişi)" ekle. `countAnchor`'dan sonra (staffColors'tan önce ya da sonra, sıra fark etmez):

```json
    "safety": {
      "description": "safety: poz güvenlik alarmı ayarları (tasarım docs/superpowers/specs/2026-10-06-poz-guvenlik-design.md). Yoksa varsayılanlar: ikisi açık, 3 ve 10 sn, resim kapalı.",
      "type": "object", "additionalProperties": false,
      "properties": {
        "handsUp": { "type": "object", "additionalProperties": false, "required": ["enabled", "seconds"],
          "properties": { "enabled": { "type": "boolean" }, "seconds": { "type": "number", "minimum": 3, "maximum": 5 } } },
        "lying": { "type": "object", "additionalProperties": false, "required": ["enabled", "seconds"],
          "properties": { "enabled": { "type": "boolean" }, "seconds": { "type": "number", "minimum": 5, "maximum": 30 } } },
        "sendImage": { "type": "boolean" }
      }
    },
```

- [ ] **Adım 4: `docs/02-contracts.md`**

`countMode` satırına `safety` değerini ekle, ardından şu satırı ekle:

```markdown
| `safety` | nesne, isteğe bağlı | `countMode = safety`: `handsUp {enabled, seconds 3–5}`, `lying {enabled, seconds 5–30}`, `sendImage` (olay resmi Telegram'a). Varsayılan: açık/3 sn, açık/10 sn, resim kapalı |
```

- [ ] **Adım 5: Python `Profile`** (`profile.py`)

`Profile` sınıfından önce:

```python
@dataclass
class SafetyRule:
    enabled: bool = True
    seconds: float = 3.0


@dataclass
class SafetyConfig:
    """Poz güvenlik alarmı (countMode = "safety"): eller yukarı 3–5 sn, yerde yatma 5–30 sn, olay resmi gönderimi."""
    handsUp: SafetyRule = field(default_factory=lambda: SafetyRule(True, 3.0))
    lying: SafetyRule = field(default_factory=lambda: SafetyRule(True, 10.0))
    sendImage: bool = False
```

`Profile` alanlarına `staffColors`'tan sonra:

```python
    safety: SafetyConfig = field(default_factory=SafetyConfig)
```

`from_dict` içinde `staffColors` bloğundan sonra:

```python
        if d.get("safety"):
            sf = d["safety"]
            p.safety = SafetyConfig(
                SafetyRule(bool(sf.get("handsUp", {}).get("enabled", True)),
                           float(sf.get("handsUp", {}).get("seconds", 3.0))),
                SafetyRule(bool(sf.get("lying", {}).get("enabled", True)),
                           float(sf.get("lying", {}).get("seconds", 10.0))),
                bool(sf.get("sendImage", False)))
```

`to_dict` içinde algılama alanlarının koşulu `if self.countMode == "detect"` → `if self.countMode in ("detect", "safety")`. `staffColors` bloğundan sonra:

```python
        if self.countMode == "safety":
            d["safety"] = asdict(self.safety)
```

Hazır profil (`people`'dan sonra):

```python
    @classmethod
    def jeweler(cls) -> Profile:
        """Kuyumcu güvenliği: eller yukarı (3 sn) ve yerde yatan kişi (10 sn) alarmı; eğik bullet/dome kamera."""
        return cls(name="Kuyumcu güvenliği", roi=Roi(0.0, 0.0, 1.0, 1.0), countMode="safety", detectClasses=["person"],
                   detectConfidence=0.35, countAnchor="bottom", minHits=3, processingWidth=640)
```

- [ ] **Adım 6: Katalog** (`live/store.py`)

`CATALOG` listesine "people" kategorisinden sonra:

```python
    {"id": "safety", "title": "Güvenlik", "subtitle": "Eller yukarı ve yerde yatan kişi alarmı",
     "available": True, "presets": [{"key": "jeweler", "name": "Kuyumcu güvenliği"}]},
```

`make_preset` sözlüğüne `"jeweler": Profile.jeweler`.

- [ ] **Adım 7: TS** (`lib/live.ts`)

```ts
/** Poz güvenlik alarmı ayarları (sözleşme `safety`) */
export interface SafetyConfig {
  handsUp: { enabled: boolean; seconds: number };
  lying: { enabled: boolean; seconds: number };
  sendImage: boolean;
}
```

- `Profile` arayüzüne `safety?: SafetyConfig;` ekle.
- `countMode` tipi `CountMode` ise `lib/types.ts`'deki `CountMode` birleşimine `"safety"` ekle; değilse `Profile.countMode` tipini genişlet.

`StartSessionDialog.tsx`:

```ts
export function categoryOf(p: Profile): string {
  if (p.countMode === "safety") return "safety";
  return p.countMode === "detect" ? "people" : "belt";
}
```

`profileStatus` başına: `if (p.countMode === "safety") return "Eller yukarı / yerde yatan kişi";`

`lib/types.ts`'de `CountMode` değerlerine bağlı `Record<CountMode, …>` etiket tabloları varsa `safety: "Güvenlik"` ekle (tsc hatası yol gösterir).

- [ ] **Adım 8: Doğrula ve commit**

Çalıştır (services/edge):

```bash
-m pytest tests/test_live.py tests/test_staff_color.py -q && ruff check .
```

Ardından apps/dashboard'da `npx tsc --noEmit`.

```bash
git add contracts docs/02-contracts.md services/edge/bantvision/core/profile.py services/edge/bantvision/live/store.py services/edge/tests apps/dashboard/src
git commit -m "Sözleşme: countMode safety ve poz güvenlik ayarları; Kuyumcu güvenliği hazır profili"
```

---

### Görev 3: Kural fonksiyonları ve bölüm durum makinesi — `core/pose_rules.py`

**Dosyalar:**
- Oluştur: `services/edge/bantvision/core/pose_rules.py`
- Test: `services/edge/tests/test_pose_rules.py`

**Arayüzler:**
- Üretir:
  - `KP_CONF`, `GRACE_S`, `COOLDOWN_S`.
  - `head(kp: np.ndarray) -> np.ndarray | None`, `scale(kp) -> float | None`.
  - `hands_up(kp) -> bool | None`, `lying(kp) -> bool | None` (`kp`: 17×3 piksel x, y, güven).
  - `EpisodeTracker` ile:
    - `update(key: tuple[int, str], verdict: bool | None, ts: float, threshold_s: float) -> bool` (bu karede alarm doğdu mu);
    - `sweep(ts: float, alive: set[int]) -> list[tuple[tuple[int, str], bool]]` (biten bölümler, alarm vermiş mi);
    - `active() -> list[tuple[int, str, float, bool]]` (iz, tür, süre sn, alarm verdi mi).

- [ ] **Adım 1: Testler** — `tests/test_pose_rules.py`

```python
"""Poz güvenlik kuralları (tasarım: docs/superpowers/specs/2026-10-06-poz-guvenlik-design.md)."""
from __future__ import annotations

import numpy as np

from bantvision.core.pose_rules import EpisodeTracker, hands_up, lying, scale

HIDDEN = None


def person(**pts: tuple[float, float] | None) -> np.ndarray:
    """Ayakta kişi (y aşağı): baş 100, omuzlar 160, dirsekler 230, bilekler 290, kalça 330, diz 430, ayak 520.
    Anahtarla eklem taşınır; None verilen eklem görünmez (güven 0)."""
    base = {0: (200, 100), 1: (192, 92), 2: (208, 92), 3: (184, 98), 4: (216, 98), 5: (170, 160), 6: (230, 160),
            7: (160, 230), 8: (240, 230), 9: (158, 290), 10: (242, 290), 11: (180, 330), 12: (220, 330),
            13: (180, 430), 14: (220, 430), 15: (180, 520), 16: (220, 520)}
    names = {"nose": 0, "l_sh": 5, "r_sh": 6, "l_el": 7, "r_el": 8, "l_wr": 9, "r_wr": 10, "l_hip": 11, "r_hip": 12}
    kp = np.zeros((17, 3))
    for i, (x, y) in base.items():
        kp[i] = (x, y, 0.9)
    for k, v in pts.items():
        i = names[k]
        if v is None:
            kp[i, 2] = 0.0
        else:
            kp[i, :2] = v
    return kp


def test_scale_uses_torso_or_head() -> None:
    assert scale(person()) == 170.0                                         # omuz ortası 160 → kalça ortası 330
    s = scale(person(l_hip=None, r_hip=None))
    assert s is not None and abs(s - 2.5 * 60) < 1e-6                       # baş 100 → omuz 160
    assert scale(person(l_sh=None)) is None


def test_hands_up_surrender_and_overhead() -> None:
    assert hands_up(person()) is False
    up = person(l_el=(150, 150), r_el=(250, 150), l_wr=(150, 90), r_wr=(250, 90))       # teslim: dirsek omuz hizası
    assert hands_up(up) is True
    over = person(l_el=(165, 110), r_el=(235, 110), l_wr=(175, 40), r_wr=(225, 40))     # baş üstü
    assert hands_up(over) is True


def test_hands_up_needs_both_hands_and_handles_counter() -> None:
    one = person(l_el=(150, 150), l_wr=(150, 90))                            # tek el (rafa uzanma)
    assert hands_up(one) is False
    counter = person(l_hip=None, r_hip=None, l_el=(150, 150), r_el=(250, 150), l_wr=(150, 90), r_wr=(250, 90))
    assert hands_up(counter) is True                                         # kalça tezgah arkasında
    assert hands_up(person(l_wr=None)) is None                               # bilek görünmüyor


def test_hands_up_low_elbows_rejected() -> None:
    wave = person(l_el=(150, 260), r_el=(250, 260), l_wr=(150, 100), r_wr=(250, 100))  # dirsek aşağıda
    assert hands_up(wave) is False


def lying_person(direction: str) -> np.ndarray:
    if direction == "side":                                                  # yatay: baş solda
        return person(nose=(100, 400), l_sh=(160, 390), r_sh=(160, 410), l_hip=(330, 390), r_hip=(330, 410))
    return person(nose=(200, 520), l_sh=(190, 470), r_sh=(210, 470), l_hip=(190, 420), r_hip=(210, 420))  # kameraya doğru


def test_lying_horizontal_and_toward_camera() -> None:
    assert lying(lying_person("side")) is True
    assert lying(lying_person("toward")) is True                             # baş kalçanın altında
    assert lying(person()) is False


def test_lying_rejects_bending_sitting_and_needs_hips() -> None:
    bend = person(nose=(250, 300), l_sh=(225, 280), r_sh=(255, 300))         # eğilme: ~45°, baş kalçanın üstünde
    assert lying(bend) is False
    sit = person(l_hip=(180, 260), r_hip=(220, 260))                          # oturma: gövde dik
    assert lying(sit) is False
    assert lying(person(l_hip=None, r_hip=None)) is None                     # tezgah arkasında ayakta


def test_episode_fires_once_after_threshold() -> None:
    ep = EpisodeTracker()
    fired = [ep.update((1, "hands_up"), True, t / 10, 3.0) for t in range(0, 50)]
    assert fired.index(True) == 30 and sum(fired) == 1


def test_episode_grace_and_end() -> None:
    ep = EpisodeTracker()
    for t in range(0, 20):
        ep.update((1, "lying"), True, t / 10, 10.0)
    ep.update((1, "lying"), None, 2.2, 10.0)                                 # 0,3 sn kopma: affedilir
    assert ep.sweep(2.3, {1}) == []
    assert ep.active()[0][:2] == (1, "lying")
    assert ep.sweep(2.6, {1}) == [((1, "lying"), False)]                     # > 0,5 sn: biter, alarm yoktu
    assert ep.active() == []


def test_episode_ends_when_track_lost_and_reports_fired() -> None:
    ep = EpisodeTracker()
    for t in range(0, 40):
        ep.update((7, "hands_up"), True, t / 10, 3.0)
    assert ep.sweep(4.0, set()) == [((7, "hands_up"), True)]
    assert not ep.update((7, "hands_up"), True, 4.1, 3.0)                    # yeni bölüm baştan sayar
```

- [ ] **Adım 2: Başarısız olduğunu gör**

Çalıştır: `-m pytest tests/test_pose_rules.py -q`
Beklenen: FAIL (`ModuleNotFoundError`).

- [ ] **Adım 3: Uygula** — `core/pose_rules.py`

```python
"""Poz güvenlik kuralları: "eller yukarı" ve yerde yatan kişi (tasarım docs/superpowers/specs/2026-10-06-poz-guvenlik-design.md).

Eklemler COCO-17, piksel (x, y aşağı), güven. Kare kararları True / False / None (yetersiz eklem: karar yok).
`EpisodeTracker` iz ve tür başına bölüm tutar: True kareler sürdürür, `GRACE_S`'ten uzun kopma ya da iz kaybı bitirir,
süre eşiği aşılınca bölüm başına bir kez alarm.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

KP_CONF = 0.3
GRACE_S = 0.5
COOLDOWN_S = 60.0

NOSE, L_SH, R_SH, L_EL, R_EL, L_WR, R_WR, L_HIP, R_HIP = 0, 5, 6, 7, 8, 9, 10, 11, 12
HEAD_ALT = (1, 2, 3, 4)


def _vis(kp: np.ndarray, i: int) -> bool:
    return bool(kp[i, 2] >= KP_CONF)


def head(kp: np.ndarray) -> np.ndarray | None:
    if _vis(kp, NOSE):
        return kp[NOSE, :2]
    pts = [kp[i, :2] for i in HEAD_ALT if _vis(kp, i)]
    return np.mean(pts, axis=0) if pts else None


def _mid(kp: np.ndarray, a: int, b: int) -> np.ndarray:
    return (kp[a, :2] + kp[b, :2]) / 2


def scale(kp: np.ndarray) -> float | None:
    """Gövde boyu (iki kalça görünürse) ya da 2,5 × baş–omuz ortası uzaklığı; omuzlar görünmezse None."""
    if not (_vis(kp, L_SH) and _vis(kp, R_SH)):
        return None
    sh = _mid(kp, L_SH, R_SH)
    if _vis(kp, L_HIP) and _vis(kp, R_HIP):
        s = float(np.linalg.norm(sh - _mid(kp, L_HIP, R_HIP)))
        return s if s > 0 else None
    h = head(kp)
    if h is None:
        return None
    d = float(np.linalg.norm(h - sh))
    return 2.5 * d if d > 0 else None


def hands_up(kp: np.ndarray) -> bool | None:
    s = scale(kp)
    if s is None or not (_vis(kp, L_WR) and _vis(kp, R_WR)):
        return None
    for sh, el, wr in ((L_SH, L_EL, L_WR), (R_SH, R_EL, R_WR)):
        if kp[wr, 1] > kp[sh, 1] - 0.35 * s:
            return False
        if _vis(kp, el) and kp[el, 1] > kp[sh, 1] + 0.15 * s:
            return False
    return True


def lying(kp: np.ndarray) -> bool | None:
    if not all(_vis(kp, i) for i in (L_SH, R_SH, L_HIP, R_HIP)):
        return None
    sh, hp = _mid(kp, L_SH, R_SH), _mid(kp, L_HIP, R_HIP)
    v = sh - hp
    s = float(np.linalg.norm(v))
    if s == 0:
        return None
    theta = math.degrees(math.atan2(abs(float(v[0])), -float(v[1])))   # 0° dik (omuz kalçanın üstünde), 90° yatay
    if theta >= 60.0:
        return True
    h = head(kp)
    return bool(h is not None and h[1] >= hp[1] - 0.1 * s)


@dataclass
class _Episode:
    start: float
    last_true: float
    fired: bool = False


class EpisodeTracker:
    def __init__(self) -> None:
        self._eps: dict[tuple[int, str], _Episode] = {}

    def update(self, key: tuple[int, str], verdict: bool | None, ts: float, threshold_s: float) -> bool:
        """Bu karenin kararı; True dönerse bu karede alarm doğdu (bölüm başına bir kez)."""
        if verdict is not True:
            return False                                   # kopma: sweep GRACE_S'e göre bitirir
        ep = self._eps.get(key)
        if ep is None or ts - ep.last_true > GRACE_S:
            ep = self._eps[key] = _Episode(ts, ts)
        ep.last_true = ts
        if not ep.fired and ts - ep.start >= threshold_s:
            ep.fired = True
            return True
        return False

    def sweep(self, ts: float, alive: set[int]) -> list[tuple[tuple[int, str], bool]]:
        """Biten bölümler (iz yok ya da son True'dan beri > GRACE_S): (anahtar, alarm vermiş mi)."""
        ended = [(k, e.fired) for k, e in self._eps.items() if k[0] not in alive or ts - e.last_true > GRACE_S]
        for k, _ in ended:
            del self._eps[k]
        return ended

    def active(self) -> list[tuple[int, str, float, bool]]:
        return [(k[0], k[1], e.last_true - e.start, e.fired) for k, e in self._eps.items()]
```

- [ ] **Adım 4: Geç ve commit**

Çalıştır: `-m pytest tests/test_pose_rules.py -q && ruff check .` → PASS.

Not: `test_episode_fires_once_after_threshold`'da t = 30 → 3,0 − 0,0 ≥ 3,0 (ilk True = başlangıç).

```bash
git add services/edge/bantvision/core/pose_rules.py services/edge/tests/test_pose_rules.py
git commit -m "edge: poz güvenlik kuralları (eller yukarı, yerde yatma) ve bölüm durum makinesi"
```

---

### Görev 4: Poz tahmini — `core/pose.py` (kırpma, MoveNet çıkarımı, geri çevirme, model indirme)

**Dosyalar:**
- Oluştur: `services/edge/bantvision/core/pose.py`
- Test: `services/edge/tests/test_pose.py`

**Arayüzler:**
- Tüketir: `pose_model.MODEL_NAME/MODEL_URL/MODEL_SHA256/INPUT_SIZE`; `detector._sha256`.
- Üretir:
  - `square_crop(box_px: tuple[float, float, float, float], pad: float = 1.25) -> tuple[float, float, float]` (x0, y0, kenar).
  - `make_input(bgr: np.ndarray, crop: tuple[float, float, float]) -> np.ndarray` (1×256×256×3 `int32` RGB).
  - `to_image(out: np.ndarray, crop) -> np.ndarray` (17×3: x, y, güven; `out` 17×3 y, x, güven normalize).
  - `pose_model_path()`, `ensure_pose_model() -> pathlib.Path`.
  - `class PoseEstimator` ile `__init__(path: pathlib.Path | None = None)` ve `estimate(bgr: np.ndarray, box_px) -> np.ndarray` (17×3).

- [ ] **Adım 1: Testler** — `tests/test_pose.py`

```python
from __future__ import annotations

import numpy as np
import pytest

from bantvision.core import pose


def test_square_crop_is_centered_and_padded() -> None:
    x0, y0, side = pose.square_crop((100, 50, 140, 210))                     # 40×160 kutu
    assert side == pytest.approx(160 * 1.25)
    assert (x0 + side / 2, y0 + side / 2) == pytest.approx((120, 130))


def test_make_input_pads_outside_with_black_and_is_rgb_int32() -> None:
    img = np.zeros((100, 100, 3), np.uint8)
    img[:, :] = (255, 0, 0)                                                  # BGR mavi
    x = pose.make_input(img, (-50.0, -50.0, 200.0))                         # sol üst görüntü dışında
    assert x.shape == (1, 256, 256, 3) and x.dtype == np.int32
    assert (x[0, 10, 10] == 0).all()                                         # dışarısı siyah
    assert tuple(x[0, 128, 128]) == (0, 0, 255)                              # görüntü içi; RGB'de mavi


def test_to_image_maps_back_including_crop_off_image() -> None:
    out = np.zeros((17, 3))
    out[0] = (0.5, 0.25, 0.8)                                                # y, x, güven
    kp = pose.to_image(out, (-40.0, 10.0, 200.0))
    assert tuple(kp[0]) == pytest.approx((-40 + 0.25 * 200, 10 + 0.5 * 200, 0.8))


def test_estimator_runs_with_fake_session() -> None:
    class FakeSession:
        def get_inputs(self) -> list[object]:
            from types import SimpleNamespace
            return [SimpleNamespace(name="input")]

        def run(self, _o: object, feed: dict[str, np.ndarray]) -> list[np.ndarray]:
            assert feed["input"].shape == (1, 256, 256, 3)
            r = np.zeros((1, 1, 17, 3), np.float32)
            r[0, 0, :, 2] = 0.9
            r[0, 0, 5] = (0.5, 0.5, 0.9)
            return [r]

    est = pose.PoseEstimator.__new__(pose.PoseEstimator)
    est._session, est._input = FakeSession(), "input"
    kp = est.estimate(np.zeros((480, 640, 3), np.uint8), (300, 100, 340, 260))
    side = 160 * 1.25
    assert kp.shape == (17, 3) and kp[5, :2] == pytest.approx((320, 180))   # kare merkezi = kutu merkezi
    assert side > 0
```

- [ ] **Adım 2: Başarısız olduğunu gör**

Çalıştır: `-m pytest tests/test_pose.py -q`
Beklenen: FAIL (`ModuleNotFoundError`).

- [ ] **Adım 3: Uygula** — `core/pose.py`

```python
"""Poz tahmini: MoveNet SinglePose Thunder (Google, Apache-2.0), ONNX Runtime (CPU). Kişi kutusu başına çalışır.

Kutu 1,25× genişletilip kareye çevrilir (dışı siyah), 256×256 RGB int32 girdi; çıkış 17×(y, x, güven) normalize →
görüntü pikseline geri çevrilir. Model ilk kullanımda GitHub sürümünden indirilir, SHA-256 doğrulanır.
"""
from __future__ import annotations

import os
import pathlib
import urllib.request

import cv2
import numpy as np

from .detector import _sha256
from .pose_model import INPUT_SIZE, MODEL_NAME, MODEL_SHA256, MODEL_URL

Crop = tuple[float, float, float]


def square_crop(box_px: tuple[float, float, float, float], pad: float = 1.25) -> Crop:
    x1, y1, x2, y2 = box_px
    side = max(x2 - x1, y2 - y1) * pad
    return (x1 + x2) / 2 - side / 2, (y1 + y2) / 2 - side / 2, side


def make_input(bgr: np.ndarray, crop: Crop) -> np.ndarray:
    x0, y0, side = crop
    s = max(1, int(round(side)))
    canvas = np.zeros((s, s, 3), np.uint8)
    h, w = bgr.shape[:2]
    ix0, iy0 = int(round(x0)), int(round(y0))
    sx0, sy0, sx1, sy1 = max(0, ix0), max(0, iy0), min(w, ix0 + s), min(h, iy0 + s)
    if sx1 > sx0 and sy1 > sy0:
        canvas[sy0 - iy0:sy1 - iy0, sx0 - ix0:sx1 - ix0] = bgr[sy0:sy1, sx0:sx1]
    img = cv2.resize(canvas, (INPUT_SIZE, INPUT_SIZE), interpolation=cv2.INTER_LINEAR)
    return img[:, :, ::-1].astype(np.int32)[None]


def to_image(out: np.ndarray, crop: Crop) -> np.ndarray:
    x0, y0, side = crop
    kp = np.empty((17, 3))
    kp[:, 0] = x0 + out[:, 1] * side
    kp[:, 1] = y0 + out[:, 0] * side
    kp[:, 2] = out[:, 2]
    return kp


def pose_model_path() -> pathlib.Path:
    base = os.environ.get("BANTVISION_MODEL_DIR") or str(pathlib.Path.home() / ".cache" / "bantvision")
    return pathlib.Path(base) / MODEL_NAME


def ensure_pose_model() -> pathlib.Path:
    """Poz modelini yoksa indirir; parmak izi tutmazsa siler ve hata verir."""
    p = pose_model_path()
    if p.exists() and _sha256(p) == MODEL_SHA256:
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".part")
    urllib.request.urlretrieve(MODEL_URL, tmp)
    if _sha256(tmp) != MODEL_SHA256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("Poz modeli doğrulanamadı (SHA-256 tutmuyor).")
    tmp.replace(p)
    return p


class PoseEstimator:
    def __init__(self, path: pathlib.Path | None = None) -> None:
        import onnxruntime as ort

        so = ort.SessionOptions()
        so.intra_op_num_threads = max(1, min(4, (os.cpu_count() or 2) // 2))
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self._session = ort.InferenceSession(str(path or ensure_pose_model()), so, providers=["CPUExecutionProvider"])
        self._input = self._session.get_inputs()[0].name

    def estimate(self, bgr: np.ndarray, box_px: tuple[float, float, float, float]) -> np.ndarray:
        crop = square_crop(box_px)
        out = self._session.run(None, {self._input: make_input(bgr, crop)})[0]
        return to_image(np.asarray(out, np.float64).reshape(17, 3), crop)
```

- [ ] **Adım 4: Modelle yerel uçtan uca denetim** (CI'da değil; model indirilir)

```bash
-c "import numpy as np; from bantvision.core.pose import PoseEstimator; e=PoseEstimator(); k=e.estimate(np.zeros((480,640,3),np.uint8),(300,100,340,260)); print(k.shape)"
```

Beklenen: `(17, 3)`.

- [ ] **Adım 5: Geç ve commit**

Çalıştır: `-m pytest tests/test_pose.py -q && ruff check .` → PASS.

```bash
git add services/edge/bantvision/core/pose.py services/edge/tests/test_pose.py
git commit -m "edge: MoveNet poz tahmini (kare kırpma, ONNX çıkarımı, model indirme)"
```

---

### Görev 5: Güvenlik çözümleyicisi, hat (pipeline) ve çizim

**Dosyalar:**
- Oluştur: `services/edge/bantvision/core/safety.py`
- Değiştir:
  - `services/edge/bantvision/core/pipeline.py` (`FrameResult.safety`, `_process_safety`)
  - `services/edge/bantvision/overlay.py` (`draw_safety`)
- Test: `services/edge/tests/test_safety.py`

**Arayüzler:**
- Tüketir: `DetectCounter` (`detect_count.py`; `process`, `enable_gate`, `tracker`), `inside_roi`, `pose_rules`, `PoseEstimator.estimate`.
- Üretir:
  - `SafetyAlarm(kind: str, track_id: int, box: tuple[float, float, float, float], started: float, ts: float)`; `kind` `"hands_up"` | `"lying"`, `box` normalize.
  - `SafetyResult(tracks: list[MotTrack], poses: dict[int, np.ndarray], active: list[tuple[int, str, float, bool]], fired: list[SafetyAlarm], ended: list[tuple[int, str, bool]])`.
  - `SafetyAnalyzer(detector=None, pose=None)` ile `process(bgr, profile, fps, ts) -> SafetyResult`, `reset()`, `enable_gate()`.
  - `FrameResult.safety: SafetyResult | None`; `Pipeline.safety: SafetyAnalyzer` (tembel oluşturulur).
  - `draw_safety(frame, profile, r: SafetyResult | None) -> np.ndarray`.

- [ ] **Adım 1: Testler** — `tests/test_safety.py`

```python
from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from bantvision.core import Pipeline, Profile
from bantvision.core.safety import SafetyAnalyzer


class FakeDetector:
    """Her karede verilen piksel kutularını kişi olarak döndürür."""

    def __init__(self, boxes: list[tuple[float, float, float, float]]) -> None:
        self.boxes = boxes

    def detect(self, crop: np.ndarray, _classes: object, conf: float = 0.15) -> list[object]:
        return [SimpleNamespace(x1=b[0], y1=b[1], x2=b[2], y2=b[3], score=0.9) for b in self.boxes]


class FakePose:
    """Kutudan bağımsız sabit eklemler (17×3 piksel); `kp` testte değiştirilir."""

    def __init__(self, kp: np.ndarray) -> None:
        self.kp = kp

    def estimate(self, _bgr: np.ndarray, _box: object) -> np.ndarray:
        return self.kp


def hands_up_kp() -> np.ndarray:
    kp = np.zeros((17, 3))
    pts = {0: (320, 120), 5: (300, 170), 6: (340, 170), 7: (290, 160), 8: (350, 160), 9: (290, 100),
           10: (350, 100), 11: (305, 330), 12: (335, 330)}
    for i, (x, y) in pts.items():
        kp[i] = (x, y, 0.9)
    return kp


def run(kp: np.ndarray, seconds: float, fps: float = 10.0, profile: Profile | None = None) -> list[object]:
    p = profile or Profile.jeweler()
    an = SafetyAnalyzer(detector=FakeDetector([(280, 80, 360, 440)]), pose=FakePose(kp))
    frame = np.zeros((480, 640, 3), np.uint8)
    out = []
    for k in range(int(seconds * fps)):
        out.append(an.process(frame, p, fps, k / fps))
    return out


def test_hands_up_alarm_after_three_seconds_once() -> None:
    res = run(hands_up_kp(), 5.0)
    fired = [(k, a.kind) for k, r in enumerate(res) for a in r.fired]
    assert len(fired) == 1 and fired[0][1] == "hands_up"
    assert 30 <= fired[0][0] <= 36                                     # 3 sn + onay (minHits) gecikmesi


def test_disabled_rule_and_area_outside_do_not_fire() -> None:
    p = Profile.jeweler()
    p.safety.handsUp.enabled = False
    assert not any(r.fired for r in run(hands_up_kp(), 5.0, profile=p))
    q = Profile.jeweler()
    q.set_polygon([(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])  # kişi alanın dışında
    assert not any(r.fired for r in run(hands_up_kp(), 5.0, profile=q))


def test_hidden_hips_never_lying() -> None:
    kp = hands_up_kp()
    kp[[9, 10], 1] = 300                                               # eller aşağıda
    kp[[11, 12], 2] = 0.0                                              # kalça tezgah arkasında
    assert not any(r.fired for r in run(kp, 15.0))


def test_pipeline_routes_safety_mode_and_draws() -> None:
    from bantvision.overlay import draw_safety

    pipe = Pipeline(Profile.jeweler())
    pipe.safety = SafetyAnalyzer(detector=FakeDetector([(280, 80, 360, 440)]), pose=FakePose(hands_up_kp()))
    frame = np.zeros((480, 640, 3), np.uint8)
    r = None
    for k in range(40):
        r = pipe.process(frame, k / 10)
    assert r is not None and r.safety is not None and r.counts == [] and pipe.total == 0
    img = draw_safety(frame.copy(), pipe.profile, r.safety)
    assert img.shape == frame.shape and img.any()                     # iskelet ve kırmızı kutu çizildi
```

- [ ] **Adım 2: Başarısız olduğunu gör**

Çalıştır: `-m pytest tests/test_safety.py -q`
Beklenen: FAIL (`ModuleNotFoundError: bantvision.core.safety`).

- [ ] **Adım 3: `core/safety.py`**

```python
"""Poz güvenlik çözümleyicisi: kişi tanıma + izleyici (detect_count.DetectCounter) + poz (MoveNet) + kurallar.

Yalnızca onaylı ve bu karede tanımayla gözlenen izlerin pozuna bakılır; alan (ROI) varsa konum noktası (alt orta)
alanda olmalı. Kurallar ve süreler pose_rules.py'de; tasarım docs/superpowers/specs/2026-10-06-poz-guvenlik-design.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .detect_count import DetectCounter, inside_roi
from .people_track import MotTrack
from .pose_rules import EpisodeTracker, hands_up, lying
from .profile import Profile


@dataclass
class SafetyAlarm:
    kind: str                                   # "hands_up" | "lying"
    track_id: int
    box: tuple[float, float, float, float]      # normalize
    started: float
    ts: float


@dataclass
class SafetyResult:
    tracks: list[MotTrack] = field(default_factory=list)
    poses: dict[int, np.ndarray] = field(default_factory=dict)
    active: list[tuple[int, str, float, bool]] = field(default_factory=list)
    fired: list[SafetyAlarm] = field(default_factory=list)
    ended: list[tuple[int, str, bool]] = field(default_factory=list)


class SafetyAnalyzer:
    def __init__(self, detector: Any | None = None, pose: Any | None = None) -> None:
        self.dc = DetectCounter(detector=detector, motion=False)
        self._pose = pose
        self.episodes = EpisodeTracker()

    @property
    def pose(self) -> Any:
        if self._pose is None:
            from .pose import PoseEstimator

            self._pose = PoseEstimator()
        return self._pose

    def enable_gate(self) -> None:
        self.dc.enable_gate()

    def reset(self) -> None:
        self.dc.reset()
        self.episodes = EpisodeTracker()

    def process(self, bgr: np.ndarray, profile: Profile, fps: float, ts: float) -> SafetyResult:
        h, w = bgr.shape[:2]
        r = self.dc.process(bgr, profile, fps)                # sayım çizgisi önemsiz; geçişler kullanılmaz
        res = SafetyResult(tracks=r.tracks)
        sf = profile.safety
        rules = [("hands_up", hands_up, sf.handsUp), ("lying", lying, sf.lying)]
        for t in r.tracks:
            x1, y1, x2, y2 = (float(v) for v in t.box)
            if not inside_roi(profile, (x1 + x2) / 2, y2):
                continue
            kp = self.pose.estimate(bgr, (x1 * w, y1 * h, x2 * w, y2 * h))
            res.poses[t.id] = kp
            for kind, fn, rule in rules:
                if not rule.enabled:
                    continue
                if self.episodes.update((t.id, kind), fn(kp), ts, rule.seconds):
                    started = next(a[2] for a in self.episodes.active() if a[0] == t.id and a[1] == kind)
                    res.fired.append(SafetyAlarm(kind, t.id, (x1, y1, x2, y2), ts - started, ts))
        alive = {t.id for t in self.dc.tracker.tracks}
        res.ended = [(k[0], k[1], fired) for k, fired in self.episodes.sweep(ts, alive)]
        res.active = self.episodes.active()
        return res
```

Not: `SafetyAlarm.started` = olayın başladığı zaman (`ts − süre`).

- [ ] **Adım 4: `pipeline.py`**
  - `FrameResult`'a `safety: Any = field(default=None, repr=False)` ekle (§ poz güvenlik).
  - `Pipeline.__init__`'e `self.safety: Any = None` ekle.
  - `process` içinde `if p.countMode == "detect":` satırından önce:

```python
        if p.countMode == "safety":
            return self._process_safety(frame, ts)
```

Yöntem (`_process_detect`'ten sonra):

```python
    def _process_safety(self, frame: np.ndarray, ts: float) -> FrameResult:
        """Poz güvenlik alarmı (countMode = "safety"): sayım yok; alarmlar FrameResult.safety'de."""
        from .safety import SafetyAnalyzer

        p = self.profile
        bgr = frame if frame.ndim == 3 else cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        fps = self._update_fps(ts)
        calib: list[tuple[str, Any]] = []
        if self._calib is not None:
            calib.append((f"{self._calib}_done", p.diffThreshold if self._calib == "background" else 0.0))
            self._calib = None
        if self.safety is None:
            self.safety = SafetyAnalyzer()
        r = self.safety.process(bgr, p, fps, ts)
        res = FrameResult(ts, [], [], [], [], calib, None, fps, 0, (bgr.shape[1], bgr.shape[0]), None)
        res.safety = r
        return res
```

`set_profile` ve `reset_count` içinde güvenlik çözümleyicisi varsa sıfırla: `if self.safety is not None: self.safety.reset()`.

- [ ] **Adım 5: `overlay.py` `draw_safety`**

```python
_SKELETON = [(5, 6), (5, 7), (7, 9), (6, 8), (8, 10), (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14),
             (14, 16), (0, 5), (0, 6)]
_SAFETY_LABELS = {"hands_up": "ELLER YUKARI", "lying": "YERDE"}


def draw_safety(frame: np.ndarray, profile: Profile, r: Any) -> np.ndarray:
    """Poz güvenlik: iskeletler; alarm vermiş (aktif) izin kutusu kırmızı ve etiketli."""
    if r is None:
        return frame
    h, w = frame.shape[:2]
    s = max(0.6, w / 960)
    th = max(1, round(2 * s))
    alarming = {(tid, kind) for tid, kind, _sec, fired in r.active if fired}
    for t in r.tracks:
        kp = r.poses.get(t.id)
        if kp is not None:
            for a, b in _SKELETON:
                if kp[a, 2] >= 0.3 and kp[b, 2] >= 0.3:
                    cv2.line(frame, (int(kp[a, 0]), int(kp[a, 1])), (int(kp[b, 0]), int(kp[b, 1])), CYAN, th,
                             cv2.LINE_AA)
        kinds = [k for (tid, k) in alarming if tid == t.id]
        if kinds:
            x1, y1, x2, y2 = (int(t.box[0] * w), int(t.box[1] * h), int(t.box[2] * w), int(t.box[3] * h))
            cv2.rectangle(frame, (x1, y1), (x2, y2), RED, th * 2, cv2.LINE_AA)
            put_text(frame, " · ".join(_SAFETY_LABELS[k] for k in kinds), (x1, max(0, y1 - int(26 * s))),
                     int(20 * s), RED)
    return frame
```

`CYAN`, `RED`, `put_text` overlay.py'de var; yoksa mevcut renk sabitlerini kullan: `CYAN` = (255, 255, 0) BGR, `RED` = (40, 40, 230) BGR.

- [ ] **Adım 6: Geç ve commit**

Çalıştır:

```bash
-m pytest tests/test_safety.py tests/test_pose_rules.py tests/test_pose.py tests/test_live.py tests/test_staff_color.py -q && ruff check .
```

Beklenen: PASS.

```bash
git add services/edge/bantvision/core/safety.py services/edge/bantvision/core/pipeline.py services/edge/bantvision/overlay.py services/edge/tests/test_safety.py
git commit -m "edge: poz güvenlik çözümleyicisi, hatta safety yöntemi ve iskelet çizimi"
```

---

### Görev 6: Alarm günlüğü — `live/alarms.py`

**Dosyalar:**
- Oluştur: `services/edge/bantvision/live/alarms.py`
- Test: `services/edge/tests/test_alarms.py`

**Arayüzler:**
- Üretir: `AlarmStore(root: pathlib.Path)` ile:
  - `add(session_id: str | None, camera: str, kind: str, started_at: float, fired_at: float, jpeg: bytes | None, notify: str) -> dict`
  - `end(alarm_id, ts) -> None`, `set_notify(alarm_id, status) -> None`, `ack(alarm_id) -> bool`
  - `list(active_only: bool = False, since: float | None = None, limit: int = 50) -> list[dict]` (yeniden eskiye)
  - `image_path(alarm_id) -> pathlib.Path | None`, `expire(now: float, days: float = 7) -> int`
- Kayıt alanları: `id, sessionId, camera, type, startedAt, firedAt, endedAt, acked, notify, image`.
- `active_only` = `acked` false olanlar.

- [ ] **Adım 1: Testler** — `tests/test_alarms.py`

```python
from __future__ import annotations

import pathlib

from bantvision.live.alarms import AlarmStore


def test_add_list_ack_end_and_image(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    a = st.add("s1", "Tezgah", "hands_up", 100.0, 103.0, b"\xff\xd8jpeg", "queued")
    b = st.add("s1", "Tezgah", "lying", 200.0, 210.0, None, "disabled")
    assert [x["id"] for x in st.list()] == [b["id"], a["id"]]
    assert a["image"] and not b["image"] and st.image_path(a["id"]).read_bytes() == b"\xff\xd8jpeg"
    assert st.image_path(b["id"]) is None
    st.end(a["id"], 105.0)
    st.set_notify(a["id"], "sent")
    assert st.ack(a["id"]) and not st.ack("yok")
    assert [x["id"] for x in st.list(active_only=True)] == [b["id"]]
    got = {x["id"]: x for x in AlarmStore(tmp_path).list()}                  # diske yazıldı
    assert got[a["id"]]["endedAt"] == 105.0 and got[a["id"]]["notify"] == "sent" and got[a["id"]]["acked"]
    assert [x["id"] for x in st.list(since=150.0)] == [b["id"]]


def test_expire_removes_old_records_and_images(tmp_path: pathlib.Path) -> None:
    st = AlarmStore(tmp_path)
    old = st.add(None, "Deneme", "test", 0.0, 0.0, b"x", "disabled")
    new = st.add(None, "Deneme", "test", 9 * 86400.0, 9 * 86400.0, b"y", "disabled")
    assert st.expire(now=9 * 86400.0 + 1, days=7) == 1
    assert [x["id"] for x in st.list()] == [new["id"]] and st.image_path(old["id"]) is None
```

- [ ] **Adım 2: Başarısız olduğunu gör**

Çalıştır: `-m pytest tests/test_alarms.py -q`
Beklenen: FAIL (`ModuleNotFoundError`).

- [ ] **Adım 3: Uygula** — `live/alarms.py`

```python
"""Poz güvenlik alarm günlüğü: <data>/live/alarms.json ve alarm-images/<id>.jpg (yalnızca bu bilgisayarda, 7 gün).

Kayıt: {id, sessionId, camera, type ("hands_up"|"lying"|"test"), startedAt, firedAt, endedAt, acked,
notify ("disabled"|"queued"|"sent"|"failed"|"suppressed"), image}. Tüm yazmalar kilit altında ve atomik.
"""
from __future__ import annotations

import json
import os
import pathlib
import threading
import uuid
from typing import Any


class AlarmStore:
    def __init__(self, root: pathlib.Path) -> None:
        self.root = root / "live"
        self.images = self.root / "alarm-images"
        self.images.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._file = self.root / "alarms.json"
        try:
            self._items: list[dict[str, Any]] = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._items = []

    def _save(self) -> None:
        tmp = self._file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._items, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._file)

    def add(self, session_id: str | None, camera: str, kind: str, started_at: float, fired_at: float,
            jpeg: bytes | None, notify: str) -> dict[str, Any]:
        a = {"id": uuid.uuid4().hex, "sessionId": session_id, "camera": camera, "type": kind,
             "startedAt": started_at, "firedAt": fired_at, "endedAt": None, "acked": False, "notify": notify,
             "image": jpeg is not None}
        with self._lock:
            if jpeg is not None:
                (self.images / f"{a['id']}.jpg").write_bytes(jpeg)
            self._items.append(a)
            self._save()
        return dict(a)

    def _find(self, alarm_id: str) -> dict[str, Any] | None:
        return next((a for a in self._items if a["id"] == alarm_id), None)

    def _update(self, alarm_id: str, **fields: Any) -> bool:
        with self._lock:
            a = self._find(alarm_id)
            if a is None:
                return False
            a.update(fields)
            self._save()
            return True

    def end(self, alarm_id: str, ts: float) -> None:
        self._update(alarm_id, endedAt=ts)

    def set_notify(self, alarm_id: str, status: str) -> None:
        self._update(alarm_id, notify=status)

    def ack(self, alarm_id: str) -> bool:
        return self._update(alarm_id, acked=True)

    def get(self, alarm_id: str) -> dict[str, Any] | None:
        with self._lock:
            a = self._find(alarm_id)
            return dict(a) if a else None

    def list(self, active_only: bool = False, since: float | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            items = [dict(a) for a in self._items if (not active_only or not a["acked"])
                     and (since is None or a["firedAt"] >= since)]
        return sorted(items, key=lambda a: a["firedAt"], reverse=True)[:limit]

    def image_path(self, alarm_id: str) -> pathlib.Path | None:
        p = self.images / f"{alarm_id}.jpg"
        return p if p.exists() else None

    def expire(self, now: float, days: float = 7) -> int:
        cutoff = now - days * 86400
        with self._lock:
            old = [a for a in self._items if a["firedAt"] < cutoff]
            for a in old:
                (self.images / f"{a['id']}.jpg").unlink(missing_ok=True)
            if old:
                self._items = [a for a in self._items if a["firedAt"] >= cutoff]
                self._save()
        return len(old)
```

- [ ] **Adım 4: Geç ve commit**

Çalıştır: `-m pytest tests/test_alarms.py -q && ruff check .` → PASS.

```bash
git add services/edge/bantvision/live/alarms.py services/edge/tests/test_alarms.py
git commit -m "Canlı: poz güvenlik alarm günlüğü (olay resmi 7 gün)"
```

---

### Görev 7: Telegram bildirimi — `live/notify.py` ve ayar saklama

**Dosyalar:**
- Oluştur: `services/edge/bantvision/live/notify.py`
- Değiştir: `services/edge/bantvision/live/store.py` (`notify_config`, `save_notify`, `telegram_token`)
- Test: `services/edge/tests/test_notify.py`

**Arayüzler:**
- Tüketir: `AlarmStore.set_notify`, `LiveStore` (`_read`/`_write`, `secrets.json`).
- Üretir:
  - `LiveStore`: `notify_config() -> dict` (`{enabled: bool, chatId: str, hasToken: bool}`), `save_notify(enabled: bool, chat_id: str, token: str | None) -> dict` (`None` korunur, `""` silinir), `telegram_token() -> str`.
  - `class NotifyError(Exception)` (Türkçe, anahtarsız ileti).
  - `TelegramNotifier(store: LiveStore, alarms: AlarmStore, root: pathlib.Path, transport: httpx.BaseTransport | None = None, clock: Callable[[], float] = time.time)` ile:
    - `configured() -> bool`;
    - `send(text: str, jpeg: bytes | None) -> None` (hemen; `NotifyError`);
    - `enqueue(alarm_id: str, text: str, jpeg: bytes | None) -> None`;
    - `flush() -> None` (vadesi gelenleri dener; iş parçacığı çağırır, test doğrudan çağırır);
    - `start()` / `stop()`.
- Kuyruk dosyası: `<data>/live/outbox.json`. Resimler kuyrukta alarm resmi yolundan okunur (alarm resmi yoksa yalnız metin).

- [ ] **Adım 1: Testler** — `tests/test_notify.py`

```python
from __future__ import annotations

import pathlib

import httpx
import pytest

from bantvision.live.alarms import AlarmStore
from bantvision.live.notify import NotifyError, TelegramNotifier
from bantvision.live.store import LiveStore

TOKEN = "123456:GIZLI-ANAHTAR"


class Fake:
    def __init__(self, fail: int = 0, status: int = 200) -> None:
        self.calls: list[httpx.Request] = []
        self.fail, self.status = fail, status

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        if self.fail > 0:
            self.fail -= 1
            raise httpx.ConnectError("ağ yok", request=req)
        return httpx.Response(self.status, json={"ok": self.status == 200, "description": "Bad Request"})


def setup(tmp_path: pathlib.Path, fake: Fake, now: list[float]) -> tuple[LiveStore, AlarmStore, TelegramNotifier]:
    store = LiveStore(tmp_path)
    store.save_notify(True, "-1001", TOKEN)
    alarms = AlarmStore(tmp_path)
    n = TelegramNotifier(store, alarms, tmp_path, transport=httpx.MockTransport(fake), clock=lambda: now[0])
    return store, alarms, n


def test_config_never_exposes_token(tmp_path: pathlib.Path) -> None:
    store = LiveStore(tmp_path)
    cfg = store.save_notify(True, "-1001", TOKEN)
    assert cfg == {"enabled": True, "chatId": "-1001", "hasToken": True} and TOKEN not in str(store.notify_config())
    store.save_notify(False, "-1001", None)
    assert store.telegram_token() == TOKEN                                  # None: korunur
    store.save_notify(False, "-1001", "")
    assert store.telegram_token() == "" and not store.notify_config()["hasToken"]


def test_send_photo_and_message_format(tmp_path: pathlib.Path) -> None:
    fake = Fake()
    _, _, n = setup(tmp_path, fake, [0.0])
    n.send("🚨 ELLER YUKARI — Tezgah · 06.10.2026 15:42:07", b"\xff\xd8jpeg")
    n.send("🧪 DENEME", None)
    assert fake.calls[0].url.path.endswith("/sendPhoto") and b"Tezgah" in fake.calls[0].content
    assert fake.calls[1].url.path.endswith("/sendMessage") and b"-1001" in fake.calls[1].content


def test_errors_are_turkish_and_masked(tmp_path: pathlib.Path) -> None:
    _, _, n = setup(tmp_path, Fake(status=401), [0.0])
    with pytest.raises(NotifyError) as e:
        n.send("x", None)
    assert TOKEN not in str(e.value) and "Telegram" in str(e.value)


def test_outbox_retries_then_sends(tmp_path: pathlib.Path) -> None:
    now = [1000.0]
    fake = Fake(fail=2)
    _, alarms, n = setup(tmp_path, fake, now)
    a = alarms.add("s", "Tezgah", "hands_up", 997.0, 1000.0, b"\xff\xd8", "queued")
    n.enqueue(a["id"], "🚨 ELLER YUKARI", b"\xff\xd8")
    n.flush()                                                               # 1. deneme başarısız
    assert alarms.get(a["id"])["notify"] == "queued"
    now[0] += 4
    n.flush()                                                               # bekleme 5 sn dolmadı: denemez
    assert len(fake.calls) == 1
    now[0] += 2
    n.flush()                                                               # 2. deneme başarısız (bekleme 10 sn)
    now[0] += 11
    n.flush()
    assert alarms.get(a["id"])["notify"] == "sent" and len(fake.calls) == 3


def test_outbox_fails_after_24h(tmp_path: pathlib.Path) -> None:
    now = [0.0]
    fake = Fake(fail=10**6)
    _, alarms, n = setup(tmp_path, fake, now)
    a = alarms.add("s", "Tezgah", "lying", 0.0, 0.0, None, "queued")
    n.enqueue(a["id"], "🚨 YERDE YATAN KİŞİ", None)
    for _ in range(400):
        now[0] += 301
        n.flush()
    assert alarms.get(a["id"])["notify"] == "failed"
```

- [ ] **Adım 2: Başarısız olduğunu gör**

Çalıştır: `-m pytest tests/test_notify.py -q`
Beklenen: FAIL (`ModuleNotFoundError`).

- [ ] **Adım 3: `LiveStore` ayarları** (`store.py`, "kamera başına ayar" bölümünden sonra)

```python
    # ------------------------------------------------------------------ bildirim (Telegram)

    def notify_config(self) -> dict[str, Any]:
        with self._lock:
            c = self._read("notify.json", {})
            return {"enabled": bool(c.get("enabled", False)), "chatId": str(c.get("chatId", "")),
                    "hasToken": bool(self._read("secrets.json", {}).get("telegram"))}

    def save_notify(self, enabled: bool, chat_id: str, token: str | None) -> dict[str, Any]:
        """`token` None: kayıtlı anahtar korunur; "": silinir. Anahtar yalnızca secrets.json'da."""
        with self._lock:
            self._write("notify.json", {"enabled": enabled, "chatId": chat_id.strip()})
            if token is not None:
                secrets = self._read("secrets.json", {})
                if token.strip():
                    secrets["telegram"] = token.strip()
                else:
                    secrets.pop("telegram", None)
                self._write("secrets.json", secrets)
        return self.notify_config()

    def telegram_token(self) -> str:
        with self._lock:
            return str(self._read("secrets.json", {}).get("telegram", ""))
```

- [ ] **Adım 4: `live/notify.py`**

```python
"""Telegram bildirimi (poz güvenlik alarmı): anında gönderim ve çevrimdışı kuyruk.

Anahtar yalnızca secrets.json'da; hata iletilerinde maskelenir (Telegram API adresinde geçer). Kuyruk
<data>/live/outbox.json: başarısız deneme sonrası bekleme 5 sn → 5 dk (iki katı), 24 saatte "failed".
"""
from __future__ import annotations

import json
import os
import pathlib
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx

from .alarms import AlarmStore
from .store import LiveStore

MAX_AGE_S = 24 * 3600
BACKOFF_MIN_S, BACKOFF_MAX_S = 5.0, 300.0


class NotifyError(Exception):
    pass


class TelegramNotifier:
    def __init__(self, store: LiveStore, alarms: AlarmStore, root: pathlib.Path,
                 transport: httpx.BaseTransport | None = None, clock: Callable[[], float] = time.time) -> None:
        self.store, self.alarms, self.clock = store, alarms, clock
        self._file = root / "live" / "outbox.json"
        self._client = httpx.Client(timeout=15.0, transport=transport, trust_env=False)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        try:
            self._queue: list[dict[str, Any]] = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._queue = []

    def configured(self) -> bool:
        c = self.store.notify_config()
        return c["enabled"] and c["hasToken"] and bool(c["chatId"])

    def send(self, text: str, jpeg: bytes | None) -> None:
        token, chat = self.store.telegram_token(), self.store.notify_config()["chatId"]
        if not token or not chat:
            raise NotifyError("Telegram ayarı eksik: bot anahtarı ve sohbet kimliği gerekli.")
        base = f"https://api.telegram.org/bot{token}"
        try:
            if jpeg is not None:
                r = self._client.post(f"{base}/sendPhoto", data={"chat_id": chat, "caption": text},
                                      files={"photo": ("olay.jpg", jpeg, "image/jpeg")})
            else:
                r = self._client.post(f"{base}/sendMessage", json={"chat_id": chat, "text": text})
        except httpx.HTTPError as e:
            raise NotifyError(f"Telegram'a ulaşılamadı: {str(e).replace(token, '***')}") from None
        if r.status_code != 200:
            try:
                desc = str(r.json().get("description", ""))
            except ValueError:
                desc = ""
            raise NotifyError(f"Telegram reddetti ({r.status_code}): {desc.replace(token, '***')}".strip())

    def _save(self) -> None:
        tmp = self._file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._queue, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._file)

    def enqueue(self, alarm_id: str, text: str, jpeg: bytes | None) -> None:
        with self._lock:
            now = self.clock()
            self._queue.append({"alarmId": alarm_id, "text": text, "image": jpeg is not None, "createdAt": now,
                                "attempts": 0, "nextAt": now})
            self._save()

    def flush(self) -> None:
        with self._lock:
            now = self.clock()
            due = [q for q in self._queue if q["nextAt"] <= now]
        for q in due:
            done, status = False, "queued"
            if now - q["createdAt"] > MAX_AGE_S:
                done, status = True, "failed"
            else:
                img = self.alarms.image_path(q["alarmId"]) if q["image"] else None
                try:
                    self.send(q["text"], img.read_bytes() if img else None)
                    done, status = True, "sent"
                except NotifyError:
                    q["attempts"] += 1
                    q["nextAt"] = now + min(BACKOFF_MAX_S, BACKOFF_MIN_S * 2 ** (q["attempts"] - 1))
            self.alarms.set_notify(q["alarmId"], status)
            if done:
                with self._lock:
                    self._queue = [x for x in self._queue if x is not q]
        with self._lock:
            self._save()

    def _run(self) -> None:
        while not self._stop.wait(1.0):
            self.flush()

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="telegram-kuyruk", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._client.close()
```

Not:
- `test_outbox_retries_then_sends`: 1. hata → bekleme 5 sn; 2. hata → 10 sn; üçüncüde gönderilir.
- `test_outbox_fails_after_24h`: her `flush` ≥ 5 dk ilerler; 24 saat sonra `failed`.

- [ ] **Adım 5: Geç ve commit**

Çalıştır: `-m pytest tests/test_notify.py tests/test_alarms.py tests/test_live.py -q && ruff check .` → PASS.

```bash
git add services/edge/bantvision/live/notify.py services/edge/bantvision/live/store.py services/edge/tests/test_notify.py
git commit -m "Canlı: Telegram bildirimi (anahtar maskeli) ve çevrimdışı kuyruk"
```

---

### Görev 8: Canlı oturum ve API entegrasyonu

**Dosyalar:**
- Değiştir:
  - `services/edge/bantvision/live/session.py`
  - `services/edge/bantvision/live/api.py`
  - `services/edge/bantvision/analyzer/app.py` (kuyruk başlat/durdur, alarm temizliği)
- Test: `services/edge/tests/test_live.py`

**Arayüzler:**
- Tüketir: `SafetyResult`, `draw_safety`, `AlarmStore`, `TelegramNotifier`, `COOLDOWN_S`.
- Üretir:
  - `LiveSession(..., alarm_sink: Callable[[LiveSession, list[SafetyAlarm], list[tuple[int, str, bool]], bytes | None], None] | None = None)`.
  - Durumda `safety: {active: [{type, trackId, seconds}], lastAlarmAt}` (güvenlik oturumunda; diğerlerinde `null`).
  - `LiveManager.alarms`, `LiveManager.notifier`, `LiveManager.on_safety(session, fired, ended, jpeg)`.
  - Uç noktalar:
    - `GET /alarms?active=&since=`, `POST /alarms/{id}/ack`, `GET /alarms/{id}/image.jpg`;
    - `POST /alarms/test {sessionId?}`;
    - `GET /notify`, `PUT /notify {enabled, chatId, token?}`, `POST /notify/test`.

- [ ] **Adım 1: Testler** (`test_live.py` sonuna)

```python
def _safety_session_with_fake(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, str]:
    """Kuyumcu profiliyle dosya kaynağı; analizör sahte tanıyıcı + sahte pozla (eller yukarı) çalışır."""
    import numpy as np

    from bantvision.core.safety import SafetyAnalyzer

    from .test_safety import FakeDetector, FakePose, hands_up_kp      # aynı test paketinden

    monkeypatch.setenv("ANALYZER_ALLOW_FILE_SOURCES", "1")
    src = client.post("/api/v1/live/sources", json=camera(brand="custom", customUrl=str(CLIP), password="",
                                                          name="Tezgah")).json()
    prof = client.post("/api/v1/live/profiles", json={"preset": "jeweler"}).json()
    s = client.post("/api/v1/live/sessions", json={"sourceId": src["id"], "profileId": prof["id"]}).json()
    sess = client.app.state.live.sessions[s["id"]]
    with sess._lock:
        sess._pipe.safety = SafetyAnalyzer(detector=FakeDetector([(280, 80, 360, 440)]), pose=FakePose(hands_up_kp()))
    assert np is not None
    return sess, s["id"]


def _mock_telegram(client: TestClient) -> None:
    """Testte Telegram'a gerçek istek gitmesin: bildirim istemcisi sahte sunucuya bağlanır."""
    import httpx

    client.app.state.live.notifier._client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True})))


def test_safety_alarm_reaches_store_status_and_queue(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_telegram(client)
    client.put("/api/v1/live/notify", json={"enabled": True, "chatId": "-1001", "token": "123:GIZLI"})
    sess, sid = _safety_session_with_fake(client, monkeypatch)
    alarms = wait_for(lambda: client.get("/api/v1/live/alarms?active=1").json(), timeout=30)
    a = alarms[0]
    assert a["type"] == "hands_up" and a["camera"].startswith("Tezgah") and a["sessionId"] == sid
    assert a["notify"] in ("queued", "sent") and not a["image"]             # sendImage varsayılan kapalı
    st = client.get(f"/api/v1/live/sessions/{sid}").json()
    assert st["safety"]["lastAlarmAt"] is not None
    assert client.post(f"/api/v1/live/alarms/{a['id']}/ack").status_code == 200
    assert all(x["id"] != a["id"] for x in client.get("/api/v1/live/alarms?active=1").json())
    assert "GIZLI" not in client.get("/api/v1/live/notify").text


def test_safety_notifications_suppressed_within_cooldown(client: TestClient) -> None:
    from types import SimpleNamespace

    from bantvision.core import Profile
    from bantvision.core.safety import SafetyAlarm

    mgr = client.app.state.live
    _mock_telegram(client)
    fake_session = SimpleNamespace(id="x", name="Tezgah", profile=Profile.jeweler(), source_id="src", channel_id=None)
    client.put("/api/v1/live/notify", json={"enabled": True, "chatId": "-1", "token": "1:T"})
    mgr.on_safety(fake_session, [SafetyAlarm("hands_up", 1, (0, 0, 1, 1), 0.0, 3.0)], [], None)
    mgr.on_safety(fake_session, [SafetyAlarm("hands_up", 2, (0, 0, 1, 1), 5.0, 8.0)], [], None)
    st = [a["notify"] for a in client.get("/api/v1/live/alarms").json()]
    assert "suppressed" in st and len(st) == 2 and set(st) <= {"queued", "sent", "suppressed"}


def test_test_alarm_and_notify_endpoints(client: TestClient) -> None:
    r = client.post("/api/v1/live/alarms/test", json={})
    assert r.status_code == 200 and r.json()["type"] == "test" and r.json()["notify"] == "disabled"
    assert client.get("/api/v1/live/alarms?active=1").json()[0]["type"] == "test"
    assert client.get(f"/api/v1/live/alarms/{r.json()['id']}/image.jpg").status_code == 404
    r = client.post("/api/v1/live/notify/test")
    assert r.status_code == 422 and "eksik" in r.json()["detail"]
    cfg = client.put("/api/v1/live/notify", json={"enabled": False, "chatId": " -100 ", "token": "9:Z"}).json()
    assert cfg == {"enabled": False, "chatId": "-100", "hasToken": True}
```

Not:
- `tests/` paket değilse (`__init__.py` yok), `from .test_safety import …` yerine sahte sınıfları `tests/fakes_safety.py`'ye taşı ve iki dosyada `from fakes_safety import …` kullan (pytest rootdir `tests` yolunu ekler; `conftest.py` varsa ona göre).
- Ruff temiz kalmalı.

- [ ] **Adım 2: Başarısız olduğunu gör**

Çalıştır: `-m pytest tests/test_live.py -q -k "safety or notify or test_alarm"`
Beklenen: FAIL (404 ya da `AttributeError`).

- [ ] **Adım 3: `session.py`**

İçe aktarma: `from ..overlay import draw_safety` (mevcut overlay içe aktarmasının yanına).

`__init__` imzasına `alarm_sink: Callable[..., None] | None = None` ekle, `self._alarm_sink = alarm_sink` ve `self._last_alarm_at: float | None = None` ayarla.

`_work_loop` içinde `self._after_frame(r, frame)` çağrısından sonra, render bloğundan önce:

```python
            sr = getattr(r, "safety", None)
            if sr is not None and (sr.fired or sr.ended) and self._alarm_sink is not None:
                jpeg = None
                if sr.fired:
                    ok, buf = cv2.imencode(".jpg", self._render(frame.copy(), profile, r),
                                           [cv2.IMWRITE_JPEG_QUALITY, 85])
                    jpeg = buf.tobytes() if ok else None
                    self._last_alarm_at = time.time()
                self._alarm_sink(self, sr.fired, sr.ended, jpeg)
```

`_render` içinde `if profile.countMode == "detect":` dalından önce:

```python
        if profile.countMode == "safety":
            img = draw_safety(frame, profile, getattr(r, "safety", None))
        elif profile.countMode == "detect":
```

(`else` dalı aynen kalır.)

`snapshot_status` sözlüğüne:

```python
                "safety": ({"active": [{"type": k, "trackId": tid, "seconds": round(sec, 1)}
                                       for tid, k, sec, _f in (self._pipe.safety.episodes.active()
                                                               if self._pipe.safety else [])],
                            "lastAlarmAt": self._last_alarm_at}
                           if self.profile.countMode == "safety" else None),
```

Güvenlik oturumunda tanıma boş sahne atlaması: `__init__` içinde `self._pipe.detect.enable_gate()` satırının yanına:

```python
        if profile.countMode == "safety":
            from ..core.safety import SafetyAnalyzer

            self._pipe.safety = SafetyAnalyzer(detector=detector)
            self._pipe.safety.enable_gate()
```

`set_profile` ile yöntem `safety`'ye geçerse aynı kurulumu yap: `self._pipe.safety` yoksa oluştur ve `enable_gate()`.

- [ ] **Adım 4: `api.py`**

İçe aktarmalar:

```python
import datetime as dt

from ..core.pose_rules import COOLDOWN_S
from .alarms import AlarmStore
from .notify import NotifyError, TelegramNotifier
```

Modeller:

```python
class NotifyIn(_Strict):
    enabled: bool = False
    chatId: str = Field(default="", max_length=64)
    token: str | None = Field(default=None, max_length=256)     # None: kayıtlı anahtar korunur, "": silinir


class TestAlarmIn(_Strict):
    sessionId: str | None = None
```

Ortak poz modeli (`SharedDetector`'ın yanına):

```python
class SharedPose:
    """Tüm güvenlik kameralarında tek poz modeli; kareler sırayla."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._inner: Any = None

    def estimate(self, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            if self._inner is None:
                from ..core.pose import PoseEstimator

                self._inner = PoseEstimator()
            return self._inner.estimate(*args, **kwargs)
```

`LiveManager.__init__` imzası `__init__(self, store: LiveStore, data_dir: pathlib.Path | None = None)`; gövdeye:

```python
        root = data_dir or store.root.parent
        self.alarms = AlarmStore(root)
        self.notifier = TelegramNotifier(store, self.alarms, root)
        self.pose = SharedPose()
        self._last_sent: dict[tuple[str, str], float] = {}         # (kamera, tür) → son bildirim zamanı
        self._alarm_of: dict[tuple[str, int, str], str] = {}      # (oturum, iz, tür) → alarm kimliği
```

Yöntemler:

```python
    _TITLES = {"hands_up": "🚨 ELLER YUKARI", "lying": "🚨 YERDE YATAN KİŞİ", "test": "🧪 DENEME ALARMI"}

    def _text(self, kind: str, camera: str, ts: float) -> str:
        return f"{self._TITLES[kind]} — {camera} · {dt.datetime.fromtimestamp(ts).strftime('%d.%m.%Y %H:%M:%S')}"

    def on_safety(self, s: Any, fired: list[Any], ended: list[tuple[int, str, bool]], jpeg: bytes | None) -> None:
        """Oturumdan: doğan alarmlar (kayıt + bildirim) ve biten bölümler (endedAt)."""
        now = time.time()
        camera = getattr(s, "name", "Kamera")
        send_image = bool(getattr(s.profile, "safety", None) and s.profile.safety.sendImage)
        cam_key = f"{getattr(s, 'source_id', '')}|{getattr(s, 'channel_id', '') or ''}"
        for a in fired:
            notify = "disabled"
            if self.notifier.configured():
                last = self._last_sent.get((cam_key, a.kind))
                notify = "suppressed" if last is not None and now - last < COOLDOWN_S else "queued"
            rec = self.alarms.add(s.id, camera, a.kind, now - (a.ts - a.started), now, jpeg if send_image else None,
                                  notify)
            self._alarm_of[(s.id, a.track_id, a.kind)] = rec["id"]
            if notify == "queued":
                self._last_sent[(cam_key, a.kind)] = now
                self.notifier.enqueue(rec["id"], self._text(a.kind, camera, now), jpeg if send_image else None)
        for tid, kind, was_fired in ended:
            aid = self._alarm_of.pop((s.id, tid, kind), None)
            if was_fired and aid:
                self.alarms.end(aid, now)
```

`create_session` içinde `LiveSession(...)` çağrısına `alarm_sink=manager.on_safety` ekle. Güvenlik oturumu için oturumun analizörü ortak poz modelini kullanır: oturum oluşturulduktan sonra

```python
        if s.profile.countMode == "safety" and s._pipe.safety is not None:
            s._pipe.safety._pose = manager.pose
```

Uç noktalar (`make_router` içinde, oturum uç noktalarından sonra):

```python
    @r.get("/alarms")
    def alarms(active: bool = False, since: float | None = None) -> list[dict[str, Any]]:
        return manager.alarms.list(active_only=active, since=since)

    @r.post("/alarms/{alarm_id}/ack")
    def ack_alarm(alarm_id: str) -> dict[str, Any]:
        if not manager.alarms.ack(alarm_id):
            raise HTTPException(404, "Alarm bulunamadı.")
        return manager.alarms.get(alarm_id) or {}

    @r.get("/alarms/{alarm_id}/image.jpg")
    def alarm_image(alarm_id: str) -> Response:
        p = manager.alarms.image_path(alarm_id)
        if p is None:
            raise HTTPException(404, "Olay resmi yok (gönderim kapalı ya da 7 günü geçti).")
        return Response(p.read_bytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @r.post("/alarms/test")
    def test_alarm(body: TestAlarmIn) -> dict[str, Any]:
        """Deneme alarmı: panel şeridi ve (yapılandırılmışsa) Telegram; tekrar önlemeye tabi değil."""
        s = manager.sessions.get(body.sessionId) if body.sessionId else None
        camera = s.name if s else "Deneme"
        jpeg = s.raw_jpeg() if s and s.profile.countMode == "safety" and s.profile.safety.sendImage else None
        now = time.time()
        notify = "queued" if manager.notifier.configured() else "disabled"
        rec = manager.alarms.add(s.id if s else None, camera, "test", now, now, jpeg, notify)
        if notify == "queued":
            manager.notifier.enqueue(rec["id"], manager._text("test", camera, now), jpeg)
        return rec

    @r.get("/notify")
    def get_notify() -> dict[str, Any]:
        return store.notify_config()

    @r.put("/notify")
    def put_notify(body: NotifyIn) -> dict[str, Any]:
        return store.save_notify(body.enabled, body.chatId, body.token)

    @r.post("/notify/test")
    def notify_test() -> dict[str, Any]:
        try:
            manager.notifier.send("🧪 BandVision deneme mesajı — bildirimler çalışıyor.", None)
        except NotifyError as e:
            raise HTTPException(422, str(e)) from e
        return {"ok": True}
```

`NotifyError` "Telegram ayarı eksik…" iletisi `eksik` içerir (test buna bakar).

- [ ] **Adım 5: `analyzer/app.py`**
  - `LiveManager(LiveStore(settings.data_dir), settings.data_dir)` olarak oluştur.
  - `lifespan` başında `live.notifier.start()`; kapanışta `live.notifier.stop()`.
  - `cleanup_loop` içine `live.alarms.expire(time.time())` ekle; `import time`.

- [ ] **Adım 6: Geç ve commit**

Çalıştır:

```bash
-m pytest tests/test_live.py tests/test_safety.py tests/test_alarms.py tests/test_notify.py tests/test_recorders.py -q && ruff check .
```

Beklenen: PASS.

```bash
git add services/edge/bantvision/live services/edge/bantvision/analyzer/app.py services/edge/tests
git commit -m "Canlı API: poz güvenlik oturumları, alarm günlüğü uç noktaları, Telegram ayarları ve deneme alarmı"
```

---

### Görev 9: Web paneli — güvenlik oturumu, alarm şeridi, Bildirimler sayfası

**Dosyalar:**
- Oluştur:
  - `apps/dashboard/src/components/live/AlarmBanner.tsx`
  - `apps/dashboard/src/components/live/SafetyPanel.tsx`
  - `apps/dashboard/src/components/live/NotifySettings.tsx`
  - `apps/dashboard/src/app/(panel)/notifications/page.tsx`
  - `apps/dashboard/e2e/safety.spec.ts`
- Değiştir:
  - `apps/dashboard/src/lib/live.ts`
  - `apps/dashboard/src/app/(panel)/layout.tsx`
  - `apps/dashboard/src/components/Sidebar.tsx`
  - `apps/dashboard/src/components/live/LiveView.tsx`
  - `apps/dashboard/src/components/geometry/RoiEditor.tsx` (`showLine`)

**Arayüzler:**
- Tüketir: Görev 8 uç noktaları ve durum alanı `safety`.
- Üretir:
  - TS `Alarm`, `NotifyConfig`, `LiveSession.safety`.
  - `<AlarmBanner />` (her panel sayfasında).
  - `<SafetyPanel session alarms />`, `<SafetySettings value onChange />` (aynı dosyada).
  - `<NotifySettings />`; `RoiEditor` `showLine?: boolean` (varsayılan `true`).

- [ ] **Adım 1: e2e** — `e2e/safety.spec.ts`

```ts
import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

const CLIP = path.resolve(__dirname, "../../ios/BantSayacUITests/ui_test_clip.mp4");

async function login(page: Page) {
  await page.goto("/notifications");
  await page.getByLabel("Şifre").fill("e2e-test-sifresi");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("heading", { name: "Bildirimler" })).toBeVisible();
}

test("güvenlik: deneme alarmı şeritte görünür ve Gördüm ile kapanır; ayarlar anahtarı göstermez", async ({ page }) => {
  page.on("dialog", (d) => d.accept());
  await login(page);
  await page.getByLabel("Bot anahtarı").fill("123:E2E-GIZLI");
  await page.getByLabel("Sohbet / grup kimliği").fill("-1001");
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();
  await expect(page.getByText("Anahtar kayıtlı")).toBeVisible();
  await expect(page.locator("body")).not.toContainText("E2E-GIZLI");
  await page.getByRole("checkbox", { name: "Bildirimler açık" }).uncheck();
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();

  await page.getByRole("button", { name: "Deneme alarmı" }).click();
  const banner = page.getByRole("alert", { name: "Güvenlik alarmı" });
  await expect(banner).toContainText("Deneme alarmı", { timeout: 10_000 });
  await banner.getByRole("button", { name: "Gördüm" }).click();
  await expect(banner).toBeHidden();
});

test("güvenlik: kuyumcu profiliyle kamera başlar, izleniyor ve ayarlar görünür", async ({ page }) => {
  page.on("dialog", (d) => d.accept());
  await login(page);
  await page.goto("/cameras");
  await page.getByRole("radio", { name: "IP kamera" }).click();
  await page.getByLabel("Kamera markası").selectOption("custom");
  await page.getByLabel("RTSP adresi").fill(CLIP);
  await page.getByRole("textbox", { name: /^Ad/ }).fill("Tezgah kamerası");
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();
  await page.getByTestId("source-card").filter({ hasText: "Tezgah kamerası" }).getByRole("button", { name: "Canlı sayım" }).click();
  const dialog = page.getByRole("dialog", { name: "Canlı sayımı başlat" });
  await dialog.getByRole("button", { name: "+ Kuyumcu güvenliği profili ekle" }).click();
  await dialog.getByRole("button", { name: /^Kuyumcu güvenliği/ }).click();
  await dialog.getByRole("button", { name: "Başlat", exact: true }).click();
  await expect(page.getByTestId("live-state")).toContainText("Canlı", { timeout: 30_000 });
  await expect(page.getByText("İzleniyor")).toBeVisible();
  await page.getByRole("button", { name: "Ayarla" }).click();
  await expect(page.getByRole("group", { name: "Güvenlik kuralları" })).toBeVisible();
  await expect(page.getByLabel("Eller yukarı süresi")).toHaveValue("3");
  await page.getByRole("button", { name: "İptal" }).click();
  await page.getByRole("button", { name: "Canlı sayımı kapat" }).click();
  await page.goto("/cameras");
  await page.getByTestId("source-card").filter({ hasText: "Tezgah kamerası" }).getByRole("button", { name: "Sil" }).click();
});
```

Not: güvenlik oturumu CI'da tanıma ve poz modellerini indirir. Klipte kişi yok; alarm beklenmez, yalnızca akış ve arayüz sınanır.

- [ ] **Adım 2: Tipler** (`lib/live.ts`)

```ts
export type AlarmType = "hands_up" | "lying" | "test";
export interface Alarm {
  id: string; sessionId: string | null; camera: string; type: AlarmType;
  startedAt: number; firedAt: number; endedAt: number | null; acked: boolean;
  notify: "disabled" | "queued" | "sent" | "failed" | "suppressed"; image: boolean;
}
export interface NotifyConfig { enabled: boolean; chatId: string; hasToken: boolean }
export const ALARM_LABELS: Record<AlarmType, string> = { hands_up: "Eller yukarı", lying: "Yerde yatan kişi", test: "Deneme alarmı" };
export const NOTIFY_LABELS: Record<Alarm["notify"], string> = {
  disabled: "Telegram kapalı", queued: "Gönderiliyor", sent: "Telegram'a gitti", failed: "Gönderilemedi", suppressed: "Tekrar (gönderilmedi)",
};
```

`LiveSession`'a:

```ts
  /** Güvenlik oturumunda: süren bölümler ve son alarm zamanı; diğerlerinde null */
  safety: { active: Array<{ type: AlarmType; trackId: number; seconds: number }>; lastAlarmAt: number | null } | null;
```

- [ ] **Adım 3: `AlarmBanner.tsx`**

```tsx
"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ALARM_LABELS, api, type Alarm } from "@/lib/live";

/** Her panel sayfasında: onaylanmamış güvenlik alarmları (2 sn'de bir). Ses yok (sessiz alarm). */
export default function AlarmBanner() {
  const [alarms, setAlarms] = useState<Alarm[]>([]);
  useEffect(() => {
    let alive = true;
    const load = () => api<Alarm[]>("alarms?active=1").then((a) => alive && setAlarms(a)).catch(() => undefined);
    load();
    const t = setInterval(load, 2000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  if (alarms.length === 0) return null;
  const time = (s: number) => new Date(s * 1000).toLocaleTimeString("tr-TR");
  return (
    <div role="alert" aria-label="Güvenlik alarmı" className="mb-4 grid gap-2">
      {alarms.slice(0, 3).map((a) => (
        <div key={a.id} className="flex flex-wrap items-center gap-3 rounded-2xl bg-nok-600 px-4 py-3 text-white shadow-lg">
          <span className="text-lg" aria-hidden="true">🚨</span>
          <p className="min-w-0 flex-1 text-sm font-semibold">
            {ALARM_LABELS[a.type]} — {a.camera} · {time(a.firedAt)}
            {a.endedAt === null && a.type !== "test" && <span className="ml-2 rounded-full bg-white/20 px-2 py-0.5 text-[11px]">devam ediyor</span>}
          </p>
          {a.sessionId && <Link href={`/live?s=${a.sessionId}`} className="text-[13px] font-medium underline">Kamerayı aç</Link>}
          <button type="button" onClick={() => api(`alarms/${a.id}/ack`, { method: "POST" }).then(() => setAlarms((x) => x.filter((y) => y.id !== a.id)))}
                  className="h-8 rounded-[9px] bg-white px-3 text-[13px] font-semibold text-nok-600">Gördüm</button>
        </div>
      ))}
    </div>
  );
}
```

`app/(panel)/layout.tsx`: `<main …>{children}</main>` → `<main …><AlarmBanner />{children}</main>` (içe aktarma `@/components/live/AlarmBanner`).

- [ ] **Adım 4: `NotifySettings.tsx` ve sayfa**

```tsx
"use client";

import { useEffect, useState } from "react";
import { api, type NotifyConfig } from "@/lib/live";

const field = "h-10 w-full rounded-[10px] border border-line bg-white px-3 text-sm outline-none focus:border-brand-500";

/** Telegram ayarları: anahtar yalnızca analiz sunucusunda saklanır, geri gösterilmez. */
export default function NotifySettings() {
  const [cfg, setCfg] = useState<NotifyConfig | null>(null);
  const [token, setToken] = useState("");
  const [chatId, setChatId] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => {
    api<NotifyConfig>("notify").then((c) => { setCfg(c); setChatId(c.chatId); setEnabled(c.enabled); }).catch((e: Error) => setMsg({ ok: false, text: e.message }));
  }, []);
  async function save() {
    try {
      const c = await api<NotifyConfig>("notify", { method: "PUT", json: { enabled, chatId, token: token === "" ? null : token } });
      setCfg(c); setToken(""); setMsg({ ok: true, text: "Kaydedildi." });
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  }
  async function run(path: string, ok: string) {
    try { await api(path, { method: "POST", json: {} }); setMsg({ ok: true, text: ok }); }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  }
  return (
    <div className="grid items-start gap-5 lg:grid-cols-[420px_minmax(0,1fr)]">
      <section className="card grid gap-3 p-5">
        <p className="eyebrow">Telegram</p>
        <label className="block text-sm font-medium">Bot anahtarı
          <input aria-label="Bot anahtarı" type="password" autoComplete="off" className={`${field} mt-1.5`} value={token}
                 placeholder={cfg?.hasToken ? "Kayıtlı (değiştirmek için yaz)" : "123456:ABC…"} onChange={(e) => setToken(e.target.value)} />
        </label>
        {cfg?.hasToken && <p className="text-[12px] text-ok-600">Anahtar kayıtlı</p>}
        <label className="block text-sm font-medium">Sohbet / grup kimliği
          <input aria-label="Sohbet / grup kimliği" className={`${field} mt-1.5`} value={chatId} placeholder="-1001234567890" onChange={(e) => setChatId(e.target.value)} />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" aria-label="Bildirimler açık" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} className="h-4 w-4 accent-brand-500" />
          Bildirimler açık
        </label>
        <div className="grid grid-cols-3 gap-2">
          <button type="button" onClick={save} className="brand-gradient h-10 rounded-[10px] text-sm font-semibold text-white">Kaydet</button>
          <button type="button" onClick={() => run("notify/test", "Deneme mesajı gönderildi.")} className="h-10 rounded-[10px] border border-line text-sm font-medium">Deneme mesajı gönder</button>
          <button type="button" onClick={() => run("alarms/test", "Deneme alarmı oluşturuldu.")} className="h-10 rounded-[10px] border border-line text-sm font-medium">Deneme alarmı</button>
        </div>
        {msg && <p role="status" className={`rounded-xl px-3 py-2 text-sm ${msg.ok ? "bg-ok-50 text-ok-600" : "bg-nok-50 text-nok-600"}`}>{msg.text}</p>}
        <p className="text-[11.5px] text-faint">Anahtar yalnızca bu bilgisayarda saklanır; panele geri gösterilmez.</p>
      </section>
      <section className="card p-5 text-sm leading-relaxed">
        <p className="eyebrow mb-2">Kurulum</p>
        <ol className="list-decimal space-y-1.5 pl-5">
          <li>Telegram'da <b>@BotFather</b>'a yazın, <b>/newbot</b> ile bir bot oluşturun; verdiği anahtarı soldaki alana yapıştırın.</li>
          <li>Alarmların gideceği grubu açın ve botu gruba ekleyin (ya da bota doğrudan bir mesaj yazın).</li>
          <li>Grup kimliği için gruba <b>@userinfobot</b>'u ekleyin ya da gruba yazdıktan sonra <code>https://api.telegram.org/bot&lt;anahtar&gt;/getUpdates</code> adresindeki <code>chat.id</code> değerini kullanın (grup kimlikleri genelde -100 ile başlar).</li>
          <li>"Bildirimler açık"ı işaretleyip Kaydet'e, sonra "Deneme mesajı gönder"e basın.</li>
        </ol>
        <p className="mt-3 text-[12px] text-faint">Olay resmi yalnızca kamera ayarında "Olay resmini Telegram'a gönder" açıksa gider; resimler bu bilgisayarda 7 gün saklanır.</p>
      </section>
    </div>
  );
}
```

`app/(panel)/notifications/page.tsx`:

```tsx
import type { Metadata } from "next";
import NotifySettings from "@/components/live/NotifySettings";
import PageHeader from "@/components/PageHeader";

export const metadata: Metadata = { title: "Bildirimler" };

export default function NotificationsPage() {
  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader eyebrow="BİLDİRİMLER" title="Bildirimler"
                  text="Güvenlik alarmları (eller yukarı, yerde yatan kişi) panelde ve Telegram'da kamera adı ve saatle görünür." />
      <NotifySettings />
    </div>
  );
}
```

`Sidebar.tsx` `NAV`'a ("Kameralar"dan sonra):

```ts
  { href: "/notifications", label: "Bildirimler", icon: icon("M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.94 1.94 0 0 0 3.4 0") },
```

- [ ] **Adım 5: `SafetyPanel.tsx`** (yan panel ve ayarlar)

```tsx
"use client";

import { useEffect, useState } from "react";
import { ALARM_LABELS, NOTIFY_LABELS, api, type Alarm, type LiveSession, type SafetyConfig } from "@/lib/live";

export const SAFETY_DEFAULTS: SafetyConfig = { handsUp: { enabled: true, seconds: 3 }, lying: { enabled: true, seconds: 10 }, sendImage: false };

/** Güvenlik oturumunun yan paneli: izleniyor, süren durumlar, son alarmlar */
export function SafetyPanel({ session }: { session: LiveSession }) {
  const [alarms, setAlarms] = useState<Alarm[]>([]);
  useEffect(() => {
    let alive = true;
    const load = () => api<Alarm[]>("alarms").then((a) => alive && setAlarms(a.filter((x) => x.sessionId === session.id).slice(0, 10))).catch(() => undefined);
    load();
    const t = setInterval(load, 3000);
    return () => { alive = false; clearInterval(t); };
  }, [session.id]);
  const active = session.safety?.active ?? [];
  return (
    <section className="card p-4" aria-label="Güvenlik">
      <p className="flex items-center gap-2 font-semibold"><span className="h-2 w-2 rounded-full bg-ok-600" aria-hidden="true" />İzleniyor</p>
      {active.length > 0 && (
        <ul className="mt-2 grid gap-1 text-[13px]">
          {active.map((a) => <li key={`${a.trackId}-${a.type}`}>{ALARM_LABELS[a.type]}: {a.seconds.toFixed(1)} sn</li>)}
        </ul>
      )}
      <p className="mb-1.5 mt-4 text-xs font-medium text-muted">Son alarmlar</p>
      {alarms.length === 0 ? <p className="text-[13px] text-faint">Henüz alarm yok.</p> : (
        <ul className="grid gap-2">
          {alarms.map((a) => (
            <li key={a.id} className="flex items-center gap-2.5 rounded-xl border border-line p-2">
              {a.image
                // eslint-disable-next-line @next/next/no-img-element -- yerel olay resmi
                ? <img src={`/api/live/alarms/${a.id}/image.jpg`} alt="" className="h-12 w-16 rounded-lg object-cover" />
                : <span className="grid h-12 w-16 place-items-center rounded-lg bg-canvas text-lg" aria-hidden="true">🚨</span>}
              <span className="min-w-0 text-[13px]">
                <b>{ALARM_LABELS[a.type]}</b> · {new Date(a.firedAt * 1000).toLocaleTimeString("tr-TR")}
                <span className="block text-[11.5px] text-faint">{NOTIFY_LABELS[a.notify]}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Ayarla panelinde güvenlik kuralları */
export function SafetySettings({ value, onChange }: { value: SafetyConfig | undefined; onChange: (v: SafetyConfig) => void }) {
  const v = value ?? SAFETY_DEFAULTS;
  const rule = (k: "handsUp" | "lying", label: string, min: number, max: number) => (
    <div className="grid gap-1">
      <label className="flex items-center gap-2 text-sm font-medium">
        <input type="checkbox" className="h-4 w-4 accent-brand-500" checked={v[k].enabled}
               onChange={(e) => onChange({ ...v, [k]: { ...v[k], enabled: e.target.checked } })} />
        {label}
      </label>
      <label className="text-[13px]">{label} süresi: <b>{v[k].seconds} sn</b>
        <input type="range" aria-label={`${label} süresi`} min={min} max={max} step={1} value={v[k].seconds} disabled={!v[k].enabled}
               className="mt-1 w-full accent-brand-500" onChange={(e) => onChange({ ...v, [k]: { ...v[k], seconds: Number(e.target.value) } })} />
      </label>
    </div>
  );
  return (
    <div role="group" aria-label="Güvenlik kuralları" className="grid gap-3">
      {rule("handsUp", "Eller yukarı", 3, 5)}
      {rule("lying", "Yerde yatan kişi", 5, 30)}
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-0.5 h-4 w-4 accent-brand-500" checked={v.sendImage} onChange={(e) => onChange({ ...v, sendImage: e.target.checked })} />
        <span>Olay resmini Telegram'a gönder
          <span className="block text-[11.5px] text-faint">Kapalıyken yalnızca kamera adı ve saat gider. Resimler bu bilgisayarda 7 gün saklanır.</span>
        </span>
      </label>
    </div>
  );
}
```

- [ ] **Adım 6: `LiveView.tsx` ve `RoiEditor.tsx`**

`RoiEditor` imzasına `showLine = true` ekle:
- Çizgi `<line>`, ok `<path>` ve `twoWay` GİRİŞ etiketini `{showLine && (…)}` içine al.
- `handles()` sonucunu `showLine ? hs : hs.filter(([h]) => !h.kind.startsWith("line"))` ile süz.

`LiveView` içinde `const safety = p.countMode === "safety";`. Ayarla düğmesinin yazısı `{twoWay || safety ? "Ayarla" : "Kalibre"}` olur:
- **RoiEditor:** çağrısına `showLine={!safety}`.
- **Sayım bölümü:** güvenlik oturumunda sayaçlar ve giriş yönü düğmesi yerine `<SafetyPanel session={session} />`. Başlat/Sıfırla düğmeleri gizlenir; analiz sürekli çalışır. "Ayarla", "Görüntü" ve "Canlı sayımı kapat" kalır.
- **Ayarla paneli:** `safety` iken yöntem/kamera bölümleri yerine

```tsx
<SafetySettings value={p.safety} onChange={(sf) => edit({ ...p, safety: sf })} />
```

  Ardından mevcut `GeometryControls` (alan; açılı çizgi seçeneği kapalı: `allowAngled={false}`), ve "Alan: kural yalnızca alandaki kişilere uygulanır (ör. tezgah arkası)." açıklaması.
- **Oturum kartı (`SessionCard`):** `s.safety?.lastAlarmAt` varsa ve son 5 dakika içindeyse kırmızı nokta (`bg-nok-600`) ve "Alarm" yazısı; güvenlik oturumunda sayaç yerine "İzleniyor".
- Güvenlik oturumunda kullanılmayan "Başlat/Durdur" eylemi gönderilmez.

- [ ] **Adım 7: Doğrula ve commit**

Çalıştır (apps/dashboard):

```bash
npx eslint src e2e && npx tsc --noEmit && npm run build && PYTHON=<venv python> npx playwright test
```

Beklenen: tümü PASS (önceki 9 + yeni 2).

```bash
git add apps/dashboard
git commit -m "Panel: güvenlik oturumu, alarm şeridi, son alarmlar, kural ayarları ve Bildirimler sayfası"
```

---

### Görev 10: iPhone — sözleşmeyi tanı (`safety` yöntemi desteklenmiyor)

**Dosyalar:**
- Değiştir:
  - `apps/ios/BantSayac/Core/ProductProfile.swift`
  - `apps/ios/BantSayac/UI/CountingViewModel.swift`
  - `apps/ios/BantSayac/UI/ProfilesView.swift`
  - `apps/ios/BantSayac/Vision/FrameProcessor.swift`
  - `exhaustive switch` uyarısı/hatası veren diğer dosyalar (CI gösterir)

**Arayüzler:**
- Üretir: `CountMode.safety`, `struct SafetyConfig: Codable, Equatable, Sendable`, `ProductProfile.safety: SafetyConfig?`.

- [ ] **Adım 1: Kod**

`ProductProfile.swift`:

```swift
/// Poz güvenlik alarmı ayarları (sözleşme `safety`; yalnızca bilgisayardaki analiz sunucusunda çalışır)
struct SafetyConfig: Codable, Equatable, Sendable {
    struct Rule: Codable, Equatable, Sendable { var enabled: Bool; var seconds: Double }
    var handsUp: Rule
    var lying: Rule
    var sendImage: Bool
}
```

- `ProductProfile`'a `var safety: SafetyConfig? = nil` (`staffColors`'tan sonra).
- `CountMode`'a `case safety`; `title` içinde `case .safety: return "Güvenlik (yalnızca bilgisayar)"`.

`CountingViewModel.beginCalibration` switch'ine:

```swift
        case .safety:
            calibrationMessage = "Bu yöntem (güvenlik alarmı) bu cihazda desteklenmiyor; bilgisayardaki web panelinde çalışır."
```

`ProfilesView.status`: `case .safety: return "Yalnızca bilgisayarda"`.

`FrameProcessor` işlem dalında `profile.mode == .safety` ise kare yalnızca görüntülenir, sayım/izleme yapılmaz. Mevcut `process(gray:…)` başında:

```swift
        if profile.mode == .safety {                   // güvenlik alarmı yalnızca bilgisayarda (web analiz sunucusu)
            if let pb = pixelBuffer { emitDisplayImage(pb, sourceWidth: frame.sourceWidth) }
            return
        }
```

`ProductCatalog` güvenlik kategorisi eklemez (iPhone'da görünmez).

- [ ] **Adım 2: CI** — push, `gh run watch` (`ios`: derleme + 0 strict-concurrency uyarısı + testler). Hata olursa `gh run view <id> --log-failed`, düzelt, tekrar.

- [ ] **Adım 3: Commit**

```bash
git add apps/ios/BantSayac
git commit -m "iOS: sözleşmedeki safety yöntemini tanır (bu cihazda desteklenmiyor)"
```

---

### Görev 11: Ölçüm aracı ve dokümanlar

**Dosyalar:**
- Oluştur:
  - `tools/eval_pose.py`
  - `tools/tests/test_eval_pose.py`
- Değiştir:
  - `docs/03-algorithm.md` (yeni §4.11 "Poz güvenlik alarmı")
  - `docs/13-web-platform.md` (canlı API tablosu, Bildirimler)
  - `docs/12-durum.md` (durum, ölçüm BEKLİYOR)

**Arayüzler:**
- Üretir: `match_pose(labels: list[dict], alarms: list[tuple[float, str]], seconds: dict[str, float], tol: float = 2.0) -> dict`.
  - Etiket `{"t": sn, "type": "hands_up"|"lying"}`: olayın başladığı an.
  - Alarm `(zaman, tür)`.
  - Eşleşme: aynı tür, `t ≤ alarm ≤ t + seconds[type] + tol`; her alarm en fazla bir etikete.
  - Sonuç:

```
{"hands_up": {"labels", "caught"}, "lying": {"labels", "caught"}, "false": int, "hours": float}
```

  - CLI `python tools/eval_pose.py VIDEO --profile P.json --labels L.json [--every N]`.
  - Çıkış 0 yalnızca her tür için `caught/labels ≥ 0,95` (her türde ≥ 20 etiket) ve `false / hours * 8 ≤ 1` (video ≥ 1 saat; değilse yanlış alarm "yetersiz süre" olarak raporlanır ve kapı kalır).

- [ ] **Adım 1: Test** — `tools/tests/test_eval_pose.py`

```python
from __future__ import annotations

import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location("eval_pose", pathlib.Path(__file__).resolve().parents[1] / "eval_pose.py")
ev = importlib.util.module_from_spec(spec)                      # type: ignore[arg-type]
spec.loader.exec_module(ev)                                     # type: ignore[union-attr]


def test_match_pose_window_type_and_false_alarms() -> None:
    labels = [{"t": 10.0, "type": "hands_up"}, {"t": 40.0, "type": "lying"}, {"t": 80.0, "type": "hands_up"}]
    alarms = [(13.2, "hands_up"), (51.0, "lying"), (95.0, "hands_up"), (200.0, "lying")]
    r = ev.match_pose(labels, alarms, {"hands_up": 3.0, "lying": 10.0})
    assert r["hands_up"] == {"labels": 2, "caught": 1}           # 95 > 80 + 3 + 2: geç
    assert r["lying"] == {"labels": 1, "caught": 1}
    assert r["false"] == 2                                       # 95 (geç) ve 200 (etiketsiz)
```

- [ ] **Adım 2: Araç** — `tools/eval_pose.py`

```python
"""Poz güvenlik alarmı doğruluğu (kabul: tür başına ≥ %95 yakalama, kamera başına 8 saatte ≤ 1 yanlış alarm).

Kullanım: python tools/eval_pose.py VIDEO --profile PROFİL.json --labels VIDEO.pose.json [--every N]
Etiket: [{"t": saniye, "type": "hands_up"|"lying"}] — olayın başladığı an. Alarm, aynı türde t ile t + süre + 2 sn
arasında gelirse yakalanmış sayılır; eşleşmeyen alarmlar yanlış alarmdır. Profil: web panelinde kameranın kayıtlı
ayarı (<ANALYZER_DATA_DIR>/live/camera_profiles.json içindeki ilgili kayıt) ya da GET /api/v1/live/sessions/{id}
yanıtındaki "profile". Bu araç Python/web yolunu ölçer. Kayıtlar kullanıcınındır; repoya konmaz.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "edge"))
MIN_LABELS = 20


def match_pose(labels: list[dict], alarms: list[tuple[float, str]], seconds: dict[str, float],
               tol: float = 2.0) -> dict:
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


def run(video: str, profile_path: str, every: int) -> tuple[list[tuple[float, str]], float, dict[str, float]]:
    import cv2

    from bantvision.core import Pipeline, Profile

    d = json.loads(pathlib.Path(profile_path).read_text(encoding="utf-8"))
    p = Profile.from_dict(d.get("profile", d))
    pipe = Pipeline(p)
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise SystemExit(f"Video açılamadı: {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    alarms: list[tuple[float, str]] = []
    k = 0
    try:
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
    return alarms, k / fps / 3600, {"hands_up": p.safety.handsUp.seconds, "lying": p.safety.lying.seconds}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--every", type=int, default=1)
    a = ap.parse_args()
    labels = json.loads(pathlib.Path(a.labels).read_text(encoding="utf-8"))
    alarms, hours, seconds = run(a.video, a.profile, max(1, a.every))
    r = match_pose(labels, alarms, seconds)
    ok = True
    for kind, name in (("hands_up", "Eller yukarı"), ("lying", "Yerde yatan kişi")):
        n, c = r[kind]["labels"], r[kind]["caught"]
        rate = c / n if n else 0.0
        enough = n >= MIN_LABELS
        ok &= enough and rate >= 0.95
        print(f"{name}: %{100 * rate:.1f} ({c}/{n}){'' if enough else ' — en az 20 etiket gerekli'}")
    per8 = r["false"] / hours * 8 if hours > 0 else float("inf")
    if hours >= 1:
        print(f"Yanlış alarm: {r['false']} ({per8:.2f} / 8 saat)")
        ok &= per8 <= 1
    else:
        print(f"Yanlış alarm: {r['false']} — video {hours * 60:.0f} dk, en az 1 saat normal hareket gerekli")
        ok = False
    print("GEÇTİ" if ok else "KALDI")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Adım 3: Dokümanlar**

`docs/03-algorithm.md`'ye yeni `### 4.11 Poz güvenlik alarmı` bölümü:
- tasarım belgesinin "Kurallar" bölümü;
- model (MoveNet Thunder, kırpma);
- `pose_rules.py` sabitleri;
- dosyalar;
- kabul ölçütü ve `eval_pose.py`.

`docs/13-web-platform.md` canlı API tablosuna Görev 8'in yedi uç noktası. Ayrıca kısa bir "Güvenlik alarmı ve Bildirimler" paragrafı:
- Telegram kurulumu;
- anahtar `secrets.json`'da;
- resim 7 gün;
- 60 sn tekrar önleme.

`docs/12-durum.md`: "Poz güvenlik alarmı (eller yukarı, yerde yatan kişi; web + Telegram)" maddesi:
- **Gerçek ölçüm BEKLİYOR.** Gerekenler:
  - ≥ 20 eller yukarı,
  - ≥ 20 yerde yatma,
  - ≥ 1 saat normal hareket,
  - ofis bullet/dome kamerası.
- Doğruluk iddiası yok.

- [ ] **Adım 4: Doğrula ve commit**

Çalıştır: `-m pytest ../../tools/tests/test_eval_pose.py -q && ruff check . ../../tools` → PASS. CI'da `tools/tests` contracts işinde koşar (opencv gerekmez: `run` içinde içe aktarılır).

```bash
git add tools/eval_pose.py tools/tests/test_eval_pose.py docs
git commit -m "Poz güvenlik: ölçüm aracı ve dokümanlar"
```

---

### Görev 12: Gerçek ölçüm (kabul kapısı — kullanıcı yardımıyla)

- [ ] **Adım 1: Protokolü kullanıcıya ilet** (Türkçe):
  - ofis bullet/dome kamerası;
  - ≥ 20 eller yukarı (farklı kişiler; önden, yandan, tezgah arkası);
  - ≥ 20 yerde yatma (farklı yönler);
  - ≥ 1 saat normal hareket.
  - Kayıt: canlı oturum açıkken NVR'dan ya da kameradan video.
- [ ] **Adım 2: Etiketle** — `video.pose.json` (olay başlangıç saniyesi ve türü).
- [ ] **Adım 3: Ölç** — `python tools/eval_pose.py video.mp4 --profile kamera.json --labels video.pose.json`. Beklenen: `GEÇTİ`.
- [ ] **Adım 4: Tutmazsa** yalnızca ölçümle ayarla (`pose_rules.py` eşikleri, süreler). Görev 3 testlerini güncelle, yeniden ölç.
- [ ] **Adım 5:** Sonuçları `docs/12-durum.md`'ye yaz ve commit et.
