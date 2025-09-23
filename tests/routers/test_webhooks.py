from unittest.mock import patch

from fastapi import status

from app.routers.webhooks import normalize_events


class TestNormalizeEvents:
    def test_normalize_single_event(self):
        payload = {
            "id": "evt-1",
            "timestamp": "2024-01-01T00:00:00Z",
            "workspace_id": "ws-1",
            "webhook_id": "wh-1",
            "event_type": "page.updated",
            "entity_id": "page-1",
            "entity_type": "page",
        }

        normalized = normalize_events(payload)
        assert len(normalized) == 1
        normalized_event, raw = normalized[0]
        assert normalized_event["entity_id"] == "page-1"
        assert raw is payload

    def test_normalize_nested_events(self):
        payload = {
            "events": [
                {
                    "event": {
                        "id": "evt-2",
                        "timestamp": "2024-01-02T00:00:00Z",
                        "workspace_id": "ws-2",
                        "webhook_id": "wh-2",
                        "type": "database.updated",
                        "entity": {"id": "db-1", "type": "database"},
                    }
                }
            ]
        }

        normalized = normalize_events(payload)
        assert len(normalized) == 1
        normalized_event, _ = normalized[0]
        assert normalized_event["event_type"] == "database.updated"
        assert normalized_event["entity_type"] == "database"
        assert normalized_event["entity_id"] == "db-1"

    def test_normalize_items_with_payload_block(self):
        payload = {
            "items": [
                {
                    "payload": {
                        "events": [
                            {
                                "event": {
                                    "id": "evt-3",
                                    "timestamp": "2024-01-03T00:00:00Z",
                                    "workspace_id": "ws-3",
                                    "subscription_id": "sub-1",
                                    "event_type": "page.created",
                                    "resource": {"id": "page-3", "type": "page"},
                                }
                            }
                        ]
                    }
                }
            ]
        }

        normalized = normalize_events(payload)
        assert len(normalized) == 1
        normalized_event, _ = normalized[0]
        assert normalized_event["webhook_id"] == "sub-1"
        assert normalized_event["event_type"] == "page.created"
        assert normalized_event["entity_id"] == "page-3"


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
        with patch("app.services.notion.is_verification_request", return_value=False):
            with patch(
                "app.services.notion.validate_webhook_signature", return_value=False
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
        with patch("app.services.notion.is_verification_request", return_value=False):
            with patch(
                "app.services.notion.validate_webhook_signature", return_value=True
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
        with patch("app.services.notion.is_verification_request", return_value=False):
            with patch(
                "app.services.notion.validate_webhook_signature", return_value=True
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
        with patch("app.services.notion.is_verification_request", return_value=False):
            with patch(
                "app.services.notion.validate_webhook_signature", return_value=True
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
        with patch("app.services.notion.is_verification_request", return_value=False):
            with patch(
                "app.services.notion.validate_webhook_signature", return_value=True
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
        with patch("app.services.notion.is_verification_request", return_value=False):
            with patch(
                "app.services.notion.validate_webhook_signature", return_value=True
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
