"""Telegram bildirimi (poz güvenlik alarmı): anında gönderim ve çevrimdışı kuyruk.

Anahtar yalnızca secrets.json'da; hata iletilerinde, günlükte ve kuyruk dosyasında geçmez (Telegram API
adresinde bulunur, bu yüzden maskelenir). Kuyruk <data>/live/outbox.json: başarısız deneme sonrası bekleme
5 sn → 5 dk (iki katı), 24 saatte "failed". `flush()` hiçbir koşulda hata fırlatmaz (arka plan iş parçacığı
her saniye çağırır). Bildirim kapalı ya da ayarsızken kuyruk gönderilmez (deneme sayılmaz, kayıtlar
bekler); 24 saat dolan kayıtlar yine "failed" olur.

Hata türleri: Telegram'ın 400/401/403/404 cevabı **kalıcıdır** (yanlış anahtar, sohbet bulunamadı, bot gruptan
çıkarıldı): alarm hemen "failed" olur, kayıt kuyruktan düşer. Ağ hatası, zaman aşımı, 429 ve 5xx yeniden denenir. Bir
turda ilk ağ hatasından sonra durulur (her istek 15 sn bekleyebilir; yeni alarmlar uzun kuyruğun arkasında kalmasın).
Kullanıcıya giden iletiler Türkçe; Telegram'ın (İngilizce, maskeli) açıklaması yalnızca günlüğe yazılır. Son hata
(`last_error`) bellekte tutulur ve ilk başarılı gönderimde silinir.
"""
from __future__ import annotations

import logging
import pathlib
import re
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import httpx

from .alarms import AlarmStore
from .jsonfile import quarantine, read_json, write_json_atomic
from .store import LiveStore

_LOG = logging.getLogger(__name__)

MAX_AGE_S = 24 * 3600
BACKOFF_MIN_S, BACKOFF_MAX_S = 5.0, 300.0
CAPTION_MAX = 1024                                # Telegram resim açıklaması sınırı
MESSAGE_MAX = 4096                                # Telegram ileti metni sınırı

_BOT_URL = re.compile(r"(api\.telegram\.org/bot)[^/\s\"']+")


PERMANENT_STATUSES = frozenset({400, 401, 403, 404})
UNREACHABLE = "Telegram'a ulaşılamıyor (internet bağlantısını kontrol edin)."
TRACEBACK_EVERY_S = 60.0                           # aynı beklenmeyen hata türünün izi günlüğe en çok dakikada bir


class NotifyError(Exception):
    """Gönderilemedi. İleti Türkçe ve anahtarsız (kullanıcıya gösterilir); `detail` Telegram'ın maskeli açıklaması
    (yalnızca günlük). `permanent`: yeniden denemenin anlamı yok; `network`: Telegram'a hiç ulaşılamadı."""

    def __init__(self, text: str, *, permanent: bool = False, network: bool = False, status: int | None = None,
                 detail: str = "") -> None:
        super().__init__(text)
        self.permanent, self.network, self.status, self.detail = permanent, network, status, detail


def describe_rejection(status: int, description: str) -> str:
    """Telegram'ın ret cevabı → Türkçe ileti (İngilizce kuyruk yok)."""
    d = description.lower()
    if status == 401:
        return "Bot anahtarı geçersiz."
    if status == 400 and "chat not found" in d:
        return "Sohbet / grup kimliği bulunamadı; botu gruba ekleyin."
    if status == 403 and ("kicked" in d or "blocked" in d):
        return "Bot gruptan çıkarılmış ya da engellenmiş."
    return f"Telegram hatası ({status})."


class _RedactTokenFilter(logging.Filter):
    """httpx her isteği INFO düzeyinde tam adresle günlüğe yazar; Telegram adresinde bot anahtarı vardır."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:                                     # noqa: BLE001 - günlük asla çökmemeli
            return True
        if "api.telegram.org/bot" in msg:
            record.msg, record.args = _BOT_URL.sub(r"\1***", msg), ()
        return True


_httpx_logger = logging.getLogger("httpx")
if not any(isinstance(f, _RedactTokenFilter) for f in _httpx_logger.filters):
    _httpx_logger.addFilter(_RedactTokenFilter())


def _mask(text: str, token: str) -> str:
    """Anahtarı (düz ve adres-kodlu biçimiyle) ve adresteki `bot...` kısmını gizler."""
    if token:
        for variant in {token, quote(token, safe=""), quote(token)}:
            text = text.replace(variant, "***")
    return _BOT_URL.sub(r"\1***", text)


class TelegramNotifier:
    def __init__(self, store: LiveStore, alarms: AlarmStore, root: pathlib.Path,
                 transport: httpx.BaseTransport | None = None, clock: Callable[[], float] = time.time) -> None:
        self.store, self.alarms, self.clock = store, alarms, clock
        self._file = root / "live" / "outbox.json"
        self._transport = transport
        self._client = self._new_client()
        self._lock = threading.Lock()                   # kuyruk listesi ve dosya
        self._flush_lock = threading.Lock()             # aynı anda tek flush (çift gönderimi önler)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error: dict[str, Any] | None = None  # {text, at}: son gönderim hatası (bellekte)
        self._traced: dict[str, float] = {}             # beklenmeyen hata türü → son iz (tekdüze saat)
        self._load_failed = False                       # açılışta kilitli: ilk kayıtta yeniden okunup birleştirilir
        self._queue: list[dict[str, Any]] = self._load()

    def _new_client(self) -> httpx.Client:
        return httpx.Client(timeout=15.0, transport=self._transport, trust_env=False)

    # ------------------------------------------------------------------ kuyruk dosyası

    def _load(self) -> list[dict[str, Any]]:
        """Kilitli dosya (Windows) birkaç kez yeniden denenir; yine okunamazsa boş başlanır ama dosya ne bozuk sayılır
        ne de ezilir (ilk kayıtta yeniden okunup birleştirilir). Yalnızca JSON'u ya da yapısı bozuk dosya kenara alınır."""
        res = read_json(self._file)
        if res.status == "unreadable":
            _LOG.error("outbox.json okunamadı (dosya kilitli olabilir); bildirim kuyruğu boş başlıyor, dosyaya "
                       "dokunulmadı — ilk kayıtta yeniden okunup birleştirilecek")
            self._load_failed = True
            return []
        if res.status == "corrupt" or (res.status == "ok" and not isinstance(res.data, list)):
            _LOG.warning("outbox.json bozuk; kenara alındı (outbox.json.corrupt), boş kuyrukla başlanıyor")
            quarantine(self._file)
            return []
        return self._parse(res.data or [])

    @staticmethod
    def _parse(data: list[Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for q in data:
            try:
                items.append({"alarmId": str(q["alarmId"]), "text": str(q["text"]), "image": bool(q["image"]),
                              "createdAt": float(q["createdAt"]), "attempts": int(q["attempts"]),
                              "nextAt": float(q["nextAt"])})
            except (KeyError, TypeError, ValueError):
                continue                                  # bozuk kayıt atlanır
        return items

    def _save(self) -> None:
        """Kilit altında çağrılır. Yazma hatası yutulur (günlüğe yazılır): kuyruk bellekte sürer. Açılışta okunamayan
        dosya önce yeniden okunup birleştirilir; hâlâ okunamıyorsa yazılmaz (bekleyen bildirimler ezilmesin)."""
        if self._load_failed:
            res = read_json(self._file, delays=())
            if res.status == "unreadable":
                _LOG.warning("outbox.json hâlâ okunamıyor; bekleyen bildirimler ezilmesin diye yazma ertelendi")
                return
            if res.status == "ok" and isinstance(res.data, list):
                mine = {q["alarmId"] for q in self._queue}
                self._queue = [q for q in self._parse(res.data) if q["alarmId"] not in mine] + self._queue
            self._load_failed = False
        try:
            write_json_atomic(self._file, self._queue)
        except OSError as e:
            _LOG.warning("outbox.json yazılamadı: %s", e)

    # ------------------------------------------------------------------ gönderim

    def configured(self) -> bool:
        c = self.store.notify_config()
        return c["enabled"] and c["hasToken"] and bool(c["chatId"])

    def last_error(self) -> dict[str, Any] | None:
        """Son gönderim hatası `{text, at}` (Türkçe, anahtarsız) ya da None."""
        with self._lock:
            return dict(self._last_error) if self._last_error else None

    def clear_last_error(self) -> None:
        """Ayar (anahtar/sohbet) değişti: eski hata artık geçerli değil."""
        with self._lock:
            self._last_error = None

    def _note(self, err: NotifyError | None) -> None:
        with self._lock:
            self._last_error = None if err is None else {"text": str(err), "at": self.clock()}

    def send(self, text: str, jpeg: bytes | None) -> None:
        """Hemen gönderir; olmazsa `NotifyError` (Türkçe). Telegram'a yapılan her denemenin sonucu `last_error`'a
        yansır (başarı siler)."""
        token, chat = self.store.telegram_token(), self.store.notify_config()["chatId"]
        if not token or not chat:
            raise NotifyError("Telegram ayarı eksik: bot anahtarı ve sohbet kimliği gerekli.")
        base = f"https://api.telegram.org/bot{token}"
        try:
            if jpeg is not None:
                r = self._client.post(f"{base}/sendPhoto", data={"chat_id": chat, "caption": text[:CAPTION_MAX]},
                                      files={"photo": ("olay.jpg", jpeg, "image/jpeg")})
            else:
                r = self._client.post(f"{base}/sendMessage", json={"chat_id": chat, "text": text[:MESSAGE_MAX]})
        except Exception as e:                            # noqa: BLE001 - ağ/zaman aşımı/kapalı istemci: ulaşılamadı
            err = NotifyError(UNREACHABLE, network=True, detail=_mask(f"{type(e).__name__}: {e}", token))
            self._note(err)
            raise err from None
        if r.status_code != 200:
            try:
                body = r.json()
                desc = str(body.get("description", "")) if isinstance(body, dict) else ""
            except ValueError:
                desc = ""
            err = NotifyError(describe_rejection(r.status_code, desc), status=r.status_code,
                              permanent=r.status_code in PERMANENT_STATUSES, detail=_mask(desc, token))
            self._note(err)
            raise err
        self._note(None)

    def enqueue(self, alarm_id: str, text: str, jpeg: bytes | None) -> None:
        with self._lock:
            now = self.clock()
            self._queue.append({"alarmId": alarm_id, "text": text, "image": jpeg is not None, "createdAt": now,
                                "attempts": 0, "nextAt": now})
            self._save()

    def flush(self) -> None:
        """Vadesi gelen kuyruk kayıtlarını dener. Hata fırlatmaz."""
        try:
            with self._flush_lock:
                self._flush()
        except Exception as e:                            # noqa: BLE001 - arka plan iş parçacığı ölmemeli
            # exc_info anahtar sızdırmaz: send() yalnız `from None` ile NotifyError (maskeli) fırlatır. Kalıcı arıza her
            # saniye iz basmasın: aynı türün izi dakikada bir.
            key, mono = type(e).__name__, time.monotonic()
            trace = mono - self._traced.get(key, -1e18) >= TRACEBACK_EVERY_S
            if trace:
                self._traced[key] = mono
            _LOG.warning("Telegram kuyruğu işlenemedi: %s", key, exc_info=trace)

    def _flush(self) -> None:
        with self._lock:
            now = self.clock()
            due = [q for q in self._queue if q["nextAt"] <= now]
        active = bool(due) and self.configured()          # kapalı/ayarsız: gönderme, ama süre dolumu işlenir
        changed = False
        offline = False                                   # bu turda ağ hatası oldu: kalanlar denenmez (süre dolumu sürer)
        for q in due:
            done, status = False, "queued"
            if now - q["createdAt"] > MAX_AGE_S:
                done, status = True, "failed"
            elif not active or offline:
                continue                                  # deneme sayılmaz; açılınca / ağ gelince hemen gider
            else:
                jpeg = self.alarms.image_bytes(q["alarmId"]) if q["image"] else None   # resim yoksa yalnız metin
                try:
                    self.send(q["text"], jpeg)
                    done, status = True, "sent"
                except NotifyError as e:
                    if e.permanent:                       # yanlış anahtar/sohbet: 24 saat "Gönderiliyor" kalmaz
                        done, status = True, "failed"
                        _LOG.warning("Telegram bildirimi reddetti, yeniden denenmeyecek: %s [%s]", e, e.detail)
                    else:
                        with self._lock:
                            q["attempts"] += 1
                            step = min(q["attempts"] - 1, 20)         # üs sınırı: bozuk dosyada taşma olmasın
                            q["nextAt"] = self.clock() + min(BACKOFF_MAX_S, BACKOFF_MIN_S * 2 ** step)
                        _LOG.warning("Telegram gönderilemedi (deneme %d): %s [%s]", q["attempts"], e, e.detail)
                        offline = e.network
            changed = True
            self.alarms.set_notify(q["alarmId"], status)
            if done:
                with self._lock:
                    self._queue = [x for x in self._queue if x is not q]
        if changed:
            with self._lock:
                self._save()

    # ------------------------------------------------------------------ arka plan

    def _run(self) -> None:
        while not self._stop.wait(1.0):
            self.flush()

    def start(self) -> None:
        """Arka plan iş parçacığını başlatır; `stop()` sonrası yeniden başlatılabilir."""
        t = self._thread
        if t is not None and t.is_alive():
            if not self._stop.is_set():
                return                                    # zaten çalışıyor
            t.join(timeout=2.0)                           # durdurulmuş ama henüz çıkmadı
            if t.is_alive():
                _LOG.warning("Telegram kuyruk iş parçacığı henüz durmadı; yeniden başlatılamadı")
                return
        self._stop.clear()
        if self._client.is_closed:
            self._client = self._new_client()
        self._thread = threading.Thread(target=self._run, name="telegram-kuyruk", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._client.close()
