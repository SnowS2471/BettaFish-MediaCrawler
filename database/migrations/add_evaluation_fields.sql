-- 南非新闻文章表：添加翻译评估和成本统计字段
-- PostgreSQL / MySQL 通用语法

-- 翻译成本统计
ALTER TABLE sa_news_article ADD COLUMN IF NOT EXISTS translation_input_tokens INTEGER DEFAULT 0;
ALTER TABLE sa_news_article ADD COLUMN IF NOT EXISTS translation_output_tokens INTEGER DEFAULT 0;
ALTER TABLE sa_news_article ADD COLUMN IF NOT EXISTS translation_cost VARCHAR(32);
ALTER TABLE sa_news_article ADD COLUMN IF NOT EXISTS translation_duration_ms BIGINT;

-- 翻译评估
ALTER TABLE sa_news_article ADD COLUMN IF NOT EXISTS eval_accuracy INTEGER;
ALTER TABLE sa_news_article ADD COLUMN IF NOT EXISTS eval_fluency INTEGER;
ALTER TABLE sa_news_article ADD COLUMN IF NOT EXISTS eval_terminology INTEGER;
ALTER TABLE sa_news_article ADD COLUMN IF NOT EXISTS eval_completeness INTEGER;
ALTER TABLE sa_news_article ADD COLUMN IF NOT EXISTS eval_overall INTEGER;
ALTER TABLE sa_news_article ADD COLUMN IF NOT EXISTS eval_comment TEXT;
ALTER TABLE sa_news_article ADD COLUMN IF NOT EXISTS eval_provider VARCHAR(64);
ALTER TABLE sa_news_article ADD COLUMN IF NOT EXISTS eval_ts BIGINT;