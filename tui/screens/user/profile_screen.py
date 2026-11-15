"""
Dedicated User Profile screen (`ProfileScreen`)
(backend/tui/screens/user/profile_screen.py).

Allows inspecting any user's profile (reviews, watched movies, lists,
followers/following lists, and follow/unfollow actions).
"""

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Static

from tui.widgets.profile_view import ProfileView


class ProfileScreen(Screen):
    """Dedicated screen to view a user's Instagram-style MovieVault profile."""

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True, priority=True),
    ]

    def __init__(self, username: str) -> None:
        super().__init__()
        self._username = (username or "").strip().lstrip("@")

    def compose(self) -> ComposeResult:
        yield Static(
            f"[bold #58a6ff]👤 USER PROFILE[/]  ›  [bold]@{self._username}[/]",
            id="top-bar",
        )
        with Vertical(classes="detail-page-container"):
            with Horizontal(classes="detail-top-actions"):
                yield Button("◀ Back [Esc]", variant="default", id="btn-profile-screen-back")
            yield ProfileView(target_username=self._username, id="external-profile-view")
        yield Footer()

    @on(Button.Pressed, "#btn-profile-screen-back")
    def _on_back(self) -> None:
        self.action_go_back()

    @on(ProfileView.ProfileUpdated)
    def _on_profile_updated(self, event: ProfileView.ProfileUpdated) -> None:
        self._username = event.session.username
        self.query_one("#top-bar", Static).update(
            f"[bold #58a6ff]👤 USER PROFILE[/]  ›  [bold]@{self._username}[/]"
        )

    def action_go_back(self) -> None:
        self.app.pop_screen()
