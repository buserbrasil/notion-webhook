from typing import Dict, Any, Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime

class NotionVerificationPayload(BaseModel):
    """Model for Notion webhook verification payload."""
    verification_token: str

class NotionEventPayload(BaseModel):
    """Model for Notion webhook event payload."""
    id: str
    timestamp: datetime
    workspace_id: str
    event_id: str
    webhook_id: str
    event_type: str = Field(..., description="Type of event: page.updated, etc.")
    entity_id: str
    entity_type: str
    user_id: Optional[str] = None
    request_id: Optional[str] = None

class NotionWebhookResponse(BaseModel):
    """Model for response to Notion webhook."""
    success: bool
    message: str