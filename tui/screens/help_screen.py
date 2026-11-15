"""
Modal help and keyboard shortcuts screen (`HelpScreen`)
(backend/tui/screens/help_screen.py).
"""

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class HelpScreen(ModalScreen[None]):
    """Displays all keyboard shortcuts and accessibility guidelines."""

    BINDINGS = [
        Binding("escape", "close", "Close", show=True),
        Binding("f1", "close", "Close", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-card", classes="modal-card"):
            yield Static(
                "[bold #58a6ff]❓ NAVIGATION GUIDE & KEYBOARD SHORTCUTS (F1)[/]\n\n"
                "[bold #3fb950]General Navigation:[/]\n"
                "  • [bold]Tab / Shift+Tab[/] : Move focus across tabs, cards, inputs, and buttons\n"
                "  • [bold]↑ / ↓ / ← / →[/]   : Navigate lists, data tables, and movie grids\n"
                "  • [bold]Enter / Click[/]    : Open movie card, person file, or trigger button\n"
                "  • [bold]Esc[/]             : Return to previous screen or close modal dialog\n"
                "  • [bold]Ctrl+P[/]          : Toggle poster image rendering (text mode)\n\n"
                "[bold #79c0ff]Letterboxd-style Actions:[/]\n"
                "  • [bold]Ctrl+N[/] : Log watched movie and write review\n"
                "  • [bold]Ctrl+B[/] : Create list or add movie to list\n"
                "  • [bold]Ctrl+F[/] : Like a review or follow an account\n"
                "  • [bold]Ctrl+U[/] : Switch active session user\n"
                "  • [bold]Ctrl+L[/] : Return to Login screen\n\n"
                "[bold #d2a8ff]Administration Panel (Admin):[/]\n"
                "  • [bold]F2[/]     : Show / hide Technical Requirements Inspector\n"
                "  • [bold]F3[/]     : Toggle between Admin Panel and User View\n"
                "  • [bold]Ctrl+E[/] : Execute active requirement or ad-hoc query"
            )
            yield Button("Close [Esc]", variant="primary", id="btn-close-help")

    @on(Button.Pressed, "#btn-close-help")
    def _on_close(self) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
