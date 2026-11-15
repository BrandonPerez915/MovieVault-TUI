"""
Modal help and keyboard shortcuts screen (`HelpScreen`)
(tui/screens/help.py).
"""

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from tui.modals.base import BaseModal
from textual.widgets import Button, Static

from tui.widgets.figlet_header import FigletHeader


class HelpScreen(BaseModal[None]):
    """Displays app overview, sections, and all keyboard shortcuts."""

    BINDINGS = [
        Binding("escape", "close", "Close", show=True),
        Binding("f1", "close", "Close", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-card", classes="modal-card"):
            yield FigletHeader(
                "Help",
                font="slant",
                color="#58a6ff",
                subtitle="MovieVault Navigation Guide & Keyboard Shortcuts",
                id="help-figlet-header",
            )
            with VerticalScroll(id="help-scroll"):
                yield Static(
                    "[bold #79c0ff]App Sections:[/]\n"
                    "  • [bold]Home (1)[/]    : Popular movies grid and quick title search\n"
                    "  • [bold]Lists (2)[/]   : Create, manage, and browse your custom movie lists\n"
                    "  • [bold]Explore (3)[/] : Unified search for Movies, Activity, and Recommendations\n"
                    "  • [bold]Profile (4)[/] : Your bio, reviews, watched movies, lists, and Wrapped stats\n"
                    "  • [bold]Settings (F2)[/] : Customize color theme, poster rendering, and local cache\n\n"
                    "[bold #3fb950]Home & Quick Navigation Shortcuts:[/]\n"
                    "  • [bold]1 / 2 / 3 / 4[/]   : Jump to Home, Lists, Explore, or Profile tab\n"
                    "  • [bold]/[/]               : Focus quick movie search on Home\n"
                    "  • [bold]Tab / Shift+Tab[/] : Move focus across tabs, cards, inputs, and buttons\n"
                    "  • [bold]↑ / ↓ / ← / →[/]   : Navigate lists, data tables, and movie grids\n"
                    "  • [bold]Enter / Click[/]   : Open movie details, person page, or activate button\n"
                    "  • [bold]Esc[/]             : Return to previous screen or close modal\n\n"
                    "[bold #f0883e]Actions & Account Shortcuts:[/]\n"
                    "  • [bold]F1[/]     : Open / close this Help guide\n"
                    "  • [bold]F2[/]     : Open Settings (theme, posters, cache)\n"
                    "  • [bold]Ctrl+N[/] : Log watched movie & write a review\n"
                    "  • [bold]Ctrl+B[/] : Manage your movie lists\n"
                    "  • [bold]Ctrl+U[/] : Switch active user session\n"
                    "  • [bold]Ctrl+L[/] : Log out / return to Login screen\n"
                    "  • [bold]Ctrl+Q[/] : Quit MovieVault\n\n"
                    "[bold #d2a8ff]Admin Panel Shortcuts:[/]\n"
                    "  • [bold]F2[/]     : Show / hide Technical Requirements Inspector\n"
                    "  • [bold]F3[/]     : Toggle between Admin Panel and User View\n"
                    "  • [bold]Ctrl+E[/] : Execute active requirement or ad-hoc query",
                    id="help-body",
                )
            yield Button("Close [Esc]", variant="primary", id="btn-close-help")

    @on(Button.Pressed, "#btn-close-help")
    def _on_close(self) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
