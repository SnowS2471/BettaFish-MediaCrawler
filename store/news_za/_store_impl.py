# -*- coding: utf-8 -*-
"""
南非新闻存储实现类
"""

import json
from typing import Dict

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from base.base_crawler import AbstractStore
from database.db_session import get_session
from database.models import SANewsArticle
from tools.async_file_writer import AsyncFileWriter
from tools.time_util import get_current_timestamp
from var import crawler_type_var


class SANewsCsvStoreImplement(AbstractStore):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.writer = AsyncFileWriter(platform="news_za", crawler_type=crawler_type_var.get())

    async def store_content(self, content_item: Dict):
        await self.writer.write_to_csv(item_type="articles", item=content_item)

    async def store_comment(self, comment_item: Dict):
        pass  # 新闻站点不爬取评论

    async def store_creator(self, creator: Dict):
        pass  # 新闻站点不爬取创作者


class SANewsJsonStoreImplement(AbstractStore):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.writer = AsyncFileWriter(platform="news_za", crawler_type=crawler_type_var.get())

    async def store_content(self, content_item: Dict):
        await self.writer.write_single_item_to_json(item_type="articles", item=content_item)

    async def store_comment(self, comment_item: Dict):
        pass

    async def store_creator(self, creator: Dict):
        pass


class SANewsDbStoreImplement(AbstractStore):
    """南非新闻数据库存储（MySQL / PostgreSQL）"""

    async def store_content(self, content_item: Dict):
        article_id = content_item.get("article_id")
        if not article_id:
            return
        async with get_session() as session:
            if await self._article_exists(session, article_id):
                await self._update_article(session, content_item)
            else:
                await self._add_article(session, content_item)

    async def _add_article(self, session: AsyncSession, item: Dict):
        ts = int(get_current_timestamp())
        article = SANewsArticle(
            article_id=item.get("article_id"),
            source_site=item.get("source_site", ""),
            title=item.get("title", ""),
            content=item.get("content", ""),
            summary=item.get("summary", ""),
            author=item.get("author", ""),
            publish_time=item.get("publish_time", ""),
            article_url=item.get("article_url", ""),
            image_urls=item.get("image_urls", "[]"),
            category=item.get("category", ""),
            tags=item.get("tags", "[]"),
            source_keyword=item.get("source_keyword", ""),
            add_ts=ts,
            last_modify_ts=ts,
        )
        session.add(article)

    async def _update_article(self, session: AsyncSession, item: Dict):
        ts = int(get_current_timestamp())
        update_data = {
            "last_modify_ts": ts,
            "title": item.get("title", ""),
            "content": item.get("content", ""),
            "summary": item.get("summary", ""),
            "author": item.get("author", ""),
        }
        stmt = update(SANewsArticle).where(
            SANewsArticle.article_id == item.get("article_id")
        ).values(**update_data)
        await session.execute(stmt)

    async def _article_exists(self, session: AsyncSession, article_id: str) -> bool:
        stmt = select(SANewsArticle).where(SANewsArticle.article_id == article_id)
        result = await session.execute(stmt)
        return result.first() is not None

    async def store_comment(self, comment_item: Dict):
        pass

    async def store_creator(self, creator: Dict):
        pass


class SANewsSqliteStoreImplement(SANewsDbStoreImplement):
    pass
