# -*- coding: utf-8 -*-
"""
新闻解析器基类
"""

import hashlib
import json
import re
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup


class BaseNewsParser(ABC):
    """新闻站点解析器基类"""

    site_key: str = ""
    site_name: str = ""
    base_url: str = ""

    def _make_article_id(self, url: str) -> str:
        """根据 URL 生成唯一文章 ID"""
        return hashlib.md5(url.encode()).hexdigest()[:16]

    def _abs_url(self, url: str) -> str:
        """将相对 URL 转为绝对 URL"""
        if url.startswith("http"):
            return url
        return urljoin(self.base_url, url)

    def _clean_text(self, text: str) -> str:
        """清理文本中的多余空白"""
        if not text:
            return ""
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _safe_category(self, soup: BeautifulSoup) -> str:
        """安全提取分类，避免匹配到大容器"""
        for selector in (
            "meta[property='article:section']",
            ".entry-category a", ".post-category a",
            ".section-name", ".breadcrumb li:last-child a",
        ):
            el = soup.select_one(selector)
            if el:
                val = el.get("content", "") if el.name == "meta" else self._clean_text(el.get_text())
                if val and len(val) < 200:
                    return val
        return ""

    def _meta(self, soup: BeautifulSoup, attr: str, value: str) -> str:
        """提取 meta 标签内容, e.g. _meta(soup, 'property', 'article:section')"""
        el = soup.select_one(f"meta[{attr}='{value}']")
        return (el.get("content", "") or "").strip() if el else ""

    def _extract_jsonld(self, soup: BeautifulSoup) -> Optional[Dict]:
        """提取 JSON-LD NewsArticle 数据"""
        import json as _json
        for script in soup.select("script[type='application/ld+json']"):
            try:
                data = _json.loads(script.string or "")
                if isinstance(data, dict) and data.get("@type") in ("NewsArticle", "Article", "ReportageNewsArticle"):
                    return data
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("@type") in ("NewsArticle", "Article"):
                            return item
            except (ValueError, TypeError):
                continue
        return None

    @abstractmethod
    def parse_article_list(self, html: str) -> List[str]:
        """从列表页 HTML 中提取文章 URL 列表"""
        ...

    @abstractmethod
    def parse_article_detail(self, html: str, url: str) -> Optional[Dict]:
        """从文章详情页 HTML 中提取结构化数据，返回 dict 或 None"""
        ...

    def parse_search_results(self, html: str) -> List[str]:
        """从搜索结果页提取文章 URL 列表，默认复用 parse_article_list"""
        return self.parse_article_list(html)
