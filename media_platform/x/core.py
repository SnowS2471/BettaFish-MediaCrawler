# -*- coding: utf-8 -*-
"""
X (Twitter) 爬虫核心逻辑
"""

import asyncio
import os
import random
import re
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

from .client import XClient, GRAPHQL_QUERIES
from .exception import DataFetchError
from .field import SearchFilter, TweetUrlInfo, CreatorUrlInfo
from .help import parse_tweet_url, parse_creator_url, extract_tweet_data, extract_creator_from_tweet
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
        # 检查是否启用官方 API 模式
        use_official = getattr(config, "X_USE_OFFICIAL_API", False)
        bearer_token = getattr(config, "X_OFFICIAL_BEARER_TOKEN", "")

        if use_official and bearer_token:
            try:
                await self._start_official_api()
                return
            except Exception as e:
                if getattr(config, "X_OFFICIAL_API_FALLBACK", True):
                    utils.logger.warning(
                        f"[XCrawler] 官方 API 失败 ({e})，回退到 GraphQL 模式"
                    )
                else:
                    raise

        await self._start_graphql()

    async def _start_official_api(self) -> None:
        """使用官方 X API v2 (tweepy) 进行爬取"""
        from .official_client import XOfficialClient

        utils.logger.info("[XCrawler] 使用官方 X API v2 模式")
        client = XOfficialClient(
            bearer_token=config.X_OFFICIAL_BEARER_TOKEN,
            api_tier=getattr(config, "X_API_TIER", "basic"),
        )

        crawler_type_var.set(config.CRAWLER_TYPE)

        if config.CRAWLER_TYPE == "search":
            await self._search_official(client)
        elif config.CRAWLER_TYPE == "detail":
            await self._get_specified_tweets_official(client)
        elif config.CRAWLER_TYPE == "creator":
            await self._get_creators_and_tweets_official(client)
        else:
            utils.logger.error(f"[XCrawler] 不支持的爬取类型: {config.CRAWLER_TYPE}")

        utils.logger.info("[XCrawler] X 平台爬取完成 (官方 API)")

    async def _start_graphql(self) -> None:
        """使用 GraphQL + 浏览器模式进行爬取（原有逻辑）"""
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

            # 提取最新的 GraphQL query ID，评论获取等 API 调用依赖这些 ID
            await self._sniff_graphql_ids()

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
        """关键词搜索推文 — 通过浏览器导航 + 拦截响应实现"""
        utils.logger.info("[XCrawler] 开始搜索推文（浏览器拦截模式）...")
        keywords = config.KEYWORDS.split(",")
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        seen_user_ids: set = set()

        for keyword in keywords:
            keyword = keyword.strip()
            if not keyword:
                continue

            utils.logger.info(f"[XCrawler] 搜索关键词: {keyword}")
            source_keyword_var.set(keyword)

            collected_tweets = 0
            max_tweets = config.CRAWLER_MAX_NOTES_COUNT
            page = 0

            try:
                # 第一页：通过浏览器导航触发搜索
                search_url = (
                    f"https://x.com/search?q={keyword}&src=typed_query&f=top"
                )
                result = await self._navigate_and_capture(
                    search_url, "SearchTimeline"
                )

                while result and collected_tweets < max_tweets:
                    tweets, next_cursor = self._parse_search_result(result)

                    if not tweets:
                        utils.logger.info(f"[XCrawler] 关键词 '{keyword}' 无更多结果")
                        break

                    tweet_ids_for_comments = []
                    for raw_tweet in tweets:
                        if collected_tweets >= max_tweets:
                            break
                        tweet_data = extract_tweet_data(raw_tweet)
                        tweet_data["source_keyword"] = keyword
                        await x_store.update_x_tweet(tweet_data)
                        collected_tweets += 1
                        if config.ENABLE_GET_COMMENTS and tweet_data.get("tweet_id"):
                            tweet_ids_for_comments.append(tweet_data["tweet_id"])

                        # 从推文嵌入的用户数据中提取创作者信息（无需额外请求）
                        user_id = tweet_data.get("user_id", "")
                        if user_id and user_id not in seen_user_ids:
                            seen_user_ids.add(user_id)
                            try:
                                creator_data = extract_creator_from_tweet(raw_tweet)
                                if creator_data:
                                    await x_store.save_creator(user_id, creator_data)
                            except Exception as e:
                                utils.logger.debug(f"[XCrawler] 保存创作者 {user_id} 失败: {e}")

                    if tweet_ids_for_comments:
                        comment_tasks = [
                            asyncio.create_task(
                                self._get_tweet_comments_task(tid, semaphore)
                            )
                            for tid in tweet_ids_for_comments
                        ]
                        await asyncio.gather(*comment_tasks)

                    utils.logger.info(
                        f"[XCrawler] 关键词 '{keyword}' 已收集 {collected_tweets} 条推文"
                    )

                    if not next_cursor or collected_tweets >= max_tweets:
                        break

                    # 下一页：滚动到底部触发加载更多
                    result = await self._scroll_and_capture("SearchTimeline")
                    page += 1
                    await asyncio.sleep(random.uniform(2, 4))

            except Exception as e:
                utils.logger.error(f"[XCrawler] 搜索 '{keyword}' 异常: {e}")

            utils.logger.info(
                f"[XCrawler] 关键词 '{keyword}' 完成，共 {collected_tweets} 条推文"
            )
            await asyncio.sleep(random.uniform(1, 3))

    async def _navigate_and_capture(
        self, url: str, operation_name: str, timeout: int = 30000
    ) -> Optional[Dict]:
        """导航到 URL 并拦截指定 GraphQL 操作的响应"""
        import json as _json

        captured = []

        async def _on_response(response):
            req_url = response.url
            if f"/{operation_name}" in req_url and "/i/api/graphql/" in req_url:
                try:
                    body = await response.json()
                    captured.append(body)
                except Exception:
                    pass

        self.context_page.on("response", _on_response)
        try:
            await self.context_page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            # 等待 GraphQL 响应到达
            for _ in range(20):
                if captured:
                    break
                await asyncio.sleep(0.5)
            await asyncio.sleep(2)  # 额外等待确保数据完整
        finally:
            self.context_page.remove_listener("response", _on_response)

        return captured[0] if captured else None

    async def _scroll_and_capture(
        self, operation_name: str, timeout: int = 15000
    ) -> Optional[Dict]:
        """滚动页面触发加载更多，拦截 GraphQL 响应"""
        captured = []

        async def _on_response(response):
            req_url = response.url
            if f"/{operation_name}" in req_url and "/i/api/graphql/" in req_url:
                try:
                    body = await response.json()
                    captured.append(body)
                except Exception:
                    pass

        self.context_page.on("response", _on_response)
        try:
            await self.context_page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            for _ in range(30):
                if captured:
                    break
                await asyncio.sleep(0.5)
        finally:
            self.context_page.remove_listener("response", _on_response)

        return captured[0] if captured else None

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

    # ------------------------------------------------------------------
    # 官方 API 模式的爬取方法
    # ------------------------------------------------------------------

    async def _search_official(self, client) -> None:
        """官方 API 模式：关键词搜索推文"""
        utils.logger.info("[XCrawler] 开始搜索推文 (官方 API)...")
        keywords = config.KEYWORDS.split(",")
        seen_user_ids: set = set()

        for keyword in keywords:
            keyword = keyword.strip()
            if not keyword:
                continue

            utils.logger.info(f"[XCrawler] 搜索关键词: {keyword}")
            source_keyword_var.set(keyword)

            try:
                tweets = await client.search_tweets(
                    keyword, max_results=config.CRAWLER_MAX_NOTES_COUNT
                )
                utils.logger.info(
                    f"[XCrawler] 关键词 '{keyword}' 获取到 {len(tweets)} 条推文"
                )

                for tweet_data in tweets:
                    tweet_data["source_keyword"] = keyword
                    await x_store.update_x_tweet(tweet_data)

                    # 保存创作者信息（官方 API 的 tweet_data 已包含 user_id 等基础字段）
                    user_id = tweet_data.get("user_id", "")
                    if user_id and user_id not in seen_user_ids:
                        seen_user_ids.add(user_id)
                        try:
                            user_info = await client.get_user_info(tweet_data.get("username", ""))
                            if user_info:
                                await x_store.save_creator(user_id, user_info)
                        except Exception as e:
                            utils.logger.debug(f"[XCrawler] 保存创作者 {user_id} 失败: {e}")

                    if config.ENABLE_GET_COMMENTS and tweet_data.get("tweet_id"):
                        comments = await client.get_tweet_comments(
                            tweet_data["tweet_id"],
                            max_results=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
                        )
                        for comment in comments:
                            await x_store.update_x_tweet_comment(
                                tweet_data["tweet_id"], comment
                            )

            except DataFetchError as e:
                utils.logger.error(f"[XCrawler] 搜索 '{keyword}' 失败: {e}")
            except Exception as e:
                utils.logger.error(f"[XCrawler] 搜索 '{keyword}' 异常: {e}")

    async def _get_specified_tweets_official(self, client) -> None:
        """官方 API 模式：获取指定推文详情"""
        tweet_urls = getattr(config, "X_SPECIFIED_ID_LIST", [])
        if not tweet_urls:
            utils.logger.warning("[XCrawler] 未指定推文 URL 列表")
            return

        for url_or_id in tweet_urls:
            tweet_info = parse_tweet_url(url_or_id)
            tweet_id = tweet_info.tweet_id if tweet_info else url_or_id

            try:
                tweet_data = await client.get_tweet_detail(tweet_id)
                if tweet_data:
                    await x_store.update_x_tweet(tweet_data)

                    if config.ENABLE_GET_COMMENTS:
                        comments = await client.get_tweet_comments(
                            tweet_id,
                            max_results=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
                        )
                        for comment in comments:
                            await x_store.update_x_tweet_comment(tweet_id, comment)
                else:
                    utils.logger.warning(f"[XCrawler] 推文 {tweet_id} 未找到")
            except Exception as e:
                utils.logger.error(f"[XCrawler] 获取推文 {tweet_id} 失败: {e}")

    async def _get_creators_and_tweets_official(self, client) -> None:
        """官方 API 模式：获取创作者信息和推文"""
        creator_urls = getattr(config, "X_CREATOR_ID_LIST", [])
        if not creator_urls:
            utils.logger.warning("[XCrawler] 未指定创作者 URL 列表")
            return

        for url_or_username in creator_urls:
            creator_info = parse_creator_url(url_or_username)
            username = creator_info.username if creator_info else url_or_username

            try:
                creator_item = await client.get_user_info(username)
                if not creator_item:
                    utils.logger.warning(f"[XCrawler] 用户 {username} 未找到")
                    continue

                user_id = creator_item["user_id"]
                await x_store.save_creator(user_id, creator_item)

                tweets = await client.get_user_tweets(
                    user_id, max_results=config.CRAWLER_MAX_NOTES_COUNT
                )
                for tweet_data in tweets:
                    await x_store.update_x_tweet(tweet_data)

                utils.logger.info(
                    f"[XCrawler] 创作者 {username} 获取到 {len(tweets)} 条推文"
                )
            except Exception as e:
                utils.logger.error(f"[XCrawler] 获取创作者 {username} 失败: {e}")

    async def _sniff_graphql_ids(self) -> None:
        """动态提取 GraphQL query ID 和 features。

        三层策略：
        1. 拦截浏览器搜索请求 → 捕获 SearchTimeline
        2. 直接导航到推文页面 → 捕获 TweetDetail
        3. 解析 JS bundle → 兜底提取所有缺失的 query ID
        """
        from .client import GRAPHQL_QUERIES, DEFAULT_FEATURES
        import json
        import urllib.parse

        utils.logger.info("[XCrawler] 正在提取最新 GraphQL 参数...")

        captured: Dict[str, Dict] = {}
        all_seen_ops: Dict[str, str] = {}

        async def _on_request(request):
            url = request.url
            if "/i/api/graphql/" not in url:
                return
            match = re.search(r"/i/api/graphql/([^/]+)/([^?]+)", url)
            if not match:
                return
            qid, op_name = match.group(1), match.group(2)
            all_seen_ops[op_name] = qid
            if op_name in GRAPHQL_QUERIES and op_name not in captured:
                entry = {"query_id": qid}
                parsed = urllib.parse.urlparse(url)
                qs = urllib.parse.parse_qs(parsed.query)
                if "features" in qs:
                    try:
                        entry["features"] = json.loads(qs["features"][0])
                    except (json.JSONDecodeError, IndexError):
                        pass
                captured[op_name] = entry
                utils.logger.info(f"[XCrawler] 捕获到 {op_name} -> {qid}")

        self.context_page.on("request", _on_request)

        try:
            # Step 1: 搜索页 → 捕获 SearchTimeline
            await self.context_page.goto(
                "https://x.com/search?q=test&src=typed_query&f=top",
                wait_until="networkidle", timeout=30000,
            )
            await asyncio.sleep(3)

            # Step 2: 直接导航到一条推文 → 捕获 TweetDetail
            # 从搜索结果页 DOM 中提取一个推文链接，用 goto 做完整导航
            if "TweetDetail" not in captured:
                tweet_url = await self._extract_tweet_url_from_page()
                if tweet_url:
                    utils.logger.info(
                        f"[XCrawler] 导航到推文页面以捕获 TweetDetail: {tweet_url}"
                    )
                    try:
                        await self.context_page.goto(
                            tweet_url, wait_until="networkidle", timeout=20000,
                        )
                        await asyncio.sleep(3)
                    except Exception as e:
                        utils.logger.debug(f"[XCrawler] 推文页面导航失败: {e}")
                else:
                    utils.logger.debug("[XCrawler] 未能从页面提取推文链接")

        except Exception as e:
            utils.logger.warning(f"[XCrawler] 浏览器导航异常（不影响已捕获的 ID）: {e}")
        finally:
            self.context_page.remove_listener("request", _on_request)

        if all_seen_ops:
            utils.logger.info(
                f"[XCrawler] 浏览器拦截到的所有 GraphQL 操作: "
                + ", ".join(f"{k}={v}" for k, v in all_seen_ops.items())
            )

        # 更新已捕获的 query ID
        for op_name, info in captured.items():
            GRAPHQL_QUERIES[op_name] = info["query_id"]

        for op_name, info in captured.items():
            if "features" in info:
                DEFAULT_FEATURES.clear()
                DEFAULT_FEATURES.update(info["features"])
                utils.logger.info(
                    f"[XCrawler] 已从 {op_name} 更新 features ({len(info['features'])} 项)"
                )
                break

        # Step 3: 对仍缺失的 query ID，从 JS bundle 中解析
        missing = [op for op in GRAPHQL_QUERIES if not GRAPHQL_QUERIES[op]]
        if missing:
            utils.logger.info(
                f"[XCrawler] 以下操作仍缺少 query ID，尝试从 JS bundle 解析: {missing}"
            )
            bundle_ids = await self._extract_query_ids_from_js_bundle(missing)
            for op_name, qid in bundle_ids.items():
                GRAPHQL_QUERIES[op_name] = qid
                utils.logger.info(f"[XCrawler] 从 JS bundle 提取到 {op_name} -> {qid}")

        filled = {k: v for k, v in GRAPHQL_QUERIES.items() if v}
        still_missing = [k for k, v in GRAPHQL_QUERIES.items() if not v]
        if filled:
            utils.logger.info(
                f"[XCrawler] 最终 GraphQL 端点: "
                + ", ".join(f"{k}={v}" for k, v in filled.items())
            )
        if still_missing:
            utils.logger.warning(f"[XCrawler] 以下操作最终仍缺少 query ID: {still_missing}")

    async def _extract_tweet_url_from_page(self) -> Optional[str]:
        """从当前页面 DOM 中提取一个推文的完整 URL。"""
        try:
            # 多种选择器兼容 X 前端不同版本的 DOM 结构
            selectors = [
                'a[href*="/status/"]',
                'article a[href*="/status/"]',
                '[data-testid="tweet"] a[href*="/status/"]',
            ]
            for selector in selectors:
                links = self.context_page.locator(selector)
                count = await links.count()
                for i in range(min(count, 10)):
                    href = await links.nth(i).get_attribute("href")
                    if href and re.search(r"/status/\d+", href):
                        if href.startswith("/"):
                            return f"https://x.com{href}"
                        return href
        except Exception as e:
            utils.logger.debug(f"[XCrawler] 提取推文链接失败: {e}")
        return None

    async def _extract_query_ids_from_js_bundle(
        self, target_ops: List[str]
    ) -> Dict[str, str]:
        """从 X 前端 JS bundle 中解析 GraphQL query ID。

        X 的前端将所有 GraphQL 操作编译进 JS bundle，格式类似：
          {queryId:"aBcDeFg",operationName:"TweetDetail",...}
        通过正则匹配即可提取。
        """
        import httpx

        result: Dict[str, str] = {}
        if not target_ops:
            return result

        try:
            # 从当前页面获取所有 JS bundle URL
            js_urls = await self.context_page.evaluate("""
                () => {
                    const scripts = document.querySelectorAll('script[src]');
                    return Array.from(scripts)
                        .map(s => s.src)
                        .filter(u => u.includes('/client-web/') || u.includes('.js'));
                }
            """)

            if not js_urls:
                utils.logger.debug("[XCrawler] 页面中未找到 JS bundle URL")
                return result

            utils.logger.info(f"[XCrawler] 找到 {len(js_urls)} 个 JS bundle，开始扫描...")

            # 构建匹配目标操作名的正则
            # X bundle 中的典型格式:
            #   queryId:"aBcDeFg",operationName:"TweetDetail"
            #   queryId:"aBcDeFg",operationName:"SearchTimeline"
            #   也可能是反序: operationName:"TweetDetail",... queryId:"aBcDeFg"
            ops_pattern = "|".join(re.escape(op) for op in target_ops)
            # 正向: queryId 在前
            pattern_forward = re.compile(
                r'queryId\s*:\s*"([^"]+)"\s*,\s*operationName\s*:\s*"('
                + ops_pattern + r')"'
            )
            # 反向: operationName 在前
            pattern_reverse = re.compile(
                r'operationName\s*:\s*"(' + ops_pattern
                + r')"\s*,\s*operationType\s*:\s*"[^"]*"\s*,\s*queryId\s*:\s*"([^"]+)"'
            )

            headers = {
                "User-Agent": self.user_agent,
                "Referer": "https://x.com/",
            }
            cookies = {k: v for k, v in self.x_client.cookie_dict.items()}

            async with httpx.AsyncClient(
                timeout=15, follow_redirects=True
            ) as client:
                for js_url in js_urls:
                    if len(result) >= len(target_ops):
                        break
                    try:
                        resp = await client.get(
                            js_url, headers=headers, cookies=cookies
                        )
                        if resp.status_code != 200:
                            continue
                        text = resp.text

                        for m in pattern_forward.finditer(text):
                            qid, op_name = m.group(1), m.group(2)
                            if op_name not in result:
                                result[op_name] = qid

                        for m in pattern_reverse.finditer(text):
                            op_name, qid = m.group(1), m.group(2)
                            if op_name not in result:
                                result[op_name] = qid

                    except Exception as e:
                        utils.logger.debug(
                            f"[XCrawler] 解析 JS bundle 失败 ({js_url[:80]}...): {e}"
                        )
                        continue

        except Exception as e:
            utils.logger.warning(f"[XCrawler] JS bundle 解析流程异常: {e}")

        return result

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
        from .client import GRAPHQL_QUERIES
        if not GRAPHQL_QUERIES.get("TweetDetail"):
            utils.logger.warning(
                f"[XCrawler] TweetDetail query ID 未捕获，跳过推文 {tweet_id} 的评论获取"
            )
            return

        max_comments = config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES
        all_count = 0
        cursor = None

        while all_count < max_comments:
            try:
                result = await self.x_client.get_tweet_detail(tweet_id, cursor=cursor)
                if not result:
                    utils.logger.debug(f"[XCrawler] 推文 {tweet_id} 评论请求返回空结果")
                    break
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