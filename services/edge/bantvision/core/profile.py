"""Ürün profili (contracts/product-profile.schema.json) için tipli model."""
from __future__ import annotations

import math
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Roi:
    x: float = 0.05
    y: float = 0.1
    width: float = 0.9
    height: float = 0.8


@dataclass
class GeometryQC:
    areaMinFactor: float = 0.8
    areaMaxFactor: float = 1.25
    aspectMin: float = 1.0
    aspectMax: float = 3.0
    solidityMin: float = 0.9


@dataclass
class SpotsQC:
    enabled: bool = False
    darkDelta: int = 35
    maxSpotAreaRatio: float = 0.004


@dataclass
class CodeQC:
    required: bool = False
    symbologies: list[str] = field(default_factory=list)
    pattern: str | None = None


@dataclass
class SizeClass:
    name: str
    maxMm: float


@dataclass
class QCConfig:
    enabled: bool = False
    geometry: GeometryQC = field(default_factory=GeometryQC)
    spots: SpotsQC = field(default_factory=SpotsQC)
    barcode: CodeQC = field(default_factory=CodeQC)
    text: CodeQC = field(default_factory=CodeQC)
    sizeClasses: list[SizeClass] = field(default_factory=list)
    saveNokImages: bool = True


@dataclass
class Profile:
    name: str = "Genel ürün"
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    schema: str = "bantvision.profile.v1"
    roi: Roi = field(default_factory=Roi)
    # İsteğe bağlı çokgen ROI (algoritma §2.0): normalize köşeler; roi bunun sınır kutusudur
    roiPolygon: list[tuple[float, float]] | None = None
    # İsteğe bağlı açılı sayım çizgisi (algoritma §4.8): (a, b); akış a→b'nin sağ eli
    countLine: tuple[tuple[float, float], tuple[float, float]] | None = None
    linePosition: float = 0.5
    direction: str = "down"
    diffThreshold: int = 25
    expectedArea: float = 0.0
    minAreaFactor: float = 0.4
    minAreaAbs: float = 0.002
    splitTouching: bool = False
    maxMultiplicity: int = 4
    closeIterations: int = 1
    processingWidth: int = 240
    minHits: int = 2
    maxMatchDistance: float = 0.15
    backgroundRate: float = 0.02
    # Sayım yöntemi (§4.9): "blob" = arka plan farkı + izleme; "linescan" = şerit tarama (tek sıra, bitişik hacimli ürün)
    countMode: str = "blob"
    # linescan: tek ürünün akış boyunca boyu, ROI'nin akış uzunluğuna oranla (0 = otomatik öğren)
    productLength: float = 0.0
    # detect (§4.10): sayılacak sınıflar (core/detector.py CLASS_IDS), tanıma güven eşiği, isteğe bağlı kapasite
    detectClasses: list[str] = field(default_factory=lambda: ["person"])
    detectConfidence: float = 0.35
    # Çizgiye göre konum noktası: "center" (tepeden kamera) ya da "bottom" (yatık kamera: ayak, zemindeki çizgi)
    countAnchor: str = "center"
    # Personel üniforma renkleri (CIE Lab; §4.10 eki): bu renkteki kişinin geçişi müşteri sayılmaz. Boş = kapalı
    staffColors: list[tuple[float, float, float]] = field(default_factory=list)
    rotation: int = 0            # source.rotation (saat yönünde derece)
    referenceFps: float = 60.0   # source.referenceFps
    mmPerPixel: float | None = None  # scale.mmPerPixel (tam çözünürlük)
    qc: QCConfig = field(default_factory=QCConfig)
    io: dict[str, Any] = field(default_factory=dict)

    # --- yön yardımcıları ---
    @property
    def vertical(self) -> bool:
        return self.direction in ("down", "up")

    @property
    def sign(self) -> float:
        return 1.0 if self.direction in ("down", "right") else -1.0

    # --- JSON dönüşümü (sözleşme biçimi) ---
    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Profile:
        p = cls(name=d.get("name", "Profil"))
        simple = ["id", "linePosition", "direction", "diffThreshold", "expectedArea", "minAreaFactor",
                  "minAreaAbs", "splitTouching", "maxMultiplicity", "closeIterations", "processingWidth",
                  "minHits", "maxMatchDistance", "backgroundRate", "countMode", "productLength",
                  "detectConfidence", "countAnchor"]
        for k in simple:
            if k in d:
                setattr(p, k, d[k])
        if d.get("detectClasses"):
            p.detectClasses = [str(c) for c in d["detectClasses"]]
        if "roi" in d:
            p.roi = Roi(**d["roi"])
        if d.get("roiPolygon"):
            p.roiPolygon = [(float(pt["x"]), float(pt["y"])) for pt in d["roiPolygon"]]
        if d.get("staffColors"):
            p.staffColors = [(float(c["L"]), float(c["a"]), float(c["b"])) for c in d["staffColors"]]
        if d.get("countLine"):
            cl = d["countLine"]
            p.countLine = ((float(cl["a"]["x"]), float(cl["a"]["y"])), (float(cl["b"]["x"]), float(cl["b"]["y"])))
        src = d.get("source") or {}
        p.rotation = int(src.get("rotation", 0))
        p.referenceFps = float(src.get("referenceFps", 60.0))
        p.mmPerPixel = (d.get("scale") or {}).get("mmPerPixel")
        q = d.get("qc")
        if q:
            p.qc = QCConfig(
                enabled=q.get("enabled", False),
                geometry=GeometryQC(**(q.get("geometry") or {})),
                spots=SpotsQC(**(q.get("spots") or {})),
                barcode=CodeQC(**(q.get("barcode") or {})),
                text=CodeQC(**{k: v for k, v in (q.get("text") or {}).items() if k in ("required", "pattern")}),
                sizeClasses=[SizeClass(**s) for s in q.get("sizeClasses", [])],
                saveNokImages=q.get("saveNokImages", True),
            )
        p.io = d.get("io") or {}
        return p

    def to_dict(self) -> dict[str, Any]:
        d = {
            "schema": self.schema, "id": self.id, "name": self.name, "roi": asdict(self.roi),
            "linePosition": self.linePosition, "direction": self.direction,
            "diffThreshold": int(self.diffThreshold), "expectedArea": float(self.expectedArea),
            "minAreaFactor": self.minAreaFactor, "minAreaAbs": self.minAreaAbs,
            "splitTouching": self.splitTouching, "maxMultiplicity": self.maxMultiplicity,
            "closeIterations": self.closeIterations, "processingWidth": self.processingWidth,
            "minHits": self.minHits, "maxMatchDistance": self.maxMatchDistance,
            "backgroundRate": self.backgroundRate,
            "countMode": self.countMode, "productLength": float(self.productLength),
            **({"detectClasses": list(self.detectClasses), "detectConfidence": float(self.detectConfidence),
                "countAnchor": self.countAnchor}
               if self.countMode == "detect" else {}),
            "source": {"rotation": self.rotation, "referenceFps": self.referenceFps},
            "scale": {"mmPerPixel": self.mmPerPixel},
            "qc": asdict(self.qc),
            "io": self.io,
        }
        if self.staffColors:
            d["staffColors"] = [{"L": L, "a": a, "b": b} for L, a, b in self.staffColors]
        if self.roiPolygon:
            d["roiPolygon"] = [{"x": x, "y": y} for x, y in self.roiPolygon]
        if self.countLine:
            (ax, ay), (bx, by) = self.countLine
            d["countLine"] = {"a": {"x": ax, "y": ay}, "b": {"x": bx, "y": by}}
        return d

    def set_polygon(self, points: list[tuple[float, float]] | None) -> None:
        """Çokgeni ayarlar (§2.0; Swift `ProductProfile.setPolygon` ile aynı): köşeler [0, 1]'e kırpılır,
        roi çokgenin sınır kutusu olur (kenar en az 0,01), sayım çizgisi kutunun içine çekilir."""
        if not points:
            self.roiPolygon = None
            return
        if not 3 <= len(points) <= 12:
            raise ValueError("çokgen 3–12 köşe olmalı")
        pts = [(min(max(float(x), 0.0), 1.0), min(max(float(y), 0.0), 1.0)) for x, y in points]
        xs, ys = [x for x, _ in pts], [y for _, y in pts]
        self.roiPolygon = pts
        self.roi = Roi(min(xs), min(ys), max(max(xs) - min(xs), 0.01), max(max(ys) - min(ys), 0.01))
        lo = self.roi.y if self.vertical else self.roi.x
        hi = lo + (self.roi.height if self.vertical else self.roi.width)
        self.linePosition = min(max(self.linePosition, lo + 0.02), max(lo + 0.02, hi - 0.02))
        self.fit_count_line_to_area()

    def fit_count_line_to_area(self) -> None:
        """Açılı çizgiyi açısını ve konumunu koruyarak alanın kenarından kenarına uzatır/kısaltır (alan büyüyünce
        çizgi de büyür; Swift `fitCountLineToArea` ile aynı). Yalnızca çizimi değiştirir: sayım çizginin doğrusuna
        bağlıdır, uçlarına değil. Ortası alanın dışındaysa dokunulmaz."""
        if not self.countLine:
            return
        (ax, ay), (bx, by) = self.countLine
        r = self.roi
        pts = self.roiPolygon or [(r.x, r.y), (r.x + r.width, r.y), (r.x + r.width, r.y + r.height),
                                  (r.x, r.y + r.height)]
        mx, my = (ax + bx) / 2, (ay + by) / 2
        dx, dy = bx - ax, by - ay
        if math.hypot(dx, dy) <= 1e-9 or len(pts) < 3:
            return
        lo: float | None = None
        hi: float | None = None
        for i, (px, py) in enumerate(pts):
            qx, qy = pts[(i + 1) % len(pts)]
            ex, ey = qx - px, qy - py
            den = dx * ey - dy * ex
            if abs(den) < 1e-12:
                continue
            wx, wy = px - mx, py - my
            t = (wx * ey - wy * ex) / den
            s = (wx * dy - wy * dx) / den
            if not 0 <= s <= 1:
                continue
            if t <= 0:
                lo = t if lo is None else max(lo, t)
            if t >= 0:
                hi = t if hi is None else min(hi, t)
        if lo is None or hi is None or hi - lo <= 1e-6:
            return
        self.countLine = ((mx + lo * dx, my + lo * dy), (mx + hi * dx, my + hi * dy))

    # --- hazır profiller ---
    @classmethod
    def egg(cls) -> Profile:
        return cls(name="Yumurta", diffThreshold=28, minAreaFactor=0.35, minAreaAbs=0.0008,
                   splitTouching=True, maxMultiplicity=6, closeIterations=0, processingWidth=240,
                   maxMatchDistance=0.10)

    @classmethod
    def flour_sack(cls) -> Profile:
        # Torbalar tek sıra, çoğu zaman bitişik/üst üste: şerit tarama (§4.9); leke ayarları "blob"a geçilirse diye
        return cls(name="Un torbası", roi=Roi(0.05, 0.05, 0.9, 0.9), diffThreshold=22, minAreaFactor=0.45,
                   minAreaAbs=0.01, splitTouching=True, maxMultiplicity=3, closeIterations=2,
                   processingWidth=240, maxMatchDistance=0.20, countMode="linescan")

    @classmethod
    def people(cls) -> Profile:
        """Kişi sayımı (kapı/giriş): iki yönlü geçiş; sayım yönü = giriş."""
        return cls(name="Kişi sayımı", roi=Roi(0.0, 0.0, 1.0, 1.0), countMode="detect", detectClasses=["person"],
                   linePosition=0.55, direction="down", minHits=3, maxMatchDistance=0.15, processingWidth=640)

    @classmethod
    def vehicles(cls) -> Profile:
        return cls(name="Araç sayımı", roi=Roi(0.0, 0.0, 1.0, 1.0), countMode="detect",
                   detectClasses=["car", "truck", "bus", "motorcycle", "bicycle"],
                   linePosition=0.55, direction="down", minHits=3, maxMatchDistance=0.2, processingWidth=640)

    @classmethod
    def animals(cls) -> Profile:
        return cls(name="Hayvan sayımı", roi=Roi(0.0, 0.0, 1.0, 1.0), countMode="detect",
                   detectClasses=["cow", "sheep", "horse", "dog", "cat", "bird"],
                   linePosition=0.55, direction="down", minHits=3, maxMatchDistance=0.15, processingWidth=640)

    @classmethod
    def box(cls) -> Profile:
        return cls(name="Koli / kutu", roi=Roi(0.05, 0.05, 0.9, 0.9), diffThreshold=22, minAreaFactor=0.45,
                   minAreaAbs=0.01, splitTouching=True, maxMultiplicity=3, closeIterations=2,
                   processingWidth=240, maxMatchDistance=0.20, countMode="linescan")
