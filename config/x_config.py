# -*- coding: utf-8 -*-
# X (Twitter) platform configuration

import os

# 指定推文 URL 列表（支持完整 URL 或推文 ID）
# 格式: "https://x.com/username/status/1234567890" 或 "1234567890"
X_SPECIFIED_ID_LIST = [
    "https://x.com/elonmusk/status/1234567890",
    # ........................
]

# 指定创作者 URL 列表（支持完整 URL 或用户名）
# 格式: "https://x.com/username" 或 "username"
X_CREATOR_ID_LIST = [
    "https://x.com/elonmusk",
    # ........................
]

# 搜索过滤类型: "Top", "Latest", "People", "Photos", "Videos"
X_SEARCH_FILTER = "Latest"

# === X 官方 API v2 配置 ===
# 开关: True = 使用 tweepy 官方 API, False = 使用 GraphQL（默认）
X_USE_OFFICIAL_API = False

# OAuth 2.0 App-Only Bearer Token
# 在 https://developer.x.com 申请
X_OFFICIAL_BEARER_TOKEN = os.getenv("X_OFFICIAL_BEARER_TOKEN", "AAAAAAAAAAAAAAAAAAAAADvD8wEAAAAAvy8CI8Ot0urNoCwSxepchjmXd%2B8%3DXjoSd5PJ19fMb3KY6csxpCi2ehnweQ5xojlAkcQaGGEBGHb4YR")

# API 层级，影响搜索能力:
#   "free"       - 无搜索端点，仅支持 detail/creator
#   "basic"      - 近 7 天搜索，10k 推文/月
#   "pro"        - 全量历史搜索
#   "enterprise" - 完整访问
X_API_TIER = os.getenv("X_API_TIER", "basic")

# 官方 API 失败时是否回退到 GraphQL 模式
X_OFFICIAL_API_FALLBACK = True
