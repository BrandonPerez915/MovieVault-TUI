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
            msg = "Sign in to interact."
            feedback.update(f"[bold #f85149]✖ {msg}[/]")
            show_error_toast(self, msg)
            return

        movie_title = self.query_one("#like-movie-title", Input).value
        review_owner = self.query_one("#like-review-owner", Input).value
        ok, msg = ActionService().like_review(session, movie_title, review_owner)
        if ok:
            self.dismiss(msg)
        elif "already in list" in msg.lower():
            feedback.update(f"[bold #58a6ff]ℹ {msg}[/]")
            show_info_toast(self, msg)
        else:
            feedback.update(f"[bold #f85149]✖ {msg}[/]")
            show_error_toast(self, msg)

    @on(Button.Pressed, "#btn-follow-user")
    def on_follow_user(self) -> None:
        session = AuthService().current_session
        feedback = self.query_one("#social-modal-feedback", Static)
        if session is None:
            msg = "Sign in to follow users."
            feedback.update(f"[bold #f85149]✖ {msg}[/]")
            show_error_toast(self, msg)
            return

        target = self.query_one("#follow-target-user", Input).value
        ok, msg = ActionService().follow_user(session, target)
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
            yield LoadingSpinner(
                "Computing Wrapped statistics...",
                auto_start=True,
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
        self.query_one("#wrapped-modal-body", LoadingSpinner).start_spinner(
            "Computing Wrapped statistics..."
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
        body = self.query_one("#wrapped-modal-body", LoadingSpinner)
        body.stop_spinner(hide=False)
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
        cur_avatar = session.avatar_url if session else ""

        with Vertical(id="edit-profile-modal-card", classes="modal-card"):
            yield Static(
                "[bold #58a6ff]✏ EDIT PROFILE INFORMATION[/]\n"
                "[dim]Update your MovieVault handle, email address, or profile photo.[/]"
            )
            yield Static("", id="edit-profile-feedback", classes="modal-feedback")

            yield Label("Username:")
            yield Input(value=cur_user, placeholder="e.g. cinephile_ana", id="inp-edit-username")

            yield Label("Email:")
            yield Input(value=cur_email, placeholder="e.g. ana@movievault.com", id="inp-edit-email")

            yield Label("Profile photo (local path or URL, optional):")
            yield Input(
                value=cur_avatar,
                placeholder="/path/to/photo.png or https://...",
                id="inp-edit-avatar",
            )

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
            msg = "You must be logged in to edit your profile."
            feedback.update(f"[bold #f85149]✖ {msg}[/]")
            show_error_toast(self, msg)
            return

        new_username = self.query_one("#inp-edit-username", Input).value
        new_email = self.query_one("#inp-edit-email", Input).value
        avatar_source = self.query_one("#inp-edit-avatar", Input).value.strip()

        svc = ActionService()
        ok, updated_session, msg = svc.update_user_profile(
            user=session,
            new_username=new_username,
            new_email=new_email,
        )
        if not ok or updated_session is None:
            feedback.update(f"[bold #f85149]✖ {msg}[/]")
            show_error_toast(self, msg)
            return

        if avatar_source and avatar_source != (session.avatar_url or "").strip():
            av_ok, av_session, av_msg = svc.update_user_avatar(
                user=updated_session,
                source_path_or_url=avatar_source,
            )
            if not av_ok or av_session is None:
                feedback.update(f"[bold #f85149]✖ {av_msg}[/]")
                show_error_toast(self, av_msg)
                return
            updated_session = av_session

        auth.update_current_session(updated_session)
        self.dismiss(updated_session)

    def action_cancel(self) -> None:
        self.dismiss(None)



class UploadAvatarModal(ModalScreen[Optional[UserSession]]):
    """Modal to upload a profile photo from a local file path or image URL."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def compose(self) -> ComposeResult:
        session = AuthService().current_session
        cur_avatar = session.avatar_url if session else ""

        with Vertical(id="upload-avatar-modal-card", classes="modal-card"):
            yield Static(
                "[bold #58a6ff]📷 UPLOAD PROFILE PHOTO[/]\n"
                "[dim]Enter a local image path (e.g. ~/Pictures/avatar.png) or an https:// image URL.[/]"
            )
            yield Static("", id="upload-avatar-feedback", classes="modal-feedback")

            yield Label("Image path or URL:")
            yield Input(
                value=cur_avatar,
                placeholder="/path/to/photo.png or https://...",
                id="inp-avatar-source",
            )

            with Horizontal(classes="modal-buttons"):
                yield Button("Save Photo", variant="success", id="btn-save-avatar")
                yield Button("Cancel [Esc]", variant="default", id="btn-cancel-avatar")

    def on_mount(self) -> None:
        self.query_one("#inp-avatar-source", Input).focus()

    @on(Button.Pressed, "#btn-cancel-avatar")
    def _on_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-save-avatar")
    def _on_save(self) -> None:
        self._submit()

    @on(Input.Submitted, "#inp-avatar-source")
    def _on_submit_input(self) -> None:
        self._submit()

    def _submit(self) -> None:
        auth = AuthService()
        session = auth.current_session
        feedback = self.query_one("#upload-avatar-feedback", Static)
        if session is None:
            msg = "You must be logged in to upload a profile photo."
            feedback.update(f"[bold #f85149]✖ {msg}[/]")
            show_error_toast(self, msg)
            return

        source = self.query_one("#inp-avatar-source", Input).value
        ok, updated_session, msg = ActionService().update_user_avatar(
            user=session,
            source_path_or_url=source,
        )
        if ok and updated_session is not None:
            auth.update_current_session(updated_session)
            self.dismiss(updated_session)
        else:
            feedback.update(f"[bold #f85149]✖ {msg}[/]")
            show_error_toast(self, msg)

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
            yield LoadingSpinner(
                "Loading accounts...",
                auto_start=True,
                id="follow-list-status",
            )
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
        status = self.query_one("#follow-list-status", LoadingSpinner)
        status.stop_spinner(hide=False)
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

