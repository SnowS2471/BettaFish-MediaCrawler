# -*- coding: utf-8 -*-
"""
翻译质量评估编排器
查询已翻译文章 → 并发评估 → 写回数据库
"""

import asyncio
import json
from typing import List

import config
from sqlalchemy import select, update

from database.db_session import get_session
from database.models import SANewsArticle
from tools import utils
from tools.time_util import get_current_timestamp

from .eval_provider import EvalProvider, EvalResult


class ArticleEvaluator:
    """翻译质量评估编排器"""

    def __init__(self, eval_provider: EvalProvider, concurrency: int = 3):
        self.eval_provider = eval_provider
        self.semaphore = asyncio.Semaphore(concurrency)

    async def evaluate_translated_articles(self, limit: int = 50) -> int:
        """评估所有已翻译但未评估的文章，返回成功数"""
        articles = await self._fetch_unevaluated(limit)
        if not articles:
            utils.logger.info("[ArticleEvaluator] 没有待评估的文章")
            return 0

        utils.logger.info(
            f"[ArticleEvaluator] 开始评估 {len(articles)} 篇文章 "
            f"(evaluator={self.eval_provider.model})"
        )

        tasks = [self._evaluate_one(a) for a in articles]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        success = sum(1 for r in results if r is True)
        failed = len(results) - success
        utils.logger.info(
            f"[ArticleEvaluator] 评估完成: 成功 {success}, 失败 {failed}"
        )

        if success > 0:
            low_count = await self._count_low_quality_batch(
                [a.article_id for a in articles]
            )
            if low_count > 0:
                utils.logger.warning(
                    f"[ArticleEvaluator] 本批检测到 {low_count} 篇低质量翻译"
                )

        return success

    async def _evaluate_one(self, article) -> bool:
        """评估单篇文章"""
        async with self.semaphore:
            title_preview = (article.title or "")[:40]
            try:
                original = f"Title: {article.title}\n\n{article.content}"
                translated = f"标题: {article.title_zh}\n\n{article.content_zh}"
                result = await self.eval_provider.evaluate(original, translated)
                await self._save_eval(article.article_id, result)

                threshold = getattr(config, "SA_NEWS_EVAL_LOW_QUALITY_THRESHOLD", 5.0)
                flag = "LOW" if result.overall < threshold else "OK"
                utils.logger.info(
                    f"[ArticleEvaluator] 评估完成: {title_preview} "
                    f"(overall={result.overall}, quality={flag})"
                )
                return True
            except Exception as e:
                utils.logger.error(
                    f"[ArticleEvaluator] 评估失败: {title_preview} - {e}"
                )
                return False

    async def _fetch_unevaluated(self, limit: int) -> List:
        """查询已翻译但未评估的文章"""
        async with get_session() as session:
            if session is None:
                return []
            stmt = (
                select(SANewsArticle)
                .where(
                    SANewsArticle.translation_status == "done",
                    SANewsArticle.eval_ts.is_(None),
                )
                .order_by(SANewsArticle.translation_ts.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [_EvalSnapshot(r) for r in rows]

    async def _count_low_quality_batch(self, article_ids: List[str]) -> int:
        """统计本批中被标记为低质量的文章数"""
        from sqlalchemy import func
        async with get_session() as session:
            if session is None:
                return 0
            stmt = (
                select(func.count())
                .where(
                    SANewsArticle.article_id.in_(article_ids),
                    SANewsArticle.quality_flag == "low_quality",
                )
            )
            result = await session.execute(stmt)
            return result.scalar() or 0

    async def _save_eval(self, article_id: str, result: EvalResult):
        """保存评估结果并自动标注质量"""
        ts = int(get_current_timestamp())
        threshold = getattr(config, "SA_NEWS_EVAL_LOW_QUALITY_THRESHOLD", 5.0)
        dim_threshold = threshold - 1.0

        is_low = (
            result.overall < threshold
            or result.accuracy < dim_threshold
            or result.fluency < dim_threshold
            or result.terminology < dim_threshold
            or result.completeness < dim_threshold
        )
        flag = "low_quality" if is_low else "good"

        async with get_session() as session:
            if session is None:
                return
            stmt = (
                update(SANewsArticle)
                .where(SANewsArticle.article_id == article_id)
                .values(
                    eval_accuracy=result.accuracy,
                    eval_fluency=result.fluency,
                    eval_terminology=result.terminology,
                    eval_completeness=result.completeness,
                    eval_overall=result.overall,
                    eval_comment=json.dumps(result.comment, ensure_ascii=False),
                    eval_provider=result.eval_provider,
                    eval_ts=ts,
                    quality_flag=flag,
                )
            )
            await session.execute(stmt)


class _EvalSnapshot:
    """评估用轻量快照"""
    __slots__ = ("article_id", "title", "content", "title_zh", "content_zh")

    def __init__(self, orm_obj):
        self.article_id = orm_obj.article_id
        self.title = orm_obj.title or ""
        self.content = orm_obj.content or ""
        self.title_zh = orm_obj.title_zh or ""
        self.content_zh = orm_obj.content_zh or ""


async def run_evaluation(limit: int = None):
    """独立运行评估任务的入口函数"""
    import config

    provider = EvalProvider(
        api_key=getattr(config, "SA_NEWS_EVAL_API_KEY", ""),
        base_url=getattr(config, "SA_NEWS_EVAL_BASE_URL", ""),
        model_name=getattr(config, "SA_NEWS_EVAL_MODEL_NAME", "qwen3.6-plus"),
    )
    concurrency = getattr(config, "SA_NEWS_EVAL_CONCURRENCY", 3)
    batch_size = limit or getattr(config, "SA_NEWS_EVAL_BATCH_SIZE", 50)

    evaluator = ArticleEvaluator(eval_provider=provider, concurrency=concurrency)
    return await evaluator.evaluate_translated_articles(limit=batch_size)


if __name__ == "__main__":
    asyncio.run(run_evaluation())