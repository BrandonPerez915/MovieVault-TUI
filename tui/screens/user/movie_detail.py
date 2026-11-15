"""
Dedicated Movie Details Screen (`MovieDetailScreen`)
(backend/tui/screens/user/movie_detail_screen.py).

When clicking or pressing `Enter` on any movie in the catalog,
search results, filmography, or recommendations, this screen opens
with a large poster, complete metadata, synopsis, interactive director
and cast buttons (opening `PersonScreen`), featured reviews, and
quick Letterboxd-style actions (Watch, Like, Review/Edit Review, Add to List).
"""

from typing import Any, Dict, List, Optional

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.screen import Screen
from textual.widgets import Button, Footer, Static
from textual.worker import get_current_worker

from databases.mongodb import MongoConnection
from services.ActionService import ActionService
from services.AuthService import AuthService
from services.CatalogService import CatalogService, MovieDetail
from services.ProfileService import ProfileService
from services.QueryService import execute_query
from tui.modals import ManageListModal, ReviewMovieModal
from tui.screens.user.person import PersonScreen
from tui.screens.user.reviews import ReviewsScreen
from tui.toast import show_success_toast
from tui.widgets.person_card import PersonCard, populate_carousel_bar
from tui.widgets.poster import PosterImage
from tui.widgets.state_message import StateMessage


class MovieDetailScreen(Screen):
    """Complete Letterboxd-style movie details screen."""

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True, priority=True),
        Binding("ctrl+n", "open_review", "Review", show=True),
        Binding("ctrl+b", "open_list", "Add to List", show=True),
    ]

    def __init__(self, movie_id_or_title: str) -> None:
        super().__init__()
        self._movie_key = (movie_id_or_title or "").strip()
        self._detail: Optional[MovieDetail] = None
        self._top_reviews: List[Dict[str, Any]] = []
        self._dir_offset: int = 0
        self._cast_offset: int = 0
        self._rev_offset: int = 0
        self._cards_per_row: int = 3
        self._rev_cards_per_row: int = 2

    def compose(self) -> ComposeResult:
        yield Static(
            f"[bold #58a6ff]🎬 MOVIE DETAILS[/]  ›  [bold]{self._movie_key}[/]",
            id="top-bar",
        )
        with VerticalScroll(classes="detail-page-scroll"):
            with Horizontal(classes="detail-top-actions"):
                yield Button("◀ Back [Esc]", variant="default", id="btn-detail-back")

            yield StateMessage(id="detail-state-msg")

            with Vertical(id="movie-hero-box"):
                with Horizontal(id="movie-hero-content"):
                    yield PosterImage(
                        poster_url="",
                        title=self._movie_key,
                        cells_width=24,
                        cells_height=16,
                        size="w342",
                        id="detail-poster",
                    )
                    with Vertical(id="movie-meta-box"):
                        yield Static("", id="detail-title-banner")
                        yield Static("", id="detail-specs-text")
                        yield Static("", id="detail-synopsis-text")

                with Horizontal(id="movie-hero-actions", classes="detail-section-actions"):
                    yield Button("Like (0)", variant="default", id="btn-detail-like")
                    yield Button("Mark as Watched", variant="default", id="btn-detail-watched")
                    yield Button("＋ Add to List", variant="primary", id="btn-detail-list")

            yield Static(
                "DIRECTORS (Click to view details):",
                classes="panel-heading",
            )
            with Horizontal(classes="carousel-row"):
                yield Button("<", id="btn-dir-prev", classes="carousel-nav-btn")
                yield Horizontal(id="detail-directors-bar", classes="chips-bar")
                yield Button(">", id="btn-dir-next", classes="carousel-nav-btn")

            yield Static(
                "MAIN CAST (Click to view details):",
                classes="panel-heading",
            )
            with Horizontal(classes="carousel-row"):
                yield Button("<", id="btn-cast-prev", classes="carousel-nav-btn")
                yield Horizontal(id="detail-cast-bar", classes="chips-bar")
                yield Button(">", id="btn-cast-next", classes="carousel-nav-btn")

            yield Static("FEATURED COMMUNITY REVIEWS:", classes="panel-heading")
            with Horizontal(classes="carousel-row"):
                yield Button("<", id="btn-rev-prev", classes="carousel-nav-btn review-carousel-nav-btn")
                yield Horizontal(id="detail-reviews-preview", classes="chips-bar")
                yield Button(">", id="btn-rev-next", classes="carousel-nav-btn review-carousel-nav-btn")
            with Horizontal(id="detail-reviews-actions", classes="detail-section-actions"):
                yield Button("Review Movie", variant="success", id="btn-detail-review")
                yield Button("View All Reviews", variant="warning", id="btn-detail-all-reviews")

        yield Footer()

    def on_mount(self) -> None:
        for btn_id in (
            "#btn-dir-prev",
            "#btn-dir-next",
            "#btn-cast-prev",
            "#btn-cast-next",
            "#btn-rev-prev",
            "#btn-rev-next",
        ):
            self.query_one(btn_id, Button).display = False
        state = self.query_one("#detail-state-msg", StateMessage)
        state.show_loading("Loading movie details...")
        self._load_movie_worker(self._movie_key)

    def on_resize(self, event: Resize) -> None:
        if self._detail is not None:
            new_per_row = self._calc_cards_per_row()
            new_rev_per_row = self._calc_review_cards_per_row()
            if (
                new_per_row != self._cards_per_row
                or new_rev_per_row != self._rev_cards_per_row
            ):
                self._render_carousels()

    def _calc_cards_per_row(self) -> int:
        """Calculates how many PersonCards fit in a single row based on terminal width (fallback: 3)."""
        try:
            term_width = self.size.width or self.app.size.width
        except Exception:
            term_width = 0
        if not term_width or term_width <= 0:
            return 3
        usable_width = max(23, term_width - 20)
        return max(1, usable_width // 23)

    def _calc_review_cards_per_row(self) -> int:
        """Calculates how many ReviewCards (width 42) fit in a single row based on terminal width (fallback: 2)."""
        try:
            term_width = self.size.width or self.app.size.width
        except Exception:
            term_width = 0
        if not term_width or term_width <= 0:
            return 2
        usable_width = max(43, term_width - 20)
        return max(1, usable_width // 43)

    def on_screen_resume(self) -> None:
        if self._detail is not None:
            self._load_movie_worker(self._movie_key)

    @work(thread=True, exclusive=True)
    def _load_movie_worker(self, movie_key: str) -> None:
        worker = get_current_worker()
        try:
            mongo = MongoConnection()
            db = mongo.database if mongo.initialized else None
        except Exception:
            db = None
        detail = CatalogService().get_movie_detail(db, movie_key)

        top_reviews: List[Dict[str, Any]] = []
        user_status: Dict[str, Any] = {
            "watched": False,
            "liked": False,
            "likes_count": 0,
            "existing_review": None,
        }
        if detail:
            rev_res = execute_query(
                "mongo_req_5",
                {"movie_title": detail.title, "keywords": "", "page": "1"},
            )
            top_reviews = rev_res.rows[:10]
            session = AuthService().current_session
            uname = session.username if session else ""
            user_status = ProfileService().get_user_movie_status(
                uname, detail.title, detail.movie_id
            )

        if not worker.is_cancelled:
            self.app.call_from_thread(
                self._render_detail, detail, top_reviews, user_status
            )

    def _render_detail(
        self,
        detail: Optional[MovieDetail],
        top_reviews: List[Dict[str, Any]],
        user_status: Dict[str, Any],
    ) -> None:
        state = self.query_one("#detail-state-msg", StateMessage)
        if detail is None:
            state.show_empty(
                f"We couldn't get information for the movie '{self._movie_key}' in local MongoDB or TMDB.",
                "Please check the input title or verify your MongoDB and TMDB connection.",
            )
            return

        state.clear_state()
        if self._detail is None or self._detail.movie_id != detail.movie_id:
            self._dir_offset = 0
            self._cast_offset = 0
            self._rev_offset = 0
        self._detail = detail
        self._top_reviews = list(top_reviews)
        self.query_one("#top-bar", Static).update(
            f"[bold #58a6ff]🎬 MOVIE DETAILS[/]  ›  "
            f"[bold]{detail.title} ({detail.release_year})[/]"
        )

        # Update stateful action buttons (persisted in MongoDB across executions)
        watched_btn = self.query_one("#btn-detail-watched", Button)
        if user_status.get("watched"):
            watched_btn.label = "✓ Watched"
            watched_btn.variant = "success"
        else:
            watched_btn.label = "Mark as Watched"
            watched_btn.variant = "default"
        watched_btn.refresh(layout=True)

        likes_count = max(detail.likes, int(user_status.get("likes_count") or 0))
        like_btn = self.query_one("#btn-detail-like", Button)
        if user_status.get("liked"):
            like_btn.label = f"Liked ({likes_count})"
            like_btn.variant = "error"
        else:
            like_btn.label = f"Like ({likes_count})"
            like_btn.variant = "default"
        like_btn.refresh(layout=True)

        rev_btn = self.query_one("#btn-detail-review", Button)
        if user_status.get("existing_review"):
            rev_btn.label = "Edit Your Review"
            rev_btn.variant = "warning"
        else:
            rev_btn.label = "Review Movie"
            rev_btn.variant = "success"
        rev_btn.refresh(layout=True)
        self.query_one("#movie-hero-actions", Horizontal).refresh(layout=True)

        poster = self.query_one("#detail-poster", PosterImage)
        poster.set_poster(detail.poster_url, title=detail.title)

        runtime_str = f"  •  ⏱ {detail.runtime} min" if detail.runtime else ""
        self.query_one("#detail-title-banner", Static).update(
            f"[bold #58a6ff]{detail.title}[/]  [dim]({detail.release_year} • Decade {detail.decade}s{runtime_str})[/]\n"
            f"[bold #f0883e]★ {detail.rating:.2f} / 5.0[/]  "
            f"[dim]({detail.ratings_count:,} votes  •  ♥ {likes_count} likes  •  Impact: {detail.impact_score:.2f})[/]"
        )

        genres_str = ", ".join(detail.genres) if detail.genres else "Unclassified"
        countries_str = ", ".join(detail.countries) if detail.countries else "N/A"
        langs_str = (
            f"{detail.language_original.upper()} "
            f"(Available: {', '.join(detail.language_availables)})"
            if detail.language_availables
            else detail.language_original.upper()
        )
        stream_str = (
            ", ".join(detail.available_streaming)
            if detail.available_streaming
            else "Not specified"
        )
        self.query_one("#detail-specs-text", Static).update(
            f"\n[bold #79c0ff]Genres:[/] {genres_str}\n"
            f"[bold #79c0ff]Origin country:[/] {countries_str}\n"
            f"[bold #79c0ff]Language:[/] {langs_str}\n"
            f"[bold #3fb950]Available on:[/] {stream_str}"
        )

        synopsis = detail.synopsis or "No synopsis registered."
        self.query_one("#detail-synopsis-text", Static).update(
            f"\n[bold #79c0ff]Synopsis:[/]\n{synopsis}\n"
        )

        self._render_carousels()

    def _render_carousels(self) -> None:
        if self._detail is None:
            return
        per_row = self._calc_cards_per_row()
        self._cards_per_row = per_row

        directors = self._detail.directors or []
        dir_bar = self.query_one("#detail-directors-bar", Horizontal)
        btn_dir_prev = self.query_one("#btn-dir-prev", Button)
        btn_dir_next = self.query_one("#btn-dir-next", Button)
        dir_bar.remove_children()

        if not directors:
            btn_dir_prev.display = False
            btn_dir_next.display = False
            dir_bar.mount(Static("[dim]No director listed[/]"))
        else:
            max_dir_offset = max(0, len(directors) - per_row)
            self._dir_offset = max(0, min(self._dir_offset, max_dir_offset))
            show_dir_nav = len(directors) > per_row
            btn_dir_prev.display = show_dir_nav
            btn_dir_next.display = show_dir_nav
            if show_dir_nav:
                btn_dir_prev.disabled = self._dir_offset <= 0
                btn_dir_next.disabled = self._dir_offset >= max_dir_offset

            dir_cards = [
                PersonCard(
                    person_id=str(d.get("id") or d["name"]),
                    person_name=d["name"],
                    kind="director",
                    poster_url=d.get("poster_url", ""),
                )
                for d in directors[self._dir_offset : self._dir_offset + per_row]
            ]
            populate_carousel_bar(dir_bar, dir_cards, per_row)

        cast = (self._detail.cast or [])[:10]
        cast_bar = self.query_one("#detail-cast-bar", Horizontal)
        btn_cast_prev = self.query_one("#btn-cast-prev", Button)
        btn_cast_next = self.query_one("#btn-cast-next", Button)
        cast_bar.remove_children()

        if not cast:
            btn_cast_prev.display = False
            btn_cast_next.display = False
            cast_bar.mount(Static("[dim]No cast listed[/]"))
        else:
            max_cast_offset = max(0, len(cast) - per_row)
            self._cast_offset = max(0, min(self._cast_offset, max_cast_offset))
            show_cast_nav = len(cast) > per_row
            btn_cast_prev.display = show_cast_nav
            btn_cast_next.display = show_cast_nav
            if show_cast_nav:
                btn_cast_prev.disabled = self._cast_offset <= 0
                btn_cast_next.disabled = self._cast_offset >= max_cast_offset

            cast_cards = [
                PersonCard(
                    person_id=str(a.get("id") or a["name"]),
                    person_name=a["name"],
                    kind="actor",
                    poster_url=a.get("poster_url", ""),
                    character=a.get("character", ""),
                )
                for a in cast[self._cast_offset : self._cast_offset + per_row]
            ]
            populate_carousel_bar(cast_bar, cast_cards, per_row)

        rev_per_row = self._calc_review_cards_per_row()
        self._rev_cards_per_row = rev_per_row
        rev_bar = self.query_one("#detail-reviews-preview", Horizontal)
        btn_rev_prev = self.query_one("#btn-rev-prev", Button)
        btn_rev_next = self.query_one("#btn-rev-next", Button)
        rev_bar.remove_children()

        if not self._top_reviews:
            btn_rev_prev.display = False
            btn_rev_next.display = False
            rev_bar.mount(
                Static(
                    "[dim]No reviews yet for this movie. Press 'Review Movie' (Ctrl+N) to write the first![/]"
                )
            )
        else:
            max_rev_offset = max(0, len(self._top_reviews) - rev_per_row)
            self._rev_offset = max(0, min(self._rev_offset, max_rev_offset))
            show_rev_nav = len(self._top_reviews) > rev_per_row
            btn_rev_prev.display = show_rev_nav
            btn_rev_next.display = show_rev_nav
            if show_rev_nav:
                btn_rev_prev.disabled = self._rev_offset <= 0
                btn_rev_next.disabled = self._rev_offset >= max_rev_offset

            session = AuthService().current_session
            cur_user = session.username if session else ""
            rev_cards: List[Vertical] = []
            for r in self._top_reviews[self._rev_offset : self._rev_offset + rev_per_row]:
                author = str(r.get("username") or "user")
                rating = float(r.get("rating") or 0.0)
                likes = int(r.get("likes") or 0)
                created = str(r.get("created_at") or "")
                content = str(r.get("content") or "").strip()
                if len(content) > 140:
                    content = content[:137] + "..."
                liked_by = {str(u).lower() for u in (r.get("_liked_by") or [])}
                user_liked = bool(cur_user and cur_user.lower() in liked_by)

                rev_cards.append(
                    Vertical(
                        Horizontal(
                            Button(
                                f"@{author}",
                                name=author,
                                classes="review-movie-title-link btn-md-author-link",
                            ),
                            Static(
                                f"  [bold #f0883e]★ {rating:.1f}[/]  "
                                f"[bold #3fb950]♥ {likes}[/]  [dim]{created}[/]",
                                classes="review-card-meta",
                            ),
                            classes="review-card-header",
                        ),
                        Static(content, classes="review-item-body"),
                        Horizontal(
                            Button(
                                f"Liked ({likes})" if user_liked else f"Like ({likes})",
                                variant="error" if user_liked else "default",
                                name=author,
                                classes="btn-md-like-review",
                            ),
                            classes="review-card-actions",
                        ),
                        classes="review-item-card",
                    )
                )
            populate_carousel_bar(
                rev_bar,
                rev_cards,
                rev_per_row,
                empty_slot_class="carousel-review-empty-slot",
            )

    @on(Button.Pressed, "#btn-dir-prev")
    def _on_dir_prev(self) -> None:
        if self._dir_offset > 0:
            self._dir_offset -= 1
            self._render_carousels()

    @on(Button.Pressed, "#btn-dir-next")
    def _on_dir_next(self) -> None:
        if self._detail and self._dir_offset + self._cards_per_row < len(self._detail.directors):
            self._dir_offset += 1
            self._render_carousels()

    @on(Button.Pressed, "#btn-cast-prev")
    def _on_cast_prev(self) -> None:
        if self._cast_offset > 0:
            self._cast_offset -= 1
            self._render_carousels()

    @on(Button.Pressed, "#btn-cast-next")
    def _on_cast_next(self) -> None:
        if self._detail and self._cast_offset + self._cards_per_row < len(self._detail.cast[:10]):
            self._cast_offset += 1
            self._render_carousels()

    @on(Button.Pressed, "#btn-rev-prev")
    def _on_rev_prev(self) -> None:
        if self._rev_offset > 0:
            self._rev_offset -= 1
            self._render_carousels()

    @on(Button.Pressed, "#btn-rev-next")
    def _on_rev_next(self) -> None:
        if self._rev_offset + self._rev_cards_per_row < len(self._top_reviews):
            self._rev_offset += 1
            self._render_carousels()

    @on(PersonCard.Selected)
    def _on_person_card_selected(self, event: PersonCard.Selected) -> None:
        self.app.push_screen(
            PersonScreen(
                event.person_id,
                kind=event.kind,
                display_name=event.person_name,
            )
        )

    @on(Button.Pressed, ".person-chip-btn")
    def _on_person_chip(self, event: Button.Pressed) -> None:
        raw = event.button.name or ""
        parts = raw.split("|", 2)
        if len(parts) == 3:
            kind_str, pid, pname = parts
            kind: Any = "director" if kind_str == "director" else "actor"
            self.app.push_screen(PersonScreen(pid, kind=kind, display_name=pname))

    @on(Button.Pressed, "#btn-detail-back")
    def _on_back(self) -> None:
        self.action_go_back()

    @on(Button.Pressed, "#btn-detail-watched")
    def _on_watched(self) -> None:
        session = AuthService().current_session
        state = self.query_one("#detail-state-msg", StateMessage)
        if session is None:
            state.show_error("Sign in to mark movies as watched.")
            return
        title = self._detail.title if self._detail else self._movie_key
        ok, msg = ActionService().mark_movie_watched(session, title)
        if ok:
            state.show_success(msg)
            self._load_movie_worker(self._movie_key)
        else:
            state.show_error(msg)

    @on(Button.Pressed, "#btn-detail-like")
    def _on_like_movie(self) -> None:
        session = AuthService().current_session
        state = self.query_one("#detail-state-msg", StateMessage)
        if session is None:
            state.show_error("Sign in to like movies.")
            return
        title = self._detail.title if self._detail else self._movie_key
        ok, msg = ActionService().like_movie(session, title)
        if ok:
            state.show_success(msg)
            self._load_movie_worker(self._movie_key)
        else:
            state.show_error(msg)

    @on(Button.Pressed, "#btn-detail-review")
    def _on_review(self) -> None:
        self.action_open_review()

    @on(Button.Pressed, "#btn-detail-list")
    def _on_list(self) -> None:
        self.action_open_list()

    @on(Button.Pressed, "#btn-detail-all-reviews")
    def _on_all_reviews(self) -> None:
        title = self._detail.title if self._detail else self._movie_key
        self.app.push_screen(ReviewsScreen(title))

    @on(Button.Pressed, ".btn-md-author-link")
    def _on_md_author_link(self, event: Button.Pressed) -> None:
        username = (event.button.name or "").strip()
        if username:
            from tui.screens.user.profile import ProfileScreen

            self.app.push_screen(ProfileScreen(username))

    @on(Button.Pressed, ".btn-md-like-review")
    def _on_md_like_review(self, event: Button.Pressed) -> None:
        review_owner = (event.button.name or "").strip()
        session = AuthService().current_session
        state = self.query_one("#detail-state-msg", StateMessage)
        if session is None:
            state.show_error("Sign in to like reviews.")
            return
        title = self._detail.title if self._detail else self._movie_key
        ok, msg = ActionService().like_review(session, title, review_owner)
        if ok:
            state.show_success(msg)
            self._load_movie_worker(self._movie_key)
        else:
            state.show_error(msg)

    def action_open_review(self) -> None:
        title = self._detail.title if self._detail else self._movie_key
        year = self._detail.release_year if self._detail else 2024

        def _after(msg: Optional[str]) -> None:
            if msg:
                self.query_one("#detail-state-msg", StateMessage).show_success(msg)
                self._load_movie_worker(self._movie_key)

        self.app.push_screen(ReviewMovieModal(movie_title=title, release_year=year), _after)

    def action_open_list(self) -> None:
        title = self._detail.title if self._detail else self._movie_key
        poster = self._detail.poster_url if self._detail else ""

        def _after(msg: Optional[str]) -> None:
            if msg:
                show_success_toast(self, msg)

        self.app.push_screen(ManageListModal(movie_title=title, poster_url=poster), _after)

    def action_go_back(self) -> None:
        self.app.pop_screen()
