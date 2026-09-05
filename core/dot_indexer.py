"""
core/dot_indexer.py
Hierarchical Dot-Notation Page & Node Indexer for CacheSplit v4.
Provides zero-cost O(1) addressing and dot-path navigation:
  e.g. 'nodes.us-east-1.branches.main.entities.pat_001.condition'
       'nodes.eu-west-1.branches.dev_feat.merkle_root'
       'pages.operations.nodes.us-east-1'
"""
from typing import Any, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class DotIndexer:
    """
    Hierarchical indexer enabling dot-notation navigation over the global
    node registry, branch DAGs, and operations pages.
    """

    def __init__(self, cluster_context: Optional[Dict[str, Any]] = None):
        self._context = cluster_context or {}

    def update_context(self, key: str, value: Any):
        self._context[key] = value

    def resolve(self, path: str, default: Any = None) -> Any:
        """
        Resolve a dot-delimited path into the cluster context.
        Example:
            resolve("nodes.us-east-1.branches.main.entities.pat_001.data.condition")
        """
        if not path:
            return self._context

        tokens = path.strip(".").split(".")
        current = self._context

        for token in tokens:
            if isinstance(current, dict):
                if token in current:
                    current = current[token]
                else:
                    return default
            elif hasattr(current, token):
                current = getattr(current, token)
            elif isinstance(current, (list, tuple)) and token.isdigit():
                idx = int(token)
                if 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return default
            else:
                return default

        return current

    def set_path(self, path: str, value: Any):
        """Set a value at a hierarchical dot-notation path."""
        tokens = path.strip(".").split(".")
        current = self._context
        for token in tokens[:-1]:
            if token not in current or not isinstance(current[token], dict):
                current[token] = {}
            current = current[token]
        current[tokens[-1]] = value

    def snapshot(self) -> Dict[str, Any]:
        return self._context


dot_indexer = DotIndexer()
