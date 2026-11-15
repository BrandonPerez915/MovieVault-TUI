"""
Base modal class with backdrop click-to-dismiss behavior (`tui/modals/base.py`).
"""

from typing import TypeVar

from textual.events import Click
from textual.screen import ModalScreen

T = TypeVar("T")


class BaseModal(ModalScreen[T]):
    """ModalScreen that dismisses when clicking on the dimmed backdrop outside its content."""

    _dismiss_value: T = None

    def on_click(self, event: Click) -> None:
        if event.widget is self:
            self.dismiss(self._dismiss_value)
