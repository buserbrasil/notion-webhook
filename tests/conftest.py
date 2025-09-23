from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


@pytest.fixture
def test_app():
    """Return a FastAPI test application."""
    return app


@pytest.fixture
def client(test_app):
    """Return a TestClient instance for testing API endpoints."""
    return TestClient(test_app)


@pytest.fixture
def mock_settings(monkeypatch):
    """Mock application settings."""
    monkeypatch.setattr(
        settings, "NOTION_VERIFICATION_TOKEN", "test_verification_token"
    )
    monkeypatch.setattr(settings, "NOTION_API_KEY", "test_api_key")
    monkeypatch.setattr(
        settings, "WEBHOOK_URL", "https://test.example.com/webhook/notion"
    )
    return settings


@pytest.fixture
def verification_payload():
    """Return a verification request payload."""
    return {"verification_token": "test_verification_token"}


@pytest.fixture
def page_updated_payload():
    """Return a page.updated event payload."""
    return {
        "id": "webhook-id-123",
        "timestamp": datetime.now().isoformat(),
        "workspace_id": "workspace-id-123",
        "event_id": "event-id-123",
        "webhook_id": "webhook-id-123",
        "event_type": "page.updated",
        "entity_id": "page-id-123",
        "entity_type": "page",
        "user_id": "user-id-123",
        "request_id": "request-id-123",
    }


@pytest.fixture
def page_created_payload():
    """Return a page.created event payload."""
    return {
        "id": "webhook-id-123",
        "timestamp": datetime.now().isoformat(),
        "workspace_id": "workspace-id-123",
        "event_id": "event-id-123",
        "webhook_id": "webhook-id-123",
        "event_type": "page.created",
        "entity_id": "page-id-123",
        "entity_type": "page",
        "user_id": "user-id-123",
        "request_id": "request-id-123",
    }


@pytest.fixture
def database_updated_payload():
    """Return a database.updated event payload."""
    return {
        "id": "webhook-id-123",
        "timestamp": datetime.now().isoformat(),
        "workspace_id": "workspace-id-123",
        "event_id": "event-id-123",
        "webhook_id": "webhook-id-123",
        "event_type": "database.updated",
        "entity_id": "database-id-123",
        "entity_type": "database",
        "user_id": "user-id-123",
        "request_id": "request-id-123",
    }


@pytest.fixture
def comment_created_payload():
    """Return a comment.created event payload."""
    return {
        "id": "webhook-id-123",
        "timestamp": datetime.now().isoformat(),
        "workspace_id": "workspace-id-123",
        "event_id": "event-id-123",
        "webhook_id": "webhook-id-123",
        "event_type": "comment.created",
        "entity_id": "comment-id-123",
        "entity_type": "comment",
        "user_id": "user-id-123",
        "request_id": "request-id-123",
    }


@pytest.fixture
def valid_signature_header():
    """Return a valid signature header for testing."""
    return "sha256=some_valid_signature"


@pytest.fixture
def invalid_signature_header():
    """Return an invalid signature header for testing."""
    return "sha256=invalid_signature"
