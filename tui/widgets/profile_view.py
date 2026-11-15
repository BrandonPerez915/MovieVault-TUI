"""
Reusable Instagram-style Profile view widget (`ProfileView`)
(backend/tui/widgets/profile_view.py).

Used both inside `HomeScreen` ("📊 My Profile" tab) for the active user and
inside `ProfileScreen` when visiting another user's profile.
"""

from typing import Any, Dict, List, Optional

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.message import Message
from textual.widgets import Button, Static, TabbedContent, TabPane
from textual.worker import get_current_worker

from services.ActionService import ActionService
from services.AuthService import AuthService, UserSession
from services.CatalogService import MovieSummary
from services.ProfileService import ProfileService, UserListSummary, UserProfile
from tui.modals import (
    EditProfileModal,
    FollowListModal,
    ReviewMovieModal,
)
from tui.toast import show_success_toast
from tui.widgets.movie_card import MovieCard
from tui.widgets.movie_grid import MovieGrid
from tui.widgets.person_card import populate_carousel_bar
from tui.widgets.poster import PosterImage
from tui.widgets.state_message import StateMessage


class ProfileView(VerticalScroll):
    """Instagram-style user profile component with stats, actions, and sub-tabs."""

    class ProfileUpdated(Message):
        """Emitted when the user edits their profile so parent screens can refresh headers."""

        def __init__(self, view: "ProfileView", session: UserSession) -> None:
            super().__init__()
            self.view = view
            self.session = session

        @property
        def control(self) -> "ProfileView":
            return self.view

    def __init__(
        self,
        target_username: str = "",
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._target_username = (target_username or "").strip().lstrip("@")
        self._profile: Optional[UserProfile] = None
        self._watched_page = 1
        self._reviews_cache: List[Dict[str, Any]] = []
        self._rev_cards_per_row: int = 2
        self._lists_cache: List[UserListSummary] = []
        self._list_offsets: Dict[str, int] = {}
        self._list_row_widgets: Dict[int, tuple[Horizontal, Button, Button]] = {}
        self._movie_cards_per_row: int = 3

    def compose(self) -> ComposeResult:
        with Vertical(id="profile-hero-card", classes="profile-hero-card"):
            with Horizontal(id="prof-avatar-row", classes="profile-avatar-row"):
                yield PosterImage(
                    poster_url="",
                    title="Profile",
                    cells_width=16,
                    cells_height=10,
                    size="w185",
                    kind="person",
                    id="prof-avatar",
                )
            yield Static("", id="prof-identity-banner")
            yield Static("", id="prof-joined-banner")
            with Horizontal(id="prof-follow-row", classes="profile-follow-row"):
                yield Button("Followers (0)", id="btn-prof-followers", classes="profile-stat-link")
                yield Button("Following (0)", id="btn-prof-following", classes="profile-stat-link")
            with Horizontal(id="prof-stats-row", classes="profile-stats-row"):
                yield Static("Reviews: 0", id="stat-reviews", classes="profile-stat-text")
                yield Static("Watched: 0", id="stat-watched", classes="profile-stat-text")
                yield Static("Lists: 0", id="stat-lists", classes="profile-stat-text")

            with Horizontal(id="prof-actions-row", classes="profile-actions-row"):
                yield Button("+ Follow", variant="success", id="btn-prof-follow-toggle")
                yield Button("Edit Profile", variant="primary", id="btn-prof-edit")
                yield Button("View Wrapped", variant="warning", id="btn-prof-wrapped")

        yield StateMessage(id="prof-state-msg")

        with TabbedContent(id="profile-subtabs"):
            with TabPane("💬 Reviews", id="subtab-prof-reviews"):
                yield Vertical(id="prof-reviews-scroll", classes="profile-subtab-body")
            with TabPane("🎬 Watched Movies", id="subtab-prof-watched"):
                yield MovieGrid(page_size=12, id="prof-watched-grid")
            with TabPane("📋 Lists", id="subtab-prof-lists"):
                yield Vertical(id="prof-lists-scroll", classes="profile-subtab-body")

    def on_mount(self) -> None:
        if self._target_username:
            self.load_profile(self._target_username)

    def on_resize(self, event: Resize) -> None:
        new_per_row = self._calc_review_cards_per_row()
        if new_per_row != self._rev_cards_per_row:
            self._rev_cards_per_row = new_per_row
            if self._reviews_cache:
                self._render_reviews_tab(self._reviews_cache)
        new_movie_per_row = self._calc_movie_cards_per_row()
        if new_movie_per_row != self._movie_cards_per_row:
            self._movie_cards_per_row = new_movie_per_row
            for idx in range(len(self._lists_cache)):
                self._update_list_carousel_row(idx)

    def _calc_review_cards_per_row(self) -> int:
        try:
            term_width = self.app.size.width
        except Exception:
            term_width = 120
        usable_width = max(43, term_width - 8)
        return max(1, usable_width // 43)

    def _calc_movie_cards_per_row(self) -> int:
        try:
            term_width = self.app.size.width
        except Exception:
            term_width = 120
        usable_width = max(23, term_width - 24)
        return max(1, usable_width // 23)

    def _is_own_profile(self) -> bool:
        session = AuthService().current_session
        if session is None or not self._target_username:
            return False
        return session.username.lower() == self._target_username.lower()

    def load_profile(self, target_username: str) -> None:
        clean = (target_username or "").strip().lstrip("@")
        if not clean:
            return
        self._target_username = clean
        self._watched_page = 1
        self._sync_action_buttons()
        self.query_one("#prof-state-msg", StateMessage).show_loading(
            f"Loading profile for @{clean}..."
        )
        session = AuthService().current_session
        viewer = session.username if session else ""
        self._fetch_profile_worker(viewer, clean, self._watched_page)

    def _sync_action_buttons(self) -> None:
        own = self._is_own_profile()
        follow_btn = self.query_one("#btn-prof-follow-toggle", Button)
        edit_btn = self.query_one("#btn-prof-edit", Button)
        wrapped_btn = self.query_one("#btn-prof-wrapped", Button)

        follow_btn.display = not own
        edit_btn.display = own
        wrapped_btn.display = own

        if not own and self._profile is not None:
            if self._profile.is_following:
                follow_btn.label = "✓ Following (Unfollow)"
                follow_btn.variant = "default"
            else:
                follow_btn.label = "+ Follow"
                follow_btn.variant = "success"

    @work(thread=True, exclusive=True, group="profile-load")
    def _fetch_profile_worker(
        self,
        viewer_username: str,
        target_username: str,
        watched_page: int,
    ) -> None:
        worker = get_current_worker()
        svc = ProfileService()
        profile = svc.get_user_profile(viewer_username, target_username)
        reviews, reviews_total = svc.get_user_reviews(target_username, page=1, page_size=20)
        watched, watched_total = svc.get_user_watched_movies(
            target_username, page=watched_page, page_size=12
        )
        lists = svc.get_user_lists(target_username)

        if not worker.is_cancelled:
            self.app.call_from_thread(
                self._render_profile,
                profile,
                reviews,
                reviews_total,
                watched,
                watched_total,
                lists,
            )

    def _render_profile(
        self,
        profile: Optional[UserProfile],
        reviews: List[Dict[str, Any]],
        reviews_total: int,
        watched: List[MovieSummary],
        watched_total: int,
        lists: List[UserListSummary],
    ) -> None:
        state = self.query_one("#prof-state-msg", StateMessage)
        if profile is None:
            state.show_empty(
                f"User @{self._target_username} was not found.",
                "Verify the username and try again.",
            )
            return

        state.clear_state()
        self._profile = profile
        own = self._is_own_profile()
        session = AuthService().current_session
        badge = " [bold #3fb950](You)[/]" if own else ""
        avatar_url = profile.avatar_url or (session.avatar_url if own and session else "")

        self.query_one("#prof-avatar", PosterImage).set_poster(
            avatar_url,
            title=profile.username,
        )
        self.query_one("#prof-identity-banner", Static).update(
            f"[bold #58a6ff]@{profile.username}[/]{badge}"
        )
        joined_banner = self.query_one("#prof-joined-banner", Static)
        if profile.created_at:
            joined_banner.display = True
            joined_banner.update(f"[dim]Joined {profile.created_at}[/]")
        else:
            joined_banner.display = False
            joined_banner.update("")

        self.query_one("#stat-reviews", Static).update(
            f"[bold]{max(profile.reviews_count, reviews_total)}[/] Reviews"
        )
        self.query_one("#stat-watched", Static).update(
            f"[bold]{max(profile.watched_count, watched_total)}[/] Watched"
        )
        self.query_one("#stat-lists", Static).update(
            f"[bold]{max(profile.lists_count, len(lists))}[/] Lists"
        )
        self.query_one("#btn-prof-followers", Button).label = (
            f"Followers ({profile.followers_count})"
        )
        self.query_one("#btn-prof-following", Button).label = (
            f"Following ({profile.following_count})"
        )

        self._sync_action_buttons()
        self._render_reviews_tab(reviews)
        self.query_one("#prof-watched-grid", MovieGrid).set_movies(
            watched,
            page=self._watched_page,
            total=watched_total,
            page_size=12,
        )
        self._render_lists_tab(lists)

    def _render_reviews_tab(self, reviews: List[Dict[str, Any]]) -> None:
        self._reviews_cache = list(reviews)
        scroll = self.query_one("#prof-reviews-scroll", Vertical)
        scroll.remove_children()
        if not reviews:
            scroll.mount(
                Static(
                    f"[dim]@{self._target_username} has not published any reviews yet.[/]",
                    classes="profile-empty-hint",
                )
            )
            return

        session = AuthService().current_session
        cur_user = session.username if session else ""
        own = self._is_own_profile()
        per_row = self._calc_review_cards_per_row()
        self._rev_cards_per_row = per_row
        cards: List[Vertical] = []

        for r in reviews:
            m_title = str(r.get("movie_title", "Untitled"))
            m_key = str(r.get("movie_id") or m_title)
            rating = float(r.get("rating") or 0.0)
            likes = int(r.get("likes") or 0)
            created = str(r.get("created_at", ""))
            content = str(r.get("content", ""))
            liked_by = {str(u).lower() for u in (r.get("liked_by") or [])}
            user_liked = bool(cur_user and cur_user.lower() in liked_by)

            action_buttons: List[Button] = [
                Button(
                    f"Liked ({likes})" if user_liked else f"Like ({likes})",
                    variant="error" if user_liked else "default",
                    name=m_title,
                    classes="btn-prof-like-review",
                ),
            ]
            if own:
                action_buttons.append(
                    Button(
                        "Edit Review",
                        variant="warning",
                        name=m_title,
                        classes="btn-prof-edit-review",
                    )
                )

            card = Vertical(
                Horizontal(
                    Button(
                        m_title,
                        name=m_key,
                        classes="review-movie-title-link",
                    ),
                    Static(
                        f"  [bold #f0883e]★ {rating:.1f}[/]  "
                        f"[bold #3fb950]♥ {likes}[/]  [dim]{created}[/]",
                        classes="review-card-meta",
                    ),
                    classes="review-card-header",
                ),
                Static(content, classes="review-item-body"),
                Horizontal(*action_buttons, classes="review-card-actions"),
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

    def _render_lists_tab(self, lists: List[UserListSummary]) -> None:
        self._lists_cache = list(lists)
        self._movie_cards_per_row = self._calc_movie_cards_per_row()
        self._list_row_widgets.clear()
        scroll = self.query_one("#prof-lists-scroll", Vertical)
        scroll.remove_children()
        if not lists:
            scroll.mount(
                Static(
                    f"[dim]@{self._target_username} has no public lists yet.[/]",
                    classes="profile-empty-hint",
                )
            )
            return

        for idx, lst in enumerate(lists):
            self._list_offsets.setdefault(lst.name, 0)
            card = Vertical(classes="list-item-card")
            scroll.mount(card)
            card.mount(
                Static(
                    f"[bold #d2a8ff]📋 {lst.name}[/]  [dim]({lst.movies_count} movies)[/]"
                )
            )
            if lst.description:
                card.mount(Static(f"[dim]{lst.description}[/]"))
            if not lst.movies:
                card.mount(Static("[dim]Empty list[/]"))
            else:
                row = Horizontal(classes="carousel-row")
                card.mount(row)
                btn_prev = Button(
                    "<",
                    name=f"prev|{idx}",
                    classes="carousel-nav-btn prof-list-nav",
                )
                bar = Horizontal(classes="chips-bar prof-list-bar")
                btn_next = Button(
                    ">",
                    name=f"next|{idx}",
                    classes="carousel-nav-btn prof-list-nav",
                )
                self._list_row_widgets[idx] = (bar, btn_prev, btn_next)
                row.mount(btn_prev)
                row.mount(bar)
                row.mount(btn_next)
                self._update_list_carousel_row(idx)

    def _update_list_carousel_row(self, idx: int) -> None:
        if not (0 <= idx < len(self._lists_cache)):
            return
        lst = self._lists_cache[idx]
        if not lst.movies:
            return
        widgets = self._list_row_widgets.get(idx)
        if widgets is None:
            return
        bar, btn_prev, btn_next = widgets
        per_row = self._movie_cards_per_row
        bar.remove_children()

        max_offset = max(0, len(lst.movies) - per_row)
        offset = max(0, min(self._list_offsets.get(lst.name, 0), max_offset))
        self._list_offsets[lst.name] = offset

        show_nav = len(lst.movies) > per_row
        btn_prev.display = show_nav
        btn_next.display = show_nav
        if show_nav:
            btn_prev.disabled = offset <= 0
            btn_next.disabled = offset >= max_offset

        cards = [
            MovieCard(m)
            for m in lst.movies[offset : offset + per_row]
        ]
        populate_carousel_bar(bar, cards, per_row)

    @on(Button.Pressed, ".prof-list-nav")
    def _on_prof_list_nav(self, event: Button.Pressed) -> None:
        raw = event.button.name or ""
        parts = raw.split("|", 1)
        if len(parts) != 2:
            return
        direction, idx_str = parts
        try:
            idx = int(idx_str)
        except ValueError:
            return
        if not (0 <= idx < len(self._lists_cache)):
            return
        lst = self._lists_cache[idx]
        cur_offset = self._list_offsets.get(lst.name, 0)
        if direction == "prev" and cur_offset > 0:
            self._list_offsets[lst.name] = cur_offset - 1
            self._update_list_carousel_row(idx)
        elif direction == "next" and cur_offset + self._movie_cards_per_row < len(lst.movies):
            self._list_offsets[lst.name] = cur_offset + 1
            self._update_list_carousel_row(idx)

    # =========================================================================
    # INTERACTIONS
    # =========================================================================

    @on(Button.Pressed, "#btn-prof-follow-toggle")
    def _on_follow_toggle(self) -> None:
        session = AuthService().current_session
        state = self.query_one("#prof-state-msg", StateMessage)
        if session is None:
            state.show_error("Sign in to follow or unfollow users.")
            return

        action_svc = ActionService()
        currently_following = bool(self._profile and self._profile.is_following)
        if currently_following:
            ok, msg = action_svc.unfollow_user(session, self._target_username)
        else:
            ok, msg = action_svc.follow_user(session, self._target_username)

        if ok:
            if self._profile is not None:
                self._profile.is_following = not currently_following
                delta = -1 if currently_following else 1
                self._profile.followers_count = max(0, self._profile.followers_count + delta)
                self.query_one("#btn-prof-followers", Button).label = (
                    f"Followers ({self._profile.followers_count})"
                )
                self._sync_action_buttons()
            state.show_success(msg)
        else:
            state.show_error(msg)

    @on(Button.Pressed, "#btn-prof-edit")
    def _on_edit_profile(self) -> None:
        def _after(updated: Optional[UserSession]) -> None:
            if updated is not None:
                self._target_username = updated.username
                self.post_message(self.ProfileUpdated(self, updated))
                self.load_profile(updated.username)
                self.query_one("#prof-state-msg", StateMessage).show_success(
                    f"Profile updated for @{updated.username}."
                )

        self.app.push_screen(EditProfileModal(), _after)

    @on(Button.Pressed, "#btn-prof-wrapped")
    def _on_open_wrapped(self) -> None:
        if self._target_username:
            from tui.screens.user.wrapped import WrappedScreen

            self.app.push_screen(WrappedScreen(self._target_username))

    @on(Button.Pressed, "#btn-prof-followers")
    def _on_open_followers(self) -> None:
        self._open_follow_modal("followers")

    @on(Button.Pressed, "#btn-prof-following")
    def _on_open_following(self) -> None:
        self._open_follow_modal("following")

    def _open_follow_modal(self, mode: str) -> None:
        if not self._target_username:
            return

        def _after(selected_username: Optional[str]) -> None:
            if selected_username:
                self._open_user_profile(selected_username)

        self.app.push_screen(
            FollowListModal(self._target_username, mode=mode),  # type: ignore[arg-type]
            _after,
        )

    def _open_user_profile(self, username: str) -> None:
        from tui.screens.user.profile import ProfileScreen

        self.app.push_screen(ProfileScreen(username))

    @on(Button.Pressed, ".review-movie-title-link")
    def _on_open_movie_btn(self, event: Button.Pressed) -> None:
        if event.button.name:
            from tui.screens.user.movie_detail import MovieDetailScreen

            self.app.push_screen(MovieDetailScreen(event.button.name))

    @on(Button.Pressed, ".btn-prof-like-review")
    def _on_prof_like_review(self, event: Button.Pressed) -> None:
        movie_title = (event.button.name or "").strip()
        session = AuthService().current_session
        state = self.query_one("#prof-state-msg", StateMessage)
        if session is None:
            state.show_error("Sign in to like reviews.")
            return
        ok, msg = ActionService().like_review(
            session, movie_title, self._target_username
        )
        if ok:
            state.show_success(msg)
            self.load_profile(self._target_username)
        else:
            state.show_error(msg)

    @on(Button.Pressed, ".btn-prof-edit-review")
    def _on_prof_edit_review(self, event: Button.Pressed) -> None:
        movie_title = (event.button.name or "").strip()
        if not movie_title:
            return

        def _after(msg: Optional[str]) -> None:
            if msg:
                self.load_profile(self._target_username)
                self.query_one("#prof-state-msg", StateMessage).show_success(msg)

        self.app.push_screen(ReviewMovieModal(movie_title=movie_title), _after)

    @on(MovieCard.Selected)
    def _on_watched_card_selected(self, event: MovieCard.Selected) -> None:
        event.stop()
        from tui.screens.user.movie_detail import MovieDetailScreen

        self.app.push_screen(MovieDetailScreen(event.movie_id or event.title))

    @on(MovieGrid.PageRequested, "#prof-watched-grid")
    def _on_watched_page(self, event: MovieGrid.PageRequested) -> None:
        self._watched_page = event.page
        session = AuthService().current_session
        viewer = session.username if session else ""
        self._fetch_profile_worker(viewer, self._target_username, self._watched_page)
