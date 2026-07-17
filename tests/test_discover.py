from datetime import date

from stages.discover import _page_re, _select_pages


def test_page_re_accepts_timeline_urls():
    r = _page_re("jack")
    for url in [
        "https://twitter.com/jack",
        "http://twitter.com/jack/",
        "https://www.twitter.com/jack",
        "https://mobile.twitter.com/jack?max_id=553222199147245568",
        "https://twitter.com/jack/with_replies",
        "https://twitter.com/jack?page=3",
        "https://x.com/jack",
        "https://twitter.com/JACK?lang=en",
    ]:
        assert r.match(url), url


def test_page_re_rejects_non_timeline_urls():
    r = _page_re("jack")
    for url in [
        "https://twitter.com/jack/status/553222199147245568",
        "https://twitter.com/jackson",           # prefix-colliding handle
        "https://twitter.com/jack/media",
        "https://twitter.com/jack/followers",
        "https://twitter.com/jack/lists/tech",
    ]:
        assert not r.match(url), url


def _row(ts, original, code="200"):
    return {"timestamp": ts, "original": original, "statuscode": code}


def test_select_pages_date_window_and_bucketing():
    rows = [
        _row("20140101120000", "https://twitter.com/jack"),
        # Same day + variant, later capture: collapses into one bucket.
        _row("20140101180000", "https://twitter.com/jack?lang=fr"),
        # Same day, distinct pagination: kept.
        _row("20140101190000", "https://twitter.com/jack?page=2"),
        # Same day, distinct variant: kept.
        _row("20140101200000", "https://twitter.com/jack/with_replies"),
        # Before --from: dropped.
        _row("20120101120000", "https://twitter.com/jack"),
        # Within 30-day grace after --to: kept.
        _row("20150110120000", "https://twitter.com/jack"),
        # Beyond the grace: dropped.
        _row("20150301120000", "https://twitter.com/jack"),
    ]
    pages = _select_pages(rows, date_from=date(2013, 1, 1), date_to=date(2014, 12, 31),
                          max_page_captures=400)
    originals = [p["original"] for p in pages]
    assert originals == [
        "https://twitter.com/jack",
        "https://twitter.com/jack?page=2",
        "https://twitter.com/jack/with_replies",
        "https://twitter.com/jack",
    ]


def test_select_pages_prefers_200s_then_earliest():
    rows = [
        _row("20140101100000", "https://twitter.com/jack", code="301"),
        _row("20140101150000", "https://twitter.com/jack", code="200"),
        _row("20140101180000", "https://twitter.com/jack", code="200"),
    ]
    pages = _select_pages(rows, None, None, 400)
    assert len(pages) == 1
    assert pages[0]["timestamp"] == "20140101150000"


def test_select_pages_even_sampling_cap():
    rows = [_row(f"201401{d:02d}120000", "https://twitter.com/jack") for d in range(1, 29)]
    pages = _select_pages(rows, None, None, 7)
    assert len(pages) == 7
    days = [int(p["timestamp"][6:8]) for p in pages]
    assert days == sorted(days)
    assert days[0] <= 4 and days[-1] >= 24  # spread, not a prefix truncation
