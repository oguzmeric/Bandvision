# Çoklu kamera izleme (web) — uygulama planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Web panelinde (ve telefonun tarayıcısında) birden çok kamerayı şablonlu bir ızgarada, analiz başlatmadan canlı izlemek.

**Architecture:**
- **İzleme okuyucuları:** Analiz sunucusunda kamera başına tek bir okuyucu (`ViewHub`) çalışır. Kamerada analiz oturumu varsa onun karesi kullanılır.
- **Birleştirici:** Şablonun kutularını tek JPEG'de birleştirip tek MJPEG akışı olarak verir (`MosaicHub`).
- **Panel:** Akışı tek `<img>` ile gösterir. Kamera adı, rozet ve alarm HTML katmanı olarak çizilir.
- **Şablonlar ve düzenler:** Şablonlar `views.json`'da saklanır; düzenler sözleşmedir.
- **Telefondan erişim:** Panel küçük bir başlatıcıyla ya yalnızca bu bilgisayara ya da (şifreyle) yerel ağa açılır.

**Tech Stack:** Python 3.11, FastAPI, OpenCV, numpy, pytest; Next.js 15.5 (App Router), React 19, TypeScript, Tailwind, Playwright; Node 22+ (`node --test`); npm `qrcode` (MIT).

**Spec:** `docs/superpowers/specs/2026-10-08-coklu-izleme-design.md`

## Genel kısıtlar
- **Dil:** Kullanıcıya görünen metin Türkçe; kod tanımlayıcıları İngilizce.
- **Python:** Tip ipuçları zorunlu. ruff satır uzunluğu 110, `pytest`.
- **Ağ yasağı:** Testler ağa ya da gerçek kameraya bağlanmaz. `services/edge/tests/conftest.py` model indirmeyi zaten yasaklar.
- **Sözleşme:** Sözleşmeler tek doğruluk kaynağıdır. Düzenler `contracts/view-layouts.json` (+ şema) ve şablon biçimi `contracts/view-template.schema.json` içindedir; `docs/02-contracts.md` güncellenir.
- **Analize dokunmama:** İzleme analiz oturumu **başlatmaz, durdurmaz, değiştirmez**. Kamerada oturum varsa onun ham karesi kullanılır, NVR'a ikinci bağlantı açılmaz.
- **Sınırlar ve oranlar:**
  - aynı anda en çok **16 alt akış** ve **2 ana akış** okuyucu;
  - ızgarada her zaman alt akış;
  - birleştirici saniyede en çok **10** tuval üretir;
  - tuval en çok **1920×1080**, kenarlar 16'nın katı;
  - okuyucu karesi en çok **960 px** (ana akış 1920 px) genişlik;
  - JPEG kalitesi ızgarada **75**, tek kamerada **80**.
- **Zamanlamalar:**
  - kullanılmayan okuyucu **30 sn** sonra kapanır;
  - yeniden bağlanma beklemesi **1 → 30 sn** (katlanarak);
  - panel durumu **1,5 sn**'de bir yoklar;
  - koparsa akış **2 sn** sonra yeniden açılır.
- **Düzen kimlikleri:** `1, 2, 3, 4, 6, 8, 9, 12, 16`. Hücreler tasarımdaki tabloyla birebir.
- **Şablon kuralları:**
  - ad 1–60 karakter;
  - `tiles` uzunluğu = hücre sayısı;
  - aynı kamera bir şablonda en çok bir kez;
  - "Tüm kanallardan şablon" en çok 16 kanal alır, fazlasını bildirir.
- **Analiz sunucusu** yalnızca `127.0.0.1`'de dinler. Kamera şifreleri hiçbir yanıtta yoktur.
- **Telefondan erişim:**
  - varsayılan `-H 127.0.0.1`;
  - erişim açıkken `0.0.0.0` ve **herkes için** şifre;
  - şifre en az 8 karakter, yalnızca scrypt özeti saklanır;
  - `DASHBOARD_PASSWORD` ortam değişkeni önceliklidir.
- **Belgeler:** Cihaz model adı, yerel yol, IP ya da sır yazılmaz.
- **Kayıt yok:** Izgara kayıt yapmaz (KVKK).

## İnceleme odağı
1. **Izgaradaki kamerada analiz oturumu açılıp kapanırsa** kutu donmaz, kendi okuyucusuna ya da oturum karesine kesintisiz geçer. Görev 3'te test edilir.
2. **Şablondaki kaynak silinmiş ya da kanal artık yoksa** yalnızca o kutu "Kamera silinmiş" ya da Türkçe neden gösterir; diğer kutular akmaya devam eder. Görev 3 ve 4'te test edilir.
3. **Tarayıcı sekmesi kapanır ya da telefon uykuya geçerse** birleştirici abonesiz kalınca durur, iş parçacığı sızmaz. Aynı şablon iki farklı boyutta (masaüstü ve telefon) aynı anda izlenebilir. Görev 4'te test edilir.
4. **Kamera ulaşılamaz, açıcı hata fırlatır ya da akış açılmazsa** Türkçe hata gösterilir. Yeniden deneme katlanarak beklenir; sıkı döngü olmaz. Görev 3'te test edilir.
5. **Şifresiz yerel ağ erişimi asla açılmaz:**
   - şifre değişince eski çerez geçersiz olur;
   - `DASHBOARD_PASSWORD` önceliklidir;
   - erişim kapalıyken adres `127.0.0.1` olur.

   Görev 7'de test edilir.

---

### Görev 1: Düzen sözleşmesi ve Python düzen kataloğu

**Dosyalar:**
- Oluştur: `contracts/view-layouts.json`, `contracts/view-layouts.schema.json`, `contracts/view-template.schema.json`, `contracts/examples/view-template-4.json`, `contracts/examples/view-template-empty.json`, `services/edge/bantvision/live/layouts.py`, `services/edge/tests/test_layouts.py`
- Değiştir: `tools/validate_contracts.py` (örnek öneki + veri dosyası doğrulaması), `tools/tests/test_contracts.py` (geometri değişmezleri), `docs/02-contracts.md` (yeni bölüm 8)

**Arayüzler:**
- Üretir:
  - `Layout` (frozen dataclass): `id: str`, `name: str`, `cols: int`, `rows: int`, `cells: tuple[tuple[int, int, int, int], ...]`, `to_dict() -> dict`.
  - `LAYOUTS: tuple[Layout, ...]`.
  - `layout_by_id(id: str) -> Layout | None`.
  - `smallest_for(n: int) -> Layout`.
  - `cell_rects(layout: Layout, w: int, h: int) -> list[tuple[int, int, int, int]]`: `(x0, y0, x1, y1)` piksel.

- [ ] **Adım 1: Sözleşme dosyaları**

`contracts/view-layouts.json`:

```json
{
  "version": 1,
  "layouts": [
    {"id": "1", "name": "Tek", "cols": 1, "rows": 1, "cells": [[0, 0, 1, 1]]},
    {"id": "2", "name": "2'li (yan yana)", "cols": 2, "rows": 1, "cells": [[0, 0, 1, 1], [1, 0, 1, 1]]},
    {"id": "3", "name": "3'lü (1 büyük + 2)", "cols": 3, "rows": 2, "cells": [[0, 0, 2, 2], [2, 0, 1, 1], [2, 1, 1, 1]]},
    {"id": "4", "name": "4'lü", "cols": 2, "rows": 2, "cells": [[0, 0, 1, 1], [1, 0, 1, 1], [0, 1, 1, 1], [1, 1, 1, 1]]},
    {"id": "6", "name": "6'lı (1 büyük + 5)", "cols": 3, "rows": 3,
     "cells": [[0, 0, 2, 2], [2, 0, 1, 1], [2, 1, 1, 1], [0, 2, 1, 1], [1, 2, 1, 1], [2, 2, 1, 1]]},
    {"id": "8", "name": "8'li (1 büyük + 7)", "cols": 4, "rows": 4,
     "cells": [[0, 0, 3, 3], [3, 0, 1, 1], [3, 1, 1, 1], [3, 2, 1, 1], [0, 3, 1, 1], [1, 3, 1, 1], [2, 3, 1, 1], [3, 3, 1, 1]]},
    {"id": "9", "name": "9'lu", "cols": 3, "rows": 3,
     "cells": [[0, 0, 1, 1], [1, 0, 1, 1], [2, 0, 1, 1], [0, 1, 1, 1], [1, 1, 1, 1], [2, 1, 1, 1], [0, 2, 1, 1], [1, 2, 1, 1], [2, 2, 1, 1]]},
    {"id": "12", "name": "12'li", "cols": 4, "rows": 3,
     "cells": [[0, 0, 1, 1], [1, 0, 1, 1], [2, 0, 1, 1], [3, 0, 1, 1], [0, 1, 1, 1], [1, 1, 1, 1], [2, 1, 1, 1], [3, 1, 1, 1],
               [0, 2, 1, 1], [1, 2, 1, 1], [2, 2, 1, 1], [3, 2, 1, 1]]},
    {"id": "16", "name": "16'lı", "cols": 4, "rows": 4,
     "cells": [[0, 0, 1, 1], [1, 0, 1, 1], [2, 0, 1, 1], [3, 0, 1, 1], [0, 1, 1, 1], [1, 1, 1, 1], [2, 1, 1, 1], [3, 1, 1, 1],
               [0, 2, 1, 1], [1, 2, 1, 1], [2, 2, 1, 1], [3, 2, 1, 1], [0, 3, 1, 1], [1, 3, 1, 1], [2, 3, 1, 1], [3, 3, 1, 1]]}
  ]
}
```

`contracts/view-layouts.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "view-layouts.schema.json",
  "title": "Çoklu izleme düzenleri",
  "type": "object",
  "additionalProperties": false,
  "required": ["version", "layouts"],
  "properties": {
    "version": {"const": 1},
    "layouts": {
      "type": "array", "minItems": 1,
      "items": {
        "type": "object", "additionalProperties": false,
        "required": ["id", "name", "cols", "rows", "cells"],
        "properties": {
          "id": {"enum": ["1", "2", "3", "4", "6", "8", "9", "12", "16"]},
          "name": {"type": "string", "minLength": 1, "maxLength": 40},
          "cols": {"type": "integer", "minimum": 1, "maximum": 4},
          "rows": {"type": "integer", "minimum": 1, "maximum": 4},
          "cells": {
            "type": "array", "minItems": 1, "maxItems": 16,
            "items": {"type": "array", "minItems": 4, "maxItems": 4, "items": {"type": "integer", "minimum": 0, "maximum": 4}}
          }
        }
      }
    }
  }
}
```

`contracts/view-template.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "view-template.schema.json",
  "title": "Çoklu izleme şablonu",
  "type": "object",
  "additionalProperties": false,
  "required": ["id", "name", "layout", "tiles", "createdAt", "updatedAt"],
  "properties": {
    "id": {"type": "string", "minLength": 1, "maxLength": 80},
    "name": {"type": "string", "minLength": 1, "maxLength": 60},
    "layout": {"enum": ["1", "2", "3", "4", "6", "8", "9", "12", "16"]},
    "tiles": {
      "type": "array", "minItems": 1, "maxItems": 16,
      "items": {
        "oneOf": [
          {"type": "null"},
          {"type": "object", "additionalProperties": false, "required": ["sourceId", "channelId"],
           "properties": {"sourceId": {"type": "string", "minLength": 1, "maxLength": 120},
                          "channelId": {"type": ["string", "null"], "maxLength": 120}}}
        ]
      }
    },
    "createdAt": {"type": "number"},
    "updatedAt": {"type": "number"}
  }
}
```

`contracts/examples/view-template-4.json`:

```json
{"id": "6f1c0e8e2b2c4f6c9d7a1b2c3d4e5f60", "name": "Giriş katı", "layout": "4",
 "tiles": [{"sourceId": "src-nvr", "channelId": "1"}, {"sourceId": "src-nvr", "channelId": "2"},
           {"sourceId": "src-cam", "channelId": null}, null],
 "createdAt": 1791400000.0, "updatedAt": 1791400100.0}
```

`contracts/examples/view-template-empty.json`:

```json
{"id": "a1", "name": "Boş tek", "layout": "1", "tiles": [null], "createdAt": 1791400000.0, "updatedAt": 1791400000.0}
```

- [ ] **Adım 2: Doğrulayıcıya bağla.**

`tools/validate_contracts.py`:
- `EXAMPLE_SCHEMAS` listesine `("view-template", "view-template.schema.json")` eklenir.
- `main()` içinde örneklerden sonra veri dosyası doğrulaması eklenir:

```python
# Veri dosyaları: kendi şemalarına uymalı (düzen kataloğu web ve iPhone'da birebir kullanılır)
DATA_FILES: list[tuple[str, str]] = [("view-layouts.json", "view-layouts.schema.json")]
```

`main()` içinde örnek döngüsünden sonra:

```python
    for data_name, ref in DATA_FILES:
        errs = errors_for(json.loads((CONTRACTS / data_name).read_text(encoding="utf-8")), ref, schemas)
        if errs:
            failed = True
            print(f"HATA: {data_name}")
            for e in errs:
                print(f"  - {e}")
        else:
            print(f"tamam: {data_name}")
```

`failed` ve `schemas` adları dosyadaki mevcut değişkenlerdir. Okuyup aynı adları kullan; farklıysa uyarla.

- [ ] **Adım 3: Geometri testleri (başarısız olduğunu gör)**

`tools/tests/test_contracts.py` sonuna:

```python
def _layouts() -> list[dict[str, Any]]:
    return json.loads((vc.CONTRACTS / "view-layouts.json").read_text(encoding="utf-8"))["layouts"]


def test_view_layouts_file_matches_schema() -> None:
    data = json.loads((vc.CONTRACTS / "view-layouts.json").read_text(encoding="utf-8"))
    assert vc.errors_for(data, "view-layouts.schema.json") == []


@pytest.mark.parametrize("lay", _layouts(), ids=lambda d: d["id"])
def test_view_layout_cells_tile_the_grid_exactly(lay: dict[str, Any]) -> None:
    cover = [[0] * lay["cols"] for _ in range(lay["rows"])]
    for x, y, w, h in lay["cells"]:
        assert w >= 1 and h >= 1 and x + w <= lay["cols"] and y + h <= lay["rows"], (lay["id"], x, y, w, h)
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                cover[yy][xx] += 1
    assert all(c == 1 for row in cover for c in row), f"{lay['id']}: boşluk ya da çakışma"   # tam ve çakışmasız
    assert len(lay["cells"]) == int(lay["id"])                                             # ad = kutu sayısı


def test_view_layout_ids_are_the_agreed_set() -> None:
    assert [d["id"] for d in _layouts()] == ["1", "2", "3", "4", "6", "8", "9", "12", "16"]
```

Çalıştır: `cd services/edge && .venv/Scripts/python -m pytest -q ../../tools/tests/test_contracts.py -k view`. Bu venv'de `jsonschema` yoksa bu dosya toplanamaz (bilinen durum). Önce `pip install jsonschema` gerekip gerekmediğine bak; yoksa testi CI'a bırak ve aynı denetimi `services/edge/tests/test_layouts.py`'de jsonschema'sız da yap (Adım 4).

Beklenen: dosyalar yoksa FAIL.

- [ ] **Adım 4: Python düzen kataloğu**

`services/edge/bantvision/live/layouts.py`:

```python
"""Çoklu izleme düzenleri. Sözleşme: contracts/view-layouts.json (web ve iPhone birebir aynı; tests/test_layouts.py
dosyayla eşitliği denetler). Hücre (x, y, w, h) birim ızgarada; sıra kutu sırasıdır; tuval herhangi boyutta olabilir."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

Cell = tuple[int, int, int, int]


@dataclass(frozen=True)
class Layout:
    id: str
    name: str
    cols: int
    rows: int
    cells: tuple[Cell, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "cols": self.cols, "rows": self.rows,
                "cells": [list(c) for c in self.cells]}


def _grid(cols: int, rows: int) -> tuple[Cell, ...]:
    return tuple((x, y, 1, 1) for y in range(rows) for x in range(cols))


LAYOUTS: tuple[Layout, ...] = (
    Layout("1", "Tek", 1, 1, _grid(1, 1)),
    Layout("2", "2'li (yan yana)", 2, 1, _grid(2, 1)),
    Layout("3", "3'lü (1 büyük + 2)", 3, 2, ((0, 0, 2, 2), (2, 0, 1, 1), (2, 1, 1, 1))),
    Layout("4", "4'lü", 2, 2, _grid(2, 2)),
    Layout("6", "6'lı (1 büyük + 5)", 3, 3,
           ((0, 0, 2, 2), (2, 0, 1, 1), (2, 1, 1, 1), (0, 2, 1, 1), (1, 2, 1, 1), (2, 2, 1, 1))),
    Layout("8", "8'li (1 büyük + 7)", 4, 4,
           ((0, 0, 3, 3), (3, 0, 1, 1), (3, 1, 1, 1), (3, 2, 1, 1), (0, 3, 1, 1), (1, 3, 1, 1), (2, 3, 1, 1),
            (3, 3, 1, 1))),
    Layout("9", "9'lu", 3, 3, _grid(3, 3)),
    Layout("12", "12'li", 4, 3, _grid(4, 3)),
    Layout("16", "16'lı", 4, 4, _grid(4, 4)),
)
_BY_ID = {lay.id: lay for lay in LAYOUTS}
MAX_TILES = 16


def layout_by_id(layout_id: str) -> Layout | None:
    return _BY_ID.get(layout_id)


def smallest_for(n: int) -> Layout:
    """`n` kameranın sığdığı en küçük düzen (16'dan fazlası için 16)."""
    for lay in LAYOUTS:
        if len(lay.cells) >= n:
            return lay
    return LAYOUTS[-1]


def cell_rects(layout: Layout, w: int, h: int) -> list[tuple[int, int, int, int]]:
    """Hücrelerin `w×h` tuvaldeki piksel dikdörtgenleri (x0, y0, x1, y1); kenarlar komşu hücreyle örtüşür, boşluk yok."""
    out = []
    for x, y, cw, ch in layout.cells:
        out.append((round(x * w / layout.cols), round(y * h / layout.rows),
                    round((x + cw) * w / layout.cols), round((y + ch) * h / layout.rows)))
    return out
```

`services/edge/tests/test_layouts.py`:

```python
"""Düzen kataloğu: sözleşme dosyasıyla birebir; piksel dikdörtgenleri tuvali tam kaplar."""
from __future__ import annotations

import json
import pathlib

import pytest

from bantvision.live.layouts import LAYOUTS, cell_rects, layout_by_id, smallest_for

CONTRACT = pathlib.Path(__file__).resolve().parents[3] / "contracts" / "view-layouts.json"


def test_python_catalog_equals_contract_file() -> None:
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert [lay.to_dict() for lay in LAYOUTS] == data["layouts"]


@pytest.mark.parametrize(("n", "want"), [(0, "1"), (1, "1"), (2, "2"), (3, "3"), (4, "4"), (5, "6"), (7, "8"),
                                         (9, "9"), (10, "12"), (13, "16"), (40, "16")])
def test_smallest_layout_for_channel_count(n: int, want: str) -> None:
    assert smallest_for(n).id == want


@pytest.mark.parametrize("lay", LAYOUTS, ids=lambda x: x.id)
def test_cell_rects_cover_canvas_without_overlap(lay: object) -> None:
    w, h = 1280, 720
    rects = cell_rects(lay, w, h)  # type: ignore[arg-type]
    area = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in rects)
    assert area == w * h
    assert all(0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h for x0, y0, x1, y1 in rects)


def test_unknown_layout_is_none() -> None:
    assert layout_by_id("5") is None and layout_by_id("16") is not None
```

- [ ] **Adım 5: Testler.**
  - Çalıştır: `cd services/edge && PYTHONIOENCODING=utf-8 .venv/Scripts/python -m pytest -q tests/test_layouts.py`. Beklenen: PASS.
  - `python ../../tools/validate_contracts.py` (jsonschema varsa). Beklenen: `tamam: view-layouts.json` ve örnekler tamam.
  - `ruff check . ../../tools`.

- [ ] **Adım 6: `docs/02-contracts.md`'ye bölüm "## 8. Çoklu izleme — `view-layouts.json`, `view-template.schema.json`" ekle.** İçeriği:
  - düzen kimlikleri ve hücre tablosu (tasarım belgesindeki tablo);
  - "hücre (x, y, w, h) birim ızgarada, sıra kutu sırası";
  - şablon alanları ve kurallar: ad 1–60, `tiles` uzunluğu hücre sayısı, aynı kamera bir kez, `channelId` tek kamerada `null`;
  - "kamera kimlikleri platforma özgü (web: analiz sunucusu kaynak kimliği)";
  - "Python kataloğu `bantvision/live/layouts.py` dosyayla eşitlik testinde".

- [ ] **Adım 7: Commit**

```bash
git add contracts tools/validate_contracts.py tools/tests/test_contracts.py services/edge/bantvision/live/layouts.py services/edge/tests/test_layouts.py docs/02-contracts.md
git commit -m "Çoklu izleme: düzen sözleşmesi ve Python düzen kataloğu"
```

---

### Görev 2: Şablon deposu ve şablon uç noktaları

**Dosyalar:**
- Oluştur: `services/edge/bantvision/live/views.py`, `services/edge/tests/test_views.py`
- Değiştir: `services/edge/bantvision/live/api.py` (LiveManager: `self.views`, `camera_name`; router: `/view-layouts`, `/views`, `/views/{id}`, `/views/from-recorder`)

**Arayüzler:**
- Tüketir: `layout_by_id`, `smallest_for`, `LAYOUTS` (Görev 1); `read_json`, `write_json_atomic`, `quarantine` (`live/jsonfile.py`).
- Üretir:
  - `ViewStore(root: pathlib.Path, clock: Callable[[], float] = time.time)` yöntemleri:
    - `.list() -> list[dict]`
    - `.get(view_id) -> dict | None`
    - `.create(name, layout, tiles) -> dict`
    - `.update(view_id, name, layout, tiles) -> dict | None`
    - `.delete(view_id) -> bool`
  - `ViewsBusy(Exception)`: dosya kilitli ya da yazılamıyor.
  - `LiveManager.views: ViewStore`.
  - `LiveManager.camera_name(source_id, channel_id) -> str`: ağsız; kanal adı önbellekten.
  - Uç noktalar: tasarım tablosundaki şablon uçları. Şablon JSON'u sözleşme biçimindedir.

- [ ] **Adım 1: Başarısız testler** — `services/edge/tests/test_views.py`:

```python
"""Şablon deposu ve uç noktaları (ağsız)."""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bantvision.analyzer import Settings, create_app
from bantvision.live import recorders as rec
from bantvision.live.views import ViewsBusy, ViewStore


@pytest.fixture()
def client(tmp_path: pathlib.Path) -> TestClient:
    with TestClient(create_app(Settings(data_dir=tmp_path))) as c:
        yield c


def _camera(c: TestClient, name: str = "Kapı") -> str:
    r = c.post("/api/v1/live/sources", json={"kind": "camera", "brand": "custom", "customUrl": "rtsp://kamera/akis",
                                             "name": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_layouts_endpoint_lists_contract_catalog(client: TestClient) -> None:
    ids = [x["id"] for x in client.get("/api/v1/live/view-layouts").json()]
    assert ids == ["1", "2", "3", "4", "6", "8", "9", "12", "16"]


def test_create_update_delete_view(client: TestClient, tmp_path: pathlib.Path) -> None:
    sid = _camera(client)
    r = client.post("/api/v1/live/views", json={"name": " Giriş ", "layout": "2",
                                                 "tiles": [{"sourceId": sid, "channelId": None}, None]})
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["name"] == "Giriş" and v["layout"] == "2" and len(v["tiles"]) == 2
    assert json.loads((tmp_path / "live" / "views.json").read_text(encoding="utf-8"))[0]["id"] == v["id"]
    r = client.put(f"/api/v1/live/views/{v['id']}", json={"name": "Giriş katı", "layout": "4",
                                                          "tiles": [None, {"sourceId": sid, "channelId": None}, None, None]})
    assert r.status_code == 200 and r.json()["layout"] == "4" and r.json()["updatedAt"] >= v["updatedAt"]
    assert [x["name"] for x in client.get("/api/v1/live/views").json()] == ["Giriş katı"]
    assert client.delete(f"/api/v1/live/views/{v['id']}").status_code == 204
    assert client.get("/api/v1/live/views").json() == []
    assert client.delete(f"/api/v1/live/views/{v['id']}").status_code == 404


@pytest.mark.parametrize(("body", "msg"), [
    ({"name": "", "layout": "1", "tiles": [None]}, "ad"),
    ({"name": "x" * 61, "layout": "1", "tiles": [None]}, None),
    ({"name": "A", "layout": "5", "tiles": [None]}, "Düzen"),
    ({"name": "A", "layout": "2", "tiles": [None]}, "kutu"),
    ({"name": "A", "layout": "2", "tiles": [{"sourceId": "s1", "channelId": None}, {"sourceId": "s1", "channelId": None}]},
     "bir kez"),
    ({"name": "A", "layout": "1", "tiles": [{"sourceId": "../x", "channelId": None}]}, None),
])
def test_view_validation_is_422_turkish(client: TestClient, body: dict[str, Any], msg: str | None) -> None:
    r = client.post("/api/v1/live/views", json=body)
    assert r.status_code == 422
    if msg:
        assert msg in r.json()["detail"]


def test_from_recorder_picks_smallest_layout_and_caps_16(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    r = client.post("/api/v1/live/sources", json={"kind": "recorder", "recorderBrand": "hikvision",
                                                  "host": "nvr.example", "username": "u", "password": "p",
                                                  "name": "Ofis NVR"})
    sid = r.json()["id"]
    mgr = client.app.state.live
    for n, want, cut in ((7, "8", False), (20, "16", True)):
        chans = [rec.RecorderChannel(id=str(i), name=f"K{i}", number=i, has_substream=True) for i in range(1, n + 1)]
        monkeypatch.setattr(mgr, "channels", lambda src, refresh=False, c=chans: c)
        v = client.post("/api/v1/live/views/from-recorder", json={"sourceId": sid}).json()
        assert v["layout"] == want and v["truncated"] is cut
        assert [t["channelId"] for t in v["tiles"] if t][:3] == ["1", "2", "3"]
        assert sum(1 for t in v["tiles"] if t) == min(n, 16)
    names = [x["name"] for x in client.get("/api/v1/live/views").json()]
    assert names == ["Ofis NVR · tüm kanallar", "Ofis NVR · tüm kanallar 2"]


def test_from_recorder_rejects_plain_camera(client: TestClient) -> None:
    sid = _camera(client)
    assert client.post("/api/v1/live/views/from-recorder", json={"sourceId": sid}).status_code == 400


def test_corrupt_views_file_is_quarantined(tmp_path: pathlib.Path) -> None:
    (tmp_path / "live").mkdir()
    (tmp_path / "live" / "views.json").write_text("{bozuk", encoding="utf-8")
    store = ViewStore(tmp_path)
    assert store.list() == []
    assert (tmp_path / "live" / "views.json.corrupt").exists()


def test_locked_views_file_is_never_overwritten(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bantvision.live import views as views_mod

    (tmp_path / "live").mkdir()
    f = tmp_path / "live" / "views.json"
    f.write_text(json.dumps([{"id": "eski", "name": "Eski", "layout": "1", "tiles": [None],
                              "createdAt": 1.0, "updatedAt": 1.0}]), encoding="utf-8")
    real = views_mod.read_json
    locked = {"on": True}

    def fake(path: pathlib.Path, delays: Any = None) -> Any:
        if locked["on"]:
            return views_mod.JsonRead(None, "unreadable")
        return real(path, ())

    monkeypatch.setattr(views_mod, "read_json", fake)
    store = ViewStore(tmp_path)
    assert store.list() == []                                    # okunamadı: boş görünür ama dosyaya dokunulmaz
    with pytest.raises(ViewsBusy):
        store.create("Yeni", "1", [None])
    assert "eski" in f.read_text(encoding="utf-8")
    locked["on"] = False
    store.create("Yeni", "1", [None])                            # okunabilince diskteki liste korunur
    assert [v["name"] for v in store.list()] == ["Eski", "Yeni"]


def test_camera_name_uses_cached_channel_title_without_network(client: TestClient) -> None:
    mgr = client.app.state.live
    sid = _camera(client, "Kapı")
    assert mgr.camera_name(sid, None) == "Kapı"
    assert mgr.camera_name("yok", None) == "Silinmiş kamera"
    nvr = client.post("/api/v1/live/sources", json={"kind": "recorder", "recorderBrand": "hikvision",
                                                    "host": "nvr.example", "username": "u", "password": "p",
                                                    "name": "Ofis NVR"}).json()["id"]
    assert mgr.camera_name(nvr, "3") == "Ofis NVR · 3"                 # önbellekte yok: kanal kimliği (ağa çıkılmaz)
    mgr._channels[nvr] = [rec.RecorderChannel(id="3", name="Kasa", number=3, has_substream=True)]
    assert mgr.camera_name(nvr, "3") == "Ofis NVR · Kasa"
```

Çalıştır: `PYTHONIOENCODING=utf-8 .venv/Scripts/python -m pytest -q tests/test_views.py`. Beklenen: FAIL (`bantvision.live.views` yok).

- [ ] **Adım 2: `services/edge/bantvision/live/views.py`**

```python
"""Çoklu izleme şablonları (<data>/live/views.json). Biçim: contracts/view-template.schema.json.

Kilitli dosya (Windows) açılışta okunamazsa liste boş görünür ama dosyaya **yazılmaz**: sonraki yazmada yeniden okunur;
hâlâ okunamıyorsa `ViewsBusy` (API 503). Bozuk dosya kenara alınır (`views.json.corrupt`).
"""
from __future__ import annotations

import copy
import logging
import pathlib
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from .jsonfile import JsonRead, quarantine, read_json, write_json_atomic
from .layouts import layout_by_id

_LOG = logging.getLogger(__name__)
__all__ = ["JsonRead", "ViewStore", "ViewsBusy", "read_json"]


class ViewsBusy(Exception):
    """Şablon dosyası şu an okunamıyor ya da yazılamıyor."""


def _valid(rec: Any) -> bool:
    return (isinstance(rec, dict) and isinstance(rec.get("id"), str) and isinstance(rec.get("name"), str)
            and layout_by_id(str(rec.get("layout"))) is not None and isinstance(rec.get("tiles"), list))


class ViewStore:
    def __init__(self, root: pathlib.Path, clock: Callable[[], float] = time.time) -> None:
        self._file = root / "live" / "views.json"
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._lock = threading.Lock()
        self._unread = False
        self._views: list[dict[str, Any]] = self._load()

    def _load(self) -> list[dict[str, Any]]:
        r = read_json(self._file)
        if r.status == "missing":
            return []
        if r.status == "corrupt" or (r.status == "ok" and not isinstance(r.data, list)):
            _LOG.error("Şablon dosyası bozuk; kenara alındı (%s)", self._file.name)
            quarantine(self._file)
            return []
        if r.status == "unreadable":
            _LOG.error("Şablon dosyası okunamadı (kilitli olabilir); yazmadan önce yeniden denenecek")
            self._unread = True
            return []
        return [v for v in r.data if _valid(v)]

    def _ensure_read(self) -> None:
        if not self._unread:
            return
        r = read_json(self._file)
        if r.status == "unreadable":
            raise ViewsBusy("Şablon dosyası şu an okunamıyor; biraz sonra yeniden deneyin.")
        self._unread = False
        self._views = [v for v in r.data if _valid(v)] if r.status == "ok" and isinstance(r.data, list) else []

    def _save(self) -> None:
        try:
            write_json_atomic(self._file, self._views, indent=2)
        except OSError as e:
            raise ViewsBusy("Şablonlar kaydedilemedi (disk ya da dosya kilidi).") from e

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._views)

    def get(self, view_id: str) -> dict[str, Any] | None:
        with self._lock:
            for v in self._views:
                if v["id"] == view_id:
                    return copy.deepcopy(v)
        return None

    def create(self, name: str, layout: str, tiles: list[dict[str, Any] | None]) -> dict[str, Any]:
        with self._lock:
            self._ensure_read()
            now = self._clock()
            v = {"id": uuid.uuid4().hex, "name": name, "layout": layout, "tiles": copy.deepcopy(tiles),
                 "createdAt": now, "updatedAt": now}
            self._views.append(v)
            try:
                self._save()
            except ViewsBusy:
                self._views.remove(v)
                raise
            return copy.deepcopy(v)

    def update(self, view_id: str, name: str, layout: str,
               tiles: list[dict[str, Any] | None]) -> dict[str, Any] | None:
        with self._lock:
            self._ensure_read()
            for i, v in enumerate(self._views):
                if v["id"] == view_id:
                    old = self._views[i]
                    self._views[i] = {**v, "name": name, "layout": layout, "tiles": copy.deepcopy(tiles),
                                      "updatedAt": max(self._clock(), v["updatedAt"])}
                    try:
                        self._save()
                    except ViewsBusy:
                        self._views[i] = old
                        raise
                    return copy.deepcopy(self._views[i])
        return None

    def delete(self, view_id: str) -> bool:
        with self._lock:
            self._ensure_read()
            keep = [v for v in self._views if v["id"] != view_id]
            if len(keep) == len(self._views):
                return False
            old, self._views = self._views, keep
            try:
                self._save()
            except ViewsBusy:
                self._views = old
                raise
            return True
```

- [ ] **Adım 3: `api.py` — modeller ve LiveManager.**

İçe aktarmalar:

```python
from .layouts import LAYOUTS, MAX_TILES, layout_by_id, smallest_for
from .views import ViewsBusy, ViewStore
```

Modeller (`TestAlarmIn`'den sonra):

```python
_REF = r"^(?!\.+$)[A-Za-z0-9._:{}-]{1,120}$"      # kaynak/kanal kimliği (TRASSIR GUID, kanal no, uuid)


class TileIn(_Strict):
    sourceId: str = Field(pattern=_REF)
    channelId: str | None = Field(default=None, pattern=_REF)


class ViewIn(_Strict):
    name: str = Field(max_length=60)
    layout: str = Field(max_length=4)
    tiles: list[TileIn | None] = Field(max_length=MAX_TILES)


class FromRecorderIn(_Strict):
    sourceId: str = Field(pattern=_REF)
```

`LiveManager.__init__` sonuna, `self.alarms`'tan sonra:

```python
        self.views = ViewStore(root)
```

Yöntem (`channel`'dan sonra):

```python
    def camera_name(self, source_id: str, channel_id: str | None) -> str:
        """Kutu etiketi: kaynak adı (+ kanal adı). Ağa çıkmaz: kanal adı önbellekte yoksa kanal kimliği yazılır."""
        src = self.store.source(source_id)
        if src is None:
            return "Silinmiş kamera"
        name = str(src.get("name") or "").strip() or "Kamera"
        if not channel_id:
            return name
        for c in self._channels.get(source_id, []):
            if c.id == channel_id:
                return f"{name} · {c.title.strip()}"
        return f"{name} · {channel_id}"
```

Doğrulama yardımcısı (dosya sonundaki yardımcıların yanına):

```python
def _view_body(body: ViewIn) -> tuple[str, str, list[dict[str, Any] | None]]:
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Şablon adı boş olamaz.")
    lay = layout_by_id(body.layout)
    if lay is None:
        raise HTTPException(422, "Düzen bulunamadı.")
    if len(body.tiles) != len(lay.cells):
        raise HTTPException(422, f"Bu düzende {len(lay.cells)} kutu var; {len(body.tiles)} kutu gönderildi.")
    tiles: list[dict[str, Any] | None] = [None if t is None else {"sourceId": t.sourceId, "channelId": t.channelId}
                                          for t in body.tiles]
    seen = [(t["sourceId"], t["channelId"]) for t in tiles if t]
    if len(seen) != len(set(seen)):
        raise HTTPException(422, "Aynı kamera bir şablonda yalnızca bir kez yer alabilir.")
    return name, lay.id, tiles
```

Pydantic'in kendi 422'si (ör. 61 karakterlik ad, bozuk kimlik) uygulama genelindeki işleyicide `{type, loc, msg}` olarak döner; testler yalnızca durum kodunu bekler.

- [ ] **Adım 4: Uç noktalar** (`make_router` içinde, `snapshot`'tan sonra)

```python
    # ---------------------------------------------------------------- çoklu izleme şablonları

    @r.get("/view-layouts")
    def view_layouts() -> list[dict[str, Any]]:
        return [lay.to_dict() for lay in LAYOUTS]

    @r.get("/views")
    def views() -> list[dict[str, Any]]:
        return manager.views.list()

    @r.post("/views")
    def create_view(body: ViewIn) -> dict[str, Any]:
        name, layout, tiles = _view_body(body)
        try:
            return manager.views.create(name, layout, tiles)
        except ViewsBusy as e:
            raise HTTPException(503, str(e)) from e

    @r.put("/views/{view_id}")
    def update_view(view_id: str, body: ViewIn) -> dict[str, Any]:
        name, layout, tiles = _view_body(body)
        try:
            v = manager.views.update(view_id, name, layout, tiles)
        except ViewsBusy as e:
            raise HTTPException(503, str(e)) from e
        if v is None:
            raise HTTPException(404, "Şablon bulunamadı.")
        return v

    @r.delete("/views/{view_id}", status_code=204)
    def delete_view(view_id: str) -> Response:
        try:
            ok = manager.views.delete(view_id)
        except ViewsBusy as e:
            raise HTTPException(503, str(e)) from e
        if not ok:
            raise HTTPException(404, "Şablon bulunamadı.")
        return Response(status_code=204)

    @r.post("/views/from-recorder")
    def view_from_recorder(body: FromRecorderIn) -> dict[str, Any]:
        """Kayıt cihazının kanallarından şablon: kanal sayısına uyan en küçük düzen, en çok 16 kanal (fazlası bildirilir)."""
        src = manager.source_or_404(body.sourceId)
        if src["kind"] != "recorder":
            raise HTTPException(400, "Bu kaynak bir kayıt cihazı değil.")
        try:
            chans = manager.channels(src)
        except rec.RecorderError as e:
            raise _err(e) from e
        if not chans:
            raise HTTPException(422, "Kayıt cihazında kamera bulunamadı.")
        used = chans[:MAX_TILES]
        lay = smallest_for(len(used))
        tiles: list[dict[str, Any] | None] = [{"sourceId": src["id"], "channelId": c.id} for c in used]
        tiles += [None] * (len(lay.cells) - len(tiles))
        base = f"{str(src.get('name') or '').strip() or 'Kayıt cihazı'} · tüm kanallar"
        name = _unique_name(base, {v["name"] for v in manager.views.list()})[:60]
        try:
            v = manager.views.create(name, lay.id, tiles)
        except ViewsBusy as e:
            raise HTTPException(503, str(e)) from e
        return {**v, "truncated": len(chans) > MAX_TILES, "channelCount": len(chans)}
```

- [ ] **Adım 5: Geç.**
  - Çalıştır: `PYTHONIOENCODING=utf-8 .venv/Scripts/python -m pytest -q tests/test_views.py tests/test_layouts.py tests/test_live.py -k "view or layout or source"`, ardından `ruff check . ../../tools`.
  - Beklenen: PASS.

- [ ] **Adım 6: Commit**

```bash
git add services/edge/bantvision/live/views.py services/edge/bantvision/live/api.py services/edge/tests/test_views.py
git commit -m "Çoklu izleme: şablon deposu ve şablon uç noktaları"
```

---

### Görev 3: İzleme okuyucuları (`ViewHub`)

**Dosyalar:**
- Oluştur: `services/edge/bantvision/live/viewer.py`, `services/edge/tests/test_viewer.py`
- Değiştir:
  - `services/edge/bantvision/live/session.py`: `latest_frame()`.
  - `services/edge/bantvision/live/api.py`:
    - `LiveManager.viewers: ViewHub`;
    - `_view_opener`, `_session_for`;
    - kapanışta `viewers.stop()`.
  - `services/edge/bantvision/analyzer/app.py`: kapanış sırası.

**Arayüzler:**
- Tüketir: `LiveManager.opener(src, channel_id, substream, lazy=True)`, `open_capture(url)`.
- Üretir:
  - `TileFrame(seq: int, frame: np.ndarray | None, state: str, message: str, fps: float)`. `state` şunlardan biridir: `"connecting"`, `"live"`, `"error"`.
  - `ViewHub(opener, find_session, capture=open_capture, clock=time.monotonic, reaper=True)`:
    - `.tile(source_id, channel_id, quality="sub") -> TileFrame`: gerekirse okuyucu açar.
    - `.peek(...) -> TileFrame`: açmaz.
    - `.sweep() -> int`.
    - `.open_count(quality) -> int`.
    - `.stop()`.
  - `SourceGone(LookupError)`.
  - `LiveSession.latest_frame() -> tuple[int, np.ndarray] | None`.
  - Sabitler: `MAX_SUB = 16`, `MAX_MAIN = 2`, `IDLE_S = 30.0`, `MAX_WIDTH = {"sub": 960, "main": 1920}`.

- [ ] **Adım 1: Başarısız testler** — `services/edge/tests/test_viewer.py`:

```python
"""İzleme okuyucuları: paylaşım, boşta kapanma, oturum karesi, sınırlar, hata ve yeniden deneme (ağsız, sahte açıcı)."""
from __future__ import annotations

import threading
import time
from typing import Any

import numpy as np
import pytest

from bantvision.live.viewer import IDLE_S, MAX_SUB, SourceGone, ViewHub


class FakeCap:
    """Okundukça kare veren sahte akış; `fail=True` hiç açılmaz; `frames` sonra akış biter."""

    def __init__(self, opened: bool = True, frames: int = 10_000, w: int = 1920, h: int = 1080) -> None:
        self._opened, self._left, self.w, self.h = opened, frames, w, h

    def isOpened(self) -> bool:
        return self._opened

    def read(self) -> tuple[bool, Any]:
        if self._left <= 0:
            return False, None
        self._left -= 1
        time.sleep(0.005)
        return True, np.full((self.h, self.w, 3), 100, np.uint8)

    def release(self) -> None:
        pass


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def make_hub(caps: Any = None, sessions: dict[tuple[str, str | None], Any] | None = None,
             gone: set[str] | None = None, clock: Any = time.monotonic) -> tuple[ViewHub, list[str]]:
    opened: list[str] = []

    def opener(source_id: str, channel_id: str | None, sub: bool) -> tuple[Any, Any]:
        if gone and source_id in gone:
            raise SourceGone("Kamera silinmiş.")
        return (lambda: f"rtsp://{source_id}/{channel_id}/{'sub' if sub else 'main'}"), None

    def capture(url: str) -> Any:
        opened.append(url)
        return caps(url) if caps else FakeCap()

    hub = ViewHub(opener, lambda s, c: (sessions or {}).get((s, c)), capture=capture, clock=clock, reaper=False)
    return hub, opened


def wait(fn: Any, timeout: float = 5.0) -> Any:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.02)
    raise AssertionError("zaman aşımı")


def test_one_reader_per_camera_shared_and_downscaled() -> None:
    hub, opened = make_hub()
    try:
        t = wait(lambda: (x := hub.tile("a", "1")).frame is not None and x)
        assert t.state == "live" and t.frame.shape[1] == 960                    # alt akış 960 px'e küçültülür
        hub.tile("a", "1")
        hub.tile("a", "1")
        assert opened == ["rtsp://a/1/sub"]                                      # aynı kamera tek bağlantı
    finally:
        hub.stop()


def test_idle_reader_closes_after_30s() -> None:
    clock = Clock()
    hub, _ = make_hub(clock=clock)
    try:
        hub.tile("a", None)
        assert hub.open_count("sub") == 1
        clock.t += IDLE_S - 1
        assert hub.sweep() == 0
        clock.t += 2
        assert hub.sweep() == 1 and hub.open_count("sub") == 0
    finally:
        hub.stop()


def test_running_session_frame_is_reused_without_second_connection() -> None:
    class Sess:
        status = type("St", (), {"state": "live", "message": "", "fps": 12.0})()

        def latest_frame(self) -> tuple[int, np.ndarray]:
            return 7, np.zeros((480, 640, 3), np.uint8)

    sessions: dict[tuple[str, str | None], Any] = {("a", "1"): Sess()}
    hub, opened = make_hub(sessions=sessions)
    try:
        t = hub.tile("a", "1")
        assert t.seq == 7 and t.frame is not None and t.state == "live" and opened == []
        sessions.clear()                                                         # oturum kapandı: kendi okuyucusu açılır
        wait(lambda: hub.tile("a", "1").frame is not None)
        assert opened == ["rtsp://a/1/sub"]
    finally:
        hub.stop()


def test_limit_16_sub_readers() -> None:
    hub, _ = make_hub()
    try:
        for i in range(MAX_SUB):
            assert hub.tile(f"s{i}", None).message == ""
        t = hub.tile("fazla", None)
        assert t.state == "error" and "Sınır aşıldı" in t.message
        assert hub.open_count("sub") == MAX_SUB
    finally:
        hub.stop()


def test_deleted_source_and_unopenable_stream_are_turkish_errors_with_backoff() -> None:
    hub, opened = make_hub(caps=lambda url: FakeCap(opened=False), gone={"silindi"})
    try:
        assert hub.tile("silindi", None).message == "Kamera silinmiş."
        t = wait(lambda: (x := hub.tile("kapali", None)).state == "error" and x)
        assert "açılamadı" in t.message
        time.sleep(1.5)
        assert len([u for u in opened if "kapali" in u]) <= 2                    # sıkı döngü yok: 1 sn, 2 sn bekleme
    finally:
        hub.stop()


def test_peek_does_not_open_a_reader() -> None:
    hub, opened = make_hub()
    try:
        t = hub.peek("a", None)
        assert t.state == "connecting" and opened == [] and hub.open_count("sub") == 0
    finally:
        hub.stop()


def test_stop_joins_reader_threads() -> None:
    hub, _ = make_hub()
    hub.tile("a", None)
    before = threading.active_count()
    hub.stop()
    wait(lambda: threading.active_count() < before)
```

Çalıştır: `PYTHONIOENCODING=utf-8 .venv/Scripts/python -m pytest -q tests/test_viewer.py`. Beklenen: FAIL (modül yok).

- [ ] **Adım 2: `LiveSession.latest_frame`** — `session.py`'de `raw_jpeg`'den önce:

```python
    def latest_frame(self) -> tuple[int, np.ndarray] | None:
        """Son okunan ham kare (sıra, kare). Çoklu izleme NVR'a ikinci bağlantı açmadan bunu kullanır; yan etkisi yok."""
        with self._frame_cv:
            if self._latest is None:
                return None
            return self._latest[0], self._latest[2]
```

- [ ] **Adım 3: `services/edge/bantvision/live/viewer.py`**

```python
"""Çoklu izleme okuyucuları: kameranın ham görüntüsünü analiz oturumu açmadan okur
(tasarım docs/superpowers/specs/2026-10-08-coklu-izleme-design.md).

- Anahtar (kaynak, kanal, kalite). Aynı anahtar için tek okuyucu.
- Kamerada analiz oturumu varsa onun son karesi kullanılır (NVR'a ikinci bağlantı yok). İzleme oturumlara dokunmaz.
- IDLE_S boyunca istenmeyen okuyucu kapanır. En çok MAX_SUB alt akış ve MAX_MAIN ana akış.
- Kopunca katlanarak bekler (1 → 30 sn).
"""
from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import cv2
import numpy as np

from .session import open_capture

_LOG = logging.getLogger(__name__)
Quality = Literal["sub", "main"]
Key = tuple[str, str | None, str]
MAX_SUB = 16
MAX_MAIN = 2
IDLE_S = 30.0
REAP_EVERY_S = 5.0
BACKOFF_MAX_S = 30.0
MAX_WIDTH: dict[str, int] = {"sub": 960, "main": 1920}
LIMITS: dict[str, tuple[int, str]] = {
    "sub": (MAX_SUB, "Sınır aşıldı (en çok 16 kamera)."),
    "main": (MAX_MAIN, "Sınır aşıldı (aynı anda en çok 2 net görüntü)."),
}
Opener = Callable[[str, str | None, bool], tuple[Callable[[], str], Callable[[str], None] | None]]


class SourceGone(LookupError):
    """Şablondaki kamera artık yok (kaynak silinmiş)."""


@dataclass
class TileFrame:
    seq: int
    frame: np.ndarray | None
    state: str                  # "connecting" | "live" | "error"
    message: str
    fps: float


def downscale(frame: np.ndarray, max_w: int) -> np.ndarray:
    h, w = frame.shape[:2]
    if w <= max_w:
        return frame
    return cv2.resize(frame, (max_w, max(1, round(h * max_w / w))), interpolation=cv2.INTER_AREA)


class CameraViewer:
    """Bir kameranın izleme okuyucusu (kendi iş parçacığı)."""

    def __init__(self, key: Key, open_url: Callable[[], str], keep_alive: Callable[[str], None] | None,
                 capture: Callable[[str], Any], clock: Callable[[], float]) -> None:
        self.key = key
        self._open_url, self._keep_alive, self._capture, self._clock = open_url, keep_alive, capture, clock
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._seq = 0
        self._frame: np.ndarray | None = None
        self._state, self._message = "connecting", ""
        self._stamps: list[float] = []
        self.last_used = clock()
        self._thread = threading.Thread(target=self._run, name=f"izleme-{key[0][:8]}", daemon=True)
        self._thread.start()

    def touch(self) -> None:
        self.last_used = self._clock()

    def snapshot(self) -> TileFrame:
        with self._lock:
            fps = 0.0
            if len(self._stamps) >= 2:
                span = self._stamps[-1] - self._stamps[0]
                fps = (len(self._stamps) - 1) / span if span > 0 else 0.0
            return TileFrame(self._seq, self._frame, self._state, self._message, round(fps, 1))

    def stop(self, join: float = 2.0) -> None:
        self._stop.set()
        self._thread.join(join)

    def _set(self, state: str, message: str) -> None:
        with self._lock:
            self._state, self._message = state, message

    def _run(self) -> None:
        backoff = 1.0
        max_w = MAX_WIDTH[self.key[2]]
        while not self._stop.is_set():
            try:
                url = self._open_url()
            except Exception as e:  # noqa: BLE001 — kayıt cihazı yanıt vermedi; yeniden denenir
                self._set("error", f"Kaynağa ulaşılamadı: {e}")
                self._stop.wait(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX_S)
                continue
            cap = self._capture(url)
            if not cap.isOpened():
                cap.release()
                self._set("error", "Görüntü açılamadı; yeniden deneniyor.")
                self._stop.wait(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX_S)
                continue
            is_file = not url.lower().startswith(("rtsp://", "http://", "https://"))
            file_fps = (cap.get(cv2.CAP_PROP_FPS) if hasattr(cap, "get") else 0.0) or 25.0
            started, n, last_ping = time.monotonic(), 0, time.monotonic()
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    break
                n += 1
                small = downscale(frame, max_w)
                now = self._clock()
                with self._lock:
                    self._seq += 1
                    self._frame = small
                    self._state, self._message = "live", ""
                    self._stamps = [s for s in self._stamps if now - s <= 2.0] + [now]
                backoff = 1.0
                if is_file:                                  # yalnızca test: dosya gerçek zamanlı oynar
                    lag = n / file_fps - (time.monotonic() - started)
                    if lag > 0:
                        self._stop.wait(lag)
                if self._keep_alive and time.monotonic() - last_ping > 5:
                    last_ping = time.monotonic()
                    threading.Thread(target=self._ping, args=(url,), daemon=True).start()
            cap.release()
            if self._stop.is_set():
                return
            if is_file:                                       # test dosyası başa sarar (canlı kamera gibi)
                continue
            self._set("error", "Görüntü kesildi; yeniden bağlanılıyor.")
            self._stop.wait(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX_S)

    def _ping(self, url: str) -> None:
        with contextlib.suppress(Exception):
            if self._keep_alive:
                self._keep_alive(url)


class ViewHub:
    """Tüm izleme okuyucuları. `find_session(kaynak, kanal)` o kamerada çalışan analiz oturumunu ya da None verir."""

    def __init__(self, opener: Opener, find_session: Callable[[str, str | None], Any],
                 capture: Callable[[str], Any] = open_capture, clock: Callable[[], float] = time.monotonic,
                 reaper: bool = True) -> None:
        self._opener, self._find_session, self._capture, self._clock = opener, find_session, capture, clock
        self._lock = threading.Lock()
        self._viewers: dict[Key, CameraViewer] = {}
        self._stop = threading.Event()
        if reaper:
            threading.Thread(target=self._reap, name="izleme-temizlik", daemon=True).start()

    def _from_session(self, s: Any, quality: str) -> TileFrame:
        got = s.latest_frame()
        st = s.status
        state = {"live": "live", "connecting": "connecting", "reconnecting": "connecting"}.get(st.state, "error")
        frame = downscale(got[1], MAX_WIDTH[quality]) if got else None
        return TileFrame(got[0] if got else 0, frame, state, st.message, float(st.fps))

    def tile(self, source_id: str, channel_id: str | None, quality: str = "sub") -> TileFrame:
        s = self._find_session(source_id, channel_id)
        if s is not None:
            return self._from_session(s, quality)
        key: Key = (source_id, channel_id, quality)
        with self._lock:
            v = self._viewers.get(key)
            if v is None:
                limit, msg = LIMITS[quality]
                if sum(1 for k in self._viewers if k[2] == quality) >= limit:
                    return TileFrame(0, None, "error", msg, 0.0)
                try:
                    open_url, keep_alive = self._opener(source_id, channel_id, quality == "sub")
                except SourceGone as e:
                    return TileFrame(0, None, "error", str(e) or "Kamera silinmiş.", 0.0)
                except Exception as e:  # noqa: BLE001 — kaynak ayarı geçersiz (ör. adres eksik)
                    detail = getattr(e, "detail", None) or str(e)
                    return TileFrame(0, None, "error", f"Kaynağa ulaşılamadı: {detail}", 0.0)
                v = CameraViewer(key, open_url, keep_alive, self._capture, self._clock)
                self._viewers[key] = v
            v.touch()
        return v.snapshot()

    def peek(self, source_id: str, channel_id: str | None, quality: str = "sub") -> TileFrame:
        s = self._find_session(source_id, channel_id)
        if s is not None:
            return self._from_session(s, quality)
        with self._lock:
            v = self._viewers.get((source_id, channel_id, quality))
        return v.snapshot() if v else TileFrame(0, None, "connecting", "", 0.0)

    def open_count(self, quality: str) -> int:
        with self._lock:
            return sum(1 for k in self._viewers if k[2] == quality)

    def sweep(self) -> int:
        now = self._clock()
        with self._lock:
            idle = [k for k, v in self._viewers.items() if now - v.last_used > IDLE_S]
            gone = [self._viewers.pop(k) for k in idle]
        for v in gone:
            v.stop(join=0.5)
        return len(gone)

    def _reap(self) -> None:
        while not self._stop.wait(REAP_EVERY_S):
            try:
                self.sweep()
            except Exception:  # noqa: BLE001 — temizlik iş parçacığı ölmesin
                _LOG.exception("İzleme okuyucusu temizliği başarısız")

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            gone = list(self._viewers.values())
            self._viewers.clear()
        for v in gone:
            v.stop()
```

- [ ] **Adım 4: LiveManager'a bağla** (`api.py`).

`LiveManager.__init__` içinde `self.views = ViewStore(root)`'tan sonra:

```python
        self.viewers = ViewHub(self._view_opener, self._session_for)
```

İçe aktarma: `from .viewer import SourceGone, ViewHub`.

Yöntemler (`camera_name`'den sonra):

```python
    def _view_opener(self, source_id: str, channel_id: str | None, sub: bool
                     ) -> tuple[Callable[[], str], Callable[[str], None] | None]:
        """İzleme okuyucusunun adres üreticisi: kanal bilgisi ilk bağlanışta istenir (açılış beklemez)."""
        src = self.store.source(source_id)
        if src is None:
            raise SourceGone("Kamera silinmiş.")
        if src["kind"] == "recorder" and not channel_id:
            raise SourceGone("Kayıt cihazından kamera seçilmemiş.")
        return self.opener(src, channel_id, sub, lazy=True)

    def _session_for(self, source_id: str, channel_id: str | None) -> LiveSession | None:
        for s in list(self.sessions.values()):
            if getattr(s, "source_id", None) == source_id and getattr(s, "channel_id", None) == channel_id:
                return s
        return None
```

`analyzer/app.py` kapanışında `live.stop_background()`'tan hemen sonra:

```python
        live.viewers.stop()                                  # izleme okuyucuları (kameralar bırakılır)
```

`stop_background` yöntemine bir şey eklenmez.

Bir kaynak silinince (`delete_source` uç noktası) o kaynağın okuyucuları en geç 30 sn içinde kapanır. Ek kod gerekmez: açıcı `SourceGone` döndürdüğü için yeni okuyucu açılmaz.

- [ ] **Adım 5: Geç.**
  - Çalıştır: `PYTHONIOENCODING=utf-8 .venv/Scripts/python -m pytest -q tests/test_viewer.py tests/test_views.py tests/test_live.py`, ardından `ruff check . ../../tools`.
  - Beklenen: PASS.

- [ ] **Adım 6: Commit**

```bash
git add services/edge/bantvision/live/viewer.py services/edge/bantvision/live/session.py services/edge/bantvision/live/api.py services/edge/bantvision/analyzer/app.py services/edge/tests/test_viewer.py
git commit -m "Çoklu izleme: kamera başına tek izleme okuyucusu (oturum karesi paylaşımı, sınırlar, boşta kapanma)"
```

---

### Görev 4: Birleştirici ve akış/durum uç noktaları

**Dosyalar:**
- Oluştur: `services/edge/bantvision/live/mosaic.py`, `services/edge/tests/test_mosaic.py`
- Değiştir: `services/edge/bantvision/live/api.py` (`LiveManager.mosaics`; uç noktalar: `/views/{id}/stream`, `/views/{id}/status`, `/cameras/stream`, `/cameras/status`), `services/edge/bantvision/analyzer/app.py` (kapanışta `mosaics.stop()`)

**Arayüzler:**
- Tüketir: `ViewHub.tile/peek` (Görev 3), `ViewStore.get` (Görev 2), `layout_by_id`, `cell_rects` (Görev 1).
- Üretir:
  - `fit_canvas(w, h) -> tuple[int, int]`.
  - `compose(layout, w, h, frames) -> np.ndarray`.
  - `Composer.jpeg(token, after, timeout) -> tuple[int, bytes | None]`.
  - `MosaicHub(views_get, hub, clock=time.monotonic)`:
    - `.acquire(view_id, w, h) -> tuple[Composer, int]`;
    - `.release(comp, token)`;
    - `.stop()`.
  - Sabitler: `FPS = 10.0`, `CANVAS_MAX = (1920, 1080)`, `SUB_TTL_S = 10.0`, `JPEG_QUALITY = 75`.
  - Durum yanıtı:

    ```
    {"id", "layout", "tiles": [null | {"name", "state", "message", "fps", "sourceId", "channelId", "analysis"}]}
    ```

    `analysis` alanı `null` ya da `{"mode", "sessionId", "name", "entered"?, "exited"?, "total"?, "healthy"?, "reason"?, "alarm"}`. `alarm` alanı da `null` ya da `{"id", "type"}`.

- [ ] **Adım 1: Başarısız testler** — `services/edge/tests/test_mosaic.py`:

```python
"""Birleştirici: kareler doğru hücreye oran korunarak; abonesiz durur; iki boyut aynı anda; şablon değişince hemen."""
from __future__ import annotations

import time
from typing import Any

import numpy as np
import pytest

from bantvision.live.layouts import cell_rects, layout_by_id
from bantvision.live.mosaic import SUB_TTL_S, MosaicHub, compose, fit_canvas
from bantvision.live.viewer import TileFrame


def test_fit_canvas_caps_to_1920x1080_and_multiples_of_16() -> None:
    assert fit_canvas(3840, 2160) == (1920, 1072)          # 1080 → 16'nın katı 1072
    assert fit_canvas(375, 600) == (368, 592)
    assert fit_canvas(10, 10) == (16, 16)


def test_compose_puts_each_frame_in_its_cell_letterboxed() -> None:
    lay = layout_by_id("4")
    assert lay is not None
    red = np.zeros((90, 160, 3), np.uint8)
    red[:, :, 2] = 255                                       # 16:9 kırmızı
    tall = np.zeros((160, 90, 3), np.uint8)
    tall[:, :, 1] = 255                                      # dikey yeşil: yanlarda siyah pay
    img = compose(lay, 640, 360, [red, None, tall, None])
    (x0, y0, x1, y1), (bx0, by0, bx1, by1), (cx0, cy0, cx1, cy1) = cell_rects(lay, 640, 360)[:3]
    assert tuple(img[(y0 + y1) // 2, (x0 + x1) // 2]) == (0, 0, 255)
    assert tuple(img[(by0 + by1) // 2, (bx0 + bx1) // 2]) == (40, 40, 40)            # boş kutu koyu gri
    assert tuple(img[(cy0 + cy1) // 2, (cx0 + cx1) // 2]) == (0, 255, 0)
    assert tuple(img[(cy0 + cy1) // 2, cx0 + 3]) == (0, 0, 0)                          # oran korundu: yan pay siyah


class FakeHub:
    def __init__(self) -> None:
        self.asked: list[tuple[str, str | None]] = []

    def tile(self, source_id: str, channel_id: str | None, quality: str = "sub") -> TileFrame:
        self.asked.append((source_id, channel_id))
        return TileFrame(1, np.full((90, 160, 3), 200, np.uint8), "live", "", 10.0)


def _views(view: dict[str, Any]) -> Any:
    return lambda vid: dict(view) if vid == view["id"] else None


def test_composer_streams_and_stops_without_subscribers() -> None:
    view = {"id": "v", "layout": "2", "tiles": [{"sourceId": "a", "channelId": None}, None]}
    hub = FakeHub()
    mh = MosaicHub(_views(view), hub)
    try:
        comp, tok = mh.acquire("v", 640, 360)
        seq, jpeg = comp.jpeg(tok, 0, timeout=3.0)
        assert jpeg is not None and jpeg[:2] == b"\xff\xd8" and seq >= 1
        assert ("a", None) in hub.asked
        mh.release(comp, tok)
        deadline = time.monotonic() + SUB_TTL_S + 6
        while comp.running() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not comp.running()                            # abonesiz: durdu, iş parçacığı sızmadı
    finally:
        mh.stop()


def test_same_view_two_sizes_and_template_edits_apply_live() -> None:
    view = {"id": "v", "layout": "1", "tiles": [{"sourceId": "a", "channelId": None}]}
    hub = FakeHub()
    mh = MosaicHub(_views(view), hub)
    try:
        c1, t1 = mh.acquire("v", 1280, 720)
        c2, t2 = mh.acquire("v", 368, 592)
        assert c1 is not c2
        c1.jpeg(t1, 0, 3.0)
        view["tiles"] = [{"sourceId": "b", "channelId": "4"}]   # şablon düzenlendi: yeniden bağlanmadan
        hub.asked.clear()
        time.sleep(0.4)
        assert ("b", "4") in hub.asked
    finally:
        mh.stop()


def test_deleted_view_ends_stream() -> None:
    hub = FakeHub()
    mh = MosaicHub(lambda vid: None, hub)
    with pytest.raises(LookupError):
        mh.acquire("yok", 640, 360)
    mh.stop()
```

`tests/test_live.py` sonuna (uç noktalar, dosya kaynağıyla; ağsız):

```python
def test_view_stream_and_status_with_file_sources(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANALYZER_ALLOW_FILE_SOURCES", "1")
    a = client.post("/api/v1/live/sources", json=camera(brand="custom", customUrl=str(CLIP), password="",
                                                        name="Kapı")).json()["id"]
    v = client.post("/api/v1/live/views", json={"name": "İki", "layout": "2",
                                                 "tiles": [{"sourceId": a, "channelId": None}, None]}).json()
    # `limit`: yalnızca test/teşhis — N kareden sonra akış biter (TestClient sonsuz akışı sonuna kadar bekler)
    r = client.get(f"/api/v1/live/views/{v['id']}/stream?w=640&h=360&limit=2")
    assert r.status_code == 200 and r.headers["content-type"].startswith("multipart/x-mixed-replace")
    assert r.content.count(b"Content-Type: image/jpeg") == 2 and b"\xff\xd8" in r.content
    st = wait_for(lambda: (x := client.get(f"/api/v1/live/views/{v['id']}/status").json())["tiles"][0]["state"] == "live"
                  and x)
    assert st["tiles"][0]["name"] == "Kapı" and st["tiles"][0]["analysis"] is None and st["tiles"][1] is None
    r = client.get(f"/api/v1/live/cameras/stream?source={a}&quality=sub&limit=1")
    assert r.status_code == 200 and r.content.count(b"Content-Type: image/jpeg") == 1
    assert client.get("/api/v1/live/views/yok/status").status_code == 404
    assert client.get("/api/v1/live/cameras/stream?source=yok").status_code == 404
    client.delete(f"/api/v1/live/sources/{a}")                       # kaynak silindi: şablon bozulmaz, kutu söyler
    t0 = client.get(f"/api/v1/live/views/{v['id']}/status").json()["tiles"][0]
    assert t0["state"] == "error" and t0["message"] == "Kamera silinmiş." and t0["name"] == "Silinmiş kamera"


def test_view_status_reports_running_analysis_and_unacked_alarm(client: TestClient,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    sess, sid = _safety_session_with_fake(client, monkeypatch)       # mevcut yardımcı (sahte tanıyıcı + poz)
    src_id = sess.source_id
    v = client.post("/api/v1/live/views", json={"name": "Kasa", "layout": "1",
                                                 "tiles": [{"sourceId": src_id, "channelId": None}]}).json()
    st = wait_for(lambda: (x := client.get(f"/api/v1/live/views/{v['id']}/status").json())["tiles"][0]["analysis"]
                  and x["tiles"][0]["analysis"].get("alarm") and x, timeout=30)
    a = st["tiles"][0]["analysis"]
    assert a["mode"] == "safety" and a["sessionId"] == sid and a["alarm"]["type"] == "hands_up"
    assert client.app.state.live.viewers.open_count("sub") == 0      # oturum karesi kullanıldı: ikinci bağlantı yok
```

`_safety_session_with_fake` yardımcısı `test_live.py`'de var. Adı ya da dönüşü farklıysa (ör. kaynak kimliği dönmüyorsa) uyarla; amaç değişmez.

Çalıştır: `PYTHONIOENCODING=utf-8 .venv/Scripts/python -m pytest -q tests/test_mosaic.py`. Beklenen: FAIL.

- [ ] **Adım 2: `services/edge/bantvision/live/mosaic.py`**

```python
"""Çoklu izleme birleştiricisi: şablonun kutularını tek JPEG'de birleştirip tek MJPEG akışı olarak verir.

Anahtar (şablon, genişlik, yükseklik). Yalnızca abonesi varken çalışır (saniyede en çok FPS). Abone her kare isteğinde
"görüldü" sayılır; SUB_TTL_S boyunca istemeyen abone gitmiş sayılır (tarayıcı kapandı, telefon uyudu). Şablon her
karede yeniden okunur: düzenleme bağlantı kopmadan yansır. Kamera adı/rozet/alarm tuvale çizilmez (panel HTML çizer).
"""
from __future__ import annotations

import itertools
import logging
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any

import cv2
import numpy as np

from .layouts import Layout, cell_rects, layout_by_id

_LOG = logging.getLogger(__name__)
FPS = 10.0
CANVAS_MAX = (1920, 1080)
SUB_TTL_S = 10.0
IDLE_STOP_S = 5.0
JPEG_QUALITY = 75
EMPTY = (40, 40, 40)                     # BGR koyu gri: boş ya da karesiz kutu
_TOKENS = itertools.count(1)


def fit_canvas(w: int, h: int) -> tuple[int, int]:
    """Tarayıcının istediği boyut: en çok 1920×1080'e sığdırılır, kenarlar 16'nın katı (en az 16)."""
    s = min(1.0, CANVAS_MAX[0] / max(1, w), CANVAS_MAX[1] / max(1, h))
    return max(16, int(w * s) // 16 * 16), max(16, int(h * s) // 16 * 16)


def compose(layout: Layout, w: int, h: int, frames: Sequence[np.ndarray | None]) -> np.ndarray:
    canvas = np.zeros((h, w, 3), np.uint8)
    for (x0, y0, x1, y1), f in zip(cell_rects(layout, w, h), frames, strict=False):
        x0, y0, x1, y1 = x0 + 1, y0 + 1, x1 - 1, y1 - 1           # kutular arası 2 px aralık
        cw, ch = x1 - x0, y1 - y0
        if cw <= 0 or ch <= 0:
            continue
        if f is None:
            canvas[y0:y1, x0:x1] = EMPTY
            continue
        if f.ndim == 2:
            f = cv2.cvtColor(f, cv2.COLOR_GRAY2BGR)
        fh, fw = f.shape[:2]
        s = min(cw / fw, ch / fh)
        nw, nh = max(1, int(fw * s)), max(1, int(fh * s))
        img = cv2.resize(f, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        ox, oy = x0 + (cw - nw) // 2, y0 + (ch - nh) // 2
        canvas[oy:oy + nh, ox:ox + nw] = img
    return canvas


class Composer:
    def __init__(self, view_id: str, w: int, h: int, views_get: Callable[[str], dict[str, Any] | None],
                 hub: Any, clock: Callable[[], float]) -> None:
        self.view_id, self.w, self.h = view_id, w, h
        self._views_get, self._hub, self._clock = views_get, hub, clock
        self._cv = threading.Condition(threading.Lock())
        self._seq = 0
        self._jpeg: bytes | None = None
        self._subs: dict[int, float] = {}
        self._gone = False                                   # şablon silindi: akış biter
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def ensure_running(self) -> None:
        if not self.running() and not self._stop.is_set():
            self._thread = threading.Thread(target=self._run, name=f"mozaik-{self.view_id[:8]}", daemon=True)
            self._thread.start()

    def subscribe(self) -> int:
        tok = next(_TOKENS)
        with self._cv:
            self._subs[tok] = self._clock()
        self.ensure_running()
        return tok

    def unsubscribe(self, tok: int) -> None:
        with self._cv:
            self._subs.pop(tok, None)

    def jpeg(self, tok: int, after: int, timeout: float) -> tuple[int, bytes | None]:
        end = time.monotonic() + timeout
        with self._cv:
            self._subs[tok] = self._clock()
            while self._seq <= after and not self._gone and not self._stop.is_set():
                left = end - time.monotonic()
                if left <= 0:
                    break
                self._cv.wait(left)
            return self._seq, (None if self._gone else self._jpeg)

    @property
    def gone(self) -> bool:
        return self._gone

    def stop(self) -> None:
        self._stop.set()
        with self._cv:
            self._cv.notify_all()
        if self._thread is not None:
            self._thread.join(2.0)

    def _alive(self) -> bool:
        now = self._clock()
        with self._cv:
            self._subs = {t: s for t, s in self._subs.items() if now - s <= SUB_TTL_S}
            return bool(self._subs)

    def _run(self) -> None:
        idle_since: float | None = None
        period = 1.0 / FPS
        while not self._stop.is_set():
            t0 = time.monotonic()
            if not self._alive():
                idle_since = idle_since or time.monotonic()
                if time.monotonic() - idle_since >= IDLE_STOP_S:
                    return                                   # abonesiz: dur (yeniden abone olunca başlar)
                self._stop.wait(0.2)
                continue
            idle_since = None
            view = self._views_get(self.view_id)
            lay = layout_by_id(str(view.get("layout"))) if view else None
            if view is None or lay is None:
                with self._cv:
                    self._gone = True
                    self._cv.notify_all()
                return
            try:
                frames: list[np.ndarray | None] = []
                for t in list(view.get("tiles", []))[:len(lay.cells)]:
                    frames.append(None if not t else self._hub.tile(t["sourceId"], t.get("channelId")).frame)
                ok, buf = cv2.imencode(".jpg", compose(lay, self.w, self.h, frames),
                                       [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            except Exception:  # noqa: BLE001 — bir karenin hatası akışı öldürmesin
                _LOG.exception("Mozaik karesi üretilemedi")
                ok = False
            if ok:
                with self._cv:
                    self._seq += 1
                    self._jpeg = buf.tobytes()
                    self._cv.notify_all()
            self._stop.wait(max(0.0, period - (time.monotonic() - t0)))


class MosaicHub:
    def __init__(self, views_get: Callable[[str], dict[str, Any] | None], hub: Any,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._views_get, self._hub, self._clock = views_get, hub, clock
        self._lock = threading.Lock()
        self._comps: dict[tuple[str, int, int], Composer] = {}

    def acquire(self, view_id: str, w: int, h: int) -> tuple[Composer, int]:
        if self._views_get(view_id) is None:
            raise LookupError("Şablon bulunamadı.")
        w, h = fit_canvas(w, h)
        with self._lock:
            key = (view_id, w, h)
            comp = self._comps.get(key)
            if comp is None or comp.gone:
                comp = Composer(view_id, w, h, self._views_get, self._hub, self._clock)
                self._comps[key] = comp
        return comp, comp.subscribe()

    def release(self, comp: Composer, tok: int) -> None:
        comp.unsubscribe(tok)

    def stop(self) -> None:
        with self._lock:
            comps = list(self._comps.values())
            self._comps.clear()
        for c in comps:
            c.stop()
```

- [ ] **Adım 3: `api.py`.**

`LiveManager.__init__` içinde `self.viewers`'dan sonra:

```python
        self.mosaics = MosaicHub(self.views.get, self.viewers)
```

İçe aktarma: `from .mosaic import MosaicHub`.

Yardımcı (dosya sonuna):

```python
def _analysis(manager: LiveManager, s: LiveSession) -> dict[str, Any]:
    """Kutudaki rozet: o kamerada çalışan analizin özeti (+ onaylanmamış güvenlik alarmı)."""
    v = s.snapshot_status()
    mode = s.profile.countMode
    a: dict[str, Any] = {"mode": mode, "sessionId": s.id, "name": s.profile.name}
    if mode == "detect":
        a.update(entered=v["total"], exited=v["totalOut"])
    elif mode == "safety":
        sf = v.get("safety") or {}
        a.update(healthy=sf.get("healthy"), reason=sf.get("reason"))
    else:
        a.update(total=v["total"])
    open_alarms = manager.alarms.list(active_only=True, session_id=s.id, limit=1)
    a["alarm"] = {"id": open_alarms[0]["id"], "type": open_alarms[0]["type"]} if open_alarms else None
    return a
```

Uç noktalar (şablon uçlarından sonra):

```python
    def _mjpeg(parts: Iterator[bytes]) -> StreamingResponse:
        return StreamingResponse(parts, media_type="multipart/x-mixed-replace; boundary=frame",
                                 headers={"Cache-Control": "no-store"})

    def _part(jpeg: bytes) -> bytes:
        return (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode()
                + b"\r\n\r\n" + jpeg + b"\r\n")

    @r.get("/views/{view_id}/stream")
    def view_stream(view_id: str, w: int = Query(1280, ge=16, le=7680), h: int = Query(720, ge=16, le=4320),
                    limit: int | None = Query(None, ge=1, le=100)) -> StreamingResponse:
        """`limit`: yalnızca test/teşhis — bu kadar kareden sonra akış biter (panel kullanmaz)."""
        try:
            comp, tok = manager.mosaics.acquire(view_id, w, h)
        except LookupError as e:
            raise HTTPException(404, "Şablon bulunamadı.") from e

        def frames() -> Iterator[bytes]:
            seq, idle, sent = 0, time.monotonic(), 0
            try:
                while limit is None or sent < limit:
                    seq2, jpeg = comp.jpeg(tok, seq, timeout=2.0)
                    if comp.gone:
                        return
                    if jpeg is None or seq2 == seq:
                        if time.monotonic() - idle > 60:
                            return
                        continue
                    idle, seq = time.monotonic(), seq2
                    sent += 1
                    yield _part(jpeg)
            finally:
                manager.mosaics.release(comp, tok)

        return _mjpeg(frames())

    @r.get("/views/{view_id}/status")
    def view_status(view_id: str) -> dict[str, Any]:
        view = manager.views.get(view_id)
        if view is None:
            raise HTTPException(404, "Şablon bulunamadı.")
        tiles: list[dict[str, Any] | None] = []
        for t in view["tiles"]:
            if not t:
                tiles.append(None)
                continue
            src_id, ch = t["sourceId"], t.get("channelId")
            gone = manager.store.source(src_id) is None
            tf = manager.viewers.peek(src_id, ch)
            s = manager._session_for(src_id, ch)
            tiles.append({"sourceId": src_id, "channelId": ch, "name": manager.camera_name(src_id, ch),
                          "state": "error" if gone else tf.state,
                          "message": "Kamera silinmiş." if gone else tf.message, "fps": tf.fps,
                          "analysis": _analysis(manager, s) if s is not None else None})
        return {"id": view["id"], "layout": view["layout"], "tiles": tiles}

    @r.get("/cameras/stream")
    def camera_stream(source: str = Query(pattern=_REF), channel: str | None = Query(None, pattern=_REF),
                      quality: Literal["sub", "main"] = "sub",
                      limit: int | None = Query(None, ge=1, le=100)) -> StreamingResponse:
        manager.source_or_404(source)

        def frames() -> Iterator[bytes]:
            last, idle, sent = -1, time.monotonic(), 0
            while limit is None or sent < limit:
                tf = manager.viewers.tile(source, channel, quality)
                if tf.frame is not None and tf.seq != last:
                    last, idle = tf.seq, time.monotonic()
                    ok, buf = cv2.imencode(".jpg", tf.frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    if ok:
                        sent += 1
                        yield _part(buf.tobytes())
                elif time.monotonic() - idle > 60:
                    return
                time.sleep(0.08)

        return _mjpeg(frames())

    @r.get("/cameras/status")
    def camera_status(source: str = Query(pattern=_REF), channel: str | None = Query(None, pattern=_REF),
                      quality: Literal["sub", "main"] = "sub") -> dict[str, Any]:
        manager.source_or_404(source)
        tf = manager.viewers.peek(source, channel, quality)
        s = manager._session_for(source, channel)
        return {"name": manager.camera_name(source, channel), "state": tf.state, "message": tf.message,
                "fps": tf.fps, "analysis": _analysis(manager, s) if s is not None else None}
```

`analyzer/app.py` kapanışında `live.viewers.stop()`'tan önce:

```python
        live.mosaics.stop()
```

- [ ] **Adım 4: Geç.**
  - Çalıştır: `PYTHONIOENCODING=utf-8 .venv/Scripts/python -m pytest -q tests/test_mosaic.py tests/test_viewer.py tests/test_views.py tests/test_live.py`, ardından `ruff check . ../../tools`.
  - Beklenen: PASS.

- [ ] **Adım 5: Commit**

```bash
git add services/edge/bantvision/live/mosaic.py services/edge/bantvision/live/api.py services/edge/bantvision/analyzer/app.py services/edge/tests/test_mosaic.py services/edge/tests/test_live.py
git commit -m "Çoklu izleme: birleşik MJPEG akışı, kutu durumu ve tek kamera akışı"
```

---

### Görev 5: Panel — İzleme sayfası (izleme kipi)

**Dosyalar:**
- Oluştur:
  - `apps/dashboard/src/lib/views.ts`;
  - `apps/dashboard/src/app/(panel)/watch/page.tsx`;
  - `apps/dashboard/src/components/watch/WatchView.tsx`;
  - `apps/dashboard/src/components/watch/TileOverlay.tsx`;
  - `apps/dashboard/src/components/watch/SingleCamera.tsx`;
  - `apps/dashboard/e2e/watch-ui.spec.ts` (sahte veri);
  - `apps/dashboard/e2e/watch.spec.ts` (gerçek yığın).
- Değiştir: `apps/dashboard/src/components/Sidebar.tsx` ("İzleme" girişi, "Kameralar"dan sonra).

**Arayüzler:**
- Tüketir: Görev 2 ve 4'teki uç noktalar (`/api/live/view-layouts`, `views`, `views/{id}/stream`, `views/{id}/status`, `cameras/stream`, `cameras/status`); `useAlarmCenter()` (`open(id)`), `api()`.
- Üretir (`lib/views.ts`):
  - tipler: `ViewLayout`, `TileRef`, `ViewTemplate`, `TileAnalysis`, `TileStatus`, `ViewStatus`;
  - `cellBox(layout, i): { left: string; top: string; width: string; height: string }`;
  - `streamSize(el: HTMLElement): { w: number; h: number }`;
  - `badge(a: TileAnalysis): { text: string; tone: "ok" | "warn" | "info" }`;
  - sabitler: `LAST_VIEW_KEY = "bv.watch.last"`, `STATUS_POLL_MS = 1500`, `STREAM_RETRY_MS = 2000`.
- Bileşenler:
  - `<WatchView />`: Görev 6 düzenleme kipini buraya ekleyecek. `onEdit` düğmesi bu görevde yalnızca görünür; düzenleme Görev 6'da.

- [ ] **Adım 1: e2e (sahte veri)** — `apps/dashboard/e2e/watch-ui.spec.ts`:

```ts
import { expect, test, type Page } from "@playwright/test";

const LAYOUTS = [
  { id: "1", name: "Tek", cols: 1, rows: 1, cells: [[0, 0, 1, 1]] },
  { id: "4", name: "4'lü", cols: 2, rows: 2, cells: [[0, 0, 1, 1], [1, 0, 1, 1], [0, 1, 1, 1], [1, 1, 1, 1]] },
];
const VIEW = { id: "v1", name: "Giriş katı", layout: "4", createdAt: 1, updatedAt: 1,
  tiles: [{ sourceId: "a", channelId: null }, { sourceId: "b", channelId: "2" }, { sourceId: "c", channelId: null }, null] };
// 1×1 siyah JPEG (akış yerine; tek parça yeterli)
const JPEG = Buffer.from("/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==", "base64");

async function mock(page: Page, status: object) {
  await page.route("**/api/live/view-layouts", (r) => r.fulfill({ json: LAYOUTS }));
  await page.route("**/api/live/views", (r) => r.fulfill({ json: [VIEW] }));
  await page.route("**/api/live/views/v1/status", (r) => r.fulfill({ json: status }));
  await page.route("**/api/live/views/v1/stream**", (r) => r.fulfill({ body: JPEG, contentType: "image/jpeg" }));
  await page.route("**/api/live/cameras/**", (r) => r.fulfill({ body: JPEG, contentType: "image/jpeg" }));
  await page.route("**/api/live/alarms?active=1", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/live/sessions", (r) => r.fulfill({ json: [] }));
}

const STATUS = { id: "v1", layout: "4", tiles: [
  { sourceId: "a", channelId: null, name: "Kapı", state: "live", message: "", fps: 10,
    analysis: { mode: "detect", sessionId: "s1", name: "Mağaza girişi", entered: 12, exited: 9, alarm: null } },
  { sourceId: "b", channelId: "2", name: "Ofis NVR · Kasa", state: "live", message: "", fps: 10,
    analysis: { mode: "safety", sessionId: "s2", name: "Kuyumcu güvenliği", healthy: true, reason: null,
                alarm: { id: "al1", type: "hands_up" } } },
  { sourceId: "c", channelId: null, name: "Arka kapı", state: "error", message: "Görüntü açılamadı; yeniden deneniyor.",
    fps: 0, analysis: null },
  null,
] };

async function login(page: Page) {
  await page.goto("/watch");
  await page.getByLabel("Şifre").fill("e2e-test-sifresi");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("heading", { name: "İzleme" })).toBeVisible();
}

test("izleme: şablon ızgarası, adlar, rozetler, hata ve alarm çerçevesi", async ({ page }) => {
  await mock(page, STATUS);
  await login(page);
  await expect(page.getByRole("combobox", { name: "Şablon" })).toHaveValue("v1");
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles).toHaveCount(4);
  await expect(tiles.nth(0)).toContainText("Kapı");
  await expect(tiles.nth(0)).toContainText("G 12 · Ç 9");
  await expect(tiles.nth(1)).toContainText("ELLER YUKARI");
  await expect(tiles.nth(1)).toHaveAttribute("data-alarm", "true");
  await expect(tiles.nth(2)).toContainText("Görüntü açılamadı");
  await expect(tiles.nth(3)).toHaveAttribute("data-empty", "true");
  await expect(page.getByAltText("Giriş katı canlı görüntü")).toBeVisible();
});

test("izleme: çift tıkla tek kamera, Esc ile geri; telefon görünümü", async ({ page }) => {
  await mock(page, STATUS);
  await login(page);
  await page.getByTestId("watch-tile").nth(0).dblclick();
  await expect(page.getByRole("heading", { name: "Kapı" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Net görüntü" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("watch-tile")).toHaveCount(4);
  await page.setViewportSize({ width: 375, height: 740 });
  await expect(page.getByTestId("watch-grid")).toBeVisible();
  const box = await page.getByTestId("watch-grid").boundingBox();
  expect(box!.width).toBeLessThanOrEqual(375);
});
```

```ts
test("izleme: alarmlı kutuya tıklayınca alarm penceresi açılır", async ({ page }) => {
  await mock(page, STATUS);
  const ALARM = { id: "al1", sessionId: "s2", camera: "Ofis NVR · Kasa", type: "hands_up", startedAt: 100, firedAt: 103,
    endedAt: null, acked: false, falseAlarm: false, notify: "disabled", image: false, clip: false, clipPending: false,
    clipFailed: false, clipStartedAt: null };
  await page.route("**/api/live/alarms?active=1", (r) => r.fulfill({ json: [ALARM] }));
  await login(page);
  const dlg = page.getByRole("alertdialog", { name: "Güvenlik alarmı" });
  if (await dlg.isVisible()) await dlg.getByRole("button", { name: "Küçült" }).click();   // yeni alarm penceresi kendiliğinden açıldıysa küçült
  await page.getByTestId("watch-tile").nth(1).click();
  await expect(page.getByRole("alertdialog", { name: "Güvenlik alarmı" })).toBeVisible();
});
```

`ALARM` alanları `lib/live.ts`'deki `Alarm` tipiyle birebir olmalı. Tipte fazla ya da eksik alan varsa ona göre düzelt.

- [ ] **Adım 2: `apps/dashboard/src/lib/views.ts`**

```ts
/** Çoklu izleme (analiz sunucusu `/api/v1/live/views…`; sözleşme contracts/view-layouts.json, view-template.schema.json) */
import type { AlarmType } from "./live";

export interface ViewLayout { id: string; name: string; cols: number; rows: number; cells: Array<[number, number, number, number]> }
export interface TileRef { sourceId: string; channelId: string | null }
export interface ViewTemplate { id: string; name: string; layout: string; tiles: Array<TileRef | null>; createdAt: number; updatedAt: number }
export interface TileAnalysis {
  mode: "blob" | "linescan" | "detect" | "safety";
  sessionId: string;
  name: string;
  entered?: number; exited?: number; total?: number;
  healthy?: boolean | null; reason?: string | null;
  alarm: { id: string; type: AlarmType } | null;
}
export interface TileStatus { sourceId: string; channelId: string | null; name: string; state: "connecting" | "live" | "error"; message: string; fps: number; analysis: TileAnalysis | null }
export interface ViewStatus { id: string; layout: string; tiles: Array<TileStatus | null> }

export const LAST_VIEW_KEY = "bv.watch.last";
export const STATUS_POLL_MS = 1500;
export const STREAM_RETRY_MS = 2000;

/** Kutunun ızgaradaki yeri (yüzde): birleşik görüntü aynı oranlarla çizilir */
export function cellBox(l: ViewLayout, i: number): { left: string; top: string; width: string; height: string } {
  const [x, y, w, h] = l.cells[i];
  const pct = (v: number) => `${v * 100}%`;
  return { left: pct(x / l.cols), top: pct(y / l.rows), width: pct(w / l.cols), height: pct(h / l.rows) };
}

/** İstenecek birleşik görüntü boyutu: kapsayıcının gerçek pikselleri (en çok 2× yoğunluk; sunucu 1920×1080'e sığdırır) */
export function streamSize(el: HTMLElement): { w: number; h: number } {
  const r = el.getBoundingClientRect();
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const round = (v: number) => Math.max(16, Math.round((v * dpr) / 16) * 16);
  return { w: round(r.width), h: round(r.height) };
}

export function badge(a: TileAnalysis): { text: string; tone: "ok" | "warn" | "info" } {
  if (a.mode === "safety") return a.healthy === false ? { text: "Uyarı", tone: "warn" } : { text: "Nöbette", tone: "ok" };
  if (a.mode === "detect") return { text: `G ${a.entered ?? 0} · Ç ${a.exited ?? 0}`, tone: "info" };
  return { text: `Sayılan ${a.total ?? 0}`, tone: "info" };
}

/** Düzen değişince kutular sırasıyla korunur; sığmayanlar düşer (kaç kamera düştüğü uyarı için döner) */
export function retile(tiles: Array<TileRef | null>, count: number): { tiles: Array<TileRef | null>; dropped: number } {
  const next = tiles.slice(0, count);
  while (next.length < count) next.push(null);
  return { tiles: next, dropped: tiles.slice(count).filter(Boolean).length };
}
```

- [ ] **Adım 3: `TileOverlay.tsx`**

```tsx
"use client";

import { ALARM_TITLES } from "@/lib/live";
import { badge, cellBox, type TileStatus, type ViewLayout } from "@/lib/views";

const TONE = { ok: "bg-ok-600 text-white", warn: "bg-warn-500 text-white", info: "bg-black/60 text-white" } as const;

/** Birleşik görüntünün üstünde tek kutunun HTML katmanı: ad, durum, rozet, alarm çerçevesi */
export default function TileOverlay({ layout, index, tile, onOpen, onAlarm }: {
  layout: ViewLayout; index: number; tile: TileStatus | null;
  onOpen: () => void; onAlarm: (alarmId: string) => void;
}) {
  const alarm = tile?.analysis?.alarm ?? null;
  return (
    <div data-testid="watch-tile" data-empty={tile ? undefined : "true"} data-alarm={alarm ? "true" : undefined}
         style={cellBox(layout, index)}
         className={`absolute p-1 ${alarm ? "animate-pulse" : ""}`}
         onDoubleClick={() => tile && onOpen()}
         onClick={() => (alarm ? onAlarm(alarm.id) : undefined)}
         role={tile ? "button" : undefined} tabIndex={tile ? 0 : -1}
         aria-label={tile ? `${tile.name}: büyütmek için çift tıklayın` : "Boş kutu"}
         onKeyDown={(e) => { if (tile && e.key === "Enter") onOpen(); }}>
      <div className={`relative h-full w-full rounded-[6px] ${alarm ? "ring-4 ring-nok-600" : ""}`}>
        {tile && (
          <span className="absolute left-1.5 top-1.5 max-w-[70%] truncate rounded-md bg-black/55 px-1.5 py-0.5 text-[11px] font-medium text-white">
            {tile.name}
          </span>
        )}
        {tile?.analysis && (
          <span className={`absolute right-1.5 top-1.5 rounded-md px-1.5 py-0.5 text-[11px] font-semibold ${TONE[badge(tile.analysis).tone]}`}
                title={tile.analysis.reason ?? tile.analysis.name}>
            {badge(tile.analysis).text}
          </span>
        )}
        {alarm && (
          <span className="absolute inset-x-0 bottom-2 mx-auto w-max rounded-md bg-nok-600 px-2 py-1 text-[12px] font-bold text-white">
            {ALARM_TITLES[alarm.type]}
          </span>
        )}
        {tile && tile.state !== "live" && (
          <span className="absolute inset-0 grid place-items-center p-2 text-center text-[12px] text-white/90">
            {tile.state === "connecting" ? "Bağlanıyor…" : tile.message || "Bağlantı yok"}
          </span>
        )}
        {tile && (
          // Üstüne gelince (telefonda dokununca odakla) küçük düğmeler: büyüt, canlı sayıma git
          <span className="absolute bottom-1.5 right-1.5 hidden gap-1 group-hover:flex group-focus-within:flex">
            <button type="button" onClick={(e) => { e.stopPropagation(); onOpen(); }}
                    className="rounded-md bg-black/60 px-1.5 py-0.5 text-[11px] text-white">Tam ekran</button>
            <a href={tile.analysis ? `/live?s=${tile.analysis.sessionId}` : "/cameras"} onClick={(e) => e.stopPropagation()}
               className="rounded-md bg-black/60 px-1.5 py-0.5 text-[11px] text-white">Canlı sayıma git</a>
          </span>
        )}
      </div>
    </div>
  );
}
```

Dış `div`'in `className`'ine `group` ekle: `` className={`group absolute p-1 …`} ``. "Canlı sayıma git" bağlantısı:
- analiz çalışıyorsa o oturuma gider (`/live?s=…`; Canlı sayım sayfası `s` parametresini zaten okur);
- çalışmıyorsa Kameralar sayfasına gider. Orada kameranın "Canlı sayım" düğmesi başlatma penceresini açar.

`warn-500` ve `nok-600` renkleri Tailwind yapılandırmasında yoksa var olan en yakın sınıfları kullan. Projede `nok-600`, `ok-600`, `warn-50/700` kullanılıyor; `globals.css` ya da `tailwind.config` dosyasına bak.

- [ ] **Adım 4: `SingleCamera.tsx`**

```tsx
"use client";

import { useEffect, useState } from "react";
import { STREAM_RETRY_MS } from "@/lib/views";

/** Tek kamera (çift tık): ham akış; "Net görüntü" ana akışa geçer. Esc/Geri ile ızgaraya dönülür. */
export default function SingleCamera({ sourceId, channelId, name, onClose }: {
  sourceId: string; channelId: string | null; name: string; onClose: () => void;
}) {
  const [quality, setQuality] = useState<"sub" | "main">("sub");
  const [key, setKey] = useState(0);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const q = new URLSearchParams({ source: sourceId, quality, k: String(key) });
  if (channelId) q.set("channel", channelId);
  return (
    <section className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={onClose} className="h-9 rounded-[10px] border border-line px-3 text-sm">← Izgaraya dön</button>
        <h2 className="min-w-0 flex-1 truncate text-lg font-semibold">{name}</h2>
        <button type="button" aria-pressed={quality === "main"} onClick={() => setQuality(quality === "sub" ? "main" : "sub")}
                className="h-9 rounded-[10px] border border-line px-3 text-sm">{quality === "sub" ? "Net görüntü" : "Hızlı görüntü"}</button>
      </div>
      {/* eslint-disable-next-line @next/next/no-img-element -- canlı MJPEG akışı */}
      <img alt={`${name} canlı görüntü`} src={`/api/live/cameras/stream?${q}`} className="w-full rounded-2xl bg-black object-contain"
           onError={() => setTimeout(() => setKey((k) => k + 1), STREAM_RETRY_MS)} />
    </section>
  );
}
```

- [ ] **Adım 5: `WatchView.tsx`**

```tsx
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/live";
import { useAlarmCenter } from "@/components/live/AlarmCenter";
import { LAST_VIEW_KEY, STATUS_POLL_MS, STREAM_RETRY_MS, streamSize, type ViewLayout, type ViewStatus, type ViewTemplate } from "@/lib/views";
import TileOverlay from "./TileOverlay";
import SingleCamera from "./SingleCamera";

function remembered(): string | null {
  try { return window.localStorage.getItem(LAST_VIEW_KEY); } catch { return null; }
}
function remember(id: string): void {
  try { window.localStorage.setItem(LAST_VIEW_KEY, id); } catch { /* depolama yok */ }
}

/** İzleme sayfası: şablon seçici, birleşik canlı görüntü + kutu katmanları, tek kamera, tüm ekran (video duvarı) */
export default function WatchView() {
  const [layouts, setLayouts] = useState<ViewLayout[]>([]);
  const [views, setViews] = useState<ViewTemplate[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [status, setStatus] = useState<ViewStatus | null>(null);
  const [single, setSingle] = useState<{ sourceId: string; channelId: string | null; name: string } | null>(null);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [streamKey, setStreamKey] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const wallRef = useRef<HTMLDivElement>(null);
  const center = useAlarmCenter();

  const reload = useCallback(async (select?: string) => {
    const [l, v] = await Promise.all([api<ViewLayout[]>("view-layouts"), api<ViewTemplate[]>("views")]);
    setLayouts(l);
    setViews(v);
    const want = select ?? remembered();
    setCurrentId((cur) => (want && v.some((x) => x.id === want) ? want : cur && v.some((x) => x.id === cur) ? cur : v[0]?.id ?? null));
  }, []);
  useEffect(() => { reload().catch((e: Error) => setError(e.message)); }, [reload]);

  const view = views.find((v) => v.id === currentId) ?? null;
  const layout = view ? layouts.find((l) => l.id === view.layout) ?? null : null;
  useEffect(() => { if (currentId) remember(currentId); }, [currentId]);

  // Kapsayıcı boyutu: birleşik görüntü tam bu boyutta istenir (telefonda küçük, masaüstünde büyük)
  useEffect(() => {
    const el = gridRef.current;
    if (!el || !layout) return;
    const update = () => setSize(streamSize(el));
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [layout, single]);

  // Kutu durumları
  useEffect(() => {
    if (!currentId || single) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const s = await api<ViewStatus>(`views/${currentId}/status`);
        if (alive) setStatus(s);
      } catch { /* sunucu yoksa şerit zaten uyarır */ }
      if (alive) timer = setTimeout(poll, STATUS_POLL_MS);
    };
    poll();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [currentId, single]);

  const wall = async () => {
    try { await wallRef.current?.requestFullscreen(); } catch { /* tarayıcı izin vermedi */ }
  };

  if (single) return <SingleCamera {...single} onClose={() => setSingle(null)} />;
  const aspect = layout ? `${layout.cols * 16} / ${layout.rows * 9}` : "16 / 9";
  const src = view && size ? `/api/live/views/${view.id}/stream?w=${size.w}&h=${size.h}&k=${streamKey}` : null;

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-2 text-2xl font-semibold">İzleme</h1>
        <select aria-label="Şablon" value={currentId ?? ""} onChange={(e) => setCurrentId(e.target.value || null)}
                className="h-10 min-w-0 flex-1 rounded-[10px] border border-line bg-white px-3 text-sm sm:max-w-[320px]">
          {views.length === 0 && <option value="">Henüz şablon yok</option>}
          {views.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
        </select>
        <button type="button" onClick={wall} disabled={!view} className="h-10 rounded-[10px] border border-line px-3 text-sm">Tüm ekran</button>
        {/* Görev 6: "Yeni şablon", "Düzenle", "Tüm kanallardan şablon" düğmeleri buraya */}
      </div>
      {error && <p role="alert" className="rounded-xl bg-nok-50 px-3 py-2 text-sm text-nok-600">{error}</p>}
      {view && layout ? (
        <div ref={wallRef} className="bg-black">
          <div ref={gridRef} data-testid="watch-grid" className="relative w-full overflow-hidden rounded-2xl bg-black" style={{ aspectRatio: aspect }}>
            {src && (
              // eslint-disable-next-line @next/next/no-img-element -- canlı MJPEG akışı
              <img alt={`${view.name} canlı görüntü`} src={src} className="absolute inset-0 h-full w-full"
                   onError={() => setTimeout(() => setStreamKey((k) => k + 1), STREAM_RETRY_MS)} />
            )}
            {layout.cells.map((_, i) => (
              <TileOverlay key={i} layout={layout} index={i} tile={status?.id === view.id ? status.tiles[i] ?? null : null}
                           onOpen={() => {
                             const t = view.tiles[i];
                             const st = status?.tiles[i];
                             if (t) setSingle({ sourceId: t.sourceId, channelId: t.channelId, name: st?.name ?? "Kamera" });
                           }}
                           onAlarm={(id) => center?.open(id)} />
            ))}
          </div>
        </div>
      ) : (
        <p className="card p-6 text-sm text-muted">Henüz şablon yok. "Yeni şablon" ile kameraları bir düzene yerleştirin.</p>
      )}
    </div>
  );
}
```

`page.tsx`:

```tsx
import type { Metadata } from "next";
import WatchView from "@/components/watch/WatchView";

export const metadata: Metadata = { title: "İzleme" };

export default function WatchPage() {
  return <div className="mx-auto max-w-[1600px]"><WatchView /></div>;
}
```

`Sidebar.tsx` `NAV`'da "Kameralar"dan sonra:

```ts
  { href: "/watch", label: "İzleme", icon: icon("M3 3h8v8H3zM13 3h8v8h-8zM3 13h8v8H3zM13 13h8v8h-8z") },
```

`useAlarmCenter().open(id)` alarm penceresini açar ve mevcuttur. Alarm o an listede yoksa (onaylanmışsa) bir şey olmaz.

- [ ] **Adım 6: Gerçek yığın e2e** — `apps/dashboard/e2e/watch.spec.ts`. `live.spec.ts`'deki `login` ve klip deseni kullanılır:

```ts
import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

const CLIP = path.resolve(__dirname, "../../ios/BantSayacUITests/ui_test_clip.mp4");

async function login(page: Page) {
  await page.goto("/cameras");
  await page.getByLabel("Şifre").fill("e2e-test-sifresi");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("heading", { name: "Kameralar ve kayıt cihazları" })).toBeVisible();
}

test("izleme (gerçek yığın): API ile şablon, birleşik akış gelir, tek kamera akışı gelir", async ({ page }) => {
  await login(page);
  const src = await (await page.request.post("/api/live/sources", { data: {
    kind: "camera", brand: "custom", customUrl: CLIP, name: "İzleme klibi" } })).json();
  const view = await (await page.request.post("/api/live/views", { data: {
    name: "E2E izleme", layout: "2", tiles: [{ sourceId: src.id, channelId: null }, null] } })).json();
  await page.goto("/watch");
  await page.getByRole("combobox", { name: "Şablon" }).selectOption(view.id);
  await expect.poll(async () => page.getByAltText("E2E izleme canlı görüntü")
    .evaluate((img: HTMLImageElement) => img.naturalWidth), { timeout: 30_000 }).toBeGreaterThan(0);
  await expect(page.getByTestId("watch-tile").first()).toContainText("İzleme klibi");
  await page.getByTestId("watch-tile").first().dblclick();
  await expect.poll(async () => page.getByAltText("İzleme klibi canlı görüntü")
    .evaluate((img: HTMLImageElement) => img.naturalWidth), { timeout: 30_000 }).toBeGreaterThan(0);
  await page.request.delete(`/api/live/views/${view.id}`);
  await page.request.delete(`/api/live/sources/${src.id}`);
});
```

- [ ] **Adım 7: Doğrula.** `apps/dashboard` içinde çalıştır:
  - `npx eslint src e2e && npx tsc --noEmit && npm run build`
  - `PYTHON=<venv python> PYTHONIOENCODING=utf-8 npx playwright test` (TAM takım)

  Beklenen: PASS.

- [ ] **Adım 8: Commit**

```bash
git add apps/dashboard
git commit -m "Panel: İzleme sayfası (şablonlu canlı ızgara, kutu bilgileri, tek kamera, tüm ekran)"
```

---

### Görev 6: Panel — şablon düzenleme

**Dosyalar:**
- Oluştur:
  - `apps/dashboard/src/components/live/Thumb.tsx`: `CamerasView`'daki `Thumb` ve `thumbSlot` buraya taşınır, iki yer de buradan kullanır.
  - `apps/dashboard/src/components/watch/ViewEditor.tsx`
  - `apps/dashboard/src/components/watch/CameraList.tsx`
- Değiştir: `apps/dashboard/src/components/live/CamerasView.tsx` (Thumb içe aktarılır), `apps/dashboard/src/components/watch/WatchView.tsx` (düğmeler ve düzenleme kipi), `apps/dashboard/e2e/watch-ui.spec.ts`, `apps/dashboard/e2e/watch.spec.ts`

**Arayüzler:**
- Tüketir:
  - `retile`, `ViewTemplate`, `ViewLayout`, `TileRef` (Görev 5);
  - uç noktalar: `POST/PUT/DELETE views`, `POST views/from-recorder`, `GET sources`, `GET sources/{id}/channels`;
  - `Source`, `Channel` (`lib/live.ts`).
- Üretir:
  - `<ViewEditor initial={ViewTemplate | null} layouts onSaved(view) onCancel onDeleted />`;
  - `<CameraList onPick(ref: TileRef, name: string) used={Set<string>} />`. Anahtar biçimi `${sourceId}|${channelId ?? ""}`.

- [ ] **Adım 1: e2e (sahte veri)** — `watch-ui.spec.ts`'ye ekle:

```ts
test("izleme: yeni şablon — düzen seç, kamera ata (tıkla + listeden), sürükleyerek yer değiştir, kaydet", async ({ page }) => {
  let saved: unknown = null;
  await mock(page, STATUS);
  await page.route("**/api/live/sources", (r) => r.fulfill({ json: [
    { id: "a", kind: "camera", name: "Kapı", brand: "custom", hasPassword: false },
    { id: "nvr", kind: "recorder", name: "Ofis NVR", recorderBrand: "hikvision", hasPassword: true },
  ] }));
  await page.route("**/api/live/sources/nvr/channels", (r) => r.fulfill({ json: [
    { id: "1", name: "Giriş", number: 1, title: "Giriş", hasSubstream: true },
    { id: "2", name: "Kasa", number: 2, title: "Kasa", hasSubstream: true },
  ] }));
  await page.route("**/api/live/sources/*/snapshot**", (r) => r.fulfill({ body: JPEG, contentType: "image/jpeg" }));
  await page.route("**/api/live/views", async (r) => {
    if (r.request().method() === "POST") {
      saved = r.request().postDataJSON();
      return r.fulfill({ json: { id: "v2", createdAt: 2, updatedAt: 2, ...(saved as object) } });
    }
    return r.fulfill({ json: [VIEW] });
  });
  await login(page);
  await page.getByRole("button", { name: "Yeni şablon" }).click();
  const ed = page.getByRole("region", { name: "Şablon düzenleyici" });
  await ed.getByLabel("Şablon adı").fill("Kasa ve giriş");
  await ed.getByRole("button", { name: "2'li (yan yana)" }).click();
  await ed.getByTestId("edit-tile").nth(0).click();                           // kutuyu seç
  await ed.getByRole("button", { name: "Kapı" }).click();                       // listeden kamera
  await ed.getByRole("button", { name: /Ofis NVR/ }).click();                   // kayıt cihazını aç
  await ed.getByTestId("edit-tile").nth(1).click();
  await ed.getByRole("button", { name: "Kasa" }).click();
  await ed.getByTestId("edit-tile").nth(0).dragTo(ed.getByTestId("edit-tile").nth(1));   // yer değiştir
  await ed.getByRole("button", { name: "Kaydet" }).click();
  expect(saved).toEqual({ name: "Kasa ve giriş", layout: "2",
    tiles: [{ sourceId: "nvr", channelId: "2" }, { sourceId: "a", channelId: null }] });
});

test("izleme: düzen küçülünce sığmayan kameralar uyarılır; aynı kamera iki kutuya konmaz", async ({ page }) => {
  await mock(page, STATUS);
  await page.route("**/api/live/sources", (r) => r.fulfill({ json: [
    { id: "a", kind: "camera", name: "Kapı", brand: "custom", hasPassword: false }] }));
  await page.route("**/api/live/sources/*/snapshot**", (r) => r.fulfill({ body: JPEG, contentType: "image/jpeg" }));
  await login(page);
  await page.getByRole("button", { name: "Düzenle" }).click();
  const ed = page.getByRole("region", { name: "Şablon düzenleyici" });
  await ed.getByRole("button", { name: "Tek" }).click();
  await expect(ed.getByRole("status")).toContainText("2 kamera düzene sığmadı");
  await ed.getByTestId("edit-tile").nth(0).click();
  await expect(ed.getByRole("button", { name: "Kapı" })).toBeDisabled();            // zaten şablonda
});
```

> Not: İkinci testte `VIEW`'in ilk kutusu `a` (Kapı). 4'lü düzenden "Tek"e geçilince `b` ve `c` düşer: "2 kamera düzene sığmadı". Kapı zaten kullanıldığı için listede pasif görünür.

- [ ] **Adım 2: `Thumb.tsx`.** `CamerasView.tsx`'teki `thumbSlot`, `MAX_THUMBS` ve `Thumb`'ı (satır ~38-84) aynen bu dosyaya taşı ve `export default Thumb` yap. `CamerasView` bunu içe aktarır. Davranış değişmez; mevcut e2e'ler doğrular.

- [ ] **Adım 3: `CameraList.tsx`**

```tsx
"use client";

import { useEffect, useState } from "react";
import { api, type Channel, type Source } from "@/lib/live";
import type { TileRef } from "@/lib/views";
import Thumb from "@/components/live/Thumb";

export const refKey = (r: TileRef) => `${r.sourceId}|${r.channelId ?? ""}`;

/** Düzenleyicinin kamera listesi: tek kameralar ve kayıt cihazlarının kanalları (aç/kapa), küçük resim ve adla.
 * Şablonda zaten olan kamera pasif. Öğe sürüklenebilir (kutuya bırakılır) ya da tıklanır (seçili kutuya gider). */
export default function CameraList({ used, onPick }: { used: Set<string>; onPick: (ref: TileRef, name: string) => void }) {
  const [sources, setSources] = useState<Source[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [channels, setChannels] = useState<Record<string, Channel[] | string>>({});
  useEffect(() => { api<Source[]>("sources").then(setSources).catch(() => undefined); }, []);
  const toggle = async (s: Source) => {
    setOpen(open === s.id ? null : s.id);
    if (channels[s.id]) return;
    try { const c = await api<Channel[]>(`sources/${s.id}/channels`); setChannels((x) => ({ ...x, [s.id]: c })); }
    catch (e) { setChannels((x) => ({ ...x, [s.id]: (e as Error).message })); }
  };
  const item = (ref: TileRef, name: string, thumb: string) => (
    <li key={refKey(ref)}>
      <button type="button" draggable disabled={used.has(refKey(ref))}
              onDragStart={(e) => e.dataTransfer.setData("application/x-bv-camera", JSON.stringify({ ref, name }))}
              onClick={() => onPick(ref, name)}
              className="flex w-full items-center gap-2 rounded-xl border border-line p-1.5 text-left text-[13px] hover:border-brand-100 disabled:opacity-40">
        <span className="w-20 shrink-0"><Thumb src={thumb} alt="" /></span>
        <span className="min-w-0 truncate">{name}</span>
      </button>
    </li>
  );
  return (
    <aside aria-label="Kameralar" className="grid content-start gap-2">
      {sources.length === 0 && <p className="text-[13px] text-faint">Henüz kaynak yok. Kameralar sayfasından ekleyin.</p>}
      <ul className="grid gap-1.5">
        {sources.map((s) => s.kind === "camera"
          ? item({ sourceId: s.id, channelId: null }, s.name, `/api/live/sources/${s.id}/snapshot`)
          : (
            <li key={s.id}>
              <button type="button" aria-expanded={open === s.id} onClick={() => toggle(s)}
                      className="w-full rounded-xl bg-canvas px-2 py-1.5 text-left text-[13px] font-medium">{s.name} {open === s.id ? "▾" : "▸"}</button>
              {open === s.id && (typeof channels[s.id] === "string"
                ? <p className="px-2 py-1 text-[12px] text-nok-600">{channels[s.id] as string}</p>
                : <ul className="mt-1.5 grid gap-1.5 pl-2">{((channels[s.id] as Channel[] | undefined) ?? []).map((c) =>
                    item({ sourceId: s.id, channelId: c.id }, c.title,
                         `/api/live/sources/${s.id}/snapshot?channel=${encodeURIComponent(c.id)}`))}</ul>)}
            </li>
          ))}
      </ul>
    </aside>
  );
}
```

- [ ] **Adım 4: `ViewEditor.tsx`**

```tsx
"use client";

import { useMemo, useState } from "react";
import { api } from "@/lib/live";
import { cellBox, retile, type TileRef, type ViewLayout, type ViewTemplate } from "@/lib/views";
import CameraList, { refKey } from "./CameraList";

/** Şablon düzenleyici: ad, düzen, kutulara kamera (tıkla-seç ya da sürükle-bırak), kutu boşalt/yer değiştir, kaydet */
export default function ViewEditor({ initial, layouts, names, onSaved, onCancel, onDeleted }: {
  initial: ViewTemplate | null; layouts: ViewLayout[]; names: Record<string, string>;
  onSaved: (v: ViewTemplate) => void; onCancel: () => void; onDeleted: (id: string) => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [layoutId, setLayoutId] = useState(initial?.layout ?? "4");
  const [tiles, setTiles] = useState<Array<TileRef | null>>(initial?.tiles ?? [null, null, null, null]);
  const [labels, setLabels] = useState<Record<string, string>>(names);
  const [selected, setSelected] = useState(0);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const layout = layouts.find((l) => l.id === layoutId) ?? layouts[0];
  const used = useMemo(() => new Set(tiles.filter((t): t is TileRef => !!t).map(refKey)), [tiles]);

  const chooseLayout = (l: ViewLayout) => {
    const r = retile(tiles, l.cells.length);
    setLayoutId(l.id);
    setTiles(r.tiles);
    setSelected(0);
    setNote(r.dropped ? `${r.dropped} kamera düzene sığmadı ve şablondan çıkarıldı.` : null);
  };
  const place = (i: number, ref: TileRef, label: string) => {
    if (used.has(refKey(ref))) return;
    setTiles((t) => t.map((x, j) => (j === i ? ref : x)));
    setLabels((m) => ({ ...m, [refKey(ref)]: label }));
    setSelected(Math.min(i + 1, tiles.length - 1));
  };
  const swap = (a: number, b: number) => setTiles((t) => { const n = [...t]; [n[a], n[b]] = [n[b], n[a]]; return n; });
  const save = async () => {
    setBusy(true); setError(null);
    try {
      const body = { name: name.trim(), layout: layoutId, tiles };
      const v = initial ? await api<ViewTemplate>(`views/${initial.id}`, { method: "PUT", json: body })
                        : await api<ViewTemplate>("views", { method: "POST", json: body });
      onSaved(v);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const remove = async () => {
    if (!initial || !window.confirm(`"${initial.name}" şablonu silinsin mi?`)) return;
    try { await api(`views/${initial.id}`, { method: "DELETE" }); onDeleted(initial.id); } catch (e) { setError((e as Error).message); }
  };

  return (
    <section aria-label="Şablon düzenleyici" className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
      <div className="grid content-start gap-3">
        <label className="text-sm font-medium">Şablon adı
          <input aria-label="Şablon adı" value={name} maxLength={60} onChange={(e) => setName(e.target.value)}
                 className="mt-1.5 h-10 w-full rounded-[10px] border border-line bg-white px-3 text-sm" />
        </label>
        <div role="group" aria-label="Düzen" className="flex flex-wrap gap-1.5">
          {layouts.map((l) => (
            <button key={l.id} type="button" aria-pressed={l.id === layoutId} onClick={() => chooseLayout(l)}
                    className={`h-9 rounded-[9px] border px-2.5 text-[13px] ${l.id === layoutId ? "border-brand-500 bg-brand-50" : "border-line"}`}>{l.name}</button>
          ))}
        </div>
        {note && <p role="status" className="rounded-xl bg-warn-50 px-3 py-2 text-sm text-warn-700">{note}</p>}
        <div className="relative w-full overflow-hidden rounded-2xl bg-ink/90" style={{ aspectRatio: `${layout.cols * 16} / ${layout.rows * 9}` }}>
          {layout.cells.map((_, i) => {
            const t = tiles[i];
            return (
              <div key={i} data-testid="edit-tile" style={cellBox(layout, i)} className="absolute p-1"
                   draggable={!!t} onDragStart={(e) => e.dataTransfer.setData("application/x-bv-tile", String(i))}
                   onDragOver={(e) => e.preventDefault()}
                   onDrop={(e) => {
                     e.preventDefault();
                     const from = e.dataTransfer.getData("application/x-bv-tile");
                     if (from !== "") return swap(Number(from), i);
                     const cam = e.dataTransfer.getData("application/x-bv-camera");
                     if (cam) { const { ref, name: n } = JSON.parse(cam) as { ref: TileRef; name: string }; place(i, ref, n); }
                   }}
                   onClick={() => setSelected(i)}>
                <div className={`flex h-full w-full items-center justify-center rounded-md border-2 text-center text-[12px] text-white ${selected === i ? "border-brand-500" : "border-white/20"}`}>
                  {t ? (
                    <span className="grid gap-1 p-1">
                      <span className="truncate">{labels[refKey(t)] ?? "Kamera"}</span>
                      <button type="button" onClick={(e) => { e.stopPropagation(); setTiles((x) => x.map((y, j) => (j === i ? null : y))); }}
                              className="mx-auto rounded bg-white/15 px-1.5 text-[11px]">Boşalt</button>
                    </span>
                  ) : <span className="text-white/50">{selected === i ? "Listeden kamera seçin" : "Boş"}</span>}
                </div>
              </div>
            );
          })}
        </div>
        {error && <p role="alert" className="rounded-xl bg-nok-50 px-3 py-2 text-sm text-nok-600">{error}</p>}
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={save} disabled={busy || !name.trim()} className="brand-gradient h-10 rounded-[10px] px-4 text-sm font-semibold text-white">Kaydet</button>
          <button type="button" onClick={onCancel} className="h-10 rounded-[10px] border border-line px-4 text-sm">Vazgeç</button>
          {initial && <button type="button" onClick={remove} className="ml-auto h-10 rounded-[10px] px-3 text-sm text-nok-600">Şablonu sil</button>}
        </div>
      </div>
      <CameraList used={used} onPick={(ref, n) => place(selected, ref, n)} />
    </section>
  );
}
```

- [ ] **Adım 5: `WatchView`'a bağla.** İçe aktarmalar: `ViewEditor`, `refKey` (`./CameraList`), `type Source` (`@/lib/live`). Durumlar:

```tsx
  const [editing, setEditing] = useState<ViewTemplate | "new" | null>(null);
  const [recorders, setRecorders] = useState<Source[]>([]);
  const [info, setInfo] = useState<string | null>(null);
  useEffect(() => { api<Source[]>("sources").then((s) => setRecorders(s.filter((x) => x.kind === "recorder"))).catch(() => undefined); }, []);
  const names = Object.fromEntries((status?.tiles ?? []).filter((t): t is NonNullable<typeof t> => !!t)
    .map((t) => [refKey({ sourceId: t.sourceId, channelId: t.channelId }), t.name]));
  const copy = async () => {
    if (!view) return;
    try {
      const v = await api<ViewTemplate>("views", { method: "POST", json: { name: `${view.name} (kopya)`.slice(0, 60), layout: view.layout, tiles: view.tiles } });
      await reload(v.id);
    } catch (e) { setError((e as Error).message); }
  };
  const fromRecorder = async (sourceId: string) => {
    if (!sourceId) return;
    try {
      const v = await api<ViewTemplate & { truncated: boolean; channelCount: number }>("views/from-recorder", { method: "POST", json: { sourceId } });
      setInfo(v.truncated ? `İlk 16 kanal alındı (toplam ${v.channelCount}).` : null);
      await reload(v.id);
    } catch (e) { setError((e as Error).message); }
  };
```

Düzenleme kipi ana dönüşün başında, `single` denetiminden sonra:

```tsx
  if (editing) return (
    <ViewEditor initial={editing === "new" ? null : editing} layouts={layouts} names={names}
                onSaved={(v) => { setEditing(null); reload(v.id); }} onCancel={() => setEditing(null)}
                onDeleted={() => { setEditing(null); reload(); }} />
  );
```

Üst çubuktaki "Görev 6" yorumunun yerine:

```tsx
        <button type="button" onClick={() => setEditing("new")} className="h-10 rounded-[10px] border border-line px-3 text-sm">Yeni şablon</button>
        <button type="button" onClick={() => view && setEditing(view)} disabled={!view} className="h-10 rounded-[10px] border border-line px-3 text-sm">Düzenle</button>
        <button type="button" onClick={copy} disabled={!view} className="h-10 rounded-[10px] border border-line px-3 text-sm">Kopyala</button>
        {recorders.length > 0 && (
          <select aria-label="Tüm kanallardan şablon" value="" onChange={(e) => fromRecorder(e.target.value)}
                  className="h-10 rounded-[10px] border border-line bg-white px-2 text-sm">
            <option value="">Tüm kanallardan şablon…</option>
            {recorders.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
        )}
```

`error` iletisinin yanında: `{info && <p role="status" className="rounded-xl bg-warn-50 px-3 py-2 text-sm text-warn-700">{info}</p>}`.

- [ ] **Adım 6: Gerçek yığın e2e'yi genişlet** — `watch.spec.ts`'ye:

```ts
test("izleme (gerçek yığın): arayüzden şablon oluştur, akış gelir, sil", async ({ page }) => {
  page.on("dialog", (d) => d.accept());
  await login(page);
  const src = await (await page.request.post("/api/live/sources", { data: {
    kind: "camera", brand: "custom", customUrl: CLIP, name: "Düzenleyici klibi" } })).json();
  await page.goto("/watch");
  await page.getByRole("button", { name: "Yeni şablon" }).click();
  const ed = page.getByRole("region", { name: "Şablon düzenleyici" });
  await ed.getByLabel("Şablon adı").fill("Arayüz şablonu");
  await ed.getByRole("button", { name: "Tek" }).click();
  await ed.getByTestId("edit-tile").first().click();
  await ed.getByRole("button", { name: "Düzenleyici klibi" }).click();
  await ed.getByRole("button", { name: "Kaydet" }).click();
  await expect(page.getByRole("combobox", { name: "Şablon" })).toContainText("Arayüz şablonu");
  await expect.poll(async () => page.getByAltText("Arayüz şablonu canlı görüntü")
    .evaluate((img: HTMLImageElement) => img.naturalWidth), { timeout: 30_000 }).toBeGreaterThan(0);
  await page.getByRole("button", { name: "Düzenle" }).click();
  await page.getByRole("button", { name: "Şablonu sil" }).click();
  await expect(page.getByRole("combobox", { name: "Şablon" })).not.toContainText("Arayüz şablonu");
  await page.request.delete(`/api/live/sources/${src.id}`);
});
```

- [ ] **Adım 7: Doğrula** (Görev 5 Adım 7 ile aynı komutlar). Beklenen: TAM takım PASS. `CamerasView` testleri de geçmeli.

- [ ] **Adım 8: Commit**

```bash
git add apps/dashboard
git commit -m "Panel: şablon düzenleyici (düzen, kamera atama, sürükle-bırak, kopyala, tüm kanallardan şablon)"
```

---

### Görev 7: Telefondan erişim (yerel ağ, şifre, QR)

**Dosyalar:**
- Oluştur:
  - `apps/dashboard/src/lib/accessCore.mjs`: saf mantık; Node'da test edilir, Next'ten içe aktarılır.
  - `apps/dashboard/src/lib/accessCore.d.mts`
  - `apps/dashboard/src/lib/accessCore.test.mjs`
  - `apps/dashboard/src/app/api/access/route.ts`
  - `apps/dashboard/src/app/(panel)/settings/page.tsx`
  - `apps/dashboard/src/components/settings/AccessSettings.tsx`
  - `tools/panel_run.mjs`
  - `apps/dashboard/e2e/access.spec.ts`
- Değiştir:
  - `apps/dashboard/src/lib/session.ts`: hash kipi.
  - `apps/dashboard/src/middleware.ts`
  - `apps/dashboard/src/app/api/login/route.ts`
  - `apps/dashboard/src/app/(panel)/layout.tsx`: `canLogout`.
  - `apps/dashboard/src/components/Sidebar.tsx`: "Ayarlar" girişi, "Bildirimler"den sonra.
  - `apps/dashboard/package.json`: `qrcode` + `@types/qrcode`, `"test:unit": "node --test src/lib/accessCore.test.mjs"`.
  - `apps/dashboard/.gitignore`: `/.local/`.
  - `apps/dashboard/playwright.config.ts`: `PANEL_ACCESS_FILE` geçici dosyada.
  - `tools/panel_baslat.bat`: panel `node tools/panel_run.mjs` ile başlar.
  - `.github/workflows/ci.yml`: dashboard işine `npm run test:unit`.

**Arayüzler:**
- Üretir (`accessCore.mjs`):
  - `MIN_PASSWORD = 8`;
  - `hashPassword(pw: string): { salt: string; hash: string }`;
  - `verifyPassword(pw, salt, hash): boolean`;
  - `newSecret(): string`;
  - `panelPlan(access: Access | null, env: Record<string, string | undefined>): { host: "127.0.0.1" | "0.0.0.0"; env: Record<string, string> }`;
  - `accessFile(env, cwd): string` (varsayılan `<cwd>/.local/access.json`, `PANEL_ACCESS_FILE` önceliklidir).
- `Access`:

  ```
  { enabled: boolean; salt?: string; hash?: string; secret?: string; updatedAt?: number }
  ```
- Ortam değişkenleri (başlatıcı → Next): `PANEL_PASSWORD_HASH`, `PANEL_PASSWORD_SALT`, `PANEL_SESSION_SECRET`, `PANEL_RUNNER=1`.

- [ ] **Adım 1: Başarısız birim testleri** — `apps/dashboard/src/lib/accessCore.test.mjs`:

```js
import assert from "node:assert/strict";
import test from "node:test";
import { MIN_PASSWORD, accessFile, hashPassword, newSecret, panelPlan, verifyPassword } from "./accessCore.mjs";

test("şifre yalnızca özetiyle doğrulanır; düz şifre özette yok", () => {
  const { salt, hash } = hashPassword("ofis-sifre-1");
  assert.ok(verifyPassword("ofis-sifre-1", salt, hash));
  assert.ok(!verifyPassword("ofis-sifre-2", salt, hash));
  assert.ok(!hash.includes("ofis") && hash.length === 64 && salt.length === 32);
  assert.equal(MIN_PASSWORD, 8);
});

test("erişim kapalıyken ya da şifre yokken panel yalnızca bu bilgisayarda", () => {
  assert.deepEqual(panelPlan(null, {}), { host: "127.0.0.1", env: {} });
  assert.equal(panelPlan({ enabled: true }, {}).host, "127.0.0.1");                    // şifresiz yerel ağ ASLA
  const { salt, hash } = hashPassword("ofis-sifre-1");
  assert.equal(panelPlan({ enabled: false, salt, hash, secret: newSecret() }, {}).host, "127.0.0.1");
});

test("erişim açık + şifre: tüm arayüzler ve oturum sırrı ortama", () => {
  const { salt, hash } = hashPassword("ofis-sifre-1");
  const secret = newSecret();
  const p = panelPlan({ enabled: true, salt, hash, secret }, {});
  assert.equal(p.host, "0.0.0.0");
  assert.deepEqual(p.env, { PANEL_PASSWORD_HASH: hash, PANEL_PASSWORD_SALT: salt, PANEL_SESSION_SECRET: secret });
});

test("DASHBOARD_PASSWORD önceliklidir: dosyadaki özet ortama verilmez", () => {
  const { salt, hash } = hashPassword("ofis-sifre-1");
  const p = panelPlan({ enabled: true, salt, hash, secret: newSecret() }, { DASHBOARD_PASSWORD: "ortam-sifresi" });
  assert.equal(p.host, "0.0.0.0");
  assert.deepEqual(p.env, {});
});

test("erişim dosyası yolu: PANEL_ACCESS_FILE önce", () => {
  assert.equal(accessFile({ PANEL_ACCESS_FILE: "/tmp/x.json" }, "/app"), "/tmp/x.json");
  assert.match(accessFile({}, "/app"), /\.local[\\/]access\.json$/);
});
```

Çalıştır: `cd apps/dashboard && node --test src/lib/accessCore.test.mjs`. Beklenen: FAIL (modül yok).

- [ ] **Adım 2: `accessCore.mjs` ve `accessCore.d.mts`**

```js
// Telefondan erişim: panel şifresi (yalnızca scrypt özeti), oturum sırrı ve paneli hangi adreste açacağımız.
// Saf mantık: hem Next (API rotası, giriş) hem başlatıcı (tools/panel_run.mjs) kullanır; `node --test` ile sınanır.
import { randomBytes, scryptSync, timingSafeEqual } from "node:crypto";
import path from "node:path";

export const MIN_PASSWORD = 8;
const SCRYPT = { N: 16384, r: 8, p: 1 };

export function hashPassword(pw) {
  const salt = randomBytes(16).toString("hex");
  return { salt, hash: scryptSync(pw, salt, 32, SCRYPT).toString("hex") };
}

export function verifyPassword(pw, salt, hash) {
  if (!salt || !hash) return false;
  const want = Buffer.from(hash, "hex");
  const got = scryptSync(String(pw), salt, 32, SCRYPT);
  return want.length === got.length && timingSafeEqual(want, got);
}

export function newSecret() {
  return randomBytes(32).toString("hex");
}

export function accessFile(env, cwd) {
  return env.PANEL_ACCESS_FILE || path.join(cwd, ".local", "access.json");
}

/** Panel hangi adreste açılsın ve Next'e hangi ortam değişkenleri gitsin. Şifresiz yerel ağ ASLA açılmaz. */
export function panelPlan(access, env) {
  const envPw = Boolean(env.DASHBOARD_PASSWORD);
  const hashed = Boolean(access && access.salt && access.hash && access.secret);
  const lan = Boolean(access && access.enabled) && (envPw || hashed);
  const out = {};
  if (lan && !envPw) {
    out.PANEL_PASSWORD_HASH = access.hash;
    out.PANEL_PASSWORD_SALT = access.salt;
    out.PANEL_SESSION_SECRET = access.secret;
  }
  return { host: lan ? "0.0.0.0" : "127.0.0.1", env: out };
}
```

`accessCore.d.mts`:

```ts
export interface Access { enabled: boolean; salt?: string; hash?: string; secret?: string; updatedAt?: number }
export const MIN_PASSWORD: number;
export function hashPassword(pw: string): { salt: string; hash: string };
export function verifyPassword(pw: string, salt: string | undefined, hash: string | undefined): boolean;
export function newSecret(): string;
export function accessFile(env: Record<string, string | undefined>, cwd: string): string;
export function panelPlan(access: Access | null, env: Record<string, string | undefined>): { host: "127.0.0.1" | "0.0.0.0"; env: Record<string, string> };
```

Çalıştır: `node --test src/lib/accessCore.test.mjs`. Beklenen: PASS.

- [ ] **Adım 3: Oturum (Edge uyumlu).** `session.ts`:

```ts
/** Giriş türü: ortamdaki DASHBOARD_PASSWORD (öncelikli) ya da başlatıcının verdiği şifre özeti + oturum sırrı. */
export type AuthMode = { kind: "env"; password: string } | { kind: "hash"; secret: string; salt: string; hash: string } | null;

export function authMode(): AuthMode {
  const pw = panelPassword();
  if (pw) return { kind: "env", password: pw };
  const secret = process.env.PANEL_SESSION_SECRET, salt = process.env.PANEL_PASSWORD_SALT, hash = process.env.PANEL_PASSWORD_HASH;
  return secret && salt && hash ? { kind: "hash", secret, salt, hash } : null;
}

/** Beklenen oturum çerezi: env kipinde şifreden (eskisi gibi), hash kipinde sırdan HMAC (şifre değişince sır da değişir) */
export async function expectedToken(mode: NonNullable<AuthMode>): Promise<string> {
  if (mode.kind === "env") return sessionToken(mode.password);
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(mode.secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode("bandvision-panel:v2"));
  return Array.from(new Uint8Array(sig), (b) => b.toString(16).padStart(2, "0")).join("");
}
```

`middleware.ts`:

```ts
  const mode = authMode();
  if (!mode) return NextResponse.next();
  if (req.cookies.get(SESSION_COOKIE)?.value === (await expectedToken(mode))) return NextResponse.next();
```

Bu iki satır, mevcut `pw` satırlarının yerine geçer; geri kalanı aynı kalır.

`login/route.ts`:
- `pw` yerine `const mode = authMode();` kullanılır.
- Doğrulama: `mode?.kind === "env" ? same(given, mode.password) : mode?.kind === "hash" ? verifyPassword(given, mode.salt, mode.hash) : false`. `verifyPassword` `@/lib/accessCore.mjs`'ten içe aktarılır.
- Çerez değeri `await expectedToken(mode)` olur.

`(panel)/layout.tsx`: `canLogout={authMode() !== null}`.

- [ ] **Adım 4: Erişim API rotası** — `src/app/api/access/route.ts`:

```ts
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { NextResponse, type NextRequest } from "next/server";
import { MIN_PASSWORD, accessFile, hashPassword, newSecret, type Access } from "@/lib/accessCore.mjs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function file(): string { return accessFile(process.env, process.cwd()); }
function read(): Access | null {
  try { return JSON.parse(fs.readFileSync(file(), "utf8")) as Access; } catch { return null; }
}
function addresses(): string[] {
  const port = process.env.PORT || "3000";
  return Object.values(os.networkInterfaces()).flat()
    .filter((i): i is os.NetworkInterfaceInfo => !!i && i.family === "IPv4" && !i.internal)
    .map((i) => `http://${i.address}:${port}`);
}
function view(a: Access | null) {
  return {
    enabled: Boolean(a?.enabled), hasPassword: Boolean(a?.hash), envPassword: Boolean(process.env.DASHBOARD_PASSWORD),
    /** Bu çalışan panel şu an yerel ağa açık mı (başlatıcı ayarladı) */
    lanActive: Boolean(process.env.PANEL_SESSION_SECRET) || (Boolean(process.env.DASHBOARD_PASSWORD) && Boolean(a?.enabled)),
    runner: process.env.PANEL_RUNNER === "1", addresses: addresses(),
  };
}

export async function GET() {
  return NextResponse.json(view(read()));
}

/** {enabled, password?}: şifre verilirse en az 8 karakter; açmak için şifre (ya da DASHBOARD_PASSWORD) gerekir */
export async function PUT(req: NextRequest) {
  let body: { enabled?: unknown; password?: unknown };
  try { body = (await req.json()) as typeof body; } catch { return NextResponse.json({ detail: "Geçersiz istek." }, { status: 400 }); }
  const cur = read() ?? { enabled: false };
  const next: Access = { ...cur, enabled: Boolean(body.enabled), updatedAt: Date.now() / 1000 };
  if (typeof body.password === "string" && body.password !== "") {
    if (body.password.length < MIN_PASSWORD) return NextResponse.json({ detail: `Şifre en az ${MIN_PASSWORD} karakter olmalı.` }, { status: 422 });
    Object.assign(next, hashPassword(body.password), { secret: newSecret() });   // yeni şifre: eski oturumlar düşer
  }
  if (next.enabled && !next.hash && !process.env.DASHBOARD_PASSWORD) {
    return NextResponse.json({ detail: "Telefondan erişim için önce panel şifresi belirleyin." }, { status: 422 });
  }
  fs.mkdirSync(path.dirname(file()), { recursive: true });
  fs.writeFileSync(file(), JSON.stringify(next), { encoding: "utf8", mode: 0o600 });
  return NextResponse.json(view(next));
}
```

- [ ] **Adım 5: Ayarlar sayfası ve QR.**
  - `npm install qrcode @types/qrcode` çalıştırılır. `package.json` ile `package-lock.json` değişir.
  - **Worktree'de çalışılıyorsa:** `node_modules` ana klasöre bağlantıdır; kurulum ekleme yapar ve bu kabul edilir.

`AccessSettings.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import QRCode from "qrcode";

interface AccessView { enabled: boolean; hasPassword: boolean; envPassword: boolean; lanActive: boolean; runner: boolean; addresses: string[] }

/** Ayarlar → Telefondan erişim: panel şifresi, açma/kapama, telefon adresi ve QR kodu */
export default function AccessSettings() {
  const [v, setV] = useState<AccessView | null>(null);
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const load = async () => setV(await (await fetch("/api/access", { cache: "no-store" })).json());
  useEffect(() => { load().catch(() => setMsg({ ok: false, text: "Ayarlar okunamadı." })); }, []);
  useEffect(() => {
    const url = v?.addresses[0];
    if (v?.lanActive && url) QRCode.toDataURL(url, { margin: 1, width: 220 }).then(setQr).catch(() => setQr(null));
    else setQr(null);
  }, [v]);
  const save = async (enabled: boolean) => {
    if (pw && pw !== pw2) return setMsg({ ok: false, text: "Şifreler aynı değil." });
    const res = await fetch("/api/access", { method: "PUT", headers: { "content-type": "application/json" },
      body: JSON.stringify({ enabled, password: pw || null }) });
    const body = await res.json();
    if (!res.ok) return setMsg({ ok: false, text: body.detail ?? "Kaydedilemedi." });
    setPw(""); setPw2(""); setV(body);
    setMsg({ ok: true, text: body.runner ? "Kaydedildi. Panel birkaç saniye içinde yeniden başlıyor; sayfayı sonra yenileyin."
                                          : "Kaydedildi. Geçerli olması için paneli masaüstü kısayoluyla yeniden başlatın." });
  };
  if (!v) return null;
  return (
    <section className="card grid max-w-[640px] gap-3 p-5">
      <p className="eyebrow">Telefondan erişim</p>
      <p className="text-sm text-muted">Açıkken panel ofis ağındaki telefon ve bilgisayarlardan açılır ve herkesten (bu bilgisayar dahil) şifre ister.</p>
      {v.envPassword
        ? <p className="text-[13px] text-faint">Panel şifresi bu bilgisayarın ayarında (DASHBOARD_PASSWORD) tanımlı.</p>
        : (
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="text-sm font-medium">{v.hasPassword ? "Yeni panel şifresi" : "Panel şifresi"}
              <input aria-label="Panel şifresi" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)}
                     className="mt-1.5 h-10 w-full rounded-[10px] border border-line bg-white px-3 text-sm" />
            </label>
            <label className="text-sm font-medium">Şifre (tekrar)
              <input aria-label="Şifre (tekrar)" type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)}
                     className="mt-1.5 h-10 w-full rounded-[10px] border border-line bg-white px-3 text-sm" />
            </label>
            <p className="text-[12px] text-faint sm:col-span-2">En az 8 karakter. Şifre bu bilgisayarda yalnızca özeti olarak saklanır.</p>
          </div>
        )}
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => save(true)} className="brand-gradient h-10 rounded-[10px] px-4 text-sm font-semibold text-white">
          {v.enabled ? "Kaydet" : "Telefondan erişimi aç"}</button>
        {v.enabled && <button type="button" onClick={() => save(false)} className="h-10 rounded-[10px] border border-line px-4 text-sm">Erişimi kapat</button>}
      </div>
      {msg && <p role="status" className={`rounded-xl px-3 py-2 text-sm ${msg.ok ? "bg-ok-50 text-ok-600" : "bg-nok-50 text-nok-600"}`}>{msg.text}</p>}
      {v.lanActive && v.addresses.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-[220px_1fr] sm:items-center">
          {/* eslint-disable-next-line @next/next/no-img-element -- yerel üretilen QR (data URL) */}
          {qr && <img src={qr} alt="Telefonla okutun" width={220} height={220} />}
          <div className="text-sm">
            <p>Telefonun kamerasıyla QR'ı okutun ya da tarayıcıya yazın:</p>
            <ul className="mt-1 font-mono text-[13px]">{v.addresses.map((a) => <li key={a}>{a}</li>)}</ul>
          </div>
        </div>
      )}
      <p className="text-[12px] text-faint">İlk açılışta Windows güvenlik duvarı "özel ağda izin ver" diye sorabilir; izin verin. Bağlantı ofis ağında şifrelenmemiş http'dir; dışarıdan erişim ayrıca kurulmalıdır.</p>
    </section>
  );
}
```

`settings/page.tsx`: `PageHeader` başlığı "Ayarlar" ve `<AccessSettings />`. `notifications/page.tsx` desenini izle. Sidebar'a ekle:

```ts
  { href: "/settings", label: "Ayarlar", icon: icon("M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z") },
```

- [ ] **Adım 6: Başlatıcı** — `tools/panel_run.mjs`:

```js
#!/usr/bin/env node
// Paneli erişim ayarına göre başlatır: telefondan erişim kapalıyken yalnızca bu bilgisayar (127.0.0.1), açıkken (şifreyle)
// tüm ağ arayüzleri. apps/dashboard/.local/access.json değişince Next'i yeniden başlatır (≈ 10 sn).
// Kullanım: node tools/panel_run.mjs [--prod] [--port 3000]
import { execFileSync, spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { accessFile, panelPlan } from "../apps/dashboard/src/lib/accessCore.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DASH = path.join(ROOT, "apps", "dashboard");
const prod = process.argv.includes("--prod");
const portArg = process.argv.indexOf("--port");
const port = portArg > 0 ? process.argv[portArg + 1] : "3000";
const FILE = accessFile(process.env, DASH);

const text = () => { try { return fs.readFileSync(FILE, "utf8"); } catch { return ""; } };
const parse = (t) => { try { return t ? JSON.parse(t) : null; } catch { return null; } };
let child = null;
let last = text();

function start() {
  const plan = panelPlan(parse(last), process.env);
  console.log(`[panel] ${plan.host === "0.0.0.0" ? "yerel ağa açık (şifreli)" : "yalnızca bu bilgisayar"} · port ${port}`);
  child = spawn("npx", ["next", prod ? "start" : "dev", "-H", plan.host, "-p", port],
                { cwd: DASH, env: { ...process.env, ...plan.env, PANEL_RUNNER: "1", PORT: port }, stdio: "inherit",
                  shell: process.platform === "win32" });
}
function stop() {
  if (!child) return;
  try {
    if (process.platform === "win32") execFileSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
    else child.kill("SIGTERM");
  } catch { /* zaten kapanmış */ }
  child = null;
}
fs.watchFile(FILE, { interval: 2000 }, () => {
  const t = text();
  if (t === last) return;
  last = t;
  console.log("[panel] erişim ayarı değişti: yeniden başlatılıyor");
  stop();
  setTimeout(start, 1500);
});
for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => { stop(); process.exit(0); });
start();
```

Çocuk süreç yalnızca kendi **PID**'iyle sonlandırılır (`/PID … /T`). Süreç adıyla sonlandırma yok.

`tools/panel_baslat.bat`'ta panel satırı:

```bat
if errorlevel 1 start "BandVision panel" /min /d "%DASH%" cmd /c "node "%ROOT%\tools\panel_run.mjs" 1>>"%LOGS%\panel.log" 2>&1"
```

`curl` sağlık denetimi `127.0.0.1:3000` olarak kalır; `0.0.0.0` loopback'i de dinler.

`.gitignore`: `/.local/`.

`playwright.config.ts` panel `webServer.env`'ine:

```ts
PANEL_ACCESS_FILE: path.join(DATA_DIR, "panel-access.json")
```

`package.json` `scripts`: `"test:unit": "node --test src/lib/accessCore.test.mjs"`.

CI dashboard işinde `npm run typecheck`'ten sonra: `- run: npm run test:unit`.

- [ ] **Adım 7: e2e** — `apps/dashboard/e2e/access.spec.ts`. e2e'de `DASHBOARD_PASSWORD` tanımlıdır; ortam şifresi kipi sınanır:

```ts
import { expect, test } from "@playwright/test";

test("ayarlar: ortam şifresi varken telefondan erişim açılır/kapanır; şifre yanıtta yok", async ({ page }) => {
  await page.goto("/settings");
  await page.getByLabel("Şifre").fill("e2e-test-sifresi");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByText("DASHBOARD_PASSWORD")).toBeVisible();
  await page.getByRole("button", { name: "Telefondan erişimi aç" }).click();
  await expect(page.getByRole("status")).toContainText("yeniden başlatın");
  const v = await (await page.request.get("/api/access")).json();
  expect(v.enabled).toBe(true);
  expect(JSON.stringify(v)).not.toContain("e2e-test-sifresi");
  await page.getByRole("button", { name: "Erişimi kapat" }).click();
  expect((await (await page.request.get("/api/access")).json()).enabled).toBe(false);
});

test("ayarlar API: kısa şifre ve şifresiz açma reddedilir; şifre dosyada düz yazılmaz", async ({ page }) => {
  await page.goto("/settings");
  await page.getByLabel("Şifre").fill("e2e-test-sifresi");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  const short = await page.request.put("/api/access", { data: { enabled: false, password: "kisa" } });
  expect(short.status()).toBe(422);
  expect((await short.json()).detail).toContain("en az 8");
  const ok = await page.request.put("/api/access", { data: { enabled: false, password: "uzun-sifre-123" } });
  expect(ok.status()).toBe(200);
  expect(JSON.stringify(await ok.json())).not.toContain("uzun-sifre-123");
});
```

Hash kipinin girişi `accessCore.test.mjs` ile sınanır: özet doğrulama ve `panelPlan`. Gerçek bir hash kipi sunucusu e2e'de kurulmaz.

- [ ] **Adım 8: Doğrula.** `apps/dashboard` içinde çalıştır:
  - `npm run test:unit`
  - `npx eslint src e2e && npx tsc --noEmit && npm run build`
  - TAM Playwright.

  Ayrıca elle denetle: `node tools/panel_run.mjs --port 3105` (masaüstündeki panele dokunmadan) şunu yazmalı: "yalnızca bu bilgisayar · port 3105". Denedikten sonra yalnızca kendi başlattığın süreci, **PID'iyle** kapat.

- [ ] **Adım 9: Commit**

```bash
git add apps/dashboard tools/panel_run.mjs tools/panel_baslat.bat .github/workflows/ci.yml
git commit -m "Panel: telefondan erişim (yalnızca şifreyle yerel ağ, özetli şifre, QR, başlatıcı)"
```

---

### Görev 8: Belgeler

**Dosyalar:** `docs/13-web-platform.md`, `docs/12-durum.md`, `docs/03-algorithm.md` (yalnızca gerekiyorsa), `docs/superpowers/specs/2026-10-08-coklu-izleme-design.md` (durum satırı)

- [ ] **Adım 1: `docs/13-web-platform.md`.**
  - Canlı API tablosuna Görev 2 ve 4'ün uçları eklenir:
    - `view-layouts`;
    - `views` CRUD;
    - `views/from-recorder` (`truncated`, `channelCount`);
    - `views/{id}/stream?w=&h=`;
    - `views/{id}/status` (alanlarıyla);
    - `cameras/stream`;
    - `cameras/status`.
  - "Çoklu izleme" paragrafı:
    - düzenler;
    - şablonların `views.json`'da saklanması;
    - okuyucu paylaşımı (oturum karesi);
    - 16/2 sınırı;
    - 30 sn kapanma;
    - 10 kare/sn ve 1920×1080;
    - alt akış;
    - kayıt yapmama.
  - "Telefondan erişim" paragrafı:
    - varsayılan `127.0.0.1`;
    - erişim açıkken herkes için şifre;
    - scrypt özeti `.local/access.json`'da;
    - `DASHBOARD_PASSWORD` önceliği;
    - başlatıcının yeniden başlatması;
    - QR;
    - güvenlik duvarı;
    - http sınırı.

  Değerleri koddan doğrula.
- [ ] **Adım 2: `docs/12-durum.md`.**
  - Durum maddesi: "Çoklu kamera izleme (web, şablonlu ızgara) + telefondan erişim".
  - Performans ölçümü **BEKLİYOR** (Görev 9).
  - iPhone ekranı ayrı alt proje (B).
- [ ] **Adım 3:** Tasarım belgesinin durum satırı "uygulandı (ölçüm bekliyor)" olur.
- [ ] **Adım 4: Commit**

```bash
git add docs
git commit -m "Belgeler: çoklu izleme ve telefondan erişim"
```

---

### Görev 9: Gerçek ölçüm (kabul — kullanıcıyla)

Bu görev kod değil, ölçümdür. Kontrolcü kullanıcıyla birlikte yapar.

- [ ] **Adım 1:** Ofis NVR'ında 4'lü, 9'lu ve (kanal varsa) 16'lı şablon oluşturulur.
  - "Tüm kanallardan şablon" denenir.
  - Her biri 2'şer dakika izlenir.
  - Analiz sunucusu sürecinin işlemci kullanımı (Görev Yöneticisi ya da `typeperf`) ve kutu fps'leri (`views/{id}/status`) not edilir.
  - Aynı anda çalışan sayım oturumunun fps'i önce ve sonra not edilir.
- [ ] **Adım 2:** Telefondan erişim açılır. Telefon ofis Wi-Fi'ında QR ile bağlanıp şifreyle girer; 9'lu şablon telefonda izlenir; tek kamera büyütülür.
- [ ] **Adım 3:** Bir güvenlik oturumu açıkken deneme alarmıyla kutunun kırmızı yanması doğrulanır.
- [ ] **Adım 4:** Sonuçlar `docs/12-durum.md` ve `docs/13-web-platform.md`'ye yazılır. Kabul ölçütü tutmuyorsa (16 kamerada < 8 kare/sn ya da sayım fps'i belirgin düşüyor) bulgu kullanıcıya sunulur. Değerler yalnızca sayıyla yazılır; cihaz modeli, IP ya da yol yazılmaz.
