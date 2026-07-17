"""Parser tests against real Wayback captures of twitter.com/jack.

Fixtures were saved verbatim from the archive (curl -L --compressed
'https://web.archive.org/web/<ts>id_/<original>'); filenames carry the era.
"""

from pathlib import Path

from lib.parsers import extract_timeline_tweets, extract_tweet_text

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return (FIXTURES / name).read_text(encoding="utf-8", errors="replace")


def test_stream_2015_desktop():
    tweets, method = extract_timeline_tweets(_load("stream_2015.html"), "jack")
    assert method == "stream-item"
    assert len(tweets) == 20
    retweets = [t for t in tweets if t["is_retweet"]]
    assert len(retweets) == 13
    for t in tweets:
        assert t["tweet_id"].isdigit()
        assert t["text"]
        if t["is_retweet"]:
            assert t["retweeted_user"] and t["retweeted_user"] != "jack"
            if t["retweet_id"]:
                assert t["retweet_id"].isdigit()
        else:
            assert t["screen_name"] == "jack"
            assert t["retweeted_user"] is None
    # t.co wrappers must be expanded to their destination URLs.
    assert not any("t.co/" in t["text"] for t in tweets)


def test_stream_2022_desktop():
    # A 2022 capture where the crawler still got legacy SSR markup.
    tweets, method = extract_timeline_tweets(_load("stream_2022.html"), "jack")
    assert method == "stream-item"
    assert len(tweets) == 21
    assert sum(t["is_retweet"] for t in tweets) == 9


def test_mobile_2014():
    tweets, method = extract_timeline_tweets(_load("mobile_2014.html"), "jack")
    assert method == "mobile-tweet"
    assert len(tweets) == 20
    retweets = [t for t in tweets if t["is_retweet"]]
    assert len(retweets) == 5
    assert all(t["tweet_id"].isdigit() for t in tweets)
    assert all(t["retweeted_user"] and t["retweeted_user"] != "jack" for t in retweets)


def test_status_tr_2009():
    tweets, method = extract_timeline_tweets(_load("status_li_2009.html"), "jack")
    assert method == "status-li"
    assert len(tweets) == 20
    assert all(t["tweet_id"].isdigit() for t in tweets)
    assert "Happy New Year, Twitter." in [t["text"] for t in tweets]


def test_js_shell_2023_yields_nothing():
    tweets, method = extract_timeline_tweets(_load("js_shell_2023.html"), "jack")
    assert (tweets, method) == ([], None)


def test_screen_name_guard_skips_other_users_non_retweets():
    html = """
    <div class="tweet" data-tweet-id="553222199147245568" data-screen-name="someoneelse">
      <p class="tweet-text">not jack's tweet</p>
    </div>
    <div class="tweet" data-tweet-id="553222199147245569" data-screen-name="jack">
      <p class="tweet-text">jack's tweet</p>
    </div>
    """
    tweets, method = extract_timeline_tweets(html, "jack")
    assert method == "stream-item"
    assert [t["text"] for t in tweets] == ["jack's tweet"]


def test_classic_rt_flagging():
    html = """
    <ol id="timeline">
      <li class="hentry status" id="status_1089673462">
        <span class="entry-content">RT @ev: launch day</span>
      </li>
    </ol>
    """
    tweets, method = extract_timeline_tweets(html, "jack")
    assert method == "status-li"
    assert tweets[0]["text"] == "RT @ev: launch day"  # verbatim
    assert tweets[0]["is_retweet"] is True
    assert tweets[0]["retweeted_user"] == "ev"


def test_profile_bio_never_used_as_tweet():
    html = """
    <meta property="og:description" content="CEO of Block. This is a bio.">
    <div id="react-root"></div>
    """
    assert extract_timeline_tweets(html, "jack") == ([], None)


def test_extract_tweet_text_regression_permalink():
    html = """
    <div class="permalink-tweet">
      <p class="tweet-text">hello <a data-expanded-url="https://example.com/x">t.co/abc</a>
      <span class="invisible">junk</span></p>
    </div>
    """
    text, method = extract_tweet_text(html)
    assert method == "tweet-text"
    assert text == "hello https://example.com/x"


def test_extract_tweet_text_regression_og_description():
    html = '<meta property="og:description" content="&#8220;quoted tweet&#8221;">'
    text, method = extract_tweet_text(html)
    assert method == "og:description"
    assert text == "quoted tweet"
