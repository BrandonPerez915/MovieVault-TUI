"""
User View Main Screen (`HomeScreen`)
(backend/tui/screens/user/home_screen.py).

Designed in the style of a modern Letterboxd frontend:
- Clean tabbed navigation without cluttering the screen:
  1. 🍿 Home (Paginated grid of popular movies with posters)
  2. 🔍 Search (Accessible vertical form per mode -> opens dedicated results page)
  3. 📖 My Diary (Watch history, reviews, likes, lists, and followed accounts)
  4. ✨ For You (Movie and friend affinity recommendations)
  5. 📋 My Lists (Manage personal movie lists)
  6. 📊 My Profile (Instagram-style profile, reviews, watched movies, lists & Wrapped)
- No technical database jargon, raw queries, or latencies.
"""

from typing import Any, Dict, List, Optional, Tuple

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Input,
    Label,
    ListItem,
    ListView,
    Select,
    Static,
    TabbedContent,
    TabPane,
)
from textual.worker import get_current_worker

from databases.mongodb import MongoConnection
from services.ActionService import ActionService
from services.AuthService import AuthService, UserSession
from services.CatalogService import CatalogService, MovieSummary
from services.PosterService import PosterService
from services.ProfileService import ProfileService, UserListSummary
from services.QueryService import (
    QueryResult,
    execute_query,
    format_cell_value,
    get_column_label,
    get_query_by_id,
)
from tui.modals import (
    AddMovieToListModal,
    ConfirmModal,
    CreateListModal,
    ManageListModal,
    ReviewMovieModal,
    SocialActionModal,
    UserMenuModal,
    UserSwitchModal,
)
from tui.screens.help import HelpScreen
from tui.screens.settings import SettingsScreen
from tui.screens.user.movie_detail import MovieDetailScreen
from tui.screens.user.person import PersonScreen
from tui.screens.user.query_results import QueryResultsScreen
from tui.screens.user.reviews import ReviewsScreen
from tui.screens.user.search_results import SearchResultsScreen
from tui.toast import show_success_toast
from tui.widgets.figlet_header import FigletHeader, render_figlet_markup
from tui.widgets.movie_card import MovieCard
from tui.widgets.movie_grid import MovieGrid
from tui.widgets.person_card import populate_carousel_bar
from tui.widgets.poster import PosterImage
from tui.widgets.profile_view import ProfileView
from tui.widgets.state_message import StateMessage

SEARCH_MODES = [
    ("Movies by title, decade, and language", "mongo_req_1"),
    ("Movies by genre, country, and director", "mongo_req_2"),
    ("Movies by rating, director, and decade", "mongo_req_3"),
    ("Movies by keywords in synopsis", "mongo_req_4"),
    ("Movies by actor and/or director", "mongo_req_6"),
    ("Actor impact analysis and filmography", "mongo_req_7"),
]

DIARY_MODES = [
    ("Recently watched movies", "cassandra_req_1"),
    ("Watched movies filtered by genre", "cassandra_req_2"),
    ("My published reviews", "cassandra_req_3"),
    ("My reviews by rating range", "cassandra_req_4"),
    ("Review history for a movie", "cassandra_req_5"),
    ("Liked reviews", "cassandra_req_6"),
    ("My movie list activity", "cassandra_req_7"),
    ("Followed accounts", "cassandra_req_8"),
]

REC_MODES = [
    ("Users who liked my favorite review", "dgraph_req_1"),
    ("Movies watched by friends in last 7 days", "dgraph_req_2"),
    ("Same-genre movies not in my list", "dgraph_req_3"),
    ("Movies liked by friends (same director)", "dgraph_req_4"),
    ("Movies with actors from films I liked", "dgraph_req_5"),
    ("Potential friends with shared tastes (≥5 in common)", "dgraph_req_6"),
    ("Unwatched movies in my list liked by friends", "dgraph_req_7"),
    ("Movies by recent Actor + Director combo", "dgraph_req_8"),
]

HOME_ASCII_BANNER = render_figlet_markup(
    "MovieVault",
    font="slant",
    color="#58a6ff",
    subtitle="Your Personal Film Catalog, Reviews & Discovery Vault",
)


def _format_user_menu_label(session: Optional[UserSession]) -> str:
    return f"@{session.username} ▾" if session else "Explorer ▾"


class HomeScreen(Screen):
    """Accessible Letterboxd-style main screen for end users."""

    BINDINGS = [
        Binding("f1", "open_help", "Help", show=True, priority=True),
        Binding("f2", "open_settings", "Settings", show=True, priority=True),
        Binding("slash", "focus_search", "Search", show=True),
        Binding("1", "goto_tab('tab-home')", "Home", show=False),
        Binding("2", "goto_tab('tab-lists')", "Lists", show=False),
        Binding("3", "goto_tab('tab-explore')", "Explore", show=False),
        Binding("4", "goto_tab('tab-profile')", "Profile", show=False),
        Binding("ctrl+n", "open_review_modal", "Review", show=True, priority=True),
        Binding("ctrl+b", "open_list_modal", "My Lists", show=True, priority=True),
        Binding("ctrl+u", "switch_user", "Switch User", show=True, priority=True),
        Binding("ctrl+l", "logout", "Log Out", show=True, priority=True),
        Binding("ctrl+q", "app.quit", "Quit", show=True, priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._popular_page = 1
        self._foryou_movies: List[MovieSummary] = []
        self._foryou_offset: int = 0
        self._genre_sections: List[Tuple[str, List[MovieSummary]]] = []
        self._genre_offsets: Dict[str, int] = {}
        self._cards_per_row: int = 3
        self._user_lists: List[UserListSummary] = []
        self._selected_list_name: str = ""

    def compose(self) -> ComposeResult:
        session = AuthService().current_session
        with Horizontal(id="top-bar"):
            yield Static("[bold #58a6ff]∅ MOVIEVAULT[/]", id="top-bar-brand")
            yield Static("", id="top-bar-spacer")
            yield Button(_format_user_menu_label(session), id="btn-user-menu")

        with TabbedContent(id="user-tabs"):
            # -------------------- TAB 1: HOME --------------------
            with TabPane("Home", id="tab-home"):
                with VerticalScroll(id="home-netflix-scroll", classes="detail-page-scroll"):
                    with Vertical(id="home-hero-header"):
                        yield Static(HOME_ASCII_BANNER, id="home-ascii-banner")
                        with Horizontal(id="home-search-row"):
                            yield Input(
                                placeholder="Search movies by title (press Enter)...",
                                id="home-quick-search-input",
                            )
                            yield Button(
                                "🔍 Search",
                                variant="success",
                                id="btn-home-quick-search",
                            )

                    yield StateMessage(id="home-state-msg")

                    yield Static(
                        "FOR YOU — RECOMMENDED MOVIES:",
                        classes="panel-heading",
                    )
                    with Horizontal(classes="carousel-row"):
                        yield Button("<", id="btn-foryou-prev", classes="carousel-nav-btn")
                        yield Horizontal(id="home-foryou-bar", classes="chips-bar")
                        yield Button(">", id="btn-foryou-next", classes="carousel-nav-btn")

                    yield Vertical(id="home-genres-container")

            # -------------------- TAB 2: MY LISTS --------------------
            with TabPane("Lists", id="tab-lists"):
                with Vertical(classes="tab-page-container"):
                    yield StateMessage(id="lists-state-msg")

                    with Horizontal(id="lists-workspace"):
                        with Vertical(id="lists-sidebar"):
                            yield Static("Your Lists:", classes="panel-heading")
                            yield ListView(id="my-lists-listview")
                            yield Button("＋ New List", variant="success", id="btn-lists-create")
                        with Vertical(id="lists-detail-panel"):
                            yield FigletHeader(
                                "Select a list",
                                font="smslant",
                                color="#d2a8ff",
                                subtitle="Select a list on the left",
                                id="lists-selected-heading",
                            )
                            yield Static("", id="lists-selected-description")
                            with Horizontal(id="lists-detail-actions"):
                                yield Button("＋ Add Movie", variant="primary", id="btn-lists-add-movie")
                                yield Button("Delete List", variant="error", id="btn-lists-delete")
                            yield MovieGrid(
                                page_size=12,
                                id="my-lists-movie-grid",
                                removable=True,
                            )

            # -------------------- TAB 3: EXPLORE (MOVIES, ACTIVITY, RECOMMENDATIONS) --------------------
            with TabPane("Explore", id="tab-explore"):
                with VerticalScroll(classes="tab-page-scroll"):
                    with Vertical(id="explore-container"):
                        with Horizontal(id="explore-selector-bar"):
                            yield Label("Section:")
                            yield Select(
                                [
                                    ("Movies", "movies"),
                                    ("Activity", "activity"),
                                    ("Recommendations", "recs"),
                                ],
                                value="movies",
                                allow_blank=False,
                                id="explore-section-select",
                            )

                        with Vertical(id="search-form-card", classes="query-form-card"):
                            yield FigletHeader(
                                "Movies",
                                font="slant",
                                color="#58a6ff",
                                subtitle="Choose how to search. If a movie is not in your local catalog, it will automatically be fetched from TMDB.",
                            )
                            yield Label("Search criteria:", classes="field-label")
                            yield Select(
                                SEARCH_MODES,
                                value="mongo_req_1",
                                allow_blank=False,
                                id="search-mode-select",
                                classes="form-mode-select",
                            )
                            yield Vertical(id="search-dynamic-fields")
                            with Horizontal(classes="form-submit-row"):
                                yield Button(
                                    "🔍 Search [Enter]",
                                    variant="success",
                                    id="btn-submit-search",
                                )

                        with Vertical(id="diary-form-card", classes="query-form-card"):
                            yield FigletHeader(
                                "Activity",
                                font="slant",
                                color="#58a6ff",
                                subtitle="Choose an activity query for your active session. Results open in a dedicated view.",
                            )
                            yield Label("Activity to query:", classes="field-label")
                            yield Select(
                                DIARY_MODES,
                                value="cassandra_req_1",
                                allow_blank=False,
                                id="diary-mode-select",
                                classes="form-mode-select",
                            )
                            yield Vertical(id="diary-dynamic-fields")
                            with Horizontal(classes="form-submit-row"):
                                yield Button(
                                    "🔍 Search [Enter]",
                                    variant="success",
                                    id="btn-run-diary",
                                )

                        with Vertical(id="rec-form-card", classes="query-form-card"):
                            yield FigletHeader(
                                "Recommendations",
                                font="smslant",
                                color="#58a6ff",
                                subtitle="Choose a recommendation criterion based on your profile and friends. Results open in a dedicated view.",
                            )
                            yield Label("Recommendation type:", classes="field-label")
                            yield Select(
                                REC_MODES,
                                value="dgraph_req_2",
                                allow_blank=False,
                                id="rec-mode-select",
                                classes="form-mode-select",
                            )
                            yield Vertical(id="rec-dynamic-fields")
                            with Horizontal(classes="form-submit-row"):
                                yield Button(
                                    "🔍 Search [Enter]",
                                    variant="success",
                                    id="btn-run-recs",
                                )

            # -------------------- TAB 6: MY PROFILE --------------------
            with TabPane("Profile", id="tab-profile"):
                with Vertical(classes="tab-page-container"):
                    yield ProfileView(
                        target_username=session.username if session else "",
                        id="my-profile-view",
                    )

    def on_mount(self) -> None:
        for btn_id in ("#btn-foryou-prev", "#btn-foryou-next"):
            self.query_one(btn_id, Button).display = False

        self._refresh_header()
        self._set_explore_section("movies")
        self._rebuild_search_fields("mongo_req_1")
        self._rebuild_diary_fields("cassandra_req_1")
        self._rebuild_rec_fields("dgraph_req_2")
        self._load_popular_page(1)
        self._load_my_lists()
        self._refresh_my_profile()

    def on_resize(self, event: Resize) -> None:
        new_per_row = self._calc_cards_per_row()
        if new_per_row != self._cards_per_row:
            self._cards_per_row = new_per_row
            self._update_foryou_row()
            for idx in range(len(self._genre_sections)):
                self._update_genre_row(idx)

    def _calc_cards_per_row(self) -> int:
        """Calculates how many MovieCards fit in a single row based on terminal width (fallback: 3)."""
        try:
            term_width = self.size.width or self.app.size.width
        except Exception:
            term_width = 0
        if not term_width or term_width <= 0:
            return 3
        usable_width = max(23, term_width - 20)
        return max(1, usable_width // 23)

    def on_screen_resume(self) -> None:
        self._refresh_header()
        self._load_my_lists()
        self._refresh_my_profile()

    @on(TabbedContent.TabActivated, "#user-tabs")
    def _on_main_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        pane_id = event.pane.id if event.pane else ""
        if pane_id == "tab-lists":
            self._load_my_lists()
        elif pane_id == "tab-profile":
            self._refresh_my_profile()

    def _refresh_header(self) -> None:
        session = AuthService().current_session
        self.query_one("#btn-user-menu", Button).label = _format_user_menu_label(session)

    @on(Button.Pressed, "#btn-user-menu")
    def _on_user_menu_pressed(self) -> None:
        session = AuthService().current_session

        def _after(action: Optional[str]) -> None:
            if action == "profile":
                self.query_one("#user-tabs", TabbedContent).active = "tab-profile"
                self._refresh_my_profile()
            elif action == "review":
                self.action_open_review_modal()
            elif action == "lists":
                self.query_one("#user-tabs", TabbedContent).active = "tab-lists"
                self._load_my_lists()
            elif action == "settings":
                self.action_open_settings()
            elif action == "help":
                self.action_open_help()
            elif action == "switch_user":
                self.action_switch_user()
            elif action == "logout":
                self.action_logout()

        self.app.push_screen(UserMenuModal(session), _after)

    # =========================================================================
    # TAB 1: HOME / NETFLIX-STYLE GENRE & FOR YOU CAROUSELS
    # =========================================================================

    def _load_popular_page(self, page: int = 1) -> None:
        self._popular_page = max(1, page)
        state = self.query_one("#home-state-msg", StateMessage)
        state.show_loading("Loading movies by genre from catalog...")
        self._fetch_popular_worker(self._popular_page)

    @work(thread=True, exclusive=True, group="home-popular")
    def _fetch_popular_worker(self, page: int) -> None:
        worker = get_current_worker()
        try:
            mongo = MongoConnection()
            db = mongo.database if mongo.initialized else None
        except Exception:
            db = None
        sections, total = CatalogService().get_movies_by_genres(db, per_genre_limit=16)
        if not worker.is_cancelled:
            self.app.call_from_thread(self._render_popular, sections, total)

    def _render_popular(
        self,
        sections: List[Tuple[str, List[MovieSummary]]],
        total: int,
    ) -> None:
        state = self.query_one("#home-state-msg", StateMessage)
        self._genre_sections = sections
        self._cards_per_row = self._calc_cards_per_row()
        self._update_foryou_row()

        container = self.query_one("#home-genres-container", Vertical)
        container.remove_children()

        if not sections or total == 0:
            state.show_empty(
                "Your local catalog does not have saved movies yet.",
                "Search for movies by title or genre to add them to your catalog.",
            )
            return

        state.clear_state()
        for index, (genre_name, movies) in enumerate(sections):
            self._genre_offsets.setdefault(genre_name, 0)
            container.mount(
                Static(
                    f"{genre_name.upper()} ({len(movies)})",
                    classes="panel-heading",
                )
            )
            row = Horizontal(classes="carousel-row")
            container.mount(row)
            btn_prev = Button(
                "<",
                id=f"btn-genre-prev-{index}",
                name=f"prev|{index}",
                classes="carousel-nav-btn home-genre-nav",
            )
            bar = Horizontal(id=f"home-genre-bar-{index}", classes="chips-bar")
            btn_next = Button(
                ">",
                id=f"btn-genre-next-{index}",
                name=f"next|{index}",
                classes="carousel-nav-btn home-genre-nav",
            )
            row.mount(btn_prev)
            row.mount(bar)
            row.mount(btn_next)
            self._update_genre_row(index)

    def _update_foryou_row(self) -> None:
        per_row = self._cards_per_row
        bar = self.query_one("#home-foryou-bar", Horizontal)
        btn_prev = self.query_one("#btn-foryou-prev", Button)
        btn_next = self.query_one("#btn-foryou-next", Button)
        bar.remove_children()

        if not self._foryou_movies:
            btn_prev.display = False
            btn_next.display = False
            bar.mount(
                Static(
                    "[dim]No personalized recommendations yet (Dgraph recommendation queries pending implementation).[/]"
                )
            )
            return

        max_offset = max(0, len(self._foryou_movies) - per_row)
        self._foryou_offset = max(0, min(self._foryou_offset, max_offset))
        show_nav = len(self._foryou_movies) > per_row
        btn_prev.display = show_nav
        btn_next.display = show_nav
        if show_nav:
            btn_prev.disabled = self._foryou_offset <= 0
            btn_next.disabled = self._foryou_offset >= max_offset

        cards = [
            MovieCard(m)
            for m in self._foryou_movies[self._foryou_offset : self._foryou_offset + per_row]
        ]
        populate_carousel_bar(bar, cards, per_row)

    def _update_genre_row(self, idx: int) -> None:
        if not (0 <= idx < len(self._genre_sections)):
            return
        genre_name, movies = self._genre_sections[idx]
        per_row = self._cards_per_row
        try:
            bar = self.query_one(f"#home-genre-bar-{idx}", Horizontal)
            btn_prev = self.query_one(f"#btn-genre-prev-{idx}", Button)
            btn_next = self.query_one(f"#btn-genre-next-{idx}", Button)
        except Exception:
            return

        if not movies:
            btn_prev.display = False
            btn_next.display = False
            bar.remove_children()
            bar.mount(Static("[dim]No movies in this genre[/]"))
            return

        max_offset = max(0, len(movies) - per_row)
        cur_offset = max(0, min(self._genre_offsets.get(genre_name, 0), max_offset))
        self._genre_offsets[genre_name] = cur_offset

        show_nav = len(movies) > per_row
        btn_prev.display = show_nav
        btn_next.display = show_nav
        if show_nav:
            btn_prev.disabled = cur_offset <= 0
            btn_next.disabled = cur_offset >= max_offset

        cards = [
            MovieCard(m)
            for m in movies[cur_offset : cur_offset + per_row]
        ]
        populate_carousel_bar(bar, cards, per_row)

    @on(Button.Pressed, "#btn-foryou-prev")
    def _on_foryou_prev(self) -> None:
        if self._foryou_offset > 0:
            self._foryou_offset -= 1
            self._update_foryou_row()

    @on(Button.Pressed, "#btn-foryou-next")
    def _on_foryou_next(self) -> None:
        if self._foryou_offset + self._cards_per_row < len(self._foryou_movies):
            self._foryou_offset += 1
            self._update_foryou_row()

    @on(Button.Pressed, ".home-genre-nav")
    def _on_genre_nav_pressed(self, event: Button.Pressed) -> None:
        raw = event.button.name or ""
        parts = raw.split("|", 1)
        if len(parts) != 2:
            return
        direction, idx_str = parts
        try:
            idx = int(idx_str)
        except ValueError:
            return
        if not (0 <= idx < len(self._genre_sections)):
            return
        genre_name, movies = self._genre_sections[idx]
        cur_offset = self._genre_offsets.get(genre_name, 0)
        if direction == "prev" and cur_offset > 0:
            self._genre_offsets[genre_name] = cur_offset - 1
            self._update_genre_row(idx)
        elif direction == "next" and cur_offset + self._cards_per_row < len(movies):
            self._genre_offsets[genre_name] = cur_offset + 1
            self._update_genre_row(idx)

    @on(Button.Pressed, "#btn-home-quick-search")
    def _on_home_quick_search_btn(self) -> None:
        self._trigger_home_quick_search()

    @on(Input.Submitted, "#home-quick-search-input")
    def _on_home_quick_search_submit(self) -> None:
        self._trigger_home_quick_search()

    def _trigger_home_quick_search(self) -> None:
        query_text = self.query_one("#home-quick-search-input", Input).value.strip()
        params: Dict[str, str] = {
            "title": query_text,
            "start_decade": "1950",
            "end_decade": "2020",
            "language": "",
            "page": "1",
        }
        breadcrumb = (
            f"🎬 Quick Search (title={query_text})"
            if query_text
            else "🎬 Quick Search (All Movies)"
        )
        self.app.push_screen(
            SearchResultsScreen("mongo_req_1", params, breadcrumb=breadcrumb)
        )

    @on(Button.Pressed, "#btn-home-refresh")
    def _on_home_refresh(self) -> None:
        self._load_popular_page(self._popular_page)

    @on(Button.Pressed, "#btn-home-seed-quick")
    def _on_home_seed_quick(self) -> None:
        state = self.query_one("#home-state-msg", StateMessage)
        state.show_loading(
            "Downloading 20 popular movies from TMDB with their directors and cast..."
        )
        self._quick_seed_worker(20)

    @work(thread=True, exclusive=True, group="home-seed")
    def _quick_seed_worker(self, count: int) -> None:
        worker = get_current_worker()
        try:
            mongo = MongoConnection()
            db = mongo.database if mongo.initialized else None
        except Exception:
            db = None
        report = CatalogService().populate_popular(
            db=db,
            n=count,
            include_person_details=True,
        )
        if not worker.is_cancelled:
            self.app.call_from_thread(self._after_quick_seed, report.new_movies, report.skipped_existing)

    def _after_quick_seed(self, new_movies: int, skipped: int) -> None:
        self._load_popular_page(1)
        state = self.query_one("#home-state-msg", StateMessage)
        state.show_success(
            f"Catalog updated: {new_movies} new movies added ({skipped} already existed)."
        )

    @on(MovieCard.Selected)
    def _on_any_card_selected(self, event: MovieCard.Selected) -> None:
        self.app.push_screen(MovieDetailScreen(event.movie_id or event.title))

    # =========================================================================
    # SHARED QUERY FORM HELPERS & TAB 2/3/4 FORMS
    # =========================================================================

    def _rebuild_query_fields(
        self,
        container_id: str,
        query_id: str,
        input_class: str,
    ) -> None:
        container = self.query_one(container_id, Vertical)
        container.remove_children()
        spec = get_query_by_id(query_id)
        if spec is None:
            return

        inline_pairs = {("start_date", "end_date"), ("start_decade", "end_decade")}
        visible_params = [p for p in spec.params if p.name not in ("page", "username")]
        idx = 0
        while idx < len(visible_params):
            p = visible_params[idx]
            if (
                idx + 1 < len(visible_params)
                and (p.name, visible_params[idx + 1].name) in inline_pairs
            ):
                end_p = visible_params[idx + 1]
                row = Horizontal(classes="inline-fields-row")
                container.mount(row)
                for col_param, col_cls in (
                    (p, "inline-field-col"),
                    (end_p, "inline-field-col inline-field-col-last"),
                ):
                    col = Vertical(classes=col_cls)
                    row.mount(col)
                    col.mount(Label(f"{col_param.label}:", classes="field-label"))
                    col.mount(
                        Input(
                            value=col_param.default,
                            placeholder=col_param.placeholder,
                            name=col_param.name,
                            classes=f"query-field-input {input_class}",
                        )
                    )
                idx += 2
                continue

            container.mount(Label(f"{p.label}:", classes="field-label"))
            container.mount(
                Input(
                    value=p.default,
                    placeholder=p.placeholder,
                    name=p.name,
                    classes=f"query-field-input {input_class}",
                )
            )
            idx += 1

    def _collect_query_params(
        self,
        query_id: str,
        input_class: str,
    ) -> Dict[str, str]:
        spec = get_query_by_id(query_id)
        defaults = {p.name: p.default for p in spec.params} if spec else {}
        params: Dict[str, str] = {}
        for inp in self.query(f".{input_class}"):
            if isinstance(inp, Input) and inp.name:
                val = inp.value.strip()
                if not val and defaults.get(inp.name):
                    val = defaults[inp.name]
                params[inp.name] = val
        return params

    @staticmethod
    def _build_breadcrumb(
        modes: List[Tuple[str, str]],
        query_id: str,
        params: Dict[str, str],
        fallback: str,
    ) -> str:
        mode_label = next((label for label, qid in modes if qid == query_id), fallback)
        summary_parts = [f"{k}={v}" for k, v in params.items() if k != "page" and v]
        return f"{mode_label} ({', '.join(summary_parts)})" if summary_parts else mode_label

    # =========================================================================
    # TAB 2: EXPLORE (MOVIES, ACTIVITY, RECOMMENDATIONS)
    # =========================================================================

    @on(Select.Changed, "#explore-section-select")
    def _on_explore_section_changed(self, event: Select.Changed) -> None:
        self._set_explore_section(str(event.value))

    def _set_explore_section(self, section: str) -> None:
        self.query_one("#search-form-card", Vertical).display = section == "movies"
        self.query_one("#diary-form-card", Vertical).display = section == "activity"
        self.query_one("#rec-form-card", Vertical).display = section == "recs"

    @on(Select.Changed, "#search-mode-select")
    def _on_search_mode_changed(self, event: Select.Changed) -> None:
        self._rebuild_search_fields(str(event.value))

    def _rebuild_search_fields(self, query_id: str) -> None:
        self._rebuild_query_fields("#search-dynamic-fields", query_id, "search-field-input")

    @on(Button.Pressed, "#btn-submit-search")
    def _on_submit_search_btn(self) -> None:
        self._trigger_search()

    @on(Input.Submitted, ".search-field-input")
    def _on_submit_search_input(self) -> None:
        self._trigger_search()

    def _trigger_search(self) -> None:
        query_id = str(self.query_one("#search-mode-select", Select).value)
        params = self._collect_query_params(query_id, "search-field-input")
        params["page"] = "1"

        if query_id == "mongo_req_7":
            actor_name = params.get("actor_name", "") or "Leonardo DiCaprio"
            self.app.push_screen(
                PersonScreen(actor_name, kind="actor", display_name=actor_name)
            )
            return

        if query_id == "mongo_req_5":
            m_title = params.get("movie_title", "") or "Inception"
            kw = params.get("keywords", "")
            self.app.push_screen(ReviewsScreen(m_title, initial_keywords=kw))
            return

        breadcrumb = self._build_breadcrumb(SEARCH_MODES, query_id, params, "Movie Search")
        self.app.push_screen(SearchResultsScreen(query_id, params, breadcrumb=breadcrumb))

    # =========================================================================
    # TAB 3: MY DIARY AND ACTIVITY (CASSANDRA)
    # =========================================================================

    @on(Select.Changed, "#diary-mode-select")
    def _on_diary_mode_changed(self, event: Select.Changed) -> None:
        self._rebuild_diary_fields(str(event.value))

    def _rebuild_diary_fields(self, query_id: str) -> None:
        self._rebuild_query_fields("#diary-dynamic-fields", query_id, "diary-field-input")

    @on(Button.Pressed, "#btn-run-diary")
    def _on_run_diary_btn(self) -> None:
        self._trigger_diary()

    @on(Input.Submitted, ".diary-field-input")
    def _on_submit_diary_input(self) -> None:
        self._trigger_diary()

    def _trigger_diary(self) -> None:
        query_id = str(self.query_one("#diary-mode-select", Select).value)
        params = self._collect_query_params(query_id, "diary-field-input")
        breadcrumb = self._build_breadcrumb(DIARY_MODES, query_id, params, "Activity")
        self.app.push_screen(
            QueryResultsScreen(
                query_id=query_id,
                params=params,
                section_title="📖 ACTIVITY",
                breadcrumb=breadcrumb,
                back_label="◀ Back to Activity [Esc]",
                loading_msg="Querying your activity history...",
                empty_title="No activity records found for this period.",
                empty_hint="Log watched movies or reviews, or adjust your date filters.",
            )
        )

    # =========================================================================
    # TAB 4: FOR YOU / RECOMMENDATIONS (DGRAPH)
    # =========================================================================

    @on(Select.Changed, "#rec-mode-select")
    def _on_rec_mode_changed(self, event: Select.Changed) -> None:
        self._rebuild_rec_fields(str(event.value))

    def _rebuild_rec_fields(self, query_id: str) -> None:
        self._rebuild_query_fields("#rec-dynamic-fields", query_id, "rec-field-input")

    @on(Button.Pressed, "#btn-run-recs")
    def _on_run_recs_btn(self) -> None:
        self._trigger_recs()

    @on(Input.Submitted, ".rec-field-input")
    def _on_submit_recs_input(self) -> None:
        self._trigger_recs()

    def _trigger_recs(self) -> None:
        query_id = str(self.query_one("#rec-mode-select", Select).value)
        params = self._collect_query_params(query_id, "rec-field-input")
        breadcrumb = self._build_breadcrumb(REC_MODES, query_id, params, "For You")
        self.app.push_screen(
            QueryResultsScreen(
                query_id=query_id,
                params=params,
                section_title="✨ FOR YOU",
                breadcrumb=breadcrumb,
                back_label="◀ Back to For You [Esc]",
                loading_msg="Computing personalized recommendations...",
                empty_title="No recommendations available for this criterion yet.",
                empty_hint="Rate movies, create lists, or follow other users to trigger suggestions.",
            )
        )

    # =========================================================================
    # TAB 5: MY LISTS
    # =========================================================================

    def _load_my_lists(self) -> None:
        session = AuthService().current_session
        state = self.query_one("#lists-state-msg", StateMessage)
        if session is None:
            self._user_lists = []
            self._render_my_lists([])
            state.show_empty(
                "Sign in to view and manage your personal lists.",
                "Press Ctrl+U to switch or sign in to an account.",
            )
            return

        state.show_loading(f"Loading lists for @{session.username}...")
        self._fetch_my_lists_worker(session.username)

    @work(thread=True, exclusive=True, group="home-lists")
    def _fetch_my_lists_worker(self, username: str) -> None:
        worker = get_current_worker()
        lists = ProfileService().get_user_lists(username)
        if not worker.is_cancelled:
            self.app.call_from_thread(self._render_my_lists, lists)

    def _render_my_lists(self, lists: List[UserListSummary]) -> None:
        self._user_lists = lists
        state = self.query_one("#lists-state-msg", StateMessage)
        lv = self.query_one("#my-lists-listview", ListView)
        lv.clear()

        if not lists:
            self._selected_list_name = ""
            state.show_empty(
                "You do not have any personal lists yet.",
                "Click '＋ New List' or press Ctrl+B to add a movie to a new list.",
            )
            self._render_selected_list_detail(None)
            return

        state.clear_state()
        for lst in lists:
            lv.append(
                ListItem(
                    Label(f"{lst.name} [dim]({lst.movies_count})[/]"),
                    name=lst.name,
                )
            )

        selected = next(
            (l for l in lists if l.name == self._selected_list_name),
            lists[0],
        )
        self._selected_list_name = selected.name
        self._render_selected_list_detail(selected)

    def _render_selected_list_detail(self, lst: Optional[UserListSummary]) -> None:
        heading = self.query_one("#lists-selected-heading", FigletHeader)
        desc_widget = self.query_one("#lists-selected-description", Static)
        grid = self.query_one("#my-lists-movie-grid", MovieGrid)

        if lst is None:
            heading.set_header("No list", subtitle="No list selected.")
            desc_widget.display = False
            desc_widget.update("")
            grid.set_movies([], page=1, total=0, page_size=12)
            return

        heading.set_header(
            lst.name,
            subtitle=f"{lst.movies_count} movies — click a poster to view details",
            single_word_max_len=10,
        )
        desc_widget.display = True
        if lst.description:
            desc_widget.update(f"[bold #58a6ff]Description:[/] {lst.description}")
        else:
            desc_widget.update("[bold #58a6ff]Description:[/] [dim italic]Not provided[/]")
        grid.set_movies(
            lst.movies,
            page=1,
            total=lst.movies_count,
            page_size=max(1, lst.movies_count),
        )

    @on(ListView.Selected, "#my-lists-listview")
    def _on_select_my_list(self, event: ListView.Selected) -> None:
        name = str(event.item.name or "")
        self._selected_list_name = name
        matched = next((l for l in self._user_lists if l.name == name), None)
        self._render_selected_list_detail(matched)

    @on(Button.Pressed, "#btn-lists-create")
    def _on_lists_create(self) -> None:
        def _after(msg: Optional[str]) -> None:
            if msg:
                show_success_toast(self, msg)
                self._load_my_lists()
                self._refresh_my_profile()

        self.app.push_screen(CreateListModal(), _after)

    @on(Button.Pressed, "#btn-lists-add-movie")
    def _on_lists_add_movie(self) -> None:
        session = AuthService().current_session
        state = self.query_one("#lists-state-msg", StateMessage)
        if session is None:
            state.show_error("Sign in to add movies to lists.")
            return
        if not self._selected_list_name:
            state.show_error("Select or create a list first.")
            return

        def _after(msg: Optional[str]) -> None:
            if msg:
                show_success_toast(self, msg)
                self._load_my_lists()
                self._refresh_my_profile()

        self.app.push_screen(AddMovieToListModal(self._selected_list_name), _after)

    @on(Button.Pressed, "#btn-lists-delete")
    def _on_lists_delete(self) -> None:
        session = AuthService().current_session
        state = self.query_one("#lists-state-msg", StateMessage)
        if session is None:
            state.show_error("Sign in to delete lists.")
            return
        if not self._selected_list_name:
            state.show_error("Select a list first.")
            return

        list_name = self._selected_list_name

        def _after_confirm(confirmed: bool) -> None:
            if not confirmed:
                return
            ok, msg = ActionService().delete_list(session, list_name)
            if ok:
                state.show_success(msg)
                self._selected_list_name = ""
                self._load_my_lists()
                self._refresh_my_profile()
            else:
                state.show_error(msg)

        self.app.push_screen(
            ConfirmModal(
                title="Delete List",
                message=f"Delete list '{list_name}' and all its movies?",
                confirm_label="Accept",
                confirm_variant="error",
            ),
            _after_confirm,
        )

    @on(MovieCard.RemoveRequested)
    def _on_lists_remove_movie(self, event: MovieCard.RemoveRequested) -> None:
        session = AuthService().current_session
        state = self.query_one("#lists-state-msg", StateMessage)
        if session is None:
            state.show_error("Sign in to modify lists.")
            return
        if not self._selected_list_name:
            state.show_error("Select a list first.")
            return

        list_name = self._selected_list_name
        movie_title = event.title

        def _after_confirm(confirmed: bool) -> None:
            if not confirmed:
                return
            ok, msg = ActionService().remove_movie_from_list(
                session,
                list_name,
                movie_title,
            )
            if ok:
                state.show_success(msg)
                self._load_my_lists()
                self._refresh_my_profile()
            else:
                state.show_error(msg)

        self.app.push_screen(
            ConfirmModal(
                title="Remove Movie",
                message=f"Remove '{movie_title}' from '{list_name}'?",
                confirm_label="Accept",
                confirm_variant="error",
            ),
            _after_confirm,
        )

    # =========================================================================
    # TAB 6: MY PROFILE
    # =========================================================================

    def _refresh_my_profile(self) -> None:
        session = AuthService().current_session
        if session is not None:
            self.query_one("#my-profile-view", ProfileView).load_profile(session.username)

    @on(ProfileView.ProfileUpdated, "#my-profile-view")
    def _on_my_profile_updated(self, _event: ProfileView.ProfileUpdated) -> None:
        self._refresh_header()
        self._load_my_lists()

    # =========================================================================
    # GLOBAL USER ACTIONS
    # =========================================================================

    def action_open_help(self) -> None:
        self.app.push_screen(HelpScreen())

    def action_open_settings(self) -> None:
        def _after(posters_changed: Optional[bool]) -> None:
            self._refresh_header()
            if posters_changed:
                for poster in self.query(PosterImage):
                    poster.refresh_poster()

        self.app.push_screen(SettingsScreen(), _after)

    def action_goto_tab(self, tab_id: str) -> None:
        tabs = self.query_one("#user-tabs", TabbedContent)
        tabs.active = tab_id
        if tab_id == "tab-lists":
            self._load_my_lists()
        elif tab_id == "tab-profile":
            self._refresh_my_profile()

    def action_focus_search(self) -> None:
        tabs = self.query_one("#user-tabs", TabbedContent)
        tabs.active = "tab-home"
        self.query_one("#home-quick-search-input", Input).focus()

    def action_open_review_modal(self) -> None:
        def _after(msg: Optional[str]) -> None:
            if msg:
                self._refresh_my_profile()

        self.app.push_screen(ReviewMovieModal(), _after)

    def action_open_list_modal(self) -> None:
        def _after(msg: Optional[str]) -> None:
            if msg:
                show_success_toast(self, msg)
                self._load_my_lists()
                self._refresh_my_profile()

        self.app.push_screen(ManageListModal(), _after)

    def action_open_social_modal(self) -> None:
        self.app.push_screen(SocialActionModal())

    def action_switch_user(self) -> None:
        def _after(new_session: Optional[UserSession]) -> None:
            if new_session is not None:
                self._refresh_header()
                self._load_my_lists()
                self._refresh_my_profile()

        self.app.push_screen(UserSwitchModal(), _after)

    def action_logout(self) -> None:
        AuthService().logout()
        self.app.switch_screen("auth")
