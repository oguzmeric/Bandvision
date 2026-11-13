"""Canlı sayım API'si (`/api/v1/live`): kaynaklar, kanal listesi ve küçük resimler, profiller, canlı oturumlar.

Panel (apps/dashboard) bu uçlara sunucu tarafından, erişim anahtarıyla konuşur. Şifreler hiçbir yanıtta yer almaz
(`hasPassword` dışında; tam RTSP adresine yazılmış kimlik `rtsp://***@…` olarak gizlenir); hata iletileri şifre
içermez. Görüntü bu bilgisayarda kalır.
"""
from __future__ import annotations

import logging
import os
import pathlib
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Annotated, Any, ClassVar, Literal

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from starlette.concurrency import run_in_threadpool
from starlette.types import Receive, Scope, Send

from ..core import Profile, devices
from ..core.fire_model import FireModelMissing
from ..core.model_download import failure_reason
from ..core.pose_rules import COOLDOWN_S
from ..core.staff_color import MAX_COLORS, is_achromatic
from . import open_gate
from . import recorders as rec
from .alarms import AlarmStore
from .archive_player import ArchiveManager
from .clips import ClipWriter
from .devices_store import DeviceSettings, DeviceSettingsBusy
from .drafts import DraftsFull, DraftStore
from .jsonfile import quarantine, read_json, write_json_atomic
from .layouts import LAYOUTS, MAX_TILES, recorder_layout
from .mosaic import MosaicHub, MosaicStopped, TooManySizes
from .notify import NotifyError, TelegramNotifier
from .power import disable_power_throttling
from .session import ALARM_MODES, LiveSession, open_capture
from .store import CATALOG, LiveStore, make_preset
from .viewer import SourceGone, ViewHub
from .views import ViewsBusy, ViewStore, check_layout_tiles

_LOG = logging.getLogger(__name__)


class _GetHeadRoute(APIRoute):
    """Ayrı GET ve HEAD yollarına bölünmüş kaynak: başka bir yöntem 405 ve `Allow: GET, HEAD` alır. (Starlette 405'te
    eşleşen İLK yolun yöntemlerini yazar; ayrı yollarda bu yalnız "HEAD" olurdu.) GET ve HEAD aynen işlenir."""

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["method"] not in ("GET", "HEAD"):
            raise HTTPException(405, headers={"Allow": "GET, HEAD"})
        await super().handle(scope, receive, send)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StaffColorIn(_Strict):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class SourceIn(_Strict):
    kind: Literal["camera", "recorder"]
    name: str = Field(default="", max_length=80)
    # kamera
    brand: Literal["hikvision", "dahua", "axis", "vivotek", "milesight", "custom"] = "hikvision"
    host: str = Field(default="", max_length=255)
    port: int = Field(default=554, ge=1, le=65535)
    channel: int = Field(default=1, ge=1, le=512)
    substream: bool = True
    customUrl: str = Field(default="", max_length=1024)
    # kayıt cihazı
    recorderBrand: Literal["trassir", "hikvision", "dahua"] = "trassir"
    httpPort: int | None = Field(default=None, ge=1, le=65535)
    rtspPort: int | None = Field(default=None, ge=1, le=65535)
    # ortak
    username: str = Field(default="admin", max_length=128)
    password: str | None = Field(default=None, max_length=256)     # None: kayıtlı şifre korunur

    @model_validator(mode="before")
    @classmethod
    def _drop_read_only(cls, data: Any) -> Any:
        """Kaynağın kendi görünümü (kimlik, zaman, şifre var mı) geri gönderilirse yok sayılır; bilinmeyen alan yine 422."""
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if k not in ("id", "createdAt", "hasPassword")}
        return data


class StreamIn(_Strict):
    substream: bool


class NotifyIn(_Strict):
    enabled: bool = False
    chatId: str = Field(default="", max_length=64)
    token: str | None = Field(default=None, max_length=256)     # None: kayıtlı anahtar korunur, "": silinir


class TestAlarmIn(_Strict):
    sessionId: str | None = None


class FalseAlarmIn(_Strict):
    falseAlarm: bool = True                 # False: "Yanlış alarm" işareti geri alınır


class DeviceChoicesIn(_Strict):
    """Cihaz seçimleri: her biri "auto" | "cpu" | kart kimliği (`devices.valid_choice`); üçü de zorunlu."""
    detector: str
    pose: str
    video: str
    fire: str | None = None                     # verilmezse kayıtlı seçim korunur (eski istemciler)

    @field_validator("detector", "pose", "video", "fire")
    @classmethod
    def _valid(cls, v: str | None) -> str | None:
        if v is not None and not devices.valid_choice(v):
            raise ValueError("geçersiz cihaz seçimi")
        return v


class DevicesIn(_Strict):
    choices: DeviceChoicesIn


class BenchmarkIn(_Strict):
    """Hız testi tek bir cihazı ölçer: "cpu" ya da kart kimliği ("auto" değil)."""
    device: str

    @field_validator("device")
    @classmethod
    def _valid(cls, v: str) -> str:
        if v == "auto" or not devices.valid_choice(v):
            raise ValueError("geçersiz cihaz")
        return v


# Kaynak/kanal kimliği (TRASSIR GUID, kanal no, uuid): 1–120 karakter, yalnızca noktalardan oluşamaz ("." ve ".." yok).
# pydantic'in düzenli ifade motoru bakış-ileri (?!...) desteklemez; aynı kural bu biçimle ve `max_length` ile ifade edilir.
_REF = r"^\.*[A-Za-z0-9_:{}-][A-Za-z0-9._:{}-]*$"


class TileIn(_Strict):
    sourceId: str = Field(pattern=_REF, max_length=120)
    channelId: str | None = Field(default=None, pattern=_REF, max_length=120)


class ViewIn(_Strict):
    name: str = Field(max_length=60)
    layout: str = Field(max_length=5)
    tiles: list[TileIn | None] = Field(max_length=MAX_TILES)


class DraftIn(_Strict):
    layout: str = Field(max_length=5)
    tiles: list[TileIn | None] = Field(max_length=MAX_TILES)


class ViewOrderIn(_Strict):
    ids: list[Annotated[str, Field(max_length=128)]] = Field(max_length=1000)


class FromRecorderIn(_Strict):
    sourceId: str = Field(pattern=_REF, max_length=120)


class _ClosingStream(StreamingResponse):
    """Yanıt bitince — istemci koptuğunda da — gövde üreticisi HEMEN kapatılır (`finally` çalışır). Starlette kopuşta
    üreticiyi kapatmaz, kapanış çöp toplayıcıya kalır: birleşik akışta abonelik `SUB_TTL_S` (10 sn) sürer, eski şablonun
    birleştiricisi okuyuculara dokunmaya devam eder ve şablon değiştirilen duvarda yeni kutular o süre "Sınır aşıldı"
    görür. Üretici zaman uyumsuz olmalı (`aclose`)."""

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            aclose = getattr(self.body_iterator, "aclose", None)
            if aclose is not None:
                await aclose()


def _part(jpeg: bytes) -> bytes:
    """MJPEG akışının bir parçası (`multipart/x-mixed-replace; boundary=frame`)."""
    return (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode()
            + b"\r\n\r\n" + jpeg + b"\r\n")


def _load_detector(choice: str) -> Any:
    from ..core.detector import ObjectDetector

    return ObjectDetector(device=choice)


def _load_pose_estimator(choice: str) -> Any:
    from ..core.pose import PoseEstimator

    return PoseEstimator(device=choice)


def _load_fire_detector(choice: str) -> Any:
    from ..core.fire_model import FireDetector

    return FireDetector(device=choice)


def _bench_detector(choice: str) -> Any:
    """Hız testi için taze tanıma modeli (ortak canlı modelden bağımsız; test bitince bırakılır)."""
    from ..core.detector import ObjectDetector

    return ObjectDetector(device=choice)


class SharedModel:
    """Tüm canlı kameralarda tek model (bellek bir kez); kareler sırayla işlenir (işlemci aşırı yüklenmez; N kamera varsa
    her biri toplam hızın yaklaşık 1/N'ini alır).

    Model (indirme dahil) ARKA PLAN iş parçacığında yüklenir (`warm()` ya da ilk kullanım): o sürece çağrılar engellemeden
    "sonuç yok" döner (oturumların görüntüsü ve durdurma/silme takılmaz). Çıkarım kilidi yükleme sırasında tutulmaz.
    Yükleme hatasında Türkçe hata günlüğe yazılır ve `RETRY_S` saniye yeniden denenmez. `state` / `error` HİZMET
    sağlığıdır (güvenlik izleme sağlığı buna bakar): `state` "loading" | "ready" | "error"; "error" yalnızca hizmette
    model yokken; `error`: o durumdaki yükleme hatası (Türkçe, kullanıcıya gösterilir).

    Cihaz seçimi (`set_choice`; "auto" | "cpu" | kart kimliği, "auto" yükleme anında donanıma göre çözülür): model hiç
    yüklenmediyse yalnızca seçim saklanır. Yüklüyse yeni model arka planda kurulurken ESKİ model hizmete devam eder; hazır
    olunca `_infer` altında değiştirilir (güvenlik alarmı boşluk yaşamaz; süren çıkarım bitmeden değişmez). Yükleme
    sürerken seçim yeniden değişirse biten sonuç atılır ve son seçim yüklenir. Değişim yüklemesi başarısızsa eski model
    hizmette kalır (`state` "ready" kalır), hata ayrıca tutulur (`status()` notu) ve `RETRY_S` sonra (ya da yeni bir
    seçimde hemen) yeni seçimle yeniden denenir; hizmetteki modelin seçimine geri dönülürse hata silinir. `status()`:
    Cihaz ayarları sayfasının gördüğü durum."""

    RETRY_S = 60.0
    LABEL = "Model"                                     # hata iletisinde: "<LABEL> yüklenemedi: <neden>"
    THREAD = "model"

    def __init__(self, loader: Callable[[str], Any], clock: Callable[[], float] = time.monotonic,
                 choice: str = "cpu") -> None:
        self._loader, self._clock = loader, clock
        self._lock = threading.Lock()                   # durum ve yükleme iş parçacığı
        self._infer = threading.Lock()                  # kareler sırayla işlenir; model değişimi de bunun altında
        self._inner: Any = None                         # bir kez kurulunca None'a dönmez (yalnızca değiştirilir)
        self._inner_choice: str | None = None           # `_inner`'ın kurulduğu seçim
        self._choice = choice                           # istenen seçim
        self._state = "loading"
        self._error = ""
        self._swap_error = ""                           # eski model hizmetteyken yeni seçimin yükleme hatası
        self._failed_at = 0.0
        self._loading = False                           # yükleme iş parçacığı sürüyor (bitiş kararı `_lock` altında)
        self._ever_started = False
        self._thread: threading.Thread | None = None

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def error(self) -> str:
        """Hizmette model yokkenki son yükleme hatası (Türkçe); hata yoksa boş."""
        with self._lock:
            return self._error

    @property
    def choice(self) -> str:
        """İstenen cihaz seçimi (hizmetteki modelinki farklı olabilir: değişim sürüyor ya da başarısız oldu)."""
        with self._lock:
            return self._choice

    @property
    def ever_started(self) -> bool:
        """Yükleme hiç başladı mı (başlamadıysa `status()` "idle")."""
        with self._lock:
            return self._ever_started

    def warm(self) -> None:
        """Modeli şimdiden yüklemeye başlar (oturum açılınca; ilk kişiyi/kareyi beklemeden). Engellemez; model hazırsa,
        yükleniyorsa ya da hata sonrası bekleme süresindeyse bir şey yapmaz."""
        self._start_loading()

    def set_choice(self, choice: str) -> None:
        """Cihaz seçimini değiştirir (aynı seçim: bir şey yapmaz). Model hiç yüklenmediyse yalnızca saklanır; yüklüyse ya
        da yükleniyorsa yeni seçim arka planda yüklenir (hata sonrası bekleme süresi beklenmez: kullanıcı yeni seçti)."""
        with self._lock:
            if choice == self._choice:
                return
            self._choice = choice
            if not self._ever_started:
                return
        self._start_loading(force=True)

    def status(self) -> dict[str, Any]:
        """Cihaz ayarları sayfası için: `state` "idle" (hiç yüklenmedi) | "loading" (ilk yükleme ya da cihaz değişimi
        sürüyor) | "ready" | "error"; `device` hizmetteki modelin cihazı ({id, kind, name}; değişim sürerken eskisi), model
        yoksa None; `note` hizmetteki modelin düşüş notu (N1–N4), değişim başarısızsa "Seçilen cihaza geçilemedi…",
        hizmette model yokken ya da iç oturum kalıcı olarak bozulduysa ("error") Türkçe hata iletisi."""
        with self._lock:
            if not self._ever_started:
                return {"state": "idle", "device": None, "note": None}
            inner = self._inner
            if inner is None:
                if self._state == "error":
                    return {"state": "error", "device": None, "note": self._error}
                return {"state": "loading", "device": None, "note": None}
            state = "loading" if self._loading else "ready"
            swap_error = "" if self._loading else self._swap_error
        broken = getattr(inner, "broken", None)
        if broken:
            return {"state": "error", "device": None, "note": str(broken)}
        used = getattr(inner, "used", None)
        device = None if used is None else {"id": used.id, "kind": used.kind, "name": used.name}
        note = None if used is None else used.note
        if swap_error:
            note = f"Seçilen cihaza geçilemedi: {swap_error}; önceki cihazda çalışmaya devam ediyor."
        return {"state": state, "device": device, "note": note}

    def _ready(self) -> Any:
        """Hazır model ya da None (o zaman yükleme başlatılır). Seçim hizmetteki modelinkinden farklıysa (başarısız
        değişim) yükleme yeniden denenir; bekleme süresine `_start_loading` bakar."""
        inner = self._inner
        if inner is None or self._inner_choice != self._choice:
            self._start_loading()
        return inner

    def _start_loading(self, force: bool = False) -> None:
        with self._lock:
            if self._inner is not None and self._inner_choice == self._choice:
                self._swap_error = ""                   # hizmetteki modelin seçimine dönüldü: değişim hatası geçersiz
                return                                  # (okuyucu `_inner`'ı None görüp kilide gelene dek yükleme bitmiş olabilir)
            if self._loading:
                return                                  # süren yükleme bitmeden seçimi yeniden okur
            failed = self._state == "error" or bool(self._swap_error)
            if not force and failed and self._clock() - self._failed_at < self.RETRY_S:
                return
            self._ever_started = True
            if self._inner is None:
                self._state = "loading"                 # değişimde eski model hizmette: `state` "ready" kalır
            self._loading = True
            self._thread = threading.Thread(target=self._load, name=self.THREAD, daemon=True)
            self._thread.start()

    def _failure(self, e: BaseException) -> str:
        """Yükleme hatasının kullanıcıya gösterilecek Türkçe iletisi."""
        return f"{self.LABEL} yüklenemedi: {failure_reason(e)}"

    def _log_level(self, e: BaseException) -> int:
        """Yükleme hatasının günlük düzeyi (yükleme iş parçacığından çağrılır). Varsayılan ERROR; beklenen durumlar
        (ör. yangın/duman modeli kurulu değil) alt sınıfta daha düşük olabilir."""
        return logging.ERROR

    def _load(self) -> None:
        """Yükleme iş parçacığı. Beklenmedik bir çıkışta (ör. `BaseException`) `_loading` takılı kalmaz: hata günlüğe
        yazılır ve yükleme hatası gibi işlenir (RETRY_S sonra yeniden denenir)."""
        try:
            self._load_loop()
        except BaseException as e:  # noqa: BLE001 — iş parçacığının sonu: durum tutarlı kalsın, ayrıntı günlükte
            msg = self._failure(e)
            _LOG.log(self._log_level(e), "%s [%s: %s]", msg, type(e).__name__, e, exc_info=True)
            with self._lock:
                self._loading, self._failed_at = False, self._clock()
                if self._inner is None:
                    self._state, self._error = "error", msg
                else:
                    self._swap_error = msg

    def _load_loop(self) -> None:
        """İstenen seçimi yükler; bu arada seçim değiştiyse sonucu atıp son seçimi yükler. Bitiş kararı `_lock` altında
        verilir: `set_choice` ile yarışta seçim değişikliği ya burada görülür ya da (`_loading` düştükten sonra) yeni bir
        yükleme başlatır."""
        while True:
            with self._lock:
                choice = self._choice
                if self._inner is not None and self._inner_choice == choice:   # hizmetteki modele geri dönüldü
                    self._state, self._error, self._swap_error, self._loading = "ready", "", "", False
                    return
            try:
                inner = self._loader(choice)
            except Exception as e:  # noqa: BLE001 — indirme/ONNX hatası: günlüğe yazılır, RETRY_S sonra yeniden denenir
                msg = self._failure(e)
                # önce günlük, sonra durum: "error" görenin günlüğü de vardır
                _LOG.log(self._log_level(e), "%s [%s: %s]", msg, type(e).__name__, e)
                with self._lock:
                    if self._choice == choice:
                        self._failed_at, self._loading = self._clock(), False
                        if self._inner is None:
                            self._state, self._error = "error", msg
                        else:
                            self._swap_error = msg      # eski model hizmette: hizmet sağlığı bozulmaz
                        return
                continue                                # bu arada seçim değişti: son seçim denenir
            with self._infer, self._lock:               # sıra hep _infer → _lock (çıkarım _lock'u tutmaz)
                if self._choice == choice:
                    old = self._inner
                    self._inner, self._inner_choice = inner, choice
                    self._state, self._error, self._swap_error, self._loading = "ready", "", "", False
                    if old is not None:
                        _LOG.info("%s yeni cihaza geçti (seçim: %s)", self.LABEL, choice)
                    return
            del inner                                   # eski seçimin sonucu hemen bırakılır (kartta oturum birikmesin)


class SharedDetector(SharedModel):
    """Ortak kişi tanıma modeli (YOLOX). Hazır değilken `detect` boş liste döner: kişi sayımı saymaz, güvenlik poz
    bakmaz (ikisi de çökmez)."""

    LABEL = "Kişi tanıma modeli"
    THREAD = "tanima-modeli"

    def __init__(self, loader: Callable[[str], Any] | None = None, clock: Callable[[], float] = time.monotonic,
                 choice: str = "cpu") -> None:
        super().__init__(loader or _load_detector, clock, choice)

    def detect(self, *args: Any, **kwargs: Any) -> Any:
        if self._ready() is None:
            return []
        with self._infer:                               # model değişimi de _infer altında: o anki model okunur
            return self._inner.detect(*args, **kwargs)


class SharedPose(SharedModel):
    """Tüm güvenlik kameralarında tek poz modeli (MoveNet). Hazır değilken `estimate` None döner (analizör o karede poza
    bakmaz)."""

    LABEL = "Poz modeli"
    THREAD = "poz-modeli"

    def __init__(self, loader: Callable[[str], Any] | None = None, clock: Callable[[], float] = time.monotonic,
                 choice: str = "cpu") -> None:
        super().__init__(loader or _load_pose_estimator, clock, choice)

    def estimate(self, *args: Any, **kwargs: Any) -> Any:
        if self._ready() is None:
            return None
        with self._infer:
            return self._inner.estimate(*args, **kwargs)


class SharedFire(SharedModel):
    """Tüm yangın/duman kameralarında tek yangın/duman modeli (YOLOX, iki sınıf). Hazır değilken `detect` boş liste
    döner (analizör o karede bir şey görmez; çökmez). Model dosyası yoksa (adres de tanımlı değilse) `state` "error",
    `error` "Yangın/duman modeli kurulu değil."; `RETRY_S` sonra yeniden denenir: dosya sonradan kurulunca kareler
    modeli yeniden dener (oturum `_after_fire_frame`) ve analiz kendiliğinden başlar."""

    LABEL = "Yangın/duman modeli"
    THREAD = "yangin-modeli"

    def __init__(self, loader: Callable[[str], Any] | None = None, clock: Callable[[], float] = time.monotonic,
                 choice: str = "cpu") -> None:
        super().__init__(loader or _load_fire_detector, clock, choice)
        self._missing_logged: str | None = None         # son WARNING'lenen "kurulu değil" iletisi (tekrarı DEBUG)

    def _failure(self, e: BaseException) -> str:
        if isinstance(e, FireModelMissing):
            return str(e)
        return super()._failure(e)

    def _log_level(self, e: BaseException) -> int:
        """Model dosyası kurulu değil beklenen bir durumdur (kullanıcı henüz kurmadı): ilk kez WARNING, aynı iletiyle
        tekrarları (dakikada bir yeniden deneme) DEBUG. Diğer hatalar ERROR."""
        if isinstance(e, FireModelMissing):
            first = self._missing_logged != str(e)
            self._missing_logged = str(e)
            return logging.WARNING if first else logging.DEBUG
        self._missing_logged = None
        return logging.ERROR

    def detect(self, *args: Any, **kwargs: Any) -> Any:
        if self._ready() is None:
            return []
        with self._infer:
            return self._inner.detect(*args, **kwargs)


class SessionIn(_Strict):
    sourceId: str
    channelId: str | None = None
    profileId: str
    substream: bool | None = None           # None: kaynağın ayarı; True alt akış (hızlı), False ana akış (net)


class ActionIn(_Strict):
    action: Literal["start", "stop", "reset", "learnBackground", "learnSample", "cancelCalibration"]


class NotSafetyProfile(LookupError):
    """Geri yüklemede: kameranın çözülen profili artık alarm yöntemi (güvenlik/yangın) değil (kayıt listeden çıkar)."""


def _err(e: Exception) -> HTTPException:
    """Kayıt cihazı / kamera hatası → her zaman 502 (iletisi Türkçe, şifresiz). Cihazın şifre reddi (`unauthorized`,
    "Kullanıcı adı ya da şifre hatalı.") de 502'dir, 401 değil: analiz sunucusunun tek 401'i kendi erişim anahtarı
    denetimi (analyzer/app.py `auth`), 403'leri yalnızca anahtarsız kipin Host ve başka site denetimidir
    (analyzer/hostcheck.py). Tek istisna: cihazın desteklemediği iş (`unsupported`, ör. dışa aktarma) 501."""
    if isinstance(e, rec.RecorderError) and e.kind == "unsupported":
        return HTTPException(501, str(e))
    if isinstance(e, rec.RecorderError):
        return HTTPException(502, str(e))
    return HTTPException(502, f"Kaynağa ulaşılamadı: {e}")


class LiveManager:
    """Kaynak bağlantıları ve çalışan oturumlar (süreç ömrü boyunca bellekte). Güvenlik ve yangın/duman oturumları
    ayrıca `<data>/live/watch.json`'da tutulur: analiz sunucusu yeniden başlayınca `restore_watched()` onları yeniden açar
    (kuyumcu, bilgisayar yeniden başlayınca alarmın sürmesini bekler). Diğer oturumlar saklanmaz."""

    def __init__(self, store: LiveStore, data_dir: pathlib.Path | None = None) -> None:
        self.store = store
        self.sessions: dict[str, LiveSession] = {}
        self._clients: dict[str, tuple[str, rec.RecorderClient]] = {}   # kaynak → (ayar imzası, istemci)
        self._channels: dict[str, list[rec.RecorderChannel]] = {}
        self._lock = threading.Lock()
        self._snap_failed: dict[str, float] = {}         # küçük resmi alınamayan kamera → zaman (1 dk tekrar denenmez)
        # Alt akışı görüntü vermeyen kayıt cihazı kanalları → işaret anı (tekdüze); DEAD_SUB_RETRY_S sonra alt yeniden denenir
        self._dead_sub: dict[tuple[str, str], float] = {}
        # Kaynak kuşağı: `forget` (düzenle/sil) artırır. Eski ayarla açılmış okuyucu/oturum (kuşağı eski) kanalı
        # işaretleyemez; düzenlemeden sonra eski bağlantının yeniden işaretlemesi yarışı olmaz.
        self._source_gen: dict[str, int] = {}
        self._dead_lock = threading.Lock()
        root = data_dir or store.root.parent
        # Cihaz ayarları (<data>/devices.json): ortak modeller hiçbiri ısınmadan önce kayıtlı seçimi alır ("auto" yükleme
        # anında donanıma göre çözülür); "video" seçimini analiz işçisi her iş başında okur
        self.device_settings = DeviceSettings(root)
        choices = self.device_settings.choices()
        self.detector = SharedDetector()
        self.detector.set_choice(choices["detector"])
        self.pose = SharedPose()
        self.pose.set_choice(choices["pose"])
        self.fire = SharedFire()
        self.fire.set_choice(choices["fire"])
        self.make_bench_detector: Callable[[str], Any] = _bench_detector   # hız testi modeli (testlerde sahte)
        self._bench_lock = threading.Lock()                 # aynı anda tek hız testi
        self._devices_lock = threading.Lock()               # devices.json kaydı/yeniden okuması + modellere uygulanması
        self.alarms = AlarmStore(root)
        self.views = ViewStore(root)
        self.viewers = ViewHub(self._view_opener, self._session_for)
        self.drafts = DraftStore()                         # kaydedilmemiş şablonlar: yalnızca bellekte
        self.mosaics = MosaicHub(lambda vid: self.drafts.get(vid) or self.views.get(vid), self.viewers)
        # Kayıttan izleme: analyzer/app.py kurar (kaynak istemcisi `recorder` önbelleğinden), lifespan kapanışta durdurur
        self.archive: ArchiveManager | None = None
        self._drafts_stop = threading.Event()
        self._drafts_reaper: threading.Thread | None = None
        self.clips = ClipWriter(self.alarms)               # olay kayıtları arka planda yazılır (oturumlar beklemez)
        self.notifier = TelegramNotifier(store, self.alarms, root)
        # Güvenlik/yangın alarmı: `on_alarm` birden çok oturum iş parçacığından gelir; iki tablo bu kilitle korunur
        self._alarm_lock = threading.Lock()
        self._last_sent: dict[tuple[str, str], float] = {}         # (kamera, tür) → son bildirim (time.monotonic)
        self._alarm_of: dict[tuple[str, int, str], str] = {}      # (oturum, iz, tür) → açık alarm kimliği
        # Açılışta hiçbir oturum yok: önceki çalışmadan "devam ediyor" kalmış alarmlar (temiz kapanış olmadı) kapanır;
        # geri yüklenen oturumlar yeni bölüm/alarm üretir.
        closed = self.alarms.close_stale(time.time())
        if closed:
            _LOG.info("Önceki çalışmadan açık kalan %d alarm kapatıldı", closed)
        lost = self.alarms.clear_clip_pending()             # yazılırken kapanmış kayıtlar: "alınamadı"
        if lost:
            _LOG.warning("Önceki çalışmada yazılamadan kalan %d olay kaydı alınamadı olarak işaretlendi", lost)
        self._watch_file = root / "live" / "watch.json"
        self._watch_lock = threading.Lock()
        # watch.json açılışta okunamadıysa (Windows kilidi): liste boş başlar, dosyaya dokunulmaz; bu arada yapılan
        # değişiklikler sırayla tutulur ve dosya okunabilince diskteki listeye uygulanıp yazılır (izlenenler kaybolmaz)
        self._watch_unread = False
        self._watch_ops: list[tuple[str, Any]] = []
        self._restore_pending = False                       # geri yükleme kilitli dosyayla çalıştı: okununca yinele
        self._watch_dirty = False                           # son watch.json yazımı başarısız: aynı liste de yazılsın
        self._watch_stop = threading.Event()                # kapanış: kilitli dosya denemesi durur, oturum açmaz
        self._watch: list[dict[str, Any]] = self._load_watch()
        disable_power_throttling()          # canlı sayım gerçek zamanlı: Windows verimlilik modu kare hızını 2–3'e düşürüyordu

    # ------------------------------------------------------------------ poz güvenlik alarmları

    WATCH_RETRY_S: ClassVar[float] = 5.0               # kilitli watch.json bu aralıkla yeniden okunur
    WATCH_RETRY_MAX: ClassVar[int] = 360                # en çok 30 dakika

    _TITLES: ClassVar[dict[str, str]] = {
        "hands_up": "🚨 ELLER YUKARI", "lying": "🚨 YERDE YATAN KİŞİ", "test": "🧪 DENEME ALARMI",
        "fire": "🔥 YANGIN", "smoke": "💨 DUMAN"}
    # alarm türü → onu üreten yöntem (uçuştaki alarm: oturum o yöntemden çıktıysa kayıt hemen kapanır)
    _MODE_OF: ClassVar[dict[str, str]] = {"hands_up": "safety", "lying": "safety", "fire": "fire", "smoke": "fire"}
    _CHECK_LINE: ClassVar[str] = "Görüntüyü hemen kontrol edin."

    def _text(self, kind: str, camera: str, ts: float) -> str:
        text = f"{self._TITLES[kind]} — {camera} · {time.strftime('%d.%m.%Y %H:%M:%S', time.localtime(ts))}"
        return f"{text}\n{self._CHECK_LINE}" if self._MODE_OF.get(kind) == "fire" else text

    @classmethod
    def _send_image(cls, profile: Any, kind: str) -> bool:
        """Telegram'a resim gitsin mi: alarm türünün bloğundaki `sendImage` (yangın/duman → `fire`, diğerleri →
        `safety`)."""
        block = getattr(profile, "fire" if cls._MODE_OF.get(kind) == "fire" else "safety", None)
        return bool(block is not None and getattr(block, "sendImage", False))

    def on_alarm(self, s: Any, fired: list[Any], ended: list[tuple[int, str, bool]],
                 jpeg: bytes | None, raw_jpeg: bytes | None = None) -> list[str]:
        """Oturumdan (poz güvenlik ya da yangın/duman): biten bölümler (endedAt) ve doğan alarmlar (kayıt + bildirim);
        yeni alarm kayıtlarının kimlikleri
        döner (oturum bunlar için olay kaydı yakalar; aynı karedekiler tek kaydı paylaşır). Biten önce işlenir: aynı karede
        aynı (iz, tür) için eski bölümün sonu ile yeni alarm gelirse eski kapanır, yeni açık kalır; yeni alarm aynı
        anahtarda hâlâ açık eski bir alarmın üstüne yazmaz (önce onu kapatır). Tekrar önleme (kamera ve tür başına
        `COOLDOWN_S`, tekdüze saatle) denetim-ve-işaretleme tek kilit altında: eşzamanlı oturumlar çift bildirmez.
        Oturum bu sırada alarmı üreten yöntemden çıkmışsa (uçuştaki alarm) kayıt tutulur ve hemen kapatılır; açık
        kalmaz. Olay resmi HER ZAMAN bu bilgisayarda saklanır (7 gün); Telegram'a resim yalnızca kamerada ilgili bloğun
        (`safety` ya da `fire`) `sendImage`'ı açıksa gider (kuyruk kaydının resim bayrağı alarm anındakine eşittir).
        `raw_jpeg`: çizimsiz alarm karesi (yalnız yangın/duman verir); yalnızca bu bilgisayarda saklanır, yanlış alarmda zor
        örneğe eğitim karesi olarak kopyalanır; hiçbir yere gönderilmez."""
        now = time.time()                                   # alarm zamanları duvar saati
        mono = time.monotonic()                             # yalnız tekrar önleme süresi
        camera = getattr(s, "name", "Kamera")
        clip_pending = bool(getattr(s, "records_clips", False))   # oturum bu alarmların kaydını yakalayacak
        cam_key = f"{getattr(s, 'source_id', '')}|{getattr(s, 'channel_id', '') or ''}"
        new_ids: list[str] = []
        try:
            self._register(s, fired, ended, jpeg, now, mono, camera, clip_pending, cam_key, new_ids, raw_jpeg)
        except BaseException:
            # kayıt eklendikten sonra hata: oturum kimlikleri alamaz, kaydı yakalayamaz — "yazılıyor" asılı kalmasın
            if new_ids:
                self.alarms.clip_failed(new_ids)
            raise
        return new_ids

    on_safety = on_alarm                                    # eski ad (poz güvenlik)

    def _register(self, s: Any, fired: list[Any], ended: list[tuple[int, str, bool]], jpeg: bytes | None, now: float,
                  mono: float, camera: str, clip_pending: bool, cam_key: str, new_ids: list[str],
                  raw_jpeg: bytes | None = None) -> None:
        """`on_alarm`'ın kilitli gövdesi; eklenen alarm kimlikleri `new_ids`'e yazılır (hata olsa da)."""
        with self._alarm_lock:
            mode = getattr(s.profile, "countMode", "safety")
            for tid, kind, _was_fired in ended:
                aid = self._alarm_of.pop((s.id, tid, kind), None)
                if aid:
                    self.alarms.end(aid, now)
            for a in fired:
                in_mode = mode == self._MODE_OF.get(a.kind, "safety")   # oturum hâlâ bu alarmın yönteminde
                notify = "disabled"
                if self.notifier.configured():
                    last = self._last_sent.get((cam_key, a.kind))
                    notify = "suppressed" if last is not None and mono - last < COOLDOWN_S else "queued"
                rec_ = self.alarms.add(s.id, camera, a.kind, now - (a.ts - a.started), now, jpeg, notify,
                                       clip_pending=clip_pending and in_mode,
                                       source_id=getattr(s, "source_id", None) or None,
                                       channel_id=getattr(s, "channel_id", None) or None,
                                       raw_jpeg=raw_jpeg)
                new_ids.append(rec_["id"])
                old = self._alarm_of.pop((s.id, a.track_id, a.kind), None)
                if old:
                    self.alarms.end(old, now)
                if in_mode:
                    self._alarm_of[(s.id, a.track_id, a.kind)] = rec_["id"]
                else:
                    self.alarms.end(rec_["id"], now)
                if notify == "queued":
                    self._last_sent[(cam_key, a.kind)] = mono
                    self.notifier.enqueue(rec_["id"], self._text(a.kind, camera, now),
                                          jpeg if self._send_image(s.profile, a.kind) else None)

    def close_alarms(self, session_id: str, now: float | None = None) -> None:
        """Oturumun açık alarmlarının sonunu yazar (oturum silindi/durdu, yöntem değişti, sunucu kapanıyor)."""
        ts = time.time() if now is None else now
        with self._alarm_lock:
            mine = [k for k in self._alarm_of if k[0] == session_id]
            for k in mine:
                self.alarms.end(self._alarm_of.pop(k), ts)

    def remove_session(self, s: LiveSession) -> None:
        """Oturumu durdurur, listeden çıkarır, açık alarmlarını kapatır; güvenlik/yangın oturumuysa izleme listesinden çıkar
        (kullanıcı kapattı: yeniden başlatmada açılmaz). Sunucu kapanışı bunu çağırmaz: liste korunur."""
        s.stop()
        self.sessions.pop(s.id, None)
        self.close_alarms(s.id)
        self.unwatch(getattr(s, "source_id", ""), getattr(s, "channel_id", None))

    # ------------------------------------------------------------------ oturum açma ve yeniden başlatmada geri yükleme

    def open_session(self, source_id: str, channel_id: str | None, profile_id: str, substream: bool | None = None,
                     *, name: str | None = None, fallback: Profile | None = None, lazy: bool = False,
                     safety_only: bool = False) -> LiveSession:
        """Kameranın canlı oturumunu açar (`POST /sessions` ve geri yükleme aynı yoldan). Profil: bu kameraya
        kaydedilmiş ayar ya da şablon. Aynı kamerada açık oturum kapanır (kamera iki kez okunmaz).

        Geri yükleme için: `name` kayıttaki ad (kayıt cihazına sorulmaz); `fallback` kayıttaki güvenlik/yangın profili
        (kaydedilmeden o yönteme geçilmişse); `lazy` kanal bilgisi açılışta istenmez, okuyucu bağlanırken ister ve
        olmazsa yeniden dener (kayıt cihazı bilgisayardan geç açılabilir; açılış beklemez); `safety_only` çözülen profil
        bir alarm yöntemi (güvenlik/yangın) değilse `NotSafetyProfile`. Kayıttaki profil kullanılırsa adı da korunur (şablonun adı yazılmaz)."""
        src = self.source_or_404(source_id)
        template = self.store.profile(profile_id)
        profile = self.store.camera_profile(source_id, channel_id, profile_id) or template  # kamera ayarı ya da şablon
        from_snapshot = (fallback is not None and fallback.countMode in ALARM_MODES
                         and (profile is None or profile.countMode != fallback.countMode))
        if from_snapshot:
            profile = fallback                               # kaydedilmeden o yönteme geçilmişti: çalışan profil (adıyla)
        if profile is None or (template is None and fallback is None):
            raise HTTPException(404, "Profil bulunamadı.")
        if safety_only and profile.countMode not in ALARM_MODES:
            raise NotSafetyProfile("profil güvenlik/yangın değil")
        if template is not None and not from_snapshot:
            profile.name = template.name                     # yeniden adlandırma kamera ayarlarına da yansısın
        for s in list(self.sessions.values()):              # aynı kamera iki kez açılmasın
            if getattr(s, "source_id", None) == source_id and getattr(s, "channel_id", None) == channel_id:
                self.remove_session(s)
        try:
            open_url, keep_alive = self.opener(src, channel_id, substream, lazy=lazy)
            if name is None:
                name = str(src.get("name") or "").strip() or "Kamera"
                if channel_id:
                    name = f"{name} · {self.channel(src, channel_id).title.strip()}"
        except rec.RecorderError as e:
            raise _err(e) from e
        s = LiveSession(name, open_url, profile, keep_alive, detector=self.detector, pose=self.pose, fire=self.fire,
                        alarm_sink=self.on_alarm, clip_sink=self.clips.submit, clip_state=self.clips.state)
        s.loop_file = os.environ.get("ANALYZER_ALLOW_FILE_SOURCES") == "1"   # yalnızca test: dosya başa sarar
        s.source_id, s.channel_id, s.profile_id = source_id, channel_id, profile_id  # type: ignore[attr-defined]
        fixed_url = src["kind"] == "camera" and src.get("brand") == "custom"      # tam RTSP adresi: seçim yok
        sub = bool(src.get("substream", True)) if substream is None else substream
        s.substream = None if fixed_url else sub  # type: ignore[attr-defined]
        self.sessions[s.id] = s
        if profile.countMode in ALARM_MODES:
            self.watch(s)
        return s

    @staticmethod
    def _valid_watch(data: Any) -> list[dict[str, Any]]:
        return [r for r in (data or []) if isinstance(r, dict) and isinstance(r.get("sourceId"), str)
                and isinstance(r.get("profileId"), str) and (r.get("channelId") is None or isinstance(r["channelId"], str))]

    def _load_watch(self) -> list[dict[str, Any]]:
        res = read_json(self._watch_file)
        if res.status == "unreadable":
            _LOG.error("watch.json okunamadı (dosya kilitli olabilir); dosyaya dokunulmadı — okunabilince izlenen "
                       "güvenlik kameraları yeniden açılacak")
            self._watch_unread = True
            return []
        if res.status == "corrupt" or (res.status == "ok" and not isinstance(res.data, list)):
            _LOG.warning("watch.json bozuk; kenara alındı (watch.json.corrupt), izlenen kamera listesi boş başlıyor")
            quarantine(self._watch_file)
            return []
        return self._valid_watch(res.data)

    @staticmethod
    def _apply_watch(records: list[dict[str, Any]], op: tuple[str, Any]) -> list[dict[str, Any]]:
        kind, arg = op
        if kind == "set":
            key = (arg["sourceId"], arg.get("channelId"))
            return [r for r in records if (r["sourceId"], r.get("channelId")) != key] + [arg]
        if kind == "del":
            return [r for r in records if (r["sourceId"], r.get("channelId")) != arg]
        return [r for r in records if r["sourceId"] != arg]          # "del_source"

    def _change_watch(self, op: tuple[str, Any]) -> None:
        """Kilit altında: değişikliği listeye uygular ve yazar. Dosya açılışta okunamadıysa değişiklik ayrıca sıraya
        alınır: diskteki liste okunabilince aynı sırayla ona uygulanır."""
        before = self._watch
        self._watch = self._apply_watch(self._watch, op)
        if self._watch_unread:
            self._watch_ops.append(op)
        elif self._watch == before and not self._watch_dirty:
            return                                          # değişiklik yok ve dosya güncel
        self._save_watch()

    def _merge_watch_disk(self) -> bool:
        """Kilit altında: açılışta okunamayan watch.json'u yeniden okur; bu arada yapılan değişiklikleri diskteki
        listeye uygular. Hâlâ okunamıyorsa False (yazılmaz)."""
        res = read_json(self._watch_file, delays=())
        if res.status == "unreadable":
            return False
        disk = self._valid_watch(res.data) if res.status == "ok" and isinstance(res.data, list) else []
        if res.status == "corrupt":
            quarantine(self._watch_file)
        for op in self._watch_ops:
            disk = self._apply_watch(disk, op)
        self._watch, self._watch_ops, self._watch_unread = disk, [], False
        _LOG.info("watch.json yeniden okundu; izlenen güvenlik kameraları listesi birleştirildi (%d kamera)", len(disk))
        return True

    def _save_watch(self) -> None:
        """Kilit altında çağrılır; yazma hatası günlüğe yazılır (liste bellekte sürer). Dosya açılışta okunamadıysa ve
        hâlâ okunamıyorsa yazılmaz (önceden izlenen kameralar ezilmesin)."""
        if self._watch_unread and not self._merge_watch_disk():
            _LOG.warning("watch.json hâlâ okunamıyor; izlenen kameralar silinmesin diye yazma ertelendi")
            return
        try:
            write_json_atomic(self._watch_file, self._watch, indent=2)
            self._watch_dirty = False
        except OSError as e:
            self._watch_dirty = True                        # sonraki izleme/bırakma (aynı liste de olsa) yeniden yazar
            _LOG.warning("watch.json yazılamadı: %s", e)

    def watch(self, s: LiveSession) -> None:
        """Güvenlik/yangın oturumunu izleme listesine yazar ya da günceller (yeniden başlatmada açılsın)."""
        sid, ch = getattr(s, "source_id", None), getattr(s, "channel_id", None)
        if not sid:
            return
        rec_ = {"sourceId": sid, "channelId": ch, "profileId": getattr(s, "profile_id", None) or s.profile.id,
                "substream": getattr(s, "substream", None), "name": s.name, "profile": s.profile.to_dict()}
        with self._watch_lock:
            self._change_watch(("set", rec_))

    def unwatch(self, source_id: str, channel_id: str | None) -> None:
        with self._watch_lock:
            self._change_watch(("del", (source_id, channel_id)))

    def unwatch_source(self, source_id: str) -> None:
        with self._watch_lock:
            self._change_watch(("del_source", source_id))

    def _retry_watch(self) -> None:
        """Arka planda: kilitli watch.json okunabilene dek `WATCH_RETRY_S`'de bir dener (en çok `WATCH_RETRY_MAX`
        kez); okununca listeyi birleştirip yazar ve açılışta açılamayan kameraları açar (açık olanlara dokunmaz)."""
        for _ in range(self.WATCH_RETRY_MAX):
            if self._watch_stop.wait(self.WATCH_RETRY_S):
                return                                      # sunucu kapanıyor
            with self._watch_lock:
                if self._watch_unread and not self._merge_watch_disk():
                    continue
                self._save_watch()                          # birleşik liste (varsa ertelenen değişikliklerle)
                records = list(self._watch) if self._restore_pending else []
                self._restore_pending = False
            open_ = {(getattr(x, "source_id", None), getattr(x, "channel_id", None)) for x in list(self.sessions.values())}
            todo = [r for r in records if (r["sourceId"], r.get("channelId")) not in open_]
            if todo and not self._watch_stop.is_set():
                self._restore(todo)
            return
        _LOG.error("watch.json %d denemede okunamadı; izlenen güvenlik kameraları yeniden açılmadı", self.WATCH_RETRY_MAX)

    def restore_watched(self) -> int:
        """Açılışta (lifespan) izlenen güvenlik kameralarını yeniden açar; açılan sayısını döndürür. Hiçbir koşulda
        hata fırlatmaz: bir kaydın hatası (kaynak/profil yok, beklenmeyen hata) Türkçe günlüğe yazılır, diğerleri ve
        sunucunun açılışı sürer. Kaynağı silinmiş, profili artık güvenlik olmayan ya da profil anlık görüntüsü bozuk
        kayıt listeden çıkar. watch.json kilitliyse dosya okunabilince bir kez daha denenir (arka planda)."""
        with self._watch_lock:
            records = list(self._watch)
            locked = self._watch_unread
            self._restore_pending = locked
        if locked:
            threading.Thread(target=self._retry_watch, name="izleme-listesi", daemon=True).start()
        return self._restore(records)

    def stop_background(self) -> None:
        """Sunucu kapanırken: kilitli watch.json denemesi durur (kapanıştan sonra oturum açmaz)."""
        self._watch_stop.set()
        self._drafts_stop.set()

    def ensure_drafts_reaper(self) -> None:
        """Taslak ilk açılınca başlar: boşta kalan taslakları (10 dk) siler."""
        with self._lock:
            if self._drafts_reaper is not None or self._drafts_stop.is_set():
                return
            self._drafts_reaper = threading.Thread(target=self._reap_drafts, name="taslak-temizlik", daemon=True)
            self._drafts_reaper.start()

    def _reap_drafts(self) -> None:
        while not self._drafts_stop.wait(30.0):
            try:
                self.drafts.sweep()
            except Exception:  # noqa: BLE001 — temizlik iş parçacığı ölmesin
                _LOG.exception("Taslak temizliği başarısız")

    def _restore(self, records: list[dict[str, Any]]) -> int:
        restored = 0
        for r in records:
            if self._watch_stop.is_set():
                break
            label = str(r.get("name") or r.get("sourceId"))
            try:
                if self.store.source(r["sourceId"]) is None:
                    _LOG.warning("İzlenen güvenlik kamerasının kaynağı silinmiş; listeden çıkarıldı: %s", label)
                    self.unwatch(r["sourceId"], r.get("channelId"))
                    continue
                try:
                    fallback = Profile.from_dict(r["profile"]) if isinstance(r.get("profile"), dict) else None
                except (KeyError, TypeError, ValueError, AttributeError) as e:
                    _LOG.warning("İzlenen güvenlik kamerasının kaydı bozuk; listeden çıkarıldı: %s (%s: %s)",
                                 label, type(e).__name__, e)
                    self.unwatch(r["sourceId"], r.get("channelId"))
                    continue
                sub = r.get("substream")
                self.open_session(r["sourceId"], r.get("channelId"), r["profileId"],
                                  sub if isinstance(sub, bool) else None, name=str(r.get("name") or "") or None,
                                  fallback=fallback, lazy=True, safety_only=True)
                restored += 1
            except NotSafetyProfile:
                _LOG.warning("İzlenen kameranın profili artık güvenlik/yangın değil; listeden çıkarıldı: %s", label)
                self.unwatch(r["sourceId"], r.get("channelId"))
            except HTTPException as e:
                _LOG.error("Güvenlik kamerası yeniden açılamadı (%s): %s", label, e.detail)
            except Exception:  # noqa: BLE001 — bir kaydın hatası diğerlerini ve açılışı durdurmaz
                _LOG.exception("Güvenlik kamerası yeniden açılamadı (%s)", label)
        if restored:
            _LOG.info("%d güvenlik kamerası yeniden izlemeye alındı", restored)
        return restored

    def source_or_404(self, source_id: str) -> dict[str, Any]:
        src = self.store.source(source_id)
        if src is None:
            raise HTTPException(404, "Kaynak bulunamadı.")
        return src

    def recorder(self, src: dict[str, Any]) -> rec.RecorderClient:
        brand = rec.RecorderBrand(src.get("recorderBrand", "trassir"))
        host = rec.clean_host(src.get("host", ""))
        if not host:
            raise HTTPException(400, "Kayıt cihazının adresi boş.")
        http_port = int(src.get("httpPort") or brand.default_http_port)
        rtsp_port = int(src.get("rtspPort") or brand.default_rtsp_port)
        password = self.store.password(src["id"]) if src.get("id") else src.get("password", "")
        sig = f"{brand}|{host}|{http_port}|{rtsp_port}|{src.get('username', '')}|{hash(password)}"
        with self._lock:
            cached = self._clients.get(src.get("id", ""))
            if cached and cached[0] == sig:
                return cached[1]
            if cached:
                cached[1].close()
            client = rec.make_recorder(brand, host, http_port, rtsp_port, src.get("username", ""), password)
            if src.get("id"):
                self._clients[src["id"]] = (sig, client)
            return client

    def forget(self, source_id: str) -> None:
        with self._lock:
            cached = self._clients.pop(source_id, None)
            self._channels.pop(source_id, None)
        with self._dead_lock:                                # ayar değişti: alt akış yeniden denensin
            for k in [k for k in self._dead_sub if k[0] == source_id]:
                del self._dead_sub[k]
            self._source_gen[source_id] = self._source_gen.get(source_id, 0) + 1
        if cached:
            cached[1].close()
        if self.archive is not None:                        # kayıttan izleme: oynatıcılar, kanal listesi, önbellek
            self.archive.forget(source_id)

    def channels(self, src: dict[str, Any], refresh: bool = False) -> list[rec.RecorderChannel]:
        sid = src["id"]
        if refresh:                                         # "Yenile": küçük resimler de yeniden denensin
            self._snap_failed = {k: v for k, v in self._snap_failed.items() if not k.startswith(f"{sid}|")}
        if not refresh and sid in self._channels:
            return self._channels[sid]
        chans = self.recorder(src).channels()
        self._channels[sid] = chans
        return chans

    def channel(self, src: dict[str, Any], channel_id: str) -> rec.RecorderChannel:
        for refresh in (False, True):
            for c in self.channels(src, refresh):
                if c.id == channel_id:
                    return c
        raise HTTPException(404, "Kamera kayıt cihazında bulunamadı.")

    def camera_name(self, source_id: str, channel_id: str | None,
                    sources: dict[str, dict[str, Any]] | None = None) -> str:
        """Kutu etiketi: kaynak adı (+ kanal adı). Ağa çıkmaz: kanal adı önbellekte yoksa kanal kimliği yazılır.
        `sources`: istek başına bir kez okunmuş kaynak tablosu (verilmezse depo okunur)."""
        src = self.store.source(source_id) if sources is None else sources.get(source_id)
        if src is None:
            return "Silinmiş kamera"
        name = str(src.get("name") or "").strip() or "Kamera"
        if not channel_id:
            return name
        for c in self._channels.get(source_id, []):
            if c.id == channel_id:
                return f"{name} · {c.title.strip()}"
        return f"{name} · {channel_id}"

    def mark_sub_dead(self, source_id: str, channel_id: str, gen: int | None = None) -> None:
        """Kanalın alt akışı görüntü vermiyor (ana akış veriyor): DEAD_SUB_RETRY_S boyunca izleme, oturum ve küçük
        resim ana akışı kullanır. Kanal yeni işaretlendiyse günlüğe bir kez yazılır (adres/jeton yazılmaz). `gen`:
        üreticinin açıldığı kaynak kuşağı; kaynak o zamandan beri düzenlendiyse işaret yok sayılır."""
        with self._dead_lock:
            if gen is not None and gen != self._source_gen.get(source_id, 0):
                return
            fresh = not self._sub_dead_locked(source_id, channel_id)
            self._dead_sub[(source_id, channel_id)] = time.monotonic()
        if fresh:
            _LOG.info("Alt akış görüntü vermiyor, ana akışa geçildi: %s/%s",
                      self._source_label(source_id), self._channel_label(source_id, channel_id))

    def source_gen(self, source_id: str) -> int:
        """Kaynak kuşağı (`forget` artırır): üretici/küçük resim açılırken alınır, işaretlerken karşılaştırılır."""
        with self._dead_lock:
            return self._source_gen.get(source_id, 0)

    def sub_dead(self, source_id: str, channel_id: str | None) -> bool:
        if not channel_id:
            return False
        with self._dead_lock:
            return self._sub_dead_locked(source_id, channel_id)

    def _sub_dead_locked(self, source_id: str, channel_id: str) -> bool:
        at = self._dead_sub.get((source_id, channel_id))
        if at is None:
            return False
        if time.monotonic() - at >= DEAD_SUB_RETRY_S:        # süre doldu: alt akış yeniden denenir
            del self._dead_sub[(source_id, channel_id)]
            return False
        return True

    def _source_label(self, source_id: str) -> str:
        src = self.store.source(source_id)
        return str((src or {}).get("name") or "").strip() or source_id[:8]

    def _channel_label(self, source_id: str, channel_id: str) -> str:
        for c in self._channels.get(source_id, []):
            if c.id == channel_id:
                return c.title.strip() or channel_id
        return channel_id

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

    def camera_url(self, src: dict[str, Any]) -> str:
        custom = str(src.get("customUrl", "")).strip()
        if (src.get("brand") == "custom" and os.environ.get("ANALYZER_ALLOW_FILE_SOURCES") == "1"
                and custom and pathlib.Path(custom).is_file()):
            return custom                                   # yalnızca test: yerel video dosyası "kamera" gibi
        url = rec.camera_rtsp_url(rec.CameraBrand(src.get("brand", "hikvision")), rec.clean_host(src.get("host", "")),
                                  int(src.get("port", 554)), int(src.get("channel", 1)), bool(src.get("substream", True)),
                                  src.get("customUrl", ""))
        if not url:
            raise HTTPException(400, "Kamera adresi eksik ya da geçersiz.")
        password = self.store.password(src["id"])
        return rec.with_credentials(url, src.get("username", ""), password) if src.get("username") else url

    def opener(self, src: dict[str, Any], channel_id: str | None, substream: bool | None = None,
               lazy: bool = False) -> tuple[Any, Any]:
        """(adres üretici, canlı tutma). Kayıt cihazında adres her bağlanışta yeniden alınır (TRASSIR jetonu).
        `substream` verilirse kaynağın alt/ana akış ayarı yerine o kullanılır (oturum başına seçim). `lazy`: kanal
        bilgisi şimdi değil ilk bağlanışta istenir (alınamazsa okuyucu yeniden dener). Kayıt cihazında üretici
        `open_gate.StreamUrl`: alt akışı ölü işaretli kanalda (`sub_dead`, her bağlanışta sorulur) ana akış verir;
        okuyucu/oturum alt akış 0 kare verince `prefer_main` ile ana akışı dener ve kare gelirse kanalı işaretler."""
        if substream is not None:
            src = {**src, "substream": substream}
        if src["kind"] == "camera":
            url = self.camera_url(src)
            return (lambda: url), None
        if not channel_id:
            raise HTTPException(400, "Kayıt cihazından bir kamera seçin.")
        client = self.recorder(src)
        found: list[rec.RecorderChannel] = [] if lazy else [self.channel(src, channel_id)]
        substream = bool(src.get("substream", True))
        brand = rec.RecorderBrand(src.get("recorderBrand", "trassir"))
        username, password = src.get("username", ""), self.store.password(src["id"])

        sid = str(src.get("id") or "")

        def make(sub: bool) -> tuple[str, bool]:
            if not found:
                found.append(self.channel(src, channel_id))
            url = client.stream_url(found[0], sub)
            if brand != rec.RecorderBrand.TRASSIR and username:
                url = rec.with_credentials(url, username, password)
            return url, found[0].has_substream

        if not sid:                                         # kaydedilmemiş kaynak: bellek yok, düz üretici
            return (lambda: make(substream)[0]), client.keep_alive
        gen = self.source_gen(sid)
        streams = open_gate.StreamUrl(make, substream, lambda: self.sub_dead(sid, channel_id),
                                      lambda: self.mark_sub_dead(sid, channel_id, gen))
        return streams, client.keep_alive

    def snapshot(self, src: dict[str, Any], channel_id: str | None) -> bytes:
        key = f"{src['id']}|{channel_id}"
        if time.monotonic() - self._snap_failed.get(key, -1e9) < SNAPSHOT_RETRY_S:
            raise HTTPException(502, "Kameradan görüntü gelmiyor (kapalı ya da sinyal yok).")
        try:
            jpeg = self._snapshot(src, channel_id)
        except HTTPException:
            self._snap_failed[key] = time.monotonic()
            raise
        self._snap_failed.pop(key, None)
        return jpeg

    def _snapshot(self, src: dict[str, Any], channel_id: str | None) -> bytes:
        if src["kind"] == "recorder" and channel_id:
            sid = str(src.get("id") or "")
            gen = self.source_gen(sid)                      # istek sürerken kaynak düzenlenirse işaretlemez
            client = self.recorder(src)
            ch = self.channel(src, channel_id)
            # Alt akıştan alınan küçük resim yanıt vermezse (zaman aşımı / bağlantı: `unreachable`) bir kez ana akış
            # denenir (bazı kanallarda alt akış ölü); ana akış verirse kanal işaretlenir. Cihazın reddi (HTTP hata
            # kodu, JPEG değil, şifre) düşürmez. Tek bir geçici zaman aşımı da kanalı 10 dk işaretleyebilir (kabul:
            # ana akış görüntü verir). İşaretli kanalda doğrudan ana akış; o da düşerse alt denenmez (502).
            can_fall_back = bool(sid) and getattr(client, "snapshot_uses_substream", False) and ch.has_substream
            dead = can_fall_back and self.sub_dead(sid, channel_id)
            try:
                return client.snapshot(ch, not dead) if can_fall_back else client.snapshot(ch)
            except rec.RecorderError as e:
                if e.kind == "unauthorized":
                    raise
                if not can_fall_back or dead or e.kind != "unreachable":
                    # Kayıt cihazının görüntü API'si var: alınamadıysa kamera görüntü vermiyor. RTSP'yi ayrıca denemek
                    # küçük resmi 10+ sn bekletiyordu (kapalı kanallar listeyi ve paneli tıkıyordu).
                    raise HTTPException(502, "Kameradan görüntü gelmiyor (kapalı ya da sinyal yok).") from e
            try:
                jpeg = client.snapshot(ch, False)
            except rec.RecorderError as e:
                if e.kind == "unauthorized":
                    raise
                raise HTTPException(502, "Kameradan görüntü gelmiyor (kapalı ya da sinyal yok).") from e
            self.mark_sub_dead(sid, channel_id, gen)
            return jpeg
        open_url, _ = self.opener(src, channel_id)          # küçük resim API'si yok: RTSP'den ilk kare
        return grab_jpeg(open_url())

    # ------------------------------------------------------------------ cihaz ayarları

    def _apply_device_choices(self, choices: dict[str, str]) -> None:
        """`_devices_lock` altında: canlı modellere kayıtlı (çözülmemiş) seçimi verir."""
        self.detector.set_choice(choices["detector"])
        self.pose.set_choice(choices["pose"])
        self.fire.set_choice(choices["fire"])

    def devices_view(self) -> dict[str, Any]:
        """`GET /devices` gövdesi: ekran kartı desteği, cihaz listesi (iç alanlar `index`/`luid` çıkmaz), "auto"nun o
        anki karşılığı, kayıtlı seçimler ve canlı modellerin gerçekte çalıştığı cihaz. devices.json açılışta kilitli
        olduğu için okunamadıysa burada yeniden denenir; okununca seçimleri canlı modellere uygulanır."""
        with self._devices_lock:
            fresh = self.device_settings.refresh()
            if fresh is not None:
                self._apply_device_choices(fresh)
        return self._devices_body()

    def _devices_body(self) -> dict[str, Any]:
        available, reason = devices.gpu_support()
        gpus = devices.list_gpus()
        return {
            "gpuSupport": {"available": available, "reason": reason},
            "devices": [{"id": devices.CPU_ID, "kind": "cpu", "name": devices.CPU_NAME}]
                       + [{"id": g.id, "kind": "gpu", "name": g.name, "memoryMb": g.memory_mb} for g in gpus],
            "auto": devices.auto_choice(gpus),
            "choices": self.device_settings.choices(),
            "inUse": {"detector": self.detector.status(), "pose": self.pose.status(), "fire": self.fire.status()},
        }

    def save_devices(self, choices: dict[str, str]) -> dict[str, Any]:
        """Seçimleri kaydeder, canlı modellere kayıtlı (çözülmemiş) seçimi verir; `DeviceSettingsBusy` yazılamadıysa.
        Kayıt ve uygulama tek kilit altında: üst üste gelen iki kayıtta dosya ile canlı modeller ayrışmaz. Açılışta
        okunamamış dosyanın içeriği yerine kullanıcının gönderdiği seçimler kazanır."""
        with self._devices_lock:
            saved = self.device_settings.save(choices)
            self._apply_device_choices(saved)
        return self._devices_body()

    BENCH_FRAME_SHAPE: ClassVar[tuple[int, int, int]] = (720, 1280, 3)
    BENCH_WARMUP: ClassVar[int] = 3
    BENCH_RUNS: ClassVar[int] = 20

    def benchmark(self, device: str) -> dict[str, Any]:
        """Tek cihazda hız testi: taze tanıma modeli (açılış süresi `loadS`), sabit karede 3 ısınma + 20 ölçüm
        (`msPerFrame`). Aynı anda tek test (`BenchmarkBusy`); model kurulamazsa `BenchmarkFailed` (Türkçe ileti)."""
        if not self._bench_lock.acquire(blocking=False):
            raise BenchmarkBusy("Başka bir hız testi sürüyor; bitince yeniden deneyin.")
        try:
            frame = np.random.default_rng(0).integers(0, 256, self.BENCH_FRAME_SHAPE, dtype=np.uint8)
            t0 = time.perf_counter()
            try:
                det = self.make_bench_detector(device)
            except Exception as e:  # indirme/ONNX hatası: ortak modelle aynı Türkçe ileti
                msg = f"{SharedDetector.LABEL} yüklenemedi: {failure_reason(e)}"
                _LOG.error("Hız testi: %s [%s: %s]", msg, type(e).__name__, e)
                raise BenchmarkFailed(msg) from e
            load_s = time.perf_counter() - t0
            try:
                for _ in range(self.BENCH_WARMUP):
                    det.detect(frame, ["person"])
                t1 = time.perf_counter()
                for _ in range(self.BENCH_RUNS):
                    det.detect(frame, ["person"])
                ms = (time.perf_counter() - t1) * 1000.0 / self.BENCH_RUNS
                used = det.used
            except Exception as e:  # çalışma hatası (ör. kalıcı bozuk oturum): günlükte ayrıntı
                _LOG.exception("Hız testi çalıştırılamadı (%s)", device)
                raise BenchmarkFailed("Hız testi tamamlanamadı (ayrıntı analiz sunucusunun günlüğünde).") from e
            finally:
                del det                                     # ekran kartı belleği hemen bırakılsın
            _LOG.info("Hız testi: %s → %.1f ms/kare, açılış %.1f sn", used.name, ms, load_s)
            return {"device": used.to_json(), "msPerFrame": round(ms, 1), "loadS": round(load_s, 1)}
        finally:
            self._bench_lock.release()


class BenchmarkBusy(Exception):
    """Başka bir hız testi sürüyor."""


class BenchmarkFailed(Exception):
    """Hız testi modeli kurulamadı ya da çalışmadı (ileti Türkçe, kullanıcıya gösterilir)."""


DEAD_SUB_RETRY_S = 600.0                    # alt akışı ölü işaretli kanalda alt akış 10 dk sonra yeniden denenir
SNAPSHOT_RETRY_S = 300.0                    # görüntüsü gelmeyen kamera 5 dk denenmez ("Yenile" ile hemen)
_GRAB_SLOTS = threading.BoundedSemaphore(2)   # aynı anda en çok 2 RTSP küçük resim: kayıt cihazını ve canlı oturumu boğmasın


def grab_jpeg(url: str, timeout: float = 10.0) -> bytes:
    result: dict[str, bytes] = {}
    deadline = time.monotonic() + timeout

    def run() -> None:
        if not _GRAB_SLOTS.acquire(timeout=timeout):
            return
        try:
            _grab(url, result, deadline)
        finally:
            _GRAB_SLOTS.release()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    if "jpeg" not in result:
        raise HTTPException(502, "Kameradan görüntü alınamadı (adres, port, kullanıcı ve şifreyi kontrol edin).")
    return result["jpeg"]


def _grab(url: str, result: dict[str, bytes], deadline: float = float("inf")) -> None:
    """İlk tam kare JPEG olarak `result`'a. Açılış sırası (`open_gate`) beklerken süre dolduysa (istek çoktan 502
    döndü) kimsenin beklemediği açılış yapılmaz."""
    with open_gate.GATE.hold(open_gate.VIEWER):
        if time.monotonic() > deadline:
            return
        cap = open_capture(url)
    try:
        for _ in range(30):                                 # ilk tam kareye kadar (anahtar kare)
            ok, frame = cap.read()
            if ok and frame is not None:
                ok2, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok2:
                    result["jpeg"] = buf.tobytes()
                return
    finally:
        cap.release()


def _public_channel(c: rec.RecorderChannel, sub_dead: bool = False) -> dict[str, Any]:
    """`subDead`: alt akış görüntü vermiyor, ana akış kullanılıyor (panel küçük resim altında yazar)."""
    return {"id": c.id, "name": c.name.strip(), "number": c.number, "title": c.title.strip(),
            "hasSubstream": c.has_substream, "subDead": sub_dead}


def make_router(manager: LiveManager, auth: Any) -> APIRouter:
    r = APIRouter(prefix="/api/v1/live", dependencies=[auth])
    store = manager.store

    # archive_api bu modülün yardımcılarını kullanır; burada (modül yüklendikten sonra) alınır, döngü olmaz
    from .archive_api import add_archive_routes

    add_archive_routes(r, manager)

    # ---------------------------------------------------------------- katalog ve profiller

    @r.get("/catalog")
    def catalog() -> list[dict[str, Any]]:
        return CATALOG

    @r.get("/profiles")
    def profiles() -> list[dict[str, Any]]:
        return store.profiles()

    @r.post("/profiles", status_code=201)
    def create_profile(body: dict[str, Any]) -> dict[str, Any]:
        """{"preset": "egg"} → hazır profilden yeni profil; ya da tam profil (sözleşme)."""
        if "preset" in body:
            try:
                p = make_preset(str(body["preset"]))
            except KeyError as e:
                raise HTTPException(422, "Bilinmeyen hazır profil.") from e
            if body.get("name"):
                p.name = str(body["name"])[:80]
        else:
            p = _profile_from(body)
            p.id = Profile().id                             # yeni kimlik
        p.name = _unique_name(p.name.strip() or "Profil", {x.get("name", "") for x in store.profiles()})
        return store.save_profile(p)

    @r.put("/profiles/{profile_id}")
    def update_profile(profile_id: str, body: dict[str, Any]) -> dict[str, Any]:
        if store.profile(profile_id) is None:
            raise HTTPException(404, "Profil bulunamadı.")
        p = _profile_from(body)
        p.id = profile_id
        p.name = p.name.strip()[:80]
        if not p.name:
            raise HTTPException(422, "Profil adı boş olamaz.")
        if any(x.get("name") == p.name and x.get("id") != profile_id for x in store.profiles()):
            raise HTTPException(409, "Bu adda başka bir profil var.")
        return store.save_profile(p)

    @r.delete("/profiles/{profile_id}", status_code=204)
    def delete_profile(profile_id: str) -> Response:
        if any(getattr(s, "profile_id", None) == profile_id for s in manager.sessions.values()):
            raise HTTPException(409, "Bu profille açık canlı sayım var; önce o sayımı kapatın.")
        if not store.delete_profile(profile_id):
            raise HTTPException(409, "Profil silinemedi (bulunamadı ya da son profil).")
        return Response(status_code=204)

    # ---------------------------------------------------------------- kaynaklar

    def _public_source(src: dict[str, Any]) -> dict[str, Any]:
        """Kaynağın yanıttaki hâli: tam RTSP adresindeki kullanıcı:şifre gizlenir (şifre panele/telefona gitmez)."""
        if not src.get("customUrl"):
            return src
        return {**src, "customUrl": rec.redact_credentials(str(src["customUrl"]))}

    @r.get("/sources")
    def sources() -> list[dict[str, Any]]:
        return [_public_source(s) for s in store.sources()]

    @r.post("/sources", status_code=201)
    def create_source(body: SourceIn) -> dict[str, Any]:
        data = body.model_dump(exclude={"password"})
        data["name"] = data["name"].strip()
        if not data["name"]:
            data["name"] = _default_name(data)
        return _public_source(store.save_source(data, body.password or ""))

    @r.put("/sources/{source_id}")
    def update_source(source_id: str, body: SourceIn) -> dict[str, Any]:
        cur = manager.source_or_404(source_id)
        data = body.model_dump(exclude={"password"})
        stored_url = str(cur.get("customUrl") or "")
        if stored_url and data["customUrl"] == rec.redact_credentials(stored_url):
            data["customUrl"] = stored_url                   # panel gizlenmiş adresi geri gönderdi: kayıtlı adres kalır
        data["name"] = data["name"].strip()
        if not data["name"]:
            data["name"] = _default_name(data)
        manager.forget(source_id)
        saved = store.save_source(data, body.password, source_id)
        manager.viewers.drop(source_id)                      # izleme okuyucuları eski adres/şifreyi bırakır, yenisiyle açılır
        # forget ile kayıt arasında açılan üretici eski ayarı taşır: kuşak yeniden artar (o üretici işaretleyemez) ve
        # o arada eski ayarla önbelleğe giren istemci/kanal listesi de bırakılır
        manager.forget(source_id)
        return _public_source(saved)

    @r.delete("/sources/{source_id}", status_code=204)
    def delete_source(source_id: str) -> Response:
        for s in [s for s in manager.sessions.values() if getattr(s, "source_id", None) == source_id]:
            manager.remove_session(s)
        manager.unwatch_source(source_id)                    # geri yüklenemeyen kayıtlar da
        manager.forget(source_id)
        deleted = store.delete_source(source_id)
        manager.viewers.drop(source_id)                      # silinen kameranın izleme okuyucuları kapanır
        # forget ile silme arasında başlayıp silinmiş kaydı okuyan istek önbelleğe yazamaz: dönem yeniden artar
        manager.forget(source_id)
        if not deleted:
            raise HTTPException(404, "Kaynak bulunamadı.")
        return Response(status_code=204)

    @r.get("/sources/{source_id}/channels")
    def channels(source_id: str, refresh: bool = False) -> list[dict[str, Any]]:
        src = manager.source_or_404(source_id)
        if src["kind"] != "recorder":
            raise HTTPException(400, "Bu kaynak bir kayıt cihazı değil.")
        try:
            return [_public_channel(c, manager.sub_dead(source_id, c.id)) for c in manager.channels(src, refresh)]
        except rec.RecorderError as e:
            raise _err(e) from e

    @r.get("/sources/{source_id}/snapshot")
    def snapshot(source_id: str, channel: str | None = None) -> Response:
        src = manager.source_or_404(source_id)
        try:
            jpeg = manager.snapshot(src, channel)
        except rec.RecorderError as e:
            raise _err(e) from e
        headers = {"Cache-Control": "no-store"}
        if manager.sub_dead(source_id, channel):            # panel kanal listesini yalnız bu durumda yeniden okur
            headers["X-Sub-Dead"] = "1"
        return Response(jpeg, media_type="image/jpeg", headers=headers)

    # ---------------------------------------------------------------- çoklu izleme şablonları

    @r.get("/view-layouts")
    def view_layouts() -> list[dict[str, Any]]:
        return [lay.to_dict() for lay in LAYOUTS]

    @r.get("/views")
    def views() -> list[dict[str, Any]]:
        return manager.views.list()

    # Taslaklar `/views/{view_id}` yollarından ÖNCE tanımlanır (aksi halde "drafts" bir şablon kimliği sanılır)
    @r.post("/views/drafts", status_code=201)
    def create_draft(body: DraftIn) -> dict[str, Any]:
        try:
            d = manager.drafts.create(body.layout, _tile_dicts(body.tiles))
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        except DraftsFull as e:                             # en çok MAX_DRAFTS: açık düzenleyicinin taslağı silinmez
            raise HTTPException(503, str(e)) from e
        manager.ensure_drafts_reaper()
        return d

    @r.put("/views/drafts/{draft_id}")
    def update_draft(draft_id: str, body: DraftIn) -> dict[str, Any]:
        try:
            d = manager.drafts.update(draft_id, body.layout, _tile_dicts(body.tiles))
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        if d is None:
            raise HTTPException(404, "Taslak bulunamadı.")
        return d

    @r.delete("/views/drafts/{draft_id}", status_code=204)
    def delete_draft(draft_id: str) -> Response:
        if not manager.drafts.delete(draft_id):
            raise HTTPException(404, "Taslak bulunamadı.")
        return Response(status_code=204)

    @r.post("/views")
    def create_view(body: ViewIn) -> dict[str, Any]:
        name, layout, tiles = _view_body(body)
        try:
            return manager.views.create(name, layout, tiles)
        except ViewsBusy as e:
            raise HTTPException(503, str(e)) from e

    # `/views/{view_id}`den ÖNCE: aksi halde "order" bir şablon kimliği sanılır
    @r.put("/views/order")
    def order_views(body: ViewOrderIn) -> list[dict[str, Any]]:
        try:
            return manager.views.reorder(body.ids)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
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
        """Kayıt cihazının kanallarından şablon: en çok MAX_TILES (128) kanal, sırayla; düzen `recorder_layout` (16'ya
        kadar katalogdaki en küçük düzen, üstünde kutusu en büyük N×M). Fazlası alınmaz ve bildirilir (`truncated`)."""
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
        lay = recorder_layout(len(used))
        tiles: list[dict[str, Any] | None] = [{"sourceId": src["id"], "channelId": c.id} for c in used]
        tiles += [None] * (len(lay.cells) - len(tiles))
        name = _recorder_view_name(str(src.get("name") or ""), {v["name"] for v in manager.views.list()})
        try:
            v = manager.views.create(name, lay.id, tiles)
        except ViewsBusy as e:
            raise HTTPException(503, str(e)) from e
        return {**v, "truncated": len(chans) > MAX_TILES, "channelCount": len(chans)}

    def _mjpeg(parts: Iterator[bytes]) -> StreamingResponse:
        return StreamingResponse(parts, media_type="multipart/x-mixed-replace; boundary=frame",
                                 headers={"Cache-Control": "no-store"})

    @r.get("/views/{view_id}/stream")
    def view_stream(view_id: str, w: int = Query(1280, ge=16, le=7680), h: int = Query(720, ge=16, le=4320),
                    limit: int | None = Query(None, ge=1, le=100)) -> StreamingResponse:
        """`limit`: yalnızca test/teşhis — bu kadar kareden sonra akış biter (panel kullanmaz)."""
        try:
            comp, tok = manager.mosaics.acquire(view_id, w, h)
        except (MosaicStopped, TooManySizes) as e:
            raise HTTPException(503, str(e)) from e
        except LookupError as e:
            raise HTTPException(404, "Şablon bulunamadı.") from e

        async def frames() -> AsyncIterator[bytes]:
            seq, idle, sent = 0, time.monotonic(), 0
            try:
                while limit is None or sent < limit:
                    seq2, jpeg = await run_in_threadpool(comp.jpeg, tok, seq, 2.0)
                    if comp.gone or comp.stopped:
                        return
                    if jpeg is None or seq2 == seq:
                        if time.monotonic() - idle > 60:
                            return
                        continue
                    idle, seq = time.monotonic(), seq2
                    sent += 1
                    yield _part(jpeg)
            finally:
                manager.mosaics.release(comp, tok)               # istemci kopunca da hemen (_ClosingStream)

        return _ClosingStream(frames(), media_type="multipart/x-mixed-replace; boundary=frame",
                              headers={"Cache-Control": "no-store"})

    @r.get("/views/{view_id}/status")
    def view_status(view_id: str) -> dict[str, Any]:
        view = manager.drafts.get(view_id) or manager.views.get(view_id)
        if view is None:
            raise HTTPException(404, "Şablon bulunamadı.")
        tiles: list[dict[str, Any] | None] = []
        # Kaynaklar istek başına BİR kez okunur (kutu başına iki dosya okuması değil); yalnızca sources.json (şifre
        # dosyası değil). Not: depo okunamazsa boş liste verir ("yok" ile ayırt edilemez); o durumda kutular geçici
        # olarak "Kamera silinmiş." görünür, sonraki yoklamada düzelir. Durum kare istemez (`peek` kare küçültmez).
        sources = {x["id"]: x for x in store.source_records()}
        for t in view["tiles"]:
            if not t:
                tiles.append(None)
                continue
            src_id, ch = t["sourceId"], t.get("channelId")
            gone = src_id not in sources
            tf = manager.viewers.peek(src_id, ch)
            s = manager._session_for(src_id, ch)
            tiles.append({"sourceId": src_id, "channelId": ch, "name": manager.camera_name(src_id, ch, sources),
                          "state": "error" if gone else tf.state,
                          "message": "Kamera silinmiş." if gone else tf.message, "fps": tf.fps,
                          "analysis": _analysis(manager, s) if s is not None else None})
        return {"id": view["id"], "layout": view["layout"], "tiles": tiles}

    @r.get("/cameras/stream")
    def camera_stream(source: str = Query(pattern=_REF, max_length=120),
                      channel: str | None = Query(None, pattern=_REF, max_length=120),
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
    def camera_status(source: str = Query(pattern=_REF, max_length=120),
                      channel: str | None = Query(None, pattern=_REF, max_length=120),
                      quality: Literal["sub", "main"] = "sub") -> dict[str, Any]:
        src = next((x for x in store.source_records() if x["id"] == source), None)    # şifre dosyası okunmaz
        if src is None:
            raise HTTPException(404, "Kaynak bulunamadı.")
        tf = manager.viewers.peek(source, channel, quality)
        s = manager._session_for(source, channel)
        return {"name": manager.camera_name(source, channel, {source: src}), "state": tf.state, "message": tf.message,
                "fps": tf.fps, "analysis": _analysis(manager, s) if s is not None else None}

    # ---------------------------------------------------------------- canlı oturumlar

    @r.get("/sessions")
    def sessions() -> list[dict[str, Any]]:
        return [_session_view(s) for s in manager.sessions.values()]

    @r.post("/sessions", status_code=201)
    def create_session(body: SessionIn) -> dict[str, Any]:
        """Güvenlik oturumu ayrıca izleme listesine yazılır: analiz sunucusu yeniden başlayınca yeniden açılır."""
        return _session_view(manager.open_session(body.sourceId, body.channelId, body.profileId, body.substream))

    def session_or_404(session_id: str) -> LiveSession:
        s = manager.sessions.get(session_id)
        if s is None:
            raise HTTPException(404, "Canlı oturum bulunamadı (sunucu yeniden başlatılmış olabilir).")
        return s

    @r.get("/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        return _session_view(session_or_404(session_id))

    @r.delete("/sessions/{session_id}", status_code=204)
    def delete_session(session_id: str) -> Response:
        manager.remove_session(session_or_404(session_id))
        return Response(status_code=204)

    @r.post("/sessions/{session_id}/actions")
    def action(session_id: str, body: ActionIn) -> dict[str, Any]:
        s = session_or_404(session_id)
        {"start": lambda: s.set_counting(True), "stop": lambda: s.set_counting(False), "reset": s.reset,
         "learnBackground": s.learn_background, "learnSample": s.learn_sample,
         "cancelCalibration": s.cancel_calibration}[body.action]()
        return _session_view(s)

    @r.put("/sessions/{session_id}/stream")
    def set_stream(session_id: str, body: StreamIn) -> dict[str, Any]:
        """Alt ↔ ana akış: aynı oturum yeni akışa bağlanır; sayaçlar sıfırlanmaz."""
        s = session_or_404(session_id)
        if getattr(s, "substream", None) is None:
            raise HTTPException(400, "Bu kaynakta akış seçilemez (tam RTSP adresi).")
        src = manager.source_or_404(getattr(s, "source_id", ""))
        try:
            open_url, keep_alive = manager.opener(src, getattr(s, "channel_id", None), body.substream)
        except rec.RecorderError as e:
            raise _err(e) from e
        if body.substream != s.substream:  # type: ignore[attr-defined]
            s.switch_source(open_url, keep_alive)
            s.substream = body.substream  # type: ignore[attr-defined]
            if s.profile.countMode in ALARM_MODES:
                manager.watch(s)                            # yeniden başlatmada aynı akış
        return _session_view(s)

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

    @r.put("/sessions/{session_id}/profile")
    def set_profile(session_id: str, body: dict[str, Any], save: bool = False) -> dict[str, Any]:
        """Oturumun profilini değiştirir (alan, çizgi, yön, yöntem…); `save=true` ise **bu kamera için** kaydeder
        (profil şablonu ve diğer kameralar değişmez)."""
        s = session_or_404(session_id)
        p = _profile_from(body)
        p.id = getattr(s, "profile_id", p.id)
        old_mode = s.profile.countMode
        s.set_profile(p)
        if old_mode in ALARM_MODES and p.countMode != old_mode:   # alarm yönteminden çıkış: bölümlerin sonu gelmez
            manager.close_alarms(s.id)
        if p.countMode in ALARM_MODES:                      # alarm yöntemine geçiş ya da ayar değişti: izleme güncel
            manager.watch(s)
        elif old_mode in ALARM_MODES:
            manager.unwatch(getattr(s, "source_id", ""), getattr(s, "channel_id", None))
        if save:
            store.save_camera_profile(getattr(s, "source_id", ""), getattr(s, "channel_id", None), p)
        return _session_view(s)

    @r.get("/sessions/{session_id}/stream")
    def stream(session_id: str) -> StreamingResponse:
        s = session_or_404(session_id)

        def frames() -> Iterator[bytes]:
            seq = 0
            idle = time.monotonic()
            while s.id in manager.sessions:
                seq2, jpeg = s.jpeg(seq, timeout=2.0)
                if jpeg is None or seq2 == seq:
                    if time.monotonic() - idle > 60:            # bir dakika kare yok: bağlantıyı bırak
                        return
                    continue
                idle = time.monotonic()
                seq = seq2
                yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode()
                       + b"\r\n\r\n" + jpeg + b"\r\n")

        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame",
                                 headers={"Cache-Control": "no-store"})

    @r.get("/sessions/{session_id}/frame.jpg")
    def frame(session_id: str) -> Response:
        jpeg = session_or_404(session_id).raw_jpeg()
        if jpeg is None:
            raise HTTPException(503, "Henüz görüntü yok.")
        return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @r.get("/sessions/{session_id}/counts.csv")
    def counts_csv(session_id: str) -> Response:
        s = session_or_404(session_id)
        return Response(s.counts_csv(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="sayimlar.csv"'})

    # ---------------------------------------------------------------- poz güvenlik: alarm günlüğü ve Telegram

    @r.get("/alarms")
    def alarms(active: bool = False, since: float | None = None, until: float | None = None,
               session_id: str | None = Query(None, alias="sessionId"),
               kind: Literal["hands_up", "lying", "test", "fire", "smoke"] | None = Query(None, alias="type"),
               limit: int = Query(50, ge=1, le=1000)) -> list[dict[str, Any]]:
        """Alarm günlüğü (en yeni önce, varsayılan en çok 50; Alarmlar sayfası 1000'e kadar ister). `sessionId`: yalnızca
        o kameranın alarmları — yan panel, başka kameraların alarmları yüzünden kendi alarmlarını kaçırmasın. `since` /
        `until`: alarm anı aralığı (dahil); `type`: tür."""
        return manager.alarms.list(active_only=active, since=since, until=until, session_id=session_id, kind=kind,
                                   limit=limit)

    @r.post("/alarms/test")
    def test_alarm(body: TestAlarmIn) -> dict[str, Any]:
        """Deneme alarmı: panel şeridi ve (yapılandırılmışsa) Telegram; tekrar önlemeye tabi değil. `sessionId` bir
        güvenlik/yangın oturumuysa o kameranın son karesi olay resmi olarak saklanır (o kameranın "Son alarmlar"ında
        görünür) ve ön kayıttan (son 8 sn, sonrası beklenmez) olay kaydı yazılır; Telegram'a resim yalnızca o kamerada
        yöntemin bloğundaki `sendImage` açıksa gider (kayıt hiçbir zaman gitmez)."""
        s = manager.sessions.get(body.sessionId) if body.sessionId else None
        camera = s.name if s else "Deneme"
        safety = s is not None and s.profile.countMode in ALARM_MODES
        jpeg = s.raw_jpeg() if s is not None and safety else None
        block = getattr(s.profile, s.profile.countMode, None) if s is not None and safety else None
        send_image = bool(block is not None and block.sendImage)
        now = time.time()
        notify = "queued" if manager.notifier.configured() else "disabled"
        rec_ = manager.alarms.add(s.id if s else None, camera, "test", now, now, jpeg, notify,
                                  clip_pending=bool(s is not None and safety and s.records_clips),
                                  source_id=getattr(s, "source_id", None) or None,
                                  channel_id=getattr(s, "channel_id", None) or None)
        if s is not None and safety:
            s.capture_clip([rec_["id"]], post_s=0.0, raw=True)  # yalnızca ön kayıt, iskeletsiz; yazım arka planda
        if notify == "queued":
            manager.notifier.enqueue(rec_["id"], manager._text("test", camera, now), jpeg if send_image else None)
        return rec_

    @r.post("/alarms/{alarm_id}/ack")
    def ack_alarm(alarm_id: str) -> dict[str, Any]:
        if not manager.alarms.ack(alarm_id):
            raise HTTPException(404, "Alarm bulunamadı.")
        return manager.alarms.get(alarm_id) or {}

    @r.post("/alarms/{alarm_id}/false-alarm")
    def false_alarm(alarm_id: str, body: FalseAlarmIn | None = None) -> dict[str, Any]:
        """"Yanlış alarm": kayıt `falseAlarm` ve onaylanmış olur (şeritten kalkar); kayıt ve resim saklanmaya devam eder.
        Yangın/duman alarmının resmi ve kaydı zor örnek olarak bu bilgisayarda saklanır. Gövde `{"falseAlarm": false}`
        işareti geri alır (onay kalır, zor örnek silinir); gövdesiz istek işaretler."""
        value = True if body is None else body.falseAlarm
        if not manager.alarms.set_false_alarm(alarm_id, value):
            raise HTTPException(404, "Alarm bulunamadı.")
        return manager.alarms.get(alarm_id) or {}

    def alarm_clip(alarm_id: str) -> FileResponse:
        """İhlal anının kaydı (VP8 WebM). Tarayıcının video oynatıcısı ileri/geri sarmak için `Range` ister: 206 ve
        `Content-Range` (Starlette FileResponse); kapsam dışı aralık 416. Dosya bu arada silinmişse (7 gün temizliği,
        en çok 500 sınırı) 404: dosya bilgisi burada alınır ve yanıta verilir (yanıt yeniden bakıp 500 vermez)."""
        path = manager.alarms.clip_file(alarm_id)
        try:
            st = path.stat() if path is not None else None
        except OSError:
            st = None
        if path is None or st is None:
            raise HTTPException(404, "Olay kaydı yok (hazırlanıyor, 7 günü geçti ya da alınamadı).")
        return FileResponse(path, media_type="video/webm", headers={"Cache-Control": "no-store"}, stat_result=st)

    def alarm_image(alarm_id: str) -> Response:
        jpeg = manager.alarms.image_bytes(alarm_id)
        if jpeg is None:
            raise HTTPException(404, "Olay resmi yok (7 günü geçti ya da alınamadı).")
        return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    # GET ve HEAD ayrı yollar: tek yolda iki yöntem şemada aynı işlem kimliğini alıyordu ("Duplicate Operation ID").
    # İkisi de _GetHeadRoute: başka yöntem 405 ve `Allow: GET, HEAD` alır (yalnız ilk yolun yöntemi değil).
    for path, endpoint in (("/alarms/{alarm_id}/clip.webm", alarm_clip), ("/alarms/{alarm_id}/image.jpg", alarm_image)):
        for method in ("GET", "HEAD"):
            r.add_api_route(path, endpoint, methods=[method], route_class_override=_GetHeadRoute)

    def notify_view(cfg: dict[str, Any]) -> dict[str, Any]:
        """Ayar + son gönderim hatası (`lastError`: {text, at} ya da null; Türkçe, anahtarsız; bellekte tutulur)."""
        return {**cfg, "lastError": manager.notifier.last_error()}

    @r.get("/notify")
    def get_notify() -> dict[str, Any]:
        return notify_view(store.notify_config())

    @r.put("/notify")
    def put_notify(body: NotifyIn) -> dict[str, Any]:
        old_chat = store.notify_config()["chatId"]
        try:
            cfg = store.save_notify(body.enabled, body.chatId, body.token)
        except ValueError as e:                             # biçimi geçersiz anahtar: ileti anahtarı içermez
            raise HTTPException(422, str(e)) from e
        if body.token is not None or cfg["chatId"] != old_chat:
            manager.notifier.clear_last_error()             # anahtar/sohbet değişti: eski hata artık geçerli değil
        return notify_view(cfg)

    @r.post("/notify/test")
    def notify_test() -> dict[str, Any]:
        """Telegram deneme mesajı; hata 422 ve Türkçe (anahtarsız) iletiyle döner."""
        try:
            manager.notifier.send("🧪 BantVision deneme mesajı — bildirimler çalışıyor.", None)
        except NotifyError as e:
            raise HTTPException(422, str(e)) from e
        return {"ok": True}

    # ------------------------------------------------------------------ cihaz ayarları (ekran kartı)

    @r.get("/devices")
    def get_devices() -> dict[str, Any]:
        return manager.devices_view()

    @r.put("/devices")
    def put_devices(body: DevicesIn) -> dict[str, Any]:
        """Üç seçimi kaydeder; canlı modeller boşluksuz yeni cihaza geçer (eski model yeni hazır olana dek hizmette)."""
        try:
            return manager.save_devices(body.choices.model_dump(exclude_none=True))
        except DeviceSettingsBusy as e:
            raise HTTPException(503, str(e)) from e

    @r.post("/devices/benchmark")
    def benchmark(body: BenchmarkIn) -> dict[str, Any]:
        """Tek cihazda hız testi (iş parçacığı havuzunda; saniyeler sürebilir). Aynı anda tek test: 409."""
        try:
            return manager.benchmark(body.device)
        except BenchmarkBusy as e:
            raise HTTPException(409, str(e)) from e
        except BenchmarkFailed as e:
            raise HTTPException(502, str(e)) from e

    return r


_SAFETY_RULES = {"handsUp": ("Eller yukarı", 3.0, 5.0), "lying": ("Yerde yatma", 5.0, 30.0)}   # ad, en az, en çok (sn)


def _check_safety(sf: Any) -> None:
    """`safety` bloğu (sözleşme: handsUp 3–5 sn, lying 5–30 sn, sendImage): yanlış tür ya da aralık dışı 422 olur.
    Eksik alanlar varsayılana düşer; `bool("false")` gibi sessiz dönüşümlere izin verilmez."""
    def bad(msg: str) -> HTTPException:
        return HTTPException(422, f"Güvenlik ayarı geçersiz: {msg}")

    if sf is None:
        return
    if not isinstance(sf, dict):
        raise bad("nesne olmalı.")
    for key, (title, lo, hi) in _SAFETY_RULES.items():
        if key not in sf:
            continue
        rule = sf[key]
        if not isinstance(rule, dict):
            raise bad(f"{title} ayarı nesne olmalı.")
        if "enabled" in rule and not isinstance(rule["enabled"], bool):
            raise bad(f"{title} açık/kapalı değeri doğru ya da yanlış olmalı.")
        sec = rule.get("seconds", lo)
        # aralık karşılaştırması NaN ve sonsuzu da dışlar (karşılaştırma yanlış çıkar)
        if isinstance(sec, bool) or not isinstance(sec, (int, float)) or not lo <= sec <= hi:
            raise bad(f"{title} süresi {lo:g}–{hi:g} sn arasında bir sayı olmalı.")
    if "sendImage" in sf and not isinstance(sf["sendImage"], bool):
        raise bad("olay resmi gönderimi doğru ya da yanlış olmalı.")


_FIRE_RULES = {"fire": ("Yangın", 2.0, 10.0), "smoke": ("Duman", 5.0, 30.0)}   # ad, en az, en çok (sn)
_FIRE_SENSITIVITY = ("low", "normal", "high")
_FIRE_MAX_ZONES, _FIRE_ZONE_POINTS = 8, (3, 12)


def _check_fire(fb: Any, mode: Any) -> None:
    """`fire` bloğu (sözleşme: fire 2–10 sn, smoke 5–30 sn, sensitivity low|normal|high, ignoreZones en çok 8 çokgen ×
    3–12 nokta, koordinat 0–1, sendImage): yanlış tür ya da aralık dışı 422 olur. Eksik alanlar varsayılana düşer.
    Yangın modunda (`countMode == "fire"`) iki kural birden kapatılamaz."""
    def bad(msg: str) -> HTTPException:
        return HTTPException(422, f"Yangın/duman ayarı geçersiz: {msg}")

    def number(v: Any) -> bool:
        return not isinstance(v, bool) and isinstance(v, (int, float))

    if fb is None:
        return
    if not isinstance(fb, dict):
        raise bad("nesne olmalı.")
    enabled = []
    for key, (title, lo, hi) in _FIRE_RULES.items():
        rule = fb.get(key, {})
        if not isinstance(rule, dict):
            raise bad(f"{title} ayarı nesne olmalı.")
        if "enabled" in rule and not isinstance(rule["enabled"], bool):
            raise bad(f"{title} açık/kapalı değeri doğru ya da yanlış olmalı.")
        sec = rule.get("seconds", lo)
        # aralık karşılaştırması NaN ve sonsuzu da dışlar (karşılaştırma yanlış çıkar)
        if not number(sec) or not lo <= sec <= hi:
            raise bad(f"{title} süresi {lo:g}–{hi:g} sn arasında bir sayı olmalı.")
        enabled.append(rule.get("enabled", True))
    if "sensitivity" in fb and fb["sensitivity"] not in _FIRE_SENSITIVITY:
        raise bad("hassasiyet düşük, normal ya da yüksek olmalı.")
    zones = fb.get("ignoreZones", [])
    if not isinstance(zones, list) or len(zones) > _FIRE_MAX_ZONES:
        raise bad(f"hariç bölgeler en çok {_FIRE_MAX_ZONES} çokgenden oluşan bir liste olmalı.")
    lo_n, hi_n = _FIRE_ZONE_POINTS
    for z in zones:
        if not isinstance(z, list) or not lo_n <= len(z) <= hi_n:
            raise bad(f"her hariç bölge {lo_n}–{hi_n} köşeli bir çokgen olmalı.")
        for pt in z:
            if not (isinstance(pt, list) and len(pt) == 2 and all(number(c) and 0.0 <= c <= 1.0 for c in pt)):
                raise bad("hariç bölge köşeleri 0–1 arasında [x, y] olmalı.")
    if "sendImage" in fb and not isinstance(fb["sendImage"], bool):
        raise bad("olay resmi gönderimi doğru ya da yanlış olmalı.")
    if mode == "fire" and not any(enabled):
        raise bad("En az bir kural açık olmalı.")


def _profile_from(body: dict[str, Any]) -> Profile:
    _check_safety(body.get("safety"))
    _check_fire(body.get("fire"), body.get("countMode"))
    try:
        p = Profile.from_dict(body)
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(422, f"Profil geçersiz: {e}") from e
    if len(p.staffColors) > MAX_COLORS:
        raise HTTPException(422, f"En fazla {MAX_COLORS} personel rengi öğretilebilir.")
    for L, a, b in p.staffColors:                    # sözleşme: L 0–100, a/b −128–127 (NaN da reddedilir)
        if not (0.0 <= L <= 100.0 and -128.0 <= a <= 127.0 and -128.0 <= b <= 127.0):
            raise HTTPException(422, "Personel rengi geçersiz: L 0–100, a ve b −128–127 arasında olmalı.")
    return p


_VIEW_NAME_MAX = 60
_ALL_CHANNELS = " · tüm kanallar"


def _recorder_view_name(source_name: str, taken: set[str]) -> str:
    """Kayıt cihazı şablonunun adı: "<kaynak adı> · tüm kanallar", doluysa sonuna " 2", " 3"... eklenir. Son ad en çok
    60 karakterdir ve `taken` içinde yoktur; sınıra sığmak için kaynak adı kısaltılır, ek ve sıra numarası korunur."""
    stem = source_name.strip() or "Kayıt cihazı"
    n = 1
    while True:
        tail = _ALL_CHANNELS + ("" if n == 1 else f" {n}")
        name = stem[:max(_VIEW_NAME_MAX - len(tail), 1)].rstrip() + tail
        if name not in taken:
            return name
        n += 1


def _unique_name(name: str, taken: set[str]) -> str:
    """Aynı adlı ikinci profil "Yumurta 2" olur (listede ayırt edilsin)."""
    if name not in taken:
        return name
    n = 2
    while f"{name} {n}" in taken:
        n += 1
    return f"{name} {n}"[:80]


def _view_body(body: ViewIn) -> tuple[str, str, list[dict[str, Any] | None]]:
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Şablon adı boş olamaz.")
    tiles = _tile_dicts(body.tiles)
    try:
        layout = check_layout_tiles(body.layout, tiles)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return name, layout, tiles


def _tile_dicts(tiles: list[TileIn | None]) -> list[dict[str, Any] | None]:
    return [None if t is None else {"sourceId": t.sourceId, "channelId": t.channelId} for t in tiles]


def _default_name(data: dict[str, Any]) -> str:
    host = rec.clean_host(data.get("host", "")) or "kamera"
    if data["kind"] == "recorder":
        return f"{rec.RecorderBrand(data['recorderBrand']).title} · {host}"
    return f"{data['brand'].capitalize() if data['brand'] != 'custom' else 'RTSP'} · {host}"


def _session_view(s: LiveSession) -> dict[str, Any]:
    v = s.snapshot_status()
    v.update(sourceId=getattr(s, "source_id", None), channelId=getattr(s, "channel_id", None),
             profileId=getattr(s, "profile_id", None), substream=getattr(s, "substream", None))
    return v


def _analysis(manager: LiveManager, s: LiveSession) -> dict[str, Any]:
    """Kutudaki rozet: o kamerada çalışan analizin özeti (+ onaylanmamış güvenlik/yangın alarmı)."""
    v = s.snapshot_status()
    mode = s.profile.countMode
    a: dict[str, Any] = {"mode": mode, "sessionId": s.id, "name": s.profile.name}
    if mode == "detect":
        a.update(entered=v["total"], exited=v["totalOut"])
    elif mode in ALARM_MODES:
        sf = v.get(mode) or {}
        a.update(healthy=sf.get("healthy"), reason=sf.get("reason"))
    else:
        a.update(total=v["total"])
    open_alarms = manager.alarms.list(active_only=True, session_id=s.id, limit=1)
    a["alarm"] = {"id": open_alarms[0]["id"], "type": open_alarms[0]["type"]} if open_alarms else None
    return a
