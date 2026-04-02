# -*- coding: utf-8 -*-
"""
X (Twitter) 爬虫核心逻辑
"""

import asyncio
import os
import random
from asyncio import Task
from typing import Dict, List, Optional

from playwright.async_api import (
    BrowserContext,
    BrowserType,
    Page,
    Playwright,
    async_playwright,
)
from tenacity import RetryError

import config
from base.base_crawler import AbstractCrawler
from proxy.proxy_ip_pool import IpInfoModel, create_ip_pool
from store import x as x_store
from tools import utils
from tools.cdp_browser import CDPBrowserManager
from var import crawler_type_var, source_keyword_var

from .client import XClient
from .exception import DataFetchError
from .field import SearchFilter, TweetUrlInfo, CreatorUrlInfo
from .help import parse_tweet_url, parse_creator_url, extract_tweet_data
from .login import XLogin


class XCrawler(AbstractCrawler):
    context_page: Page
    x_client: XClient
    browser_context: BrowserContext
    cdp_manager: Optional[CDPBrowserManager]

    def __init__(self) -> None:
        self.index_url = "https://x.com"
        self.user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        )
        self.cdp_manager = None
        self.ip_proxy_pool = None

    async def start(self) -> None:
        playwright_proxy_format, httpx_proxy_format = None, None
        if config.ENABLE_IP_PROXY:
            self.ip_proxy_pool = await create_ip_pool(
                config.IP_PROXY_POOL_COUNT, enable_validate_ip=True
            )
            ip_proxy_info: IpInfoModel = await self.ip_proxy_pool.get_proxy()
            playwright_proxy_format, httpx_proxy_format = utils.format_proxy_info(ip_proxy_info)

        async with async_playwright() as playwright:
            if config.ENABLE_CDP_MODE:
                utils.logger.info("[XCrawler] 使用 CDP 模式启动浏览器")
                self.browser_context = await self.launch_browser_with_cdp(
                    playwright,
                    playwright_proxy_format,
                    self.user_agent,
                    headless=config.CDP_HEADLESS,
                )
            else:
                utils.logger.info("[XCrawler] 使用标准模式启动浏览器")
                chromium = playwright.chromium
                self.browser_context = await self.launch_browser(
                    chromium,
                    playwright_proxy_format,
                    self.user_agent,
                    headless=config.HEADLESS,
                )
                await self.browser_context.add_init_script(path="libs/stealth.min.js")

            self.context_page = await self.browser_context.new_page()
            await self.context_page.goto(self.index_url)

            # 创建 API 客户端
            self.x_client = await self.create_x_client(httpx_proxy_format)
            self.x_client.set_browser_context(self.browser_context)
            if not await self.x_client.pong():
                login_obj = XLogin(
                    login_type=config.LOGIN_TYPE,
                    browser_context=self.browser_context,
                    context_page=self.context_page,
                    cookie_str=config.COOKIES,
                )
                await login_obj.begin()
                await self.x_client.update_cookies(self.browser_context)

            crawler_type_var.set(config.CRAWLER_TYPE)

            if config.CRAWLER_TYPE == "search":
                await self.search()
            elif config.CRAWLER_TYPE == "detail":
                await self.get_specified_tweets()
            elif config.CRAWLER_TYPE == "creator":
                await self.get_creators_and_tweets()
            else:
                utils.logger.error(f"[XCrawler] 不支持的爬取类型: {config.CRAWLER_TYPE}")

            utils.logger.info("[XCrawler] X 平台爬取完成")

    async def search(self) -> None:
        """关键词搜索推文"""
        utils.logger.info("[XCrawler] 开始搜索推文...")
        keywords = config.KEYWORDS.split(",")
        search_filter = getattr(config, "X_SEARCH_FILTER", SearchFilter.LATEST.value)
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)

        for keyword in keywords:
            keyword = keyword.strip()
            if not keyword:
                continue

            utils.logger.info(f"[XCrawler] 搜索关键词: {keyword}")
            source_keyword_var.set(keyword)

            page = 0
            cursor = None
            while page < config.CRAWLER_MAX_NOTES_COUNT // 20 + 1:
                try:
                    result = await self.x_client.search_tweets(
                        keyword, cursor=cursor, search_filter=search_filter
                    )
                    tweets, next_cursor = self._parse_search_result(result)

                    if not tweets:
                        utils.logger.info(f"[XCrawler] 关键词 '{keyword}' 无更多结果")
                        break

                    # 顺序存储推文，收集需要获取评论的 tweet_id
                    tweet_ids_for_comments = []
                    for raw_tweet in tweets:
                        tweet_data = extract_tweet_data(raw_tweet)
                        tweet_data["source_keyword"] = keyword
                        await x_store.update_x_tweet(tweet_data)
                        if config.ENABLE_GET_COMMENTS and tweet_data.get("tweet_id"):
                            tweet_ids_for_comments.append(tweet_data["tweet_id"])

                    # 并发获取评论
                    if tweet_ids_for_comments:
                        comment_tasks = [
                            asyncio.create_task(
                                self._get_tweet_comments_task(tid, semaphore)
                            )
                            for tid in tweet_ids_for_comments
                        ]
                        await asyncio.gather(*comment_tasks)

                    if not next_cursor:
                        break
                    cursor = next_cursor
                    page += 1

                    # 随机延迟，避免触发反爬
                    await asyncio.sleep(random.uniform(2, 5))

                except RetryError:
                    utils.logger.error(f"[XCrawler] 搜索 '{keyword}' 重试次数耗尽")
                    break
                except Exception as e:
                    utils.logger.error(f"[XCrawler] 搜索 '{keyword}' 异常: {e}")
                    break

    async def get_specified_tweets(self) -> None:
        """获取指定推文详情"""
        tweet_urls = getattr(config, "X_SPECIFIED_ID_LIST", [])
        if not tweet_urls:
            utils.logger.warning("[XCrawler] 未指定推文 URL 列表")
            return

        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)

        # 解析所有 URL
        tweet_ids = []
        for url_or_id in tweet_urls:
            tweet_info = parse_tweet_url(url_or_id)
            tweet_ids.append(tweet_info.tweet_id if tweet_info else url_or_id)

        # 并发获取推文详情
        detail_tasks = [
            asyncio.create_task(self._get_tweet_detail_task(tid, semaphore))
            for tid in tweet_ids
        ]
        tweet_results = await asyncio.gather(*detail_tasks)

        # 并发获取评论
        if config.ENABLE_GET_COMMENTS:
            comment_tasks = [
                asyncio.create_task(
                    self._get_tweet_comments_task(td["tweet_id"], semaphore)
                )
                for td in tweet_results
                if td and td.get("tweet_id")
            ]
            if comment_tasks:
                await asyncio.gather(*comment_tasks)

    async def get_creators_and_tweets(self) -> None:
        """获取创作者信息和推文"""
        creator_urls = getattr(config, "X_CREATOR_ID_LIST", [])
        if not creator_urls:
            utils.logger.warning("[XCrawler] 未指定创作者 URL 列表")
            return

        for url_or_username in creator_urls:
            creator_info = parse_creator_url(url_or_username)
            username = creator_info.username if creator_info else url_or_username

            try:
                # 获取用户信息
                user_result = await self.x_client.get_user_info(username)
                user_data = user_result.get("data", {}).get("user", {}).get("result", {})
                user_legacy = user_data.get("legacy", {})
                user_id = user_data.get("rest_id", "")

                creator_item = {
                    "user_id": user_id,
                    "username": user_legacy.get("screen_name", ""),
                    "nickname": user_legacy.get("name", ""),
                    "avatar": user_legacy.get("profile_image_url_https", ""),
                    "banner_url": user_legacy.get("profile_banner_url", ""),
                    "bio": user_legacy.get("description", ""),
                    "location": user_legacy.get("location", ""),
                    "website": "",
                    "join_date": user_legacy.get("created_at", ""),
                    "verified": 1 if user_data.get("is_blue_verified") else 0,
                    "verified_type": user_data.get("verified_type", ""),
                    "protected": 1 if user_legacy.get("protected") else 0,
                    "followers_count": str(user_legacy.get("followers_count", 0)),
                    "following_count": str(user_legacy.get("friends_count", 0)),
                    "tweet_count": str(user_legacy.get("statuses_count", 0)),
                    "listed_count": str(user_legacy.get("listed_count", 0)),
                    "profile_url": f"https://x.com/{username}",
                }
                await x_store.save_creator(user_id, creator_item)

                # 获取用户推文
                cursor = None
                for _ in range(config.CRAWLER_MAX_NOTES_COUNT // 20 + 1):
                    tweets_result = await self.x_client.get_user_tweets(user_id, cursor=cursor)
                    tweets, next_cursor = self._parse_timeline_result(tweets_result)

                    for raw_tweet in tweets:
                        tweet_data = extract_tweet_data(raw_tweet)
                        await x_store.update_x_tweet(tweet_data)

                    if not next_cursor or not tweets:
                        break
                    cursor = next_cursor
                    await asyncio.sleep(random.uniform(2, 5))

            except Exception as e:
                utils.logger.error(f"[XCrawler] 获取创作者 {username} 失败: {e}")

            await asyncio.sleep(random.uniform(1, 3))

    async def create_x_client(self, httpx_proxy: Optional[str]) -> XClient:
        """创建 X API 客户端"""
        cookies = await self.browser_context.cookies()
        cookie_str, cookie_dict = utils.convert_cookies(cookies)
        x_client = XClient(
            proxy=httpx_proxy,
            headers={
                "User-Agent": self.user_agent,
                "Cookie": cookie_str,
                "Origin": self.index_url,
                "Referer": self.index_url,
            },
            playwright_page=self.context_page,
            cookie_dict=cookie_dict,
        )
        return x_client

    async def launch_browser(
        self,
        chromium: BrowserType,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        """启动浏览器"""
        utils.logger.info(f"[XCrawler] 启动浏览器, headless={headless}")
        user_data_dir = os.path.join(
            os.getcwd(), "browser_data", config.USER_DATA_DIR % config.PLATFORM
        )
        browser_context = await chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            accept_downloads=True,
            headless=headless,
            proxy=playwright_proxy,
            viewport={"width": 1920, "height": 1080},
            user_agent=user_agent,
        )
        return browser_context

    async def _get_tweet_detail_task(
        self, tweet_id: str, semaphore: asyncio.Semaphore, keyword: str = ""
    ) -> Optional[Dict]:
        """获取单条推文详情（并发任务）"""
        async with semaphore:
            try:
                result = await self.x_client.get_tweet_detail(tweet_id)
                raw_tweet = self._parse_tweet_detail(result)
                if raw_tweet:
                    tweet_data = extract_tweet_data(raw_tweet)
                    if keyword:
                        tweet_data["source_keyword"] = keyword
                    await x_store.update_x_tweet(tweet_data)
                    return tweet_data
            except Exception as e:
                utils.logger.error(f"[XCrawler] 获取推文 {tweet_id} 失败: {e}")
            finally:
                await asyncio.sleep(random.uniform(1, 3))
            return None

    async def _get_tweet_comments_task(
        self, tweet_id: str, semaphore: asyncio.Semaphore
    ) -> None:
        """获取推文评论（并发任务）"""
        async with semaphore:
            await self._get_tweet_comments(tweet_id)

    async def _get_tweet_comments(self, tweet_id: str) -> None:
        """获取推文评论（回复），支持分页"""
        max_comments = config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES
        all_count = 0
        cursor = None

        while all_count < max_comments:
            try:
                result = await self.x_client.get_tweet_detail(tweet_id, cursor=cursor)
                comments, next_cursor = self._parse_tweet_comments(result, tweet_id)

                if not comments:
                    break

                remaining = max_comments - all_count
                batch = comments[:remaining]

                for comment_data in batch:
                    await x_store.update_x_tweet_comment(tweet_id, comment_data)

                all_count += len(batch)
                utils.logger.info(
                    f"[XCrawler] 推文 {tweet_id} 已获取 {all_count} 条评论"
                )

                if not next_cursor:
                    break
                cursor = next_cursor
                await asyncio.sleep(random.uniform(1, 3))

            except RetryError:
                utils.logger.error(
                    f"[XCrawler] 获取推文 {tweet_id} 评论重试次数耗尽"
                )
                break
            except Exception as e:
                utils.logger.error(f"[XCrawler] 获取推文 {tweet_id} 评论失败: {e}")
                break

    def _parse_search_result(self, result: Dict) -> tuple:
        """解析搜索结果，返回 (tweets, next_cursor)"""
        tweets = []
        next_cursor = None
        try:
            instructions = (
                result.get("data", {})
                .get("search_by_raw_query", {})
                .get("search_timeline", {})
                .get("timeline", {})
                .get("instructions", [])
            )
            for instruction in instructions:
                entries = instruction.get("entries", [])
                for entry in entries:
                    content = entry.get("content", {})
                    entry_type = content.get("entryType", "")

                    if entry_type == "TimelineTimelineItem":
                        tweet_result = (
                            content.get("itemContent", {})
                            .get("tweet_results", {})
                            .get("result", {})
                        )
                        if tweet_result and tweet_result.get("__typename") == "Tweet":
                            tweets.append(tweet_result)

                    elif entry_type == "TimelineTimelineCursor":
                        if content.get("cursorType") == "Bottom":
                            next_cursor = content.get("value")
        except Exception as e:
            utils.logger.error(f"[XCrawler] 解析搜索结果失败: {e}")

        return tweets, next_cursor

    def _parse_tweet_detail(self, result: Dict) -> Optional[Dict]:
        """从推文详情响应中提取推文数据"""
        try:
            instructions = (
                result.get("data", {})
                .get("threaded_conversation_with_injections_v2", {})
                .get("instructions", [])
            )
            for instruction in instructions:
                entries = instruction.get("entries", [])
                for entry in entries:
                    content = entry.get("content", {})
                    tweet_result = (
                        content.get("itemContent", {})
                        .get("tweet_results", {})
                        .get("result", {})
                    )
                    if tweet_result and tweet_result.get("__typename") == "Tweet":
                        return tweet_result
        except Exception as e:
            utils.logger.error(f"[XCrawler] 解析推文详情失败: {e}")
        return None

    def _parse_tweet_comments(self, result: Dict, focal_tweet_id: str) -> tuple:
        """从推文详情响应中提取评论（回复），返回 (comments, next_cursor)"""
        comments = []
        next_cursor = None
        try:
            instructions = (
                result.get("data", {})
                .get("threaded_conversation_with_injections_v2", {})
                .get("instructions", [])
            )
            for instruction in instructions:
                entries = instruction.get("entries", [])
                for entry in entries:
                    content = entry.get("content", {})
                    entry_type = content.get("entryType", "")

                    # 跳过焦点推文本身
                    if f"tweet-{focal_tweet_id}" in entry.get("entryId", ""):
                        continue

                    # 提取分页 cursor
                    if entry_type == "TimelineTimelineCursor":
                        if content.get("cursorType") in ("Bottom", "ShowMore"):
                            next_cursor = content.get("value")
                        continue

                    # 处理单条回复
                    tweet_result = (
                        content.get("itemContent", {})
                        .get("tweet_results", {})
                        .get("result", {})
                    )
                    if tweet_result:
                        unwrapped = self._unwrap_tweet_result(tweet_result)
                        if unwrapped:
                            comments.append(extract_tweet_data(unwrapped))

                    # 处理对话线程中的回复
                    items = content.get("items", [])
                    for item in items:
                        item_content = item.get("item", {}).get("itemContent", {})
                        tweet_result = item_content.get("tweet_results", {}).get("result", {})
                        if tweet_result:
                            unwrapped = self._unwrap_tweet_result(tweet_result)
                            if unwrapped:
                                comments.append(extract_tweet_data(unwrapped))

        except Exception as e:
            utils.logger.error(f"[XCrawler] 解析评论失败: {e}")
        return comments, next_cursor

    @staticmethod
    def _unwrap_tweet_result(tweet_result: Dict) -> Optional[Dict]:
        """解包推文结果，处理 TweetWithVisibilityResults 类型"""
        typename = tweet_result.get("__typename", "")
        if typename == "Tweet":
            return tweet_result
        elif typename == "TweetWithVisibilityResults":
            return tweet_result.get("tweet")
        return None

    def _parse_timeline_result(self, result: Dict) -> tuple:
        """解析用户时间线结果"""
        tweets = []
        next_cursor = None
        try:
            instructions = (
                result.get("data", {})
                .get("user", {})
                .get("result", {})
                .get("timeline_v2", {})
                .get("timeline", {})
                .get("instructions", [])
            )
            for instruction in instructions:
                entries = instruction.get("entries", [])
                for entry in entries:
                    content = entry.get("content", {})
                    entry_type = content.get("entryType", "")

                    if entry_type == "TimelineTimelineItem":
                        tweet_result = (
                            content.get("itemContent", {})
                            .get("tweet_results", {})
                            .get("result", {})
                        )
                        if tweet_result and tweet_result.get("__typename") == "Tweet":
                            tweets.append(tweet_result)

                    elif entry_type == "TimelineTimelineCursor":
                        if content.get("cursorType") == "Bottom":
                            next_cursor = content.get("value")
        except Exception as e:
            utils.logger.error(f"[XCrawler] 解析时间线结果失败: {e}")

        return tweets, next_cursor