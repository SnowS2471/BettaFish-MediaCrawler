# -*- coding: utf-8 -*-
"""
X (Twitter) 存储模块
"""

from typing import Dict, List

import config
from tools import utils
from var import source_keyword_var

from ._store_impl import *


class XStoreFactory:
    STORES = {
        "csv": XCsvStoreImplement,
        "db": XDbStoreImplement,
        "postgres": XDbStoreImplement,
        "json": XJsonStoreImplement,
        "sqlite": XSqliteStoreImplement,
        "mongodb": XMongoStoreImplement,
        "excel": XExcelStoreImplement,
    }

    @staticmethod
    def create_store() -> AbstractStore:
        store_class = XStoreFactory.STORES.get(config.SAVE_DATA_OPTION)
        if not store_class:
            raise ValueError(
                f"[XStoreFactory] Invalid save option: {config.SAVE_DATA_OPTION}. "
                f"Supported: {list(XStoreFactory.STORES.keys())}"
            )
        return store_class()


async def update_x_tweet(tweet_item: Dict):
    """
    存储推文数据
    """
    tweet_id = tweet_item.get("tweet_id")
    if not tweet_id:
        return

    tweet_item["last_modify_ts"] = utils.get_current_timestamp()
    tweet_item.setdefault("source_keyword", source_keyword_var.get())

    utils.logger.info(f"[store.x.update_x_tweet] tweet_id: {tweet_id}")
    await XStoreFactory.create_store().store_content(tweet_item)


async def update_x_tweet_comment(tweet_id: str, comment_item: Dict):
    """
    存储推文评论
    """
    comment_id = comment_item.get("comment_id") or comment_item.get("tweet_id")
    if not comment_id:
        return

    # 确保 tweet_id 字段指向被评论的推文
    comment_item["tweet_id"] = tweet_id
    comment_item["comment_id"] = comment_id
    comment_item["last_modify_ts"] = utils.get_current_timestamp()

    utils.logger.info(f"[store.x.update_x_tweet_comment] comment_id: {comment_id}")
    await XStoreFactory.create_store().store_comment(comment_item)


async def batch_update_x_tweet_comments(tweet_id: str, comments: List[Dict]):
    """
    批量存储推文评论
    """
    if not comments:
        return
    for comment_item in comments:
        await update_x_tweet_comment(tweet_id, comment_item)


async def save_creator(user_id: str, creator_item: Dict):
    """
    存储创作者信息
    """
    if not user_id:
        return

    creator_item["last_modify_ts"] = utils.get_current_timestamp()

    utils.logger.info(f"[store.x.save_creator] user_id: {user_id}")
    await XStoreFactory.create_store().store_creator(creator_item)