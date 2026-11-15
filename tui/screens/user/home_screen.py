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
    CreateListModal,
    ManageListModal,
    ReviewMovieModal,
    SocialActionModal,
    UserSwitchModal,
)
from tui.screens.help_screen import HelpScreen
from tui.screens.user.movie_detail_screen import MovieDetailScreen
from tui.screens.user.person_screen import PersonScreen
from tui.screens.user.reviews_screen import ReviewsScreen
from tui.screens.user.search_results_screen import SearchResultsScreen
from tui.widgets.movie_card import MovieCard
from tui.widgets.movie_grid import MovieGrid
from tui.widgets.person_card import populate_carousel_bar
from tui.widgets.poster import PosterImage
from tui.widgets.profile_view import ProfileView
from tui.widgets.state_message import StateMessage

SEARCH_MODES = [
    ("🎬 Movies by title, decade, and language", "mongo_req_1"),
    ("🌍 Movies by genre, country, and director", "mongo_req_2"),
    ("⭐ Movies by rating, director, and decade", "mongo_req_3"),
    ("📝 Movies by keywords in synopsis", "mongo_req_4"),
    ("🎭 Movies by actor and/or director", "mongo_req_6"),
    ("📊 Actor impact analysis and filmography", "mongo_req_7"),
    ("💬 Movie reviews by keywords", "mongo_req_5"),
]

DIARY_MODES = [
    ("👁 Recently watched movies", "cassandra_req_1"),
    ("🎭 Watched movies filtered by genre", "cassandra_req_2"),
    ("✍ My published reviews", "cassandra_req_3"),
    ("★ My reviews by rating range", "cassandra_req_4"),
    ("💬 Review history for a movie", "cassandra_req_5"),
    ("♥ Liked reviews", "cassandra_req_6"),
    ("📋 My movie list activity", "cassandra_req_7"),
    ("🤝 Followed accounts", "cassandra_req_8"),
]

REC_MODES = [
    ("🤝 Users who liked my favorite review", "dgraph_req_1"),
    ("🍿 Movies watched by friends in last 7 days", "dgraph_req_2"),
    ("🎞 Same-genre movies not in my list", "dgraph_req_3"),
    ("🎬 Movies liked by friends (same director)", "dgraph_req_4"),
    ("🎭 Movies with actors from films I liked", "dgraph_req_5"),
    ("👥 Potential friends with shared tastes (≥5 in common)", "dgraph_req_6"),
    ("📋 Unwatched movies in my list liked by friends", "dgraph_req_7"),
    ("✨ Movies by recent Actor + Director combo", "dgraph_req_8"),
]

HOME_ASCII_BANNER = (
    "[bold #f0883e]╭───────────────╮[/]\n"
    "[bold #f0883e]│  ◉    ▶    ◉  │[/]\n"
    "[bold #f0883e]╰───────────────╯[/]\n"
    "[bold #58a6ff] __  __            _     [/][bold #d2a8ff]__     __          _ _   [/]\n"
    "[bold #58a6ff]|  \\/  | _____   _(_) ___[/][bold #d2a8ff]\\ \\   / /_ _ _   _| | |_ [/]\n"
    "[bold #58a6ff]| |\\/| |/ _ \\ \\ / / |/ _ \\[/][bold #d2a8ff]\\ \\ / / _` | | | | | __|[/]\n"
    "[bold #58a6ff]| |  | | (_) \\ V /| |  __/[/][bold #d2a8ff] \\ V / (_| | |_| | | |_ [/]\n"
    "[bold #58a6ff]|_|  |_|\\___/ \\_/ |_|\\___|[/][bold #d2a8ff]  \\_/ \\__,_|\\__,_|_|\\__|[/]\n"
    "[dim]Your Personal Film Catalog, Reviews & Discovery Vault[/]"
)


def _build_home_header(session: Optional[UserSession]) -> str:
    user_str = (
        f"[bold #79c0ff]👤 @{session.username}[/]"
        if session
        else "[bold #f0883e]👤 Explorer Mode[/]"
    )
    posters_on = PosterService().enabled
    poster_badge = (
        "[bold #3fb950]🖼 Posters: YES [Ctrl+P][/]"
        if posters_on
        else "[bold #d29922]🖼 Posters: TEXT MODE [Ctrl+P][/]"
    )
    return (
        f"[bold #58a6ff]🎬 MOVIEVAULT[/]  │  {user_str}  │  "
        f"{poster_badge}  │  [dim]F1: Help  •  Ctrl+N: Review  •  Ctrl+B: Lists[/]"
    )


class HomeScreen(Screen):
    """Accessible Letterboxd-style main screen for end users."""

    BINDINGS = [
        Binding("f1", "open_help", "Help", show=True, priority=True),
        Binding("ctrl+p", "toggle_posters", "Posters Toggle", show=True, priority=True),
        Binding("ctrl+n", "open_review_modal", "Review", show=True, priority=True),
        Binding("ctrl+b", "open_list_modal", "My Lists", show=True, priority=True),
        Binding("ctrl+f", "open_social_modal", "Like / Follow", show=True, priority=True),
        Binding("ctrl+u", "switch_user", "Switch User", show=True, priority=True),
        Binding("ctrl+l", "logout", "Log Out", show=True, priority=True),
        Binding("q", "app.quit", "Quit", show=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._popular_page = 1
        self._foryou_movies: List[MovieSummary] = []
        self._foryou_offset: int = 0
        self._genre_sections: List[Tuple[str, List[MovieSummary]]] = []
        self._genre_offsets: Dict[str, int] = {}
        self._cards_per_row: int = 3
        self._diary_rows: List[Dict[str, Any]] = []
        self._rec_rows: List[Dict[str, Any]] = []
        self._user_lists: List[UserListSummary] = []
        self._selected_list_name: str = ""

    def compose(self) -> ComposeResult:
        session = AuthService().current_session
        yield Static(_build_home_header(session), id="top-bar")

        with TabbedContent(id="user-tabs"):
            # =================================================================
            # TAB 1: HOME / NETFLIX-STYLE GENRE & FOR YOU CAROUSELS
            # =================================================================
            with TabPane("🍿 Home", id="tab-home"):
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

                    with Horizontal(classes="section-toolbar"):
                        yield Static(
                            "[bold #79c0ff]🍿 BROWSE BY GENRE & FOR YOU[/]  "
                            "[dim](Enter or click a poster to view details)[/]"
                        )
                        yield Button("🔄 Refresh", variant="default", id="btn-home-refresh")
                        yield Button(
                            "📥 Fetch 20 Popular from TMDB",
                            variant="primary",
                            id="btn-home-seed-quick",
                        )

                    yield StateMessage(id="home-state-msg")

                    yield Static(
                        "✨ FOR YOU — RECOMMENDED MOVIES:",
                        classes="panel-heading",
                    )
                    with Horizontal(classes="carousel-row"):
                        yield Button("<", id="btn-foryou-prev", classes="carousel-nav-btn")
                        yield Horizontal(id="home-foryou-bar", classes="chips-bar")
                        yield Button(">", id="btn-foryou-next", classes="carousel-nav-btn")

                    yield Vertical(id="home-genres-container")

            # =================================================================
            # TAB 2: SEARCH MOVIES AND TALENT (CLEAN FORM)
            # =================================================================
            with TabPane("🔍 Search", id="tab-search"):
                with VerticalScroll(classes="tab-page-scroll"):
                    with Vertical(id="search-form-card"):
                        yield Static(
                            "[bold #58a6ff]🔍 MOVIE, TALENT, AND REVIEW SEARCH[/]\n"
                            "[dim]Choose how to search. If a movie is not in your local catalog, it will automatically be fetched from TMDB.[/]"
                        )
                        yield Label("Search criteria:")
                        yield Select(
                            SEARCH_MODES,
                            value="mongo_req_1",
                            allow_blank=False,
                            id="search-mode-select",
                        )
                        yield Vertical(id="search-dynamic-fields")
                        with Horizontal(classes="form-submit-row"):
                            yield Button(
                                "🔍 Search Now [Enter]",
                                variant="success",
                                id="btn-submit-search",
                            )

            # =================================================================
            # TAB 3: MY DIARY AND ACTIVITY
            # =================================================================
            with TabPane("📖 My Diary", id="tab-diary"):
                with Vertical(classes="tab-page-container"):
                    with Vertical(classes="filter-card"):
                        with Horizontal(classes="section-toolbar"):
                            yield Label("Activity to query:")
                            yield Select(
                                DIARY_MODES,
                                value="cassandra_req_1",
                                allow_blank=False,
                                id="diary-mode-select",
                            )
                            yield Button(
                                "📖 View Activity",
                                variant="primary",
                                id="btn-run-diary",
                            )
                        yield Horizontal(id="diary-dynamic-fields", classes="inline-fields-row")

                    yield StateMessage(id="diary-state-msg")
                    yield DataTable(id="diary-table")

            # =================================================================
            # TAB 4: FOR YOU (RECOMMENDATIONS)
            # =================================================================
            with TabPane("✨ For You", id="tab-recs"):
                with Vertical(classes="tab-page-container"):
                    with Vertical(classes="filter-card"):
                        with Horizontal(classes="section-toolbar"):
                            yield Label("Recommendation type:")
                            yield Select(
                                REC_MODES,
                                value="dgraph_req_2",
                                allow_blank=False,
                                id="rec-mode-select",
                            )
                            yield Button(
                                "✨ Get Recommendations",
                                variant="primary",
                                id="btn-run-recs",
                            )
                        yield Horizontal(id="rec-dynamic-fields", classes="inline-fields-row")

                    yield StateMessage(id="rec-state-msg")
                    yield DataTable(id="rec-table")

            # =================================================================
            # TAB 5: MY LISTS
            # =================================================================
            with TabPane("📋 My Lists", id="tab-lists"):
                with Vertical(classes="tab-page-container"):
                    with Horizontal(classes="section-toolbar"):
                        yield Static("[bold #79c0ff]📋 MY PERSONAL LISTS[/]")
                        yield Button("＋ New List", variant="success", id="btn-lists-create")
                        yield Button("＋ Add Movie [Ctrl+B]", variant="primary", id="btn-lists-add-movie")
                        yield Button("🗑 Delete List", variant="error", id="btn-lists-delete")
                        yield Button("🔄 Refresh", variant="default", id="btn-lists-refresh")

                    yield StateMessage(id="lists-state-msg")

                    with Horizontal(id="lists-workspace"):
                        with Vertical(id="lists-sidebar"):
                            yield Static("Your Lists:", classes="panel-heading")
                            yield ListView(id="my-lists-listview")
                        with Vertical(id="lists-detail-panel"):
                            yield Static(
                                "[bold #d2a8ff]Select a list on the left[/]",
                                id="lists-selected-heading",
                            )
                            with Horizontal(id="lists-remove-bar", classes="section-toolbar"):
                                yield Select([], prompt="Select movie to remove", id="lists-remove-select")
                                yield Button("✖ Remove Movie", variant="warning", id="btn-lists-remove-movie")
                            yield MovieGrid(page_size=12, id="my-lists-movie-grid")

            # =================================================================
            # TAB 6: MY PROFILE
            # =================================================================
            with TabPane("📊 My Profile", id="tab-profile"):
                with Vertical(classes="tab-page-container"):
                    yield ProfileView(
                        target_username=session.username if session else "",
                        id="my-profile-view",
                    )

        yield Footer()

    def on_mount(self) -> None:
        for btn_id in ("#btn-foryou-prev", "#btn-foryou-next"):
            self.query_one(btn_id, Button).display = False
        for tbl_id in ("#diary-table", "#rec-table"):
            tbl = self.query_one(tbl_id, DataTable)
            tbl.cursor_type = "row"
            tbl.zebra_stripes = True

        self._refresh_header()
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
        self.query_one("#top-bar", Static).update(_build_home_header(session))

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
                "Click the '📥 Fetch 20 Popular from TMDB' button above or perform a search.",
            )
            return

        state.clear_state()
        for idx, (genre_name, movies) in enumerate(sections):
            self._genre_offsets.setdefault(genre_name, 0)
            container.mount(
                Static(
                    f"🎬 {genre_name.upper()} ({len(movies)})",
                    classes="panel-heading",
                )
            )
            row = Horizontal(classes="carousel-row")
            container.mount(row)
            btn_prev = Button(
                "<",
                id=f"btn-genre-prev-{idx}",
                name=f"prev|{idx}",
                classes="carousel-nav-btn home-genre-nav",
            )
            bar = Horizontal(id=f"home-genre-bar-{idx}", classes="chips-bar")
            btn_next = Button(
                ">",
                id=f"btn-genre-next-{idx}",
                name=f"next|{idx}",
                classes="carousel-nav-btn home-genre-nav",
            )
            row.mount(btn_prev)
            row.mount(bar)
            row.mount(btn_next)
            self._update_genre_row(idx)

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
    # TAB 2: ACCESSIBLE SEARCH FORM
    # =========================================================================

    @on(Select.Changed, "#search-mode-select")
    def _on_search_mode_changed(self, event: Select.Changed) -> None:
        self._rebuild_search_fields(str(event.value))

    def _rebuild_search_fields(self, query_id: str) -> None:
        container = self.query_one("#search-dynamic-fields", Vertical)
        container.remove_children()
        spec = get_query_by_id(query_id)
        if spec is None:
            return

        for p in spec.params:
            if p.name == "page":
                continue
            container.mount(Label(f"{p.label}:", classes="field-label"))
            container.mount(
                Input(
                    value=p.default,
                    placeholder=p.placeholder,
                    name=p.name,
                    classes="search-field-input",
                )
            )

    @on(Button.Pressed, "#btn-submit-search")
    def _on_submit_search_btn(self) -> None:
        self._trigger_search()

    @on(Input.Submitted, ".search-field-input")
    def _on_submit_search_input(self) -> None:
        self._trigger_search()

    def _trigger_search(self) -> None:
        query_id = str(self.query_one("#search-mode-select", Select).value)
        params: Dict[str, str] = {"page": "1"}
        for inp in self.query(".search-field-input"):
            if isinstance(inp, Input) and inp.name:
                params[inp.name] = inp.value.strip()

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

        mode_label = next(
            (label for label, qid in SEARCH_MODES if qid == query_id),
            "Movie Search",
        )
        summary_parts = [f"{k}={v}" for k, v in params.items() if k != "page" and v]
        breadcrumb = f"{mode_label} ({', '.join(summary_parts)})" if summary_parts else mode_label
        self.app.push_screen(SearchResultsScreen(query_id, params, breadcrumb=breadcrumb))

    # =========================================================================
    # TAB 3: MY DIARY AND ACTIVITY (CASSANDRA)
    # =========================================================================

    @on(Select.Changed, "#diary-mode-select")
    def _on_diary_mode_changed(self, event: Select.Changed) -> None:
        qid = str(event.value)
        self._rebuild_diary_fields(qid)

    def _rebuild_diary_fields(self, query_id: str) -> None:
        box = self.query_one("#diary-dynamic-fields", Horizontal)
        box.remove_children()
        spec = get_query_by_id(query_id)
        if spec is None:
            return
        session = AuthService().current_session
        active_uname = session.username if session else ""

        for p in spec.params:
            val = p.default
            if p.name == "username" and not val and active_uname:
                val = active_uname
            col = Vertical(classes="inline-field-col")
            box.mount(col)
            col.mount(Label(p.label))
            col.mount(
                Input(
                    value=val,
                    placeholder=p.placeholder,
                    name=p.name,
                    classes="diary-field-input",
                )
            )

    @on(Button.Pressed, "#btn-run-diary")
    def _on_run_diary_btn(self) -> None:
        qid = str(self.query_one("#diary-mode-select", Select).value)
        self._run_diary_query(qid)

    def _run_diary_query(self, query_id: str) -> None:
        params: Dict[str, str] = {}
        for inp in self.query(".diary-field-input"):
            if isinstance(inp, Input) and inp.name:
                params[inp.name] = inp.value.strip()

        state = self.query_one("#diary-state-msg", StateMessage)
        state.show_loading("Querying your activity history...")
        self._diary_worker(query_id, params)

    @work(thread=True, exclusive=True, group="home-diary")
    def _diary_worker(self, query_id: str, params: Dict[str, str]) -> None:
        worker = get_current_worker()
        res = execute_query(query_id, params)
        if not worker.is_cancelled:
            self.app.call_from_thread(self._render_diary_table, res)

    def _render_diary_table(self, res: QueryResult) -> None:
        self._diary_rows = list(res.rows)
        state = self.query_one("#diary-state-msg", StateMessage)
        table = self.query_one("#diary-table", DataTable)
        table.clear(columns=True)

        for col in res.columns:
            table.add_column(get_column_label(col))

        if not res.rows:
            state.show_empty(
                "No activity records found for this period.",
                "Log watched movies or reviews with Ctrl+N, or verify your Cassandra records.",
            )
            return

        state.clear_state()
        for r in res.rows:
            table.add_row(*[format_cell_value(c, r.get(c)) for c in res.columns])

    @on(DataTable.RowSelected, "#diary-table")
    def _on_diary_row_selected(self, event: DataTable.RowSelected) -> None:
        idx = event.cursor_row
        if 0 <= idx < len(self._diary_rows):
            row = self._diary_rows[idx]
            title = row.get("movie_title")
            if title:
                self.app.push_screen(MovieDetailScreen(str(title)))

    # =========================================================================
    # TAB 4: FOR YOU / RECOMMENDATIONS (DGRAPH)
    # =========================================================================

    @on(Select.Changed, "#rec-mode-select")
    def _on_rec_mode_changed(self, event: Select.Changed) -> None:
        qid = str(event.value)
        self._rebuild_rec_fields(qid)

    def _rebuild_rec_fields(self, query_id: str) -> None:
        box = self.query_one("#rec-dynamic-fields", Horizontal)
        box.remove_children()
        spec = get_query_by_id(query_id)
        if spec is None:
            return
        session = AuthService().current_session
        active_uname = session.username if session else ""

        for p in spec.params:
            val = p.default
            if p.name == "username" and not val and active_uname:
                val = active_uname
            col = Vertical(classes="inline-field-col")
            box.mount(col)
            col.mount(Label(p.label))
            col.mount(
                Input(
                    value=val,
                    placeholder=p.placeholder,
                    name=p.name,
                    classes="rec-field-input",
                )
            )

    @on(Button.Pressed, "#btn-run-recs")
    def _on_run_recs_btn(self) -> None:
        qid = str(self.query_one("#rec-mode-select", Select).value)
        self._run_rec_query(qid)

    def _run_rec_query(self, query_id: str) -> None:
        params: Dict[str, str] = {}
        for inp in self.query(".rec-field-input"):
            if isinstance(inp, Input) and inp.name:
                params[inp.name] = inp.value.strip()

        state = self.query_one("#rec-state-msg", StateMessage)
        state.show_loading("Computing personalized recommendations...")
        self._rec_worker(query_id, params)

    @work(thread=True, exclusive=True, group="home-rec")
    def _rec_worker(self, query_id: str, params: Dict[str, str]) -> None:
        worker = get_current_worker()
        res = execute_query(query_id, params)
        if not worker.is_cancelled:
            self.app.call_from_thread(self._render_rec_table, res)

    def _render_rec_table(self, res: QueryResult) -> None:
        self._rec_rows = list(res.rows)
        state = self.query_one("#rec-state-msg", StateMessage)
        table = self.query_one("#rec-table", DataTable)
        table.clear(columns=True)

        for col in res.columns:
            table.add_column(get_column_label(col))

        if not res.rows:
            state.show_empty(
                "No recommendations available for this criterion yet.",
                "Rate movies, create lists, or follow other users to trigger suggestions.",
            )
            return

        state.clear_state()
        for r in res.rows:
            table.add_row(*[format_cell_value(c, r.get(c)) for c in res.columns])

    @on(DataTable.RowSelected, "#rec-table")
    def _on_rec_row_selected(self, event: DataTable.RowSelected) -> None:
        idx = event.cursor_row
        if 0 <= idx < len(self._rec_rows):
            row = self._rec_rows[idx]
            title = row.get("movie_title")
            if title:
                self.app.push_screen(MovieDetailScreen(str(title)))

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
                    Label(f"📋 {lst.name} [dim]({lst.movies_count})[/]"),
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
        heading = self.query_one("#lists-selected-heading", Static)
        grid = self.query_one("#my-lists-movie-grid", MovieGrid)
        remove_bar = self.query_one("#lists-remove-bar", Horizontal)
        remove_sel = self.query_one("#lists-remove-select", Select)

        if lst is None:
            heading.update("[dim]No list selected.[/]")
            remove_bar.display = False
            grid.set_movies([], page=1, total=0, page_size=12)
            return

        heading.update(
            f"[bold #d2a8ff]📋 {lst.name}[/]  [dim]({lst.movies_count} movies — click a poster to view details)[/]"
        )
        grid.set_movies(
            lst.movies,
            page=1,
            total=lst.movies_count,
            page_size=max(1, lst.movies_count),
        )
        if lst.movies:
            remove_bar.display = True
            remove_sel.set_options([(m.title, m.title) for m in lst.movies])
        else:
            remove_bar.display = False

    @on(ListView.Selected, "#my-lists-listview")
    def _on_select_my_list(self, event: ListView.Selected) -> None:
        name = str(event.item.name or "")
        self._selected_list_name = name
        matched = next((l for l in self._user_lists if l.name == name), None)
        self._render_selected_list_detail(matched)

    @on(Button.Pressed, "#btn-lists-refresh")
    def _on_lists_refresh(self) -> None:
        self._load_my_lists()

    @on(Button.Pressed, "#btn-lists-create")
    def _on_lists_create(self) -> None:
        def _after(msg: Optional[str]) -> None:
            if msg:
                self.query_one("#lists-state-msg", StateMessage).show_success(msg)
                self._load_my_lists()
                self._refresh_my_profile()

        self.app.push_screen(CreateListModal(), _after)

    @on(Button.Pressed, "#btn-lists-add-movie")
    def _on_lists_add_movie(self) -> None:
        self.action_open_list_modal()

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

        ok, msg = ActionService().delete_list(session, self._selected_list_name)
        if ok:
            state.show_success(msg)
            self._selected_list_name = ""
            self._load_my_lists()
            self._refresh_my_profile()
        else:
            state.show_error(msg)

    @on(Button.Pressed, "#btn-lists-remove-movie")
    def _on_lists_remove_movie(self) -> None:
        session = AuthService().current_session
        state = self.query_one("#lists-state-msg", StateMessage)
        if session is None:
            state.show_error("Sign in to modify lists.")
            return
        if not self._selected_list_name:
            state.show_error("Select a list first.")
            return

        sel_val = self.query_one("#lists-remove-select", Select).value
        if sel_val is Select.BLANK or not sel_val:
            state.show_error("Select a movie to remove from the list.")
            return

        ok, msg = ActionService().remove_movie_from_list(
            session,
            self._selected_list_name,
            str(sel_val),
        )
        if ok:
            state.show_success(msg)
            self._load_my_lists()
            self._refresh_my_profile()
        else:
            state.show_error(msg)

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

    def action_toggle_posters(self) -> None:
        PosterService().toggle_enabled()
        self._refresh_header()
        for poster in self.query(PosterImage):
            poster.refresh_poster()

    def action_open_review_modal(self) -> None:
        def _after(msg: Optional[str]) -> None:
            if msg:
                self._refresh_my_profile()

        self.app.push_screen(ReviewMovieModal(), _after)

    def action_open_list_modal(self) -> None:
        def _after(msg: Optional[str]) -> None:
            if msg:
                self.query_one("#lists-state-msg", StateMessage).show_success(msg)
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
