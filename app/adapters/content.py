import asyncio
import logging
from typing import Optional

import pg8000

from ..config import settings

logger = logging.getLogger(__name__)


class ContentStoreAdapter:
    """Adapter responsible for persisting Notion content snapshots."""

    def __init__(self) -> None:
        self._schema_ready = False
        self._lock = asyncio.Lock()

    def _connect(self):
        if not settings.has_database_credentials:
            raise RuntimeError("Database credentials are not configured")

        return pg8000.connect(
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            database=settings.DB_NAME,
        )

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
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            );
            """,
            "ALTER TABLE notion_contents ADD COLUMN IF NOT EXISTS title TEXT;",
        ]

        conn = self._connect()
        try:
            conn.autocommit = True
            with conn.cursor() as cursor:
                for statement in create_statements:
                    cursor.execute(statement.strip())
        finally:
            conn.close()

    async def upsert(
        self,
        notion_id: str,
        entity_type: str,
        url: Optional[str],
        markdown: str,
        title: Optional[str] = None,
    ) -> None:
        await self.ensure_schema()
        await asyncio.to_thread(
            self._upsert_sync, notion_id, entity_type, url, markdown, title or ""
        )

    def _upsert_sync(
        self,
        notion_id: str,
        entity_type: str,
        url: Optional[str],
        markdown: str,
        title: str,
    ) -> None:
        query = """
        INSERT INTO notion_contents (id, entity_type, title, url, markdown, updated_at)
        VALUES (%s, %s, %s, %s, %s, NOW())
        ON CONFLICT (id) DO UPDATE SET
            entity_type = EXCLUDED.entity_type,
            title = EXCLUDED.title,
            url = EXCLUDED.url,
            markdown = EXCLUDED.markdown,
            updated_at = NOW();
        """

        with self._connect() as conn:
            conn.autocommit = True
            with conn.cursor() as cursor:
                cursor.execute(
                    query, (notion_id, entity_type, title, url, markdown)
                )
