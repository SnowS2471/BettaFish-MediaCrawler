# -*- coding: utf-8 -*-
"""
翻译质量统计分析 CLI 入口
用法: python -m media_platform.news_za.translation.run_stats [选项]
"""

import argparse
import asyncio
import json
import os

import pandas as pd
from tools import utils

from .demo_data import generate_demo_data, clear_demo_data, demo_data_count
from .stats import TranslationQualityStats, DIM_LABELS, DIMENSIONS
from .visualizer import QualityVisualizer


async def run_stats_pipeline(
    output_dir: str = "./output/translation_stats",
    low_quality_threshold: float = 5.0,
    export_csv: bool = True,
    export_json: bool = True,
    generate_charts: bool = True,
    demo_mode: bool = False,
    demo_count: int = 200,
):
    os.makedirs(output_dir, exist_ok=True)
    stats = TranslationQualityStats()

    if demo_mode:
        existing = await demo_data_count()
        if existing > 0:
            utils.logger.info(f"[Stats] 已有 {existing} 条演示数据，跳过生成")
        else:
            await generate_demo_data(count=demo_count)

    utils.logger.info("[Stats] 开始计算统计数据...")

    summary = await stats.summary_stats()
    if summary.get("total", 0) == 0:
        utils.logger.warning("[Stats] 没有已评估的文章数据。使用 --demo 生成演示数据")
        return

    by_source = await stats.stats_by_source_site()
    by_category = await stats.stats_by_category()
    by_provider = await stats.stats_by_provider()
    trend = await stats.stats_by_date(granularity="day")
    distribution = await stats.quality_distribution()
    correlation = await stats.correlation_analysis()
    flagged = await stats.flag_low_quality(threshold=low_quality_threshold)
    raw_data = await stats.fetch_all_evaluated()

    _print_summary(summary, flagged, low_quality_threshold)

    if export_csv:
        _export_csv(output_dir, summary, by_source, by_category,
                    trend, flagged, raw_data)
        utils.logger.info(f"[Stats] CSV 已导出到 {output_dir}")

    if export_json:
        all_stats = {
            "summary": summary,
            "by_source": by_source,
            "by_category": by_category,
            "by_provider": by_provider,
            "trend": trend,
            "distribution": distribution,
            "correlation": correlation,
            "low_quality_count": len(flagged),
            "low_quality_threshold": low_quality_threshold,
        }
        json_path = os.path.join(output_dir, "all_stats.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(all_stats, f, ensure_ascii=False, indent=2)
        utils.logger.info(f"[Stats] JSON 已导出到 {json_path}")

    if generate_charts:
        viz = QualityVisualizer(output_dir=output_dir)
        paths = viz.generate_all_charts(
            summary=summary,
            distribution=distribution,
            by_source=by_source,
            trend=trend,
            by_provider=by_provider,
            correlation=correlation,
            flagged=flagged,
        )
        utils.logger.info(f"[Stats] 已生成 {len(paths)} 张图表:")
        for p in paths:
            utils.logger.info(f"  - {p}")

def _print_summary(summary: dict, flagged: list, threshold: float):
    """打印统计摘要到控制台"""
    total = summary.get("total", 0)
    dims = summary.get("dimensions", {})

    lines = [
        f"\n{'='*60}",
        f"  翻译质量统计报告 ({total} 篇已评估文章)",
        f"{'='*60}",
        "",
        f"  {'维度':<12} {'均值':>6} {'标准差':>6} {'中位数':>6} {'最低':>4} {'最高':>4}",
        f"  {'-'*46}",
    ]
    for dim in DIMENSIONS:
        d = dims.get(dim, {})
        lines.append(
            f"  {d.get('label', dim):<12} "
            f"{d.get('mean', 0):>6.2f} "
            f"{d.get('std', 0):>6.2f} "
            f"{d.get('median', 0):>6.1f} "
            f"{d.get('min', 0):>4} "
            f"{d.get('max', 0):>4}"
        )
    lines.extend([
        "",
        f"  低质量翻译 (阈值={threshold}): {len(flagged)} 篇",
        f"{'='*60}",
    ])
    utils.logger.info("\n".join(lines))


def _export_csv(output_dir, summary, by_source, by_category,
                trend, flagged, raw_data):
    """导出 CSV 文件"""
    dims = summary.get("dimensions", {})
    rows = []
    for dim in DIMENSIONS:
        d = dims.get(dim, {})
        rows.append({
            "维度": d.get("label", dim),
            "均值": d.get("mean"),
            "标准差": d.get("std"),
            "中位数": d.get("median"),
            "最小值": d.get("min"),
            "最大值": d.get("max"),
            "样本数": d.get("count"),
        })
    pd.DataFrame(rows).to_csv(
        os.path.join(output_dir, "summary_stats.csv"),
        index=False, encoding="utf-8-sig")

    _group_to_csv(by_source, os.path.join(output_dir, "stats_by_source.csv"),
                  "来源")
    _group_to_csv(by_category, os.path.join(output_dir, "stats_by_category.csv"),
                  "类别")

    if trend:
        pd.DataFrame(trend).to_csv(
            os.path.join(output_dir, "stats_by_date.csv"),
            index=False, encoding="utf-8-sig")

    if flagged:
        pd.DataFrame(flagged).to_csv(
            os.path.join(output_dir, "low_quality_articles.csv"),
            index=False, encoding="utf-8-sig")

    if raw_data:
        pd.DataFrame(raw_data).to_csv(
            os.path.join(output_dir, "raw_eval_data.csv"),
            index=False, encoding="utf-8-sig")


def _group_to_csv(group_data: dict, path: str, group_label: str):
    """将分组统计数据导出为 CSV"""
    if not group_data:
        return
    rows = []
    for group_name, data in group_data.items():
        row = {group_label: group_name, "样本数": data.get("count", 0)}
        for dim in DIMENSIONS:
            d = data.get(dim, {})
            row[f"{DIM_LABELS.get(dim, dim)}_均值"] = d.get("mean")
            row[f"{DIM_LABELS.get(dim, dim)}_标准差"] = d.get("std")
        rows.append(row)
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def main():
    parser = argparse.ArgumentParser(
        description="翻译质量统计分析工具"
    )
    parser.add_argument("--demo", action="store_true",
                        help="生成演示数据后再统计")
    parser.add_argument("--demo-count", type=int, default=200,
                        help="演示数据数量 (默认 200)")
    parser.add_argument("--clean-demo", action="store_true",
                        help="清除演示数据后退出")
    parser.add_argument("--charts", action="store_true", default=True,
                        help="生成图表 (默认开启)")
    parser.add_argument("--no-charts", action="store_true",
                        help="不生成图表")
    parser.add_argument("--csv", action="store_true", default=True,
                        help="导出 CSV (默认开启)")
    parser.add_argument("--json", action="store_true", default=True,
                        help="导出 JSON (默认开启)")
    parser.add_argument("--output", type=str,
                        default="./output/translation_stats",
                        help="输出目录")
    parser.add_argument("--threshold", type=float, default=5.0,
                        help="低质量阈值 (默认 5.0)")
    args = parser.parse_args()

    if args.clean_demo:
        asyncio.run(clear_demo_data())
        return

    asyncio.run(run_stats_pipeline(
        output_dir=args.output,
        low_quality_threshold=args.threshold,
        export_csv=args.csv,
        export_json=args.json,
        generate_charts=args.charts and not args.no_charts,
        demo_mode=args.demo,
        demo_count=args.demo_count,
    ))


if __name__ == "__main__":
    main()
