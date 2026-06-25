# -*- coding: utf-8 -*-
"""
Sowetan (sowetan.co.za) 解析器
Arena Holdings / Arc Publishing (Fusion engine)
"""

import json
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from .base_parser import BaseNewsParser


class SowetanParser(BaseNewsParser):
    site_key = "sowetan"
    site_name = "Sowetan"
    base_url = "https://www.sowetan.co.za"

    def parse_article_list(self, html: str) -> List[str]:
        soup = BeautifulSoup(html, "lxml")
        urls = []
        for a in soup.select(
            "article a[href], .article-card a[href], .card a[href], "
            ".article-list a[href], h2 a[href], h3 a[href]"
        ):
            href = a.get("href", "")
            url = self._abs_url(href)
            if url and url not in urls and ("/news/" in url or "/opinion/" in url):
                urls.append(url)
        if not urls:
            for a in soup.select("a[href]"):
                href = a.get("href", "")
                url = self._abs_url(href)
                if url and url not in urls and ("/news/" in url or "/opinion/" in url or "/sport/" in url):
                    urls.append(url)
        return urls

    def parse_article_detail(self, html: str, url: str) -> Optional[Dict]:
        soup = BeautifulSoup(html, "lxml")

        # 标题: h1.b-headline
        title_el = soup.select_one("h1.b-headline, h1")
        title = self._clean_text(title_el.get_text()) if title_el else ""
        if not title:
            return None

        # 正文: article.b-article-body > p.c-paragraph
        body_el = soup.select_one("article.b-article-body")
        content = ""
        if body_el:
            paragraphs = body_el.select("p.c-paragraph")
            content = " ".join(self._clean_text(p.get_text()) for p in paragraphs if p.get_text(strip=True))

        # 摘要: h2.b-subheadline 或 meta description
        summary_el = soup.select_one("h2.b-subheadline")
        summary = self._clean_text(summary_el.get_text()) if summary_el else self._meta(soup, "name", "description")

        # 作者: h2.b-author-bio__author-name
        author_el = soup.select_one("h2.b-author-bio__author-name")
        author = self._clean_text(author_el.get_text()) if author_el else ""

        # 发布时间: time.b-date[dateTime]
        time_el = soup.select_one("time.b-date[dateTime]")
        publish_time = time_el.get("dateTime", "") if time_el else ""

        # 图片
        images = []
        lead_img = soup.select_one("div.b-lead-art img[src]")
        if lead_img:
            images.append(self._abs_url(lead_img["src"]))

        # 分类: a.b-overline
        cat_el = soup.select_one("a.b-overline")
        category = self._clean_text(cat_el.get_text()) if cat_el else ""

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