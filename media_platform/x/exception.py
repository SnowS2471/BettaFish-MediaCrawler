# -*- coding: utf-8 -*-
"""
X (Twitter) 平台异常定义
"""

from httpx import RequestError


class DataFetchError(RequestError):
    """数据获取错误"""


class IPBlockError(RequestError):
    """IP 被封禁"""


class TweetNotFoundError(RequestError):
    """推文不存在或已删除"""


class RateLimitError(RequestError):
    """速率限制"""