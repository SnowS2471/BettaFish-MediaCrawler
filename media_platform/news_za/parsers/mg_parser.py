# -*- coding: utf-8 -*-
"""
Mail & Guardian (mg.co.za) 解析器
WordPress 站点，主题 MG-Boot-Child
"""

import json
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from .base_parser import BaseNewsParser


class MGParser(BaseNewsParser):
    site_key = "mg"
    site_name = "Mail & Guardian"
    base_url = "https://mg.co.za"

    def parse_article_list(self, html: str) -> List[str]:
        soup = BeautifulSoup(html, "lxml")
        urls = []
        for article in soup.select("article a[href]"):
            href = article.get("href", "")
            url = self._abs_url(href)
            if url and url not in urls and self._is_article_url(url):
                urls.append(url)
        if not urls:
            for heading in soup.select("h2 a[href], h3 a[href]"):
                href = heading.get("href", "")
                url = self._abs_url(href)
                if url and url not in urls and self._is_article_url(url):
                    urls.append(url)
        return urls

    @staticmethod
    def _is_article_url(url: str) -> bool:
        skip = ("/section/", "/author/", "/tag/", "/category/", "/page/")
        return not any(s in url for s in skip)

    def parse_article_detail(self, html: str, url: str) -> Optional[Dict]:
        soup = BeautifulSoup(html, "lxml")

        # 标题: h1.single-title
        title_el = soup.select_one("h1.single-title, h1.entry-title, article h1")
        title = self._clean_text(title_el.get_text()) if title_el else ""
        if not title:
            return None

        # 正文: div.entry-content
        body_el = soup.select_one("div.entry-content, .post-content")
        content = ""
        if body_el:
            paragraphs = body_el.select("p")
            content = " ".join(self._clean_text(p.get_text()) for p in paragraphs if p.get_text(strip=True))

        # 摘要: meta description
        summary = self._meta(soup, "name", "description")

        # 作者: div.byline-single 内的 a[rel=author]
        author_el = soup.select_one("a[rel='author'], div.byline-single a")
        author = self._clean_text(author_el.get_text()) if author_el else ""

        # 发布时间: meta article:published_time (页面无 <time> 标签)
        publish_time = self._meta(soup, "property", "article:published_time")
        if not publish_time:
            date_el = soup.select_one("div.meta-box-date")
            if date_el:
                publish_time = self._clean_text(date_el.get_text()).lstrip("/ ").strip()

        # 图片
        images = []
        if body_el:
            for img in body_el.select("img[src]"):
                images.append(self._abs_url(img["src"]))

        # 分类
        category = self._meta(soup, "property", "article:section")
        if not category:
            cat_el = soup.select_one("div.entry-meta > a")
            category = self._clean_text(cat_el.get_text()) if cat_el else ""

        # 标签
        tag_els = soup.select("div.entry-tags a[rel='tag']")
        tags = [self._clean_text(t.get_text()) for t in tag_els] if tag_els else []

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