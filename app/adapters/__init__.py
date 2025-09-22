from typing import Optional

from ..models.entity import NotionDatabase, NotionPage
from .base import BaseAdapter

try:
    from .content import ContentStoreAdapter
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    ContentStoreAdapter = None  # type: ignore[assignment]

try:
    from .postgres import PostgresAdapter
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    PostgresAdapter = None  # type: ignore[assignment]

_content_adapter: Optional["ContentStoreAdapter"] = None


# Legacy factory (unused but kept for backwards compatibility)
def get_adapter(entity_type: str):
    if PostgresAdapter is None:
        raise ValueError("PostgreSQL adapter not available. Install asyncpg to enable it.")

    if entity_type == "page":
        return PostgresAdapter(NotionPage)
    if entity_type == "database":
        return PostgresAdapter(NotionDatabase)

    raise ValueError(f"Unknown entity type: {entity_type}")


def get_content_adapter() -> ContentStoreAdapter:
    if ContentStoreAdapter is None:
        raise ValueError("PostgreSQL adapter not available. Install pg8000 to enable it.")

    global _content_adapter
    if _content_adapter is None:
        _content_adapter = ContentStoreAdapter()

    return _content_adapter
