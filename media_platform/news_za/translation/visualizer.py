# -*- coding: utf-8 -*-
"""
翻译质量可视化图表生成器
生成论文级 matplotlib 图表（300 DPI PNG）
"""

import os
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np

from .stats import DIMENSIONS, DIM_LABELS

_FONT_CANDIDATES = [
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "..", "docs", "STZHONGS.TTF"),
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/msyh.ttc",
]

COLORS = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3",
           "#937860", "#DA8BC3", "#8C8C8C", "#CCB974", "#64B5CD"]


def _get_font_prop() -> Optional[fm.FontProperties]:
    for path in _FONT_CANDIDATES:
        resolved = os.path.abspath(path)
        if os.path.isfile(resolved):
            return fm.FontProperties(fname=resolved)
    return None


def _setup_style(font_prop):
    plt.style.use("seaborn-v0_8-whitegrid")
    if font_prop:
        plt.rcParams["font.family"] = font_prop.get_name()
        plt.rcParams["axes.unicode_minus"] = False


class QualityVisualizer:
    """翻译质量图表生成器"""

    def __init__(self, output_dir: str = "./output/translation_stats",
                 dpi: int = 300, font_path: str = ""):
        self.output_dir = output_dir
        self.dpi = dpi
        os.makedirs(output_dir, exist_ok=True)

        if font_path and os.path.isfile(font_path):
            self.font_prop = fm.FontProperties(fname=font_path)
        else:
            self.font_prop = _get_font_prop()
        _setup_style(self.font_prop)

    def _save(self, fig, name: str) -> str:
        path = os.path.join(self.output_dir, name)
        fig.savefig(path, dpi=self.dpi, bbox_inches="tight",
                    facecolor="white", edgecolor="none")
        plt.close(fig)
        return path

    def _text(self, ax, *args, **kwargs):
        if self.font_prop:
            kwargs["fontproperties"] = self.font_prop
        return ax.set_title(*args, **kwargs) if "title" in str(args) else None

    def plot_dimension_radar(self, summary_data: dict,
                             by_group: dict = None) -> str:
        """雷达图：各维度均分对比"""
        dims = [d for d in DIMENSIONS if d != "overall"]
        labels = [DIM_LABELS[d] for d in dims]
        angles = np.linspace(0, 2 * np.pi, len(dims), endpoint=False).tolist()
        angles += angles[:1]

        fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))

        if by_group:
            for i, (group_name, group_data) in enumerate(by_group.items()):
                values = [group_data.get(d, {}).get("mean", 0) for d in dims]
                values += values[:1]
                ax.plot(angles, values, "o-", linewidth=2,
                        color=COLORS[i % len(COLORS)], label=group_name)
                ax.fill(angles, values, alpha=0.1, color=COLORS[i % len(COLORS)])
            ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1),
                      prop=self.font_prop)
        else:
            dim_data = summary_data.get("dimensions", {})
            values = [dim_data.get(d, {}).get("mean", 0) for d in dims]
            values += values[:1]
            ax.plot(angles, values, "o-", linewidth=2, color=COLORS[0])
            ax.fill(angles, values, alpha=0.25, color=COLORS[0])

        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(labels, fontproperties=self.font_prop)
        ax.set_ylim(0, 10)
        ax.set_yticks([2, 4, 6, 8, 10])
        ax.set_title("翻译质量各维度评分", pad=20,
                      fontproperties=self.font_prop, fontsize=14)
        return self._save(fig, "fig_radar_overall.png")

    def plot_score_distribution(self, dist_data: dict) -> str:
        """直方图：各维度评分分布"""
        dims = [d for d in DIMENSIONS if d != "overall"]
        fig, axes = plt.subplots(2, 2, figsize=(12, 10))
        axes = axes.flatten()

        for i, dim in enumerate(dims):
            ax = axes[i]
            data = dist_data.get(dim, {})
            dist = data.get("distribution", {})
            scores = dist.get("scores", list(range(1, 11)))
            counts = dist.get("counts", [0] * 10)

            ax.bar(scores, counts, color=COLORS[i], alpha=0.8, edgecolor="white")
            ax.set_xlabel("评分", fontproperties=self.font_prop)
            ax.set_ylabel("文章数", fontproperties=self.font_prop)
            ax.set_title(DIM_LABELS[dim], fontproperties=self.font_prop,
                         fontsize=12)
            ax.set_xticks(range(1, 11))
            ax.set_xlim(0.5, 10.5)

        fig.suptitle("翻译质量评分分布", fontsize=14,
                     fontproperties=self.font_prop)
        fig.tight_layout(rect=[0, 0, 1, 0.96])
        return self._save(fig, "fig_distribution.png")

    def plot_quality_by_source(self, source_data: dict) -> str:
        """分组柱状图：各来源质量对比"""
        if not source_data:
            return ""

        sites = list(source_data.keys())
        dims = [d for d in DIMENSIONS if d != "overall"]
        x = np.arange(len(sites))
        width = 0.18

        fig, ax = plt.subplots(figsize=(12, 6))
        for i, dim in enumerate(dims):
            means = [source_data[s].get(dim, {}).get("mean", 0) for s in sites]
            stds = [source_data[s].get(dim, {}).get("std", 0) for s in sites]
            ax.bar(x + i * width, means, width, yerr=stds,
                   label=DIM_LABELS[dim], color=COLORS[i],
                   capsize=3, alpha=0.85)

        ax.set_xlabel("新闻来源", fontproperties=self.font_prop)
        ax.set_ylabel("平均评分", fontproperties=self.font_prop)
        ax.set_title("各新闻来源翻译质量对比", fontproperties=self.font_prop,
                     fontsize=14)
        ax.set_xticks(x + width * 1.5)
        ax.set_xticklabels(sites)
        ax.set_ylim(0, 10)
        ax.legend(prop=self.font_prop)
        return self._save(fig, "fig_quality_by_source.png")

    def plot_quality_trend(self, trend_data: list) -> str:
        """折线图：质量随时间变化趋势"""
        if not trend_data:
            return ""

        dates = [d["date"] for d in trend_data]
        fig, ax = plt.subplots(figsize=(14, 6))

        for i, dim in enumerate(DIMENSIONS):
            values = [d.get(f"mean_{dim}", 0) for d in trend_data]
            style = "-" if dim == "overall" else "--"
            lw = 2.5 if dim == "overall" else 1.5
            ax.plot(dates, values, style, linewidth=lw,
                    color=COLORS[i], label=DIM_LABELS[dim], marker="o",
                    markersize=4 if dim != "overall" else 6)

        ax.set_xlabel("日期", fontproperties=self.font_prop)
        ax.set_ylabel("平均评分", fontproperties=self.font_prop)
        ax.set_title("翻译质量时间趋势", fontproperties=self.font_prop,
                     fontsize=14)
        ax.set_ylim(0, 10)
        ax.legend(prop=self.font_prop)

        step = max(1, len(dates) // 15)
        ax.set_xticks(range(0, len(dates), step))
        ax.set_xticklabels([dates[i] for i in range(0, len(dates), step)],
                           rotation=45, ha="right")
        return self._save(fig, "fig_quality_trend.png")

    def plot_provider_comparison(self, provider_data: dict) -> str:
        """柱状图：翻译提供商对比"""
        if not provider_data or len(provider_data) < 2:
            return ""

        providers = list(provider_data.keys())
        dims = [d for d in DIMENSIONS if d != "overall"]
        x = np.arange(len(dims))
        width = 0.8 / len(providers)

        fig, ax = plt.subplots(figsize=(10, 6))
        for i, prov in enumerate(providers):
            means = [provider_data[prov].get(d, {}).get("mean", 0) for d in dims]
            stds = [provider_data[prov].get(d, {}).get("std", 0) for d in dims]
            ax.bar(x + i * width, means, width, yerr=stds,
                   label=prov, color=COLORS[i], capsize=3, alpha=0.85)

        ax.set_xlabel("评价维度", fontproperties=self.font_prop)
        ax.set_ylabel("平均评分", fontproperties=self.font_prop)
        ax.set_title("翻译提供商质量对比", fontproperties=self.font_prop,
                     fontsize=14)
        ax.set_xticks(x + width * (len(providers) - 1) / 2)
        ax.set_xticklabels([DIM_LABELS[d] for d in dims],
                           fontproperties=self.font_prop)
        ax.set_ylim(0, 10)
        ax.legend(prop=self.font_prop)
        return self._save(fig, "fig_provider_comparison.png")

    def plot_correlation_heatmap(self, corr_data: dict) -> str:
        """热力图：维度相关性矩阵"""
        if not corr_data:
            return ""

        matrix = np.array(corr_data["matrix"])
        labels = corr_data["labels"]

        fig, ax = plt.subplots(figsize=(8, 7))
        im = ax.imshow(matrix, cmap="RdYlBu_r", vmin=-1, vmax=1)

        ax.set_xticks(range(len(labels)))
        ax.set_yticks(range(len(labels)))
        ax.set_xticklabels(labels, fontproperties=self.font_prop, rotation=45,
                           ha="right")
        ax.set_yticklabels(labels, fontproperties=self.font_prop)

        for i in range(len(labels)):
            for j in range(len(labels)):
                color = "white" if abs(matrix[i, j]) > 0.6 else "black"
                ax.text(j, i, f"{matrix[i, j]:.2f}", ha="center",
                        va="center", color=color, fontsize=10)

        fig.colorbar(im, ax=ax, shrink=0.8)
        ax.set_title("评价维度相关性矩阵", fontproperties=self.font_prop,
                     fontsize=14)
        return self._save(fig, "fig_correlation_heatmap.png")

    def plot_low_quality_summary(self, flagged: list,
                                 source_data: dict = None) -> str:
        """低质量翻译分布图"""
        if not flagged:
            return ""

        site_counts = {}
        for item in flagged:
            site = item.get("source_site", "unknown")
            site_counts[site] = site_counts.get(site, 0) + 1

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

        sites = list(site_counts.keys())
        counts = [site_counts[s] for s in sites]
        ax1.barh(sites, counts, color=COLORS[3], alpha=0.85)
        ax1.set_xlabel("低质量文章数", fontproperties=self.font_prop)
        ax1.set_title("各来源低质量翻译数量", fontproperties=self.font_prop,
                      fontsize=12)

        total = len(flagged)
        if source_data:
            total_all = sum(v.get("count", 0) for v in source_data.values())
        else:
            total_all = total * 3
        good = max(0, total_all - total)
        ax2.pie([good, total],
                labels=["合格", "低质量"],
                colors=[COLORS[2], COLORS[3]],
                autopct="%1.1f%%", startangle=90,
                textprops={"fontproperties": self.font_prop})
        ax2.set_title("翻译质量分布", fontproperties=self.font_prop,
                      fontsize=12)

        fig.suptitle("低质量翻译分析", fontsize=14,
                     fontproperties=self.font_prop)
        fig.tight_layout(rect=[0, 0, 1, 0.95])
        return self._save(fig, "fig_low_quality.png")

    def generate_all_charts(self, summary, distribution, by_source,
                            trend, by_provider, correlation,
                            flagged) -> list:
        """一键生成所有图表，返回文件路径列表"""
        paths = []

        path = self.plot_dimension_radar(summary, by_group=by_source)
        if path:
            paths.append(path)

        path = self.plot_score_distribution(distribution)
        if path:
            paths.append(path)

        path = self.plot_quality_by_source(by_source)
        if path:
            paths.append(path)

        path = self.plot_quality_trend(trend)
        if path:
            paths.append(path)

        path = self.plot_provider_comparison(by_provider)
        if path:
            paths.append(path)

        path = self.plot_correlation_heatmap(correlation)
        if path:
            paths.append(path)

        path = self.plot_low_quality_summary(flagged, by_source)
        if path:
            paths.append(path)

        return paths
