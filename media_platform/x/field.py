# -*- coding: utf-8 -*-
"""
X (Twitter) 平台数据字段定义
"""

from enum import Enum
from typing import NamedTuple, List, Optional


class TweetType(Enum):
    """推文类型"""
    TWEET = "tweet"
    RETWEET = "retweet"
    QUOTE = "quote"
    REPLY = "reply"


class MediaType(Enum):
    """媒体类型"""
    PHOTO = "photo"
    VIDEO = "video"
    GIF = "animated_gif"


class SearchFilter(Enum):
    """搜索过滤器"""
    TOP = "Top"
    LATEST = "Latest"
    PEOPLE = "People"
    PHOTOS = "Photos"
    VIDEOS = "Videos"


class VerifiedType(Enum):
    """认证类型"""
    NONE = "none"
    BLUE = "blue"
    BUSINESS = "business"
    GOVERNMENT = "government"


class TweetUrlInfo(NamedTuple):
    """推文 URL 解析结果"""
    tweet_id: str
    username: str


class CreatorUrlInfo(NamedTuple):
    """创作者 URL 解析结果"""
    username: str