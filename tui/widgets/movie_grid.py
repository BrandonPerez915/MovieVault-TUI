"""
Responsive and paginated movie card grid (`MovieGrid`)
(backend/tui/widgets/movie_grid.py).
"""

import math
from typing import List

from textual import on
from textual.app import ComposeResult
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Static

from services.CatalogService import MovieSummary
from tui.widgets.movie_card import MovieCard


class MovieGrid(Vertical):
    """Grid container with vertical scroll and pagination bar."""

    class PageRequested(Message):
        """Message emitted when the user requests a page change."""

        def __init__(self, grid: "MovieGrid", page: int) -> None:
            super().__init__()
            self.grid = grid
            self.page = page

        @property
        def control(self) -> "MovieGrid":
            return self.grid

    def __init__(
        self,
        page_size: int = 10,
        id: str | None = None,
        classes: str | None = None,
        scrollable: bool = True,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._page = 1
        self._page_size = max(1, page_size)
        self._total = 0
        self._movies: List[MovieSummary] = []
        self._scrollable = scrollable

    def compose(self) -> ComposeResult:
        if self._scrollable:
            with VerticalScroll(classes="movie-grid-scroll"):
                yield Grid(classes="movie-grid-inner")
        else:
            with Vertical(classes="movie-grid-container"):
                yield Grid(classes="movie-grid-inner")
        with Horizontal(classes="pagination-bar"):
            yield Button("◀ Previous", id="btn-prev-page", classes="page-btn")
            yield Static("Page 1 of 1 (0 movies)", classes="page-info")
            yield Button("Next ▶", id="btn-next-page", classes="page-btn")

    def set_movies(
        self,
        movies: List[MovieSummary],
        page: int = 1,
        total: int = 0,
        page_size: int | None = None,
    ) -> None:
        if page_size is not None:
            self._page_size = max(1, page_size)
        self._movies = list(movies)
        self._page = max(1, page)
        self._total = max(len(self._movies), total)

        grid = self.query_one(".movie-grid-inner", Grid)
        grid.remove_children()
        for m in self._movies:
            grid.mount(MovieCard(m))

        total_pages = max(1, math.ceil(self._total / self._page_size))
        info = self.query_one(".page-info", Static)
        info.update(
            f"[bold #79c0ff]Page {self._page} of {total_pages}[/]  [dim]({self._total} movies)[/]"
        )

        prev_btn = self.query_one("#btn-prev-page", Button)
        next_btn = self.query_one("#btn-next-page", Button)
        prev_btn.disabled = self._page <= 1
        next_btn.disabled = self._page >= total_pages

    def focus_first_card(self) -> None:
        cards = list(self.query(MovieCard))
        if cards:
            cards[0].focus()

    def refresh_all_posters(self) -> None:
        from tui.widgets.poster import PosterImage

        for p in self.query(PosterImage):
            p.reload_poster()

    @on(Button.Pressed, "#btn-prev-page")
    def _on_prev(self, event: Button.Pressed) -> None:
        event.stop()
        if self._page > 1:
            self.post_message(self.PageRequested(self, self._page - 1))

    @on(Button.Pressed, "#btn-next-page")
    def _on_next(self, event: Button.Pressed) -> None:
        event.stop()
        total_pages = max(1, math.ceil(self._total / self._page_size))
        if self._page < total_pages:
            self.post_message(self.PageRequested(self, self._page + 1))
