"""
Main Textual Application for MovieVault (backend/tui/app.py).

Orchestrates the main application screens:
- `auth` (`AuthScreen`): Login, registration, and mode selector.
- `home` / `user` (`HomeScreen`): Letterboxd-style user experience with
  terminal posters, dedicated pages for movies, actors/directors, and reviews.
- `admin` (`AdminScreen`): Technical panel with inspector for all 24 requirements,
  interactive ad-hoc console, and recursive catalog population from TMDB.
"""

from pathlib import Path

from textual.app import App
from textual.binding import Binding

from databases.mongodb import MongoConnection
from services.CatalogService import CatalogService
from tui.screens.admin import AdminScreen
from tui.screens.auth import AuthScreen
from tui.screens.user.home import HomeScreen


class MovieVaultApp(App):
    """MovieVault Interactive Terminal Application (User View + Admin Panel)."""

    TITLE = "MovieVault — Film & Reviews Platform"
    CSS_PATH = str(Path(__file__).resolve().parent / "styles.tcss")
    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
    ]
    SCREENS = {
        "auth": AuthScreen,
        "home": HomeScreen,
        "user": HomeScreen,
        "admin": AdminScreen,
    }

    def on_mount(self) -> None:
        try:
            mongo = MongoConnection()
            if mongo.initialized and mongo.database is not None:
                CatalogService().ensure_indexes(mongo.database)
        except Exception:
            pass
        self.push_screen("auth")
