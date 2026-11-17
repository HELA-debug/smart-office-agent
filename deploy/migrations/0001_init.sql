-- office-agent-mvp 初始迁移（PostgreSQL 语法）
-- 对应计划书表 7-1 四张表：threads / messages / approvals / artifacts
-- 用法：psql "$DATABASE_URL" -f deploy/migrations/0001_init.sql
--
-- SQLite 兼容说明：
--   1) JSONB → SQLite 用 TEXT 存 JSON 字符串（repo 层负责序列化）；
--   2) TIMESTAMPTZ → SQLite 用 TEXT 存 ISO-8601 带时区字符串（应用层生成，不用 CURRENT_TIMESTAMP 的 UTC 无时区格式）；
--   3) 部分索引/函数默认值在 SQLite 不支持，repo 层初始化时按本文件字段顺序建兼容表；
--   4) 改库只改 DATABASE_URL，业务代码不出现方言专有 SQL（见 ADR 0001）。

BEGIN;

-- 会话
CREATE TABLE IF NOT EXISTS threads (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    extra       JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- 消息与工具结果摘要
CREATE TABLE IF NOT EXISTS messages (
    id          TEXT PRIMARY KEY,
    thread_id   TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool', 'system', 'run_summary')),
    content     TEXT NOT NULL DEFAULT '',
    run_id      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    extra       JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- 审批记录（演示与审计用；mock 发件箱只写本地文件，绝不真实外发）
CREATE TABLE IF NOT EXISTS approvals (
    id          TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL,
    thread_id   TEXT REFERENCES threads(id) ON DELETE CASCADE,
    tool        TEXT NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    decision    TEXT NOT NULL DEFAULT 'pending'
                CHECK (decision IN ('pending', 'approved', 'rejected')),
    decided_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    extra       JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- 产物登记（docx / pdf / txt / upload）
CREATE TABLE IF NOT EXISTS artifacts (
    id          TEXT PRIMARY KEY,
    run_id      TEXT,
    thread_id   TEXT REFERENCES threads(id) ON DELETE CASCADE,
    type        TEXT NOT NULL CHECK (type IN ('docx', 'pdf', 'txt', 'upload')),
    filename    TEXT NOT NULL DEFAULT '',
    path        TEXT NOT NULL DEFAULT '',
    size        BIGINT NOT NULL DEFAULT 0,
    sha256      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    extra       JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- 审计与列表查询索引
CREATE INDEX IF NOT EXISTS idx_messages_thread_created ON messages (thread_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_run             ON messages (run_id);
CREATE INDEX IF NOT EXISTS idx_approvals_run            ON approvals (run_id);
CREATE INDEX IF NOT EXISTS idx_approvals_thread         ON approvals (thread_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_run            ON artifacts (run_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_thread         ON artifacts (thread_id);

COMMIT;

-- 回滚（开发环境手工执行）：
-- DROP TABLE IF EXISTS artifacts;
-- DROP TABLE IF EXISTS approvals;
-- DROP TABLE IF EXISTS messages;
-- DROP TABLE IF EXISTS threads;
