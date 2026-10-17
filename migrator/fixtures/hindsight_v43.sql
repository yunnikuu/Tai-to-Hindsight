CREATE TABLE schema_version(version INTEGER PRIMARY KEY);
-- v1

    CREATE TABLE IF NOT EXISTS activities (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at      TEXT NOT NULL,
        ended_at        TEXT NOT NULL,
        duration_secs   INTEGER NOT NULL,
        local_date      TEXT NOT NULL,
        local_hour      INTEGER NOT NULL,
        process_name    TEXT NOT NULL,
        window_title    TEXT,
        category_id     TEXT NOT NULL,
        screenshot_path TEXT,
        image_hash      INTEGER,
        device_id       TEXT NOT NULL DEFAULT 'local'
    );
    CREATE INDEX IF NOT EXISTS idx_activities_date       ON activities(local_date);
    CREATE INDEX IF NOT EXISTS idx_activities_date_hour  ON activities(local_date, local_hour);
    CREATE INDEX IF NOT EXISTS idx_activities_process    ON activities(process_name);
    CREATE INDEX IF NOT EXISTS idx_activities_device     ON activities(device_id);

    CREATE TABLE IF NOT EXISTS categories (
        id      TEXT PRIMARY KEY,
        name    TEXT NOT NULL,
        color   TEXT NOT NULL,
        builtin INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS app_categories (
        process_name TEXT PRIMARY KEY,
        category_id  TEXT NOT NULL REFERENCES categories(id)
    );
    
INSERT INTO schema_version VALUES (1);
-- v2

    CREATE TABLE IF NOT EXISTS process_paths (
        process_name      TEXT PRIMARY KEY,
        exe_path          TEXT NOT NULL,
        seen_at           TEXT NOT NULL
    );
    
INSERT INTO schema_version VALUES (2);
-- v3

    DELETE FROM app_categories;
    
INSERT INTO schema_version VALUES (3);
-- v4

    DELETE FROM activities
    WHERE process_name LIKE '%\%' OR process_name LIKE '%/%';

    DELETE FROM process_paths
    WHERE process_name LIKE '%\%' OR process_name LIKE '%/%';
    
INSERT INTO schema_version VALUES (4);
-- v5

    UPDATE categories SET builtin = 0;

    INSERT OR IGNORE INTO categories(id, name, color, builtin) VALUES('code',   '编程', '#a78bfa', 0);
    INSERT OR IGNORE INTO categories(id, name, color, builtin) VALUES('browse', '浏览', '#60a5fa', 0);
    INSERT OR IGNORE INTO categories(id, name, color, builtin) VALUES('talk',   '社交', '#34d399', 0);
    INSERT OR IGNORE INTO categories(id, name, color, builtin) VALUES('design', '设计', '#fbbf24', 0);
    INSERT OR IGNORE INTO categories(id, name, color, builtin) VALUES('fun',    '娱乐', '#fb7185', 0);
    INSERT OR IGNORE INTO categories(id, name, color, builtin) VALUES('other',  '其他', '#94a3b8', 0);
    
INSERT INTO schema_version VALUES (5);
-- v6

    ALTER TABLE categories ADD COLUMN icon TEXT NOT NULL DEFAULT 'Tag';

    UPDATE categories SET icon = 'Code'           WHERE id = 'code';
    UPDATE categories SET icon = 'Globe'          WHERE id = 'browse';
    UPDATE categories SET icon = 'MessageCircle'  WHERE id = 'talk';
    UPDATE categories SET icon = 'Brush'          WHERE id = 'design';
    UPDATE categories SET icon = 'Gamepad2'       WHERE id = 'fun';
    UPDATE categories SET icon = 'MoreHorizontal' WHERE id = 'other';
    
INSERT INTO schema_version VALUES (6);
-- v7

    CREATE TABLE IF NOT EXISTS settings_store (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        data TEXT NOT NULL
    );
    INSERT OR IGNORE INTO settings_store(id, data) VALUES (1, '{}');
    
INSERT INTO schema_version VALUES (7);
-- v8

    ALTER TABLE categories     ADD COLUMN updated_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z';
    ALTER TABLE categories     ADD COLUMN deleted_at TEXT;
    ALTER TABLE app_categories ADD COLUMN updated_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z';
    ALTER TABLE app_categories ADD COLUMN deleted_at TEXT;
    ALTER TABLE process_paths  ADD COLUMN updated_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z';

    ALTER TABLE activities ADD COLUMN remote_id  TEXT;
    ALTER TABLE activities ADD COLUMN updated_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z';
    ALTER TABLE activities ADD COLUMN origin     TEXT NOT NULL DEFAULT 'local';

    CREATE UNIQUE INDEX IF NOT EXISTS idx_activities_remote
      ON activities(device_id, remote_id) WHERE remote_id IS NOT NULL;

    CREATE TABLE IF NOT EXISTS devices (
      device_id     TEXT PRIMARY KEY,
      display_name  TEXT NOT NULL,
      color         TEXT NOT NULL DEFAULT '#60a5fa',
      icon          TEXT NOT NULL DEFAULT 'Monitor',
      os            TEXT,
      last_seen_at  TEXT,
      is_self       INTEGER NOT NULL DEFAULT 0,
      updated_at    TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z',
      deleted_at    TEXT
    );

    CREATE TABLE IF NOT EXISTS sync_outbox (
      id            INTEGER PRIMARY KEY AUTOINCREMENT,
      op            TEXT NOT NULL,
      entity        TEXT NOT NULL,
      entity_pk     TEXT NOT NULL,
      payload       TEXT NOT NULL,
      created_at    TEXT NOT NULL,
      attempts      INTEGER NOT NULL DEFAULT 0,
      last_error    TEXT,
      next_retry_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_outbox_due ON sync_outbox(next_retry_at);

    CREATE TABLE IF NOT EXISTS sync_cursor (
      entity         TEXT PRIMARY KEY,
      last_pulled_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z'
    );

    CREATE TABLE IF NOT EXISTS auth_state (
      id                INTEGER PRIMARY KEY CHECK (id = 1),
      uid               TEXT,
      email             TEXT,
      refresh_token_enc BLOB,
      access_token      TEXT,
      expires_at        TEXT
    );
    INSERT OR IGNORE INTO auth_state(id) VALUES(1);

    -- 把现有 activities 的 updated_at 回填到 ended_at（首次同步会推这批存量）
    UPDATE activities SET updated_at = ended_at WHERE updated_at = '1970-01-01T00:00:00Z';
    
INSERT INTO schema_version VALUES (8);
-- v9

    DELETE FROM sync_outbox;
    DELETE FROM sync_cursor;
    
INSERT INTO schema_version VALUES (9);
-- v10

    UPDATE categories
       SET name = '社交',
           updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
     WHERE id = 'talk' AND name = '沟通';
    
INSERT INTO schema_version VALUES (10);
-- v11

    DELETE FROM process_paths
    WHERE exe_path = '' OR (exe_path NOT GLOB '?:\*' AND exe_path NOT GLOB '?:/*');

    DELETE FROM app_categories
    WHERE process_name NOT LIKE '%.exe';

INSERT INTO schema_version VALUES (11);
-- v12

INSERT INTO schema_version VALUES (12);
-- v13

    INSERT INTO sync_outbox(op, entity, entity_pk, payload, created_at, attempts, next_retry_at)
    SELECT 'upsert', 'activity', CAST(MIN(id) AS TEXT),
           json_object('localDate', local_date),
           '1970-01-01T00:00:00+00:00',
           0,
           '1970-01-01T00:00:00+00:00'
    FROM activities
    WHERE origin = 'local'
    GROUP BY local_date;

INSERT INTO schema_version VALUES (13);
-- v14

    CREATE TABLE IF NOT EXISTS app_icons (
      process_name TEXT PRIMARY KEY,
      icon_png     BLOB NOT NULL,
      updated_at   TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z',
      deleted_at   TEXT
    );

INSERT INTO schema_version VALUES (14);
-- v15

    CREATE TABLE IF NOT EXISTS app_groups (
      id           TEXT PRIMARY KEY,
      display_name TEXT NOT NULL,
      category_id  TEXT,
      updated_at   TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z',
      deleted_at   TEXT
    );

    CREATE TABLE IF NOT EXISTS app_group_members (
      process_name TEXT PRIMARY KEY,
      group_id     TEXT NOT NULL REFERENCES app_groups(id),
      updated_at   TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z',
      deleted_at   TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_app_group_members_group ON app_group_members(group_id);

    -- Backfill：每个出现过的 process_name（来自 activities 或 app_categories）建一个
    -- 单成员组，group_id = process_name 自身（确定性、跨设备一致）。category_id 从
    -- 现有 app_categories 继承，让老用户配过的分类不丢。
    INSERT INTO app_groups (id, display_name, category_id, updated_at, deleted_at)
    SELECT p.process_name AS id,
           p.process_name AS display_name,
           (SELECT ac.category_id FROM app_categories ac
              WHERE ac.process_name = p.process_name AND ac.deleted_at IS NULL
              LIMIT 1) AS category_id,
           strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
           NULL
    FROM (
        SELECT DISTINCT process_name FROM activities
        UNION
        SELECT DISTINCT process_name FROM app_categories WHERE deleted_at IS NULL
    ) p
    WHERE p.process_name IS NOT NULL
      AND p.process_name <> ''
      AND p.process_name <> 'Unknown'
      AND NOT EXISTS (SELECT 1 FROM app_groups g WHERE g.id = p.process_name);

    INSERT INTO app_group_members (process_name, group_id, updated_at, deleted_at)
    SELECT p.process_name,
           p.process_name,
           strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
           NULL
    FROM (
        SELECT DISTINCT process_name FROM activities
        UNION
        SELECT DISTINCT process_name FROM app_categories WHERE deleted_at IS NULL
    ) p
    WHERE p.process_name IS NOT NULL
      AND p.process_name <> ''
      AND p.process_name <> 'Unknown'
      AND NOT EXISTS (SELECT 1 FROM app_group_members m WHERE m.process_name = p.process_name);

INSERT INTO schema_version VALUES (15);
-- v16

    ALTER TABLE categories ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0;

    UPDATE categories SET sort_order = (
        SELECT rn FROM (
            SELECT id,
                   ROW_NUMBER() OVER (ORDER BY (id = 'other') ASC, id) - 1 AS rn
            FROM categories
        ) ranked
        WHERE ranked.id = categories.id
    );

INSERT INTO schema_version VALUES (16);
-- v17

    -- 字段缺失：直接补完整 10 项
    UPDATE settings_store
    SET data = json_set(
        data,
        '$.privacyUrlKeywords',
        json('["/login","/signin","/sign-in","/sign_in","/auth","/oauth","/sso","/logon","/connect/authorize","/password"]')
    )
    WHERE id = 1
      AND json_type(data, '$.privacyUrlKeywords') IS NULL;

    -- 字段已存在但不含 /password：append
    UPDATE settings_store
    SET data = json_insert(data, '$.privacyUrlKeywords[#]', '/password')
    WHERE id = 1
      AND json_type(data, '$.privacyUrlKeywords') = 'array'
      AND NOT EXISTS (
          SELECT 1 FROM json_each(json_extract(data, '$.privacyUrlKeywords'))
          WHERE value = '/password'
      );

INSERT INTO schema_version VALUES (17);
-- v18

    CREATE TABLE IF NOT EXISTS ai_summaries (
      local_date    TEXT NOT NULL,
      segment_idx   INTEGER NOT NULL,
      label         TEXT NOT NULL,
      start_hour    INTEGER NOT NULL,
      end_hour      INTEGER NOT NULL,
      content       TEXT NOT NULL,
      model         TEXT NOT NULL,
      status        TEXT NOT NULL,
      error         TEXT,
      generated_at  TEXT NOT NULL,
      PRIMARY KEY (local_date, segment_idx)
    );
    CREATE INDEX IF NOT EXISTS idx_ai_summaries_date ON ai_summaries(local_date);

INSERT INTO schema_version VALUES (18);
-- v19

    CREATE TABLE IF NOT EXISTS ai_image_descriptions (
      local_date      TEXT NOT NULL,
      segment_idx     INTEGER NOT NULL,
      image_index     INTEGER NOT NULL,
      screenshot_path TEXT NOT NULL,
      description     TEXT NOT NULL,
      model           TEXT NOT NULL,
      generated_at    TEXT NOT NULL,
      PRIMARY KEY (local_date, segment_idx, image_index)
    );
    CREATE INDEX IF NOT EXISTS idx_ai_image_desc_segment
      ON ai_image_descriptions(local_date, segment_idx);

INSERT INTO schema_version VALUES (19);
-- v20

    ALTER TABLE ai_image_descriptions ADD COLUMN latency_ms INTEGER;
    ALTER TABLE ai_image_descriptions ADD COLUMN prompt_tokens INTEGER;
    ALTER TABLE ai_image_descriptions ADD COLUMN completion_tokens INTEGER;

INSERT INTO schema_version VALUES (20);
-- v21

    CREATE TABLE ai_summaries_new (
      source        TEXT NOT NULL DEFAULT 'daily',
      local_date    TEXT NOT NULL,
      segment_idx   INTEGER NOT NULL,
      label         TEXT NOT NULL,
      start_hour    INTEGER NOT NULL,
      end_hour      INTEGER NOT NULL,
      content       TEXT NOT NULL,
      model         TEXT NOT NULL,
      status        TEXT NOT NULL,
      error         TEXT,
      generated_at  TEXT NOT NULL,
      PRIMARY KEY (source, local_date, segment_idx)
    );
    INSERT INTO ai_summaries_new (
      source, local_date, segment_idx, label, start_hour, end_hour,
      content, model, status, error, generated_at
    )
    SELECT 'daily', local_date, segment_idx, label, start_hour, end_hour,
           content, model, status, error, generated_at
      FROM ai_summaries;
    DROP TABLE ai_summaries;
    ALTER TABLE ai_summaries_new RENAME TO ai_summaries;
    CREATE INDEX IF NOT EXISTS idx_ai_summaries_date
      ON ai_summaries(source, local_date);

    CREATE TABLE ai_image_descriptions_new (
      source            TEXT NOT NULL DEFAULT 'daily',
      local_date        TEXT NOT NULL,
      segment_idx       INTEGER NOT NULL,
      image_index       INTEGER NOT NULL,
      screenshot_path   TEXT NOT NULL,
      description       TEXT NOT NULL,
      model             TEXT NOT NULL,
      generated_at      TEXT NOT NULL,
      latency_ms        INTEGER,
      prompt_tokens     INTEGER,
      completion_tokens INTEGER,
      PRIMARY KEY (source, local_date, segment_idx, image_index)
    );
    INSERT INTO ai_image_descriptions_new (
      source, local_date, segment_idx, image_index, screenshot_path,
      description, model, generated_at, latency_ms, prompt_tokens, completion_tokens
    )
    SELECT 'daily', local_date, segment_idx, image_index, screenshot_path,
           description, model, generated_at, latency_ms, prompt_tokens, completion_tokens
      FROM ai_image_descriptions;
    DROP TABLE ai_image_descriptions;
    ALTER TABLE ai_image_descriptions_new RENAME TO ai_image_descriptions;
    CREATE INDEX IF NOT EXISTS idx_ai_image_desc_segment
      ON ai_image_descriptions(source, local_date, segment_idx);

INSERT INTO schema_version VALUES (21);
-- v22

    CREATE TABLE IF NOT EXISTS screenshot_embeddings (
        screenshot_path TEXT NOT NULL,
        model_id        TEXT NOT NULL,
        dim             INTEGER NOT NULL,
        embedding       BLOB NOT NULL,
        created_at      TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (screenshot_path, model_id)
    );
    CREATE INDEX IF NOT EXISTS idx_screenshot_embeddings_path
        ON screenshot_embeddings (screenshot_path);

INSERT INTO schema_version VALUES (22);
-- v23

    UPDATE settings_store
    SET data = json_set(data, '$.screenshotEnabled', json('false'))
    WHERE id = 1;

INSERT INTO schema_version VALUES (23);
-- v24

    UPDATE sync_cursor
       SET last_pulled_at = '1970-01-01T00:00:00Z'
     WHERE entity = 'drive_files';

INSERT INTO schema_version VALUES (24);
-- v25

    UPDATE sync_outbox
       SET attempts = 0,
           next_retry_at = '1970-01-01T00:00:00+00:00',
           last_error = NULL
     WHERE attempts >= 10;

    INSERT INTO sync_outbox(op, entity, entity_pk, payload, created_at, attempts, next_retry_at)
    SELECT 'upsert', 'activity', CAST(MIN(a.id) AS TEXT),
           json_object('localDate', a.local_date),
           '1970-01-01T00:00:00+00:00',
           0,
           '1970-01-01T00:00:00+00:00'
    FROM activities a
    WHERE a.origin = 'local'
      AND NOT EXISTS (
          SELECT 1 FROM sync_outbox so
          WHERE so.entity = 'activity'
            AND json_extract(so.payload, '$.localDate') = a.local_date
      )
    GROUP BY a.local_date;

INSERT INTO schema_version VALUES (25);
-- v26

    UPDATE activities SET remote_id = CAST(id AS TEXT)
     WHERE remote_id IS NULL;

    CREATE TRIGGER IF NOT EXISTS activities_local_remote_id
    AFTER INSERT ON activities
    FOR EACH ROW WHEN NEW.remote_id IS NULL
    BEGIN
        UPDATE activities SET remote_id = CAST(NEW.id AS TEXT) WHERE id = NEW.id;
    END;

INSERT INTO schema_version VALUES (26);
-- v27

    INSERT OR IGNORE INTO categories(id, name, color, icon, builtin, sort_order, updated_at)
    VALUES (
        'hidden',
        '隐藏',
        '#64748b',
        'EyeOff',
        1,
        COALESCE((SELECT MAX(sort_order) + 1 FROM categories WHERE deleted_at IS NULL), 0),
        '1970-01-01T00:00:00Z'
    );

INSERT INTO schema_version VALUES (27);
-- v28

    CREATE TABLE IF NOT EXISTS super_categories (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        color       TEXT NOT NULL,
        icon        TEXT NOT NULL,
        sort_order  INTEGER NOT NULL DEFAULT 0,
        updated_at  TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z',
        deleted_at  TEXT
    );

    ALTER TABLE categories ADD COLUMN super_category_id TEXT;

INSERT INTO schema_version VALUES (28);
-- v29

    -- 新增 office 默认分类 —— 但仅当用户没有任何 id 或 name 已匹配"办公/office"的活动分类
    -- （`INSERT OR IGNORE` 只防 id 撞车，用户曾用别的 UUID 手动建了「办公」时拦不住，
    --  所以这里用 SELECT...WHERE NOT EXISTS 双校验：id='office' / name='办公' / name='office'
    --  任一已存在的活动分类即跳过插入）
    INSERT INTO categories(id, name, color, icon, builtin, sort_order, updated_at)
    SELECT 'office', '办公', '#0ea5e9', 'Briefcase', 0,
           COALESCE((SELECT MAX(sort_order) + 1 FROM categories WHERE deleted_at IS NULL), 0),
           '1970-01-01T00:00:00Z'
     WHERE NOT EXISTS (
         SELECT 1 FROM categories
          WHERE deleted_at IS NULL
            AND (id = 'office' OR TRIM(name) = '办公' OR LOWER(TRIM(name)) = 'office')
     );

    -- 新增 work 默认大类（id 固定 'work'，INSERT OR IGNORE 防重复）
    INSERT OR IGNORE INTO super_categories(id, name, color, icon, sort_order, updated_at)
    VALUES (
        'work',
        '工作',
        '#8b5cf6',
        'Briefcase',
        0,
        '1970-01-01T00:00:00Z'
    );

    -- 把 编程 / 任何"办公-like"分类 默认归入 工作 —— 仅当它们还未归入任何大类时。
    -- 用户已自创办公（UUID id）也会被匹配上，跟新 seed 的 office 行为一致。
    UPDATE categories SET super_category_id = 'work', updated_at = '1970-01-01T00:00:00Z'
     WHERE deleted_at IS NULL
       AND super_category_id IS NULL
       AND (
           id = 'code'
           OR id = 'office'
           OR TRIM(name) = '办公'
           OR LOWER(TRIM(name)) = 'office'
       );

INSERT INTO schema_version VALUES (29);
-- v30

    INSERT INTO categories(id, name, color, icon, builtin, sort_order, updated_at)
    SELECT 'workchat', '工作沟通', '#14b8a6', 'MessageCircle', 0,
           COALESCE((SELECT MAX(sort_order) + 1 FROM categories WHERE deleted_at IS NULL), 0),
           '1970-01-01T00:00:00Z'
     WHERE NOT EXISTS (
         SELECT 1 FROM categories
          WHERE deleted_at IS NULL
            AND (id = 'workchat' OR TRIM(name) = '工作沟通')
     );

    -- 把所有"工作沟通"-like 分类（不管 id 是新 seed 的 workchat 还是用户自创 UUID）
    -- 默认归入 work 大类——仅当它们还未归入任何大类时。
    UPDATE categories SET super_category_id = 'work', updated_at = '1970-01-01T00:00:00Z'
     WHERE deleted_at IS NULL
       AND super_category_id IS NULL
       AND (id = 'workchat' OR TRIM(name) = '工作沟通');

INSERT INTO schema_version VALUES (30);
-- v31

    -- 1. 清掉 app_groups 指向 fun 的归属（app 变成未分类）
    UPDATE app_groups SET category_id = NULL, updated_at = '1970-01-01T00:00:00Z'
     WHERE category_id = 'fun';

    -- 2. 清掉旧 app_categories 镜像表里指向 fun 的行（软删）
    UPDATE app_categories SET deleted_at = '1970-01-01T00:00:00Z',
                              updated_at = '1970-01-01T00:00:00Z'
     WHERE category_id = 'fun' AND deleted_at IS NULL;

    -- 3. 软删 fun 分类本身（builtin=0，没有保护）
    UPDATE categories SET deleted_at = '1970-01-01T00:00:00Z'
     WHERE id = 'fun' AND deleted_at IS NULL;

    -- 4. 新增 play 大类（id 固定，跟 work 同款套路）
    INSERT OR IGNORE INTO super_categories(id, name, color, icon, sort_order, updated_at)
    VALUES ('play', '娱乐', '#ec4899', 'Sparkles', 1, '1970-01-01T00:00:00Z');

    -- 5. 新增 game 分类，直接 super=play
    INSERT INTO categories(id, name, color, icon, builtin, sort_order, super_category_id, updated_at)
    SELECT 'game', '游戏', '#fb7185', 'Gamepad2', 0,
           COALESCE((SELECT MAX(sort_order) + 1 FROM categories WHERE deleted_at IS NULL), 0),
           'play',
           '1970-01-01T00:00:00Z'
     WHERE NOT EXISTS (
         SELECT 1 FROM categories
          WHERE deleted_at IS NULL
            AND (id = 'game' OR TRIM(name) = '游戏')
     );

    -- 6. 新增 video 分类，直接 super=play
    INSERT INTO categories(id, name, color, icon, builtin, sort_order, super_category_id, updated_at)
    SELECT 'video', '影音', '#a855f7', 'Film', 0,
           COALESCE((SELECT MAX(sort_order) + 1 FROM categories WHERE deleted_at IS NULL), 0),
           'play',
           '1970-01-01T00:00:00Z'
     WHERE NOT EXISTS (
         SELECT 1 FROM categories
          WHERE deleted_at IS NULL
            AND (id = 'video' OR TRIM(name) = '影音')
     );

    -- 7. 把所有 game/video-like 分类（含用户自创 UUID）默认归入 play 大类，
    --    仅当它们未归入任何大类时
    UPDATE categories SET super_category_id = 'play', updated_at = '1970-01-01T00:00:00Z'
     WHERE deleted_at IS NULL
       AND super_category_id IS NULL
       AND (id IN ('game', 'video') OR TRIM(name) IN ('游戏', '影音'));

INSERT INTO schema_version VALUES (31);
-- v32

    INSERT OR IGNORE INTO super_categories(id, name, color, icon, sort_order, updated_at)
    VALUES ('social', '社交', '#34d399', 'MessageCircle', 2, '1970-01-01T00:00:00Z');

    UPDATE categories SET super_category_id = 'social', updated_at = '1970-01-01T00:00:00Z'
     WHERE deleted_at IS NULL
       AND super_category_id IS NULL
       AND (id = 'talk' OR TRIM(name) = '社交');

INSERT INTO schema_version VALUES (32);
-- v33

    INSERT OR IGNORE INTO super_categories(id, name, color, icon, sort_order, updated_at)
    VALUES ('browse', '浏览', '#60a5fa', 'Globe', 3, '1970-01-01T00:00:00Z');

    UPDATE categories SET super_category_id = 'browse', updated_at = '1970-01-01T00:00:00Z'
     WHERE deleted_at IS NULL
       AND super_category_id IS NULL
       AND (id = 'browse' OR TRIM(name) = '浏览');

INSERT INTO schema_version VALUES (33);
-- v34

    DELETE FROM activities        WHERE process_name LIKE '% pid=%';
    DELETE FROM app_group_members WHERE process_name LIKE '% pid=%';
    DELETE FROM app_groups        WHERE id           LIKE '% pid=%';
    DELETE FROM app_categories    WHERE process_name LIKE '% pid=%';
    DELETE FROM process_paths     WHERE process_name LIKE '% pid=%';
    DELETE FROM app_icons         WHERE process_name LIKE '% pid=%';

INSERT INTO schema_version VALUES (34);
-- v35

    CREATE TABLE IF NOT EXISTS screenshot_dedup_map (
        member_path TEXT PRIMARY KEY,
        rep_path    TEXT NOT NULL,
        local_date  TEXT NOT NULL,
        created_at  TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_dedup_map_rep  ON screenshot_dedup_map(rep_path);
    CREATE INDEX IF NOT EXISTS idx_dedup_map_date ON screenshot_dedup_map(local_date);

INSERT INTO schema_version VALUES (35);
-- v36

    ALTER TABLE activities ADD COLUMN excluded INTEGER NOT NULL DEFAULT 0;

INSERT INTO schema_version VALUES (36);
-- v37

    ALTER TABLE activities ADD COLUMN url_host TEXT;

INSERT INTO schema_version VALUES (37);
-- v38

    DROP TABLE IF EXISTS app_categories;

INSERT INTO schema_version VALUES (38);
-- v39

    ALTER TABLE auth_state ADD COLUMN backend TEXT CHECK (backend IN ('drive', 'webdav'));
    ALTER TABLE auth_state ADD COLUMN drive_account TEXT;
    ALTER TABLE auth_state ADD COLUMN webdav_url TEXT;
    ALTER TABLE auth_state ADD COLUMN webdav_user TEXT;
    ALTER TABLE auth_state ADD COLUMN webdav_password_enc BLOB;

INSERT INTO schema_version VALUES (39);
-- v40

    CREATE TABLE IF NOT EXISTS webdav_accounts (
        host TEXT PRIMARY KEY,
        url  TEXT NOT NULL,
        user TEXT NOT NULL
    );

INSERT INTO schema_version VALUES (40);
-- v41

    UPDATE app_groups SET category_id = NULL
     WHERE category_id = 'fun'
       AND EXISTS (SELECT 1 FROM categories WHERE id = 'fun' AND deleted_at IS NOT NULL);

INSERT INTO schema_version VALUES (41);
-- v42

    CREATE TABLE IF NOT EXISTS site_rules (
        host        TEXT NOT NULL,
        browser     TEXT NOT NULL DEFAULT '',
        device      TEXT NOT NULL DEFAULT '',
        category_id TEXT NOT NULL,
        updated_at  TEXT NOT NULL,
        deleted_at  TEXT,
        PRIMARY KEY (host, browser, device)
    );

INSERT INTO schema_version VALUES (42);
-- v43

    INSERT INTO sync_outbox(op, entity, entity_pk, payload, created_at, attempts, next_retry_at)
    SELECT 'upsert', e.entity, '*', '{}', '1970-01-01T00:00:00+00:00', 0, '1970-01-01T00:00:00+00:00'
    FROM (SELECT 'super_category' AS entity UNION ALL SELECT 'category') AS e
    WHERE EXISTS (SELECT 1 FROM activities);

INSERT INTO schema_version VALUES (43);
