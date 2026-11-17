"""
Dedicated Query Results Screen (`QueryResultsScreen`)
(tui/screens/user/query_results_screen.py).

Executes Activity (Cassandra) and For You / Recommendations (Dgraph) queries
in the background (`@work(thread=True)`) and displays tabular results in a
dedicated screen, matching `SearchResultsScreen`'s navigation flow.
"""

import math
from typing import Any, Dict, List, Optional

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Static
from textual.worker import get_current_worker

from services.ActionService import ActionService
from services.AuthService import AuthService
from services.QueryService import (
    QueryResult,
    execute_query,
    format_cell_value,
    get_column_label,
)
from tui.screens.user.movie_detail import MovieDetailScreen
from tui.widgets.person_card import populate_carousel_bar
from tui.widgets.state_message import StateMessage
from tui.widgets.user_card import UserCard


class QueryResultsScreen(Screen):
    """Displays tabular query results (Activity / For You) in a dedicated view."""

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True, priority=True),
    ]

    def __init__(
        self,
        query_id: str,
        params: Dict[str, str],
        section_title: str,
        breadcrumb: str = "Results",
        back_label: str = "◀ Back [Esc]",
        loading_msg: str = "Running query...",
        empty_title: str = "No records found.",
        empty_hint: str = "Try adjusting your filters or verifying your records.",
    ) -> None:
        super().__init__()
        self._query_id = query_id
        self._params = dict(params)
        self._section_title = section_title
        self._breadcrumb = breadcrumb
        self._back_label = back_label
        self._loading_msg = loading_msg
        self._empty_title = empty_title
        self._empty_hint = empty_hint
        self._rows: List[Dict[str, Any]] = []
        self._last_result: Optional[QueryResult] = None
        self._page: int = 1
        self._total_pages: int = 1

    def compose(self) -> ComposeResult:
        yield Static(
            f"[bold #58a6ff]{self._section_title}[/]  ›  [bold]{self._breadcrumb}[/]",
            id="top-bar",
        )
        with Vertical(classes="detail-page-container"):
            with Horizontal(classes="detail-top-actions"):
                yield Button(self._back_label, variant="default", id="btn-query-back")
                yield Static("", id="query-summary-banner")

            yield StateMessage(id="query-state-msg")
            yield DataTable(id="query-results-table")
            with VerticalScroll(id="query-users-scroll", classes="movie-grid-scroll"):
                yield Grid(id="query-users-grid", classes="movie-grid-inner")
            yield VerticalScroll(id="query-cards-scroll", classes="movie-grid-scroll")
            with Horizontal(id="query-pagination-bar", classes="pagination-bar"):
                yield Button("<", id="btn-qr-prev", classes="page-btn")
                yield Static("Page 1 of 1", id="qr-page-info", classes="page-info")
                yield Button(">", id="btn-qr-next", classes="page-btn")

    def on_mount(self) -> None:
        self.query_one("#query-users-scroll", VerticalScroll).display = False
        self.query_one("#query-cards-scroll", VerticalScroll).display = False
        self.query_one("#query-pagination-bar", Horizontal).display = False
        table = self.query_one("#query-results-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True

        state = self.query_one("#query-state-msg", StateMessage)
        state.show_loading(self._loading_msg)
        self._execute_worker(self._query_id, dict(self._params))

    def on_resize(self, event: Resize) -> None:
        self._update_user_grid_columns()

    def _update_user_grid_columns(self) -> None:
        try:
            width = self.size.width or self.app.size.width or 100
            available = max(22, width - 8)
            cols = max(1, (available + 2) // 24)
            self.query_one("#query-users-grid", Grid).styles.grid_size_columns = cols
        except Exception:
            pass

    @work(thread=True, exclusive=True)
    def _execute_worker(self, query_id: str, params: Dict[str, str]) -> None:
        worker = get_current_worker()
        res = execute_query(query_id, params)
        if not worker.is_cancelled:
            self.app.call_from_thread(self._render_result, res)

    def _update_pagination(self, total: int, page_size: int, unit: str) -> None:
        bar = self.query_one("#query-pagination-bar", Horizontal)
        self._total_pages = max(1, math.ceil(total / max(1, page_size)))
        if self._total_pages <= 1:
            bar.display = False
            return
        bar.display = True
        self.query_one("#qr-page-info", Static).update(
            f"[bold #79c0ff]Page {self._page} of {self._total_pages}[/]  [dim]({total} {unit})[/]"
        )
        self.query_one("#btn-qr-prev", Button).disabled = self._page <= 1
        self.query_one("#btn-qr-next", Button).disabled = self._page >= self._total_pages

    def _render_result(self, result: QueryResult) -> None:
        self._last_result = result
        state = self.query_one("#query-state-msg", StateMessage)
        banner = self.query_one("#query-summary-banner", Static)
        table = self.query_one("#query-results-table", DataTable)
        users_scroll = self.query_one("#query-users-scroll", VerticalScroll)
        users_grid = self.query_one("#query-users-grid", Grid)
        cards_scroll = self.query_one("#query-cards-scroll", VerticalScroll)
        pag_bar = self.query_one("#query-pagination-bar", Horizontal)
        table.clear(columns=True)
        users_grid.remove_children()
        cards_scroll.remove_children()

        is_social_user_cards = self._query_id == "social_users" or (
            self._section_title == "👥 SOCIAL"
            and self._query_id in ("dgraph_req_1", "dgraph_req_6")
        )

        if is_social_user_cards:
            table.display = False
            cards_scroll.display = False
            if not result.rows:
                users_scroll.display = False
                pag_bar.display = False
                banner.update("")
                state.show_empty(self._empty_title, self._empty_hint)
                return

            state.clear_state()
            users_scroll.display = True
            width = self.size.width or self.app.size.width or 100
            cols = max(1, (max(22, width - 8) + 2) // 24)
            self._update_user_grid_columns()
            page_size = cols * 2
            total = len(result.rows)
            total_pages = max(1, math.ceil(total / page_size))
            self._page = max(1, min(self._page, total_pages))
            page_rows = result.rows[(self._page - 1) * page_size : self._page * page_size]
            self._rows = list(page_rows)

            cards: List[UserCard] = []
            for r in page_rows:
                uname = str(
                    r.get("username")
                    or r.get("recommended_user")
                    or r.get("potential_friend")
                    or r.get("friend")
                    or ""
                )
                if not uname:
                    continue
                card = UserCard(
                    username=uname,
                    avatar_url=str(r.get("avatar_url") or ""),
                    reviews_count=int(r.get("reviews_count") or 0),
                    watched_count=int(r.get("watched_count") or 0),
                    lists_count=int(r.get("lists_count") or 0),
                    followers_count=int(r.get("followers_count") or r.get("followers") or 0),
                )
                cards.append(card)
                users_grid.mount(card)

            self._update_pagination(total, page_size, "users")
            banner.update(
                f"[bold #79c0ff]{total} users found[/]  "
                "[dim](Press Enter or click a card to view profile)[/]"
            )
            if cards:
                cards[0].focus()
            return

        if self._query_id in ("social_reviews", "social_recent_activity"):
            table.display = False
            users_scroll.display = False
            if not result.rows:
                cards_scroll.display = False
                pag_bar.display = False
                banner.update("")
                state.show_empty(self._empty_title, self._empty_hint)
                return

            state.clear_state()
            cards_scroll.display = True
            session = AuthService().current_session
            cur_user = session.username if session else ""
            per_row = max(1, (max(43, (self.size.width or self.app.size.width or 120) - 8)) // 43)
            page_size = per_row * 2
            total = len(result.rows)
            total_pages = max(1, math.ceil(total / page_size))
            self._page = max(1, min(self._page, total_pages))
            page_rows = result.rows[(self._page - 1) * page_size : self._page * page_size]
            self._rows = list(page_rows)
            card_widgets: List[Vertical] = []

            for r in page_rows:
                uname = str(r.get("username") or "anonymous")
                m_title = str(r.get("movie_title") or "Untitled")
                created = str(r.get("created_at") or "")
                if self._query_id == "social_reviews":
                    rating = float(r.get("rating") or 0.0)
                    likes = int(r.get("likes") or 0)
                    content = str(r.get("content") or "").strip()
                    liked_by = {str(u).lower() for u in (r.get("_liked_by") or [])}
                    user_liked = bool(cur_user and cur_user.lower() in liked_by)
                    card_widgets.append(
                        Vertical(
                            Horizontal(
                                Button(
                                    f"@{uname}",
                                    name=uname,
                                    classes="review-movie-title-link btn-qr-author-link",
                                ),
                                Static(
                                    f"  [bold #f0883e]★ {rating:.1f}[/]  "
                                    f"[bold #3fb950]♥ {likes}[/]  [dim]{created}[/]",
                                    classes="review-card-meta",
                                ),
                                classes="review-card-header",
                            ),
                            Button(
                                m_title,
                                name=m_title,
                                classes="review-movie-title-link btn-qr-movie-link",
                            ),
                            Static(content, classes="review-item-body"),
                            Horizontal(
                                Button(
                                    f"Liked ({likes})" if user_liked else f"Like ({likes})",
                                    variant="error" if user_liked else "default",
                                    name=f"{uname}||{m_title}",
                                    classes="btn-qr-like-review",
                                ),
                                classes="review-card-actions",
                            ),
                            classes="review-item-card",
                        )
                    )
                else:
                    action_lbl = str(r.get("action") or "Activity")
                    badge_color = "#3fb950" if action_lbl.lower() == "reviewed" else "#58a6ff"
                    detail = str(r.get("detail") or "")
                    card_widgets.append(
                        Vertical(
                            Horizontal(
                                Button(
                                    f"@{uname}",
                                    name=uname,
                                    classes="review-movie-title-link btn-qr-author-link",
                                ),
                                Static(
                                    f"  [bold {badge_color}]{action_lbl}[/]  [dim]{created}[/]",
                                    classes="review-card-meta",
                                ),
                                classes="review-card-header",
                            ),
                            Button(
                                m_title,
                                name=m_title,
                                classes="review-movie-title-link btn-qr-movie-link",
                            ),
                            Static(detail, classes="review-item-body"),
                            classes="review-item-card",
                        )
                    )

            for idx in range(0, len(card_widgets), per_row):
                row_bar = Horizontal(classes="reviews-row")
                cards_scroll.mount(row_bar)
                populate_carousel_bar(
                    row_bar,
                    card_widgets[idx : idx + per_row],
                    per_row,
                    empty_slot_class="carousel-review-empty-slot",
                )

            label_kind = "reviews" if self._query_id == "social_reviews" else "activity records"
            self._update_pagination(total, page_size, label_kind)
            banner.update(
                f"[bold #79c0ff]{total} {label_kind} found[/]  "
                "[dim](Click @username or movie title to open)[/]"
            )
            return

        users_scroll.display = False
        cards_scroll.display = False
        table.display = True
        for col in result.columns:
            table.add_column(get_column_label(col))

        if not result.rows:
            pag_bar.display = False
            banner.update("")
            state.show_empty(self._empty_title, self._empty_hint)
            return

        state.clear_state()
        page_size = 12
        total = len(result.rows)
        total_pages = max(1, math.ceil(total / page_size))
        self._page = max(1, min(self._page, total_pages))
        page_rows = result.rows[(self._page - 1) * page_size : self._page * page_size]
        self._rows = list(page_rows)
        for r in page_rows:
            table.add_row(*[format_cell_value(c, r.get(c)) for c in result.columns])

        self._update_pagination(total, page_size, "results")
        has_movie_titles = any(r.get("movie_title") for r in page_rows)
        has_usernames = any(r.get("username") for r in page_rows)
        if has_movie_titles:
            hint = "  [dim](Press Enter or click a row to view movie details)[/]"
        elif has_usernames:
            hint = "  [dim](Press Enter or click a row to view user profile)[/]"
        else:
            hint = ""
        banner.update(f"[bold #79c0ff]{total} results found[/]{hint}")
        table.focus()

    @on(DataTable.RowSelected, "#query-results-table")
    def _on_row_selected(self, event: DataTable.RowSelected) -> None:
        idx = event.cursor_row
        if 0 <= idx < len(self._rows):
            row = self._rows[idx]
            title = row.get("movie_title")
            if title:
                self.app.push_screen(MovieDetailScreen(str(title)))
                return
            uname = row.get("username")
            if uname:
                from tui.screens.user.profile import ProfileScreen

                self.app.push_screen(ProfileScreen(str(uname)))

    @on(UserCard.Selected)
    def _on_user_card_selected(self, event: UserCard.Selected) -> None:
        if event.username:
            from tui.screens.user.profile import ProfileScreen

            self.app.push_screen(ProfileScreen(event.username))

    @on(Button.Pressed, ".btn-qr-author-link")
    def _on_qr_author_link(self, event: Button.Pressed) -> None:
        uname = (event.button.name or "").strip()
        if uname:
            from tui.screens.user.profile import ProfileScreen

            self.app.push_screen(ProfileScreen(uname))

    @on(Button.Pressed, ".btn-qr-movie-link")
    def _on_qr_movie_link(self, event: Button.Pressed) -> None:
        title = (event.button.name or "").strip()
        if title:
            self.app.push_screen(MovieDetailScreen(title))

    @on(Button.Pressed, ".btn-qr-like-review")
    def _on_qr_like_review(self, event: Button.Pressed) -> None:
        raw = str(event.button.name or "")
        if "||" not in raw:
            return
        owner, title = raw.split("||", 1)
        session = AuthService().current_session
        state = self.query_one("#query-state-msg", StateMessage)
        if session is None:
            state.show_error("Sign in to like reviews.")
            return
        ok, msg = ActionService().like_review(session, title, owner)
        if ok:
            state.show_success(msg)
            self._execute_worker(self._query_id, dict(self._params))
        else:
            state.show_error(msg)

    @on(Button.Pressed, "#btn-qr-prev")
    def _on_qr_prev(self) -> None:
        if self._page > 1 and self._last_result is not None:
            self._page -= 1
            self._render_result(self._last_result)

    @on(Button.Pressed, "#btn-qr-next")
    def _on_qr_next(self) -> None:
        if self._page < self._total_pages and self._last_result is not None:
            self._page += 1
            self._render_result(self._last_result)

    @on(Button.Pressed, "#btn-query-back")
    def _on_back(self) -> None:
        self.action_go_back()

    def action_go_back(self) -> None:
        self.app.pop_screen()
