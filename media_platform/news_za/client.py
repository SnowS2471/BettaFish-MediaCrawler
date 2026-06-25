# -*- coding: utf-8 -*-
"""
南非新闻网站 HTTP 客户端
三级回退: httpx → curl_cffi → Playwright
"""

import asyncio
import random
from typing import Optional
from urllib.parse import urlparse

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from tools import utils

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]

# 每个域名记住最佳获取方式: "httpx" / "cffi" / "playwright"
_domain_strategy: dict[str, str] = {}


class SANewsClient:
    """南非新闻网站 HTTP 客户端"""

    def __init__(self, proxy: Optional[str] = None, timeout: float = 30.0):
        self.proxy = proxy
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._pw_browser = None
        self._pw_context = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                proxy=self.proxy,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Connection": "keep-alive",
                },
                verify=True,
            )
        return self._client

    # ---- 第一级: httpx ----
    async def _fetch_httpx(self, url: str) -> Optional[str]:
        client = await self._get_client()
        headers = {"User-Agent": random.choice(USER_AGENTS)}
        resp = await client.get(url, headers=headers)
        if resp.status_code == 403:
            return None  # 触发下一级
        resp.raise_for_status()
        return resp.text

    # ---- 第二级: curl_cffi ----
    def _fetch_cffi_sync(self, url: str) -> str:
        from curl_cffi import requests as cffi_requests
        resp = cffi_requests.get(
            url, impersonate="chrome",
            timeout=int(self.timeout), allow_redirects=True,
        )
        resp.raise_for_status()
        return resp.text

    async def _fetch_cffi(self, url: str) -> Optional[str]:
        try:
            return await asyncio.to_thread(self._fetch_cffi_sync, url)
        except Exception:
            return None  # 触发下一级

    # ---- 第三级: Playwright ----
    async def _ensure_playwright(self):
        if self._pw_context is not None:
            return
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        self._pw_browser = await self._pw.chromium.launch(headless=True)
        self._pw_context = await self._pw_browser.new_context(
            user_agent=USER_AGENTS[0],
            viewport={"width": 1280, "height": 800},
        )

    async def _fetch_playwright(self, url: str) -> str:
        await self._ensure_playwright()
        page = await self._pw_context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)  # 等 JS 渲染
            return await page.content()
        finally:
            await page.close()

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=8))
    async def fetch_page(self, url: str) -> str:
        """三级回退获取页面: httpx → curl_cffi → Playwright"""
        domain = urlparse(url).netloc
        strategy = _domain_strategy.get(domain, "httpx")

        # 按已知策略直接走
        if strategy == "playwright":
            return await self._fetch_playwright(url)
        if strategy == "cffi":
            result = await self._fetch_cffi(url)
            if result is not None:
                return result
            # cffi 也失败了，升级到 playwright
            utils.logger.info(f"[SANewsClient] curl_cffi 失败, 升级 Playwright: {domain}")
            _domain_strategy[domain] = "playwright"
            return await self._fetch_playwright(url)

        # 默认从 httpx 开始
        result = await self._fetch_httpx(url)
        if result is not None:
            return result

        # httpx 403 → 尝试 curl_cffi
        utils.logger.info(f"[SANewsClient] httpx 403, 尝试 curl_cffi: {domain}")
        result = await self._fetch_cffi(url)
        if result is not None:
            _domain_strategy[domain] = "cffi"
            return result

        # curl_cffi 也失败 → Playwright
        utils.logger.info(f"[SANewsClient] curl_cffi 失败, 升级 Playwright: {domain}")
        _domain_strategy[domain] = "playwright"
        return await self._fetch_playwright(url)

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        if self._pw_context:
            await self._pw_context.close()
        if self._pw_browser:
            await self._pw_browser.close()
        if hasattr(self, "_pw") and self._pw:
            await self._pw.stop()