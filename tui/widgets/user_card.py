"""
Interactive user card (`UserCard`) (`tui/widgets/user_card.py`).
"""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Click
from textual.message import Message
from textual.widgets import Static

from tui.widgets.poster import PosterImage


class UserCard(Vertical, can_focus=True):
    """Focusable user card with avatar, @username, and quick stats."""

    BINDINGS = [
        Binding("enter", "select_card", "View Profile", show=True),
        Binding("space", "select_card", "View Profile", show=False),
    ]

    class Selected(Message):
        """Message emitted when the user opens the card via Enter, Space, or click."""

        def __init__(self, card: "UserCard", username: str) -> None:
            super().__init__()
            self.card = card
            self.username = username

        @property
        def control(self) -> "UserCard":
            return self.card

    def __init__(
        self,
        username: str,
        *,
        avatar_url: str = "",
        reviews_count: int = 0,
        watched_count: int = 0,
        lists_count: int = 0,
        followers_count: int = 0,
        id: str | None = None,
    ) -> None:
        super().__init__(
            id=id,
            name=username,
            classes="movie-card user-card",
        )
        self.username = username
        self.avatar_url = avatar_url
        self.reviews_count = reviews_count
        self.watched_count = watched_count
        self.lists_count = lists_count
        self.followers_count = followers_count

    def compose(self) -> ComposeResult:
        yield PosterImage(
            poster_url=self.avatar_url,
            title=self.username,
            cells_width=16,
            cells_height=10,
            size="w185",
            kind="person",
            classes="card-poster",
        )
        display_handle = f"@{self.username}"
        if len(display_handle) > 20:
            display_handle = f"{display_handle[:18]}…"
        yield Static(
            f"[bold #e6edf3]{display_handle}[/]\n"
            f"[bold #58a6ff]{self.reviews_count} rev[/] [dim]• {self.followers_count} fol[/]",
            classes="card-caption",
        )

    def action_select_card(self) -> None:
        self.post_message(self.Selected(card=self, username=self.username))

    def press(self) -> "UserCard":
        """Triggers selection programmatically."""
        self.action_select_card()
        return self

    def on_click(self, event: Click) -> None:
        event.stop()
        self.focus()
        self.action_select_card()
