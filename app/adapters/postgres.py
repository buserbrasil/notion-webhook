import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, TypeVar

import asyncpg

from ..config import settings
from ..models.entity import NotionEntity
from .base import BaseAdapter

# Configure logging
logger = logging.getLogger(__name__)

T = TypeVar("T", bound=NotionEntity)


class PostgresAdapter(BaseAdapter[T]):
    """PostgreSQL adapter implementation using asyncpg directly."""

    def __init__(self, model_class: Type[T]):
        """Initialize the adapter with the model class."""
        self.model_class = model_class
        self.pool: Optional[asyncpg.Pool] = None

        # Determine table name based on model
        entity_type = model_class.__name__.lower().replace("notion", "")
        self.table_name = f"notion_{entity_type}s"

    async def connect(self) -> None:
        """Connect to the database and create tables if needed."""
        if not self.pool:
            logger.info(
                f"Connecting to database: {settings.DB_HOST}/{settings.DB_NAME}"
            )

            # Create connection pool
            self.pool = await asyncpg.create_pool(
                host=settings.DB_HOST,
                port=settings.DB_PORT,
                user=settings.DB_USER,
                password=settings.DB_PASSWORD,
                database=settings.DB_NAME,
                min_size=1,
                max_size=settings.DB_POOL_SIZE,
            )

            # Create tables if they don't exist
            await self._create_tables()

    async def disconnect(self) -> None:
        """Disconnect from the database."""
        if self.pool:
            await self.pool.close()
            self.pool = None

    async def _create_tables(self) -> None:
        """Create the required tables if they don't exist."""
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            entity_data JSONB NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
            title TEXT,
            url TEXT,
            parent_id TEXT
        );
        """

        async with self.pool.acquire() as conn:
            await conn.execute(create_table_query)
            # Add any indexes if needed
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_entity_type ON {self.table_name}(entity_type);"
            )

    async def save(self, data: T) -> T:
        """Save data to the database."""
        if not self.pool:
            await self.connect()

        # Convert Pydantic model to dict
        data_dict = data.model_dump()

        # Convert datetime objects to strings
        if "created_at" in data_dict and isinstance(data_dict["created_at"], datetime):
            data_dict["created_at"] = data_dict["created_at"].isoformat()
        else:
            data_dict["created_at"] = datetime.utcnow().isoformat()

        if "updated_at" in data_dict and isinstance(data_dict["updated_at"], datetime):
            data_dict["updated_at"] = data_dict["updated_at"].isoformat()
        else:
            data_dict["updated_at"] = datetime.utcnow().isoformat()

        # Build the column names and placeholders for the query
        columns = []
        placeholders = []
        values = []

        for i, (key, value) in enumerate(data_dict.items(), start=1):
            columns.append(key)
            placeholders.append(f"${i}")

            # Handle entity_data conversion to JSON
            if key == "entity_data" and isinstance(value, dict):
                values.append(json.dumps(value))
            else:
                values.append(value)

        columns_str = ", ".join(columns)
        placeholders_str = ", ".join(placeholders)

        query = f"""
        INSERT INTO {self.table_name} ({columns_str})
        VALUES ({placeholders_str})
        ON CONFLICT (id) DO UPDATE
        SET entity_data = EXCLUDED.entity_data,
            updated_at = EXCLUDED.updated_at,
            title = EXCLUDED.title,
            url = EXCLUDED.url,
            parent_id = EXCLUDED.parent_id
        RETURNING *;
        """

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, *values)

        # Convert row back to model
        return self._row_to_model(row)

    async def get(self, id: str) -> Optional[T]:
        """Get an entity by ID."""
        if not self.pool:
            await self.connect()

        query = f"SELECT * FROM {self.table_name} WHERE id = $1;"

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, id)

        if not row:
            return None

        # Convert row to model
        return self._row_to_model(row)

    async def list(self, filters: Optional[Dict[str, Any]] = None) -> List[T]:
        """List entities with optional filters."""
        if not self.pool:
            await self.connect()

        # Build query with filters
        where_clauses = []
        values = []

        if filters:
            for i, (key, value) in enumerate(filters.items(), start=1):
                where_clauses.append(f"{key} = ${i}")
                values.append(value)

        where_clause = " AND ".join(where_clauses) if where_clauses else "TRUE"
        query = f"SELECT * FROM {self.table_name} WHERE {where_clause};"

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *values)

        # Convert rows to models
        return [self._row_to_model(row) for row in rows]

    async def update(self, id: str, data: Dict[str, Any]) -> Optional[T]:
        """Update an entity by ID."""
        if not self.pool:
            await self.connect()

        # Set updated_at
        data["updated_at"] = datetime.utcnow().isoformat()

        # Build SET clause for the query
        set_clauses = []
        values = [id]  # First value is the ID for the WHERE clause

        for i, (key, value) in enumerate(data.items(), start=2):
            set_clauses.append(f"{key} = ${i}")

            # Handle entity_data conversion to JSON
            if key == "entity_data" and isinstance(value, dict):
                values.append(json.dumps(value))
            else:
                values.append(value)

        set_clause = ", ".join(set_clauses)

        query = f"""
        UPDATE {self.table_name}
        SET {set_clause}
        WHERE id = $1
        RETURNING *;
        """

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, *values)

        if not row:
            return None

        # Convert row to model
        return self._row_to_model(row)

    async def delete(self, id: str) -> bool:
        """Delete an entity by ID."""
        if not self.pool:
            await self.connect()

        query = f"DELETE FROM {self.table_name} WHERE id = $1;"

        async with self.pool.acquire() as conn:
            result = await conn.execute(query, id)

        # Parse the result format which is like 'DELETE 1'
        affected = result.split()[1] if result else "0"
        return int(affected) > 0

    def _row_to_model(self, row: asyncpg.Record) -> T:
        """Convert a database row to a model instance."""
        # Convert Record to dict
        row_dict = dict(row)

        # Handle entity_data (already converted to Python dict by asyncpg)
        if "entity_data" in row_dict and isinstance(row_dict["entity_data"], str):
            row_dict["entity_data"] = json.loads(row_dict["entity_data"])

        # Handle datetime conversion
        for field in ["created_at", "updated_at"]:
            if field in row_dict and not isinstance(row_dict[field], datetime):
                try:
                    if isinstance(row_dict[field], str):
                        row_dict[field] = datetime.fromisoformat(row_dict[field])
                except Exception:
                    # If conversion fails, use current time
                    row_dict[field] = datetime.utcnow()

        # Create and return model instance
        return self.model_class(**row_dict)
