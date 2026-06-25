# -*- coding: utf-8 -*-
"""
翻译提供商工厂
"""

import config
from .online_provider import OnlineTranslationProvider


def create_translation_provider() -> OnlineTranslationProvider:
    """创建在线翻译提供商实例"""
    return OnlineTranslationProvider(
        api_key=getattr(config, "SA_NEWS_TRANSLATION_API_KEY", ""),
        base_url=getattr(config, "SA_NEWS_TRANSLATION_BASE_URL", "https://api.deepseek.com"),
        model_name=getattr(config, "SA_NEWS_TRANSLATION_MODEL_NAME", "deepseek-chat"),
        chunk_size=getattr(config, "SA_NEWS_TRANSLATION_CHUNK_SIZE", 6000),
    )
