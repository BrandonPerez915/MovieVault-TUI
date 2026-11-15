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

RATING_OPTIONS = [
    ("★★★★★ (5.0) — Masterpiece", "5.0"),
    ("★★★★½ (4.5) — Excellent", "4.5"),
    ("★★★★ (4.0) — Great", "4.0"),
    ("★★★½ (3.5) — Good", "3.5"),
    ("★★★ (3.0) — Entertaining", "3.0"),
    ("★★½ (2.5) — Average", "2.5"),
    ("★★ (2.0) — Mediocre", "2.0"),
    ("★½ (1.5) — Poor", "1.5"),
    ("★ (1.0) — Terrible", "1.0"),
    ("½ (0.5) — Awful", "0.5"),
]




class ReviewMovieModal(ModalScreen[Optional[str]]):
    """Letterboxd-style modal to log a watched movie and publish its review."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(self, movie_title: str = "", release_year: int = 2024) -> None:
        super().__init__()
        self._initial_title = (movie_title or "").strip()
        self._initial_year = str(release_year) if release_year else "2024"

    def compose(self) -> ComposeResult:
        with Vertical(id="review-modal-card", classes="modal-card"):
            yield Static(
                "[bold #3fb950]✍ LOG MOVIE AND PUBLISH REVIEW (Ctrl+N)[/]\n"
                "[dim]Share your rating, viewing platform, and review content.[/]",
                id="rev-modal-header",
            )
            yield Static("", id="review-modal-feedback", classes="modal-feedback")

            yield Label("Movie title:")
            yield Input(
                placeholder="e.g. Inception",
                value=self._initial_title,
                id="rev-movie-title",
            )

            with Horizontal(classes="modal-row"):
                with Vertical(classes="modal-col"):
                    yield Label("Release year:")
                    yield Input(
                        placeholder="e.g. 2010",
                        value=self._initial_year,
                        id="rev-release-year",
                    )
                with Vertical(classes="modal-col"):
                    yield Label("Rating:")
                    yield Select(
                        RATING_OPTIONS,
                        value="4.5",
                        allow_blank=False,
                        id="rev-rating-select",
                    )
                with Vertical(classes="modal-col"):
                    yield Label("Viewing medium:")
                    yield Input(
                        placeholder="e.g. Cinema, Netflix, MUBI",
                        value="Streaming",
                        id="rev-viewed-on",
                    )

            yield Checkbox("♥ Liked this film", value=True, id="rev-liked")

            yield Label("Your review:")
            yield TextArea("", id="rev-content-area")

            with Horizontal(classes="modal-buttons"):
                yield Button("Publish Review", variant="success", id="btn-save-review")
                yield Button("Cancel [Esc]", variant="default", id="btn-cancel-review")

    def on_mount(self) -> None:
        if self._initial_title:
            self._load_existing_review_if_any(self._initial_title, replace_text=True)
            self.query_one("#rev-content-area", TextArea).focus()
        else:
            self.query_one("#rev-movie-title", Input).focus()

    @on(Input.Changed, "#rev-movie-title")
    def _on_title_changed(self, event: Input.Changed) -> None:
        self._load_existing_review_if_any(event.value, replace_text=False)

    def _load_existing_review_if_any(self, movie_title: str, replace_text: bool = False) -> None:
        session = AuthService().current_session
        clean_title = (movie_title or "").strip()
        header = self.query_one("#rev-modal-header", Static)
        save_btn = self.query_one("#btn-save-review", Button)
        if session is None or not clean_title:
            return

        status = ProfileService().get_user_movie_status(session.username, clean_title)
        existing = status.get("existing_review")
        if existing:
            header.update(
                "[bold #f0883e]✏ EDIT YOUR EXISTING REVIEW (Ctrl+N)[/]\n"
                "[dim]You already reviewed this movie (1 review per movie allowed). Modify it below:[/]"
            )
            save_btn.label = "Update Review"
            rating_str = f"{float(existing.get('rating') or 4.5):.1f}"
            valid_ratings = {val for _, val in RATING_OPTIONS}
            if rating_str in valid_ratings:
                self.query_one("#rev-rating-select", Select).value = rating_str
            self.query_one("#rev-liked", Checkbox).value = bool(status.get("liked", True))
            area = self.query_one("#rev-content-area", TextArea)
            if replace_text or not area.text.strip():
                area.load_text(str(existing.get("content") or ""))
        else:
            header.update(
                "[bold #3fb950]✍ LOG MOVIE AND PUBLISH REVIEW (Ctrl+N)[/]\n"
                "[dim]Share your rating, viewing platform, and review content.[/]"
            )
            save_btn.label = "Publish Review"

    @on(Button.Pressed, "#btn-cancel-review")
    def on_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-save-review")
    def on_save(self) -> None:
        session = AuthService().current_session
        feedback = self.query_one("#review-modal-feedback", Static)
        if session is None:
            msg = "You must be logged in to publish a review."
            feedback.update(f"[bold #f85149]✖ {msg}[/]")
            show_error_toast(self, msg)
            return

        title = self.query_one("#rev-movie-title", Input).value
        year_str = self.query_one("#rev-release-year", Input).value
        rating_val = str(self.query_one("#rev-rating-select", Select).value)
        viewed_on = self.query_one("#rev-viewed-on", Input).value
        liked = self.query_one("#rev-liked", Checkbox).value
        content = self.query_one("#rev-content-area", TextArea).text

        try:
            release_year = int(year_str.strip())
        except ValueError:
            release_year = 2024

        try:
            rating = float(rating_val)
        except ValueError:
            rating = 4.0

        ok, msg = ActionService().create_review(
            user=session,
            movie_title=title,
            release_year=release_year,
            rating=rating,
            content=content,
            liked=liked,
            viewed_on=viewed_on,
        )
        if ok:
            self.dismiss(msg)
        elif "already in list" in msg.lower():
            feedback.update(f"[bold #58a6ff]ℹ {msg}[/]")
            show_info_toast(self, msg)
        else:
            feedback.update(f"[bold #f85149]✖ {msg}[/]")
            show_error_toast(self, msg)

    def action_cancel(self) -> None:
        self.dismiss(None)



class SearchReviewsModal(ModalScreen[Optional[str]]):
    """Modal to search a movie's reviews by keywords (MongoDB Req 5)."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(self, movie_title: str = "") -> None:
        super().__init__()
        self._movie_title = (movie_title or "").strip()

    def compose(self) -> ComposeResult:
        title_line = (
            f" for [bold #79c0ff]{self._movie_title}[/]" if self._movie_title else ""
        )
        with Vertical(id="search-reviews-modal-card", classes="modal-card"):
            yield Static(
                f"[bold #58a6ff]🔍 SEARCH REVIEWS BY KEYWORD[/]\n"
                f"[dim]Filter community reviews{title_line} by keywords.[/]"
            )
            yield Static("", id="search-reviews-feedback", classes="modal-feedback")
            yield Label("Keywords:")
            yield Input(
                placeholder="e.g. masterpiece, cinematography, ending...",
                id="inp-search-review-keywords",
            )
            with Horizontal(classes="modal-buttons"):
                yield Button(
                    "🔍 Search Reviews",
                    variant="primary",
                    id="btn-confirm-search-reviews",
                )
                yield Button(
                    "Cancel [Esc]",
                    variant="default",
                    id="btn-cancel-search-reviews",
                )

    def on_mount(self) -> None:
        self.query_one("#inp-search-review-keywords", Input).focus()

    @on(Button.Pressed, "#btn-cancel-search-reviews")
    def _on_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-confirm-search-reviews")
    def _on_confirm(self) -> None:
        self._submit()

    @on(Input.Submitted, "#inp-search-review-keywords")
    def _on_submit_input(self) -> None:
        self._submit()

    def _submit(self) -> None:
        keywords = self.query_one("#inp-search-review-keywords", Input).value.strip()
        self.dismiss(keywords)

    def action_cancel(self) -> None:
        self.dismiss(None)

