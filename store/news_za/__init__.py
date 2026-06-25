# -*- coding: utf-8 -*-
"""
南非新闻存储模块
"""

from typing import Dict

import config
from base.base_crawler import AbstractStore
from tools import utils
from var import source_keyword_var

from ._store_impl import *


class SANewsStoreFactory:
    STORES = {
        "csv": SANewsCsvStoreImplement,
        "db": SANewsDbStoreImplement,
        "postgres": SANewsDbStoreImplement,
        "json": SANewsJsonStoreImplement,
        "sqlite": SANewsSqliteStoreImplement,
    }

    @staticmethod
    def create_store() -> AbstractStore:
        store_class = SANewsStoreFactory.STORES.get(config.SAVE_DATA_OPTION)
        if not store_class:
            raise ValueError(
                f"[SANewsStoreFactory] Invalid save option: {config.SAVE_DATA_OPTION}. "
                f"Supported: {list(SANewsStoreFactory.STORES.keys())}"
            )
        return store_class()


async def update_sa_news_article(article_item: Dict):
    """存储新闻文章"""
    article_id = article_item.get("article_id")
    if not article_id:
        return

    article_item["last_modify_ts"] = utils.get_current_timestamp()
    article_item.setdefault("source_keyword", source_keyword_var.get())

    utils.logger.info(
        f"[store.news_za] article: {article_item.get('title', '')[:50]} "
        f"({article_item.get('source_site', '')})"
    )
    await SANewsStoreFactory.create_store().store_content(article_item)
