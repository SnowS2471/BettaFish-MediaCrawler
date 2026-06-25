-- 南非新闻文章表：添加翻译字段
-- 适用于已有 sa_news_article 表的数据库迁移
-- PostgreSQL / MySQL 通用语法

ALTER TABLE sa_news_article ADD COLUMN IF NOT EXISTS title_zh TEXT;
ALTER TABLE sa_news_article ADD COLUMN IF NOT EXISTS content_zh TEXT;
ALTER TABLE sa_news_article ADD COLUMN IF NOT EXISTS summary_zh TEXT;
ALTER TABLE sa_news_article ADD COLUMN IF NOT EXISTS translation_status VARCHAR(16) DEFAULT 'pending';
ALTER TABLE sa_news_article ADD COLUMN IF NOT EXISTS translation_provider VARCHAR(64);
ALTER TABLE sa_news_article ADD COLUMN IF NOT EXISTS translation_ts BIGINT;

CREATE INDEX IF NOT EXISTS ix_sa_news_article_translation_status
    ON sa_news_article (translation_status);

-- 将已有文章的 translation_status 设为 pending（如果为 NULL）
UPDATE sa_news_article SET translation_status = 'pending' WHERE translation_status IS NULL;
