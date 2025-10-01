import asyncio
import contextlib
import logging
from queue import Empty, Queue
from threading import Lock
from typing import Optional

import pg8000

from ..config import settings

logger = logging.getLogger(__name__)


class ContentStoreAdapter:
    """Adapter responsible for persisting Notion content snapshots."""

    def __init__(self) -> None:
        self._schema_ready = False
        self._lock = asyncio.Lock()
        pool_size = max(1, settings.DB_POOL_SIZE)
        self._pool: Queue = Queue(maxsize=pool_size)
        self._pool_lock = Lock()
        self._created_connections = 0

    def _create_connection(self):
        if not settings.has_database_credentials:
            raise RuntimeError("Database credentials are not configured")

        conn = pg8000.connect(
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            database=settings.DB_NAME,
        )
        conn.autocommit = True
        return conn

    def _acquire_connection(self):
        try:
            conn = self._pool.get_nowait()
            return conn
        except Empty:
            pass

        with self._pool_lock:
            if self._created_connections < self._pool.maxsize:
                conn = self._create_connection()
                self._created_connections += 1
                logger.debug(
                    "Created new content adapter connection (%s/%s)",
                    self._created_connections,
                    self._pool.maxsize,
                )
                return conn

        conn = self._pool.get()
        return conn

    def _release_connection(self, conn, *, discard: bool = False) -> None:
        if discard or getattr(conn, "is_closed", False):
            try:
                conn.close()
            finally:
                with self._pool_lock:
                    self._created_connections = max(0, self._created_connections - 1)
            return

        try:
            self._pool.put_nowait(conn)
        except Exception:
            conn.close()
            with self._pool_lock:
                self._created_connections = max(0, self._created_connections - 1)

    @contextlib.contextmanager
    def _borrow_connection(self):
        conn = self._acquire_connection()
        try:
            yield conn
        except Exception:
            self._release_connection(conn, discard=True)
            raise
        else:
            self._release_connection(conn)

    async def ensure_schema(self) -> None:
        if self._schema_ready:
            return

        async with self._lock:
            if self._schema_ready:
                return

            await asyncio.to_thread(self._create_table)
            self._schema_ready = True

    def _create_table(self) -> None:
        create_statements = [
            """
            CREATE TABLE IF NOT EXISTS notion_contents (
                id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                title TEXT,
                url TEXT,
                markdown TEXT,
                breadcrumbs TEXT,
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            );
            """,
            "ALTER TABLE notion_contents ADD COLUMN IF NOT EXISTS title TEXT;",
            "ALTER TABLE notion_contents ADD COLUMN IF NOT EXISTS breadcrumbs TEXT;",
        ]

        with self._borrow_connection() as conn:
            with conn.cursor() as cursor:
                for statement in create_statements:
                    cursor.execute(statement.strip())

    async def upsert(
        self,
        notion_id: str,
        entity_type: str,
        url: Optional[str],
        markdown: str,
        title: Optional[str] = None,
        breadcrumbs_json: Optional[str] = None,
    ) -> None:
        await self.ensure_schema()
        await asyncio.to_thread(
            self._upsert_sync,
            notion_id,
            entity_type,
            url,
            markdown,
            title or "",
            breadcrumbs_json or None,
        )

    def _upsert_sync(
        self,
        notion_id: str,
        entity_type: str,
        url: Optional[str],
        markdown: str,
        title: str,
        breadcrumbs_json: Optional[str],
    ) -> None:
        query = """
        INSERT INTO notion_contents (
            id, entity_type, title, url, markdown, breadcrumbs, updated_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s, NOW()
        )
        ON CONFLICT (id) DO UPDATE SET
            entity_type = EXCLUDED.entity_type,
            title = EXCLUDED.title,
            url = EXCLUDED.url,
            markdown = EXCLUDED.markdown,
            breadcrumbs = EXCLUDED.breadcrumbs,
            updated_at = NOW();
        """

        conn = self._acquire_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    query,
                    (
                        notion_id,
                        entity_type,
                        title,
                        url,
                        markdown,
                        breadcrumbs_json,
                    ),
                )
        except Exception:
            self._release_connection(conn, discard=True)
            raise
        else:
            self._release_connection(conn)
