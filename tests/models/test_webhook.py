from datetime import datetime

import pytest
from pydantic import ValidationError

from app.models.webhook import (
    NotionEventPayload,
    NotionVerificationPayload,
    NotionWebhookResponse,
)


class TestNotionVerificationPayload:
    def test_valid_payload(self):
        """Test that a valid verification payload can be parsed."""
        data = {"verification_token": "test_token"}
        payload = NotionVerificationPayload(**data)
        assert payload.verification_token == "test_token"

    def test_missing_token(self):
        """Test that an error is raised if verification_token is missing."""
        data = {}
        with pytest.raises(ValidationError):
            NotionVerificationPayload(**data)


class TestNotionEventPayload:
    def test_valid_page_updated_payload(self, page_updated_payload):
        """Test that a valid page.updated payload can be parsed."""
        payload = NotionEventPayload(**page_updated_payload)
        assert payload.event_type == "page.updated"
        assert payload.entity_type == "page"
        assert payload.entity_id == "page-id-123"

    def test_valid_page_created_payload(self, page_created_payload):
        """Test that a valid page.created payload can be parsed."""
        payload = NotionEventPayload(**page_created_payload)
        assert payload.event_type == "page.created"
        assert payload.entity_type == "page"
        assert payload.entity_id == "page-id-123"

    def test_valid_database_updated_payload(self, database_updated_payload):
        """Test that a valid database.updated payload can be parsed."""
        payload = NotionEventPayload(**database_updated_payload)
        assert payload.event_type == "database.updated"
        assert payload.entity_type == "database"
        assert payload.entity_id == "database-id-123"

    def test_valid_comment_created_payload(self, comment_created_payload):
        """Test that a valid comment.created payload can be parsed."""
        payload = NotionEventPayload(**comment_created_payload)
        assert payload.event_type == "comment.created"
        assert payload.entity_type == "comment"
        assert payload.entity_id == "comment-id-123"

    def test_missing_required_fields(self):
        """Test that an error is raised if required fields are missing."""
        # Missing id
        data = {
            "timestamp": datetime.now().isoformat(),
            "workspace_id": "workspace-id-123",
            "event_id": "event-id-123",
            "webhook_id": "webhook-id-123",
            "event_type": "page.updated",
            "entity_id": "page-id-123",
            "entity_type": "page",
        }
        with pytest.raises(ValidationError):
            NotionEventPayload(**data)

        # Missing event_type
        data = {
            "id": "webhook-id-123",
            "timestamp": datetime.now().isoformat(),
            "workspace_id": "workspace-id-123",
            "event_id": "event-id-123",
            "webhook_id": "webhook-id-123",
            "entity_id": "page-id-123",
            "entity_type": "page",
        }
        with pytest.raises(ValidationError):
            NotionEventPayload(**data)

    def test_optional_fields(self):
        """Test that optional fields can be omitted."""
        data = {
            "id": "webhook-id-123",
            "timestamp": datetime.now().isoformat(),
            "workspace_id": "workspace-id-123",
            "event_id": "event-id-123",
            "webhook_id": "webhook-id-123",
            "event_type": "page.updated",
            "entity_id": "page-id-123",
            "entity_type": "page",
            # user_id and request_id are optional
        }
        payload = NotionEventPayload(**data)
        assert payload.user_id is None
        assert payload.request_id is None


class TestNotionWebhookResponse:
    def test_valid_response(self):
        """Test that a valid webhook response can be created."""
        data = {"success": True, "message": "Event processed successfully"}
        response = NotionWebhookResponse(**data)
        assert response.success is True
        assert response.message == "Event processed successfully"

    def test_missing_required_fields(self):
        """Test that an error is raised if required fields are missing."""
        # Missing success
        data = {"message": "Event processed successfully"}
        with pytest.raises(ValidationError):
            NotionWebhookResponse(**data)

        # Missing message
        data = {"success": True}
        with pytest.raises(ValidationError):
            NotionWebhookResponse(**data)
