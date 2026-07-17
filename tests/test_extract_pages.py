from lib.snowflake import snowflake_to_datetime
from stages.extract_pages import _tweet_record

CAP = {"timestamp": "20150108170518", "original": "https://twitter.com/jack"}


def _tweet(**kw):
    base = {"tweet_id": "553222199147245568", "retweet_id": None,
            "screen_name": "jack", "text": "hello", "is_retweet": False,
            "retweeted_user": None}
    base.update(kw)
    return base


def test_own_tweet_dated_by_snowflake():
    row_id, rec = _tweet_record(_tweet(), CAP, "stream-item")
    assert row_id == "553222199147245568"
    assert rec["date_confidence"] == "exact"
    expected = snowflake_to_datetime(553222199147245568).strftime("%Y-%m-%d %H:%M:%S")
    assert rec["date"] == expected
    assert rec["recovered_via"] == "timeline"
    assert rec["is_retweet"] is False
    assert "retweet_of" not in rec


def test_retweet_dated_by_retweet_id_snowflake():
    row_id, rec = _tweet_record(
        _tweet(tweet_id="552966249127628800", retweet_id="553083709302513664",
               screen_name="pierremorel", is_retweet=True,
               retweeted_user="pierremorel"),
        CAP, "stream-item")
    assert row_id == "553083709302513664"  # the retweet event's own ID
    assert rec["date_confidence"] == "exact"
    expected = snowflake_to_datetime(553083709302513664).strftime("%Y-%m-%d %H:%M:%S")
    assert rec["date"] == expected  # when jack retweeted, not the original's date
    assert rec["retweet_of"] == "552966249127628800"
    assert rec["retweeted_user"] == "pierremorel"


def test_retweet_without_retweet_id_dated_by_capture():
    row_id, rec = _tweet_record(
        _tweet(tweet_id="416315527922200576", is_retweet=True,
               screen_name="historicalpics", retweeted_user="historicalpics"),
        CAP, "mobile-tweet")
    assert row_id == "rt:416315527922200576"  # non-numeric, never enters failed.jsonl
    assert rec["date_confidence"] == "approximate"
    assert rec["date"] == "2015-01-08 17:05:18"  # capture time, not the original's snowflake


def test_pre_snowflake_own_tweet_dated_by_capture():
    cap = {"timestamp": "20090101113614", "original": "http://twitter.com/jack"}
    row_id, rec = _tweet_record(_tweet(tweet_id="1089673462"), cap, "status-li")
    assert rec["date_confidence"] == "approximate"
    assert rec["date"] == "2009-01-01 11:36:14"
