"""Versioned database migrations.

Every migration is applied exactly once and recorded in ``schema_migrations``.
Migrations are append-only: never edit an applied migration, add a new one.
Each entry is ``(version, name, [sql statements])``.
"""

from __future__ import annotations

MIGRATIONS: list[tuple[int, str, list[str]]] = [
    (
        1,
        "core_schema",
        [
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_name TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                mime TEXT,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                sha256 TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'imported',
                page_count INTEGER NOT NULL DEFAULT 0,
                subject TEXT,
                source TEXT,
                notes TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_sha ON documents(sha256)",
            "CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status)",
            """
            CREATE TABLE IF NOT EXISTS document_pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                page_number INTEGER NOT NULL,
                image_path TEXT,
                text TEXT,
                ocr_engine TEXT,
                ocr_confidence REAL,
                needs_review INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_pages_document ON document_pages(document_id)",
            """
            CREATE TABLE IF NOT EXISTS knowledge_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
                page_id INTEGER REFERENCES document_pages(id) ON DELETE SET NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                subject TEXT,
                topic TEXT,
                subtopic TEXT,
                source_label TEXT,
                page_number INTEGER,
                quality REAL NOT NULL DEFAULT 1.0,
                uncertainty INTEGER NOT NULL DEFAULT 0,
                content_hash TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_knowledge_subject ON knowledge_items(subject)",
            "CREATE INDEX IF NOT EXISTS idx_knowledge_topic ON knowledge_items(topic)",
            "CREATE INDEX IF NOT EXISTS idx_knowledge_hash ON knowledge_items(content_hash)",
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                title, content, subject, topic, source_label,
                content='knowledge_items',
                content_rowid='id',
                tokenize='unicode61 remove_diacritics 2'
            )
            """,
            """
            CREATE TRIGGER IF NOT EXISTS knowledge_ai AFTER INSERT ON knowledge_items BEGIN
                INSERT INTO knowledge_fts(rowid, title, content, subject, topic, source_label)
                VALUES (new.id, new.title, new.content, new.subject, new.topic, new.source_label);
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS knowledge_ad AFTER DELETE ON knowledge_items BEGIN
                INSERT INTO knowledge_fts(knowledge_fts, rowid, title, content, subject, topic, source_label)
                VALUES ('delete', old.id, old.title, old.content, old.subject, old.topic, old.source_label);
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS knowledge_au AFTER UPDATE ON knowledge_items BEGIN
                INSERT INTO knowledge_fts(knowledge_fts, rowid, title, content, subject, topic, source_label)
                VALUES ('delete', old.id, old.title, old.content, old.subject, old.topic, old.source_label);
                INSERT INTO knowledge_fts(rowid, title, content, subject, topic, source_label)
                VALUES (new.id, new.title, new.content, new.subject, new.topic, new.source_label);
            END
            """,
            """
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT,
                topic TEXT,
                type TEXT NOT NULL,
                difficulty INTEGER NOT NULL DEFAULT 2,
                prompt TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                solution_json TEXT NOT NULL DEFAULT '{}',
                explanation TEXT,
                source_knowledge_ids TEXT,
                created_by TEXT NOT NULL DEFAULT 'system',
                quality REAL NOT NULL DEFAULT 1.0,
                times_served INTEGER NOT NULL DEFAULT 0,
                times_correct INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_questions_subject ON questions(subject, topic)",
            "CREATE INDEX IF NOT EXISTS idx_questions_type ON questions(type)",
            """
            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER REFERENCES questions(id) ON DELETE SET NULL,
                exam_id INTEGER,
                user_answer TEXT,
                is_correct INTEGER NOT NULL DEFAULT 0,
                score REAL NOT NULL DEFAULT 0,
                max_score REAL NOT NULL DEFAULT 1,
                feedback TEXT,
                grading_method TEXT,
                duration_ms INTEGER,
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_attempts_question ON attempts(question_id)",
            "CREATE INDEX IF NOT EXISTS idx_attempts_exam ON attempts(exam_id)",
            """
            CREATE TABLE IF NOT EXISTS exam_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'created',
                config_json TEXT NOT NULL DEFAULT '{}',
                started_at TEXT,
                finished_at TEXT,
                time_limit_seconds INTEGER,
                total_score REAL NOT NULL DEFAULT 0,
                max_score REAL NOT NULL DEFAULT 0,
                analysis_json TEXT,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS exam_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exam_id INTEGER NOT NULL REFERENCES exam_sessions(id) ON DELETE CASCADE,
                question_id INTEGER REFERENCES questions(id) ON DELETE SET NULL,
                position INTEGER NOT NULL,
                answer TEXT,
                points_awarded REAL,
                max_points REAL NOT NULL DEFAULT 1,
                is_correct INTEGER,
                feedback TEXT,
                answered_at TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_exam_items_exam ON exam_items(exam_id)",
            """
            CREATE TABLE IF NOT EXISTS srs_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER REFERENCES questions(id) ON DELETE CASCADE,
                knowledge_id INTEGER REFERENCES knowledge_items(id) ON DELETE SET NULL,
                subject TEXT,
                topic TEXT,
                ease REAL NOT NULL DEFAULT 2.5,
                interval_days REAL NOT NULL DEFAULT 0,
                repetitions INTEGER NOT NULL DEFAULT 0,
                lapses INTEGER NOT NULL DEFAULT 0,
                due_at TEXT NOT NULL,
                last_reviewed_at TEXT,
                state TEXT NOT NULL DEFAULT 'new',
                created_at TEXT NOT NULL
            )
            """,
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_srs_question ON srs_cards(question_id)",
            "CREATE INDEX IF NOT EXISTS idx_srs_due ON srs_cards(due_at)",
            """
            CREATE TABLE IF NOT EXISTS review_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id INTEGER REFERENCES srs_cards(id) ON DELETE CASCADE,
                question_id INTEGER,
                grade INTEGER NOT NULL,
                ease_before REAL,
                ease_after REAL,
                interval_before REAL,
                interval_after REAL,
                reviewed_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS topic_mastery (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                topic TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                correct INTEGER NOT NULL DEFAULT 0,
                mastery REAL NOT NULL DEFAULT 0,
                last_attempt_at TEXT,
                UNIQUE(subject, topic)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS study_plan (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                generated_at TEXT NOT NULL,
                horizon_days INTEGER NOT NULL DEFAULT 14,
                plan_json TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS drawings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                data_json TEXT NOT NULL,
                thumbnail TEXT,
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                priority INTEGER NOT NULL DEFAULT 5,
                payload_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT,
                error TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                progress REAL NOT NULL DEFAULT 0,
                message TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, priority)",
            """
            CREATE TABLE IF NOT EXISTS system_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL,
                category TEXT NOT NULL,
                message TEXT NOT NULL,
                details_json TEXT,
                resolved INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_events_level ON system_events(level, resolved)",
            """
            CREATE TABLE IF NOT EXISTS repairs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER REFERENCES system_events(id) ON DELETE SET NULL,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                detail TEXT,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS ai_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                model TEXT,
                task_type TEXT,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                requests INTEGER NOT NULL DEFAULT 1,
                success INTEGER NOT NULL DEFAULT 1,
                error TEXT,
                latency_ms INTEGER,
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_ai_usage_day ON ai_usage(provider, created_at)",
            """
            CREATE TABLE IF NOT EXISTS ai_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cache_key TEXT NOT NULL UNIQUE,
                provider TEXT,
                model TEXT,
                task_type TEXT,
                response_json TEXT NOT NULL,
                hits INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS ai_budget (
                day TEXT NOT NULL,
                provider TEXT NOT NULL,
                requests_used INTEGER NOT NULL DEFAULT 0,
                tokens_used INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (day, provider)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS backups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                sha256 TEXT,
                kind TEXT NOT NULL DEFAULT 'auto',
                status TEXT NOT NULL DEFAULT 'ok',
                integrity_ok INTEGER,
                note TEXT,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                level TEXT NOT NULL DEFAULT 'info',
                channel TEXT NOT NULL DEFAULT 'homeassistant',
                status TEXT NOT NULL DEFAULT 'pending',
                error TEXT,
                created_at TEXT NOT NULL,
                sent_at TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS diagnostics_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL DEFAULT 'running',
                report_json TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS setup_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                current_step INTEGER NOT NULL DEFAULT 0,
                steps_json TEXT NOT NULL DEFAULT '[]',
                completed INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor TEXT NOT NULL DEFAULT 'system',
                action TEXT NOT NULL,
                target TEXT,
                detail_json TEXT,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """,
        ],
    ),
]
