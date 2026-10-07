"""Telegram bildirimi (poz güvenlik alarmı): anında gönderim ve çevrimdışı kuyruk.

Anahtar yalnızca secrets.json'da; hata iletilerinde, günlükte ve kuyruk dosyasında geçmez (Telegram API
adresinde bulunur, bu yüzden maskelenir). Kuyruk <data>/live/outbox.json: başarısız deneme sonrası bekleme
5 sn → 5 dk (iki katı), 24 saatte "failed". `flush()` hiçbir koşulda hata fırlatmaz (arka plan iş parçacığı
her saniye çağırır).
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
        self._client = httpx.Client(timeout=15.0, transport=transport, trust_env=False)
        self._lock = threading.Lock()                   # kuyruk listesi ve dosya
        self._flush_lock = threading.Lock()             # aynı anda tek flush (çift gönderimi önler)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._queue: list[dict[str, Any]] = self._load()

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
                r = self._client.post(f"{base}/sendMessage", json={"chat_id": chat, "text": text})
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
            _LOG.warning("Telegram kuyruğu işlenemedi: %s", type(e).__name__)

    def _flush(self) -> None:
        with self._lock:
            now = self.clock()
            due = [q for q in self._queue if q["nextAt"] <= now]
        for q in due:
            done, status = False, "queued"
            if now - q["createdAt"] > MAX_AGE_S:
                done, status = True, "failed"
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
            self.alarms.set_notify(q["alarmId"], status)
            if done:
                with self._lock:
                    self._queue = [x for x in self._queue if x is not q]
        if due:
            with self._lock:
                self._save()

    # ------------------------------------------------------------------ arka plan

    def _run(self) -> None:
        while not self._stop.wait(1.0):
            self.flush()

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="telegram-kuyruk", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._client.close()
