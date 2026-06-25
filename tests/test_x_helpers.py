# -*- coding: utf-8 -*-
"""Unit tests for X (Twitter) helper functions and field definitions"""

import json
import sys
from pathlib import Path

import pytest

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from media_platform.x.help import (
    parse_tweet_url,
    parse_creator_url,
    format_tweet_time,
    extract_media_urls,
    extract_tweet_data,
)
from media_platform.x.field import (
    TweetType,
    MediaType,
    SearchFilter,
    VerifiedType,
    TweetUrlInfo,
    CreatorUrlInfo,
)


class TestParseTweetUrl:
    def test_x_com_url(self):
        result = parse_tweet_url("https://x.com/elonmusk/status/1234567890")
        assert result == TweetUrlInfo(tweet_id="1234567890", username="elonmusk")

    def test_twitter_com_url(self):
        result = parse_tweet_url("https://twitter.com/jack/status/9999999999")
        assert result == TweetUrlInfo(tweet_id="9999999999", username="jack")

    def test_url_with_query_params(self):
        result = parse_tweet_url("https://x.com/user/status/123?s=20&t=abc")
        assert result is not None
        assert result.tweet_id == "123"

    def test_invalid_url_returns_none(self):
        assert parse_tweet_url("https://google.com/something") is None

    def test_plain_id_returns_none(self):
        assert parse_tweet_url("1234567890") is None

    def test_url_with_trailing_path(self):
        result = parse_tweet_url("https://x.com/user/status/123/photo/1")
        assert result is not None
        assert result.tweet_id == "123"


class TestParseCreatorUrl:
    def test_x_com_url(self):
        result = parse_creator_url("https://x.com/elonmusk")
        assert result == CreatorUrlInfo(username="elonmusk")

    def test_twitter_com_url(self):
        result = parse_creator_url("https://twitter.com/jack")
        assert result == CreatorUrlInfo(username="jack")

    def test_trailing_slash(self):
        result = parse_creator_url("https://x.com/testuser/")
        assert result == CreatorUrlInfo(username="testuser")

    def test_reserved_names_return_none(self):
        reserved = ("home", "explore", "search", "notifications", "messages", "i", "settings")
        for name in reserved:
            assert parse_creator_url(f"https://x.com/{name}") is None

    def test_plain_username_returns_none(self):
        # No URL structure, just a username
        assert parse_creator_url("elonmusk") is None


class TestFormatTweetTime:
    def test_valid_twitter_time(self):
        ts = format_tweet_time("Wed Oct 10 20:19:24 +0000 2018")
        assert ts == 1539202764

    def test_invalid_time_returns_zero(self):
        assert format_tweet_time("not a date") == 0

    def test_empty_string_returns_zero(self):
        assert format_tweet_time("") == 0


class TestExtractMediaUrls:
    def test_photo_extraction(self):
        entities = {
            "media": [{"type": "photo", "media_url_https": "https://example.com/photo.jpg"}]
        }
        result = extract_media_urls(entities)
        assert len(result) == 1
        assert result[0] == {"type": "photo", "url": "https://example.com/photo.jpg"}

    def test_video_selects_highest_bitrate(self):
        entities = {
            "media": [{
                "type": "video",
                "video_info": {
                    "variants": [
                        {"content_type": "application/x-mpegURL", "url": "https://v.com/pl.m3u8"},
                        {"content_type": "video/mp4", "bitrate": 832000, "url": "https://v.com/low.mp4"},
                        {"content_type": "video/mp4", "bitrate": 2176000, "url": "https://v.com/high.mp4"},
                    ]
                }
            }]
        }
        result = extract_media_urls(entities)
        assert len(result) == 1
        assert result[0]["type"] == "video"
        assert "high.mp4" in result[0]["url"]

    def test_empty_entities(self):
        assert extract_media_urls({}) == []

    def test_gif_extraction(self):
        entities = {
            "media": [{
                "type": "animated_gif",
                "video_info": {
                    "variants": [{"url": "https://example.com/gif.mp4"}]
                }
            }]
        }
        result = extract_media_urls(entities)
        assert result[0]["type"] == "animated_gif"
        assert result[0]["url"] == "https://example.com/gif.mp4"


# --- Fixtures for extract_tweet_data tests ---

@pytest.fixture
def sample_graphql_tweet():
    return {
        "__typename": "Tweet",
        "rest_id": "1234567890123456789",
        "core": {
            "user_results": {
                "result": {
                    "rest_id": "9876543210",
                    "is_blue_verified": True,
                    "verified_type": "blue",
                    "legacy": {
                        "id_str": "9876543210",
                        "screen_name": "testuser",
                        "name": "Test User",
                        "profile_image_url_https": "https://pbs.twimg.com/test.jpg",
                    },
                }
            }
        },
        "legacy": {
            "id_str": "1234567890123456789",
            "full_text": "Hello #python @mentioned https://t.co/example",
            "created_at": "Wed Oct 10 20:19:24 +0000 2018",
            "favorite_count": 42,
            "retweet_count": 10,
            "reply_count": 5,
            "quote_count": 3,
            "bookmark_count": 7,
            "lang": "en",
            "entities": {
                "hashtags": [{"text": "python"}],
                "user_mentions": [{"screen_name": "mentioned"}],
                "urls": [{"expanded_url": "https://example.com"}],
            },
        },
        "views": {"count": 1500},
    }


class TestExtractTweetData:
    def test_basic_fields(self, sample_graphql_tweet):
        data = extract_tweet_data(sample_graphql_tweet)
        assert data["tweet_id"] == "1234567890123456789"
        assert data["user_id"] == "9876543210"
        assert data["username"] == "testuser"
        assert data["nickname"] == "Test User"
        assert data["user_verified"] == 1
        assert data["tweet_type"] == "tweet"
        assert data["lang"] == "en"

    def test_counts_are_strings(self, sample_graphql_tweet):
        data = extract_tweet_data(sample_graphql_tweet)
        assert data["like_count"] == "42"
        assert data["retweet_count"] == "10"
        assert data["view_count"] == "1500"

    def test_hashtags_and_mentions(self, sample_graphql_tweet):
        data = extract_tweet_data(sample_graphql_tweet)
        assert "python" in json.loads(data["hashtags"])
        assert "mentioned" in json.loads(data["mentioned_users"])

    def test_tweet_url_format(self, sample_graphql_tweet):
        data = extract_tweet_data(sample_graphql_tweet)
        assert data["tweet_url"] == "https://x.com/testuser/status/1234567890123456789"

    def test_retweet_detection(self, sample_graphql_tweet):
        sample_graphql_tweet["legacy"]["retweeted_status_result"] = {
            "result": {
                "legacy": {"id_str": "1111111111"},
                "core": {"user_results": {"result": {"rest_id": "2222222222"}}},
            }
        }
        data = extract_tweet_data(sample_graphql_tweet)
        assert data["tweet_type"] == "retweet"
        assert data["is_retweet"] == 1
        assert data["retweeted_tweet_id"] == "1111111111"

    def test_reply_detection(self, sample_graphql_tweet):
        sample_graphql_tweet["legacy"]["in_reply_to_status_id_str"] = "9999999999"
        sample_graphql_tweet["legacy"]["in_reply_to_user_id_str"] = "8888888888"
        data = extract_tweet_data(sample_graphql_tweet)
        assert data["tweet_type"] == "reply"
        assert data["is_reply"] == 1
        assert data["reply_to_tweet_id"] == "9999999999"


class TestFieldEnums:
    def test_tweet_type_values(self):
        assert TweetType.TWEET.value == "tweet"
        assert TweetType.RETWEET.value == "retweet"
        assert TweetType.QUOTE.value == "quote"
        assert TweetType.REPLY.value == "reply"

    def test_media_type_values(self):
        assert MediaType.PHOTO.value == "photo"
        assert MediaType.VIDEO.value == "video"
        assert MediaType.GIF.value == "animated_gif"

    def test_search_filter_values(self):
        assert SearchFilter.TOP.value == "Top"
        assert SearchFilter.LATEST.value == "Latest"

    def test_verified_type_values(self):
        assert VerifiedType.NONE.value == "none"
        assert VerifiedType.BLUE.value == "blue"

    def test_namedtuples(self):
        tweet_info = TweetUrlInfo(tweet_id="123", username="user")
        assert tweet_info.tweet_id == "123"
        creator_info = CreatorUrlInfo(username="user")
        assert creator_info.username == "user"
