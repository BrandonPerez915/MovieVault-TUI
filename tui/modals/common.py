"""
Letterboxd-style interactive modals for MovieVault (backend/tui/modals.py).
"""

from typing import Any, Dict, List, Literal, Optional

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Click
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Label,
    ListItem,
    ListView,
    Select,
    Static,
    TextArea,
)
from textual.worker import get_current_worker

from databases.mongodb import MongoConnection
from services.ActionService import ActionService
from services.AuthService import AuthService, UserSession
from services.CatalogService import CatalogService, MovieSummary
from services.PosterService import PosterService
from services.ProfileService import ProfileService
from services.QueryService import execute_query
from tui.toast import show_error_toast, show_info_toast, show_success_toast, show_toast
from tui.widgets.loading_spinner import LoadingSpinner



class ConfirmModal(ModalScreen[bool]):
    """Generic confirmation modal returning True on Accept and False on Cancel."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(
        self,
        title: str = "Confirm Action",
        message: str = "Are you sure you want to continue?",
        confirm_label: str = "Accept",
        cancel_label: str = "Cancel [Esc]",
        confirm_variant: Literal["default", "primary", "success", "warning", "error"] = "error",
    ) -> None:
        super().__init__()
        self._title = title
        self._message = message
        self._confirm_label = confirm_label
        self._cancel_label = cancel_label
        self._confirm_variant = confirm_variant

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-modal-card", classes="modal-card"):
            yield Static(f"[bold #f85149]⚠ {self._title}[/]")
            yield Static(self._message, id="confirm-modal-message")
            with Horizontal(classes="modal-buttons"):
                yield Button(
                    self._confirm_label,
                    variant=self._confirm_variant,
                    id="btn-confirm-accept",
                )
                yield Button(
                    self._cancel_label,
                    variant="default",
                    id="btn-confirm-cancel",
                )

    def on_mount(self) -> None:
        self.query_one("#btn-confirm-cancel", Button).focus()

    @on(Button.Pressed, "#btn-confirm-accept")
    def _on_accept(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#btn-confirm-cancel")
    def _on_cancel(self) -> None:
        self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)

