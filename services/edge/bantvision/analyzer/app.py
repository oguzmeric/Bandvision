"""Video analiz sunucusu (FastAPI) — docs/13-web-platform.md, sözleşme: contracts/analysis-job.schema.json.

Çalıştırma: `python -m bantvision.analyzer` (ortam: ANALYZER_DATA_DIR, ANALYZER_RETENTION_DAYS, ANALYZER_MAX_UPLOAD_MB,
ANALYZER_TOKEN, ANALYZER_CORS_ORIGINS, ANALYZER_FFMPEG).
"""
from __future__ import annotations

import contextlib
import json
import logging
import pathlib
import secrets
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

from .jobs import PUBLIC_FILES, VIDEO_EXTENSIONS, JobStore, Settings, Worker

_LOG = logging.getLogger(__name__)
CHUNK = 1024 * 1024
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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = JobStore(settings)
    worker = Worker(store)
    stop_cleanup = threading.Event()

    def cleanup_loop() -> None:
        while not stop_cleanup.wait(CLEANUP_INTERVAL_S):
            # iki iş ayrı korunur: biri patlarsa diğeri yine denenir ve döngü (iş parçacığı) ölmez
            for name, task in (("iş kayıtları", store.expire),
                               ("alarm günlüğü", lambda: live.alarms.expire(time.time()))):
                try:
                    task()
                except Exception:  # noqa: BLE001
                    _LOG.exception("Saatlik temizlik başarısız: %s", name)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
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
        worker.stop()
        sessions = list(live.sessions.values())
        # İzlenen güvenlik kameraları listesi (watch.json) korunur: sonraki açılışta yeniden açılırlar
        for s in sessions:                                   # canlı oturumlar kapanırken kamerayı bırak
            s.stop()
        for s in sessions:                                   # açık alarmların sonu yazılır (günlükte açık kalmasın)
            live.close_alarms(s.id)
        live.clips.stop()                                    # durdurulan oturumların kayıtları yazılsın (en çok 60 sn)
        live.notifier.stop()

    app = FastAPI(title="BantVision analiz sunucusu", version="1", lifespan=lifespan)
    app.state.store, app.state.worker, app.state.settings = store, worker, settings

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        """FastAPI'nin varsayılan 422'si her hatada girilen değeri (`input`) yankılar: aşırı uzun/yanlış türde bir
        Telegram anahtarı ya da kamera şifresi yanıt gövdesinde geri dönerdi. Aynı biçim (`detail` listesi: type, loc,
        msg); `input`, `ctx` ve `url` düşer. Panel yalnızca `type` ve `loc`'u okur."""
        errors = [{k: v for k, v in e.items() if k not in ("input", "ctx", "url")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"],
                           allow_headers=["*"])

    def auth(authorization: Annotated[str | None, Header()] = None) -> None:
        if not settings.token:
            return
        expected = f"Bearer {settings.token}"
        if not authorization or not secrets.compare_digest(authorization, expected):
            raise HTTPException(401, "Yetkisiz: geçerli bir erişim anahtarı gerekli.")

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
        worker.cancel(job_id)
        store.delete(job_id)

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
