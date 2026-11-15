"""
Dedicated Movie Reviews Screen (`ReviewsScreen`)
(backend/tui/screens/user/reviews_screen.py).

Implements review reading and keyword filtering flow (MongoDB Req 5)
with pagination of 10 reviews per page, button to write a new review,
and button to like existing reviews.
"""

import math
from typing import Any, Dict, List, Optional

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Label, Static
from textual.worker import get_current_worker

from services.ActionService import ActionService
from services.AuthService import AuthService
from services.ProfileService import ProfileService
from services.QueryService import execute_query
from tui.modals import ReviewMovieModal
from tui.widgets.person_card import populate_carousel_bar
from tui.widgets.state_message import StateMessage


class ReviewsScreen(Screen):
    """Dedicated screen to browse and filter reviews for a movie."""

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True, priority=True),
        Binding("ctrl+n", "write_review", "Write Review", show=True),
    ]

    def __init__(self, movie_title: str, initial_keywords: str = "") -> None:
        super().__init__()
        self._movie_title = (movie_title or "").strip()
        self._keywords = (initial_keywords or "").strip()
        self._page = 1
        self._total = 0
        self._rows: List[Dict[str, Any]] = []
        self._cards_per_row: int = 2

    def compose(self) -> ComposeResult:
        yield Static(
            f"[bold #58a6ff]💬 MOVIE REVIEWS[/]  ›  [bold]{self._movie_title}[/]",
            id="top-bar",
        )
        with Vertical(classes="detail-page-container"):
            with Horizontal(classes="reviews-filter-bar"):
                yield Button("◀ Back [Esc]", variant="default", id="btn-rev-back")
                yield Label("Filter by keywords:")
                yield Input(
                    placeholder="e.g. masterpiece, cinematography, ending...",
                    value=self._keywords,
                    id="inp-rev-keywords",
                )
                yield Button("🔎 Search", variant="primary", id="btn-rev-filter")
                yield Button("Write Review", variant="success", id="btn-rev-new")

            yield StateMessage(id="rev-state-msg")
            yield VerticalScroll(id="rev-cards-scroll")

            with Horizontal(classes="pagination-bar"):
                yield Button("◀ Previous", id="btn-rev-prev", classes="page-btn")
                yield Static("Page 1 of 1", id="rev-page-info", classes="page-info")
                yield Button("Next ▶", id="btn-rev-next", classes="page-btn")
        yield Footer()

    def on_mount(self) -> None:
        self._load_reviews(page=1)

    def on_resize(self, event: Resize) -> None:
        new_per_row = self._calc_review_cards_per_row()
        if new_per_row != self._cards_per_row:
            self._cards_per_row = new_per_row
            if self._rows:
                self._render_reviews(self._rows, self._total)

    def _calc_review_cards_per_row(self) -> int:
        try:
            term_width = self.app.size.width
        except Exception:
            term_width = 120
        usable_width = max(43, term_width - 8)
        return max(1, usable_width // 43)

    def _load_reviews(self, page: int = 1) -> None:
        self._page = max(1, page)
        self._keywords = self.query_one("#inp-rev-keywords", Input).value.strip()
        state = self.query_one("#rev-state-msg", StateMessage)
        state.show_loading(f"Searching reviews for '{self._movie_title}'...")
        self._fetch_reviews_worker(self._movie_title, self._keywords, self._page)

    @work(thread=True, exclusive=True)
    def _fetch_reviews_worker(self, movie_title: str, keywords: str, page: int) -> None:
        worker = get_current_worker()
        res = execute_query(
            "mongo_req_5",
            {
                "movie_title": movie_title,
                "keywords": keywords,
                "page": str(page),
            },
        )
        if not worker.is_cancelled:
            self.app.call_from_thread(self._render_reviews, res.rows, res.total_count)

    def _render_reviews(self, rows: List[Dict[str, Any]], total: int) -> None:
        self._rows = list(rows)
        self._total = max(len(rows), total)
        state = self.query_one("#rev-state-msg", StateMessage)
        scroll = self.query_one("#rev-cards-scroll", VerticalScroll)
        scroll.remove_children()

        session = AuthService().current_session
        cur_user = session.username if session else ""
        if cur_user:
            m_status = ProfileService().get_user_movie_status(
                cur_user, self._movie_title
            )
            new_btn = self.query_one("#btn-rev-new", Button)
            if m_status.get("existing_review"):
                new_btn.label = "Edit Review"
                new_btn.variant = "warning"
            else:
                new_btn.label = "Write Review"
                new_btn.variant = "success"

        if not rows:
            state.show_empty(
                f"No reviews registered for '{self._movie_title}' with that filter.",
                "Be the first to share your thoughts by pressing 'Write Review' (Ctrl+N).",
            )
        else:
            state.clear_state()
            per_row = self._calc_review_cards_per_row()
            self._cards_per_row = per_row
            cards: List[Vertical] = []

            for r in rows:
                uname = r.get("username", "anonymous")
                rating = float(r.get("rating") or 0.0)
                likes = int(r.get("likes") or 0)
                comments = int(r.get("comments_count") or 0)
                created = r.get("created_at", "")
                content = r.get("content", "")
                liked_by = {str(u).lower() for u in (r.get("_liked_by") or [])}
                user_liked = bool(cur_user and cur_user.lower() in liked_by)

                card = Vertical(
                    Horizontal(
                        Button(
                            f"@{uname}",
                            name=uname,
                            classes="review-movie-title-link btn-open-author-profile",
                        ),
                        Static(
                            f"  [bold #f0883e]★ {rating:.1f}[/]  "
                            f"[bold #3fb950]♥ {likes}[/]  [dim]💬 {comments} • {created}[/]",
                            classes="review-card-meta",
                        ),
                        classes="review-card-header",
                    ),
                    Static(content, classes="review-item-body"),
                    Horizontal(
                        Button(
                            f"Liked ({likes})" if user_liked else f"Like ({likes})",
                            variant="error" if user_liked else "default",
                            name=uname,
                            classes="btn-like-inline",
                        ),
                        classes="review-card-actions",
                    ),
                    classes="review-item-card",
                )
                cards.append(card)

            for idx in range(0, len(cards), per_row):
                row_bar = Horizontal(classes="reviews-row")
                scroll.mount(row_bar)
                populate_carousel_bar(
                    row_bar,
                    cards[idx : idx + per_row],
                    per_row,
                    empty_slot_class="carousel-review-empty-slot",
                )

        total_pages = max(1, math.ceil(self._total / 10))
        self.query_one("#rev-page-info", Static).update(
            f"[bold #79c0ff]Page {self._page} of {total_pages}[/]  [dim]({self._total} reviews)[/]"
        )
        self.query_one("#btn-rev-prev", Button).disabled = self._page <= 1
        self.query_one("#btn-rev-next", Button).disabled = self._page >= total_pages

    @on(Button.Pressed, "#btn-rev-back")
    def _on_back(self) -> None:
        self.action_go_back()

    @on(Button.Pressed, "#btn-rev-filter")
    def _on_filter(self) -> None:
        self._load_reviews(page=1)

    @on(Input.Submitted, "#inp-rev-keywords")
    def _on_input_submit(self) -> None:
        self._load_reviews(page=1)

    @on(Button.Pressed, "#btn-rev-new")
    def _on_new(self) -> None:
        self.action_write_review()

    @on(Button.Pressed, "#btn-rev-prev")
    def _on_prev(self) -> None:
        if self._page > 1:
            self._load_reviews(page=self._page - 1)

    @on(Button.Pressed, "#btn-rev-next")
    def _on_next(self) -> None:
        total_pages = max(1, math.ceil(self._total / 10))
        if self._page < total_pages:
            self._load_reviews(page=self._page + 1)

    @on(Button.Pressed, ".btn-like-inline")
    def _on_like_inline(self, event: Button.Pressed) -> None:
        review_owner = event.button.name or ""
        session = AuthService().current_session
        state = self.query_one("#rev-state-msg", StateMessage)
        if session is None:
            state.show_error("Sign in to like a review.")
            return
        ok, msg = ActionService().like_review(session, self._movie_title, review_owner)
        if ok:
            state.show_success(msg)
            self._load_reviews(page=self._page)
        else:
            state.show_error(msg)

    @on(Button.Pressed, ".btn-open-author-profile")
    def _on_open_author_profile(self, event: Button.Pressed) -> None:
        author = (event.button.name or "").strip()
        if author:
            from tui.screens.user.profile import ProfileScreen

            self.app.push_screen(ProfileScreen(author))

    def action_write_review(self) -> None:
        def _after(msg: Optional[str]) -> None:
            if msg:
                self.query_one("#rev-state-msg", StateMessage).show_success(msg)
                self._load_reviews(page=1)

        self.app.push_screen(ReviewMovieModal(movie_title=self._movie_title), _after)

    def action_go_back(self) -> None:
        self.app.pop_screen()
