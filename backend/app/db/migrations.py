import sqlite3

from app.core.config import settings
from app.db.session import get_connection


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def _add_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    if column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def migrate() -> None:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS communities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                street TEXT,
                area TEXT,
                create_time TEXT,
                modify_time TEXT
            );

            CREATE TABLE IF NOT EXISTS orders (
                ID INTEGER PRIMARY KEY AUTOINCREMENT,
                city TEXT,
                area TEXT,
                street TEXT,
                residential TEXT,
                room_number TEXT,
                acreage REAL,
                list_price REAL,
                price REAL,
                agent TEXT,
                store TEXT,
                signing_date TEXT,
                CA TEXT,
                creator TEXT,
                create_time TEXT,
                modifier TEXT,
                modify_time TEXT,
                maintainor TEXT,
                maintainor_store TEXT,
                parking INTEGER CHECK(parking IN (0, 1)),
                status TEXT CHECK(status IN ('normal', 'cancel')),
                remark TEXT,
                location TEXT,
                brand TEXT
            );
            """
        )

        _add_column(conn, "communities", "city", "TEXT DEFAULT '宁波市'")
        _add_column(conn, "orders", "source_type", "TEXT")
        _add_column(conn, "orders", "source_id", "INTEGER")
        _add_column(conn, "orders", "source_file", "TEXT")
        _add_column(conn, "orders", "review_status", "TEXT DEFAULT 'confirmed'")
        _add_column(conn, "orders", "raw_payload_json", "TEXT")
        _add_column(conn, "orders", "maintainor_store", "TEXT")

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS lease_properties (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                city TEXT,
                community_name TEXT,
                address TEXT,
                acreage REAL,
                price REAL,
                listing_date TEXT,
                rental_type TEXT,
                recorder TEXT,
                maintainor TEXT,
                has_key INTEGER CHECK(has_key IN (0, 1)),
                agent TEXT,
                deal_date TEXT,
                lease_expire_date TEXT,
                cancel_time TEXT,
                cancel_reason TEXT,
                for_sale INTEGER CHECK(for_sale IN (0, 1)),
                owner_phone TEXT,
                customer_phone TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                creator TEXT,
                create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                modifier TEXT,
                modify_time TEXT
            );

            CREATE TABLE IF NOT EXISTS duty_roster (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                city TEXT NOT NULL,
                store_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                sort_order INTEGER NOT NULL,
                create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                modify_time TEXT,
                UNIQUE(city, store_id, user_id),
                FOREIGN KEY(store_id) REFERENCES stores(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS duty_overrides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                city TEXT NOT NULL,
                store_id INTEGER NOT NULL,
                duty_date TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                modifier_user_id INTEGER,
                create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                modify_time TEXT,
                UNIQUE(city, store_id, duty_date),
                FOREIGN KEY(store_id) REFERENCES stores(id),
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(modifier_user_id) REFERENCES users(id)
            );
            """
        )

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                code TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                modify_time TEXT
            );

            CREATE TABLE IF NOT EXISTS stores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                city_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                area TEXT,
                street TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                modify_time TEXT,
                UNIQUE(city_id, name),
                FOREIGN KEY(city_id) REFERENCES cities(id)
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                city_id INTEGER,
                store_id INTEGER,
                status TEXT NOT NULL DEFAULT 'active',
                create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                modify_time TEXT,
                FOREIGN KEY(city_id) REFERENCES cities(id),
                FOREIGN KEY(store_id) REFERENCES stores(id)
            );

            CREATE TABLE IF NOT EXISTS roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                description TEXT,
                create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                permission_type TEXT NOT NULL,
                description TEXT,
                create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS user_roles (
                user_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                PRIMARY KEY(user_id, role_id),
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(role_id) REFERENCES roles(id)
            );

            CREATE TABLE IF NOT EXISTS auth_sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                expire_time TEXT,
                revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0, 1)),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS role_permissions (
                role_id INTEGER NOT NULL,
                permission_id INTEGER NOT NULL,
                PRIMARY KEY(role_id, permission_id),
                FOREIGN KEY(role_id) REFERENCES roles(id),
                FOREIGN KEY(permission_id) REFERENCES permissions(id)
            );

            CREATE TABLE IF NOT EXISTS source_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                city TEXT NOT NULL,
                business_date TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_name TEXT NOT NULL,
                file_hash TEXT NOT NULL UNIQUE,
                ocr_text TEXT,
                parsed_result_json TEXT,
                confidence_json TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                related_order_id INTEGER,
                error_message TEXT,
                create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                modify_time TEXT,
                FOREIGN KEY(related_order_id) REFERENCES orders(ID)
            );

            CREATE TABLE IF NOT EXISTS task_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT NOT NULL,
                title TEXT NOT NULL,
                city TEXT,
                store TEXT,
                source_type TEXT,
                source_id INTEGER,
                assignee_role TEXT,
                assignee_user_id INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                priority INTEGER NOT NULL DEFAULT 2,
                payload_json TEXT,
                reason TEXT,
                result_ref_type TEXT,
                result_ref_id INTEGER,
                create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finish_time TEXT,
                FOREIGN KEY(assignee_user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS task_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                operator_user_id INTEGER,
                before_json TEXT,
                after_json TEXT,
                remark TEXT,
                create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(task_id) REFERENCES task_items(id),
                FOREIGN KEY(operator_user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS lease_task_followups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                lease_id INTEGER NOT NULL,
                operator_user_id INTEGER,
                content TEXT NOT NULL,
                create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(task_id) REFERENCES task_items(id),
                FOREIGN KEY(lease_id) REFERENCES lease_properties(id),
                FOREIGN KEY(operator_user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS lease_reminder_suppressions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lease_id INTEGER NOT NULL UNIQUE,
                task_id INTEGER,
                operator_user_id INTEGER,
                reason TEXT,
                create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(lease_id) REFERENCES lease_properties(id),
                FOREIGN KEY(task_id) REFERENCES task_items(id),
                FOREIGN KEY(operator_user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS import_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                import_type TEXT NOT NULL,
                city TEXT,
                file_path TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                total_count INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                error_json TEXT,
                create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finish_time TEXT
            );

            CREATE TABLE IF NOT EXISTS chat_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT,
                create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                modify_time TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                user_id INTEGER,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                query_json TEXT,
                result_json TEXT,
                create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(session_id) REFERENCES chat_sessions(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS chart_exports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                question TEXT,
                chart_type TEXT,
                chart_config_json TEXT,
                image_path TEXT,
                create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS knowledge_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                city TEXT,
                tags TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                modify_time TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_orders_city_date ON orders(city, signing_date);
            CREATE INDEX IF NOT EXISTS idx_orders_city_residential ON orders(city, residential);
            CREATE INDEX IF NOT EXISTS idx_orders_city_store ON orders(city, store);
            CREATE INDEX IF NOT EXISTS idx_orders_city_agent ON orders(city, agent);
            CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
            CREATE INDEX IF NOT EXISTS idx_orders_review_status ON orders(review_status);
            CREATE INDEX IF NOT EXISTS idx_lease_city_community ON lease_properties(city, community_name);
            CREATE INDEX IF NOT EXISTS idx_lease_city_price ON lease_properties(city, price);
            CREATE INDEX IF NOT EXISTS idx_lease_city_expire ON lease_properties(city, lease_expire_date);
            CREATE INDEX IF NOT EXISTS idx_lease_status ON lease_properties(status);
            CREATE INDEX IF NOT EXISTS idx_duty_roster_store ON duty_roster(city, store_id, sort_order);
            CREATE INDEX IF NOT EXISTS idx_duty_overrides_store_date ON duty_overrides(city, store_id, duty_date);
            CREATE INDEX IF NOT EXISTS idx_source_images_city_date ON source_images(city, business_date);
            CREATE INDEX IF NOT EXISTS idx_task_items_status ON task_items(status);
            CREATE INDEX IF NOT EXISTS idx_task_items_city_status ON task_items(city, status);
            CREATE INDEX IF NOT EXISTS idx_task_items_type_source ON task_items(task_type, source_type, source_id);
            CREATE INDEX IF NOT EXISTS idx_task_items_assignee_status ON task_items(assignee_user_id, status);
            CREATE INDEX IF NOT EXISTS idx_lease_followups_task ON lease_task_followups(task_id);
            CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_knowledge_documents_city ON knowledge_documents(city);
            """
        )

        conn.execute(
            "INSERT OR IGNORE INTO cities(name, code) VALUES (?, ?)",
            (settings.default_city, "ningbo"),
        )
        conn.executemany(
            "INSERT OR IGNORE INTO roles(code, name, description) VALUES (?, ?, ?)",
            [
                ("clerk", "店员", "查询所属城市成交数据，使用智能问答"),
                ("store_manager", "店长", "处理待办、导入数据、管理店员权限"),
                ("admin", "管理员", "系统管理和全部数据权限"),
                ("rental_clerk", "租赁店员", "处理租赁房源到期提醒待办"),
            ],
        )
        conn.executemany(
            "INSERT OR IGNORE INTO permissions(code, name, permission_type, description) VALUES (?, ?, ?, ?)",
            [
                ("orders:read", "查看成交数据", "api", "查询成交记录和统计"),
                ("qa:ask", "智能问答", "api", "通过自然语言查询成交数据"),
                ("images:import", "图片导入", "api", "扫描图片并解析入库"),
                ("tasks:handle", "处理待办", "api", "确认或忽略待办任务"),
                ("users:manage", "用户管理", "api", "管理用户和权限"),
            ],
        )
        role_permissions = {
            "clerk": ["orders:read", "qa:ask"],
            "store_manager": ["orders:read", "qa:ask", "images:import", "tasks:handle"],
            "rental_agent": ["leases:manage"],
            "admin": ["orders:read", "qa:ask", "images:import", "tasks:handle", "users:manage"],
        }
        for role_code, permission_codes in role_permissions.items():
            role = conn.execute("SELECT id FROM roles WHERE code = ?", (role_code,)).fetchone()
            if role is None:
                continue
            for permission_code in permission_codes:
                permission = conn.execute("SELECT id FROM permissions WHERE code = ?", (permission_code,)).fetchone()
                if permission:
                    conn.execute(
                        "INSERT OR IGNORE INTO role_permissions(role_id, permission_id) VALUES (?, ?)",
                        (role["id"], permission["id"]),
                    )
        conn.execute(
            "INSERT OR IGNORE INTO roles(code, name, description) VALUES (?, ?, ?)",
            ("rental_agent", "租赁经纪人", "管理租赁房源数据"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO permissions(code, name, permission_type, description) VALUES (?, ?, ?, ?)",
            ("leases:manage", "租赁房源管理", "api", "新增、导入、编辑和删除租赁房源"),
        )
        role = conn.execute("SELECT id FROM roles WHERE code = ?", ("rental_agent",)).fetchone()
        permission = conn.execute("SELECT id FROM permissions WHERE code = ?", ("leases:manage",)).fetchone()
        if role and permission:
            conn.execute(
                "INSERT OR IGNORE INTO role_permissions(role_id, permission_id) VALUES (?, ?)",
                (role["id"], permission["id"]),
            )
        admin_role = conn.execute("SELECT id FROM roles WHERE code = ?", ("admin",)).fetchone()
        if admin_role and permission:
            conn.execute(
                "INSERT OR IGNORE INTO role_permissions(role_id, permission_id) VALUES (?, ?)",
                (admin_role["id"], permission["id"]),
            )
        conn.commit()
