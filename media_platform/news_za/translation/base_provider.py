# -*- coding: utf-8 -*-
"""
翻译提供商抽象基类
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TranslationResult:
    """翻译结果"""
    title_zh: str
    content_zh: str
    summary_zh: str
    provider: str
    # 成本统计
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    estimated_cost_usd: float = 0.0


class BaseTranslationProvider(ABC):
    """翻译提供商基类"""

    @abstractmethod
    async def translate_article(
        self, title: str, content: str, summary: str
    ) -> TranslationResult:
        """翻译单篇文章的标题、正文、摘要"""
        ...

    @abstractmethod
    def provider_name(self) -> str:
        """返回提供商标识，如 'deepseek-chat'"""
        ...
