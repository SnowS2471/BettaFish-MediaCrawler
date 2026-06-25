# -*- coding: utf-8 -*-
"""
X (Twitter) 登录管理
支持 Cookie 登录和账号密码登录
"""

import asyncio
from typing import Optional

from playwright.async_api import BrowserContext, Page
from tenacity import retry, retry_if_result, stop_after_attempt, wait_fixed

import config
from base.base_crawler import AbstractLogin
from tools import utils


class XLogin(AbstractLogin):

    def __init__(
        self,
        login_type: str,
        browser_context: BrowserContext,
        context_page: Page,
        login_phone: Optional[str] = "",
        cookie_str: str = "",
    ):
        config.LOGIN_TYPE = login_type
        self.browser_context = browser_context
        self.context_page = context_page
        self.login_phone = login_phone
        self.cookie_str = cookie_str

    @retry(stop=stop_after_attempt(600), wait=wait_fixed(1), retry=retry_if_result(lambda v: v is False))
    async def check_login_state(self, no_logged_in_session: str) -> bool:
        """
        检查登录状态
        通过检查 Cookie 中的 auth_token 和页面元素判断
        """
        # 1. 检查页面是否有用户头像/导航栏元素
        try:
            nav_selector = 'a[data-testid="AppTabBar_Profile_Link"]'
            is_visible = await self.context_page.is_visible(nav_selector, timeout=500)
            if is_visible:
                utils.logger.info("[XLogin.check_login_state] 通过页面元素确认已登录")
                return True
        except Exception:
            pass

        # 2. 检查 Cookie 变化
        current_cookies = await self.browser_context.cookies()
        _, cookie_dict = utils.convert_cookies(current_cookies)
        auth_token = cookie_dict.get("auth_token")
        if auth_token and auth_token != no_logged_in_session:
            utils.logger.info("[XLogin.check_login_state] 通过 Cookie 确认已登录")
            return True

        return False

    async def begin(self):
        """开始登录流程"""
        utils.logger.info("[XLogin.begin] 开始 X 平台登录...")

        if self.cookie_str:
            # 优先使用 Cookie 登录
            await self.login_by_cookies()
        elif config.LOGIN_TYPE == "phone":
            await self.login_by_mobile()
        else:
            # 默认使用 Cookie 登录（X 不支持二维码登录）
            await self.login_by_cookies()

    async def login_by_qrcode(self):
        """X 平台不支持二维码登录，降级为等待手动登录"""
        utils.logger.info("[XLogin.login_by_qrcode] X 不支持二维码登录，请在浏览器中手动登录")
        # 导航到登录页面
        await self.context_page.goto("https://x.com/i/flow/login")
        # 获取当前未登录状态的 session 标识
        current_cookies = await self.browser_context.cookies()
        _, cookie_dict = utils.convert_cookies(current_cookies)
        no_logged_in_session = cookie_dict.get("auth_token", "")
        # 等待用户手动登录
        await self.check_login_state(no_logged_in_session)
        utils.logger.info("[XLogin.login_by_qrcode] 手动登录成功")

    async def login_by_mobile(self):
        """账号密码登录"""
        utils.logger.info("[XLogin.login_by_mobile] 请在浏览器中完成账号密码登录")
        await self.context_page.goto("https://x.com/i/flow/login")
        current_cookies = await self.browser_context.cookies()
        _, cookie_dict = utils.convert_cookies(current_cookies)
        no_logged_in_session = cookie_dict.get("auth_token", "")
        await self.check_login_state(no_logged_in_session)
        utils.logger.info("[XLogin.login_by_mobile] 登录成功")

    async def login_by_cookies(self):
        """Cookie 登录"""
        utils.logger.info("[XLogin.login_by_cookies] 使用 Cookie 登录 X 平台")
        if not self.cookie_str:
            # 没有提供 Cookie，等待手动登录
            utils.logger.info("[XLogin.login_by_cookies] 未提供 Cookie，请在浏览器中手动登录")
            await self.context_page.goto("https://x.com/i/flow/login")
            current_cookies = await self.browser_context.cookies()
            _, cookie_dict = utils.convert_cookies(current_cookies)
            no_logged_in_session = cookie_dict.get("auth_token", "")
            await self.check_login_state(no_logged_in_session)
            return

        # 解析并注入 Cookie
        for cookie_pair in self.cookie_str.split(";"):
            cookie_pair = cookie_pair.strip()
            if "=" in cookie_pair:
                name, value = cookie_pair.split("=", 1)
                await self.browser_context.add_cookies([{
                    "name": name.strip(),
                    "value": value.strip(),
                    "domain": ".x.com",
                    "path": "/",
                }])

        # 刷新页面验证 Cookie 是否有效
        await self.context_page.goto("https://x.com/home")
        await asyncio.sleep(2)

        # 验证登录状态
        current_cookies = await self.browser_context.cookies()
        _, cookie_dict = utils.convert_cookies(current_cookies)
        if cookie_dict.get("auth_token"):
            utils.logger.info("[XLogin.login_by_cookies] Cookie 登录成功")
        else:
            utils.logger.error("[XLogin.login_by_cookies] Cookie 登录失败，请检查 Cookie 是否有效")
            raise Exception("Cookie 登录失败")