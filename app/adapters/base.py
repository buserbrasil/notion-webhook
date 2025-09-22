from abc import ABC, abstractmethod
from typing import Any, Dict, Generic, List, Optional, TypeVar

T = TypeVar("T")


class BaseAdapter(Generic[T], ABC):
    """Base adapter interface for data persistence."""

    @abstractmethod
    async def save(self, data: T) -> T:
        """Save data to storage."""
        pass

    @abstractmethod
    async def get(self, id: str) -> Optional[T]:
        """Retrieve data by ID."""
        pass

    @abstractmethod
    async def list(self, filters: Optional[Dict[str, Any]] = None) -> List[T]:
        """List data with optional filters."""
        pass

    @abstractmethod
    async def update(self, id: str, data: Dict[str, Any]) -> Optional[T]:
        """Update data by ID."""
        pass

    @abstractmethod
    async def delete(self, id: str) -> bool:
        """Delete data by ID."""
        pass

    @abstractmethod
    async def connect(self) -> None:
        """Connect to the data store."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the data store."""
        pass
