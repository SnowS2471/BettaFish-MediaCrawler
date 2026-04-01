# -*- coding: utf-8 -*-
"""
X (Twitter) 平台辅助函数
"""

import re
import json
import time
from typing import Dict, List, Optional
from email.utils import parsedate_to_datetime

from .field import TweetUrlInfo, CreatorUrlInfo


def parse_tweet_url(url: str) -> Optional[TweetUrlInfo]:
    """
    从 URL 提取推文信息
    支持格式:
        https://twitter.com/username/status/1234567890
        https://x.com/username/status/1234567890
    """
    pattern = r'(?:twitter\.com|x\.com)/([^/]+)/status/(\d+)'
    match = re.search(pattern, url)
    if match:
        return TweetUrlInfo(tweet_id=match.group(2), username=match.group(1))
    return None


def parse_creator_url(url: str) -> Optional[CreatorUrlInfo]:
    """
    从 URL 提取用户名
    支持格式:
        https://twitter.com/username
        https://x.com/username
    """
    pattern = r'(?:twitter\.com|x\.com)/([^/?#]+)$'
    match = re.search(pattern, url.rstrip('/'))
    if match:
        username = match.group(1)
        if username not in ('home', 'explore', 'search', 'notifications', 'messages', 'i', 'settings'):
            return CreatorUrlInfo(username=username)
    return None


def format_tweet_time(created_at: str) -> int:
    """
    将 Twitter 时间格式转换为时间戳
    Twitter 格式: "Wed Oct 10 20:19:24 +0000 2018"
    """
    try:
        dt = parsedate_to_datetime(created_at)
        return int(dt.timestamp())
    except Exception:
        return 0


def extract_media_urls(entities: Dict) -> List[Dict]:
    """
    从推文 entities 中提取媒体 URL
    返回: [{"type": "photo|video|gif", "url": "..."}]
    """
    media_list = []
    media_items = entities.get("media", [])
    for item in media_items:
        media_type = item.get("type", "photo")
        if media_type == "photo":
            url = item.get("media_url_https", "")
        elif media_type == "video":
            variants = item.get("video_info", {}).get("variants", [])
            mp4_variants = [v for v in variants if v.get("content_type") == "video/mp4"]
            url = max(mp4_variants, key=lambda v: v.get("bitrate", 0)).get("url", "") if mp4_variants else ""
        elif media_type == "animated_gif":
            variants = item.get("video_info", {}).get("variants", [])
            url = variants[0].get("url", "") if variants else ""
        else:
            url = item.get("media_url_https", "")
        if url:
            media_list.append({"type": media_type, "url": url})
    return media_list


def extract_tweet_data(raw_tweet: Dict) -> Dict:
    """
    从 GraphQL 响应中提取推文数据，转换为本地数据库格式
    """
    legacy = raw_tweet.get("legacy", raw_tweet)
    core = raw_tweet.get("core", {})
    user_results = core.get("user_results", {}).get("result", {})
    user_legacy = user_results.get("legacy", {})

    entities = legacy.get("entities", {})
    extended_entities = legacy.get("extended_entities", entities)

    # 提取媒体
    media_info = extract_media_urls(extended_entities)
    media_urls = [m["url"] for m in media_info]
    media_types = [m["type"] for m in media_info]

    # 提取 hashtags
    hashtags = [h.get("text", "") for h in entities.get("hashtags", [])]

    # 提取 mentioned users
    mentioned_users = [u.get("screen_name", "") for u in entities.get("user_mentions", [])]

    # 提取 urls
    urls = [u.get("expanded_url", "") for u in entities.get("urls", [])]

    # 判断推文类型
    tweet_type = "tweet"
    retweeted_status = legacy.get("retweeted_status_result", {}).get("result", {})
    quoted_status = raw_tweet.get("quoted_status_result", {}).get("result", {})
    in_reply_to = legacy.get("in_reply_to_status_id_str")

    if retweeted_status:
        tweet_type = "retweet"
    elif quoted_status:
        tweet_type = "quote"
    elif in_reply_to:
        tweet_type = "reply"

    # 视频 URL
    video_urls = [m["url"] for m in media_info if m["type"] in ("video", "animated_gif")]
    video_url = video_urls[0] if video_urls else ""

    tweet_id = legacy.get("id_str", raw_tweet.get("rest_id", ""))
    user_id = user_legacy.get("id_str", user_results.get("rest_id", ""))
    username = user_legacy.get("screen_name", "")

    return {
        "tweet_id": tweet_id,
        "user_id": user_id,
        "username": username,
        "nickname": user_legacy.get("name", ""),
        "avatar": user_legacy.get("profile_image_url_https", ""),
        "user_verified": 1 if user_results.get("is_blue_verified") else 0,
        "user_verified_type": user_results.get("verified_type", ""),
        "ip_location": "",
        "content": legacy.get("full_text", ""),
        "tweet_type": tweet_type,
        "create_time": format_tweet_time(legacy.get("created_at", "")),
        "create_date_time": legacy.get("created_at", ""),
        "like_count": str(legacy.get("favorite_count", 0)),
        "retweet_count": str(legacy.get("retweet_count", 0)),
        "reply_count": str(legacy.get("reply_count", 0)),
        "quote_count": str(legacy.get("quote_count", 0)),
        "bookmark_count": str(legacy.get("bookmark_count", 0)),
        "view_count": str(raw_tweet.get("views", {}).get("count", 0)),
        "media_urls": json.dumps(media_urls, ensure_ascii=False),
        "media_types": json.dumps(media_types, ensure_ascii=False),
        "video_url": video_url,
        "hashtags": json.dumps(hashtags, ensure_ascii=False),
        "mentioned_users": json.dumps(mentioned_users, ensure_ascii=False),
        "urls": json.dumps(urls, ensure_ascii=False),
        "is_retweet": 1 if retweeted_status else 0,
        "retweeted_tweet_id": retweeted_status.get("legacy", {}).get("id_str", ""),
        "retweeted_user_id": retweeted_status.get("core", {}).get("user_results", {}).get("result", {}).get("rest_id", ""),
        "is_quote": 1 if quoted_status else 0,
        "quoted_tweet_id": quoted_status.get("legacy", {}).get("id_str", ""),
        "quoted_user_id": quoted_status.get("core", {}).get("user_results", {}).get("result", {}).get("rest_id", ""),
        "is_reply": 1 if in_reply_to else 0,
        "reply_to_tweet_id": in_reply_to or "",
        "reply_to_user_id": legacy.get("in_reply_to_user_id_str", ""),
        "tweet_url": f"https://x.com/{username}/status/{tweet_id}",
        "lang": legacy.get("lang", ""),
    }