"""Kayıt cihazı arşivi bağdaştırıcıları ve ayrıştırıcıları (bantvision.live.archive).

Ağ yok: cihaz istekleri `httpx.MockTransport` ile `_DeviceHTTP` içinde yanıtlanır. Hikvision/Dahua biçimleri
cihazda doğrulanmadı (plan R7/R8); TRASSIR biçimi SDK belgesinden (R6, R10).
"""
from __future__ import annotations

import json
import os
import pathlib
import time
import urllib.parse
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta, tzinfo

import cv2
import httpx
import numpy as np
import pytest

from bantvision.live import archive as arc
from bantvision.live.archive import (
    DahuaArchive,
    FileArchive,
    HikvisionArchive,
    TrassirArchive,
    dahua_time,
    day_end,
    hik_iso,
    hik_utc,
    make_archive,
    merge_ranges,
    parse_dahua_find,
    parse_hik_daily,
    parse_hik_search,
    parse_trassir_calendar,
    parse_trassir_timeline,
    trassir_time,
)
from bantvision.live.recorders import (
    DahuaClient,
    HikvisionClient,
    RecorderBrand,
    RecorderChannel,
    RecorderError,
    TrassirClient,
    _DeviceHTTP,
)

HOST = "nvr.test"
CH1 = RecorderChannel(id="1", name="Bant", number=1, has_substream=True)
CH2_NOSUB = RecorderChannel(id="2", name="", number=2, has_substream=False)
GUID = RecorderChannel(id="g-1", name="Kapı", number=None, has_substream=True)


def local(y: int, mo: int, d: int, h: int = 0, mi: int = 0, s: int = 0) -> float:
    return time.mktime((y, mo, d, h, mi, s, 0, 0, -1))


Handler = Callable[[httpx.Request], httpx.Response]


def fake_http(handler: Handler, https: bool = False, port: int = 80) -> _DeviceHTTP:
    http = _DeviceHTTP(HOST, port, https, "admin", "gizli", insecure=https)
    http._client.close()
    http._client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    return http


def query(request: httpx.Request) -> dict[str, str]:
    return dict(urllib.parse.parse_qsl(request.url.query.decode(), keep_blank_values=True))


# MARK: - Zaman biçimleri


def test_hik_formats_are_utc() -> None:
    epoch = datetime(2026, 11, 7, 8, 5, 9, tzinfo=UTC).timestamp()
    assert hik_utc(epoch) == "20261107T080509Z"
    assert hik_iso(epoch) == "2026-11-07T08:05:09Z"
    assert hik_utc(epoch + 0.9) == "20261107T080509Z"


def test_local_formats_follow_this_computer() -> None:
    epoch = local(2026, 11, 7, 8, 5, 9)
    assert trassir_time(epoch) == "20261107T080509"
    assert dahua_time(epoch, "_") == "2026_11_07_08_05_09"
    assert dahua_time(epoch, "-") == "2026-11-07 08:05:09"


def test_local_midnight_converts_to_utc_for_hikvision() -> None:
    day = local(2026, 11, 7)
    expected = datetime.fromtimestamp(day, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert hik_iso(day) == expected


def test_day_end_is_next_local_midnight() -> None:
    day = local(2026, 11, 7)
    assert day_end(day) == local(2026, 11, 8)
    # DST günü (Avrupa'da yaz saati 29 Mart): bilgisayarın bölgesi ne olursa olsun takvim günü sonuna gider
    dst = local(2026, 3, 29)
    assert day_end(dst) == local(2026, 3, 30)
    assert time.localtime(day_end(dst))[3:6] == (0, 0, 0)


def _last_sunday(year: int, month: int) -> int:
    return 31 - (date(year, month, 31).weekday() + 1) % 7


class Berlin(tzinfo):
    """Orta Avrupa kuralı (CET/CEST; geçiş Mart ve Ekim'in son pazarı 01:00 UTC). Windows'ta tzdata olmadığı
    için `zoneinfo` yerine; yalnız testte."""

    def _bounds(self, year: int) -> tuple[datetime, datetime]:
        return (datetime(year, 3, _last_sunday(year, 3), 1, tzinfo=UTC),
                datetime(year, 10, _last_sunday(year, 10), 1, tzinfo=UTC))

    def fromutc(self, dt: datetime) -> datetime:
        start, end = self._bounds(dt.year)
        summer = start <= dt.replace(tzinfo=UTC) < end
        wall = (dt + timedelta(hours=2 if summer else 1)).replace(tzinfo=self)
        repeated = not summer and wall.month == 10 and wall.day == _last_sunday(dt.year, 10) and wall.hour == 2
        return wall.replace(fold=1) if repeated else wall

    def utcoffset(self, dt: datetime | None) -> timedelta:
        assert dt is not None
        naive = dt.replace(tzinfo=None, fold=0)
        begin = datetime(dt.year, 3, _last_sunday(dt.year, 3), 2)  # noqa: DTZ001 - duvar saati karşılaştırması
        end = datetime(dt.year, 10, _last_sunday(dt.year, 10), 3)  # noqa: DTZ001
        summer = begin <= naive < end and not (dt.fold and naive >= end - timedelta(hours=1))
        return timedelta(hours=2 if summer else 1)

    def dst(self, dt: datetime | None) -> timedelta:
        return self.utcoffset(dt) - timedelta(hours=1)

    def tzname(self, dt: datetime | None) -> str:
        return "CEST" if self.dst(dt) else "CET"


BERLIN = Berlin()


def berlin(y: int, mo: int, d: int, h: int = 0, mi: int = 0, s: int = 0) -> float:
    return datetime(y, mo, d, h, mi, s, tzinfo=BERLIN).timestamp()


def test_berlin_test_zone_is_sane() -> None:
    assert berlin(2026, 1, 1) == utc(2025, 12, 31, 23)
    assert berlin(2026, 7, 1) == utc(2026, 6, 30, 22)
    assert berlin(2026, 3, 29, 3) - berlin(2026, 3, 29, 1) == 3600       # 02:00 → 03:00 atlanır
    assert berlin(2026, 10, 25, 3) - berlin(2026, 10, 25, 2) == 2 * 3600  # 02:00–03:00 iki kez


def test_dst_days_in_a_dst_zone() -> None:
    spring, autumn = berlin(2026, 3, 29), berlin(2026, 10, 25)
    assert day_end(spring, BERLIN) - spring == 23 * 3600
    assert day_end(autumn, BERLIN) - autumn == 25 * 3600
    assert day_end(spring, BERLIN) == berlin(2026, 3, 30)
    assert day_end(autumn, BERLIN) == berlin(2026, 10, 26)
    assert trassir_time(spring, BERLIN) == "20260329T000000"
    assert trassir_time(day_end(spring, BERLIN) - 1, BERLIN) == "20260329T235959"
    assert hik_iso(spring) == "2026-03-28T23:00:00Z"
    assert hik_iso(autumn) == "2026-10-24T22:00:00Z"
    assert dahua_time(berlin(2026, 10, 25, 23, 59, 59), "-", BERLIN) == "2026-10-25 23:59:59"
    assert parse_dahua_find("found=1\r\nitems[0].StartTime=2026-03-29 01:00:00\r\n"
                            "items[0].EndTime=2026-03-29 04:00:00\r\n", BERLIN) == [
        (berlin(2026, 3, 29, 1), berlin(2026, 3, 29, 1) + 2 * 3600)]


def test_trassir_timeline_on_25_hour_day() -> None:
    autumn = berlin(2026, 10, 25)
    obj = {"day_start": "2026-10-25", "timeline": [{"begin": 0, "end": 90000}, {"begin": 89000, "end": 95000}]}
    assert parse_trassir_timeline(obj, autumn, tz=BERLIN) == [(autumn, autumn + 25 * 3600)]


# MARK: - Aralık birleştirme


def test_merge_ranges() -> None:
    assert merge_ranges([]) == []
    assert merge_ranges([(10, 20), (0, 5), (19, 30), (31.5, 40), (50, 50), (60, 55)]) == [(0, 5), (10, 40)]
    assert merge_ranges([(0, 10), (12.5, 20)]) == [(0, 10), (12.5, 20)]
    assert merge_ranges([(0, 10), (2, 3)]) == [(0, 10)]
    assert merge_ranges([(0, 10), (12, 20)], gap=0) == [(0, 10), (12, 20)]


# MARK: - TRASSIR ayrıştırıcıları (R6)


def test_trassir_calendar_object_and_list() -> None:
    assert parse_trassir_calendar({"calendar": ["2026-11-01", "2026-11-07", 5, "bozuk"]}) == {
        "2026-11-01", "2026-11-07"}
    lst = [{"token": "a", "calendar": ["2026-11-02"]}, {"token": "b", "calendar": ["2026-11-03"]}]
    assert parse_trassir_calendar(lst) == {"2026-11-02", "2026-11-03"}
    assert parse_trassir_calendar(lst, token="b") == {"2026-11-03"}
    assert parse_trassir_calendar({"calendar": []}) == set()


def test_trassir_calendar_bad_shapes() -> None:
    for bad in ({"x": 1}, "metin", [1, 2], {"calendar": "2026-11-01"}):
        with pytest.raises(RecorderError) as e:
            parse_trassir_calendar(bad)
        assert e.value.kind == "unexpected"
    with pytest.raises(RecorderError) as e:
        parse_trassir_calendar({"success": 0, "error_code": "bad sid"})
    assert e.value.kind == "trassir"


def test_trassir_timeline_relative_to_day_start() -> None:
    day = local(2026, 11, 7)
    obj = [{"token": "t", "day_start": "2026-11-07",
            "timeline": [{"begin": 3600, "end": 7200}, {"begin": 7201, "end": 7300}, {"begin": "x", "end": 1}]}]
    assert parse_trassir_timeline(obj, day) == [(day + 3600, day + 7300)]
    assert parse_trassir_timeline(obj[0], day) == [(day + 3600, day + 7300)]
    assert parse_trassir_timeline(obj, day, token="baska") == []


def test_trassir_timeline_day_mismatch_is_empty() -> None:
    day = local(2026, 11, 7)
    obj = {"day_start": "2026-11-06", "timeline": [{"begin": 0, "end": 100}]}
    assert parse_trassir_timeline(obj, day) == []


def test_trassir_timeline_bad_shapes() -> None:
    day = local(2026, 11, 7)
    for bad in ({"timeline": []}, {"day_start": "2026-11-07"}, {"day_start": "dün", "timeline": []}, 7, [3]):
        with pytest.raises(RecorderError) as e:
            parse_trassir_timeline(bad, day)
        assert e.value.kind == "unexpected"


# MARK: - Hikvision ayrıştırıcıları (R7)

NS = 'xmlns="http://www.hikvision.com/ver20/XMLSchema"'


def hik_result(status: str, spans: list[tuple[str, str]]) -> bytes:
    items = "".join(
        f"<searchMatchItem><trackID>101</trackID><timeSpan><startTime>{a}</startTime><endTime>{b}</endTime>"
        f"</timeSpan></searchMatchItem>" for a, b in spans)
    return (f'<?xml version="1.0" encoding="UTF-8"?><CMSearchResult {NS}><searchID>x</searchID>'
            f"<responseStatus>true</responseStatus><responseStatusStrg>{status}</responseStatusStrg>"
            f"<numOfMatches>{len(spans)}</numOfMatches><matchList>{items}</matchList></CMSearchResult>").encode()


def utc(y: int, mo: int, d: int, h: int = 0, mi: int = 0, s: int = 0) -> float:
    return datetime(y, mo, d, h, mi, s, tzinfo=UTC).timestamp()


def test_parse_hik_search() -> None:
    ranges, status = parse_hik_search(hik_result("MORE", [("2026-11-07T08:00:00Z", "2026-11-07T09:00:00Z"),
                                                          ("2026-11-07T10:00:00", "2026-11-07T10:30:00")]))
    assert status == "MORE"
    assert ranges == [(utc(2026, 11, 7, 8), utc(2026, 11, 7, 9)), (utc(2026, 11, 7, 10), utc(2026, 11, 7, 10, 30))]
    ranges, status = parse_hik_search(hik_result("NO MATCHES", []))
    assert (ranges, status) == ([], "NO MATCHES")
    ranges, status = parse_hik_search(hik_result("OK", [("2026-11-07T08:00:00+03:00", "2026-11-07T08:10:00+03:00")]))
    assert ranges == [(utc(2026, 11, 7, 5), utc(2026, 11, 7, 5, 10))]


@pytest.mark.parametrize("bad", [b"", b"<bozuk", b"<ResponseStatus><statusCode>4</statusCode></ResponseStatus>",
                                 b"<CMSearchResult><responseStatusStrg>FAIL</responseStatusStrg></CMSearchResult>"])
def test_parse_hik_search_bad(bad: bytes) -> None:
    with pytest.raises(RecorderError) as e:
        parse_hik_search(bad)
    assert e.value.kind == "unexpected"


def test_parse_hik_daily() -> None:
    xml = (f"<trackDailyDistribution {NS}><dayList>"
           "<day><id>1</id><dayOfMonth>1</dayOfMonth><record>true</record><recordType>time</recordType></day>"
           "<day><id>2</id><dayOfMonth>2</dayOfMonth><record>false</record></day>"
           "<day><id>7</id><dayOfMonth>7</dayOfMonth><record>true</record></day>"
           "</dayList></trackDailyDistribution>").encode()
    assert parse_hik_daily(xml) == {1, 7}
    for bad in (b"", b"<x", b"<trackDailyDistribution/>"):
        with pytest.raises(RecorderError) as e:
            parse_hik_daily(bad)
        assert e.value.kind == "unexpected"


# MARK: - Dahua ayrıştırıcısı (R8)


def dahua_page(items: list[tuple[str, str]]) -> str:
    lines = [f"found={len(items)}"]
    for i, (a, b) in enumerate(items):
        lines += [f"items[{i}].Channel=0", f"items[{i}].StartTime={a}", f"items[{i}].EndTime={b}",
                  f"items[{i}].Type=dav"]
    return "\r\n".join(lines) + "\r\n"


def test_parse_dahua_find() -> None:
    text = dahua_page([("2026-11-07 08:00:00", "2026-11-07 09:00:00"), ("2026-11-07 09:00:01", "2026-11-07 10:00:00")])
    assert parse_dahua_find(text) == [(local(2026, 11, 7, 8), local(2026, 11, 7, 9)),
                                      (local(2026, 11, 7, 9, 0, 1), local(2026, 11, 7, 10))]
    assert parse_dahua_find("found=0\r\n") == []
    assert parse_dahua_find("found=1\r\nitems[0].StartTime=bozuk\r\nitems[0].EndTime=2026-11-07 10:00:00\r\n") == []
    for bad in ("", "Error\r\nBad Request!", "OK"):
        with pytest.raises(RecorderError) as e:
            parse_dahua_find(bad)
        assert e.value.kind == "unexpected"


# MARK: - _DeviceHTTP.post / stream


def test_device_post_sends_body_and_maps_errors() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/ok":
            return httpx.Response(200, content=b"<ok/>")
        if request.url.path == "/auth":
            return httpx.Response(401)
        if request.url.path == "/slow":
            raise httpx.ReadTimeout("zaman aşımı", request=request)
        return httpx.Response(500)

    http = fake_http(handler)
    assert http.post("/ok", b"<x/>", "application/xml", [("a", "b c")]) == b"<ok/>"
    assert seen[0].method == "POST" and seen[0].content == b"<x/>"
    assert seen[0].headers["content-type"] == "application/xml"
    assert query(seen[0]) == {"a": "b c"}
    for path, kind in (("/auth", "unauthorized"), ("/slow", "unreachable"), ("/err", "http")):
        with pytest.raises(RecorderError) as e:
            http.post(path, b"", "text/plain")
        assert e.value.kind == kind
    with pytest.raises(RecorderError) as e:
        http.post("/err", b"", "text/plain")
    assert e.value.status == 500


def test_device_stream_yields_chunks_and_maps_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        match request.url.path:
            case "/file":
                return httpx.Response(200, content=b"abc" * 1000)
            case "/auth":
                return httpx.Response(401)
            case "/slow":
                raise httpx.ConnectTimeout("zaman aşımı", request=request)
            case "/cut":
                raise httpx.ReadError("koptu", request=request)
        return httpx.Response(404)

    http = fake_http(handler)
    assert b"".join(http.stream(f"http://{HOST}:80/file", 600)) == b"abc" * 1000
    for path, kind in (("/auth", "unauthorized"), ("/slow", "unreachable"), ("/cut", "unreachable"),
                       ("/x", "http")):
        with pytest.raises(RecorderError) as e:
            list(http.stream(f"http://{HOST}:80{path}", 5))
        assert e.value.kind == kind
    with pytest.raises(RecorderError) as e:
        list(http.stream("http://baska.test:80/file", 5))
    assert e.value.kind == "unexpected"


def test_unsupported_error() -> None:
    err = RecorderError.unsupported()
    assert err.kind == "unsupported"
    assert str(err) == "Bu kayıt cihazında dışa aktarma henüz desteklenmiyor."


# MARK: - Hikvision bağdaştırıcısı


def test_hikvision_stream_url_is_utc_track_url() -> None:
    a = HikvisionArchive(HikvisionClient(fake_http(lambda r: httpx.Response(500)), HOST, 554))
    start = utc(2026, 11, 7, 8)
    assert a.stream_url(CH1, start, start + 600, False, 1) == (
        f"rtsp://{HOST}:554/Streaming/tracks/101?starttime=20261107T080000Z&endtime=20261107T081000Z")
    assert a.stream_url(CH1, start, None, True, 4) == (
        f"rtsp://{HOST}:554/Streaming/tracks/102?starttime=20261107T080000Z&endtime=20261108T080000Z")
    assert "/tracks/201?" in a.stream_url(CH2_NOSUB, start, None, True, 1)
    assert a.speeds == (1, 2, 4) and not a.can_export
    with pytest.raises(RecorderError) as e:
        a.export(CH1, start, start + 60)
    assert e.value.kind == "unsupported"
    a.stop("rtsp://x/y")
    a.keep_alive("rtsp://x/y")


def test_hikvision_timeline_pages_with_more() -> None:
    day = local(2026, 11, 7)
    bodies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST" and request.url.path == "/ISAPI/ContentMgmt/search"
        body = request.content.decode()
        bodies.append(body)
        if "<searchResultPostion>0<" in body:
            return httpx.Response(200, content=hik_result("MORE", [(hik_iso(day - 600), hik_iso(day + 3600))]))
        return httpx.Response(200, content=hik_result("OK", [(hik_iso(day + 3601), hik_iso(day + 7200)),
                                                             (hik_iso(day + 86000), hik_iso(day + 90000))]))

    a = HikvisionArchive(HikvisionClient(fake_http(handler), HOST, 554))
    assert a.timeline(CH1, day) == [(day, day + 7200), (day + 86000, day_end(day))]
    assert len(bodies) == 2
    assert "<searchResultPostion>400<" in bodies[1]
    assert "<trackID>101</trackID>" in bodies[0]
    assert f"<startTime>{hik_iso(day)}</startTime>" in bodies[0]
    assert f"<endTime>{hik_iso(day_end(day))}</endTime>" in bodies[0]
    assert "<maxResults>400</maxResults>" in bodies[0]
    assert "recordType.meta.std-cgi.com" in bodies[0]
    search_ids = {b.split("<searchID>")[1].split("</searchID>")[0] for b in bodies}
    assert len(search_ids) == 1


def test_hikvision_timeline_no_matches_and_page_limit() -> None:
    a = HikvisionArchive(HikvisionClient(fake_http(lambda r: httpx.Response(
        200, content=hik_result("NO MATCHES", []))), HOST, 554))
    assert a.timeline(CH1, local(2026, 11, 7)) == []
    calls: list[int] = []

    def more(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, content=hik_result("MORE", []))

    a = HikvisionArchive(HikvisionClient(fake_http(more), HOST, 554))
    assert a.timeline(CH1, local(2026, 11, 7)) == []
    assert len(calls) == 10


def test_hikvision_calendar() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"<trackDailyDistribution><dayList><day><dayOfMonth>3</dayOfMonth>"
                                           b"<record>true</record></day></dayList></trackDailyDistribution>")

    a = HikvisionArchive(HikvisionClient(fake_http(handler), HOST, 554))
    assert a.calendar(CH1, 2026, 11) == {3}
    assert seen[0].url.path == "/ISAPI/ContentMgmt/record/tracks/101/dailyDistribution"
    assert b"<year>2026</year><monthOfYear>11</monthOfYear>" in seen[0].content


# MARK: - Dahua bağdaştırıcısı


def test_dahua_stream_url_is_local_time() -> None:
    a = DahuaArchive(DahuaClient(fake_http(lambda r: httpx.Response(500)), HOST, 554))
    start = local(2026, 11, 7, 8)
    assert a.stream_url(CH1, start, start + 600, True, 2) == (
        f"rtsp://{HOST}:554/cam/playback?channel=1&subtype=1"
        "&starttime=2026_11_07_08_00_00&endtime=2026_11_07_08_10_00")
    assert a.stream_url(CH1, start, None, False, 1).endswith(
        f"subtype=0&starttime=2026_11_07_08_00_00&endtime={dahua_time(start + 86400, '_')}")
    assert "subtype=0" in a.stream_url(CH2_NOSUB, start, None, True, 1)
    assert a.speeds == (1, 2, 4) and not a.can_export


class FakeDahua:
    """mediaFileFind.cgi durum makinesi: iki sayfa (100 + 1 öğe)."""

    def __init__(self, pages: list[list[tuple[str, str]]], create: str = "result=7\r\n") -> None:
        self.pages = pages
        self.create = create
        self.actions: list[dict[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/cgi-bin/mediaFileFind.cgi"
        q = query(request)
        self.actions.append(q)
        match q["action"]:
            case "factory.create":
                return httpx.Response(200, text=self.create)
            case "findFile":
                return httpx.Response(200, text="OK\r\n")
            case "findNextFile":
                page = self.pages.pop(0) if self.pages else []
                return httpx.Response(200, text=dahua_page(page))
        return httpx.Response(200, text="OK\r\n")


def test_dahua_timeline_two_pages_then_close_and_destroy() -> None:
    day = local(2026, 11, 7)
    first = [(dahua_time(day + i * 60, "-"), dahua_time(day + i * 60 + 59, "-")) for i in range(100)]
    fake = FakeDahua([first, [(dahua_time(day + 7200, "-"), dahua_time(day + 7300, "-"))]])
    a = DahuaArchive(DahuaClient(fake_http(fake), HOST, 554))
    assert a.timeline(CH1, day) == [(day, day + 99 * 60 + 59), (day + 7200, day + 7300)]
    names = [q["action"] for q in fake.actions]
    assert names == ["factory.create", "findFile", "findNextFile", "findNextFile", "close", "destroy"]
    find = fake.actions[1]
    assert find["object"] == "7" and find["condition.Channel"] == "1"
    assert find["condition.StartTime"] == dahua_time(day, "-")
    assert find["condition.EndTime"] == dahua_time(day_end(day), "-")
    assert find["condition.Types[0]"] == "dav"
    assert fake.actions[2]["count"] == "100" and fake.actions[2]["object"] == "7"


def test_dahua_find_cleans_up_on_error() -> None:
    fake = FakeDahua([])
    original = fake.__call__

    def handler(request: httpx.Request) -> httpx.Response:
        if query(request)["action"] == "findNextFile":
            fake.actions.append(query(request))
            return httpx.Response(200, text="bozuk")
        return original(request)

    a = DahuaArchive(DahuaClient(fake_http(handler), HOST, 554))
    with pytest.raises(RecorderError):
        a.timeline(CH1, local(2026, 11, 7))
    assert [q["action"] for q in fake.actions][-2:] == ["close", "destroy"]
    bad = DahuaArchive(DahuaClient(fake_http(FakeDahua([], create="Error")), HOST, 554))
    with pytest.raises(RecorderError) as e:
        bad.timeline(CH1, local(2026, 11, 7))
    assert e.value.kind == "unexpected"


def test_dahua_calendar_days_from_month_search() -> None:
    fake = FakeDahua([[("2026-11-01 10:00:00", "2026-11-01 11:00:00"),
                       ("2026-11-03 23:30:00", "2026-11-04 00:30:00"),
                       ("2026-10-31 23:00:00", "2026-11-01 00:10:00"),
                       ("2026-11-30 23:00:00", "2026-12-01 01:00:00")]])
    a = DahuaArchive(DahuaClient(fake_http(fake), HOST, 554))
    assert a.calendar(CH1, 2026, 11) == {1, 3, 4, 30}
    find = fake.actions[1]
    assert find["condition.StartTime"] == "2026-11-01 00:00:00"
    assert find["condition.EndTime"] == "2026-12-01 00:00:00"


# MARK: - TRASSIR bağdaştırıcısı


class FakeTrassir:
    """TRASSIR SDK: login, get_video, archive_command, archive_status, jit-export-*."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, str]]] = []
        self.timeline: list[object] = []      # sırayla verilecek archive_status yanıtları
        self.calendar: list[object] = []
        self.download: list[httpx.Response] = []
        self.create: list[httpx.Response] = []
        self.command_status = 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        q = query(request)
        path = request.url.path
        self.requests.append((path, q))
        if path == "/login":
            return httpx.Response(200, text='{"success":1,"sid":"S1"}')
        if path == "/get_video":
            return httpx.Response(200, text='{"success":1,"token":"TOK1"}')
        if path == "/archive_command":
            return httpx.Response(self.command_status, text='{"success":1}')
        if path == "/archive_status":
            source = self.timeline if q["type"] == "timeline" else self.calendar
            return httpx.Response(200, text=json.dumps(source.pop(0) if source else []))
        if path == "/jit-export-create-task":
            if self.create:
                return self.create.pop(0)
            return httpx.Response(200, text='{"success":1,"task_id":"T9"}')
        if path == "/jit-export-download":
            return self.download.pop(0)
        return httpx.Response(404)

    def paths(self) -> list[str]:
        return [p for p, _ in self.requests]

    def last(self, path: str) -> dict[str, str]:
        return [q for p, q in self.requests if p == path][-1]


def trassir(fake: FakeTrassir) -> TrassirArchive:
    client = TrassirClient(fake_http(fake, https=True, port=8080), HOST, 555, "u", "p")
    return TrassirArchive(client, sleep=lambda s: None)


def test_trassir_stream_url_plays_archive_token() -> None:
    fake = FakeTrassir()
    a = trassir(fake)
    start = local(2026, 11, 7, 8)
    assert a.stream_url(GUID, start, start + 600, True, 8) == f"rtsp://{HOST}:555/TOK1"
    assert fake.last("/get_video")["stream"] == "archive_sub"
    assert fake.last("/get_video")["container"] == "rtsp"
    cmd = fake.last("/archive_command")
    assert cmd == {"command": "play", "start": "20261107T080000", "stop": "20261107T081000", "speed": "8",
                   "token": "TOK1", "sid": "S1"}
    a.stream_url(GUID, start, None, False, 1)
    assert fake.last("/get_video")["stream"] == "archive_main"
    assert "stop" not in fake.last("/archive_command")
    nosub = RecorderChannel(id="g-2", name="", number=None, has_substream=False)
    a.stream_url(nosub, start, None, True, 1)
    assert fake.last("/get_video")["stream"] == "archive_main"
    assert a.speeds == (1, 2, 4, 8, 16) and a.can_export


def test_trassir_stop_sends_command_and_swallows_errors() -> None:
    fake = FakeTrassir()
    a = trassir(fake)
    a.stop(f"rtsp://{HOST}:555/TOK1")
    assert fake.last("/archive_command") == {"command": "stop", "token": "TOK1", "sid": "S1"}
    fake.command_status = 500
    before = len(fake.requests)
    a.stop(f"rtsp://{HOST}:555/TOK1")                 # hata yutulur
    # tek istek: yeniden giriş yok, ikinci stop yok, paylaşılan sid korunur
    assert fake.paths()[before:] == ["/archive_command"]
    assert fake.paths().count("/login") == 1
    assert a._live._sid == "S1"
    n = len(fake.requests)
    a.stop("rtsp://x/../bozuk jeton")
    assert len(fake.requests) == n


def test_trassir_keep_alive_delegates_to_live_client() -> None:
    fake = FakeTrassir()
    a = trassir(fake)
    a.keep_alive(f"rtsp://{HOST}:555/TOK1")
    path, _ = fake.requests[-1]
    assert path == "/TOK1"


def test_trassir_timeline_play_status_stop_with_retry() -> None:
    fake = FakeTrassir()
    day = local(2026, 11, 7)
    fake.timeline = [[], [{"token": "TOK1", "day_start": "2026-11-07", "timeline": [{"begin": 60, "end": 120}]}]]
    a = trassir(fake)
    assert a.timeline(GUID, day) == [(day + 60, day + 120)]
    assert fake.last("/get_video")["stream"] == "archive_main"
    plays = [q for p, q in fake.requests if p == "/archive_command"]
    assert plays[0]["command"] == "play" and plays[0]["start"] == "20261107T000000"
    assert plays[0]["stop"] == "20261107T235959" and plays[0]["speed"] == "1"
    assert plays[-1] == {"command": "stop", "token": "TOK1", "sid": "S1"}
    assert [q["type"] for p, q in fake.requests if p == "/archive_status"] == ["timeline", "timeline"]


def test_trassir_timeline_day_mismatch_warns_once(caplog: pytest.LogCaptureFixture) -> None:
    fake = FakeTrassir()
    day = local(2026, 11, 7)
    other = {"day_start": "2026-11-06", "timeline": [{"begin": 0, "end": 10}]}
    fake.timeline = [other, other, other]
    a = trassir(fake)
    with caplog.at_level("WARNING", logger="bantvision.live.archive"):
        assert a.timeline(GUID, day) == []
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "TOK1" not in caplog.text and "S1" not in caplog.text
    assert fake.paths().count("/archive_status") == 3
    assert fake.last("/archive_command")["command"] == "stop"


def test_trassir_calendar() -> None:
    fake = FakeTrassir()
    fake.calendar = [{"calendar": ["2026-10-31", "2026-11-01", "2026-11-07"]}]
    a = trassir(fake)
    assert a.calendar(GUID, 2026, 11) == {1, 7}
    assert fake.last("/archive_status")["type"] == "calendar"
    assert fake.last("/archive_command")["command"] == "stop"


def test_trassir_bad_status_raises_and_still_stops() -> None:
    fake = FakeTrassir()
    fake.timeline = [{"bilinmeyen": 1}]
    a = trassir(fake)
    with pytest.raises(RecorderError) as e:
        a.timeline(GUID, local(2026, 11, 7))
    assert e.value.kind == "unexpected"
    assert fake.last("/archive_command")["command"] == "stop"


def test_trassir_export_waits_until_ready_and_streams() -> None:
    fake = FakeTrassir()
    fake.download = [httpx.Response(200, text='{"success":0,"error_code":"not ready"}'),
                     httpx.Response(404, text="hazır değil"),
                     httpx.Response(200, content=b"\x00\x00\x00\x18ftypmp42" + b"v" * 5000)]
    a = trassir(fake)
    start = local(2026, 11, 7, 8)
    data = b"".join(a.export(GUID, start, start + 60))
    assert data.startswith(b"\x00\x00\x00\x18ftyp") and len(data) == 12 + 5000
    create = [r for r in fake.requests if r[0] == "/jit-export-create-task"]
    assert create[0][1] == {"sid": "S1"}
    dl = fake.last("/jit-export-download")
    assert dl == {"sid": "S1", "task_id": "T9"}
    assert fake.paths().count("/jit-export-download") == 3


def test_trassir_export_body() -> None:
    bodies: list[dict[str, object]] = []
    fake = FakeTrassir()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/jit-export-create-task":
            bodies.append(json.loads(request.content))
            assert request.headers["content-type"] == "application/json"
        return fake(request)

    fake.download = [httpx.Response(200, content=b"\x00\x00\x00\x18ftyp")]
    client = TrassirClient(fake_http(handler, https=True, port=8080), HOST, 555, "u", "p")
    a = TrassirArchive(client)
    list(a.export(GUID, 1_700_000_000.5, 1_700_000_060.0))
    assert bodies == [{"resource_guid": "g-1", "start_ts": 1_700_000_000_500_000, "end_ts": 1_700_000_060_000_000,
                       "is_hardware": 0, "prefer_substream": 0}]


def test_trassir_export_create_is_not_retried_on_http_error() -> None:
    fake = FakeTrassir()
    fake.create = [httpx.Response(500)]
    a = trassir(fake)
    with pytest.raises(RecorderError) as e:
        a.export(GUID, 0, 60)
    assert e.value.kind == "http"
    assert fake.paths().count("/jit-export-create-task") == 1
    assert fake.paths().count("/login") == 1


def test_trassir_export_create_relogs_once_on_session_error() -> None:
    fake = FakeTrassir()
    fake.create = [httpx.Response(200, text='{"success":0,"error_code":"invalid sid"}')]
    fake.download = [httpx.Response(200, content=b"\x00\x00\x00\x18ftypmp42")]
    a = trassir(fake)
    assert b"".join(a.export(GUID, 0, 60)).startswith(b"\x00\x00\x00\x18ftyp")
    assert fake.paths().count("/jit-export-create-task") == 2
    assert fake.paths().count("/login") == 2


def test_trassir_export_rejects_non_mp4_body() -> None:
    fake = FakeTrassir()
    fake.download = [httpx.Response(200, content=b"<html>giris sayfasi</html>")]
    a = trassir(fake)
    with pytest.raises(RecorderError) as e:
        a.export(GUID, 0, 60)
    assert e.value == RecorderError.unexpected("dışa aktarma yanıtı")
    assert fake.paths().count("/jit-export-download") == 1


class TrackedStream(httpx.SyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        yield from self.chunks

    def close(self) -> None:
        self.closed = True


def test_trassir_export_close_before_first_next_closes_response() -> None:
    fake = FakeTrassir()
    body = TrackedStream([b"\x00\x00\x00\x18ftypmp42", b"v" * 100, b"w" * 100])
    fake.download = [httpx.Response(200, stream=body)]
    a = trassir(fake)
    stream = a.export(GUID, 0, 60)
    assert not body.closed
    stream.close()
    assert body.closed
    with pytest.raises(StopIteration):
        next(stream)
    body2 = TrackedStream([b"\x00\x00\x00\x18ftypmp42", b"v" * 100])
    fake.download = [httpx.Response(200, stream=body2)]
    with a.export(GUID, 0, 60) as s2:
        assert next(s2).startswith(b"\x00\x00\x00\x18ftyp")
    assert body2.closed


def test_trassir_export_gives_up_after_20_tries() -> None:
    fake = FakeTrassir()
    fake.download = [httpx.Response(200, text='{"success":0}') for _ in range(20)]
    a = trassir(fake)
    with pytest.raises(RecorderError) as e:
        a.export(GUID, 0, 60)
    assert e.value.kind == "trassir"
    assert fake.paths().count("/jit-export-download") == 20


def test_trassir_export_auth_error_is_not_retried() -> None:
    fake = FakeTrassir()
    fake.download = [httpx.Response(200, text='{"success":0,"error_code":"invalid user session"}')]
    a = trassir(fake)
    with pytest.raises(RecorderError) as e:
        a.export(GUID, 0, 60)
    assert e.value.kind == "unauthorized"
    fake.download = [httpx.Response(200, content=b"") for _ in range(20)]   # boş gövde: hazır değil sayılır
    with pytest.raises(RecorderError) as e:
        a.export(GUID, 0, 60)
    assert e.value.kind == "trassir"


# MARK: - Dosya kaynağı (R9)


@pytest.fixture
def video(tmp_path: pathlib.Path) -> Iterator[str]:
    path = str(tmp_path / "v.avi")
    writer = cv2.VideoWriter(path, cv2.VideoWriter.fourcc(*"MJPG"), 10.0, (64, 48))
    for _ in range(30):
        writer.write(np.zeros((48, 64, 3), np.uint8))
    writer.release()
    yield path


def test_file_archive(video: str) -> None:
    a = FileArchive(video)
    assert a.stream_url(CH1, 1.5, None, False, 2) == video
    assert a.calendar(CH1, 1970, 1) == {1}
    assert a.calendar(CH1, 2026, 11) == set()
    assert a.timeline(CH1, 0) == [(0.0, pytest.approx(3.0))]
    assert a.timeline(CH1, 86400) == []
    assert a.speeds == (1, 2, 4) and not a.can_export
    with pytest.raises(RecorderError) as e:
        a.export(CH1, 0, 1)
    assert e.value.kind == "unsupported"


def test_file_archive_empty_duration(video: str) -> None:
    a = FileArchive(video)
    a._duration = 0.0
    assert a.timeline(CH1, 0) == []


def test_file_archive_missing_file(tmp_path: pathlib.Path) -> None:
    a = FileArchive(os.fspath(tmp_path / "yok.mp4"))
    with pytest.raises(RecorderError) as e:
        a.timeline(CH1, 0)
    assert e.value.kind == "unexpected"


# MARK: - Marka seçimi


def test_make_archive_dispatches_by_brand() -> None:
    http = fake_http(lambda r: httpx.Response(500))
    assert isinstance(make_archive(TrassirClient(http, HOST, 555, "u", "p"), RecorderBrand.TRASSIR), TrassirArchive)
    assert isinstance(make_archive(HikvisionClient(http, HOST, 554), RecorderBrand.HIKVISION), HikvisionArchive)
    assert isinstance(make_archive(DahuaClient(http, HOST, 554), "dahua"), DahuaArchive)  # type: ignore[arg-type]
    with pytest.raises(RecorderError) as e:
        make_archive(DahuaClient(http, HOST, 554), RecorderBrand.TRASSIR)
    assert e.value.kind == "unexpected"
    with pytest.raises(RecorderError) as e:
        make_archive(DahuaClient(http, HOST, 554), "uniview")
    assert e.value == RecorderError.unexpected("bilinmeyen marka")
    assert make_archive(DahuaClient(http, HOST, 554), RecorderBrand.DAHUA, BERLIN).tz is BERLIN


def test_unsupported_speed_is_a_programming_error(tmp_path: pathlib.Path) -> None:
    http = fake_http(lambda r: httpx.Response(500))
    adapters = [HikvisionArchive(HikvisionClient(http, HOST, 554)), DahuaArchive(DahuaClient(http, HOST, 554)),
                FileArchive(os.fspath(tmp_path / "v.mp4")),
                TrassirArchive(TrassirClient(http, HOST, 555, "u", "p"))]
    for a in adapters:
        with pytest.raises(ValueError, match="hız 3 desteklenmiyor"):
            a.stream_url(CH1, 0, None, False, 3)
    with pytest.raises(ValueError):
        adapters[0].stream_url(CH1, 0, None, False, 8)       # 8× yalnız TRASSIR


def test_dahua_uses_given_zone() -> None:
    spring = berlin(2026, 3, 29)
    fake = FakeDahua([[]])
    a = DahuaArchive(DahuaClient(fake_http(fake), HOST, 554), BERLIN)
    assert a.timeline(CH1, spring) == []
    assert fake.actions[1]["condition.StartTime"] == "2026-03-29 00:00:00"
    assert fake.actions[1]["condition.EndTime"] == "2026-03-30 00:00:00"
    assert a.stream_url(CH1, spring, None, False, 1).endswith(
        "starttime=2026_03_29_00_00_00&endtime=2026_03_30_01_00_00")


def test_module_exports() -> None:
    for name in ("ArchiveClient", "make_archive", "merge_ranges", "parse_hik_search"):
        assert name in arc.__all__


def test_session_error_matches_whole_words_only() -> None:
    """`sid` yalnızca tam kelime olarak oturum hatasıdır ("consider" gibi kelime içi eşleşme değil)."""
    assert arc._is_session_error(RecorderError.trassir("invalid sid"))
    assert arc._is_session_error(RecorderError.trassir("SID expired"))
    assert arc._is_session_error(RecorderError.trassir("invalid user session"))
    assert not arc._is_session_error(RecorderError.trassir("please consider retrying"))
    assert not arc._is_session_error(RecorderError.trassir("residual task"))
    assert not arc._is_session_error(RecorderError.unexpected("invalid sid"))
