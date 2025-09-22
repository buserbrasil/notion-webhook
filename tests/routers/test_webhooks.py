import json
from unittest.mock import patch

import pytest
from fastapi import HTTPException, status

from app.services.notion import NotionService


class TestWebhookRouter:
    def test_handle_notion_webhook_invalid_json(self, client):
        """Test that the endpoint handles invalid JSON properly."""
        response = client.post(
            "/webhook/notion",
            content="invalid json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid JSON payload" in response.json()["detail"]

    def test_handle_verification_request(self, client, verification_payload):
        """Test that the endpoint handles verification requests properly."""
        response = client.post(
            "/webhook/notion",
            json=verification_payload,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert data["message"].startswith("Verification token received: ")
        assert data["message"].endswith(verification_payload["verification_token"])

    def test_handle_verification_request_invalid(self, client):
        """Test that the endpoint handles invalid verification requests properly."""
        response = client.post(
            "/webhook/notion",
            json={"verification_token": None},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid verification payload" in response.json()["detail"]

    def test_handle_webhook_invalid_signature(self, client, page_updated_payload):
        """Test that the endpoint handles invalid signatures properly."""
        with patch.object(NotionService, "is_verification_request", return_value=False):
            with patch.object(
                NotionService, "validate_webhook_signature", return_value=False
            ):
                response = client.post(
                    "/webhook/notion",
                    json=page_updated_payload,
                    headers={
                        "Content-Type": "application/json",
                        "x-notion-signature": "invalid_signature",
                    },
                )
                assert response.status_code == status.HTTP_401_UNAUTHORIZED
                assert "Invalid signature" in response.json()["detail"]

    def test_handle_page_updated_event(self, client, page_updated_payload):
        """Test that the endpoint handles page.updated events properly."""
        with patch.object(NotionService, "is_verification_request", return_value=False):
            with patch.object(
                NotionService, "validate_webhook_signature", return_value=True
            ):
                response = client.post(
                    "/webhook/notion",
                    json=page_updated_payload,
                    headers={
                        "Content-Type": "application/json",
                        "x-notion-signature": "valid_signature",
                    },
                )
                assert response.status_code == status.HTTP_200_OK
                data = response.json()
                assert data["success"] is True
                assert "page.updated" in data["message"]

    def test_handle_page_created_event(self, client, page_created_payload):
        """Test that the endpoint handles page.created events properly."""
        with patch.object(NotionService, "is_verification_request", return_value=False):
            with patch.object(
                NotionService, "validate_webhook_signature", return_value=True
            ):
                response = client.post(
                    "/webhook/notion",
                    json=page_created_payload,
                    headers={
                        "Content-Type": "application/json",
                        "x-notion-signature": "valid_signature",
                    },
                )
                assert response.status_code == status.HTTP_200_OK
                data = response.json()
                assert data["success"] is True
                assert "page.created" in data["message"]

    def test_handle_database_updated_event(self, client, database_updated_payload):
        """Test that the endpoint handles database.updated events properly."""
        with patch.object(NotionService, "is_verification_request", return_value=False):
            with patch.object(
                NotionService, "validate_webhook_signature", return_value=True
            ):
                response = client.post(
                    "/webhook/notion",
                    json=database_updated_payload,
                    headers={
                        "Content-Type": "application/json",
                        "x-notion-signature": "valid_signature",
                    },
                )
                assert response.status_code == status.HTTP_200_OK
                data = response.json()
                assert data["success"] is True
                assert "database.updated" in data["message"]

    def test_handle_comment_created_event(self, client, comment_created_payload):
        """Test that the endpoint handles comment.created events properly."""
        with patch.object(NotionService, "is_verification_request", return_value=False):
            with patch.object(
                NotionService, "validate_webhook_signature", return_value=True
            ):
                response = client.post(
                    "/webhook/notion",
                    json=comment_created_payload,
                    headers={
                        "Content-Type": "application/json",
                        "x-notion-signature": "valid_signature",
                    },
                )
                assert response.status_code == status.HTTP_200_OK
                data = response.json()
                assert data["success"] is True
                assert "comment.created" in data["message"]

    def test_handle_invalid_event_payload(self, client):
        """Test that the endpoint handles invalid event payloads properly."""
        with patch.object(NotionService, "is_verification_request", return_value=False):
            with patch.object(
                NotionService, "validate_webhook_signature", return_value=True
            ):
                # Missing required fields
                invalid_payload = {
                    "event_type": "page.updated",
                    # Missing other required fields
                }
                response = client.post(
                    "/webhook/notion",
                    json=invalid_payload,
                    headers={
                        "Content-Type": "application/json",
                        "x-notion-signature": "valid_signature",
                    },
                )
                assert response.status_code == status.HTTP_400_BAD_REQUEST
                assert "Failed to process webhook" in response.json()["detail"]
