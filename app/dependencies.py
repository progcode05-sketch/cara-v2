from __future__ import annotations

from functools import lru_cache

from app.bootstrap import ServiceContainer, build_container


@lru_cache(maxsize=1)
def get_container() -> ServiceContainer:
    return build_container()
