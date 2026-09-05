from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

class CommitStore(ABC):
    """
    Abstract base class for CommitStore.
    """
    @abstractmethod
    def write(self, key: str, value: Any, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Write a value to the store and return the commit ID."""
        pass

    @abstractmethod
    def read(self, key: str) -> Optional[Any]:
        """Read the latest value for a key."""
        pass

    @abstractmethod
    def list_history(self, key: str) -> List[Dict[str, Any]]:
        """List the commit history for a key."""
        pass
