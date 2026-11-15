"""
Letterboxd-style interactive movie card (`MovieCard`)
(backend/tui/widgets/movie_card.py).
"""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Click
from textual.message import Message
from textual.widgets import Static

from services.CatalogService import MovieSummary
from tui.widgets.poster import PosterImage


class MovieCard(Vertical, can_focus=True):
    """Focusable card with poster, title, year, and rating."""

    BINDINGS = [
        Binding("enter", "select_card", "View Details", show=True),
        Binding("space", "select_card", "View Details", show=False),
    ]

    class Selected(Message):
        """Message emitted when the user opens the card with Enter or click."""

        def __init__(self, card: "MovieCard", movie_id: str, title: str) -> None:
            super().__init__()
            self.card = card
            self.movie_id = movie_id
            self.title = title

        @property
        def control(self) -> "MovieCard":
            return self.card

    def __init__(self, movie: MovieSummary, id: str | None = None) -> None:
        super().__init__(id=id, classes="movie-card")
        self.movie = movie

    def compose(self) -> ComposeResult:
        yield PosterImage(
            poster_url=self.movie.poster_url,
            title=self.movie.title,
            cells_width=16,
            cells_height=10,
            size="w185",
            classes="card-poster",
        )
        short_title = (
            self.movie.title
            if len(self.movie.title) <= 20
            else f"{self.movie.title[:18]}…"
        )
        year_str = str(self.movie.release_year) if self.movie.release_year else "—"
        rating_str = f"★ {self.movie.rating:.1f}" if self.movie.rating else "★ —"
        yield Static(
            f"[bold #e6edf3]{short_title}[/]\n"
            f"[dim]{year_str}[/]  [bold #f0883e]{rating_str}[/]",
            classes="card-caption",
        )

    def action_select_card(self) -> None:
        self.post_message(
            self.Selected(
                card=self,
                movie_id=self.movie.movie_id or self.movie.title,
                title=self.movie.title,
            )
        )

    def on_click(self, event: Click) -> None:
        event.stop()
        self.focus()
        self.action_select_card()
