# -*- coding: utf-8 -*-
"""
News24 South Africa (news24.com/SouthAfrica) 解析器
南非最大新闻网站，Cloudflare 保护，需要 Playwright 渲染
无法直接验证 HTML 结构，保留猜测选择器 + JSON-LD 兜底
"""

import json
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from .base_parser import BaseNewsParser


class News24Parser(BaseNewsParser):
    site_key = "news24"
    site_name = "News24 South Africa"
    base_url = "https://www.news24.com"

    def parse_article_list(self, html: str) -> List[str]:
        soup = BeautifulSoup(html, "lxml")
        urls = []
        for a in soup.select(
            "article a[href], .article-item a[href], "
            ".article-list a[href], .card a[href], "
            "[data-testid='article-item'] a[href]"
        ):
            href = a.get("href", "")
            url = self._abs_url(href)
            if url and url not in urls and "/news/" in url.lower():
                urls.append(url)
        if not urls:
            for a in soup.select("h2 a[href], h3 a[href], h4 a[href]"):
                href = a.get("href", "")
                url = self._abs_url(href)
                if url and url not in urls and "news24.com" in url:
                    urls.append(url)
        return urls

    def parse_article_detail(self, html: str, url: str) -> Optional[Dict]:
        soup = BeautifulSoup(html, "lxml")

        # 尝试 CSS 选择器
        title = self._try_title(soup)
        content = self._try_content(soup)
        summary = self._meta(soup, "name", "description")
        author = self._try_author(soup)
        publish_time = self._meta(soup, "property", "article:published_time")
        category = self._meta(soup, "property", "article:section")

        # JSON-LD 兜底：如果 CSS 选择器没拿到正文，从 JSON-LD 补充
        if not title or not content:
            ld = self._extract_jsonld(soup)
            if ld:
                if not title:
                    title = ld.get("headline", "")
                if not content:
                    content = ld.get("articleBody", "")
                if not summary:
                    summary = ld.get("description", "")
                if not author:
                    authors = ld.get("author", [])
                    if isinstance(authors, list):
                        author = ", ".join(a.get("name", "") for a in authors if isinstance(a, dict))
                    elif isinstance(authors, dict):
                        author = authors.get("name", "")
                if not publish_time:
                    publish_time = ld.get("datePublished", "")
                if not category:
                    category = ld.get("articleSection", "")

        # 最终兜底：从所有 <p> 标签提取正文
        if not content:
            article_el = soup.select_one("article")
            container = article_el or soup.select_one("[role='main']") or soup
            paragraphs = container.select("p")
            parts = [self._clean_text(p.get_text()) for p in paragraphs if len(p.get_text(strip=True)) > 40]
            content = " ".join(parts)

        if not title:
            return None

        # 图片
        images = []
        og_img = self._meta(soup, "property", "og:image")
        if og_img:
            images.append(og_img)

        return {
            "article_id": self._make_article_id(url),
            "source_site": self.site_key,
            "title": title,
            "content": content,
            "summary": summary,
            "author": author,
            "publish_time": publish_time,
            "article_url": url,
            "image_urls": json.dumps(images),
            "category": category,
            "tags": "[]",
        }

    def _try_title(self, soup: BeautifulSoup) -> str:
        for sel in ("h1.article__title", "h1.article-title", "article h1", "h1"):
            el = soup.select_one(sel)
            if el:
                return self._clean_text(el.get_text())
        return self._meta(soup, "property", "og:title")

    def _try_content(self, soup: BeautifulSoup) -> str:
        for sel in (
            ".article__body", ".article-body", ".article-content",
            "[data-testid='article-body']", "article .body",
        ):
            el = soup.select_one(sel)
            if el:
                return self._clean_text(el.get_text())
        return ""

    def _try_author(self, soup: BeautifulSoup) -> str:
        author = self._meta(soup, "property", "article:author")
        if author:
            return author
        for sel in (".article__author", ".author-name", ".byline", "[data-testid='author']"):
            el = soup.select_one(sel)
            if el:
                return self._clean_text(el.get_text())
        return ""