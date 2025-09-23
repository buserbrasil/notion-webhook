import asyncio
import hashlib
import hmac
import logging
from contextvars import ContextVar
from typing import Any, Dict, List, Optional

import httpx
from fastapi import Request

from ..adapters import get_content_adapter
from ..config import settings

logger = logging.getLogger(__name__)
NOTION_API_URL = "https://api.notion.com/v1"

_client_var: ContextVar[Optional[httpx.AsyncClient]] = ContextVar(
    "notion_http_client", default=None
)
_client_lock_var: ContextVar[Optional[asyncio.Lock]] = ContextVar(
    "notion_http_client_lock", default=None
)
_retryable_statuses = {408, 425, 429, 500, 502, 503, 504}
_max_retries = 3
_retry_backoff = 0.5


def _get_lock(create: bool = True) -> Optional[asyncio.Lock]:
    lock = _client_lock_var.get()
    if lock is None and create:
        lock = asyncio.Lock()
        _client_lock_var.set(lock)
    return lock


async def _get_http_client() -> httpx.AsyncClient:
    """Return a shared AsyncClient instance, initialising it on demand."""

    lock = _get_lock()
    assert lock is not None  # lock is created when missing

    async with lock:
        client = _client_var.get()
        if client is None or client.is_closed:
            client = httpx.AsyncClient(timeout=httpx.Timeout(15.0))
            _client_var.set(client)

    return client


async def aclose_http_client() -> None:
    """Gracefully close the shared HTTP client."""

    lock = _get_lock(create=False)
    if lock is None:
        client = _client_var.get()
        if client is None:
            return
        _client_var.set(None)
        try:
            await client.aclose()
        except Exception:
            logger.debug("Failed to close HTTP client during shutdown", exc_info=True)
        return

    async with lock:
        client = _client_var.get()
        if client is None:
            return
        _client_var.set(None)

    try:
        await client.aclose()
    except Exception:
        logger.debug("Failed to close HTTP client during shutdown", exc_info=True)


async def validate_webhook_signature(request: Request, body: bytes) -> bool:
    """Return True when the request signature matches the computed HMAC."""

    token = settings.NOTION_VERIFICATION_TOKEN
    if not token:
        logger.debug(
            "NOTION_VERIFICATION_TOKEN not configured; skipping signature validation."
        )
        return True

    signature_header = request.headers.get("X-Notion-Signature")
    if not signature_header:
        logger.warning("Missing %s header", "X-Notion-Signature")
        return False

    expected_signature = "sha256=" + hmac.new(
        token.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(signature_header, expected_signature)


def is_verification_request(body: Dict[str, Any]) -> bool:
    """Return True when the payload matches the verification shape."""

    return isinstance(body, dict) and "verification_token" in body


async def fetch_entity_data(
    entity_id: str,
    entity_type: str,
    event_metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Fetch data for an entity from the Notion API."""

    if not settings.NOTION_API_KEY:
        logger.info(
            "NOTION_API_KEY not configured; skipping fetch for %s %s",
            entity_type,
            entity_id,
        )
        return None

    endpoint = f"{NOTION_API_URL}/{entity_type}s/{entity_id}"
    params: Dict[str, Any] = {}
    headers = {
        "Authorization": f"Bearer {settings.NOTION_API_KEY}",
        "Notion-Version": settings.NOTION_API_VERSION,
        "Content-Type": "application/json",
    }

    try:
        response = await _request_with_retry(
            "GET",
            endpoint,
            headers=headers,
            params=params,
        )
        entity = response.json()

        if entity_type == "page":
            blocks = await _fetch_block_children(entity_id, headers)
            entity["blocks"] = blocks
            entity["markdown"] = blocks_to_markdown(blocks)
            entity["title"] = extract_title(entity, "page")
        elif entity_type == "database":
            entity.setdefault("markdown", "")
            entity["title"] = extract_title(entity, "database")

        if entity_type == "page" and "url" not in entity:
            entity["url"] = build_page_url(entity)

        if event_metadata:
            entity.setdefault("event_metadata", event_metadata)

        return entity
    except httpx.HTTPStatusError as exc:
        logger.error(
            "HTTP error fetching Notion entity %s: %s",
            entity_id,
            exc,
        )
        raise Exception(f"Failed to fetch Notion entity: {exc}") from exc
    except httpx.RequestError as exc:
        logger.error("Network error fetching Notion entity %s: %s", entity_id, exc)
        raise Exception(f"Failed to fetch Notion entity: {exc}") from exc
    except Exception as exc:
        logger.error("Error fetching Notion entity %s: %s", entity_id, exc)
        raise Exception(f"Failed to fetch Notion entity: {exc}") from exc


async def _request_with_retry(
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    json_payload: Optional[Dict[str, Any]] = None,
) -> httpx.Response:
    """Perform an HTTP request with exponential backoff on transient errors."""

    for attempt in range(_max_retries):
        client = await _get_http_client()
        try:
            response = await client.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_payload,
            )
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            should_retry = status_code in _retryable_statuses
            if not should_retry or attempt == _max_retries - 1:
                raise
            sleep_for = _retry_backoff * (2**attempt)
            logger.warning(
                "Retrying %s %s after HTTP %s (attempt %s/%s)",
                method,
                url,
                status_code,
                attempt + 1,
                _max_retries,
            )
            await asyncio.sleep(sleep_for)
        except httpx.RequestError as exc:
            if attempt == _max_retries - 1:
                raise
            await _invalidate_http_client()
            sleep_for = _retry_backoff * (2**attempt)
            logger.warning(
                "Retrying %s %s after network error %s (attempt %s/%s)",
                method,
                url,
                exc,
                attempt + 1,
                _max_retries,
            )
            await asyncio.sleep(sleep_for)
        except RuntimeError as exc:
            if "handler is closed" not in str(exc) or attempt == _max_retries - 1:
                raise
            await _invalidate_http_client()
            sleep_for = _retry_backoff * (2**attempt)
            logger.warning(
                "Retrying %s %s after runtime error %s (attempt %s/%s)",
                method,
                url,
                exc,
                attempt + 1,
                _max_retries,
            )
            await asyncio.sleep(sleep_for)

    raise RuntimeError("Retry loop exhausted without returning a response")


async def _fetch_block_children(
    block_id: str,
    headers: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Recursively fetch all child blocks for a given block/page."""

    children: List[Dict[str, Any]] = []
    cursor: Optional[str] = None

    while True:
        params: Dict[str, Any] = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor

        response = await _request_with_retry(
            "GET",
            f"{NOTION_API_URL}/blocks/{block_id}/children",
            headers=headers,
            params=params,
        )
        payload = response.json()

        for block in payload.get("results", []):
            if block.get("has_children"):
                block["children"] = await _fetch_block_children(
                    block["id"], headers
                )
            children.append(block)

        if not payload.get("has_more"):
            break

        cursor = payload.get("next_cursor")

    return children


async def _invalidate_http_client() -> None:
    """Dispose of the shared HTTP client so the next request builds a fresh one."""

    lock = _get_lock(create=False)
    if lock is None:
        client = _client_var.get()
        if client is None:
            return
        _client_var.set(None)
    else:
        async with lock:
            client = _client_var.get()
            if client is None:
                return
            _client_var.set(None)

    try:
        await client.aclose()
    except Exception:
        logger.debug("Failed to close HTTP client during reset", exc_info=True)


def blocks_to_markdown(blocks: List[Dict[str, Any]], indent_level: int = 0) -> str:
    """Convert a list of Notion blocks into Markdown."""

    lines: List[str] = []
    numbered_counters: Dict[int, int] = {}

    for block in blocks:
        if block.get("type") is None:
            continue

        block_type = block["type"]
        content = block.get(block_type, {})
        indent = " " * (indent_level * 2)
        text = _rich_text_array_to_markdown(content.get("rich_text", []))

        line = ""
        if block_type == "paragraph":
            line = f"{indent}{text}" if text else indent
        elif block_type == "heading_1":
            line = f"# {text}" if text else "#"
        elif block_type == "heading_2":
            line = f"## {text}" if text else "##"
        elif block_type == "heading_3":
            line = f"### {text}" if text else "###"
        elif block_type == "bulleted_list_item":
            line = f"{indent}- {text}" if text else f"{indent}-"
        elif block_type == "numbered_list_item":
            count = numbered_counters.get(indent_level, 0) + 1
            numbered_counters[indent_level] = count
            line = f"{indent}{count}. {text}" if text else f"{indent}{count}."
        else:
            numbered_counters.pop(indent_level, None)
            if block_type == "to_do":
                checked = "x" if content.get("checked") else " "
                line = (
                    f"{indent}- [{checked}] {text}" if text else f"{indent}- [{checked}]"
                )
            elif block_type == "quote":
                line = f"> {text}" if text else ">"
            elif block_type == "callout":
                icon = content.get("icon", {}).get("emoji", "💡")
                line = f"> {icon} {text}" if text else f"> {icon}"
            elif block_type == "code":
                language = content.get("language", "")
                fence = language if language else ""
                code_text = "\n".join(
                    segment.get("plain_text", "")
                    for segment in content.get("rich_text", [])
                )
                line = f"```{fence}\n{code_text}\n```"
            elif block_type == "divider":
                line = "---"
            elif block_type == "toggle":
                line = f"{indent}- {text}" if text else f"{indent}-"
            elif block_type == "child_page":
                line = f"## {content.get('title', 'Untitled Page')}"
            elif block_type == "child_database":
                line = f"## {content.get('title', 'Untitled Database')}"
            elif block_type == "image":
                image_url = _extract_file_url(content)
                if image_url:
                    line = f"![Image]({image_url})"
            elif block_type == "bookmark":
                url = content.get("url", "")
                caption = _rich_text_array_to_markdown(content.get("caption", []))
                label = caption or url
                line = f"[{label}]({url})" if url else label
            else:
                plain = block.get("plain_text") or text
                if plain:
                    line = f"{indent}{plain}"

        if line:
            lines.append(line.rstrip())

        children = block.get("children") or content.get("children")
        if children:
            child_markdown = blocks_to_markdown(
                children,
                indent_level=indent_level + (0 if block_type in {"quote", "code"} else 1),
            )
            if child_markdown:
                lines.append(child_markdown)

        if block_type != "numbered_list_item" and indent_level in numbered_counters:
            numbered_counters.pop(indent_level, None)

    return "\n".join(line for line in lines if line is not None)


def _rich_text_array_to_markdown(rich_text_array: List[Dict[str, Any]]) -> str:
    return "".join(_rich_text_to_markdown(segment) for segment in rich_text_array)


def _rich_text_to_markdown(segment: Dict[str, Any]) -> str:
    text = segment.get("plain_text", "")
    href = segment.get("href")
    annotations = segment.get("annotations", {})

    if annotations.get("code"):
        text = f"`{text}`"

    if annotations.get("bold"):
        text = f"**{text}**"
    if annotations.get("italic"):
        text = f"*{text}*"
    if annotations.get("strikethrough"):
        text = f"~~{text}~~"
    if annotations.get("underline"):
        text = f"__{text}__"

    if href:
        text = f"[{text}]({href})"

    return text


def _extract_file_url(content: Dict[str, Any]) -> Optional[str]:
    if content.get("type") == "external":
        return content.get("external", {}).get("url")
    if content.get("type") == "file":
        return content.get("file", {}).get("url")
    return None


def build_page_url(page: Dict[str, Any]) -> Optional[str]:
    page_id = page.get("id")
    if not page_id:
        return None

    base_url = "https://www.notion.so/"
    title = page.get("properties", {}).get("title")

    slug = ""
    if isinstance(title, dict):
        rich_text = title.get("title", [])
        slug = _rich_text_array_to_markdown(rich_text)

    slug = slug.strip().replace(" ", "-")
    sanitized_slug = "".join(ch for ch in slug if ch.isalnum() or ch in {"-"})
    without_hyphen = page_id.replace("-", "")
    if sanitized_slug:
        return f"{base_url}{sanitized_slug}-{without_hyphen}"
    return f"{base_url}{without_hyphen}"


async def ensure_content_storage() -> None:
    """Ensure the backing storage for content snapshots exists."""

    if not settings.has_database_credentials:
        logger.info("Database credentials missing; skipping content storage setup")
        return

    try:
        adapter = get_content_adapter()
    except ValueError:
        logger.debug("Content adapter unavailable; skipping content storage setup")
        return

    try:
        await adapter.ensure_schema()
        logger.info("Content storage schema is ready")
    except Exception as exc:
        logger.error("Failed to prepare content storage: %s", exc)
        raise


def extract_title(data: Dict[str, Any], entity_type: str) -> str:
    """Extract the best-effort title from Notion API payloads."""

    try:
        if entity_type == "page":
            properties = data.get("properties", {})
            if isinstance(properties, dict):
                for value in properties.values():
                    if not isinstance(value, dict):
                        continue
                    value_type = value.get("type")
                    if value_type == "title":
                        fragments = value.get("title") or value.get("rich_text") or []
                        return "".join(
                            fragment.get("plain_text", "")
                            for fragment in fragments
                        ).strip()

            title_field = data.get("title")
            if isinstance(title_field, list):
                return "".join(
                    fragment.get("plain_text", "") for fragment in title_field
                ).strip()
            if isinstance(title_field, str):
                return title_field.strip()

        if entity_type == "database":
            title_field = data.get("title")
            if isinstance(title_field, list):
                return "".join(
                    fragment.get("plain_text", "") for fragment in title_field
                ).strip()
            if isinstance(title_field, str):
                return title_field.strip()

        name_field = data.get("name")
        if isinstance(name_field, list):
            return "".join(
                fragment.get("plain_text", "") for fragment in name_field
            ).strip()
        if isinstance(name_field, str):
            return name_field.strip()

    except Exception as exc:
        logger.debug("Failed to extract title: %s", exc)

    return ""


async def save_entity(
    entity_id: str,
    entity_type: str,
    entity_data: Dict[str, Any],
) -> Optional[bool]:
    """Persist entity data to the configured store when possible."""

    if not settings.has_database_credentials:
        logger.debug(
            "Database credentials not configured; skipping persistence for %s %s",
            entity_type,
            entity_id,
        )
        return None

    if entity_type not in {"page", "database"}:
        logger.info("Unsupported entity type for persistence: %s", entity_type)
        return None

    markdown = entity_data.get("markdown") or ""
    url = entity_data.get("url")
    title = entity_data.get("title") or extract_title(entity_data, entity_type)

    try:
        adapter = get_content_adapter()
    except ValueError:
        logger.debug("Content adapter unavailable; skipping persistence")
        return None

    try:
        await adapter.upsert(entity_id, entity_type, url, markdown, title or "")
        logger.info("Stored content snapshot for %s %s", entity_type, entity_id)
        return True
    except Exception as exc:
        logger.error(
            "Error storing content for %s %s: %s",
            entity_type,
            entity_id,
            exc,
        )
        return False
