"""
Reusable animated terminal spinner / loader widget (`LoadingSpinner`)
(tui/widgets/loading_spinner.py).
"""

from typing import Optional

from textual.timer import Timer
from textual.widgets import Static

SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


class LoadingSpinner(Static):
    """Animated Braille spinner widget for background loading operations."""

    def __init__(
        self,
        renderable: str = "",
        *,
        auto_start: bool = False,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(
            renderable,
            name=name,
            id=id,
            classes=classes,
            disabled=disabled,
        )
        self._loading_text: str = str(renderable) if renderable else "Loading..."
        self._frame_index: int = 0
        self._is_spinning: bool = auto_start
        self._timer: Optional[Timer] = None

    def on_mount(self) -> None:
        self._timer = self.set_interval(
            0.08,
            self._tick_spinner,
            pause=not self._is_spinning,
        )
        if self._is_spinning:
            self._render_spinner_frame()

    def _tick_spinner(self) -> None:
        if not self._is_spinning:
            return
        self._frame_index = (self._frame_index + 1) % len(SPINNER_FRAMES)
        self._render_spinner_frame()

    def _render_spinner_frame(self) -> None:
        frame = SPINNER_FRAMES[self._frame_index]
        self.update(f"[bold #58a6ff]{frame} LOADING:[/] {self._loading_text}")

    def start_spinner(self, text: str = "Loading...") -> None:
        """Starts the spinner animation and displays the widget."""
        self._loading_text = text
        self._frame_index = 0
        self._is_spinning = True
        self.add_class("loading-state")
        self.display = True
        self._render_spinner_frame()
        if self._timer is not None:
            self._timer.resume()

    def set_spinner_text(self, text: str) -> None:
        """Updates the text of an active spinner without resetting its frame."""
        self._loading_text = text
        if not self._is_spinning:
            self.start_spinner(text)
        else:
            self._render_spinner_frame()

    def stop_spinner(self, hide: bool = True) -> None:
        """Stops the spinner animation and optionally hides the widget."""
        self._is_spinning = False
        self.remove_class("loading-state")
        if self._timer is not None:
            self._timer.pause()
        if hide:
            self.display = False
            self.update("")
