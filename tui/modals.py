"""
Letterboxd-style interactive modals for MovieVault (backend/tui/modals.py).
"""

from typing import Any, Dict, List, Literal, Optional

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
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

from services.ActionService import ActionService
from services.AuthService import AuthService, UserSession
from services.ProfileService import ProfileService
from services.QueryService import execute_query

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


class UserSwitchModal(ModalScreen[Optional[UserSession]]):
    """Modal to quickly switch between registered users."""

    BINDINGS = [
        Binding("escape", "cancel", "Close", show=True),
    ]

    def compose(self) -> ComposeResult:
        auth = AuthService()
        registered_users = auth.list_demo_users()
        current = auth.current_session

        with Vertical(id="switch-card", classes="modal-card"):
            yield Static(
                "[bold #d2a8ff]⇄ QUICK USER SWITCH (Ctrl+U)[/]\n"
                "[dim]Select an account with ↑/↓ and press Enter:[/]"
            )
            items: List[ListItem] = []
            for u in registered_users:
                uname = u["username"]
                marker = " ★ [ACTIVE]" if (current and current.username == uname) else ""
                label = (
                    f"@{uname}{marker} "
                    f"[dim]({u.get('email', '')} • {u.get('lists_count', 0)} lists)[/]"
                )
                items.append(ListItem(Label(label), name=uname))

            if not items:
                yield Static(
                    "\n[bold #f0883e]∅ No registered users available.[/]"
                )
            yield ListView(*items, id="switch-user-list")
            yield Static("\n[dim]Enter: Switch account  │  Esc: Close[/]")

    def on_mount(self) -> None:
        self.query_one("#switch-user-list", ListView).focus()

    @on(ListView.Selected, "#switch-user-list")
    def on_user_selected(self, event: ListView.Selected) -> None:
        username = event.item.name
        if username:
            ok, session, _ = AuthService().quick_switch_user(username)
            if ok:
                self.dismiss(session)
                return
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


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
            feedback.update("[bold #f85149]✖ You must be logged in to publish a review.[/]")
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
        else:
            feedback.update(f"[bold #f85149]✖ {msg}[/]")

    def action_cancel(self) -> None:
        self.dismiss(None)


class ManageListModal(ModalScreen[Optional[str]]):
    """Modal to create a personal list or add a movie to one."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(self, movie_title: str = "", poster_url: str = "") -> None:
        super().__init__()
        self._initial_movie = (movie_title or "").strip()
        self._initial_poster = (poster_url or "").strip()

    def compose(self) -> ComposeResult:
        with Vertical(id="list-modal-card", classes="modal-card"):
            yield Static(
                "[bold #58a6ff]📋 MANAGE MOVIE LISTS (Ctrl+B)[/]\n"
                "[dim]Create a new list or add movies to your existing lists.[/]"
            )
            yield Static("", id="list-modal-feedback", classes="modal-feedback")

            yield Label("List name:")
            yield Input(
                placeholder="e.g. Watchlist, Sci-Fi Favorites",
                value="Watchlist",
                id="list-name",
            )

            yield Label("Movie title to include:")
            yield Input(
                placeholder="e.g. Interstellar",
                value=self._initial_movie,
                id="list-movie-title",
            )

            yield Label("Poster URL (Optional):")
            yield Input(
                placeholder="https://...",
                value=self._initial_poster,
                id="list-poster-url",
            )

            with Horizontal(classes="modal-buttons"):
                yield Button("Add to List", variant="primary", id="btn-save-list")
                yield Button("Cancel [Esc]", variant="default", id="btn-cancel-list")

    def on_mount(self) -> None:
        if self._initial_movie:
            self.query_one("#list-name", Input).focus()
        else:
            self.query_one("#list-movie-title", Input).focus()

    @on(Button.Pressed, "#btn-cancel-list")
    def on_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-save-list")
    def on_save(self) -> None:
        session = AuthService().current_session
        feedback = self.query_one("#list-modal-feedback", Static)
        if session is None:
            feedback.update("[bold #f85149]✖ You must be logged in to manage lists.[/]")
            return

        list_name = self.query_one("#list-name", Input).value
        movie_title = self.query_one("#list-movie-title", Input).value
        poster_url = self.query_one("#list-poster-url", Input).value

        ok, msg = ActionService().add_movie_to_list(
            user=session,
            list_name=list_name,
            movie_title=movie_title,
            poster_url=poster_url,
        )
        if ok:
            self.dismiss(msg)
        else:
            feedback.update(f"[bold #f85149]✖ {msg}[/]")

    def action_cancel(self) -> None:
        self.dismiss(None)


class SocialActionModal(ModalScreen[Optional[str]]):
    """Modal to like a user's review or follow an account."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="social-modal-card", classes="modal-card"):
            yield Static(
                "[bold #d2a8ff]🤝 SOCIAL INTERACTION: LIKE REVIEW / FOLLOW USER (Ctrl+F)[/]"
            )
            yield Static("", id="social-modal-feedback", classes="modal-feedback")

            yield Static("[bold #79c0ff]Option A — Like a Review:[/]")
            with Horizontal(classes="modal-row"):
                with Vertical(classes="modal-col"):
                    yield Label("Reviewed movie:")
                    yield Input(placeholder="e.g. Inception", id="like-movie-title")
                with Vertical(classes="modal-col"):
                    yield Label("Review author (@username):")
                    yield Input(placeholder="e.g. cinephile_ana", id="like-review-owner")
            yield Button("♥ Like Review", variant="primary", id="btn-like-review")

            yield Static("\n[bold #d2a8ff]Option B — Follow a User (Follow):[/]")
            yield Label("Account username to follow:")
            yield Input(placeholder="e.g. director_carlos", id="follow-target-user")

            with Horizontal(classes="modal-buttons"):
                yield Button("+ Follow User", variant="success", id="btn-follow-user")
                yield Button("Close [Esc]", variant="default", id="btn-cancel-social")

    def on_mount(self) -> None:
        self.query_one("#like-movie-title", Input).focus()

    @on(Button.Pressed, "#btn-cancel-social")
    def on_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-like-review")
    def on_like_review(self) -> None:
        session = AuthService().current_session
        feedback = self.query_one("#social-modal-feedback", Static)
        if session is None:
            feedback.update("[bold #f85149]✖ Sign in to interact.[/]")
            return

        movie_title = self.query_one("#like-movie-title", Input).value
        review_owner = self.query_one("#like-review-owner", Input).value
        ok, msg = ActionService().like_review(session, movie_title, review_owner)
        if ok:
            self.dismiss(msg)
        else:
            feedback.update(f"[bold #f85149]✖ {msg}[/]")

    @on(Button.Pressed, "#btn-follow-user")
    def on_follow_user(self) -> None:
        session = AuthService().current_session
        feedback = self.query_one("#social-modal-feedback", Static)
        if session is None:
            feedback.update("[bold #f85149]✖ Sign in to follow users.[/]")
            return

        target = self.query_one("#follow-target-user", Input).value
        ok, msg = ActionService().follow_user(session, target)
        if ok:
            self.dismiss(msg)
        else:
            feedback.update(f"[bold #f85149]✖ {msg}[/]")

    def action_cancel(self) -> None:
        self.dismiss(None)


class WrappedModal(ModalScreen[None]):
    """Modal that executes Mongo Req 8 and displays the user's Wrapped statistics."""

    BINDINGS = [
        Binding("escape", "cancel", "Close", show=True),
    ]

    def __init__(self, username: str) -> None:
        super().__init__()
        self._username = (username or "").strip().lstrip("@")

    def compose(self) -> ComposeResult:
        with Vertical(id="wrapped-modal-card", classes="modal-card"):
            yield Static(
                f"[bold #d2a8ff]📊 CINEMATIC WRAPPED — @{self._username}[/]\n"
                "[dim]Statistics computed via MongoDB Aggregation (Mongo Req 8).[/]"
            )
            yield Static(
                "[dim]⏳ Computing Wrapped statistics...[/]",
                id="wrapped-modal-body",
                classes="wrapped-summary-card",
            )
            with Horizontal(classes="modal-buttons"):
                yield Button("🔄 Refresh", variant="primary", id="btn-wrapped-refresh")
                yield Button("Close [Esc]", variant="default", id="btn-wrapped-close")

    def on_mount(self) -> None:
        self._run_wrapped_query()

    @on(Button.Pressed, "#btn-wrapped-refresh")
    def _on_refresh(self) -> None:
        self.query_one("#wrapped-modal-body", Static).update(
            "[dim]⏳ Computing Wrapped statistics...[/]"
        )
        self._run_wrapped_query()

    @on(Button.Pressed, "#btn-wrapped-close")
    def _on_close(self) -> None:
        self.dismiss(None)

    @work(thread=True, exclusive=True)
    def _run_wrapped_query(self) -> None:
        worker = get_current_worker()
        res = execute_query("mongo_req_8", {"username": self._username})
        if not worker.is_cancelled:
            self.app.call_from_thread(self._render_wrapped, res.rows)

    def _render_wrapped(self, rows: List[Dict[str, Any]]) -> None:
        body = self.query_one("#wrapped-modal-body", Static)
        if not rows:
            body.update(
                "[bold #f0883e]∅ No Wrapped data available yet.[/]\n"
                "[dim]Publish reviews to generate your cinematic statistics.[/]"
            )
            return

        r = rows[0]
        body.update(
            f"[bold #58a6ff]👤 @{r.get('username', self._username)}[/]\n\n"
            f"  • [bold #3fb950]Published reviews:[/] {r.get('total_reviews', 0)}\n"
            f"  • [bold #f0883e]Movies rated:[/] {r.get('total_ratings', 0)}\n"
            f"  • [bold #79c0ff]Average likes per review:[/] {r.get('avg_likes_per_review', 0.0)}\n"
            f"  • [bold #d2a8ff]User Impact Score:[/] {r.get('user_impact_score', 0.0)}\n\n"
            f"[bold #79c0ff]🎬 Favorite Genres:[/]  {r.get('top_genres', 'N/A')}\n"
            f"[bold #79c0ff]🎭 Most Watched Actors:[/] {r.get('top_actors', 'N/A')}\n"
            f"[bold #79c0ff]🎥 Favorite Directors:[/] {r.get('top_directors', 'N/A')}"
        )

    def action_cancel(self) -> None:
        self.dismiss(None)


class EditProfileModal(ModalScreen[Optional[UserSession]]):
    """Modal to edit the authenticated user's username and email."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def compose(self) -> ComposeResult:
        session = AuthService().current_session
        cur_user = session.username if session else ""
        cur_email = session.email if session else ""

        with Vertical(id="edit-profile-modal-card", classes="modal-card"):
            yield Static(
                "[bold #58a6ff]✏ EDIT PROFILE INFORMATION[/]\n"
                "[dim]Update your MovieVault handle or email address.[/]"
            )
            yield Static("", id="edit-profile-feedback", classes="modal-feedback")

            yield Label("Username:")
            yield Input(value=cur_user, placeholder="e.g. cinephile_ana", id="inp-edit-username")

            yield Label("Email:")
            yield Input(value=cur_email, placeholder="e.g. ana@movievault.com", id="inp-edit-email")

            with Horizontal(classes="modal-buttons"):
                yield Button("Save Changes", variant="success", id="btn-save-profile")
                yield Button("Cancel [Esc]", variant="default", id="btn-cancel-profile")

    def on_mount(self) -> None:
        self.query_one("#inp-edit-username", Input).focus()

    @on(Button.Pressed, "#btn-cancel-profile")
    def _on_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-save-profile")
    def _on_save(self) -> None:
        auth = AuthService()
        session = auth.current_session
        feedback = self.query_one("#edit-profile-feedback", Static)
        if session is None:
            feedback.update("[bold #f85149]✖ You must be logged in to edit your profile.[/]")
            return

        new_username = self.query_one("#inp-edit-username", Input).value
        new_email = self.query_one("#inp-edit-email", Input).value
        ok, updated_session, msg = ActionService().update_user_profile(
            user=session,
            new_username=new_username,
            new_email=new_email,
        )
        if ok and updated_session is not None:
            auth.update_current_session(updated_session)
            self.dismiss(updated_session)
        else:
            feedback.update(f"[bold #f85149]✖ {msg}[/]")

    def action_cancel(self) -> None:
        self.dismiss(None)


class FollowListModal(ModalScreen[Optional[str]]):
    """Modal displaying followers or following accounts; selecting one opens their profile."""

    BINDINGS = [
        Binding("escape", "cancel", "Close", show=True),
    ]

    def __init__(
        self,
        username: str,
        mode: Literal["followers", "following"] = "followers",
    ) -> None:
        super().__init__()
        self._username = (username or "").strip().lstrip("@")
        self._mode: Literal["followers", "following"] = mode

    def compose(self) -> ComposeResult:
        title = "👥 FOLLOWERS" if self._mode == "followers" else "👣 FOLLOWING"
        with Vertical(id="follow-list-modal-card", classes="modal-card"):
            yield Static(
                f"[bold #d2a8ff]{title} — @{self._username}[/]\n"
                "[dim]Select an account and press Enter to open their profile:[/]"
            )
            yield Static("[dim]⏳ Loading accounts...[/]", id="follow-list-status")
            yield ListView(id="follow-users-listview")
            with Horizontal(classes="modal-buttons"):
                yield Button("Close [Esc]", variant="default", id="btn-close-follow-list")

    def on_mount(self) -> None:
        self._load_accounts()

    @work(thread=True, exclusive=True)
    def _load_accounts(self) -> None:
        worker = get_current_worker()
        session = AuthService().current_session
        viewer = session.username if session else ""
        svc = ProfileService()
        if self._mode == "followers":
            rows = svc.get_followers(self._username, viewer_username=viewer)
        else:
            rows = svc.get_following(self._username, viewer_username=viewer)
        if not worker.is_cancelled:
            self.app.call_from_thread(self._render_accounts, rows)

    def _render_accounts(self, rows: List[Dict[str, Any]]) -> None:
        status = self.query_one("#follow-list-status", Static)
        lv = self.query_one("#follow-users-listview", ListView)
        lv.clear()
        if not rows:
            noun = "followers" if self._mode == "followers" else "followed accounts"
            status.update(f"[bold #f0883e]∅ No {noun} found for @{self._username}.[/]")
            return

        status.update(f"[dim]{len(rows)} account(s) found.[/]")
        for r in rows:
            uname = str(r.get("username", "")).strip()
            followers = int(r.get("followers_count") or 0)
            following_badge = "  [bold #3fb950]✓ Following[/]" if r.get("is_following") else ""
            lv.append(
                ListItem(
                    Label(f"@{uname}  [dim]({followers} followers)[/]{following_badge}"),
                    name=uname,
                )
            )
        lv.focus()

    @on(ListView.Selected, "#follow-users-listview")
    def _on_select_user(self, event: ListView.Selected) -> None:
        if event.item.name:
            self.dismiss(str(event.item.name))

    @on(Button.Pressed, "#btn-close-follow-list")
    def _on_close(self) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class CreateListModal(ModalScreen[Optional[str]]):
    """Modal to create a new empty personal movie list."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="create-list-modal-card", classes="modal-card"):
            yield Static(
                "[bold #58a6ff]📋 CREATE NEW PERSONAL LIST[/]\n"
                "[dim]Organize movies into custom collections (e.g. Watchlist, Sci-Fi Top).[/]"
            )
            yield Static("", id="create-list-feedback", classes="modal-feedback")
            yield Label("List name:")
            yield Input(placeholder="e.g. Weekend Watchlist", id="inp-new-list-name")
            with Horizontal(classes="modal-buttons"):
                yield Button("Create List", variant="success", id="btn-confirm-create-list")
                yield Button("Cancel [Esc]", variant="default", id="btn-cancel-create-list")

    def on_mount(self) -> None:
        self.query_one("#inp-new-list-name", Input).focus()

    @on(Button.Pressed, "#btn-cancel-create-list")
    def _on_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-confirm-create-list")
    def _on_create(self) -> None:
        self._submit()

    @on(Input.Submitted, "#inp-new-list-name")
    def _on_submit_input(self) -> None:
        self._submit()

    def _submit(self) -> None:
        session = AuthService().current_session
        feedback = self.query_one("#create-list-feedback", Static)
        if session is None:
            feedback.update("[bold #f85149]✖ You must be logged in to create lists.[/]")
            return

        name = self.query_one("#inp-new-list-name", Input).value
        ok, msg = ActionService().create_list(session, name)
        if ok:
            self.dismiss(msg)
        else:
            feedback.update(f"[bold #f85149]✖ {msg}[/]")

    def action_cancel(self) -> None:
        self.dismiss(None)


class VisitProfileModal(ModalScreen[Optional[str]]):
    """Modal to look up and visit another user's profile by @username."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="visit-profile-modal-card", classes="modal-card"):
            yield Static(
                "[bold #58a6ff]🔍 VISIT USER PROFILE[/]\n"
                "[dim]Enter a @username to inspect their reviews, watched movies, and lists.[/]"
            )
            yield Static("", id="visit-profile-feedback", classes="modal-feedback")
            yield Label("Username:")
            yield Input(placeholder="e.g. cinephile_ana", id="inp-visit-username")
            with Horizontal(classes="modal-buttons"):
                yield Button("Open Profile", variant="primary", id="btn-confirm-visit-profile")
                yield Button("Cancel [Esc]", variant="default", id="btn-cancel-visit-profile")

    def on_mount(self) -> None:
        self.query_one("#inp-visit-username", Input).focus()

    @on(Button.Pressed, "#btn-cancel-visit-profile")
    def _on_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-confirm-visit-profile")
    def _on_open(self) -> None:
        self._submit()

    @on(Input.Submitted, "#inp-visit-username")
    def _on_submit_input(self) -> None:
        self._submit()

    def _submit(self) -> None:
        raw = self.query_one("#inp-visit-username", Input).value.strip().lstrip("@")
        if not raw:
            self.query_one("#visit-profile-feedback", Static).update(
                "[bold #f85149]✖ Please enter a username.[/]"
            )
            return
        self.dismiss(raw)

    def action_cancel(self) -> None:
        self.dismiss(None)
