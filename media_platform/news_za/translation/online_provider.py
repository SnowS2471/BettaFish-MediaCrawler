# -*- coding: utf-8 -*-
"""
在线 API 翻译提供商（DeepSeek / Qwen 等 OpenAI 兼容接口）
"""

import asyncio
import re
import time

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from tools import utils

from .base_provider import BaseTranslationProvider, TranslationResult
from .cost_tracker import calc_cost, extract_usage

TRANSLATION_SYSTEM_PROMPT = """你是一位专业的英中新闻翻译专家。请将以下南非英文新闻内容翻译为简体中文。

翻译要求：
1. 保持新闻的客观性和专业性
2. 南非地名、人名、机构名在首次出现时附上中文翻译，如 Johannesburg（约翰内斯堡）
3. 保持原文的段落结构
4. 货币单位 ZAR/Rand 翻译为"兰特"
5. 不添加任何评论或解释，仅输出翻译文本"""


class OnlineTranslationProvider(BaseTranslationProvider):
    """在线 API 翻译（OpenAI 兼容接口）"""

    def __init__(self, api_key: str, base_url: str, model_name: str,
                 chunk_size: int = 6000, timeout: float = 120.0):
        if not api_key:
            raise ValueError("SA_NEWS_TRANSLATION_API_KEY is required for online translation")
        self.client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0)
        self.model = model_name
        self.chunk_size = chunk_size
        self.timeout = timeout

    def provider_name(self) -> str:
        return self.model

    async def translate_article(
        self, title: str, content: str, summary: str
    ) -> TranslationResult:
        t0 = time.perf_counter()
        self._token_acc = [0, 0]  # [input, output] 累加器

        tasks = []
        tasks.append(self._translate_text(title) if title else self._noop())
        tasks.append(self._translate_text(summary) if summary else self._noop())
        tasks.append(self._translate_long_text(content) if content else self._noop())
        title_zh, summary_zh, content_zh = await asyncio.gather(*tasks)

        duration_ms = int((time.perf_counter() - t0) * 1000)
        in_tok, out_tok = self._token_acc
        cost = calc_cost(self.provider_name(), in_tok, out_tok)

        return TranslationResult(
            title_zh=title_zh,
            content_zh=content_zh,
            summary_zh=summary_zh,
            provider=self.provider_name(),
            input_tokens=in_tok,
            output_tokens=out_tok,
            duration_ms=duration_ms,
            estimated_cost_usd=cost,
        )

    @staticmethod
    async def _noop() -> str:
        return ""

    async def _translate_text(self, text: str) -> str:
        """翻译短文本（标题、摘要等）"""
        if not text.strip():
            return ""
        text_result, in_t, out_t = await asyncio.to_thread(self._call_llm, text)
        self._token_acc[0] += in_t
        self._token_acc[1] += out_t
        return text_result

    async def _translate_long_text(self, text: str) -> str:
        """翻译长文本，超过阈值则按段落分块"""
        if not text.strip():
            return ""
        if len(text) <= self.chunk_size:
            return await self._translate_text(text)
        chunks = self._split_into_chunks(text)
        translated = []
        for chunk in chunks:
            result = await self._translate_text(chunk)
            translated.append(result)
        return "\n\n".join(translated)

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        retry=retry_if_exception_type((Exception,)),
        before_sleep=lambda rs: utils.logger.warning(
            f"[Translation] API 调用失败，第 {rs.attempt_number} 次重试: {rs.outcome.exception()}"
        ),
        reraise=True,
    )
    def _call_llm(self, text: str) -> tuple:
        """同步调用 LLM API，返回 (翻译文本, input_tokens, output_tokens)"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": TRANSLATION_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.1,
            timeout=self.timeout,
        )
        in_t, out_t = extract_usage(response)
        content = ""
        if response.choices and response.choices[0].message:
            content = response.choices[0].message.content.strip()
        return content, in_t, out_t

    def _split_into_chunks(self, text: str) -> list:
        """按段落边界分块，每块不超过 chunk_size"""
        paragraphs = re.split(r"\n\s*\n|\n", text)
        chunks = []
        current = ""
        for para in paragraphs:
            if len(current) + len(para) + 2 > self.chunk_size and current:
                chunks.append(current.strip())
                current = para
            else:
                current = current + "\n\n" + para if current else para
        if current.strip():
            chunks.append(current.strip())
        return chunks if chunks else [text]
