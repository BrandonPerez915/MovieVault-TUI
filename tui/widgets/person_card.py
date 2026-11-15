"""
Letterboxd-style interactive actor/director card (`PersonCard`)
(backend/tui/widgets/person_card.py).
"""

from typing import Literal, Sequence

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Click
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from tui.widgets.poster import PosterImage


def populate_carousel_bar(
    bar: Horizontal,
    cards: Sequence[Widget],
    per_row: int,
    empty_slot_class: str = "carousel-empty-slot",
) -> None:
    """
    Mounts up to `per_row` fixed-width cards inside `bar` (`width: 1fr`),
    interleaved with `1fr` spacers and empty slots so cards are evenly distributed
    across 100% of the available width while keeping `<` and `>` at the outer edges.
    """
    bar.remove_children()
    bar.mount(Static("", classes="carousel-spacer"))
    for i in range(max(1, per_row)):
        if i < len(cards):
            bar.mount(cards[i])
        else:
            bar.mount(Static("", classes=empty_slot_class))
        bar.mount(Static("", classes="carousel-spacer"))


class PersonCard(Vertical, can_focus=True):
    """Focusable card with profile image (`PosterImage`), name, and role/character."""

    BINDINGS = [
        Binding("enter", "select_card", "View Details", show=True),
        Binding("space", "select_card", "View Details", show=False),
    ]

    class Selected(Message):
        """Message emitted when the user opens the person card with Enter or click."""

        def __init__(
            self,
            card: "PersonCard",
            person_id: str,
            person_name: str,
            kind: Literal["actor", "director"],
        ) -> None:
            super().__init__()
            self.card = card
            self.person_id = person_id
            self.person_name = person_name
            self.kind: Literal["actor", "director"] = kind

        @property
        def control(self) -> "PersonCard":
            return self.card

    def __init__(
        self,
        person_id: str,
        person_name: str,
        kind: Literal["actor", "director"],
        poster_url: str = "",
        character: str = "",
        id: str | None = None,
    ) -> None:
        super().__init__(
            id=id,
            name=f"{kind}|{person_id or person_name}|{person_name}",
            classes="movie-card person-card person-chip-btn",
        )
        self.person_id = person_id
        self.person_name = person_name
        self.kind: Literal["actor", "director"] = kind
        self.poster_url = poster_url
        self.character = character

    def compose(self) -> ComposeResult:
        yield PosterImage(
            poster_url=self.poster_url,
            title=self.person_name,
            cells_width=16,
            cells_height=10,
            size="w185",
            classes="card-poster",
        )
        short_name = (
            self.person_name
            if len(self.person_name) <= 20
            else f"{self.person_name[:18]}…"
        )
        if self.kind == "director":
            subtitle_str = "[bold #58a6ff]🎬 Director[/]"
        else:
            raw_role = (self.character or "Actor").strip()
            short_role = raw_role if len(raw_role) <= 18 else f"{raw_role[:16]}…"
            subtitle_str = f"[dim]🎭 {short_role}[/]"

        yield Static(
            f"[bold #e6edf3]{short_name}[/]\n{subtitle_str}",
            classes="card-caption",
        )

    def action_select_card(self) -> None:
        self.post_message(
            self.Selected(
                card=self,
                person_id=self.person_id or self.person_name,
                person_name=self.person_name,
                kind=self.kind,
            )
        )

    def press(self) -> "PersonCard":
        """Triggers selection programmatically (compatible with Button-style tests)."""
        self.action_select_card()
        return self

    def on_click(self, event: Click) -> None:
        event.stop()
        self.focus()
        self.action_select_card()
