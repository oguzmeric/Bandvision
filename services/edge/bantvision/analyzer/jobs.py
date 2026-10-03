"""Video analiz işleri: kalıcı iş deposu, tek işçi, saklama süresi (docs/13-web-platform.md).

Her iş `data_dir/jobs/<id>/` altında: `job.json` (contracts/analysis-job.schema.json), `input.<uzantı>`, `out/`.
Analiz ayrı süreçte `python -m bantvision.video --progress-json` ile yapılır (çökme/bellek yalıtımı, iptal);
işaretli video tarayıcıda oynasın diye H.264'e (yuv420p, faststart) çevrilir.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import queue
import shutil
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

SCHEMA = "bantvision.analysis-job.v1"
RESULT_FILES = {  # video aracının çıktısı → yayımlanan ad
    "sayimlar.csv": "counts.csv",
    "profil.json": "profile.json",
    "arka_plan.png": "background.png",
}
PUBLIC_FILES = ("annotated.mp4", "counts.csv", "profile.json", "background.png")
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".3gp", ".mts", ".ts"}


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def iso(t: dt.datetime) -> str:
    return t.astimezone(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s)                  # 3.11+: "Z" doğrudan okunur


@dataclass
class Settings:
    data_dir: pathlib.Path
    retention_days: float = 7.0
    max_upload_mb: int = 2048
    token: str | None = None
    cors_origins: list[str] = field(default_factory=list)
    python: str = sys.executable
    ffmpeg: str | None = None
    out_width: int = 960

    @classmethod
    def from_env(cls) -> Settings:
        data = pathlib.Path(os.environ.get("ANALYZER_DATA_DIR", "analyzer-data")).resolve()
        cors = [o.strip() for o in os.environ.get("ANALYZER_CORS_ORIGINS", "").split(",") if o.strip()]
        return cls(
            data_dir=data,
            retention_days=float(os.environ.get("ANALYZER_RETENTION_DAYS", "7")),
            max_upload_mb=int(os.environ.get("ANALYZER_MAX_UPLOAD_MB", "2048")),
            token=os.environ.get("ANALYZER_TOKEN") or None,
            cors_origins=cors,
            ffmpeg=os.environ.get("ANALYZER_FFMPEG") or None,
        )

    def ffmpeg_exe(self) -> str:
        if self.ffmpeg:
            return self.ffmpeg
        found = shutil.which("ffmpeg")
        if found:
            return found
        import imageio_ffmpeg  # isteğe bağlı bağımlılık: sistemde ffmpeg yoksa

        return imageio_ffmpeg.get_ffmpeg_exe()


def options_to_args(options: dict[str, Any]) -> list[str]:
    """Sözleşmedeki `options` → `bantvision.video` komut satırı."""
    args: list[str] = []
    if options.get("preset"):
        args += ["--preset", options["preset"]]
    if options.get("truth"):
        args += ["--truth", str(int(options["truth"]))]
    if options.get("countMode"):
        args += ["--mode", options["countMode"]]
    if options.get("productLength"):
        args += ["--product-length", str(float(options["productLength"]))]
    if options.get("direction"):
        args += ["--direction", options["direction"]]
    roi = options.get("roi")
    if roi:
        args += ["--roi", ",".join(str(float(roi[k])) for k in ("x", "y", "width", "height"))]
    poly = options.get("roiPolygon")
    if poly:
        args += ["--roi-polygon", ";".join(f"{float(p['x'])},{float(p['y'])}" for p in poly)]
    cl = options.get("countLine")
    if cl:
        args += ["--count-line", ",".join(str(float(cl[k][c])) for k in ("a", "b") for c in ("x", "y"))]
    if options.get("line") is not None:
        args += ["--line", str(float(options["line"]))]
    bg = options.get("bgRange")
    if bg:
        args += ["--bg-range", f"{float(bg[0])},{float(bg[1])}"]
    return args


class JobStore:
    """Diskteki işler. Tüm yazmalar kilit altında ve atomik (geçici dosya + yeniden adlandırma)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.data_dir / "jobs"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def dir(self, job_id: str) -> pathlib.Path:
        uuid.UUID(job_id)  # yol enjeksiyonuna karşı: yalnızca UUID
        return self.root / job_id

    def create(self, name: str, size: int, options: dict[str, Any], suffix: str) -> tuple[dict[str, Any], pathlib.Path]:
        job_id = str(uuid.uuid4())
        t = now()
        job: dict[str, Any] = {
            "schema": SCHEMA, "id": job_id, "status": "queued",
            "createdAt": iso(t), "updatedAt": iso(t),
            "expiresAt": iso(t + dt.timedelta(days=self.settings.retention_days)),
            "video": {"name": name[:255] or "video", "sizeBytes": max(1, size)},
            "options": options, "progress": 0.0,
        }
        d = self.dir(job_id)
        (d / "out").mkdir(parents=True)
        self.save(job)
        return job, d / f"input{suffix}"

    def save(self, job: dict[str, Any]) -> None:
        with self._lock:
            job["updatedAt"] = iso(now())
            d = self.dir(job["id"])
            if not d.exists():
                return  # silinmiş
            tmp = d / "job.json.tmp"
            tmp.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, d / "job.json")

    def get(self, job_id: str) -> dict[str, Any] | None:
        try:
            p = self.dir(job_id) / "job.json"
        except ValueError:
            return None
        with self._lock:
            if not p.exists():
                return None
            return json.loads(p.read_text(encoding="utf-8"))

    def update(self, job_id: str, **changes: Any) -> dict[str, Any] | None:
        with self._lock:
            job = self.get(job_id)
            if job is None:
                return None
            job.update(changes)
            self.save(job)
            return job

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = [json.loads(p.read_text(encoding="utf-8")) for p in self.root.glob("*/job.json")]
        return sorted(jobs, key=lambda j: j["createdAt"], reverse=True)

    def delete(self, job_id: str) -> bool:
        with self._lock:
            d = self.dir(job_id)
            if not d.exists():
                return False
            shutil.rmtree(d, ignore_errors=True)
            return True

    def file(self, job_id: str, name: str) -> pathlib.Path | None:
        if name not in PUBLIC_FILES:
            return None
        p = self.dir(job_id) / "out" / name
        return p if p.is_file() else None

    def expire(self, at: dt.datetime | None = None) -> list[str]:
        """Süresi dolan işlerin dosyaları silinir, kaydı `expired` olarak kalır. Silinenlerin kimlikleri döner."""
        at = at or now()
        expired: list[str] = []
        for job in self.list():
            if job["status"] in ("queued", "running", "expired") or parse_iso(job["expiresAt"]) > at:
                continue
            d = self.dir(job["id"])
            for p in d.iterdir():
                if p.name != "job.json":
                    shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
            if job.get("result"):
                job["result"]["files"] = []
            job["status"] = "expired"
            self.save(job)
            expired.append(job["id"])
        return expired


class Worker:
    """Tek işçi (analiz CPU yoğun): kuyruktan sırayla işler; silinen iş çalışıyorsa süreci sonlandırır."""

    def __init__(self, store: JobStore, on_change: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.store = store
        self.settings = store.settings
        self.queue: queue.Queue[str] = queue.Queue()
        self._current: tuple[str, subprocess.Popen[str]] | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.on_change = on_change

    def recover(self) -> None:
        """Açılışta: kuyruktakiler yeniden sıraya, yarım kalanlar başarısız (sonuç dosyaları güvenilmez)."""
        for job in sorted(self.store.list(), key=lambda j: j["createdAt"]):
            if job["status"] == "running":
                self.store.update(job["id"], status="failed", error="Sunucu analiz sırasında yeniden başladı; videoyu yeniden yükleyin.")
            elif job["status"] == "queued":
                self.queue.put(job["id"])

    def start(self) -> None:
        self.recover()
        self._thread = threading.Thread(target=self._run, name="analiz-isci", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.queue.put("")
        self.cancel_current()

    def submit(self, job_id: str) -> None:
        self.queue.put(job_id)

    def cancel(self, job_id: str) -> None:
        with self._lock:
            if self._current and self._current[0] == job_id:
                self._current[1].kill()

    def cancel_current(self) -> None:
        with self._lock:
            if self._current:
                self._current[1].kill()

    def _run(self) -> None:
        while not self._stop.is_set():
            job_id = self.queue.get()
            if not job_id or self._stop.is_set():
                continue
            try:
                self.process(job_id)
            except Exception as e:  # noqa: BLE001 — işçi iş parçacığı ölmemeli; iş başarısız sayılır
                self.store.update(job_id, status="failed", error=f"Beklenmeyen hata: {e}")

    def _changed(self, job: dict[str, Any] | None) -> None:
        if job and self.on_change:
            self.on_change(job)

    def process(self, job_id: str) -> None:
        job = self.store.get(job_id)
        if job is None or job["status"] != "queued":
            return
        d = self.store.dir(job_id)
        inputs = [p for p in d.iterdir() if p.name.startswith("input")]
        if not inputs:
            self._changed(self.store.update(job_id, status="failed", error="Video dosyası bulunamadı."))
            return
        out = d / "out"
        raw = d / "work"
        raw.mkdir(exist_ok=True)
        self._changed(self.store.update(job_id, status="running", stage="calibrating", progress=0.0))

        cmd = [self.settings.python, "-m", "bantvision.video", str(inputs[0]), "--out", str(raw),
               "--progress-json", "--out-width", str(self.settings.out_width), *options_to_args(job["options"])]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(pathlib.Path(__file__).resolve().parents[2]),
                                                          env.get("PYTHONPATH")]))
        tail: list[str] = []
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", env=env)
        with self._lock:
            self._current = (job_id, proc)
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.strip()
                if line.startswith("{"):
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    self._on_message(job_id, msg)
                elif line:
                    tail = (tail + [line])[-8:]
            code = proc.wait()
        finally:
            with self._lock:
                self._current = None

        if self.store.get(job_id) is None:  # analiz sürerken silindi
            return
        if code != 0:
            reason = next((ln for ln in reversed(tail) if ln and not ln.startswith(" ")), "") or f"çıkış kodu {code}"
            self._changed(self.store.update(job_id, status="failed", error=f"Analiz başarısız: {reason}"))
            return

        self._changed(self.store.update(job_id, stage="encoding", progress=1.0))
        files: list[str] = []
        try:
            if (raw / "isaretli.mp4").exists():
                self._encode_h264(raw / "isaretli.mp4", out / "annotated.mp4")
                files.append("annotated.mp4")
            for src, dst in RESULT_FILES.items():
                if (raw / src).exists():
                    os.replace(raw / src, out / dst)
                    files.append(dst)
            summary = json.loads((raw / "ozet.json").read_text(encoding="utf-8"))
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as e:
            self._changed(self.store.update(job_id, status="failed", error=f"Sonuç hazırlanamadı: {e}"))
            return
        finally:
            shutil.rmtree(raw, ignore_errors=True)

        result = {
            "count": int(summary["count"]), "truth": summary.get("truth"), "errorPct": summary.get("errorPct"),
            "calibration": summary.get("calibration") or {}, "processingFps": summary.get("processingFps"),
            "files": [f for f in PUBLIC_FILES if f in files],
        }
        job = self.store.get(job_id)
        if job is None:
            return
        job["video"].update({k: v for k, v in {
            "seconds": summary.get("seconds"), "fps": summary.get("fps"),
            "width": (summary.get("size") or [None, None])[0], "height": (summary.get("size") or [None, None])[1],
        }.items() if v})
        job.update(status="done", result=result, progress=1.0)
        job.pop("stage", None)
        self.store.save(job)
        self._changed(job)
        # Girdi videosu artık gerekmez (yeniden analiz için kullanıcı yeniden yükler); yer kaplamasın
        for p in d.iterdir():
            if p.name.startswith("input"):
                p.unlink(missing_ok=True)

    def _on_message(self, job_id: str, msg: dict[str, Any]) -> None:
        if "stage" in msg:
            changes: dict[str, Any] = {"stage": msg["stage"]}
            if msg["stage"] == "calibrating":
                job = self.store.get(job_id)
                if job:
                    video = job["video"]
                    for k in ("seconds", "fps", "width", "height"):
                        if msg.get(k):
                            video[k] = msg[k]
                    changes["video"] = video
            self._changed(self.store.update(job_id, **changes))
        elif "progress" in msg:
            # Sayım ilerlemesi 0–0,95 aralığına; son %5 kodlama
            p = max(0.0, min(1.0, float(msg["progress"]))) * 0.95
            self._changed(self.store.update(job_id, progress=round(p, 4)))

    def _encode_h264(self, src: pathlib.Path, dst: pathlib.Path) -> None:
        subprocess.run([self.settings.ffmpeg_exe(), "-v", "error", "-y", "-i", str(src), "-an",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", str(dst)], check=True, capture_output=True, timeout=3600)
