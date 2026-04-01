# -*- coding: utf-8 -*-
"""
X (Twitter) 存储实现类
"""

import json
from typing import List, Dict

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from base.base_crawler import AbstractStore
from database.db_session import get_session
from database.models import TwitterTweet, TwitterTweetComment, TwitterCreator
from database.mongodb_store_base import MongoDBStoreBase
from tools.async_file_writer import AsyncFileWriter
from tools.time_util import get_current_timestamp
from tools import utils
from var import crawler_type_var


class XCsvStoreImplement(AbstractStore):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.writer = AsyncFileWriter(platform="x", crawler_type=crawler_type_var.get())

    async def store_content(self, content_item: Dict):
        await self.writer.write_to_csv(item_type="contents", item=content_item)

    async def store_comment(self, comment_item: Dict):
        await self.writer.write_to_csv(item_type="comments", item=comment_item)

    async def store_creator(self, creator_item: Dict):
        await self.writer.write_to_csv(item_type="creators", item=creator_item)


class XJsonStoreImplement(AbstractStore):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.writer = AsyncFileWriter(platform="x", crawler_type=crawler_type_var.get())

    async def store_content(self, content_item: Dict):
        await self.writer.write_single_item_to_json(item_type="contents", item=content_item)

    async def store_comment(self, comment_item: Dict):
        await self.writer.write_single_item_to_json(item_type="comments", item=comment_item)

    async def store_creator(self, creator_item: Dict):
        await self.writer.write_single_item_to_json(item_type="creators", item=creator_item)


class XDbStoreImplement(AbstractStore):
    """X 平台数据库存储（MySQL / PostgreSQL）"""

    async def store_content(self, content_item: Dict):
        tweet_id = content_item.get("tweet_id")
        if not tweet_id:
            return
        async with get_session() as session:
            if await self._content_exists(session, tweet_id):
                await self._update_content(session, content_item)
            else:
                await self._add_content(session, content_item)

    async def _add_content(self, session: AsyncSession, item: Dict):
        ts = int(get_current_timestamp())
        tweet = TwitterTweet(
            user_id=item.get("user_id"),
            username=item.get("username"),
            nickname=item.get("nickname"),
            avatar=item.get("avatar"),
            user_verified=item.get("user_verified", 0),
            user_verified_type=item.get("user_verified_type", ""),
            ip_location=item.get("ip_location", ""),
            add_ts=ts,
            last_modify_ts=ts,
            tweet_id=item.get("tweet_id"),
            tweet_type=item.get("tweet_type", "tweet"),
            content=item.get("content"),
            create_time=item.get("create_time"),
            create_date_time=item.get("create_date_time"),
            like_count=item.get("like_count", "0"),
            retweet_count=item.get("retweet_count", "0"),
            reply_count=item.get("reply_count", "0"),
            quote_count=item.get("quote_count", "0"),
            bookmark_count=item.get("bookmark_count", "0"),
            view_count=item.get("view_count", "0"),
            media_urls=item.get("media_urls", "[]"),
            media_types=item.get("media_types", "[]"),
            video_url=item.get("video_url", ""),
            hashtags=item.get("hashtags", "[]"),
            mentioned_users=item.get("mentioned_users", "[]"),
            urls=item.get("urls", "[]"),
            is_retweet=item.get("is_retweet", 0),
            retweeted_tweet_id=item.get("retweeted_tweet_id", ""),
            retweeted_user_id=item.get("retweeted_user_id", ""),
            is_quote=item.get("is_quote", 0),
            quoted_tweet_id=item.get("quoted_tweet_id", ""),
            quoted_user_id=item.get("quoted_user_id", ""),
            is_reply=item.get("is_reply", 0),
            reply_to_tweet_id=item.get("reply_to_tweet_id", ""),
            reply_to_user_id=item.get("reply_to_user_id", ""),
            tweet_url=item.get("tweet_url", ""),
            source_keyword=item.get("source_keyword", ""),
            lang=item.get("lang", ""),
        )
        session.add(tweet)

    async def _update_content(self, session: AsyncSession, item: Dict):
        ts = int(get_current_timestamp())
        update_data = {
            "last_modify_ts": ts,
            "like_count": item.get("like_count", "0"),
            "retweet_count": item.get("retweet_count", "0"),
            "reply_count": item.get("reply_count", "0"),
            "quote_count": item.get("quote_count", "0"),
            "bookmark_count": item.get("bookmark_count", "0"),
            "view_count": item.get("view_count", "0"),
        }
        stmt = update(TwitterTweet).where(
            TwitterTweet.tweet_id == item.get("tweet_id")
        ).values(**update_data)
        await session.execute(stmt)

    async def _content_exists(self, session: AsyncSession, tweet_id: str) -> bool:
        stmt = select(TwitterTweet).where(TwitterTweet.tweet_id == tweet_id)
        result = await session.execute(stmt)
        return result.first() is not None

    async def store_comment(self, comment_item: Dict):
        comment_id = comment_item.get("comment_id") or comment_item.get("tweet_id")
        if not comment_id:
            return
        async with get_session() as session:
            if await self._comment_exists(session, comment_id):
                await self._update_comment(session, comment_item)
            else:
                await self._add_comment(session, comment_item)

    async def _add_comment(self, session: AsyncSession, item: Dict):
        ts = int(get_current_timestamp())
        comment = TwitterTweetComment(
            user_id=item.get("user_id"),
            username=item.get("username"),
            nickname=item.get("nickname"),
            avatar=item.get("avatar"),
            user_verified=item.get("user_verified", 0),
            ip_location=item.get("ip_location", ""),
            add_ts=ts,
            last_modify_ts=ts,
            comment_id=item.get("comment_id") or item.get("tweet_id"),
            tweet_id=item.get("tweet_id"),
            content=item.get("content"),
            create_time=item.get("create_time"),
            create_date_time=item.get("create_date_time"),
            like_count=item.get("like_count", "0"),
            reply_count=item.get("reply_count", "0"),
            retweet_count=item.get("retweet_count", "0"),
            parent_comment_id=item.get("reply_to_tweet_id", ""),
            media_urls=item.get("media_urls", "[]"),
        )
        session.add(comment)

    async def _update_comment(self, session: AsyncSession, item: Dict):
        ts = int(get_current_timestamp())
        comment_id = item.get("comment_id") or item.get("tweet_id")
        update_data = {
            "last_modify_ts": ts,
            "like_count": item.get("like_count", "0"),
            "reply_count": item.get("reply_count", "0"),
        }
        stmt = update(TwitterTweetComment).where(
            TwitterTweetComment.comment_id == comment_id
        ).values(**update_data)
        await session.execute(stmt)

    async def _comment_exists(self, session: AsyncSession, comment_id: str) -> bool:
        stmt = select(TwitterTweetComment).where(TwitterTweetComment.comment_id == comment_id)
        result = await session.execute(stmt)
        return result.first() is not None

    async def store_creator(self, creator_item: Dict):
        user_id = creator_item.get("user_id")
        if not user_id:
            return
        async with get_session() as session:
            if await self._creator_exists(session, user_id):
                await self._update_creator(session, creator_item)
            else:
                await self._add_creator(session, creator_item)

    async def _add_creator(self, session: AsyncSession, item: Dict):
        ts = int(get_current_timestamp())
        creator = TwitterCreator(
            user_id=item.get("user_id"),
            username=item.get("username"),
            nickname=item.get("nickname"),
            avatar=item.get("avatar"),
            banner_url=item.get("banner_url", ""),
            ip_location=item.get("ip_location", ""),
            add_ts=ts,
            last_modify_ts=ts,
            bio=item.get("bio", ""),
            location=item.get("location", ""),
            website=item.get("website", ""),
            join_date=item.get("join_date", ""),
            verified=item.get("verified", 0),
            verified_type=item.get("verified_type", ""),
            protected=item.get("protected", 0),
            followers_count=item.get("followers_count", "0"),
            following_count=item.get("following_count", "0"),
            tweet_count=item.get("tweet_count", "0"),
            listed_count=item.get("listed_count", "0"),
            profile_url=item.get("profile_url", ""),
        )
        session.add(creator)

    async def _update_creator(self, session: AsyncSession, item: Dict):
        ts = int(get_current_timestamp())
        update_data = {
            "last_modify_ts": ts,
            "nickname": item.get("nickname"),
            "avatar": item.get("avatar"),
            "bio": item.get("bio", ""),
            "followers_count": item.get("followers_count", "0"),
            "following_count": item.get("following_count", "0"),
            "tweet_count": item.get("tweet_count", "0"),
        }
        stmt = update(TwitterCreator).where(
            TwitterCreator.user_id == item.get("user_id")
        ).values(**update_data)
        await session.execute(stmt)

    async def _creator_exists(self, session: AsyncSession, user_id: str) -> bool:
        stmt = select(TwitterCreator).where(TwitterCreator.user_id == user_id)
        result = await session.execute(stmt)
        return result.first() is not None


class XSqliteStoreImplement(XDbStoreImplement):
    pass


class XMongoStoreImplement(AbstractStore):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.mongo_store = MongoDBStoreBase(collection_prefix="x")

    async def store_content(self, content_item: Dict):
        tweet_id = content_item.get("tweet_id")
        if not tweet_id:
            return
        await self.mongo_store.save_or_update(
            collection_suffix="contents", query={"tweet_id": tweet_id}, data=content_item
        )

    async def store_comment(self, comment_item: Dict):
        comment_id = comment_item.get("comment_id") or comment_item.get("tweet_id")
        if not comment_id:
            return
        await self.mongo_store.save_or_update(
            collection_suffix="comments", query={"comment_id": comment_id}, data=comment_item
        )

    async def store_creator(self, creator_item: Dict):
        user_id = creator_item.get("user_id")
        if not user_id:
            return
        await self.mongo_store.save_or_update(
            collection_suffix="creators", query={"user_id": user_id}, data=creator_item
        )


class XExcelStoreImplement:
    def __new__(cls, *args, **kwargs):
        from store.excel_store_base import ExcelStoreBase
        return ExcelStoreBase.get_instance(
            platform="x", crawler_type=crawler_type_var.get()
        )