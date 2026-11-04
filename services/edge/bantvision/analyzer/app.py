"""Video analiz sunucusu (FastAPI) — docs/13-web-platform.md, sözleşme: contracts/analysis-job.schema.json.

Çalıştırma: `python -m bantvision.analyzer` (ortam: ANALYZER_DATA_DIR, ANALYZER_RETENTION_DAYS, ANALYZER_MAX_UPLOAD_MB,
ANALYZER_TOKEN, ANALYZER_CORS_ORIGINS, ANALYZER_FFMPEG). ANALYZER_TOKEN yokken yalnızca bu bilgisayarla konuşur: başka
ada ve başka siteden gelen tarayıcı isteğine kapalıdır (`hostcheck.py`), ağa açılmaz (`__main__.py`).
"""
from __future__ import annotations

import contextlib
import importlib.metadata
import json
import logging
import os
import pathlib
import secrets
import subprocess
import threading
import time
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal

import cv2
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from ..core import devices, gpu_load
from .hostcheck import LocalOnlyMiddleware
from .jobs import PUBLIC_FILES, VIDEO_EXTENSIONS, JobStore, Settings, Worker

_LOG = logging.getLogger(__name__)
CHUNK = 1024 * 1024
TOKEN_REFUSED = "Yetkisiz: geçerli bir erişim anahtarı gerekli."
CLEANUP_INTERVAL_S = 3600.0                     # saatte bir: saklama süresi dolan iş ve alarm kayıtları
MEDIA_TYPES = {"annotated.mp4": "video/mp4", "counts.csv": "text/csv; charset=utf-8",
               "profile.json": "application/json", "background.png": "image/png"}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoiIn(_Strict):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)


class PointIn(_Strict):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class CountLineIn(_Strict):
    a: PointIn
    b: PointIn


class OptionsIn(_Strict):
    """Sözleşmedeki `options` ile birebir (bilinmeyen alan reddedilir)."""
    preset: Literal["generic", "egg", "flour", "box", "people"] | None = None
    countMode: Literal["blob", "linescan", "detect"] | None = None
    countAnchor: Literal["center", "bottom"] | None = None
    productLength: float | None = Field(default=None, gt=0, le=2)
    truth: int | None = Field(default=None, ge=1)
    direction: Literal["down", "up", "right", "left"] | None = None
    roi: RoiIn | None = None
    roiPolygon: list[PointIn] | None = Field(default=None, min_length=3, max_length=12)
    countLine: CountLineIn | None = None
    line: float | None = Field(default=None, ge=0, le=1)
    bgRange: list[float] | None = Field(default=None, min_length=2, max_length=2)


def _bearer_bytes(token: str) -> bytes:
    """Beklenen `Authorization` başlığının baytları; hata vermez (kodlanamayan anahtar 500 değil 401 olur). Önce
    surrogateescape: POSIX'te UTF-8 olmayan ortam değeri bu biçimde gelir, süreç hangi baytlarla başladıysa onları verir ve
    istemci aynı baytları gönderince eşleşir. Kaçış aralığı dışındaki tek vekil (ör. U+D800) onda hata verir; surrogatepass
    hiçbir dizgede hata vermez. `ignore` ve `replace` kullanılmaz: anahtarı değiştirip başka değerlerin eşleşmesine yol açar."""
    value = f"Bearer {token}"
    try:
        return value.encode("utf-8", "surrogateescape")
    except UnicodeEncodeError:
        return value.encode("utf-8", "surrogatepass")


def token_matches(authorization: str | None, token: str) -> bool:
    """`Authorization` başlığı doğru anahtar mı. Baytlar karşılaştırılır: compare_digest ASCII dışı dizgede hata verirdi
    (Türkçe karakterli anahtar ya da başlık 500 olurdu). Starlette başlığı latin-1 çözer: encode("latin-1") gönderilen
    baytları geri verir; panel anahtarın UTF-8 baytlarını gönderir."""
    return bool(authorization) and secrets.compare_digest(authorization.encode("latin-1"), _bearer_bytes(token))


class ApiTokenMiddleware:
    """Anahtar kipinde `/api/` isteğini gövdesi okunmadan reddeder. FastAPI bağımlılığı (`auth`) çok parçalı gövde
    ayrıştırıldıktan sonra çalışır: anahtarsız bir istemci sunucuya bütün bir yüklemeyi okutabilirdi. Saf ASGI (akışlar
    olduğu gibi geçer). `/healthz` ve API dışı yollar değişmez; yöntem ve yol hataları da (405, 404) anahtardan sonra gelir."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (scope["type"] == "http" and scope["path"].startswith("/api/")
                and not token_matches(Headers(scope=scope).get("authorization"), self.token)):
            await JSONResponse({"detail": TOKEN_REFUSED}, status_code=401)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _git_commit() -> str:
    """Kısa git özeti: ortamda BV_COMMIT varsa o, yoksa paket klasöründe `git rev-parse --short HEAD` (hata → "?")."""
    env = os.environ.get("BV_COMMIT", "").strip()
    if env:
        return env
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=pathlib.Path(__file__).parent,
                             capture_output=True, text=True, timeout=2, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "?"
    return out or "?"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    commit = _git_commit()                                  # açılışta bir kez (Hakkında)
    started = time.monotonic()                              # çalışma süresi (durum şeridi)
    store = JobStore(settings)
    # "Video ile test" modelleri Cihaz ayarlarındaki "video" seçimiyle çalışır; her iş başında okunur (`live`
    # aşağıda kurulur, işçi ise yalnızca açılışta, lifespan'de başlar)
    worker = Worker(store, device_choice=lambda: live.device_settings.choices()["video"])
    stop_cleanup = threading.Event()

    def cleanup_loop() -> None:
        while not stop_cleanup.wait(CLEANUP_INTERVAL_S):
            # iki iş ayrı korunur: biri patlarsa diğeri yine denenir ve döngü (iş parçacığı) ölmez
            for name, task in (("iş kayıtları", store.expire),
                               ("silinen işler", store.retry_removals),
                               ("alarm günlüğü", lambda: live.alarms.expire(time.time()))):
                try:
                    task()
                except Exception:  # noqa: BLE001
                    _LOG.exception("Saatlik temizlik başarısız: %s", name)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        store.sweep_orphans()                                # silmesi bitememiş iş klasörleri
        store.expire()
        try:                                                 # 7 günden eski alarm ve resimler açılışta da silinir
            live.alarms.expire(time.time())
        except Exception:  # noqa: BLE001 — temizlik hatası açılışı durdurmaz
            _LOG.exception("Açılışta alarm günlüğü temizlenemedi")
        worker.start()
        live.notifier.start()                                # Telegram çevrimdışı kuyruğu
        live.restore_watched()                               # güvenlik kameraları yeniden izlemede (hata fırlatmaz)
        t = threading.Thread(target=cleanup_loop, name="analiz-temizlik", daemon=True)
        t.start()
        yield
        stop_cleanup.set()
        live.stop_background()                               # kilitli watch.json denemesi kapanıştan sonra oturum açmasın
        live.mosaics.stop()                                  # birleşik izleme akışları (okuyuculardan önce)
        live.viewers.stop()                                  # izleme okuyucuları (kameralar bırakılır)
        worker.stop()
        sessions = list(live.sessions.values())
        # İzlenen güvenlik kameraları listesi (watch.json) korunur: sonraki açılışta yeniden açılırlar
        for s in sessions:                                   # canlı oturumlar kapanırken kamerayı bırak
            s.stop()
        for s in sessions:                                   # açık alarmların sonu yazılır (günlükte açık kalmasın)
            live.close_alarms(s.id)
        live.clips.stop()                                    # durdurulan oturumların kayıtları yazılsın (en çok 60 sn)
        live.notifier.stop()
        if gpu_sampler is not None:
            gpu_sampler.close()                              # PDH sorgusu

    # Erişim anahtarı tanımlıyken anahtarsız açık tek uç /healthz kalır: API belge sayfaları (/docs, /redoc) ve şema
    # (/openapi.json) sunulmaz. Anahtarsız (yerel geliştirme) açıktır, ama yalnızca bu bilgisayardan (aşağıda
    # LocalOnlyMiddleware).
    no_docs: dict[str, Any] = {"docs_url": None, "redoc_url": None, "openapi_url": None} if settings.token else {}
    app = FastAPI(title="BantVision analiz sunucusu", version="1", lifespan=lifespan, **no_docs)
    app.state.store, app.state.worker, app.state.settings = store, worker, settings

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        """FastAPI'nin varsayılan 422'si her hatada girilen değeri (`input`) yankılar: aşırı uzun/yanlış türde bir
        Telegram anahtarı ya da kamera şifresi yanıt gövdesinde geri dönerdi. Aynı biçim (`detail` listesi: type, loc,
        msg); `input`, `ctx` ve `url` düşer. Panel yalnızca `type` ve `loc`'u okur."""
        errors = [{k: v for k, v in e.items() if k not in ("input", "ctx", "url")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    # Anahtar denetimi CORS'un İÇİNDE (önce eklenir: son eklenen en dıştadır): listedeki sitenin ön uçuşu anahtar göndermez,
    # CORS yanıtlar; 401 de CORS başlığı taşır, site nedenini okuyabilir.
    if settings.token:
        app.add_middleware(ApiTokenMiddleware, token=settings.token)
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"],
                           allow_headers=["*"])
    # Anahtarsız kipte Host ve başka site denetimi (hostcheck.py): /healthz ve belge sayfaları dahil her istek. CORS'tan
    # SONRA eklenir: Starlette'de son eklenen ara katman en dıştadır, yani yabancı addan ya da listede olmayan siteden
    # gelen CORS ön uçuşu (OPTIONS) da CORS'un yanıtını değil 403'ü alır. Anahtar tanımlıyken bu denetimler yok (anahtar
    # korur).
    if not settings.token:
        app.add_middleware(LocalOnlyMiddleware, allowed_origins=settings.cors_origins)

    def auth(authorization: Annotated[str | None, Header()] = None) -> None:
        if settings.token and not token_matches(authorization, settings.token):
            raise HTTPException(401, TOKEN_REFUSED)

    Auth = Depends(auth)

    # Canlı sayım (web paneli): ağ kamerası / kayıt cihazı → sayım (bantvision/live)
    from ..live.api import LiveManager, make_router
    from ..live.store import LiveStore

    live = LiveManager(LiveStore(settings.data_dir), settings.data_dir)
    app.state.live = live
    app.include_router(make_router(live, Auth))

    def job_or_404(job_id: str) -> dict[str, Any]:
        job = store.get(job_id)
        if job is None:
            raise HTTPException(404, "İş bulunamadı.")
        return job

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"ok": True, "retentionDays": settings.retention_days, "maxUploadMb": settings.max_upload_mb}

    psutil_missing_logged = False

    def cpu_percent() -> float | None:
        """Bilgisayarın toplam işlemci yükü; psutil kurulu değilse (güncellemeden önceki kurulum) None. psutil burada,
        ilk istekte yüklenir: eksikse sunucu yine açılır, yalnızca işlemci yükü bilinmez (uyarı günlüğe bir kez)."""
        nonlocal psutil_missing_logged
        try:
            import psutil  # bilerek geç yüklenir (yukarıdaki not)
        except ImportError:
            if not psutil_missing_logged:
                psutil_missing_logged = True
                _LOG.warning("psutil kurulu değil: işlemci yükü gösterilmez (analiz paketlerini yeniden kurun)")
            return None
        # interval=None: önceki çağrıdan bu yana ölçer; ilk çağrı 0.0 döner, sonraki yoklamalar anlamlıdır.
        return round(psutil.cpu_percent(interval=None), 1)

    gpu_sampler: gpu_load.GpuLoad | None = None
    gpu_sampler_lock = threading.Lock()
    gpu_failed_logged = False

    def gpu_status() -> dict[str, Any] | None:
        """Durum şeridi için ekran kartı: canlı algılayıcının kullandığı kart, yoksa poz modelinin, yoksa `auto` kartı
        (R12); kimlik kart listesinde yoksa ya da hiç kart yoksa None. Yük ölçülemezse `percent` None, ad yine döner.
        Örnekleyici uygulama başına tek, ilk çağrıda kurulur (PDH sorgusu süreç boyunca açık kalır)."""
        nonlocal gpu_sampler, gpu_failed_logged
        try:
            gid: str | None = None
            for model in (live.detector, live.pose):
                dev = model.status().get("device")
                if dev and dev.get("kind") == "gpu":
                    gid = dev.get("id")
                    break
            if gid is None:
                auto = devices.auto_choice()
                gid = auto if auto != devices.CPU_ID else None
            gpu = next((g for g in devices.list_gpus() if g.id == gid), None) if gid else None
            if gpu is None:
                return None
            with gpu_sampler_lock:
                if gpu_sampler is None:
                    gpu_sampler = gpu_load.GpuLoad()
                sampler = gpu_sampler
            percent = sampler.percent(gpu.luid)
            return {"name": gpu.name, "percent": None if percent is None else round(percent, 1)}
        except Exception:  # noqa: BLE001 — ekran kartı bilgisi durum ucunu düşürmez
            if not gpu_failed_logged:
                gpu_failed_logged = True
                _LOG.warning("Ekran kartı yükü durum yanıtına eklenemedi", exc_info=True)
            return None

    @app.get("/api/v1/system/status", dependencies=[Auth])
    def system_status() -> dict[str, Any]:
        # Sürüm kurulu dağıtımın adıyla okunur (pyproject.toml `name`); paket kurulu değilse "?"
        try:
            version = importlib.metadata.version("bantvision-edge")
        except importlib.metadata.PackageNotFoundError:
            version = "?"
        return {"cpuPercent": cpu_percent(), "uptimeS": int(time.monotonic() - started), "version": version,
                "commit": commit, "gpu": gpu_status()}

    @app.post("/api/v1/jobs", status_code=202, dependencies=[Auth])
    async def create_job(file: Annotated[UploadFile, File()],
                         options: Annotated[str | None, Form()] = None) -> dict[str, Any]:
        try:
            opts = OptionsIn.model_validate(json.loads(options)) if options else OptionsIn()
        except (json.JSONDecodeError, ValidationError) as e:
            raise HTTPException(422, f"Seçenekler geçersiz: {e}") from e
        name = pathlib.Path(file.filename or "video").name
        suffix = pathlib.Path(name).suffix.lower()
        if suffix not in VIDEO_EXTENSIONS:
            raise HTTPException(415, f"Desteklenmeyen dosya türü: {suffix or 'uzantısız'}. "
                                     f"Kabul edilenler: {', '.join(sorted(VIDEO_EXTENSIONS))}")
        job, dest = store.create(name, 1, opts.model_dump(exclude_none=True), suffix)
        limit = settings.max_upload_mb * CHUNK
        size = 0
        try:
            with dest.open("wb") as fh:
                while chunk := await file.read(CHUNK):
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(413, f"Video çok büyük (en fazla {settings.max_upload_mb} MB).")
                    fh.write(chunk)
            if size == 0:
                raise HTTPException(400, "Dosya boş.")
            if not _is_readable_video(dest):
                raise HTTPException(400, "Video okunamadı: dosya bozuk ya da desteklenmeyen kodlama.")
        except HTTPException:
            store.delete(job["id"])
            raise
        job["video"]["sizeBytes"] = size
        store.save(job)
        worker.submit(job["id"])
        return job

    @app.get("/api/v1/jobs", dependencies=[Auth])
    def list_jobs() -> list[dict[str, Any]]:
        return store.list()

    @app.get("/api/v1/jobs/{job_id}", dependencies=[Auth])
    def get_job(job_id: str) -> dict[str, Any]:
        return job_or_404(job_id)

    @app.get("/api/v1/jobs/{job_id}/files/{name}", dependencies=[Auth])
    def get_file(job_id: str, name: str) -> FileResponse:
        job_or_404(job_id)
        if name not in PUBLIC_FILES:
            raise HTTPException(404, "Dosya bulunamadı.")
        path = store.file(job_id, name)
        if path is None:
            raise HTTPException(404, "Dosya henüz hazır değil ya da saklama süresi doldu.")
        # FileResponse Range isteklerini destekler: tarayıcı oynatıcısı ileri/geri sarabilir.
        # Video/görsel/JSON tarayıcıda açılır; CSV indirilir.
        return FileResponse(path, media_type=MEDIA_TYPES[name], filename=name,
                            content_disposition_type="attachment" if name.endswith(".csv") else "inline")

    @app.delete("/api/v1/jobs/{job_id}", status_code=204, dependencies=[Auth])
    def delete_job(job_id: str) -> None:
        job_or_404(job_id)
        worker.delete(job_id)

    return app


def _is_readable_video(path: pathlib.Path) -> bool:
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            return False
        ok, frame = cap.read()
        return bool(ok) and frame is not None
    finally:
        cap.release()
