# -*- coding: utf-8 -*-
"""
南非新闻网站数据字段定义
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class NewsArticle:
    """新闻文章数据结构"""
    article_id: str = ""
    source_site: str = ""
    title: str = ""
    content: str = ""
    summary: str = ""
    author: str = ""
    publish_time: str = ""
    article_url: str = ""
    image_urls: str = "[]"
    category: str = ""
    tags: str = "[]"
    source_keyword: str = ""

    def to_dict(self) -> dict:
        return {
            "article_id": self.article_id,
            "source_site": self.source_site,
            "title": self.title,
            "content": self.content,
            "summary": self.summary,
            "author": self.author,
            "publish_time": self.publish_time,
            "article_url": self.article_url,
            "image_urls": self.image_urls,
            "category": self.category,
            "tags": self.tags,
            "source_keyword": self.source_keyword,
        }
