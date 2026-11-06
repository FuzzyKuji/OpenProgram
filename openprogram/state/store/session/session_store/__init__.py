"""SessionStore — git-backed replacement for the old ``DagSessionDB``."""
from .service import SessionStore
from .shared import (
    BrokenPredecessorChainError,
    PredecessorMissingError,
    SessionPlacementError,
    _check_append_invariant,
    _default_root,
    _node_caller,
    _node_conv_predecessor,
    default_store,
)

__all__ = [
    "SessionStore",
    "BrokenPredecessorChainError",
    "PredecessorMissingError",
    "SessionPlacementError",
    "_check_append_invariant",
    "_default_root",
    "_node_caller",
    "_node_conv_predecessor",
    "default_store",
]
