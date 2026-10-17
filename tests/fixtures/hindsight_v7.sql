CREATE TABLE schema_version(version INTEGER PRIMARY KEY);

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
    

    CREATE TABLE IF NOT EXISTS process_paths (
        process_name      TEXT PRIMARY KEY,
        exe_path          TEXT NOT NULL,
        seen_at           TEXT NOT NULL
    );
    

    DELETE FROM app_categories;
    

    DELETE FROM activities
    WHERE process_name LIKE '%\%' OR process_name LIKE '%/%';

    DELETE FROM process_paths
    WHERE process_name LIKE '%\%' OR process_name LIKE '%/%';
    

    UPDATE categories SET builtin = 0;

    INSERT OR IGNORE INTO categories(id, name, color, builtin) VALUES('code',   '编程', '#a78bfa', 0);
    INSERT OR IGNORE INTO categories(id, name, color, builtin) VALUES('browse', '浏览', '#60a5fa', 0);
    INSERT OR IGNORE INTO categories(id, name, color, builtin) VALUES('talk',   '社交', '#34d399', 0);
    INSERT OR IGNORE INTO categories(id, name, color, builtin) VALUES('design', '设计', '#fbbf24', 0);
    INSERT OR IGNORE INTO categories(id, name, color, builtin) VALUES('fun',    '娱乐', '#fb7185', 0);
    INSERT OR IGNORE INTO categories(id, name, color, builtin) VALUES('other',  '其他', '#94a3b8', 0);
    

    ALTER TABLE categories ADD COLUMN icon TEXT NOT NULL DEFAULT 'Tag';

    UPDATE categories SET icon = 'Code'           WHERE id = 'code';
    UPDATE categories SET icon = 'Globe'          WHERE id = 'browse';
    UPDATE categories SET icon = 'MessageCircle'  WHERE id = 'talk';
    UPDATE categories SET icon = 'Brush'          WHERE id = 'design';
    UPDATE categories SET icon = 'Gamepad2'       WHERE id = 'fun';
    UPDATE categories SET icon = 'MoreHorizontal' WHERE id = 'other';
    

    CREATE TABLE IF NOT EXISTS settings_store (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        data TEXT NOT NULL
    );
    INSERT OR IGNORE INTO settings_store(id, data) VALUES (1, '{}');
    
INSERT INTO schema_version VALUES(7);
