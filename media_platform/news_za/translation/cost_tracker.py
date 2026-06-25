# -*- coding: utf-8 -*-
"""
翻译成本计算工具
"""

import config


def calc_cost(provider_name: str, input_tokens: int, output_tokens: int) -> float:
    """根据定价表计算费用（USD），返回浮点数"""
    pricing = getattr(config, "SA_NEWS_COST_PRICING", {})
    rate = pricing.get(provider_name, {"input": 0, "output": 0})
    return (input_tokens * rate["input"] + output_tokens * rate["output"]) / 1_000_000


def format_cost(cost_usd: float) -> str:
    """格式化费用为字符串"""
    if cost_usd <= 0:
        return "0 USD"
    return f"{cost_usd:.6f} USD"


def extract_usage(response) -> tuple:
    """从 OpenAI 响应对象提取 token 用量，返回 (prompt_tokens, completion_tokens)"""
    if hasattr(response, "usage") and response.usage:
        return (
            getattr(response.usage, "prompt_tokens", 0) or 0,
            getattr(response.usage, "completion_tokens", 0) or 0,
        )
    return 0, 0