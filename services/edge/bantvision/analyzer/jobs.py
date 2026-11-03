"""Video analiz işleri: kalıcı iş deposu, tek işçi, saklama süresi (docs/13-web-platform.md).

Her iş `data_dir/jobs/<id>/` altında: `job.json` (contracts/analysis-job.schema.json), `input.<uzantı>`, `out/`.
Analiz ayrı süreçte `python -m bantvision.video --progress-json` ile yapılır (çökme/bellek yalıtımı, iptal);
işaretli video tarayıcıda oynasın diye H.264'e (yuv420p, faststart) çevrilir.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import logging
import os
import pathlib
import queue
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator
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
# JavaScript `String.prototype.trim`'in attığı karakterler (boşluk + satır sonu). Python'un `str.strip()`'i farklıdır
# (\x1c-\x1f ve \x85'i de atar, \ufeff'i atmaz): panelle aynı girdide aynı sonuç için açık küme (`Host` ayrıştırma, anahtar).
JS_WHITESPACE = ("\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
                 "\u2028\u2029\u202f\u205f\u3000\ufeff")
CANCEL_WAIT_S = 10.0     # öldürülen sürecin bitmesi için en çok bu kadar beklenir
REMOVE_ATTEMPTS = 20     # açık dosya silinemez (Windows): klasör kısa aralıklarla yeniden denenir (en çok ~5 sn)
REMOVE_WAIT_S = 0.25

_LOG = logging.getLogger(__name__)


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def iso(t: dt.datetime) -> str:
    return t.astimezone(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s)                  # 3.11+: "Z" doğrudan okunur


def token_from_env() -> str | None:
    """Erişim anahtarı: ANALYZER_TOKEN, çevresindeki boşluk atılmış. Sondaki boşluk yazım hatasıdır ve panel de atar (aynı
    küme: JS `trim`); atılmasaydı ekranda nedeni görünmeyen bir anahtar uyuşmazlığı olurdu. Geriye bir şey kalmazsa None
    (anahtar yok): boşluk anahtar sayılsaydı ağa açılma engeli ve Host denetimi kapanırdı."""
    return os.environ.get("ANALYZER_TOKEN", "").strip(JS_WHITESPACE) or None


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
            token=token_from_env(),
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
    if options.get("countAnchor"):
        args += ["--anchor", options["countAnchor"]]
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
        self._forgotten: set[str] = set()   # silinmiş ama klasörü henüz gitmemiş işler

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

    def save(self, job: dict[str, Any]) -> bool:
        """Kaydı yazar; iş silinmişse yazmaz (`False`), klasörü henüz gitmemiş olsa da kayıt geri gelmez."""
        with self._lock:
            job["updatedAt"] = iso(now())
            d = self.dir(job["id"])
            if job["id"] in self._forgotten or not d.exists():
                return False
            tmp = d / "job.json.tmp"
            tmp.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, d / "job.json")
            return True

    def get(self, job_id: str) -> dict[str, Any] | None:
        try:
            p = self.dir(job_id) / "job.json"
        except ValueError:
            return None
        with self._lock:
            if job_id in self._forgotten or not p.exists():
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
            jobs = [json.loads(p.read_text(encoding="utf-8")) for p in self.root.glob("*/job.json")
                    if p.parent.name not in self._forgotten]
        return sorted(jobs, key=lambda j: j["createdAt"], reverse=True)

    def forget(self, job_id: str) -> bool:
        """İş hemen silinmiş sayılır (listede yok, yazmalar geri getirmez); dosyalar `remove_files` ile gider."""
        with self._lock:
            d = self.dir(job_id)
            if not d.exists():
                return False
            self._forgotten.add(job_id)
            with contextlib.suppress(OSError):
                (d / "job.json").unlink(missing_ok=True)
            return True

    def remove_files(self, job_id: str) -> bool:
        """Klasörü siler; açık dosya varsa kısa süre yeniden dener. Bitmezse `retry_removals` ve açılış temizliği."""
        d = self.dir(job_id)
        for attempt in range(REMOVE_ATTEMPTS):
            if attempt:
                time.sleep(REMOVE_WAIT_S)
            shutil.rmtree(d, ignore_errors=True)
            if not d.exists():
                return True
        _LOG.warning("Silinen işin klasörü kaldırılamadı, sonra yeniden denenecek: %s", job_id)
        return False

    def delete(self, job_id: str) -> bool:
        if not self.forget(job_id):
            return False
        self.remove_files(job_id)
        return True

    def retry_removals(self) -> None:
        """Silinmiş ama klasörü kalmış işler için bir deneme daha (saatlik temizlik)."""
        with self._lock:
            pending = list(self._forgotten)
        for job_id in pending:
            d = self.dir(job_id)
            shutil.rmtree(d, ignore_errors=True)
            if not d.exists():
                with self._lock:
                    self._forgotten.discard(job_id)

    def sweep_orphans(self) -> list[str]:
        """Açılışta (henüz yükleme yokken): kaydı olmayan iş klasörleri kaldırılır. Silinenlerin adları döner."""
        removed: list[str] = []
        for d in self.root.iterdir():
            try:
                is_job_dir = d.is_dir() and str(uuid.UUID(d.name)) == d.name
            except ValueError:
                continue
            if is_job_dir and not (d / "job.json").exists():
                shutil.rmtree(d, ignore_errors=True)
                removed.append(d.name)
        return removed

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
    """Tek işçi (analiz CPU yoğun): kuyruktan sırayla işler; silinen iş çalışıyorsa süreci (analiz ya da ffmpeg) sonlandırır."""

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

    def delete(self, job_id: str) -> None:
        """Önce kayıt gider (işçi ölen süreci "başarısız" saymasın), sonra süreç durur, sonra dosyalar silinir."""
        self.store.forget(job_id)
        self.cancel(job_id)
        self.store.remove_files(job_id)

    def cancel(self, job_id: str) -> None:
        """Süreci durdurur ve bitmesini bekler: `kill` hemen döner, süreç bitene dek dosyaları açık kalır."""
        with self._lock:
            proc = self._current[1] if self._current and self._current[0] == job_id else None
            if proc:
                proc.kill()
        if proc:
            try:
                proc.wait(timeout=CANCEL_WAIT_S)
            except subprocess.TimeoutExpired:
                _LOG.warning("İptal edilen işin süreci zamanında bitmedi: %s", job_id)

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

    @contextlib.contextmanager
    def _tracked(self, job_id: str, proc: subprocess.Popen[Any]) -> Iterator[None]:
        """Süreç iptal edilebilir olur. Kayıttan önce silindiyse silme onu göremedi: burada durdurulur."""
        with self._lock:
            self._current = (job_id, proc)
        try:
            if self.store.get(job_id) is None:
                proc.kill()
            yield
        finally:
            with self._lock:
                self._current = None

    def process(self, job_id: str) -> None:
        try:
            self._process(job_id)
        finally:
            if self.store.get(job_id) is None:   # analiz sürerken silindi: süreç artık dosya tutmuyor
                self.store.remove_files(job_id)

    def _process(self, job_id: str) -> None:
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
        with self._tracked(job_id, proc):
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
                self._encode_h264(job_id, raw / "isaretli.mp4", out / "annotated.mp4")
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
        if summary.get("countOut") is not None:                  # iki yönlü sayım (kişi): çıkış
            result["countOut"] = int(summary["countOut"])
        job = self.store.get(job_id)
        if job is None:
            return
        job["video"].update({k: v for k, v in {
            "seconds": summary.get("seconds"), "fps": summary.get("fps"),
            "width": (summary.get("size") or [None, None])[0], "height": (summary.get("size") or [None, None])[1],
        }.items() if v})
        job.update(status="done", result=result, progress=1.0)
        job.pop("stage", None)
        if not self.store.save(job):
            return
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

    def _encode_h264(self, job_id: str, src: pathlib.Path, dst: pathlib.Path) -> None:
        cmd = [self.settings.ffmpeg_exe(), "-v", "error", "-y", "-i", str(src), "-an",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
               "-movflags", "+faststart", str(dst)]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        with self._tracked(job_id, proc):
            try:
                output, errors = proc.communicate(timeout=3600)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                raise
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, cmd, output, errors)
