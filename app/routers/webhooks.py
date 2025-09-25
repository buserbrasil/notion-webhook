import asyncio
import json
import logging
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status

from ..models.webhook import (
    NotionEventPayload,
    NotionVerificationPayload,
    NotionWebhookResponse,
)
from ..services import notion

NormalizedEvent = Tuple[Dict[str, Any], Dict[str, Any]]


def _coalesce(*values):
    for value in values:
        if value is not None:
            return value
    return None


def _extract_resource(container: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for key in ("resource", "entity", "item", "target"):
        value = container.get(key)
        if isinstance(value, dict):
            return value
    return None


def normalize_events(payload: Dict[str, Any]) -> List[NormalizedEvent]:
    """Return normalized events paired with their original source data."""

    def iter_candidates(data: Any) -> Iterable[Dict[str, Any]]:
        if isinstance(data, dict):
            # Handle common aggregations: items, events, payload
            if "items" in data and isinstance(data["items"], list):
                for item in data["items"]:
                    yield from iter_candidates(item)
            elif "events" in data and isinstance(data["events"], list):
                for item in data["events"]:
                    yield from iter_candidates(item)
            elif "payload" in data and isinstance(data["payload"], dict):
                payload_block = data["payload"]
                if isinstance(payload_block.get("events"), list):
                    for item in payload_block["events"]:
                        yield from iter_candidates(item)
                else:
                    yield payload_block
            else:
                yield data
        elif isinstance(data, list):
            for item in data:
                yield from iter_candidates(item)

    def to_event_dict(raw: Dict[str, Any]) -> Dict[str, Any]:
        event_section = raw.get("event") if isinstance(raw.get("event"), dict) else raw
        resource = _extract_resource(event_section) or _extract_resource(raw) or {}

        normalized = {
            "id": _coalesce(
                raw.get("id"),
                event_section.get("id"),
            ),
            "timestamp": _coalesce(
                raw.get("timestamp"),
                event_section.get("timestamp"),
            ),
            "workspace_id": _coalesce(
                raw.get("workspace_id"),
                event_section.get("workspace_id"),
            ),
            "event_id": _coalesce(
                raw.get("event_id"),
                event_section.get("event_id"),
                event_section.get("id"),
            ),
            "webhook_id": _coalesce(
                raw.get("webhook_id"),
                event_section.get("webhook_id"),
                raw.get("subscription_id"),
                event_section.get("subscription_id"),
            ),
            "event_type": _coalesce(
                raw.get("event_type"),
                event_section.get("event_type"),
                event_section.get("type"),
            ),
            "entity_id": _coalesce(
                raw.get("entity_id"),
                event_section.get("entity_id"),
                resource.get("id"),
            ),
            "entity_type": _coalesce(
                raw.get("entity_type"),
                event_section.get("entity_type"),
                resource.get("type"),
            ),
            "user_id": _coalesce(
                raw.get("user_id"),
                event_section.get("user_id"),
            ),
            "request_id": _coalesce(
                raw.get("request_id"),
                event_section.get("request_id"),
            ),
        }

        # Drop None values so Pydantic handles optional fields gracefully
        return {key: value for key, value in normalized.items() if value is not None}

    events: List[NormalizedEvent] = []
    for candidate in iter_candidates(payload):
        if not isinstance(candidate, dict):
            continue
        events.append((to_event_dict(candidate), candidate))

    if not events and isinstance(payload, dict):
        events.append((to_event_dict(payload), payload))

    return events


# Configure logging
logger = logging.getLogger(__name__)

# Hold strong references to in-flight tasks to prevent premature GC.
_BACKGROUND_TASKS: Set[asyncio.Task[Any]] = set()

router = APIRouter(
    prefix="/webhook",
    tags=["webhook"],
)


async def handle_notion_event(
    event: NotionEventPayload,
    raw_event: Optional[Dict[str, Any]] = None,
) -> NotionWebhookResponse:
    """
    Handle Notion webhook event.

    Args:
        event: The Notion event payload

    Returns:
        NotionWebhookResponse: Response to send back to Notion
    """
    # Log the event
    logger.info(
        f"Received Notion event: {event.event_type} for {event.entity_type} {event.entity_id}"
    )

    message = f"Event {event.event_type} received"
    entity_data: Optional[Dict[str, Any]] = None
    entity_url: Optional[str] = None

    try:
        if event.entity_type in {"page", "database"}:
            entity_data = await notion.fetch_entity_data(
                entity_id=event.entity_id,
                entity_type=event.entity_type,
                event_metadata=raw_event,
            )

            if entity_data is not None:
                logger.info(
                    "Fetched data for %s %s",
                    event.entity_type,
                    event.entity_id,
                )
                entity_url = entity_data.get("url")

    except Exception as exc:
        logger.error(
            "Unable to fetch %s %s from Notion: %s",
            event.entity_type,
            event.entity_id,
            exc,
        )

    if entity_data:
        persist_result = await notion.save_entity(
            entity_id=event.entity_id,
            entity_type=event.entity_type,
            entity_data=entity_data,
        )

        if persist_result is True:
            message_parts = ["Event", event.event_type, "received and stored"]
            if entity_url:
                message_parts.append(f"({entity_url})")
            message = " ".join(message_parts)
        elif persist_result is False:
            logger.warning(
                "Failed to persist %s %s to database",
                event.entity_type,
                event.entity_id,
            )
    elif entity_url:
        message = f"Event {event.event_type} received ({entity_url})"

    return NotionWebhookResponse(success=True, message=message)


def enqueue_event_processing(
    event: NotionEventPayload,
    raw_event: Optional[Dict[str, Any]] = None,
):
    """Schedule webhook handling without blocking the response lifecycle."""

    async def runner():
        try:
            await handle_notion_event(event, raw_event)
        except Exception as exc:  # pragma: no cover - best effort logging
            logger.error(
                "Background processing failed for %s %s: %s",
                event.entity_type,
                event.entity_id,
                exc,
            )

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(runner())
    else:
        task = loop.create_task(runner())
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)


@router.post("/notion", response_model=NotionWebhookResponse)
async def handle_notion_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Handle webhooks from Notion.

    This endpoint handles both verification requests and event notifications.
    """
    # Read the raw request body
    body = await request.body()

    # Parse the body as JSON
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        logger.error("Invalid JSON payload")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload"
        )

    # Handle verification request
    if notion.is_verification_request(payload):
        try:
            verification = NotionVerificationPayload(**payload)
        except Exception as exc:
            logger.error("Invalid verification payload: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid verification payload",
            ) from exc

        token_message = (
            f"Verification token received: {verification.verification_token}"
        )
        logger.info(token_message)
        logger.info(
            "Store the verification token securely before enabling signature validation."
        )
        return NotionWebhookResponse(
            success=True,
            message=token_message,
        )

    # Validate signature when a verification token is configured
    is_valid_signature = await notion.validate_webhook_signature(request, body)
    if not is_valid_signature:
        logger.warning("Invalid webhook signature")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature",
        )

    normalized_events = normalize_events(payload)
    messages: List[str] = []
    errors: List[str] = []

    for event_data, raw_event in normalized_events:
        try:
            event = NotionEventPayload(**event_data)
        except Exception as exc:
            serialized = json.dumps(event_data, default=str)
            logger.error(
                "Invalid event payload after normalization: %s | payload=%s",
                exc,
                serialized,
            )
            errors.append(str(exc))
            continue

        background_tasks.add_task(enqueue_event_processing, event, raw_event)
        messages.append(f"Event {event.event_type} queued")

    if not messages:
        detail = "Failed to process webhook"
        if errors:
            detail += f": {'; '.join(errors)}"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        )

    # When multiple events are batched, return all messages
    combined_message = "; ".join(messages)
    return NotionWebhookResponse(success=True, message=combined_message)
