# -*- coding: utf-8 -*-
"""
翻译质量评估提供商（LLM-as-judge）
"""

import asyncio
import json
import re
from dataclasses import dataclass

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from tools import utils

EVAL_SYSTEM_PROMPT = """你是一位专业的英中翻译质量评估专家。请对以下英文原文和中文翻译进行质量评估。

评估维度（每项1-10分）：
1. 忠实度(accuracy): 翻译是否忠实传达了原文含义？有无误译、漏译？
2. 流畅度(fluency): 中文表达是否自然流畅？是否有翻译腔？
3. 术语准确性(terminology): 新闻术语、地名、人名、机构名翻译是否准确？南非特有名词处理是否得当？
4. 完整性(completeness): 原文信息是否完整保留？段落结构是否一致？

请严格按以下JSON格式输出，不要输出其他内容：
{
  "accuracy": {"score": 8, "comment": "整体忠实，但第二段有轻微意译偏差"},
  "fluency": {"score": 7, "comment": "大部分流畅，个别句子有翻译腔"},
  "terminology": {"score": 9, "comment": "地名人名处理准确"},
  "completeness": {"score": 10, "comment": "信息完整，段落结构一致"},
  "overall": 8
}"""

EVAL_USER_TEMPLATE = """【英文原文】
{original}

【中文翻译】
{translated}"""


@dataclass
class EvalResult:
    """单篇文章的评估结果"""
    accuracy: int
    fluency: int
    terminology: int
    completeness: int
    overall: int
    comment: dict
    eval_provider: str


class EvalProvider:
    """翻译质量评估提供商（LLM-as-judge）"""

    def __init__(self, api_key: str, base_url: str, model_name: str,
                 timeout: float = 120.0):
        if not api_key:
            raise ValueError("SA_NEWS_EVAL_API_KEY is required for evaluation")
        self.client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0)
        self.model = model_name
        self.timeout = timeout

    async def evaluate(self, original_en: str, translated_zh: str) -> EvalResult:
        """评估单段翻译质量"""
        return await asyncio.to_thread(
            self._call_eval, original_en, translated_zh
        )

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        retry=retry_if_exception_type((Exception,)),
        before_sleep=lambda rs: utils.logger.warning(
            f"[Eval] API 调用失败，第 {rs.attempt_number} 次重试: {rs.outcome.exception()}"
        ),
        reraise=True,
    )
    def _call_eval(self, original_en: str, translated_zh: str) -> EvalResult:
        """同步调用评估 LLM"""
        # 截断过长文本避免超出上下文
        original_en = original_en[:8000]
        translated_zh = translated_zh[:8000]

        user_prompt = EVAL_USER_TEMPLATE.format(
            original=original_en, translated=translated_zh
        )
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": EVAL_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            timeout=self.timeout,
        )
        text = ""
        if response.choices and response.choices[0].message:
            text = response.choices[0].message.content.strip()
        return self._parse_eval_response(text)

    def _parse_eval_response(self, text: str) -> EvalResult:
        """解析 LLM 返回的 JSON 评分"""
        # 去除 markdown 代码块包裹
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # 尝试从文本中提取 JSON
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    utils.logger.warning(f"[EvalProvider] JSON 解析失败: {text[:200]}")
                    return self._default_result()
            else:
                utils.logger.warning(f"[EvalProvider] 无法提取 JSON: {text[:200]}")
                return self._default_result()

        comment = {}
        for dim in ("accuracy", "fluency", "terminology", "completeness"):
            val = data.get(dim, {})
            if isinstance(val, dict):
                comment[dim] = val.get("comment", "")
            else:
                comment[dim] = ""

        def _score(key):
            val = data.get(key, {})
            if isinstance(val, dict):
                return max(1, min(10, int(val.get("score", 5))))
            if isinstance(val, (int, float)):
                return max(1, min(10, int(val)))
            return 5

        return EvalResult(
            accuracy=_score("accuracy"),
            fluency=_score("fluency"),
            terminology=_score("terminology"),
            completeness=_score("completeness"),
            overall=max(1, min(10, int(data.get("overall", 5)))),
            comment=comment,
            eval_provider=self.model,
        )

    def _default_result(self) -> EvalResult:
        """解析失败时的默认结果"""
        return EvalResult(
            accuracy=0, fluency=0, terminology=0, completeness=0, overall=0,
            comment={"error": "评估 LLM 返回格式异常"},
            eval_provider=self.model,
        )