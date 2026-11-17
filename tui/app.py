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
from services.AuthService import AuthService
from services.CatalogService import CatalogService
from services.PosterService import PosterService
from services.SettingsService import SettingsService
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
        settings = SettingsService()
        if settings.theme in self.available_themes:
            self.theme = settings.theme
        PosterService().set_enabled(settings.posters_enabled)

        try:
            mongo = MongoConnection()
            if mongo.initialized and mongo.database is not None:
                CatalogService().ensure_indexes(mongo.database)
        except Exception:
            pass

        if settings.remember_session and settings.last_username:
            ok, session, _ = AuthService().quick_switch_user(settings.last_username)
            if ok and session is not None:
                self.push_screen("admin" if session.is_admin else "home")
                return

        self.push_screen("auth")
