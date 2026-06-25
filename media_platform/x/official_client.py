# -*- coding: utf-8 -*-
"""
X (Twitter) 官方 API v2 客户端
基于 tweepy 封装，输出与 GraphQL 爬虫兼容的数据格式
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

import tweepy

from .exception import DataFetchError

# v2 API 请求字段
TWEET_FIELDS = [
    "id", "text", "created_at", "author_id", "conversation_id",
    "in_reply_to_user_id", "referenced_tweets", "public_metrics",
    "entities", "attachments", "lang",
]
USER_FIELDS = [
    "id", "name", "username", "profile_image_url", "verified",
    "verified_type", "description", "location", "url",
    "created_at", "public_metrics", "protected",
    "profile_banner_url",
]
MEDIA_FIELDS = ["media_key", "type", "url", "preview_image_url", "variants"]
TWEET_EXPANSIONS = [
    "author_id",
    "referenced_tweets.id",
    "referenced_tweets.id.author_id",
    "attachments.media_keys",
]


class XOfficialClient:
    """X API v2 客户端，基于 tweepy，输出与现有 store 层兼容的 dict 格式"""

    def __init__(self, bearer_token: str, api_tier: str = "basic"):
        self._client = tweepy.Client(
            bearer_token=bearer_token,
            wait_on_rate_limit=True,
        )
        self._api_tier = api_tier.lower()

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------

    async def search_tweets(self, keyword: str, max_results: int = 50) -> List[Dict]:
        """搜索推文，返回 store 兼容的 dict 列表"""
        if self._api_tier == "free":
            raise DataFetchError("Free 层级不支持搜索端点，请升级或切换到 GraphQL 模式")

        results: List[Dict] = []
        per_page = min(max_results, 100)

        def _paginate():
            pages = []
            for resp in tweepy.Paginator(
                self._client.search_recent_tweets,
                query=keyword,
                tweet_fields=TWEET_FIELDS,
                user_fields=USER_FIELDS,
                media_fields=MEDIA_FIELDS,
                expansions=TWEET_EXPANSIONS,
                max_results=per_page,
            ):
                pages.append(resp)
                # 提前终止：已收集足够数据
                collected = sum(len(p.data or []) for p in pages)
                if collected >= max_results:
                    break
            return pages

        pages = await asyncio.to_thread(_paginate)
        for page in pages:
            if not page.data:
                continue
            users = self._build_user_lookup(page.includes)
            media = self._build_media_lookup(page.includes)
            ref_tweets = self._build_ref_tweet_lookup(page.includes)
            for tweet in page.data:
                results.append(self._convert_tweet(tweet, users, media, ref_tweets))
                if len(results) >= max_results:
                    return results
        return results

    async def get_tweet_detail(self, tweet_id: str) -> Optional[Dict]:
        """获取单条推文详情"""
        resp = await asyncio.to_thread(
            self._client.get_tweet,
            id=tweet_id,
            tweet_fields=TWEET_FIELDS,
            user_fields=USER_FIELDS,
            media_fields=MEDIA_FIELDS,
            expansions=TWEET_EXPANSIONS,
        )
        if not resp or not resp.data:
            return None
        users = self._build_user_lookup(resp.includes)
        media = self._build_media_lookup(resp.includes)
        ref_tweets = self._build_ref_tweet_lookup(resp.includes)
        return self._convert_tweet(resp.data, users, media, ref_tweets)

    async def get_tweet_comments(self, tweet_id: str, max_results: int = 20) -> List[Dict]:
        """获取推文的回复（通过 conversation_id 搜索）"""
        if self._api_tier == "free":
            return []

        query = f"conversation_id:{tweet_id} -is:retweet"
        results: List[Dict] = []
        per_page = min(max_results, 100)

        def _paginate():
            pages = []
            for resp in tweepy.Paginator(
                self._client.search_recent_tweets,
                query=query,
                tweet_fields=TWEET_FIELDS,
                user_fields=USER_FIELDS,
                media_fields=MEDIA_FIELDS,
                expansions=TWEET_EXPANSIONS,
                max_results=per_page,
            ):
                pages.append(resp)
                collected = sum(len(p.data or []) for p in pages)
                if collected >= max_results:
                    break
            return pages

        pages = await asyncio.to_thread(_paginate)
        for page in pages:
            if not page.data:
                continue
            users = self._build_user_lookup(page.includes)
            media = self._build_media_lookup(page.includes)
            ref_tweets = self._build_ref_tweet_lookup(page.includes)
            for tweet in page.data:
                results.append(self._convert_tweet(tweet, users, media, ref_tweets))
                if len(results) >= max_results:
                    return results
        return results

    async def get_user_info(self, username: str) -> Optional[Dict]:
        """获取用户信息，返回 creator 兼容的 dict"""
        resp = await asyncio.to_thread(
            self._client.get_user,
            username=username,
            user_fields=USER_FIELDS,
        )
        if not resp or not resp.data:
            return None
        return self._convert_user(resp.data)

    async def get_user_tweets(self, user_id: str, max_results: int = 50) -> List[Dict]:
        """获取用户推文列表"""
        results: List[Dict] = []
        per_page = min(max_results, 100)

        def _paginate():
            pages = []
            for resp in tweepy.Paginator(
                self._client.get_users_tweets,
                id=user_id,
                tweet_fields=TWEET_FIELDS,
                user_fields=USER_FIELDS,
                media_fields=MEDIA_FIELDS,
                expansions=TWEET_EXPANSIONS,
                max_results=per_page,
            ):
                pages.append(resp)
                collected = sum(len(p.data or []) for p in pages)
                if collected >= max_results:
                    break
            return pages

        pages = await asyncio.to_thread(_paginate)
        for page in pages:
            if not page.data:
                continue
            users = self._build_user_lookup(page.includes)
            media = self._build_media_lookup(page.includes)
            ref_tweets = self._build_ref_tweet_lookup(page.includes)
            for tweet in page.data:
                results.append(self._convert_tweet(tweet, users, media, ref_tweets))
                if len(results) >= max_results:
                    return results
        return results

    # ------------------------------------------------------------------
    # 数据转换（核心：映射为与 extract_tweet_data() 完全一致的 dict）
    # ------------------------------------------------------------------

    @staticmethod
    def _build_user_lookup(includes: Optional[Dict]) -> Dict[str, tweepy.User]:
        if not includes or "users" not in includes:
            return {}
        return {str(u.id): u for u in includes["users"]}

    @staticmethod
    def _build_media_lookup(includes: Optional[Dict]) -> Dict[str, Dict]:
        if not includes or "media" not in includes:
            return {}
        return {m.media_key: m for m in includes["media"]}

    @staticmethod
    def _build_ref_tweet_lookup(includes: Optional[Dict]) -> Dict[str, tweepy.Tweet]:
        if not includes or "tweets" not in includes:
            return {}
        return {str(t.id): t for t in includes["tweets"]}

    def _convert_tweet(
        self,
        tweet: tweepy.Tweet,
        users: Dict[str, tweepy.User],
        media_lookup: Dict[str, Dict],
        ref_tweets: Dict[str, tweepy.Tweet],
    ) -> Dict:
        """将 tweepy v2 Tweet 转换为与 extract_tweet_data() 输出一致的 dict"""
        data = tweet.data
        tweet_id = str(data["id"])
        author_id = str(data.get("author_id", ""))
        user = users.get(author_id)

        username = user.username if user else ""
        nickname = user.name if user else ""
        avatar = user.data.get("profile_image_url", "") if user else ""
        user_verified = 1 if (user and user.data.get("verified_type")) else 0
        user_verified_type = (user.data.get("verified_type", "") if user else "") or ""

        # 时间戳
        created_at = data.get("created_at", "")
        create_time = 0
        if created_at:
            try:
                dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                create_time = int(dt.timestamp())
            except (ValueError, TypeError):
                pass

        # 互动数据
        pm = data.get("public_metrics", {})

        # 推文类型 & 引用关系
        tweet_type = "tweet"
        retweeted_tweet_id, retweeted_user_id = "", ""
        quoted_tweet_id, quoted_user_id = "", ""
        reply_to_tweet_id = ""
        reply_to_user_id = data.get("in_reply_to_user_id", "") or ""
        if reply_to_user_id:
            reply_to_user_id = str(reply_to_user_id)

        for ref in data.get("referenced_tweets", []) or []:
            ref_type = ref.get("type", "")
            ref_id = str(ref.get("id", ""))
            ref_tweet_obj = ref_tweets.get(ref_id)
            if ref_type == "retweeted":
                tweet_type = "retweet"
                retweeted_tweet_id = ref_id
                if ref_tweet_obj:
                    retweeted_user_id = str(ref_tweet_obj.data.get("author_id", ""))
            elif ref_type == "quoted":
                tweet_type = "quote"
                quoted_tweet_id = ref_id
                if ref_tweet_obj:
                    quoted_user_id = str(ref_tweet_obj.data.get("author_id", ""))
            elif ref_type == "replied_to":
                if tweet_type == "tweet":
                    tweet_type = "reply"
                reply_to_tweet_id = ref_id

        # 媒体
        media_urls_list: List[str] = []
        media_types_list: List[str] = []
        video_url = ""
        attachments = data.get("attachments", {}) or {}
        for mk in attachments.get("media_keys", []) or []:
            m = media_lookup.get(mk)
            if not m:
                continue
            m_data = m.data if hasattr(m, "data") else m
            m_type = m_data.get("type", "photo")
            if m_type == "photo":
                url = m_data.get("url", "")
            elif m_type == "video":
                variants = m_data.get("variants", []) or []
                mp4s = [v for v in variants if v.get("content_type") == "video/mp4"]
                url = max(mp4s, key=lambda v: v.get("bit_rate", 0)).get("url", "") if mp4s else ""
                if url and not video_url:
                    video_url = url
            elif m_type == "animated_gif":
                variants = m_data.get("variants", []) or []
                url = variants[0].get("url", "") if variants else ""
                if url and not video_url:
                    video_url = url
            else:
                url = m_data.get("url", "")
            if url:
                media_urls_list.append(url)
                media_types_list.append(m_type)

        # entities
        entities = data.get("entities", {}) or {}
        hashtags = [h.get("tag", "") for h in entities.get("hashtags", []) or []]
        mentioned_users = [m.get("username", "") for m in entities.get("mentions", []) or []]
        urls = [u.get("expanded_url", "") for u in entities.get("urls", []) or []]

        is_retweet = 1 if tweet_type == "retweet" else 0
        is_quote = 1 if tweet_type == "quote" else 0
        is_reply = 1 if tweet_type == "reply" else 0

        return {
            "tweet_id": tweet_id,
            "user_id": author_id,
            "username": username,
            "nickname": nickname,
            "avatar": avatar,
            "user_verified": user_verified,
            "user_verified_type": user_verified_type,
            "ip_location": "",
            "content": data.get("text", ""),
            "tweet_type": tweet_type,
            "create_time": create_time,
            "create_date_time": created_at,
            "like_count": str(pm.get("like_count", 0)),
            "retweet_count": str(pm.get("retweet_count", 0)),
            "reply_count": str(pm.get("reply_count", 0)),
            "quote_count": str(pm.get("quote_count", 0)),
            "bookmark_count": str(pm.get("bookmark_count", 0)),
            "view_count": str(pm.get("impression_count", 0)),
            "media_urls": json.dumps(media_urls_list, ensure_ascii=False),
            "media_types": json.dumps(media_types_list, ensure_ascii=False),
            "video_url": video_url,
            "hashtags": json.dumps(hashtags, ensure_ascii=False),
            "mentioned_users": json.dumps(mentioned_users, ensure_ascii=False),
            "urls": json.dumps(urls, ensure_ascii=False),
            "is_retweet": is_retweet,
            "retweeted_tweet_id": retweeted_tweet_id,
            "retweeted_user_id": retweeted_user_id,
            "is_quote": is_quote,
            "quoted_tweet_id": quoted_tweet_id,
            "quoted_user_id": quoted_user_id,
            "is_reply": is_reply,
            "reply_to_tweet_id": reply_to_tweet_id,
            "reply_to_user_id": reply_to_user_id,
            "tweet_url": f"https://x.com/{username}/status/{tweet_id}",
            "lang": data.get("lang", ""),
        }

    @staticmethod
    def _convert_user(user: tweepy.User) -> Dict:
        """将 tweepy User 转换为与 core.py get_creators_and_tweets() 一致的 creator dict"""
        d = user.data
        pm = d.get("public_metrics", {})
        return {
            "user_id": str(d["id"]),
            "username": d.get("username", ""),
            "nickname": d.get("name", ""),
            "avatar": d.get("profile_image_url", ""),
            "banner_url": d.get("profile_banner_url", ""),
            "bio": d.get("description", ""),
            "location": d.get("location", ""),
            "website": d.get("url", "") or "",
            "join_date": d.get("created_at", ""),
            "verified": 1 if d.get("verified_type") else 0,
            "verified_type": d.get("verified_type", "") or "",
            "protected": 1 if d.get("protected") else 0,
            "followers_count": str(pm.get("followers_count", 0)),
            "following_count": str(pm.get("following_count", 0)),
            "tweet_count": str(pm.get("tweet_count", 0)),
            "listed_count": str(pm.get("listed_count", 0)),
            "profile_url": f"https://x.com/{d.get('username', '')}",
        }
