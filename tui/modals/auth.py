"""
Letterboxd-style interactive modals for MovieVault (backend/tui/modals.py).
"""

from typing import List, Optional

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Click
from tui.modals.base import BaseModal
from textual.widgets import (
    Button,
    Label,
    ListItem,
    ListView,
    Static,
)

from services.AuthService import AuthService, UserSession



class UserSwitchModal(BaseModal[Optional[UserSession]]):
    """Modal to quickly switch between registered users."""

    BINDINGS = [
        Binding("escape", "cancel", "Close", show=True),
    ]

    def compose(self) -> ComposeResult:
        auth = AuthService()
        registered_users = auth.list_demo_users()
        current = auth.current_session

        with Vertical(id="switch-card", classes="modal-card"):
            yield Static(
                "[bold #d2a8ff]⇄ QUICK USER SWITCH (Ctrl+U)[/]\n"
                "[dim]Select an account with ↑/↓ and press Enter:[/]"
            )
            items: List[ListItem] = []
            for u in registered_users:
                uname = u["username"]
                marker = " ★ [ACTIVE]" if (current and current.username == uname) else ""
                label = (
                    f"@{uname}{marker} "
                    f"[dim]({u.get('email', '')} • {u.get('lists_count', 0)} lists)[/]"
                )
                items.append(ListItem(Label(label), name=uname))

            if not items:
                yield Static(
                    "\n[bold #f0883e]∅ No registered users available.[/]"
                )
            yield ListView(*items, id="switch-user-list")
            yield Static("\n[dim]Enter: Switch account  │  Esc: Close[/]")

    def on_mount(self) -> None:
        self.query_one("#switch-user-list", ListView).focus()

    @on(ListView.Selected, "#switch-user-list")
    def on_user_selected(self, event: ListView.Selected) -> None:
        username = event.item.name
        if username:
            ok, session, _ = AuthService().quick_switch_user(username)
            if ok:
                self.dismiss(session)
                return
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)



class UserMenuModal(BaseModal[Optional[str]]):
    """Compact dropdown submenu opened when clicking the @username header button."""

    BINDINGS = [
        Binding("escape", "cancel", "Close", show=True),
    ]

    def __init__(self, session: Optional[UserSession]) -> None:
        super().__init__()
        self._session = session

    def compose(self) -> ComposeResult:
        uname = f"@{self._session.username}" if self._session else "Explorer Mode"
        logout_label = "🚪 Log Out" if self._session else "🔑 Sign In"
        with Vertical(id="user-menu-card"):
            with Horizontal(id="user-menu-header"):
                yield Static(f"[bold #79c0ff]{uname}[/]", id="user-menu-title")
                yield Button("✕", id="btn-close-user-menu")
            yield Button("👤 View Profile", id="menu-act-profile", classes="user-menu-item")
            yield Button("⚙️ Settings", id="menu-act-settings", classes="user-menu-item")
            yield Button("❓ Help", id="menu-act-help", classes="user-menu-item")
            yield Button(logout_label, variant="error", id="menu-act-logout", classes="user-menu-item")

    @on(Button.Pressed, "#btn-close-user-menu")
    def _on_close(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#menu-act-profile")
    def _on_profile(self) -> None:
        self.dismiss("profile")

    @on(Button.Pressed, "#menu-act-settings")
    def _on_settings(self) -> None:
        self.dismiss("settings")

    @on(Button.Pressed, "#menu-act-help")
    def _on_help(self) -> None:
        self.dismiss("help")

    @on(Button.Pressed, "#menu-act-logout")
    def _on_logout(self) -> None:
        self.dismiss("logout")

    def on_click(self, event: Click) -> None:
        card = self.query_one("#user-menu-card")
        if not card.region.contains(event.screen_x, event.screen_y):
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

