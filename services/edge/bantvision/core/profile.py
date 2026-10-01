"""Ürün profili (contracts/product-profile.schema.json) için tipli model."""
from __future__ import annotations

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
                  "minHits", "maxMatchDistance", "backgroundRate"]
        for k in simple:
            if k in d:
                setattr(p, k, d[k])
        if "roi" in d:
            p.roi = Roi(**d["roi"])
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
            "source": {"rotation": self.rotation, "referenceFps": self.referenceFps},
            "scale": {"mmPerPixel": self.mmPerPixel},
            "qc": asdict(self.qc),
            "io": self.io,
        }
        return d

    # --- hazır profiller ---
    @classmethod
    def egg(cls) -> Profile:
        return cls(name="Yumurta", diffThreshold=28, minAreaFactor=0.35, minAreaAbs=0.0008,
                   splitTouching=True, maxMultiplicity=6, closeIterations=0, processingWidth=240,
                   maxMatchDistance=0.10)

    @classmethod
    def flour_sack(cls) -> Profile:
        return cls(name="Un torbası", roi=Roi(0.05, 0.05, 0.9, 0.9), diffThreshold=22, minAreaFactor=0.45,
                   minAreaAbs=0.01, splitTouching=True, maxMultiplicity=3, closeIterations=2,
                   processingWidth=160, maxMatchDistance=0.20)
