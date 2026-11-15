"""
Letterboxd-style interactive modals for MovieVault (backend/tui/modals.py).
"""

from typing import Literal

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from tui.modals.base import BaseModal
from textual.widgets import (
    Button,
    Static,
)



class ConfirmModal(BaseModal[bool]):
    """Generic confirmation modal returning True on Accept and False on Cancel."""

    _dismiss_value = False

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

