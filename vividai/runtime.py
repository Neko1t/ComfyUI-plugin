from __future__ import annotations

import os
from pathlib import Path

from .service import Service
from .storage import Store

_store = None
_service = None


def store() -> Store:
    global _store
    if _store is None:
        import folder_paths

        root = os.environ.get("VIVIDAI_DATA_DIR") or folder_paths.get_system_user_directory(
            "vividai"
        )
        _store = Store(Path(root))
    return _store


def service() -> Service:
    global _service
    if _service is None:
        _service = Service(store())
    return _service
