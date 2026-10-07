from __future__ import annotations

import json
import logging
import pathlib
import re
import time
import traceback

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
    assert str(e.value) == "Bot anahtarı geçersiz." and e.value.permanent and TOKEN not in e.value.detail


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
    assert n._queue == [] and (tmp_path / "live" / "outbox.json").read_text(encoding="utf-8") == "[]"
    now[0] += 10_000
    n.flush()                                                               # gönderilen kayıt bir daha gitmez
    assert len(fake.calls) == 3 and alarms.get(a["id"])["notify"] == "sent"


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
    live = tmp_path / "live"
    live.mkdir()
    (live / "outbox.json").write_text("{bozuk", encoding="utf-8")
    _, _, n = setup(tmp_path, Fake(), [0.0])
    assert n._queue == []                                                   # boş başlar
    assert not (live / "outbox.json").exists()                              # bozuk dosya kenara alındı
    assert (live / "outbox.json.corrupt").read_text(encoding="utf-8") == "{bozuk"
    n.flush()                                                               # çökmemeli
    (live / "outbox.json").write_text('{"bu": "liste degil"}', encoding="utf-8")
    _, _, n2 = setup(tmp_path, Fake(), [0.0])
    assert n2._queue == []
    n2.flush()


def test_outbox_load_skips_bad_records(tmp_path: pathlib.Path) -> None:
    live = tmp_path / "live"
    live.mkdir()
    good = {"alarmId": "a" * 32, "text": "t", "image": False, "createdAt": 1.0, "attempts": 2, "nextAt": 9.0}
    (live / "outbox.json").write_text(json.dumps([good, {"alarmId": "x"}, "sacma", 7, None]), encoding="utf-8")
    _, _, n = setup(tmp_path, Fake(), [0.0])
    assert n._queue == [good]


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
    assert n._queue[0]["attempts"] == 0                                     # deneme sayılmaz


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


# ---------------------------------------------------------------- ek: kapalı bildirim, düzeltme turu 1


def test_disabled_queue_is_not_delivered_until_reenabled(tmp_path: pathlib.Path) -> None:
    now = [1000.0]
    fake = Fake()
    store, alarms, n = setup(tmp_path, fake, now)
    store.save_notify(False, "-1001", None)                                 # anahtar korunur, bildirim kapalı
    assert store.telegram_token() == TOKEN and not n.configured()
    a = alarms.add("s", "Tezgah", "hands_up", 997.0, 1000.0, b"\xff\xd8", "queued")
    n.enqueue(a["id"], "🚨 ELLER YUKARI", b"\xff\xd8")
    for _ in range(3):
        now[0] += 400
        n.flush()
    assert fake.calls == []                                                 # hiç ağ çağrısı yok
    assert alarms.get(a["id"])["notify"] == "queued" and len(n._queue) == 1
    assert n._queue[0]["attempts"] == 0 and n._queue[0]["nextAt"] == 1000.0  # deneme/bekleme artmadı
    store.save_notify(True, "-1001", None)                                  # yeniden aç
    n.flush()                                                               # hemen gider
    assert len(fake.calls) == 1 and fake.calls[0].url.path.endswith("/sendPhoto")
    assert alarms.get(a["id"])["notify"] == "sent" and n._queue == []


def test_disabled_queue_still_expires_after_24h(tmp_path: pathlib.Path) -> None:
    now = [0.0]
    fake = Fake()
    store, alarms, n = setup(tmp_path, fake, now)
    a = alarms.add("s", "Tezgah", "lying", 0.0, 0.0, None, "queued")
    n.enqueue(a["id"], "🚨 YERDE YATAN KİŞİ", None)
    store.save_notify(False, "-1001", None)
    now[0] = 24 * 3600 - 1
    n.flush()                                                               # henüz dolmadı: bekler
    assert alarms.get(a["id"])["notify"] == "queued" and len(n._queue) == 1
    now[0] = 24 * 3600 + 1
    n.flush()
    assert alarms.get(a["id"])["notify"] == "failed" and n._queue == []
    assert fake.calls == []


def test_unexpected_error_is_logged_with_traceback_and_token_safe(
        tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    _, alarms, n = setup(tmp_path, Fake(), now)
    a = alarms.add("s", "Tezgah", "hands_up", 997.0, 1000.0, b"\xff\xd8", "queued")
    n.enqueue(a["id"], "x", b"\xff\xd8")

    def boom(_alarm_id: str) -> bytes | None:
        raise RuntimeError("beklenmeyen")

    monkeypatch.setattr(alarms, "image_bytes", boom)
    n.flush()                                                               # fırlatmamalı
    assert "Traceback" in caplog.text and "beklenmeyen" in caplog.text
    assert TOKEN not in caplog.text and "GIZLI" not in caplog.text


def test_send_error_traceback_has_no_token(tmp_path: pathlib.Path) -> None:
    def leaky(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"bağlanamadı: {req.url}", request=req)

    _, _, n = setup(tmp_path, leaky, [0.0])                                 # type: ignore[arg-type]
    with pytest.raises(NotifyError) as e:
        n.send("x", None)
    assert e.value.__cause__ is None and e.value.__suppress_context__       # from None: zincir yok
    text = "".join(traceback.format_exception(e.value))
    assert TOKEN not in text and "GIZLI" not in text


def test_save_notify_rejects_bad_token_format(tmp_path: pathlib.Path) -> None:
    store = LiveStore(tmp_path)
    store.save_notify(True, "-1001", TOKEN)
    for bad in ("bozuk", "123456", "123456:", ":ABC", "abc:DEF", "123:a b", "123:a/b", "123:ş", "123:ab\ncd"):
        with pytest.raises(ValueError) as e:
            store.save_notify(False, "-9", bad)
        assert "Telegram" in str(e.value) and bad not in str(e.value)
    assert store.telegram_token() == TOKEN                                  # değişmedi
    assert store.notify_config() == {"enabled": True, "chatId": "-1001", "hasToken": True}   # hiçbir şey yazılmadı
    assert store.save_notify(True, "-1001", "  987654:Ab-C_d  ")["hasToken"]
    assert store.telegram_token() == "987654:Ab-C_d"                        # kırpılır, geçerli biçim kabul edilir


def test_long_text_is_truncated(tmp_path: pathlib.Path) -> None:
    fake = Fake()
    _, _, n = setup(tmp_path, fake, [0.0])
    n.send("a" * 5000, None)
    n.send("b" * 2000, b"\xff\xd8")
    assert max(len(m) for m in re.findall(rb"a+", fake.calls[0].content)) == 4096
    assert max(len(m) for m in re.findall(rb"b+", fake.calls[1].content)) == 1024


def test_restart_after_stop(tmp_path: pathlib.Path) -> None:
    fake = Fake()
    _, alarms, n = setup(tmp_path, fake, [1000.0])
    n.start()
    n.stop()
    assert n._thread is not None and not n._thread.is_alive()
    a = alarms.add("s", "Tezgah", "hands_up", 997.0, 1000.0, None, "queued")
    n.enqueue(a["id"], "x", None)
    n.start()                                                               # stop() sonrası yeniden başlar
    t = n._thread
    assert t is not None and t.is_alive()
    deadline = time.time() + 5
    while alarms.get(a["id"])["notify"] != "sent" and time.time() < deadline:
        time.sleep(0.05)
    n.start()                                                               # çalışırken ikinci start: aynı iş parçacığı
    assert n._thread is t
    n.stop()
    assert alarms.get(a["id"])["notify"] == "sent" and not t.is_alive()


# ---------------------------------------------------------------- son düzeltme dalgası A: kalıcı hatalar (I4)


class Reply:
    """Telegram gibi cevap veren sahte sunucu: (durum, açıklama) sırayla; liste biterse 200."""

    def __init__(self, *replies: tuple[int, str] | Exception) -> None:
        self.replies, self.calls = list(replies), []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        r = self.replies.pop(0) if self.replies else (200, "")
        if isinstance(r, Exception):
            raise r
        return httpx.Response(r[0], json={"ok": r[0] == 200, "description": r[1]})


@pytest.mark.parametrize(("status", "desc", "text"), [
    (401, "Unauthorized", "Bot anahtarı geçersiz."),
    (400, "Bad Request: chat not found", "Sohbet / grup kimliği bulunamadı; botu gruba ekleyin."),
    (403, "Forbidden: bot was kicked from the supergroup chat", "Bot gruptan çıkarılmış ya da engellenmiş."),
    (403, "Forbidden: bot was blocked by the user", "Bot gruptan çıkarılmış ya da engellenmiş."),
    (400, "Bad Request: message text is empty", "Telegram hatası (400)."),
    (404, "Not Found", "Telegram hatası (404)."),
])
def test_permanent_telegram_errors_fail_at_once_in_turkish(
        tmp_path: pathlib.Path, status: int, desc: str, text: str, caplog: pytest.LogCaptureFixture) -> None:
    """Yanlış anahtar/sohbet kimliği 24 saat "Gönderiliyor" kalmaz: alarm hemen "failed", kayıt kuyruktan düşer."""
    now = [1000.0]
    fake = Reply((status, desc))
    _, alarms, n = setup(tmp_path, fake, now)                                # type: ignore[arg-type]
    a = alarms.add("s", "Tezgah", "hands_up", 997.0, 1000.0, None, "queued")
    n.enqueue(a["id"], "🚨 ELLER YUKARI", None)
    with caplog.at_level(logging.WARNING):
        n.flush()
    assert alarms.get(a["id"])["notify"] == "failed" and n._queue == [] and len(fake.calls) == 1
    assert n.last_error() == {"text": text, "at": 1000.0}
    assert json.loads((tmp_path / "live" / "outbox.json").read_text(encoding="utf-8")) == []
    now[0] += 10_000
    n.flush()
    assert len(fake.calls) == 1                                              # bir daha denenmez
    assert TOKEN not in caplog.text and "GIZLI" not in caplog.text


@pytest.mark.parametrize("failure", [(500, "Internal Server Error"), (502, "Bad Gateway"), (429, "Too Many Requests")])
def test_server_errors_and_rate_limit_are_retried(tmp_path: pathlib.Path, failure: tuple[int, str]) -> None:
    now = [1000.0]
    fake = Reply(failure)
    _, alarms, n = setup(tmp_path, fake, now)                                # type: ignore[arg-type]
    a = alarms.add("s", "Tezgah", "lying", 997.0, 1000.0, None, "queued")
    n.enqueue(a["id"], "🚨 YERDE YATAN KİŞİ", None)
    n.flush()
    assert alarms.get(a["id"])["notify"] == "queued" and len(n._queue) == 1 and n._queue[0]["attempts"] == 1
    assert n.last_error() == {"text": f"Telegram hatası ({failure[0]}).", "at": 1000.0}
    now[0] += 6
    n.flush()                                                                # bekleme dolunca yeniden: gider
    assert alarms.get(a["id"])["notify"] == "sent" and n._queue == [] and len(fake.calls) == 2
    assert n.last_error() is None                                            # başarılı gönderim temizler


def test_network_error_text_is_turkish_and_masked(tmp_path: pathlib.Path) -> None:
    def leaky(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout(f"timed out connecting to {req.url}", request=req)

    _, _, n = setup(tmp_path, leaky, [5.0])                                  # type: ignore[arg-type]
    with pytest.raises(NotifyError) as e:
        n.send("x", None)
    assert str(e.value) == "Telegram'a ulaşılamıyor (internet bağlantısını kontrol edin)."
    assert e.value.network and not e.value.permanent and TOKEN not in e.value.detail and "GIZLI" not in e.value.detail
    assert n.last_error() == {"text": str(e.value), "at": 5.0}


def test_network_failure_stops_the_round_so_new_alarms_are_not_stuck(tmp_path: pathlib.Path) -> None:
    """Ağ yokken her istek 15 sn zaman aşımına kadar bekler: bir turda ilk ağ hatasından sonra durulur (kuyruktaki
    yüz bildirim için 25 dakika beklenmez). Süresi dolanlar yine "failed" olur."""
    now = [100_000.0]
    fake = Reply(httpx.ConnectError("ağ yok"), httpx.ConnectError("ağ yok"))
    _, alarms, n = setup(tmp_path, fake, now)                                # type: ignore[arg-type]
    old = alarms.add("s", "Tezgah", "hands_up", 0.0, 0.0, None, "queued")
    ids = [alarms.add("s", "Tezgah", "hands_up", 1.0, 1.0, None, "queued")["id"] for _ in range(3)]
    n.enqueue(old["id"], "eski", None)
    n._queue[0]["createdAt"] = now[0] - 25 * 3600                           # 24 saati geçmiş
    for i in ids:
        n.enqueue(i, "yeni", None)
    n.flush()
    assert len(fake.calls) == 1                                              # yalnızca ilk deneme
    assert alarms.get(old["id"])["notify"] == "failed"                      # süre dolumu ağ beklemeden işlendi
    assert [q["attempts"] for q in n._queue] == [1, 0, 0]
    now[0] += 6
    n.flush()                                                                # ikinci tur: yine ilk hatada durur
    assert len(fake.calls) == 2 and [q["attempts"] for q in n._queue] == [2, 0, 0]
    now[0] += 20
    n.flush()                                                                # ağ geldi: hepsi gider
    assert all(alarms.get(i)["notify"] == "sent" for i in ids) and n._queue == []


def test_flush_traceback_is_rate_limited(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    _, alarms, n = setup(tmp_path, Fake(), now)
    a = alarms.add("s", "Tezgah", "hands_up", 997.0, 1000.0, b"\xff\xd8", "queued")
    n.enqueue(a["id"], "x", b"\xff\xd8")

    def boom(_alarm_id: str) -> bytes | None:
        raise RuntimeError("beklenmeyen")

    monkeypatch.setattr(alarms, "image_bytes", boom)
    with caplog.at_level(logging.WARNING):
        for _ in range(5):
            n.flush()                                                        # kalıcı arıza: her saniye çağrılır
    assert caplog.text.count("Traceback") == 1
    assert len([r for r in caplog.records if r.name == "bantvision.live.notify"]) == 5


def test_locked_outbox_is_retried_and_never_clobbered(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                                      caplog: pytest.LogCaptureFixture) -> None:
    from bantvision.live import jsonfile

    monkeypatch.setattr(jsonfile, "READ_RETRY_DELAYS_S", (0.0,) * 5)
    live = tmp_path / "live"
    live.mkdir()
    outbox = live / "outbox.json"
    good = {"alarmId": "a" * 32, "text": "t", "image": False, "createdAt": 1.0, "attempts": 0, "nextAt": 1.0}
    outbox.write_text(json.dumps([good]), encoding="utf-8")
    real = pathlib.Path.read_text
    fail = [2]

    def read_text(self: pathlib.Path, *a: object, **k: object) -> str:
        if self.name == "outbox.json" and fail[0] > 0:
            fail[0] -= 1
            raise PermissionError(13, "Erişim engellendi", str(self))
        return real(self, *a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(pathlib.Path, "read_text", read_text)
    _, _, n = setup(tmp_path, Fake(), [0.0])
    assert n._queue == [good] and not (live / "outbox.json.corrupt").exists()   # iki kilit denemesinden sonra okundu

    fail[0] = 10**6                                                           # hep kilitli
    with caplog.at_level(logging.ERROR):
        _, _, n2 = setup(tmp_path, Fake(), [0.0])
    assert n2._queue == [] and "okunamadı" in caplog.text and outbox.exists()
    assert not (live / "outbox.json.corrupt").exists()                        # kilitli dosya bozuk sayılmaz
    n2.enqueue("b" * 32, "yeni", None)                                        # hâlâ kilitli: dosya ezilmez
    assert json.loads(real(outbox, encoding="utf-8")) == [good]
    fail[0] = 0                                                               # kilit kalktı: birleşir
    n2.enqueue("c" * 32, "daha yeni", None)
    assert [q["alarmId"] for q in json.loads(real(outbox, encoding="utf-8"))] == ["a" * 32, "b" * 32, "c" * 32]
