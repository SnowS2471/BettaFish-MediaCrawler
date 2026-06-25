# -*- coding: utf-8 -*-
"""
南非新闻网站爬虫核心逻辑
"""

import asyncio
import random
from typing import Dict, List, Optional

from playwright.async_api import BrowserContext, BrowserType, Playwright

import config
from base.base_crawler import AbstractCrawler
from store import news_za as news_za_store
from tools import utils
from var import crawler_type_var, source_keyword_var

from .client import SANewsClient
from .parsers import PARSER_MAP


class SANewsCrawler(AbstractCrawler):
    """南非新闻网站爬虫"""

    def __init__(self) -> None:
        self.client: Optional[SANewsClient] = None

    async def start(self) -> None:
        httpx_proxy = None
        if config.ENABLE_IP_PROXY:
            from proxy.proxy_ip_pool import create_ip_pool
            pool = await create_ip_pool(config.IP_PROXY_POOL_COUNT, enable_validate_ip=True)
            ip_info = await pool.get_proxy()
            _, httpx_proxy = utils.format_proxy_info(ip_info)

        self.client = SANewsClient(proxy=httpx_proxy)
        crawler_type_var.set(config.CRAWLER_TYPE)

        try:
            if config.CRAWLER_TYPE == "search":
                await self.search()
            else:
                # 默认抓取各站点首页最新文章
                await self.get_latest()
        finally:
            await self.client.close()

        utils.logger.info("[SANewsCrawler] 南非新闻爬取完成")

        # 爬取完成后自动翻译
        if getattr(config, "SA_NEWS_AUTO_TRANSLATE", False):
            try:
                from .translation.translator import run_translation
                count = await run_translation()
                utils.logger.info(f"[SANewsCrawler] 自动翻译完成，成功 {count} 篇")
            except Exception as e:
                utils.logger.error(f"[SANewsCrawler] 自动翻译失败: {e}")

        # 翻译完成后自动评估翻译质量
        if getattr(config, "SA_NEWS_AUTO_EVALUATE", True):
            try:
                from .translation.evaluator import run_evaluation
                eval_count = await run_evaluation()
                utils.logger.info(f"[SANewsCrawler] 自动评估完成，成功 {eval_count} 篇")
            except Exception as e:
                utils.logger.error(f"[SANewsCrawler] 自动评估失败: {e}")

    async def search(self) -> None:
        """按关键词搜索各站点"""
        keywords = [k.strip() for k in config.KEYWORDS.split(",") if k.strip()]
        sites = self._get_enabled_sites()

        for keyword in keywords:
            utils.logger.info(f"[SANewsCrawler] 搜索关键词: {keyword}")
            source_keyword_var.set(keyword)

            for site_key, site_cfg in sites.items():
                parser = PARSER_MAP.get(site_key)
                if not parser:
                    continue
                parser_inst = parser()

                search_url = site_cfg.get("search_url", "")
                if not search_url:
                    utils.logger.warning(f"[SANewsCrawler] {site_key} 无搜索 URL，跳过")
                    continue

                url = search_url.format(keyword=keyword)
                utils.logger.info(f"[SANewsCrawler] 搜索 {site_cfg['name']}: {url}")

                try:
                    html = await self.client.fetch_page(url)
                except Exception as e:
                    utils.logger.error(f"[SANewsCrawler] 搜索页获取失败: {e}")
                    continue

                article_urls = parser_inst.parse_search_results(html)
                max_articles = getattr(config, "SA_NEWS_MAX_ARTICLES_PER_SITE", 50)
                article_urls = article_urls[:max_articles]

                utils.logger.info(
                    f"[SANewsCrawler] {site_cfg['name']} 搜索到 {len(article_urls)} 篇文章"
                )

                await self._crawl_articles(parser_inst, article_urls, keyword)

                delay = getattr(config, "SA_NEWS_CRAWL_DELAY", 2)
                await asyncio.sleep(delay + random.uniform(0, 1))

    async def get_latest(self) -> None:
        """抓取各站点首页最新文章"""
        sites = self._get_enabled_sites()

        for site_key, site_cfg in sites.items():
            parser = PARSER_MAP.get(site_key)
            if not parser:
                continue
            parser_inst = parser()

            # 使用 section_url（如 News24 的 /SouthAfrica）或 base_url
            list_url = site_cfg.get("section_url", site_cfg["base_url"])
            utils.logger.info(f"[SANewsCrawler] 抓取 {site_cfg['name']} 首页: {list_url}")

            try:
                html = await self.client.fetch_page(list_url)
            except Exception as e:
                utils.logger.error(f"[SANewsCrawler] 首页获取失败: {e}")
                continue

            article_urls = parser_inst.parse_article_list(html)
            max_articles = getattr(config, "SA_NEWS_MAX_ARTICLES_PER_SITE", 50)
            article_urls = article_urls[:max_articles]

            utils.logger.info(
                f"[SANewsCrawler] {site_cfg['name']} 发现 {len(article_urls)} 篇文章"
            )

            await self._crawl_articles(parser_inst, article_urls)

            delay = getattr(config, "SA_NEWS_CRAWL_DELAY", 2)
            await asyncio.sleep(delay + random.uniform(0, 1))

    async def _crawl_articles(
        self, parser, article_urls: List[str], keyword: str = ""
    ) -> None:
        """逐篇抓取文章详情并存储"""
        delay = getattr(config, "SA_NEWS_CRAWL_DELAY", 2)

        for url in article_urls:
            try:
                html = await self.client.fetch_page(url)
                article_data = parser.parse_article_detail(html, url)
                if article_data:
                    if keyword:
                        article_data["source_keyword"] = keyword
                    await news_za_store.update_sa_news_article(article_data)
                else:
                    utils.logger.warning(f"[SANewsCrawler] 解析失败: {url}")
            except Exception as e:
                utils.logger.error(f"[SANewsCrawler] 文章抓取失败: {url} - {e}")

            await asyncio.sleep(delay + random.uniform(0, 0.5))

    def _get_enabled_sites(self) -> Dict:
        """获取启用的站点配置"""
        all_sites = getattr(config, "SA_NEWS_SITES", {})
        specified = getattr(config, "SA_NEWS_SPECIFIED_SITES", [])

        if specified:
            return {k: v for k, v in all_sites.items() if k in specified}
        return {k: v for k, v in all_sites.items() if v.get("enabled", True)}

    async def launch_browser(
        self,
        chromium: BrowserType,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        """新闻站点不需要浏览器，此方法不会被调用"""
        raise NotImplementedError("SANewsCrawler 使用 httpx，不需要浏览器")
