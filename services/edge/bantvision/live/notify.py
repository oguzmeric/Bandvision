"""Telegram bildirimi (poz güvenlik alarmı): anında gönderim ve çevrimdışı kuyruk.

Anahtar yalnızca secrets.json'da; hata iletilerinde, günlükte ve kuyruk dosyasında geçmez (Telegram API
adresinde bulunur, bu yüzden maskelenir). Kuyruk <data>/live/outbox.json: başarısız deneme sonrası bekleme
5 sn → 5 dk (iki katı), 24 saatte "failed". `flush()` hiçbir koşulda hata fırlatmaz (arka plan iş parçacığı
her saniye çağırır). Bildirim kapalı ya da ayarsızken kuyruk gönderilmez (deneme sayılmaz, kayıtlar
bekler); 24 saat dolan kayıtlar yine "failed" olur.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import pathlib
import re
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import httpx

from .alarms import AlarmStore
from .store import LiveStore

_LOG = logging.getLogger(__name__)

MAX_AGE_S = 24 * 3600
BACKOFF_MIN_S, BACKOFF_MAX_S = 5.0, 300.0
CAPTION_MAX = 1024                                # Telegram resim açıklaması sınırı
MESSAGE_MAX = 4096                                # Telegram ileti metni sınırı

_BOT_URL = re.compile(r"(api\.telegram\.org/bot)[^/\s\"']+")


class NotifyError(Exception):
    pass


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
        self._queue: list[dict[str, Any]] = self._load()

    def _new_client(self) -> httpx.Client:
        return httpx.Client(timeout=15.0, transport=self._transport, trust_env=False)

    # ------------------------------------------------------------------ kuyruk dosyası

    def _load(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as e:                # bozuk dosya: boş başla, bozuğu sakla
            _LOG.warning("outbox.json okunamadı (%s); boş kuyrukla başlanıyor", type(e).__name__)
            with contextlib.suppress(OSError):
                self._file.replace(self._file.with_suffix(".json.corrupt"))
            return []
        items: list[dict[str, Any]] = []
        for q in data if isinstance(data, list) else []:
            try:
                items.append({"alarmId": str(q["alarmId"]), "text": str(q["text"]), "image": bool(q["image"]),
                              "createdAt": float(q["createdAt"]), "attempts": int(q["attempts"]),
                              "nextAt": float(q["nextAt"])})
            except (KeyError, TypeError, ValueError):
                continue                                  # bozuk kayıt atlanır
        return items

    def _save(self) -> None:
        """Kilit altında çağrılır. Yazma hatası yutulur (günlüğe yazılır): kuyruk bellekte sürer."""
        try:
            tmp = self._file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._queue, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self._file)
        except OSError as e:
            _LOG.warning("outbox.json yazılamadı: %s", e)

    # ------------------------------------------------------------------ gönderim

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
                r = self._client.post(f"{base}/sendPhoto", data={"chat_id": chat, "caption": text[:CAPTION_MAX]},
                                      files={"photo": ("olay.jpg", jpeg, "image/jpeg")})
            else:
                r = self._client.post(f"{base}/sendMessage", json={"chat_id": chat, "text": text[:MESSAGE_MAX]})
        except Exception as e:                            # noqa: BLE001 - ağ/URL/kapalı istemci: hepsi gönderilemedi
            raise NotifyError(f"Telegram'a ulaşılamadı: {_mask(str(e), token)}") from None
        if r.status_code != 200:
            try:
                body = r.json()
                desc = str(body.get("description", "")) if isinstance(body, dict) else ""
            except ValueError:
                desc = ""
            raise NotifyError(f"Telegram reddetti ({r.status_code}): {_mask(desc, token)}".strip())

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
            # exc_info anahtar sızdırmaz: send() yalnız `from None` ile NotifyError (maskeli) fırlatır
            _LOG.warning("Telegram kuyruğu işlenemedi: %s", type(e).__name__, exc_info=True)

    def _flush(self) -> None:
        with self._lock:
            now = self.clock()
            due = [q for q in self._queue if q["nextAt"] <= now]
        active = bool(due) and self.configured()          # kapalı/ayarsız: gönderme, ama süre dolumu işlenir
        changed = False
        for q in due:
            done, status = False, "queued"
            if now - q["createdAt"] > MAX_AGE_S:
                done, status = True, "failed"
            elif not active:
                continue                                  # deneme sayılmaz; açılınca hemen gider
            else:
                jpeg = self.alarms.image_bytes(q["alarmId"]) if q["image"] else None   # resim yoksa yalnız metin
                try:
                    self.send(q["text"], jpeg)
                    done, status = True, "sent"
                except NotifyError as e:
                    with self._lock:
                        q["attempts"] += 1
                        step = min(q["attempts"] - 1, 20)         # üs sınırı: bozuk dosyada taşma olmasın
                        q["nextAt"] = self.clock() + min(BACKOFF_MAX_S, BACKOFF_MIN_S * 2 ** step)
                    _LOG.warning("Telegram gönderilemedi (deneme %d): %s", q["attempts"], e)
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
