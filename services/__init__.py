"""
Services package for MovieVault.
"""
from typing import Any

__all__ = [
    "ActionService",
    "AuthService",
    "UserSession",
    "CatalogService",
    "PosterService",
    "ProfileService",
    "TMDBService",
]


def __getattr__(name: str) -> Any:
    if name == "ActionService":
        from services.ActionService import ActionService
        return ActionService
    if name in ("AuthService", "UserSession"):
        from services import AuthService as _auth
        return getattr(_auth, name)
    if name == "CatalogService":
        from services.CatalogService import CatalogService
        return CatalogService
    if name == "PosterService":
        from services.PosterService import PosterService
        return PosterService
    if name == "ProfileService":
        from services.ProfileService import ProfileService
        return ProfileService
    if name == "TMDBService":
        from services.TMDBService import TMDBService
        return TMDBService
    raise AttributeError(f"module 'services' has no attribute {name!r}")
