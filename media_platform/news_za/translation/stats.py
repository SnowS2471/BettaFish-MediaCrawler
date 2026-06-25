# -*- coding: utf-8 -*-
"""
翻译质量统计计算引擎
查询已评估文章 → 聚合统计 → 输出结构化结果
"""

from typing import Optional

import numpy as np
import pandas as pd
from dateutil import parser as dateparser
from sqlalchemy import select

from database.db_session import get_session
from database.models import SANewsArticle
from tools import utils

DIMENSIONS = ["accuracy", "fluency", "terminology", "completeness", "overall"]
DIM_LABELS = {
    "accuracy": "忠实度",
    "fluency": "流畅度",
    "terminology": "术语准确性",
    "completeness": "完整性",
    "overall": "综合",
}


class TranslationQualityStats:
    """翻译质量统计计算引擎"""

    async def _fetch_evaluated(self) -> pd.DataFrame:
        """查询所有已评估文章，返回 DataFrame"""
        async with get_session() as session:
            if session is None:
                return pd.DataFrame()
            stmt = (
                select(
                    SANewsArticle.article_id,
                    SANewsArticle.source_site,
                    SANewsArticle.category,
                    SANewsArticle.publish_time,
                    SANewsArticle.title,
                    SANewsArticle.translation_provider,
                    SANewsArticle.eval_accuracy,
                    SANewsArticle.eval_fluency,
                    SANewsArticle.eval_terminology,
                    SANewsArticle.eval_completeness,
                    SANewsArticle.eval_overall,
                    SANewsArticle.eval_comment,
                    SANewsArticle.eval_provider,
                    SANewsArticle.eval_ts,
                    SANewsArticle.translation_duration_ms,
                    SANewsArticle.translation_cost,
                    SANewsArticle.source_keyword,
                )
                .where(SANewsArticle.eval_ts.isnot(None))
            )
            result = await session.execute(stmt)
            rows = result.all()

        if not rows:
            return pd.DataFrame()

        columns = [
            "article_id", "source_site", "category", "publish_time",
            "title", "translation_provider",
            "eval_accuracy", "eval_fluency", "eval_terminology",
            "eval_completeness", "eval_overall", "eval_comment",
            "eval_provider", "eval_ts", "translation_duration_ms",
            "translation_cost", "source_keyword",
        ]
        df = pd.DataFrame([dict(zip(columns, r)) for r in rows])

        for dim in DIMENSIONS:
            col = f"eval_{dim}"
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

        df["date"] = df["publish_time"].apply(self._parse_date)
        return df

    @staticmethod
    def _parse_date(val) -> Optional[str]:
        if not val:
            return None
        try:
            return dateparser.parse(str(val)).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return None

    async def summary_stats(self) -> dict:
        """全局统计：各维度 mean/std/min/max/median + 评分分布"""
        df = await self._fetch_evaluated()
        if df.empty:
            return {"total": 0, "dimensions": {}, "distributions": {}}

        result = {"total": len(df), "dimensions": {}, "distributions": {}}
        for dim in DIMENSIONS:
            col = f"eval_{dim}"
            vals = df[col].values
            result["dimensions"][dim] = {
                "label": DIM_LABELS[dim],
                "mean": round(float(np.mean(vals)), 2),
                "std": round(float(np.std(vals)), 2),
                "min": int(np.min(vals)),
                "max": int(np.max(vals)),
                "median": round(float(np.median(vals)), 1),
                "count": len(vals),
            }
            hist, _ = np.histogram(vals, bins=np.arange(0.5, 11.5, 1))
            result["distributions"][dim] = {
                "scores": list(range(1, 11)),
                "counts": hist.tolist(),
            }
        return result

    async def stats_by_source_site(self) -> dict:
        """按新闻来源分组统计"""
        df = await self._fetch_evaluated()
        if df.empty:
            return {}
        return self._group_stats(df, "source_site")

    async def stats_by_category(self) -> dict:
        """按新闻类别分组统计"""
        df = await self._fetch_evaluated()
        if df.empty:
            return {}
        df_valid = df[df["category"].notna() & (df["category"] != "")]
        return self._group_stats(df_valid, "category")

    async def stats_by_provider(self) -> dict:
        """按翻译提供商分组统计"""
        df = await self._fetch_evaluated()
        if df.empty:
            return {}
        return self._group_stats(df, "translation_provider")

    async def stats_by_date(self, granularity: str = "day") -> list:
        """按日期聚合的时间序列数据"""
        df = await self._fetch_evaluated()
        if df.empty:
            return []

        df_dated = df[df["date"].notna()].copy()
        if df_dated.empty:
            return []

        df_dated["date_key"] = pd.to_datetime(df_dated["date"])
        if granularity == "week":
            df_dated["date_key"] = df_dated["date_key"].dt.to_period("W").dt.start_time
        elif granularity == "month":
            df_dated["date_key"] = df_dated["date_key"].dt.to_period("M").dt.start_time

        result = []
        for date_key, group in df_dated.groupby("date_key"):
            entry = {"date": str(date_key.date()), "count": len(group)}
            for dim in DIMENSIONS:
                col = f"eval_{dim}"
                entry[f"mean_{dim}"] = round(float(group[col].mean()), 2)
            result.append(entry)

        result.sort(key=lambda x: x["date"])
        return result

    async def quality_distribution(self) -> dict:
        """各维度评分分布 + 百分位数"""
        df = await self._fetch_evaluated()
        if df.empty:
            return {}

        result = {}
        for dim in DIMENSIONS:
            col = f"eval_{dim}"
            vals = df[col].values
            hist, _ = np.histogram(vals, bins=np.arange(0.5, 11.5, 1))
            result[dim] = {
                "label": DIM_LABELS[dim],
                "distribution": {
                    "scores": list(range(1, 11)),
                    "counts": hist.tolist(),
                },
                "percentiles": {
                    "p25": round(float(np.percentile(vals, 25)), 1),
                    "p50": round(float(np.percentile(vals, 50)), 1),
                    "p75": round(float(np.percentile(vals, 75)), 1),
                    "p90": round(float(np.percentile(vals, 90)), 1),
                },
            }
        return result

    async def flag_low_quality(self, threshold: float = 5.0) -> list:
        """标记低质量翻译，返回文章列表及标记原因"""
        df = await self._fetch_evaluated()
        if df.empty:
            return []

        flagged = []
        dim_threshold = threshold - 1.0

        for _, row in df.iterrows():
            reasons = []
            if row["eval_overall"] < threshold:
                reasons.append(f"综合评分 {row['eval_overall']} < {threshold}")
            for dim in ["accuracy", "fluency", "terminology", "completeness"]:
                col = f"eval_{dim}"
                if row[col] < dim_threshold:
                    reasons.append(
                        f"{DIM_LABELS[dim]} {row[col]} < {dim_threshold}"
                    )
            if reasons:
                flagged.append({
                    "article_id": row["article_id"],
                    "title": row["title"],
                    "source_site": row["source_site"],
                    "category": row["category"],
                    "eval_overall": int(row["eval_overall"]),
                    "eval_accuracy": int(row["eval_accuracy"]),
                    "eval_fluency": int(row["eval_fluency"]),
                    "eval_terminology": int(row["eval_terminology"]),
                    "eval_completeness": int(row["eval_completeness"]),
                    "translation_provider": row["translation_provider"],
                    "flag_reasons": reasons,
                })
        return flagged

    async def correlation_analysis(self) -> dict:
        """维度间 Pearson 相关系数矩阵"""
        df = await self._fetch_evaluated()
        if df.empty or len(df) < 3:
            return {}

        cols = [f"eval_{d}" for d in DIMENSIONS]
        matrix = df[cols].corr().values
        labels = [DIM_LABELS[d] for d in DIMENSIONS]

        return {
            "labels": labels,
            "dimensions": DIMENSIONS,
            "matrix": [[round(float(v), 3) for v in row] for row in matrix],
        }

    async def fetch_all_evaluated(self) -> list:
        """原始数据导出"""
        df = await self._fetch_evaluated()
        if df.empty:
            return []
        export_cols = [
            "article_id", "source_site", "category", "date", "title",
            "translation_provider", "eval_accuracy", "eval_fluency",
            "eval_terminology", "eval_completeness", "eval_overall",
            "eval_provider",
        ]
        return df[export_cols].to_dict(orient="records")

    def _group_stats(self, df: pd.DataFrame, group_col: str) -> dict:
        """通用分组统计"""
        result = {}
        for group_val, group_df in df.groupby(group_col):
            if not group_val:
                continue
            entry = {"count": len(group_df)}
            for dim in DIMENSIONS:
                col = f"eval_{dim}"
                vals = group_df[col].values
                entry[dim] = {
                    "label": DIM_LABELS[dim],
                    "mean": round(float(np.mean(vals)), 2),
                    "std": round(float(np.std(vals)), 2),
                }
            result[str(group_val)] = entry
        return result
