from __future__ import annotations

import logging
import pathlib
import time

import httpx
import pytest

from bantvision.live.alarms import AlarmStore
from bantvision.live.notify import NotifyError, TelegramNotifier
from bantvision.live.store import LiveStore

TOKEN = "123456:GIZLI-ANAHTAR"


class Fake:
    def __init__(self, fail: int = 0, status: int = 200) -> None:
        self.calls: list[httpx.Request] = []
        self.fail, self.status = fail, status

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        if self.fail > 0:
            self.fail -= 1
            raise httpx.ConnectError("ağ yok", request=req)
        return httpx.Response(self.status, json={"ok": self.status == 200, "description": "Bad Request"})


def setup(tmp_path: pathlib.Path, fake: Fake, now: list[float]) -> tuple[LiveStore, AlarmStore, TelegramNotifier]:
    store = LiveStore(tmp_path)
    store.save_notify(True, "-1001", TOKEN)
    alarms = AlarmStore(tmp_path)
    n = TelegramNotifier(store, alarms, tmp_path, transport=httpx.MockTransport(fake), clock=lambda: now[0])
    return store, alarms, n


def test_config_never_exposes_token(tmp_path: pathlib.Path) -> None:
    store = LiveStore(tmp_path)
    cfg = store.save_notify(True, "-1001", TOKEN)
    assert cfg == {"enabled": True, "chatId": "-1001", "hasToken": True} and TOKEN not in str(store.notify_config())
    store.save_notify(False, "-1001", None)
    assert store.telegram_token() == TOKEN                                  # None: korunur
    store.save_notify(False, "-1001", "")
    assert store.telegram_token() == "" and not store.notify_config()["hasToken"]


def test_send_photo_and_message_format(tmp_path: pathlib.Path) -> None:
    fake = Fake()
    _, _, n = setup(tmp_path, fake, [0.0])
    n.send("🚨 ELLER YUKARI — Tezgah · 06.10.2026 15:42:07", b"\xff\xd8jpeg")
    n.send("🧪 DENEME", None)
    assert fake.calls[0].url.path.endswith("/sendPhoto") and b"Tezgah" in fake.calls[0].content
    assert fake.calls[1].url.path.endswith("/sendMessage") and b"-1001" in fake.calls[1].content


def test_errors_are_turkish_and_masked(tmp_path: pathlib.Path) -> None:
    _, _, n = setup(tmp_path, Fake(status=401), [0.0])
    with pytest.raises(NotifyError) as e:
        n.send("x", None)
    assert TOKEN not in str(e.value) and "Telegram" in str(e.value)


def test_outbox_retries_then_sends(tmp_path: pathlib.Path) -> None:
    now = [1000.0]
    fake = Fake(fail=2)
    _, alarms, n = setup(tmp_path, fake, now)
    a = alarms.add("s", "Tezgah", "hands_up", 997.0, 1000.0, b"\xff\xd8", "queued")
    n.enqueue(a["id"], "🚨 ELLER YUKARI", b"\xff\xd8")
    n.flush()                                                               # 1. deneme başarısız
    assert alarms.get(a["id"])["notify"] == "queued"
    now[0] += 4
    n.flush()                                                               # bekleme 5 sn dolmadı: denemez
    assert len(fake.calls) == 1
    now[0] += 2
    n.flush()                                                               # 2. deneme başarısız (bekleme 10 sn)
    now[0] += 11
    n.flush()
    assert alarms.get(a["id"])["notify"] == "sent" and len(fake.calls) == 3


def test_outbox_fails_after_24h(tmp_path: pathlib.Path) -> None:
    now = [0.0]
    fake = Fake(fail=10**6)
    _, alarms, n = setup(tmp_path, fake, now)
    a = alarms.add("s", "Tezgah", "lying", 0.0, 0.0, None, "queued")
    n.enqueue(a["id"], "🚨 YERDE YATAN KİŞİ", None)
    for _ in range(400):
        now[0] += 301
        n.flush()
    assert alarms.get(a["id"])["notify"] == "failed"


# ---------------------------------------------------------------- ek: dayanıklılık ve güvenlik


def test_outbox_file_never_contains_token(tmp_path: pathlib.Path) -> None:
    now = [1000.0]
    _, alarms, n = setup(tmp_path, Fake(fail=1), now)
    a = alarms.add("s", "Tezgah", "hands_up", 997.0, 1000.0, b"\xff\xd8", "queued")
    n.enqueue(a["id"], "🚨 ELLER YUKARI", b"\xff\xd8")
    n.flush()                                                               # başarısız: kuyrukta kalır
    outbox = tmp_path / "live" / "outbox.json"
    assert outbox.is_file() and TOKEN not in outbox.read_text(encoding="utf-8")
    assert "GIZLI" not in outbox.read_text(encoding="utf-8")


def test_unreachable_error_masks_token(tmp_path: pathlib.Path) -> None:
    def leaky(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"bağlanamadı: {req.url}", request=req)   # URL (anahtar dahil) iletide

    _, _, n = setup(tmp_path, leaky, [0.0])                                 # type: ignore[arg-type]
    with pytest.raises(NotifyError) as e:
        n.send("x", None)
    assert TOKEN not in str(e.value) and "Telegram" in str(e.value)


def test_corrupt_outbox_starts_empty(tmp_path: pathlib.Path) -> None:
    (tmp_path / "live").mkdir()
    (tmp_path / "live" / "outbox.json").write_text("{bozuk", encoding="utf-8")
    _, _, n = setup(tmp_path, Fake(), [0.0])
    n.flush()                                                               # çökmemeli
    (tmp_path / "live" / "outbox.json").write_text('{"bu": "liste degil"}', encoding="utf-8")
    _, _, n2 = setup(tmp_path, Fake(), [0.0])
    n2.flush()


def test_outbox_survives_restart(tmp_path: pathlib.Path) -> None:
    now = [1000.0]
    fake = Fake(fail=1)
    _, alarms, n = setup(tmp_path, fake, now)
    a = alarms.add("s", "Tezgah", "hands_up", 997.0, 1000.0, None, "queued")
    n.enqueue(a["id"], "🚨 ELLER YUKARI", None)
    n.flush()                                                               # başarısız
    n.stop()
    fake2 = Fake()
    n2 = TelegramNotifier(LiveStore(tmp_path), alarms, tmp_path, transport=httpx.MockTransport(fake2),
                          clock=lambda: now[0])
    now[0] += 10
    n2.flush()
    assert alarms.get(a["id"])["notify"] == "sent" and len(fake2.calls) == 1


def test_missing_image_sends_text_only(tmp_path: pathlib.Path) -> None:
    now = [1000.0]
    fake = Fake()
    _, alarms, n = setup(tmp_path, fake, now)
    a = alarms.add("s", "Tezgah", "hands_up", 997.0, 1000.0, b"\xff\xd8", "queued")
    n.enqueue(a["id"], "🚨 ELLER YUKARI", b"\xff\xd8")
    (tmp_path / "live" / "alarm-images" / f"{a['id']}.jpg").unlink()        # resim süresi dolmuş
    n.flush()
    assert fake.calls[0].url.path.endswith("/sendMessage")
    assert alarms.get(a["id"])["notify"] == "sent"


def test_flush_never_raises(tmp_path: pathlib.Path) -> None:
    now = [1000.0]
    _, alarms, n = setup(tmp_path, Fake(), now)
    a = alarms.add("s", "Tezgah", "hands_up", 997.0, 1000.0, None, "queued")
    n.enqueue(a["id"], "x", None)
    outbox = tmp_path / "live" / "outbox.json"
    outbox.unlink()
    outbox.mkdir()                                                          # yazma OSError verir
    n.enqueue(a["id"], "y", None)                                           # enqueue de çökmemeli
    n.flush()                                                               # flush çökmemeli
    assert alarms.get(a["id"])["notify"] == "sent"


def test_not_configured_keeps_queue(tmp_path: pathlib.Path) -> None:
    now = [1000.0]
    fake = Fake()
    store, alarms, n = setup(tmp_path, fake, now)
    store.save_notify(True, "-1001", "")                                    # anahtar silindi
    assert not n.configured()
    a = alarms.add("s", "Tezgah", "hands_up", 997.0, 1000.0, None, "queued")
    n.enqueue(a["id"], "x", None)
    n.flush()
    assert fake.calls == [] and alarms.get(a["id"])["notify"] == "queued"


def test_httpx_request_log_masks_token(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)                                          # httpx isteği INFO'da tam adresle yazar
    _, _, n = setup(tmp_path, Fake(), [0.0])
    n.send("x", None)
    assert "api.telegram.org" in caplog.text and TOKEN not in caplog.text and "GIZLI" not in caplog.text


def test_huge_attempts_in_outbox_do_not_stall(tmp_path: pathlib.Path) -> None:
    now = [1000.0]
    fake = Fake(fail=1)
    _, alarms, n = setup(tmp_path, fake, now)
    a = alarms.add("s", "Tezgah", "hands_up", 997.0, 1000.0, None, "queued")
    n.enqueue(a["id"], "x", None)
    n._queue[0]["attempts"] = 5000                                          # bozuk/eski dosyadan gelen büyük sayı
    n.flush()                                                               # üs taşması olmamalı
    assert n._queue[0]["attempts"] == 5001 and n._queue[0]["nextAt"] == now[0] + 300.0


def test_background_thread_sends_and_stops(tmp_path: pathlib.Path) -> None:
    fake = Fake()
    _, alarms, n = setup(tmp_path, fake, [1000.0])
    a = alarms.add("s", "Tezgah", "hands_up", 997.0, 1000.0, None, "queued")
    n.enqueue(a["id"], "x", None)
    n.start()
    deadline = time.time() + 5
    while alarms.get(a["id"])["notify"] != "sent" and time.time() < deadline:
        time.sleep(0.05)
    n.stop()
    assert alarms.get(a["id"])["notify"] == "sent" and n._thread is not None and not n._thread.is_alive()
