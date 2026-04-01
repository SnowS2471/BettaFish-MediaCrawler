# -*- coding: utf-8 -*-
"""
X (Twitter) API 客户端
基于 GraphQL API 实现推文搜索、详情获取、评论爬取等功能
"""

import asyncio
import json
import urllib.parse
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

import httpx
from playwright.async_api import BrowserContext, Page
from tenacity import retry, stop_after_attempt, wait_fixed

import config
from base.base_crawler import AbstractApiClient
from proxy.proxy_mixin import ProxyRefreshMixin
from tools import utils
from tools.httpx_util import make_async_client

if TYPE_CHECKING:
    from proxy.proxy_ip_pool import ProxyIpPool

from .exception import DataFetchError, RateLimitError, TweetNotFoundError

# X Web App Bearer Token (公开的，所有 Web 客户端共用)
BEARER_TOKEN = "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"

# GraphQL 查询 ID 映射 (需要定期更新)
GRAPHQL_QUERIES = {
    "SearchTimeline": "nK1dw4oV3k4w5TdtcAdSww",
    "TweetDetail": "xOhkmRac04YFZDUKBNhCXg",
    "UserByScreenName": "G3KGOASz96M-Qu0nwT_CjQ",
    "UserTweets": "V1ze5q3ijDS1VeLwLY0m7g",
}

# GraphQL 通用 features 参数
DEFAULT_FEATURES = {
    "rweb_lists_timeline_redesign_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "tweetypie_unmention_optimization_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": False,
    "tweet_awards_web_tipping_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_media_download_video_enabled": False,
    "responsive_web_enhance_cards_enabled": False,
}


class XClient(AbstractApiClient, ProxyRefreshMixin):

    def __init__(
        self,
        timeout=30,
        proxy=None,
        *,
        headers: Dict[str, str],
        playwright_page: Page,
        cookie_dict: Dict[str, str],
        proxy_ip_pool: Optional["ProxyIpPool"] = None,
    ):
        self.proxy = proxy
        self.timeout = timeout
        self.headers = headers
        self._host = "https://x.com"
        self._graphql_host = "https://x.com/i/api/graphql"
        self.playwright_page = playwright_page
        self.cookie_dict = cookie_dict
        self.init_proxy_pool(proxy_ip_pool)

    async def _pre_headers(self, url: str, data=None) -> Dict:
        """构造请求头，包含 Bearer Token 和 CSRF Token"""
        csrf_token = self.cookie_dict.get("ct0", "")
        headers = {
            "authorization": f"Bearer {BEARER_TOKEN}",
            "x-csrf-token": csrf_token,
            "x-twitter-auth-type": "OAuth2Session",
            "x-twitter-active-user": "yes",
            "x-twitter-client-language": "en",
            "content-type": "application/json",
            "referer": "https://x.com/",
            "user-agent": self.headers.get("User-Agent", ""),
        }
        return headers

    async def request(self, method, url, **kwargs) -> Any:
        """发送 HTTP 请求"""
        async with make_async_client(proxy=self.proxy, timeout=self.timeout) as client:
            headers = await self._pre_headers(url)
            cookies = {k: v for k, v in self.cookie_dict.items()}
            response = await client.request(
                method, url, headers=headers, cookies=cookies, **kwargs
            )
            if response.status_code == 429:
                raise RateLimitError(f"Rate limited: {url}")
            response.raise_for_status()
            data = response.json()
            return data

    async def update_cookies(self, browser_context: BrowserContext):
        """从浏览器上下文更新 Cookie"""
        cookies = await browser_context.cookies()
        for cookie in cookies:
            if cookie["domain"] in (".x.com", ".twitter.com", "x.com", "twitter.com"):
                self.cookie_dict[cookie["name"]] = cookie["value"]

    async def pong(self) -> bool:
        """检查客户端是否可用（登录状态是否有效）"""
        try:
            # 尝试获取当前用户信息来验证登录状态
            if not self.cookie_dict.get("auth_token") or not self.cookie_dict.get("ct0"):
                return False
            return True
        except Exception:
            return False

    def _build_graphql_url(self, operation_name: str) -> str:
        """构建 GraphQL 请求 URL"""
        query_id = GRAPHQL_QUERIES.get(operation_name, "")
        return f"{self._graphql_host}/{query_id}/{operation_name}"

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    async def search_tweets(
        self, keyword: str, cursor: str = None, count: int = 20, search_filter: str = "Latest"
    ) -> Dict:
        """
        搜索推文
        Args:
            keyword: 搜索关键词
            cursor: 分页游标
            count: 每页数量
            search_filter: 搜索过滤 (Top/Latest)
        Returns:
            搜索结果
        """
        url = self._build_graphql_url("SearchTimeline")
        variables = {
            "rawQuery": keyword,
            "count": count,
            "querySource": "typed_query",
            "product": search_filter,
        }
        if cursor:
            variables["cursor"] = cursor

        params = {
            "variables": json.dumps(variables),
            "features": json.dumps(DEFAULT_FEATURES),
        }
        return await self.request("GET", url, params=params)

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    async def get_tweet_detail(self, tweet_id: str) -> Dict:
        """获取推文详情"""
        url = self._build_graphql_url("TweetDetail")
        variables = {
            "focalTweetId": tweet_id,
            "with_rux_injections": False,
            "includePromotedContent": False,
            "withCommunity": True,
            "withQuickPromoteEligibilityTweetFields": True,
            "withBirdwatchNotes": True,
            "withVoice": True,
            "withV2Timeline": True,
        }
        params = {
            "variables": json.dumps(variables),
            "features": json.dumps(DEFAULT_FEATURES),
        }
        return await self.request("GET", url, params=params)

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    async def get_user_info(self, username: str) -> Dict:
        """通过用户名获取用户信息"""
        url = self._build_graphql_url("UserByScreenName")
        variables = {
            "screen_name": username,
            "withSafetyModeUserFields": True,
        }
        params = {
            "variables": json.dumps(variables),
            "features": json.dumps(DEFAULT_FEATURES),
        }
        return await self.request("GET", url, params=params)

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    async def get_user_tweets(self, user_id: str, cursor: str = None, count: int = 20) -> Dict:
        """获取用户推文列表"""
        url = self._build_graphql_url("UserTweets")
        variables = {
            "userId": user_id,
            "count": count,
            "includePromotedContent": False,
            "withQuickPromoteEligibilityTweetFields": True,
            "withVoice": True,
            "withV2Timeline": True,
        }
        if cursor:
            variables["cursor"] = cursor

        params = {
            "variables": json.dumps(variables),
            "features": json.dumps(DEFAULT_FEATURES),
        }
        return await self.request("GET", url, params=params)