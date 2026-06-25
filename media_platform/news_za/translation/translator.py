# -*- coding: utf-8 -*-
"""
文章翻译编排器
查询待翻译文章 → 并发翻译 → 写回数据库
"""

import asyncio
from typing import List

from sqlalchemy import select, update

from database.db_session import get_session
from database.models import SANewsArticle
from tools import utils
from tools.time_util import get_current_timestamp

from .base_provider import BaseTranslationProvider
from .cost_tracker import format_cost


class ArticleTranslator:
    """文章翻译编排器"""

    def __init__(self, provider: BaseTranslationProvider, concurrency: int = 3):
        self.provider = provider
        self.semaphore = asyncio.Semaphore(concurrency)

    async def translate_pending_articles(self, batch_size: int = 50) -> int:
        """循环翻译所有待翻译的文章，每批 batch_size 篇，直到全部完成"""
        total_success = 0

        while True:
            articles = await self._fetch_pending(batch_size)
            if not articles:
                if total_success == 0:
                    utils.logger.info("[ArticleTranslator] 没有待翻译的文章")
                break

            utils.logger.info(
                f"[ArticleTranslator] 本批翻译 {len(articles)} 篇 "
                f"(provider={self.provider.provider_name()}, 已完成={total_success})"
            )

            tasks = [self._translate_one(a) for a in articles]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            success = sum(1 for r in results if r is True)
            failed = len(results) - success
            total_success += success

            utils.logger.info(
                f"[ArticleTranslator] 本批完成: 成功 {success}, 失败 {failed}"
            )

            # 如果本批全部失败，停止循环避免死循环
            if success == 0:
                utils.logger.warning("[ArticleTranslator] 本批全部失败，停止翻译")
                break

        if total_success > 0:
            utils.logger.info(f"[ArticleTranslator] 全部翻译完成，共成功 {total_success} 篇")
        return total_success

    async def _translate_one(self, article) -> bool:
        """翻译单篇文章"""
        async with self.semaphore:
            article_id = article.article_id
            title_preview = (article.title or "")[:40]
            try:
                await self._mark_status(article_id, "translating")
                result = await self.provider.translate_article(
                    title=article.title or "",
                    content=article.content or "",
                    summary=article.summary or "",
                )
                await self._save_translation(article_id, result)
                utils.logger.info(f"[ArticleTranslator] 翻译成功: {title_preview}")
                return True
            except Exception as e:
                utils.logger.error(
                    f"[ArticleTranslator] 翻译失败: {title_preview} - {e}"
                )
                await self._mark_status(article_id, "failed")
                return False

    async def _fetch_pending(self, limit: int) -> List:
        """查询待翻译文章（pending 或 failed）"""
        async with get_session() as session:
            if session is None:
                return []
            stmt = (
                select(SANewsArticle)
                .where(SANewsArticle.translation_status.in_(["pending", "failed", None]))
                .order_by(SANewsArticle.add_ts.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            # 将 ORM 对象的关键字段提取出来，避免 session 关闭后无法访问
            return [_ArticleSnapshot(r) for r in rows]

    async def _mark_status(self, article_id: str, status: str):
        """更新翻译状态"""
        async with get_session() as session:
            if session is None:
                return
            stmt = (
                update(SANewsArticle)
                .where(SANewsArticle.article_id == article_id)
                .values(translation_status=status)
            )
            await session.execute(stmt)

    async def _save_translation(self, article_id: str, result):
        """保存翻译结果"""
        ts = int(get_current_timestamp())
        async with get_session() as session:
            if session is None:
                return
            stmt = (
                update(SANewsArticle)
                .where(SANewsArticle.article_id == article_id)
                .values(
                    title_zh=result.title_zh,
                    content_zh=result.content_zh,
                    summary_zh=result.summary_zh,
                    translation_status="done",
                    translation_provider=result.provider,
                    translation_ts=ts,
                    translation_input_tokens=result.input_tokens,
                    translation_output_tokens=result.output_tokens,
                    translation_cost=format_cost(result.estimated_cost_usd),
                    translation_duration_ms=result.duration_ms,
                )
            )
            await session.execute(stmt)


class _ArticleSnapshot:
    """轻量快照，避免 session 关闭后 ORM 延迟加载问题"""
    __slots__ = ("article_id", "title", "content", "summary")

    def __init__(self, orm_obj):
        self.article_id = orm_obj.article_id
        self.title = orm_obj.title or ""
        self.content = orm_obj.content or ""
        self.summary = orm_obj.summary or ""


async def run_translation(limit: int = None):
    """独立运行翻译任务的入口函数"""
    import config
    from .provider_factory import create_translation_provider

    provider = create_translation_provider()
    concurrency = getattr(config, "SA_NEWS_TRANSLATION_CONCURRENCY", 3)
    batch_size = limit or getattr(config, "SA_NEWS_TRANSLATION_BATCH_SIZE", 50)

    translator = ArticleTranslator(provider=provider, concurrency=concurrency)
    return await translator.translate_pending_articles(batch_size=batch_size)


if __name__ == "__main__":
    asyncio.run(run_translation())
