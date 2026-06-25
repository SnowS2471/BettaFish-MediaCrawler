# -*- coding: utf-8 -*-
"""
南非新闻翻译模块
支持在线 API 翻译，含质量评估与统计分析
"""

from .base_provider import BaseTranslationProvider, TranslationResult
from .online_provider import OnlineTranslationProvider
from .provider_factory import create_translation_provider
from .translator import ArticleTranslator
from .eval_provider import EvalProvider, EvalResult
from .evaluator import ArticleEvaluator, run_evaluation
from .stats import TranslationQualityStats
from .visualizer import QualityVisualizer
from .demo_data import generate_demo_data, clear_demo_data
from .run_stats import run_stats_pipeline
