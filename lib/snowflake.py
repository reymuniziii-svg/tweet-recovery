"""Twitter snowflake ID -> UTC timestamp.

Every tweet ID minted after 2010-11-04 encodes its creation time:
    ms_since_twitter_epoch = id >> 22
    twitter_epoch = 1288834974657 (ms, Unix)
Pre-snowflake IDs (sequential, < ~30_000_000_000) carry no timestamp.
"""

from datetime import datetime, timezone

TWITTER_EPOCH_MS = 1288834974657

# Smallest plausible snowflake ID (first snowflakes were ~29.7e9 << 22).
# Anything below this is a pre-2010 sequential ID with no embedded date.
MIN_SNOWFLAKE_ID = 1 << 40


def snowflake_to_datetime(tweet_id: int):
    """Return the tweet's creation time (UTC) or None for pre-snowflake IDs."""
    if tweet_id < MIN_SNOWFLAKE_ID:
        return None
    ms = (tweet_id >> 22) + TWITTER_EPOCH_MS
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def capture_ts_to_datetime(ts: str):
    """Wayback capture timestamp (YYYYMMDDhhmmss) -> UTC datetime."""
    return datetime.strptime(ts[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
