import hashlib
import hmac
import json

import pytest
from fastapi import Request

from app.config import settings
from app.services import notion


class TestNotionModule:
    async def test_is_verification_request_true(self):
        """Test that a request with verification_token is identified as a verification request."""
        body = {"verification_token": "test_token"}
        result = notion.is_verification_request(body)
        assert result is True

    async def test_is_verification_request_false(self):
        """Test that a request without verification_token is not identified as a verification request."""
        body = {"event_type": "page.updated"}
        result = notion.is_verification_request(body)
        assert result is False

    async def test_validate_webhook_signature_no_token(self, mocker):
        """Validation is skipped when no verification token is configured."""
        # Create a mock request
        mock_request = mocker.AsyncMock(spec=Request)
        mock_request.headers = {}

        # Set empty token
        mocker.patch("app.services.notion.settings.NOTION_VERIFICATION_TOKEN", "")

        result = await notion.validate_webhook_signature(mock_request, b"{}")
        assert result is True

    async def test_validate_webhook_signature_no_header(self, mocker):
        """Test validation fails when no signature header is present."""
        # Create a mock request
        mock_request = mocker.AsyncMock(spec=Request)
        mock_request.headers = {}

        # Set verification token
        mocker.patch(
            "app.services.notion.settings.NOTION_VERIFICATION_TOKEN", "test_token"
        )

        result = await notion.validate_webhook_signature(mock_request, b"{}")
        assert result is False

    async def test_validate_webhook_signature_valid(self, mocker):
        """Test validation succeeds with valid signature."""
        # Create test data
        test_body = b'{"event_type":"page.updated"}'
        test_token = "test_token"

        # Calculate the expected signature
        expected_signature = f"sha256={hmac.new(test_token.encode(), test_body, hashlib.sha256).hexdigest()}"

        # Create a mock request
        mock_request = mocker.AsyncMock(spec=Request)
        mock_request.headers = {"X-Notion-Signature": expected_signature}

        # Set verification token
        mocker.patch(
            "app.services.notion.settings.NOTION_VERIFICATION_TOKEN", test_token
        )

        # Test the validation
        result = await notion.validate_webhook_signature(mock_request, test_body)
        assert result is True

    async def test_validate_webhook_signature_invalid(self, mocker):
        """Test validation fails with invalid signature."""
        # Create test data
        test_body = b'{"event_type":"page.updated"}'
        test_token = "test_token"
        invalid_signature = "sha256=invalid_signature"

        # Create a mock request
        mock_request = mocker.AsyncMock(spec=Request)
        mock_request.headers = {"X-Notion-Signature": invalid_signature}

        # Set verification token
        mocker.patch(
            "app.services.notion.settings.NOTION_VERIFICATION_TOKEN", test_token
        )

        # Test the validation
        result = await notion.validate_webhook_signature(mock_request, test_body)
        assert result is False

    def test_blocks_to_markdown_paragraph(self):
        """Convert a simple paragraph block into markdown."""
        blocks = [
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "plain_text": "Hello",
                            "annotations": {
                                "bold": True,
                                "italic": False,
                                "code": False,
                                "underline": False,
                                "strikethrough": False,
                            },
                            "href": None,
                        }
                    ]
                },
            }
        ]

        markdown = notion.blocks_to_markdown(blocks)
        assert markdown == "**Hello**"

    async def test_ensure_content_storage_invokes_adapter(self, mocker):
        """Ensure schema setup is invoked when credentials exist."""
        mock_adapter = mocker.Mock()
        mock_adapter.ensure_schema = mocker.AsyncMock()
        mocker.patch("app.services.notion.get_content_adapter", return_value=mock_adapter)

        await notion.ensure_content_storage()

        mock_adapter.ensure_schema.assert_awaited_once()

    async def test_ensure_content_storage_skips_without_credentials(self, monkeypatch, mocker):
        """Skip schema setup when credentials are missing."""
        original_host = settings.DB_HOST
        monkeypatch.setattr(settings, "DB_HOST", "")
        get_adapter = mocker.patch("app.services.notion.get_content_adapter")

        try:
            await notion.ensure_content_storage()
            get_adapter.assert_not_called()
        finally:
            monkeypatch.setattr(settings, "DB_HOST", original_host)
