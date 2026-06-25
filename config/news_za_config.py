# -*- coding: utf-8 -*-
"""
南非新闻网站爬虫配置
"""

# 南非新闻站点配置
SA_NEWS_SITES = {
    "mg": {
        "name": "Mail & Guardian",
        "base_url": "https://mg.co.za",
        "search_url": "https://mg.co.za/?s={keyword}",
        "enabled": True,
    },
    "iol": {
        "name": "Independent Online",
        "base_url": "https://iol.co.za",
        "search_url": "https://iol.co.za/search?q={keyword}",
        "enabled": True,
    },
    "sowetan": {
        "name": "Sowetan",
        "base_url": "https://www.sowetan.co.za",
        "search_url": "https://www.sowetan.co.za/search?q={keyword}",
        "enabled": True,
    },
    "news24": {
        "name": "News24 South Africa",
        "base_url": "https://www.news24.com",
        "section_url": "https://www.news24.com/SouthAfrica",
        "search_url": "https://www.news24.com/search?query={keyword}",
        "enabled": True,
    },
    "sundaytimes": {
        "name": "Sunday Times",
        "base_url": "https://www.sundaytimes.timeslive.co.za",
        "search_url": "https://www.sundaytimes.timeslive.co.za/search?q={keyword}",
        "enabled": True,
    },
}

# 每个站点最大抓取文章数
SA_NEWS_MAX_ARTICLES_PER_SITE = 50

# 请求间隔（秒）
SA_NEWS_CRAWL_DELAY = 2

# 指定要爬取的站点列表（为空则爬取所有 enabled 的站点）
SA_NEWS_SPECIFIED_SITES = []

# ===== 翻译配置 =====
# 在线 API 配置（OpenAI 兼容格式，默认 DeepSeek）
SA_NEWS_TRANSLATION_API_KEY = "sk-2dda3d2360bb4cb5a2e092d36f0e4f17"
SA_NEWS_TRANSLATION_BASE_URL = "https://api.deepseek.com"
SA_NEWS_TRANSLATION_MODEL_NAME = "deepseek-v4-flash"

# 翻译并发数
SA_NEWS_TRANSLATION_CONCURRENCY = 3

# 单次批量翻译文章数
SA_NEWS_TRANSLATION_BATCH_SIZE = 50

# 长文章分块阈值（字符数，超过则按段落分块翻译）
SA_NEWS_TRANSLATION_CHUNK_SIZE = 6000

# 爬取完成后是否自动触发翻译
SA_NEWS_AUTO_TRANSLATE = True

# 翻译完成后是否自动触发质量评估
SA_NEWS_AUTO_EVALUATE = True

# ===== 翻译评估配置 =====
# 评估 LLM（应与翻译 LLM 不同，避免自评偏差）
SA_NEWS_EVAL_API_KEY = "sk-3c39ceeee5c540258b5cf7170c1ae30b"
SA_NEWS_EVAL_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
SA_NEWS_EVAL_MODEL_NAME = "qwen3.6-plus"

# 评估并发数
SA_NEWS_EVAL_CONCURRENCY = 3

# 单次批量评估文章数
SA_NEWS_EVAL_BATCH_SIZE = 50

# 翻译成本定价（每百万 token，USD）
SA_NEWS_COST_PRICING = {
    "deepseek-v4-flash": {"input": 0.28, "output": 0.42},
}

# ===== 翻译质量统计配置 =====
# 低质量翻译阈值（综合评分低于此值标记为低质量）
SA_NEWS_EVAL_LOW_QUALITY_THRESHOLD = 5.0

# 统计输出目录
SA_NEWS_STATS_OUTPUT_DIR = "./output/translation_stats"

# 图表 DPI
SA_NEWS_STATS_CHART_DPI = 300

# 图表中文字体路径（为空则自动检测）
SA_NEWS_STATS_FONT_PATH = ""
