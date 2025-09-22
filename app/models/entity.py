from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, ConfigDict


class NotionEntity(BaseModel):
    """Base model for Notion entities that will be saved in the database."""

    id: str
    entity_type: str
    entity_data: Dict[str, Any]
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(from_attributes=True)


class NotionPage(NotionEntity):
    """Model for Notion pages."""

    title: Optional[str] = None
    url: Optional[str] = None
    parent_id: Optional[str] = None

    @classmethod
    def from_api_response(
        cls, entity_id: str, api_data: Dict[str, Any]
    ) -> "NotionPage":
        """Create a NotionPage from the Notion API response."""
        # Extract title if available
        title = None
        if "properties" in api_data and "title" in api_data["properties"]:
            title_obj = api_data["properties"]["title"]
            if title_obj and "title" in title_obj and title_obj["title"]:
                title = "".join(
                    [text_obj.get("plain_text", "") for text_obj in title_obj["title"]]
                )

        # Extract URL
        url = api_data.get("url")

        # Extract parent ID
        parent_id = None
        if "parent" in api_data:
            parent = api_data["parent"]
            if "page_id" in parent:
                parent_id = parent["page_id"]
            elif "database_id" in parent:
                parent_id = parent["database_id"]

        return cls(
            id=entity_id,
            entity_type="page",
            entity_data=api_data,
            title=title,
            url=url,
            parent_id=parent_id,
        )


class NotionDatabase(NotionEntity):
    """Model for Notion databases."""

    title: Optional[str] = None
    url: Optional[str] = None

    @classmethod
    def from_api_response(
        cls, entity_id: str, api_data: Dict[str, Any]
    ) -> "NotionDatabase":
        """Create a NotionDatabase from the Notion API response."""
        # Extract title if available
        title = None
        if "title" in api_data and api_data["title"]:
            title = "".join(
                [text_obj.get("plain_text", "") for text_obj in api_data["title"]]
            )

        # Extract URL
        url = api_data.get("url")

        return cls(
            id=entity_id,
            entity_type="database",
            entity_data=api_data,
            title=title,
            url=url,
        )
