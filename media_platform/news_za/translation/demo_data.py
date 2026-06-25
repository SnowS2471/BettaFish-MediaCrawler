# -*- coding: utf-8 -*-
"""
翻译质量评估演示数据生成器
生成可复现的合成评估数据，用于统计分析和可视化开发测试
"""

import asyncio
import hashlib
import json
import time

import numpy as np
from sqlalchemy import delete, select, func

from database.db_session import get_session
from database.models import SANewsArticle
from tools import utils

DEMO_MARKER = "__demo__"

SOURCE_SITES = ["mg", "iol", "sowetan", "news24", "sundaytimes"]
CATEGORIES = ["politics", "economy", "sports", "crime", "health", "technology", "entertainment"]
PROVIDERS = ["deepseek-v4-flash"]

# 基础评分分布参数 (mean, std)
PROVIDER_BASELINES = {
    "deepseek-v4-flash": {
        "accuracy": (7.8, 1.0),
        "fluency": (7.5, 1.2),
        "terminology": (7.0, 1.5),
        "completeness": (8.0, 0.8),
    },
}

SOURCE_MODIFIERS = {
    "news24": 0.3,
    "mg": 0.2,
    "iol": 0.0,
    "sowetan": -0.2,
    "sundaytimes": 0.1,
}

CATEGORY_MODIFIERS = {
    "sports": {"fluency": 0.5},
    "politics": {"terminology": -0.5},
    "economy": {"terminology": -0.3},
    "crime": {"accuracy": 0.3},
    "health": {"terminology": -0.2},
    "technology": {"fluency": 0.2},
    "entertainment": {"fluency": 0.3},
}

SAMPLE_TITLES = {
    "politics": [
        "South Africa's ANC faces coalition challenges ahead of 2025",
        "Parliament debates new land reform legislation",
        "Opposition parties unite against proposed electoral changes",
    ],
    "economy": [
        "Rand strengthens as inflation data beats expectations",
        "Eskom announces new load shedding schedule for winter",
        "South African Reserve Bank holds interest rates steady",
    ],
    "sports": [
        "Springboks announce squad for Rugby Championship",
        "Bafana Bafana qualify for AFCON quarter-finals",
        "Cricket South Africa unveils new domestic league format",
    ],
    "crime": [
        "Police arrest suspects in Johannesburg cash-in-transit heist",
        "Cape Town gang violence claims three lives over weekend",
        "SAPS launches operation to combat illegal mining",
    ],
    "health": [
        "South Africa rolls out new HIV prevention programme",
        "Gauteng hospitals face critical staff shortages",
        "WHO praises South Africa's TB treatment advances",
    ],
    "technology": [
        "Cape Town startup raises R500m in Series B funding",
        "MTN expands 5G coverage to rural Eastern Cape",
        "South African fintech disrupts cross-border payments",
    ],
    "entertainment": [
        "Amapiano takes global stage at Coachella festival",
        "South African film wins Best International Feature nomination",
        "Netflix announces new original series set in Soweto",
    ],
}

def _generate_scores(rng: np.random.Generator, provider: str,
                      source_site: str, category: str) -> dict:
    """根据提供商/来源/类别生成带偏移的评分"""
    baselines = PROVIDER_BASELINES[provider]
    source_mod = SOURCE_MODIFIERS.get(source_site, 0.0)
    cat_mods = CATEGORY_MODIFIERS.get(category, {})

    scores = {}
    for dim in ("accuracy", "fluency", "terminology", "completeness"):
        mean, std = baselines[dim]
        mean += source_mod + cat_mods.get(dim, 0.0)
        raw = rng.normal(mean, std)
        scores[dim] = int(np.clip(round(raw), 1, 10))

    weights = {"accuracy": 0.35, "fluency": 0.25,
               "terminology": 0.25, "completeness": 0.15}
    weighted = sum(scores[d] * w for d, w in weights.items())
    scores["overall"] = int(np.clip(round(weighted), 1, 10))
    return scores


def _generate_comment(scores: dict) -> dict:
    """根据评分生成简评"""
    templates = {
        "accuracy": {
            (1, 4): "存在较多误译和漏译",
            (5, 6): "基本忠实原文，有少量偏差",
            (7, 8): "整体忠实，个别细节有轻微偏差",
            (9, 10): "高度忠实原文，翻译准确",
        },
        "fluency": {
            (1, 4): "翻译腔明显，表达不自然",
            (5, 6): "基本通顺，部分句子有翻译腔",
            (7, 8): "表达流畅自然，偶有生硬之处",
            (9, 10): "中文表达地道流畅",
        },
        "terminology": {
            (1, 4): "术语翻译错误较多，专有名词处理不当",
            (5, 6): "部分术语翻译不够准确",
            (7, 8): "术语翻译基本准确，个别可改进",
            (9, 10): "术语和专有名词翻译准确规范",
        },
        "completeness": {
            (1, 4): "信息缺失严重，段落结构不一致",
            (5, 6): "大部分信息保留，有少量遗漏",
            (7, 8): "信息基本完整，结构一致",
            (9, 10): "信息完整保留，段落结构完全一致",
        },
    }
    comment = {}
    for dim, ranges in templates.items():
        score = scores[dim]
        for (lo, hi), text in ranges.items():
            if lo <= score <= hi:
                comment[dim] = text
                break
    return comment


async def generate_demo_data(count: int = 200, seed: int = 42) -> int:
    """生成演示评估数据，返回插入数量"""
    rng = np.random.default_rng(seed)
    base_ts = int(time.time()) - 90 * 86400  # 90天前起始

    articles = []
    for i in range(count):
        source_site = rng.choice(SOURCE_SITES)
        category = rng.choice(CATEGORIES)
        provider = rng.choice(PROVIDERS)
        day_offset = int(rng.uniform(0, 90))
        ts = base_ts + day_offset * 86400 + int(rng.uniform(0, 86400))

        titles = SAMPLE_TITLES.get(category, SAMPLE_TITLES["politics"])
        title = rng.choice(titles)
        article_id = hashlib.md5(f"demo_{i}_{seed}".encode()).hexdigest()[:16]

        scores = _generate_scores(rng, provider, source_site, category)
        comment = _generate_comment(scores)

        publish_date = time.strftime("%Y-%m-%d", time.gmtime(ts))

        articles.append({
            "article_id": f"demo_{article_id}",
            "source_site": source_site,
            "title": title,
            "content": f"[Demo content for {title}]",
            "summary": f"[Demo summary for {title}]",
            "category": category,
            "publish_time": publish_date,
            "source_keyword": DEMO_MARKER,
            "add_ts": ts,
            "last_modify_ts": ts,
            "title_zh": f"[演示翻译] {title}",
            "content_zh": f"[演示翻译内容]",
            "summary_zh": f"[演示翻译摘要]",
            "translation_status": "done",
            "translation_provider": provider,
            "translation_ts": ts + 60,
            "translation_input_tokens": int(rng.uniform(500, 3000)),
            "translation_output_tokens": int(rng.uniform(400, 2500)),
            "translation_cost": f"${rng.uniform(0.001, 0.05):.4f}",
            "translation_duration_ms": int(rng.uniform(1000, 15000)),
            "eval_accuracy": scores["accuracy"],
            "eval_fluency": scores["fluency"],
            "eval_terminology": scores["terminology"],
            "eval_completeness": scores["completeness"],
            "eval_overall": scores["overall"],
            "eval_comment": json.dumps(comment, ensure_ascii=False),
            "eval_provider": "qwen3.5-plus-2026-02-15",
            "eval_ts": ts + 120,
        })

    inserted = 0
    async with get_session() as session:
        if session is None:
            utils.logger.error("[DemoData] 无法获取数据库会话")
            return 0
        for art in articles:
            exists = await session.execute(
                select(func.count()).where(
                    SANewsArticle.article_id == art["article_id"]
                )
            )
            if exists.scalar() > 0:
                continue
            session.add(SANewsArticle(**art))
            inserted += 1

    utils.logger.info(f"[DemoData] 已插入 {inserted} 条演示数据 (seed={seed})")
    return inserted


async def clear_demo_data() -> int:
    """清除所有演示数据，返回删除数量"""
    async with get_session() as session:
        if session is None:
            return 0
        result = await session.execute(
            delete(SANewsArticle).where(
                SANewsArticle.source_keyword == DEMO_MARKER
            )
        )
        count = result.rowcount
    utils.logger.info(f"[DemoData] 已清除 {count} 条演示数据")
    return count


async def demo_data_count() -> int:
    """查询当前演示数据数量"""
    async with get_session() as session:
        if session is None:
            return 0
        result = await session.execute(
            select(func.count()).where(
                SANewsArticle.source_keyword == DEMO_MARKER
            )
        )
        return result.scalar() or 0


if __name__ == "__main__":
    asyncio.run(generate_demo_data())
