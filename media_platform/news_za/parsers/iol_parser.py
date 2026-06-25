# -*- coding: utf-8 -*-
"""
Independent Online (iol.co.za) 解析器
Next.js 站点，CSS Modules（class 带 hash 后缀，用 [class*=] 匹配）
"""

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from .base_parser import BaseNewsParser


class IOLParser(BaseNewsParser):
    site_key = "iol"
    site_name = "Independent Online"
    base_url = "https://iol.co.za"

    def parse_article_list(self, html: str) -> List[str]:
        soup = BeautifulSoup(html, "lxml")
        urls = []
        for a in soup.select("article a[href], .article-item a[href], .card a[href]"):
            href = a.get("href", "")
            url = self._abs_url(href)
            if url and url not in urls and ("/news/" in url or "/politics/" in url or "/business/" in url):
                urls.append(url)
        if not urls:
            for a in soup.select("h2 a[href], h3 a[href], h4 a[href]"):
                href = a.get("href", "")
                url = self._abs_url(href)
                if url and url not in urls:
                    urls.append(url)
        return urls

    def parse_article_detail(self, html: str, url: str) -> Optional[Dict]:
        soup = BeautifulSoup(html, "lxml")

        # 标题: CSS Modules div[class*="titles_article-titles"] 内的 h1
        title_el = soup.select_one("[class*='titles_article-titles'] h1")
        if not title_el:
            title_el = soup.select_one("h1")
        title = self._clean_text(title_el.get_text()) if title_el else ""
        if not title:
            return None

        # 正文: 多个 div[class*="text_text"] 块拼接
        body_blocks = soup.select("[class*='text_text']")
        content = ""
        if body_blocks:
            parts = []
            for block in body_blocks:
                for p in block.select("p, h2, h3"):
                    txt = self._clean_text(p.get_text())
                    if txt:
                        parts.append(txt)
            content = " ".join(parts)

        # 摘要: meta description
        summary = self._meta(soup, "name", "description")

        # 作者: meta article:author 或 CSS Modules 选择器
        author = self._meta(soup, "property", "article:author")
        if not author:
            author_el = soup.select_one("[class*='attribution-and-updated_author-text'] a")
            author = self._clean_text(author_el.get_text()) if author_el else ""

        # 发布时间: meta article:published_time (Unix 毫秒时间戳)
        publish_time = ""
        raw_ts = self._meta(soup, "property", "article:published_time")
        if raw_ts and raw_ts.isdigit():
            try:
                dt = datetime.fromtimestamp(int(raw_ts) / 1000, tz=timezone.utc)
                publish_time = dt.isoformat()
            except (ValueError, OSError):
                publish_time = raw_ts
        elif raw_ts:
            publish_time = raw_ts

        # 图片
        images = []
        hero = soup.select_one("[class*='image_image-widget'] img[src]")
        if hero:
            images.append(self._abs_url(hero["src"]))

        # 分类
        category = self._meta(soup, "property", "article:section")

        # 标签
        tag_metas = soup.select("meta[property='article:tag']")
        tags = [t.get("content", "") for t in tag_metas if t.get("content")]

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
            "tags": json.dumps(tags),
        }