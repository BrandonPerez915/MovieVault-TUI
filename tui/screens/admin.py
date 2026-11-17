"""
MovieVault Technical Administration Panel (`AdminScreen`)
(tui/screens/admin.py).

Organized into 4 clean sections matching the main app header and navbar:
1. Panel: Live database & TMDB health, catalog metrics, and quick navigation.
2. Requirements Inspector: Browse and execute the 24 official requirements with
   on-demand technical inspector drawer (`F2`).
3. Query Console: Ad-hoc MongoDB (JSON), Cassandra (CQL), or Dgraph (DQL)
   execution with full-width Table / JSON output toggle.
4. TMDB Catalog: Recursive non-duplicate catalog ingestion from TMDB.
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from rich.syntax import Syntax
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.events import Click, Resize
from textual.message import Message
from textual.screen import Screen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Input,
    Label,
    ListItem,
    ListView,
    ProgressBar,
    RichLog,
    Select,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)
from textual.worker import get_current_worker

from databases import get_databases_status
from databases.mongodb import MongoConnection
from services.AuthService import AuthService, UserSession
from services.CatalogService import CatalogService, PopulateReport
from services.QueryService import (
    QueryResult,
    QuerySpec,
    execute_query,
    execute_raw_query,
    get_modules,
    get_queries_by_module,
)
from services.TMDBService import TMDBService
from tui.modals import (
    AdminEditModal,
    ConfirmModal,
    UserMenuModal,
)
from tui.screens.admin_entity import AdminEntityScreen, ClickableReviewCard
from tui.screens.help import HelpScreen
from tui.screens.settings import SettingsScreen
from tui.toast import show_error_toast, show_info_toast, show_success_toast
from tui.widgets.figlet_header import FigletHeader
from tui.widgets.loading_spinner import LoadingSpinner
from tui.widgets.person_card import PersonCard, populate_carousel_bar
from tui.widgets.poster import PosterImage
from tui.widgets.user_card import UserCard

MAX_PARAM_SLOTS = 5

DEFAULT_ADHOC_TEMPLATES: Dict[str, str] = {
    "MongoDB": json.dumps(
        {
            "collection": "movies",
            "filter": {},
            "projection": {"title": 1, "release_year": 1, "rating": 1, "impact_score": 1},
            "sort": [["impact_score", -1]],
            "limit": 10,
        },
        indent=2,
        ensure_ascii=False,
    ),
    "Cassandra": "SELECT release_version FROM system.local;",
    "Dgraph": "{\n  users(func: type(User), first: 10) {\n    uid\n    username\n    email\n  }\n}",
}


def format_engine_badge(engine: str) -> str:
    """Return Rich markup with colored badge according to the engine."""
    if engine == "MongoDB":
        return "[bold black on #3fb950] MONGODB [/]"
    if engine == "Cassandra":
        return "[bold black on #58a6ff] CASSANDRA [/]"
    if engine == "Dgraph":
        return "[bold black on #d2a8ff] DGRAPH [/]"
    return f"[bold reverse] {engine} [/]"


def format_source_badge(data_source: str) -> str:
    """Return accessible badge (symbol + text) for the data source."""
    mapping = {
        "mongodb": "[bold #3fb950]✔ LOCAL MONGODB[/]",
        "tmdb_cached": "[bold #d29922]★ TMDB FALLBACK → SAVED TO MONGODB[/]",
        "cassandra": "[bold #58a6ff]✔ CASSANDRA LIVE[/]",
        "dgraph": "[bold #d2a8ff]✔ DGRAPH LIVE[/]",
        "offline": "[bold #f85149]✖ OFFLINE[/]",
    }
    return mapping.get(data_source, f"[dim]{data_source}[/]")


def _format_user_menu_label(session: Optional[UserSession]) -> str:
    if session is not None:
        return f"@{session.username} ▾"
    return "@admin ▾"


class ClickableStatCard(Vertical, can_focus=True):
    """Clickable stat card on the Admin Panel overview."""

    BINDINGS = [
        Binding("enter", "activate", "Open", show=False),
        Binding("space", "activate", "Open", show=False),
    ]

    class Pressed(Message):
        def __init__(self, card: "ClickableStatCard") -> None:
            super().__init__()
            self.card = card

        @property
        def control(self) -> "ClickableStatCard":
            return self.card

    def on_click(self, event: Click) -> None:
        event.stop()
        self.post_message(self.Pressed(self))

    def action_activate(self) -> None:
        self.post_message(self.Pressed(self))


class AdminScreen(Screen):
    """Clean, structured Admin Panel matching the main MovieVault layout."""

    BINDINGS = [
        Binding("f1", "open_help", "Help", show=True, priority=True),
        Binding("f2", "toggle_inspector", "Inspector Toggle", show=True, priority=True),
        Binding("f3", "switch_to_user_view", "User View", show=True, priority=True),
        Binding("1", "goto_tab('tab-admin-panel')", "Panel", show=False),
        Binding("2", "goto_tab('tab-inspector')", "Inspector", show=False),
        Binding("3", "goto_tab('tab-console')", "Console", show=False),
        Binding("4", "goto_tab('tab-seed')", "TMDB Catalog", show=False),
        Binding("ctrl+e", "execute_active_query", "Run Query", show=True, priority=True),
        Binding("ctrl+l", "logout", "Go to Login", show=True, priority=True),
        Binding("ctrl+q", "app.quit", "Quit", show=True, priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._modules: List[Dict[str, str]] = get_modules()
        self._active_module_idx: int = -1
        self._current_queries: List[QuerySpec] = []
        self._active_query: Optional[QuerySpec] = None
        self._inspector_visible: bool = False
        self._console_view_mode: str = "table"
        self._admin_movies_cache: List[Dict[str, Any]] = []
        self._admin_movies_filtered: List[Dict[str, Any]] = []
        self._current_movie_doc: Optional[Dict[str, Any]] = None
        self._preview_directors: List[Dict[str, Any]] = []
        self._preview_cast: List[Dict[str, Any]] = []
        self._preview_liked_users: List[Dict[str, Any]] = []
        self._preview_watched_users: List[Dict[str, Any]] = []
        self._preview_reviews: List[Dict[str, Any]] = []
        self._dir_offset: int = 0
        self._cast_offset: int = 0
        self._liked_offset: int = 0
        self._watched_offset: int = 0
        self._rev_offset: int = 0

    def compose(self) -> ComposeResult:
        session = AuthService().current_session
        with Horizontal(id="top-bar"):
            yield Static("[bold #58a6ff]∅ MOVIEVAULT[/]", id="top-bar-brand")
            yield Static("", id="top-bar-spacer")
            yield Button(_format_user_menu_label(session), id="btn-user-menu")

        with TabbedContent(id="admin-tabs"):
            # =================================================================
            # TAB 1: PANEL (OVERVIEW & HEALTH)
            # =================================================================
            with TabPane("Panel", id="tab-admin-panel"):
                with VerticalScroll(id="admin-panel-scroll", classes="detail-page-scroll"):
                    yield FigletHeader(
                        "Admin Panel",
                        font="slant",
                        color="#58a6ff",
                        subtitle="System health, catalog overview, and administrative tools.",
                        id="admin-panel-figlet",
                    )

                    with Horizontal(id="admin-panel-toolbar"):
                        yield Static(
                            "[bold #79c0ff]System Connections & Catalog Status[/]",
                            classes="panel-heading",
                        )
                        yield Static("", id="admin-panel-spacer")
                        yield Button("↻ Refresh Status", id="btn-admin-refresh-health")

                    with Horizontal(id="admin-health-cards"):
                        with Vertical(classes="admin-stat-card"):
                            yield Static("MongoDB", classes="admin-stat-title")
                            yield Static("Checking...", id="health-mongodb", classes="admin-stat-val")
                        with Vertical(classes="admin-stat-card"):
                            yield Static("Cassandra", classes="admin-stat-title")
                            yield Static("Checking...", id="health-cassandra", classes="admin-stat-val")
                        with Vertical(classes="admin-stat-card"):
                            yield Static("Dgraph", classes="admin-stat-title")
                            yield Static("Checking...", id="health-dgraph", classes="admin-stat-val")
                        with Vertical(classes="admin-stat-card"):
                            yield Static("TMDB API", classes="admin-stat-title")
                            yield Static("Checking...", id="health-tmdb", classes="admin-stat-val")

                    yield Static(
                        "[bold #79c0ff]Catalog Overview (MongoDB)[/]",
                        classes="panel-heading",
                    )
                    with Horizontal(id="admin-catalog-cards"):
                        with ClickableStatCard(
                            id="card-stat-movies",
                            classes="admin-stat-card admin-stat-card-clickable",
                        ):
                            yield Static("Movies  [dim]▸[/]", classes="admin-stat-title")
                            yield Static("—", id="stat-movies-count", classes="admin-stat-val")
                        with Vertical(classes="admin-stat-card"):
                            yield Static("Actors", classes="admin-stat-title")
                            yield Static("—", id="stat-actors-count", classes="admin-stat-val")
                        with Vertical(classes="admin-stat-card"):
                            yield Static("Directors", classes="admin-stat-title")
                            yield Static("—", id="stat-directors-count", classes="admin-stat-val")
                        with Vertical(classes="admin-stat-card"):
                            yield Static("Users", classes="admin-stat-title")
                            yield Static("—", id="stat-users-count", classes="admin-stat-val")
                        with Vertical(classes="admin-stat-card"):
                            yield Static("Reviews", classes="admin-stat-title")
                            yield Static("—", id="stat-reviews-count", classes="admin-stat-val")

                    yield Static(
                        "[bold #79c0ff]Quick Actions[/]",
                        classes="panel-heading",
                    )
                    with Horizontal(id="admin-quick-actions"):
                        yield Button(
                            "Requirements Inspector",
                            variant="primary",
                            id="btn-quick-inspector",
                        )
                        yield Button(
                            "Query Console",
                            variant="default",
                            id="btn-quick-console",
                        )
                        yield Button(
                            "TMDB Catalog",
                            variant="success",
                            id="btn-quick-seed",
                        )
                        yield Button(
                            "Switch to User View [F3]",
                            variant="warning",
                            id="btn-quick-user-view",
                        )

                with Vertical(id="admin-movies-browser"):
                    with Horizontal(id="admin-movies-topbar"):
                        yield Button("◀ Back to Panel", id="btn-admin-movies-back")
                        yield Static(
                            "[bold #79c0ff]Catalog Movies Inspector[/]",
                            id="admin-movies-browser-title",
                        )
                        yield Input(
                            placeholder="Filter movies by title...",
                            id="inp-admin-movies-filter",
                        )
                    with Horizontal(id="admin-movies-split"):
                        with Vertical(id="admin-movies-list-pane"):
                            yield Static("ALL MOVIES", classes="panel-heading")
                            yield ListView(id="admin-movies-listview")
                        with VerticalScroll(id="admin-movies-preview-pane"):
                            with Vertical(id="admin-movie-hero-row"):
                                with Center(id="admin-movie-poster-wrap"):
                                    yield PosterImage(
                                        poster_url="",
                                        title="Movie",
                                        cells_width=20,
                                        cells_height=13,
                                        size="w342",
                                        id="admin-movie-poster",
                                    )
                                yield Static("", id="admin-movie-title-line")
                                yield Static("", id="admin-movie-ids-line")
                                with Horizontal(id="admin-movie-actions-row"):
                                    yield Button("Edit Movie", variant="primary", id="btn-admin-edit-movie")
                                    yield Button("Delete Movie", variant="error", id="btn-admin-delete-movie")
                            yield Static(
                                "[dim]Select a movie from the list to inspect its metadata, likes, and reviews.[/]",
                                id="admin-movie-preview-body",
                            )
                            yield Static("DIRECTORS", id="admin-dir-heading", classes="panel-heading")
                            with Horizontal(classes="carousel-row"):
                                yield Button("<", id="btn-admin-dir-prev", classes="carousel-nav-btn")
                                yield Horizontal(id="admin-movie-dir-bar", classes="chips-bar")
                                yield Button(">", id="btn-admin-dir-next", classes="carousel-nav-btn")
                            yield Static("CAST", id="admin-cast-heading", classes="panel-heading")
                            with Horizontal(classes="carousel-row"):
                                yield Button("<", id="btn-admin-cast-prev", classes="carousel-nav-btn")
                                yield Horizontal(id="admin-movie-cast-bar", classes="chips-bar")
                                yield Button(">", id="btn-admin-cast-next", classes="carousel-nav-btn")
                            yield Static("LIKED BY", id="admin-liked-heading", classes="panel-heading")
                            with Horizontal(classes="carousel-row"):
                                yield Button("<", id="btn-admin-liked-prev", classes="carousel-nav-btn")
                                yield Horizontal(id="admin-movie-liked-bar", classes="chips-bar")
                                yield Button(">", id="btn-admin-liked-next", classes="carousel-nav-btn")
                            yield Static("WATCHED BY", id="admin-watched-heading", classes="panel-heading")
                            with Horizontal(classes="carousel-row"):
                                yield Button("<", id="btn-admin-watched-prev", classes="carousel-nav-btn")
                                yield Horizontal(id="admin-movie-watched-bar", classes="chips-bar")
                                yield Button(">", id="btn-admin-watched-next", classes="carousel-nav-btn")
                            yield Static("REVIEWS", id="admin-reviews-heading", classes="panel-heading")
                            with Horizontal(classes="carousel-row"):
                                yield Button("<", id="btn-admin-rev-prev", classes="carousel-nav-btn review-carousel-nav-btn")
                                yield Horizontal(id="admin-movie-reviews-bar", classes="chips-bar")
                                yield Button(">", id="btn-admin-rev-next", classes="carousel-nav-btn review-carousel-nav-btn")

            # =================================================================
            # TAB 2: REQUIREMENTS INSPECTOR (24)
            # =================================================================
            with TabPane("Requirements Inspector", id="tab-inspector"):
                with Horizontal(id="dashboard-body"):
                    with Vertical(id="sidebar"):
                        yield Static("MODULES", classes="panel-heading")
                        mod_items: List[ListItem] = []
                        for m in self._modules:
                            label_markup = (
                                f"[bold]{m['name']}[/]\n"
                                f"[dim]{m['subtitle']}[/]"
                            )
                            mod_items.append(ListItem(Label(label_markup), name=m["id"]))
                        yield ListView(*mod_items, id="admin-modules-list")

                    with Vertical(id="main-workspace"):
                        with Vertical(id="queries-box"):
                            yield Static(
                                "MODULE REQUIREMENTS (Enter or Ctrl+E to run)",
                                id="admin-queries-heading",
                                classes="panel-heading",
                            )
                            yield ListView(id="admin-queries-list")

                        with Horizontal(id="params-box"):
                            for slot_i in range(MAX_PARAM_SLOTS):
                                yield Input(
                                    id=f"admin-param-slot-{slot_i}",
                                    classes="param-input",
                                )
                            yield Static("", id="admin-param-context-label")
                            yield Button("▶ Run [Ctrl+E]", variant="success", id="btn-admin-execute")
                            yield Button("Inspector [F2]", variant="default", id="btn-toggle-inspector")

                        with Vertical(id="results-box"):
                            yield LoadingSpinner(
                                "RESULTS",
                                id="admin-results-heading",
                                classes="panel-heading",
                            )
                            yield DataTable(id="admin-results-table")

                        with VerticalScroll(id="inspector-panel", classes="hidden"):
                            yield Static(
                                "TECHNICAL INSPECTOR (Press F2 to hide)",
                                id="inspector-header",
                            )
                            yield Static("", id="inspector-code")

            # =================================================================
            # TAB 3: QUERY CONSOLE
            # =================================================================
            with TabPane("Query Console", id="tab-console"):
                with Vertical(id="console-container"):
                    with Horizontal(id="console-toolbar"):
                        yield Label("Engine:")
                        yield Select(
                            [
                                ("MongoDB (JSON find / aggregate)", "MongoDB"),
                                ("Apache Cassandra (CQL)", "Cassandra"),
                                ("Dgraph (DQL)", "Dgraph"),
                            ],
                            value="MongoDB",
                            allow_blank=False,
                            id="console-engine-select",
                        )
                        yield Button("▶ Run [Ctrl+E]", variant="primary", id="btn-run-adhoc")
                        yield Button("Reset Template", variant="default", id="btn-clear-adhoc")
                        yield Static("", id="console-toolbar-spacer")
                        yield Button("Table View", variant="success", id="btn-console-view-table")
                        yield Button("JSON View", variant="default", id="btn-console-view-json")

                    yield TextArea(
                        DEFAULT_ADHOC_TEMPLATES["MongoDB"],
                        language="json",
                        id="console-editor",
                    )

                    yield LoadingSpinner(
                        "[dim]Select an engine, edit the query, and press 'Run [Ctrl+E]'.[/]",
                        id="console-status",
                    )

                    with Vertical(id="console-table-box"):
                        yield DataTable(id="console-results-table")
                    with VerticalScroll(id="console-json-box"):
                        yield Static("", id="console-json-output")

            # =================================================================
            # TAB 4: TMDB CATALOG
            # =================================================================
            with TabPane("TMDB Catalog", id="tab-seed"):
                with Vertical(id="seed-container"):
                    yield FigletHeader(
                        "TMDB Catalog",
                        font="slant",
                        color="#58a6ff",
                        subtitle="Recursively download popular movies, directors, and up to 10 cast members into MongoDB without duplicates.",
                        id="seed-figlet-header",
                    )
                    with Horizontal(id="seed-controls-row"):
                        yield Label("Movies (N):")
                        yield Input(value="25", placeholder="e.g. 50", id="inp-seed-count")
                        yield Checkbox(
                            "Enrich people (/person/{id} bio, birth year, nationality)",
                            value=True,
                            id="chk-seed-full-person",
                        )
                        yield Button("Start Ingestion", variant="success", id="btn-start-seed")

                    yield ProgressBar(total=100, show_eta=True, id="seed-progress-bar")
                    yield LoadingSpinner(
                        "[dim]Ready to start. You can also run `python main.py --seed N` from CLI.[/]",
                        id="seed-summary-status",
                    )
                    yield RichLog(highlight=True, markup=True, id="seed-log")

    def on_mount(self) -> None:
        table = self.query_one("#admin-results-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True

        console_table = self.query_one("#console-results-table", DataTable)
        console_table.cursor_type = "row"
        console_table.zebra_stripes = True

        self._set_console_view_mode("table")
        self.query_one("#admin-movies-browser", Vertical).display = False
        self._refresh_header()
        self._refresh_panel_overview()
        self._load_module(0, run_initial=False)

    def on_screen_resume(self) -> None:
        self._refresh_header()
        self._refresh_panel_overview()

    def _refresh_header(self) -> None:
        session = AuthService().current_session
        self.query_one("#btn-user-menu", Button).label = _format_user_menu_label(session)

    @on(Button.Pressed, "#btn-user-menu")
    def _on_user_menu_pressed(self) -> None:
        session = AuthService().current_session

        def _after(action: Optional[str]) -> None:
            if action == "profile":
                self.app.switch_screen("home")
            elif action == "settings":
                self.app.push_screen(SettingsScreen())
            elif action == "help":
                self.app.push_screen(HelpScreen())
            elif action == "logout":
                self.action_logout()

        self.app.push_screen(UserMenuModal(session), _after)

    # =========================================================================
    # TAB 1: PANEL OVERVIEW
    # =========================================================================

    def _refresh_panel_overview(self) -> None:
        statuses = get_databases_status()

        def _fmt(key: str, color: str) -> str:
            st = statuses.get(key, "UNINITIALIZED")
            if st == "INITIALIZED":
                return f"[bold {color}]● CONNECTED[/]"
            return "[bold #f85149]● OFFLINE[/]"

        self.query_one("#health-mongodb", Static).update(_fmt("mongodb", "#3fb950"))
        self.query_one("#health-cassandra", Static).update(_fmt("cassandra", "#58a6ff"))
        self.query_one("#health-dgraph", Static).update(_fmt("dgraph", "#d2a8ff"))
        tmdb_txt = (
            "[bold #3fb950]● CONFIGURED[/]"
            if TMDBService().is_configured
            else "[bold #d29922]● NO TOKEN[/]"
        )
        self.query_one("#health-tmdb", Static).update(tmdb_txt)
        self._load_catalog_stats_worker()

    @work(thread=True, exclusive=True, group="admin-stats")
    def _load_catalog_stats_worker(self) -> None:
        worker = get_current_worker()
        counts = {"movies": "—", "actors": "—", "directors": "—", "users": "—", "reviews": "—"}
        try:
            mongo = MongoConnection()
            if mongo.initialized and mongo.database is not None:
                db = mongo.database
                for col in counts:
                    counts[col] = f"{db[col].count_documents({}):,}"
        except Exception:
            pass
        if not worker.is_cancelled:
            self.app.call_from_thread(self._render_catalog_stats, counts)

    def _render_catalog_stats(self, counts: Dict[str, str]) -> None:
        self.query_one("#stat-movies-count", Static).update(f"[bold #e6edf3]{counts['movies']}[/]")
        self.query_one("#stat-actors-count", Static).update(f"[bold #e6edf3]{counts['actors']}[/]")
        self.query_one("#stat-directors-count", Static).update(f"[bold #e6edf3]{counts['directors']}[/]")
        self.query_one("#stat-users-count", Static).update(f"[bold #e6edf3]{counts['users']}[/]")
        self.query_one("#stat-reviews-count", Static).update(f"[bold #e6edf3]{counts['reviews']}[/]")

    @on(Button.Pressed, "#btn-admin-refresh-health")
    def _on_refresh_health(self) -> None:
        self._refresh_panel_overview()
        show_info_toast(self, "System status refreshed")

    @on(Button.Pressed, "#btn-quick-inspector")
    def _on_quick_inspector(self) -> None:
        self.action_goto_tab("tab-inspector")

    @on(Button.Pressed, "#btn-quick-console")
    def _on_quick_console(self) -> None:
        self.action_goto_tab("tab-console")

    @on(Button.Pressed, "#btn-quick-seed")
    def _on_quick_seed(self) -> None:
        self.action_goto_tab("tab-seed")

    @on(Button.Pressed, "#btn-quick-user-view")
    def _on_quick_user_view(self) -> None:
        self.action_switch_to_user_view()

    @on(ClickableStatCard.Pressed, "#card-stat-movies")
    def _on_movies_card_pressed(self) -> None:
        self.query_one("#admin-panel-scroll", VerticalScroll).display = False
        self.query_one("#admin-movies-browser", Vertical).display = True
        self.query_one("#inp-admin-movies-filter", Input).value = ""
        self.query_one("#admin-movie-preview-body", Static).update(
            "[dim]Loading movies from MongoDB...[/]"
        )
        self._load_admin_movies_worker()

    @on(Button.Pressed, "#btn-admin-movies-back")
    def _on_admin_movies_back(self) -> None:
        self.query_one("#admin-movies-browser", Vertical).display = False
        self.query_one("#admin-panel-scroll", VerticalScroll).display = True

    @on(Input.Changed, "#inp-admin-movies-filter")
    def _on_admin_movies_filter_changed(self, event: Input.Changed) -> None:
        self._apply_admin_movies_filter(event.value)

    @work(thread=True, exclusive=True, group="admin-movies-list")
    def _load_admin_movies_worker(self) -> None:
        worker = get_current_worker()
        docs: List[Dict[str, Any]] = []
        try:
            mongo = MongoConnection()
            if mongo.initialized and mongo.database is not None:
                cursor = (
                    mongo.database["movies"]
                    .find(
                        {},
                        {
                            "title": 1,
                            "release_year": 1,
                            "rating": 1,
                            "impact_score": 1,
                        },
                    )
                    .sort([("impact_score", -1), ("title", 1)])
                )
                for doc in cursor:
                    docs.append(
                        {
                            "id": str(doc["_id"]),
                            "title": str(doc.get("title") or "Untitled"),
                            "release_year": int(doc.get("release_year") or 0),
                            "rating": float(doc.get("rating") or 0.0),
                        }
                    )
        except Exception:
            pass
        if not worker.is_cancelled:
            self.app.call_from_thread(self._render_admin_movies_list, docs)

    def _render_admin_movies_list(self, docs: List[Dict[str, Any]]) -> None:
        self._admin_movies_cache = docs
        self._apply_admin_movies_filter(
            self.query_one("#inp-admin-movies-filter", Input).value
        )

    def _apply_admin_movies_filter(self, query_text: str) -> None:
        needle = (query_text or "").strip().lower()
        if needle:
            filtered = [
                m for m in self._admin_movies_cache if needle in m["title"].lower()
            ]
        else:
            filtered = list(self._admin_movies_cache)
        self._admin_movies_filtered = filtered

        lv = self.query_one("#admin-movies-listview", ListView)
        lv.clear()
        for m in filtered:
            yr = f" ({m['release_year']})" if m["release_year"] else ""
            rt = f"★ {m['rating']:.1f}" if m["rating"] else "★ —"
            words = m["title"].split()
            short_title = " ".join(words[:2]) + ("..." if len(words) > 2 else "")
            lv.append(
                ListItem(
                    Label(f"[bold]{short_title}[/][dim]{yr}[/]  [bold #f0883e]{rt}[/]"),
                )
            )

        if filtered:
            lv.index = 0
            self._load_admin_movie_preview(filtered[0]["id"])
        else:
            self.query_one("#admin-movie-preview-body", Static).update(
                "[dim]No movies match the current filter.[/]"
            )

    @on(ListView.Highlighted, "#admin-movies-listview")
    def _on_admin_movie_highlighted(self, event: ListView.Highlighted) -> None:
        lv = self.query_one("#admin-movies-listview", ListView)
        if lv.index is not None and 0 <= lv.index < len(self._admin_movies_filtered):
            self._load_admin_movie_preview(self._admin_movies_filtered[lv.index]["id"])

    @on(ListView.Selected, "#admin-movies-listview")
    def _on_admin_movie_selected(self, event: ListView.Selected) -> None:
        lv = self.query_one("#admin-movies-listview", ListView)
        if lv.index is not None and 0 <= lv.index < len(self._admin_movies_filtered):
            self._load_admin_movie_preview(self._admin_movies_filtered[lv.index]["id"])

    @work(thread=True, exclusive=True, group="admin-movie-preview")
    def _load_admin_movie_preview(self, movie_id: str) -> None:
        worker = get_current_worker()
        movie_doc: Optional[Dict[str, Any]] = None
        reviews_docs: List[Dict[str, Any]] = []
        user_profiles: Dict[str, Dict[str, Any]] = {}
        person_posters: Dict[str, str] = {}
        person_posters_by_name: Dict[str, str] = {}
        try:
            mongo = MongoConnection()
            if mongo.initialized and mongo.database is not None:
                db = mongo.database
                oid = ObjectId(movie_id)
                movie_doc = db["movies"].find_one({"_id": oid})
                if movie_doc is not None:
                    reviews_docs = list(
                        db["reviews"]
                        .find(
                            {
                                "$or": [
                                    {"movie.id": oid},
                                    {"movie.title": movie_doc.get("title", "")},
                                ]
                            }
                        )
                        .sort("created_at", -1)
                        .limit(25)
                    )
                    dir_ids = [d.get("id") for d in (movie_doc.get("directors") or []) if d.get("id")]
                    dir_names = [d.get("name") for d in (movie_doc.get("directors") or []) if d.get("name")]
                    if dir_ids or dir_names:
                        for ddoc in db["directors"].find(
                            {"$or": [{"_id": {"$in": dir_ids}}, {"name": {"$in": dir_names}}]},
                            {"name": 1, "poster_url": 1, "profile_url": 1, "tmdb_profile_path": 1},
                        ):
                            purl = str(ddoc.get("poster_url") or ddoc.get("profile_url") or "")
                            if not purl and ddoc.get("tmdb_profile_path"):
                                purl = TMDBService().build_image_url(str(ddoc["tmdb_profile_path"]), "w185")
                            if purl:
                                person_posters[str(ddoc["_id"])] = purl
                                if ddoc.get("name"):
                                    person_posters_by_name[str(ddoc["name"]).lower()] = purl
                    cast_ids = [c.get("id") for c in (movie_doc.get("cast") or [])[:10] if c.get("id")]
                    cast_names = [c.get("name") for c in (movie_doc.get("cast") or [])[:10] if c.get("name")]
                    if cast_ids or cast_names:
                        for adoc in db["actors"].find(
                            {"$or": [{"_id": {"$in": cast_ids}}, {"name": {"$in": cast_names}}]},
                            {"name": 1, "poster_url": 1, "profile_url": 1, "tmdb_profile_path": 1},
                        ):
                            purl = str(adoc.get("poster_url") or adoc.get("profile_url") or "")
                            if not purl and adoc.get("tmdb_profile_path"):
                                purl = TMDBService().build_image_url(str(adoc["tmdb_profile_path"]), "w185")
                            if purl:
                                person_posters[str(adoc["_id"])] = purl
                                if adoc.get("name"):
                                    person_posters_by_name[str(adoc["name"]).lower()] = purl
                    usernames = sorted(
                        {
                            str(u)
                            for u in (
                                list(movie_doc.get("liked_by") or [])
                                + list(movie_doc.get("watched_by") or [])
                            )
                            if u
                        }
                    )
                    if usernames:
                        for udoc in db["users"].find(
                            {"username": {"$in": usernames}},
                            {"username": 1, "avatar_url": 1, "lists": 1, "followers_count": 1},
                        ):
                            uname = str(udoc.get("username") or "")
                            if uname:
                                rev_cnt = db["reviews"].count_documents(
                                    {"owner.username": uname}
                                )
                                user_profiles[uname.lower()] = {
                                    "username": uname,
                                    "avatar_url": str(udoc.get("avatar_url") or ""),
                                    "reviews_count": rev_cnt,
                                    "lists_count": len(udoc.get("lists") or []),
                                    "followers_count": int(udoc.get("followers_count") or 0),
                                }
        except Exception:
            pass
        if not worker.is_cancelled:
            self.app.call_from_thread(
                self._render_admin_movie_preview,
                movie_doc,
                reviews_docs,
                user_profiles,
                person_posters,
                person_posters_by_name,
            )

    def _calc_admin_user_cards_per_row(self) -> int:
        try:
            term_width = self.size.width or self.app.size.width
        except Exception:
            term_width = 0
        if not term_width or term_width <= 0:
            return 2
        usable = max(23, term_width - 62)
        return max(1, usable // 23)

    def _calc_admin_review_cards_per_row(self) -> int:
        try:
            term_width = self.size.width or self.app.size.width
        except Exception:
            term_width = 0
        if not term_width or term_width <= 0:
            return 2
        usable = max(44, term_width - 62)
        return max(1, usable // 44)

    def _render_admin_movie_preview(
        self,
        doc: Optional[Dict[str, Any]],
        reviews: List[Dict[str, Any]],
        user_profiles: Dict[str, Dict[str, Any]],
        person_posters: Dict[str, str],
        person_posters_by_name: Dict[str, str],
    ) -> None:
        self._current_movie_doc = doc
        preview = self.query_one("#admin-movie-preview-body", Static)
        title_line = self.query_one("#admin-movie-title-line", Static)
        ids_line = self.query_one("#admin-movie-ids-line", Static)
        poster = self.query_one("#admin-movie-poster", PosterImage)
        if not doc:
            poster.set_poster("", "Movie")
            title_line.update("")
            ids_line.update("")
            preview.update("[bold #f85149]Could not load movie details.[/]")
            self._preview_directors = []
            self._preview_cast = []
            self._preview_liked_users = []
            self._preview_watched_users = []
            self._preview_reviews = []
            self._render_admin_preview_carousels()
            return

        title = str(doc.get("title") or "Untitled")
        poster.set_poster(str(doc.get("poster_url") or ""), title)
        year = doc.get("release_year") or "—"
        decade = doc.get("decade") or "—"
        runtime = f"{doc.get('runtime')} min" if doc.get("runtime") else "—"
        tmdb_id = doc.get("tmdb_id") or "—"
        mongo_id = str(doc.get("_id") or "—")

        title_line.update(f"[bold #58a6ff]{title}[/] [dim]({year})[/]")
        ids_line.update(f"[dim]MongoDB _id: {mongo_id}  │  TMDB ID: {tmdb_id}[/]")

        added_dt = doc.get("added_date")
        if isinstance(added_dt, datetime):
            added_str = added_dt.strftime("%Y-%m-%d %H:%M UTC")
        elif isinstance(doc.get("_id"), ObjectId):
            added_str = (
                f"{doc['_id'].generation_time.strftime('%Y-%m-%d %H:%M UTC')} "
                "[dim](from ObjectId)[/]"
            )
        else:
            added_str = "Not recorded"

        rating = float(doc.get("rating") or 0.0)
        ratings_count = int(doc.get("ratings_count") or 0)
        impact_score = float(doc.get("impact_score") or 0.0)
        likes_count = int(doc.get("likes") or 0)

        genres = ", ".join(doc.get("genres") or []) or "—"
        countries = ", ".join(doc.get("countries") or []) or "—"
        lang_obj = doc.get("language") or {}
        orig_lang = lang_obj.get("original") or "—"
        avail_langs = ", ".join(lang_obj.get("availables") or []) or orig_lang
        streaming = ", ".join(doc.get("available_streaming") or []) or "None listed"
        synopsis = str(doc.get("synopsis") or "").strip() or "No synopsis available."

        lines: List[str] = [
            "[bold #79c0ff]Synopsis[/]",
            "",
            f"  {synopsis}",
            "",
            "",
            "[bold #79c0ff]Database & Catalog Metadata[/]",
            "",
            f"  • [bold]Added to DB:[/] {added_str}",
            "",
            f"  • [bold]Rating:[/] ★ {rating:.2f} ({ratings_count:,} votes)   │   "
            f"[bold]Impact:[/] {impact_score:.4f}   │   [bold]Likes:[/] {likes_count}",
            "",
            f"  • [bold]Decade:[/] {decade}   │   [bold]Runtime:[/] {runtime}",
            "",
            f"  • [bold]Genres:[/] {genres}",
            "",
            f"  • [bold]Countries:[/] {countries}",
            "",
            f"  • [bold]Languages:[/] {orig_lang} (available: {avail_langs})",
            "",
            f"  • [bold]Streaming:[/] {streaming}",
        ]
        preview.update("\n".join(lines))

        self._preview_directors = [
            {
                "id": str(d.get("id") or ""),
                "name": str(d.get("name") or "Unknown"),
                "poster_url": str(
                    d.get("poster_url")
                    or person_posters.get(str(d.get("id") or ""))
                    or person_posters_by_name.get(str(d.get("name") or "").lower(), "")
                ),
                "character": "Director",
            }
            for d in (doc.get("directors") or [])
            if d.get("name")
        ]
        self._preview_cast = [
            {
                "id": str(c.get("id") or ""),
                "name": str(c.get("name") or "Unknown"),
                "poster_url": str(
                    c.get("poster_url")
                    or person_posters.get(str(c.get("id") or ""))
                    or person_posters_by_name.get(str(c.get("name") or "").lower(), "")
                ),
                "character": str(c.get("character") or "Actor"),
            }
            for c in (doc.get("cast") or [])[:10]
            if c.get("name")
        ]

        def _build_user_list(names: List[Any]) -> List[Dict[str, Any]]:
            result: List[Dict[str, Any]] = []
            for raw_u in names:
                uname = str(raw_u or "").strip()
                if not uname:
                    continue
                prof = user_profiles.get(uname.lower())
                if prof:
                    result.append(prof)
                else:
                    result.append(
                        {
                            "username": uname,
                            "avatar_url": "",
                            "reviews_count": 0,
                            "lists_count": 0,
                            "followers_count": 0,
                        }
                    )
            return result

        self._preview_liked_users = _build_user_list(doc.get("liked_by") or [])
        self._preview_watched_users = _build_user_list(doc.get("watched_by") or [])
        self._preview_reviews = list(reviews)
        self._dir_offset = 0
        self._cast_offset = 0
        self._liked_offset = 0
        self._watched_offset = 0
        self._rev_offset = 0
        self._render_admin_preview_carousels()

    def _render_admin_preview_carousels(self) -> None:
        user_per_row = self._calc_admin_user_cards_per_row()
        rev_per_row = self._calc_admin_review_cards_per_row()

        # Directors carousel
        self.query_one("#admin-dir-heading", Static).update(
            f"DIRECTORS ({len(self._preview_directors)})"
        )
        dir_bar = self.query_one("#admin-movie-dir-bar", Horizontal)
        dir_prev = self.query_one("#btn-admin-dir-prev", Button)
        dir_next = self.query_one("#btn-admin-dir-next", Button)
        if not self._preview_directors:
            dir_bar.remove_children()
            dir_bar.mount(Static("[dim]No directors recorded.[/]", classes="empty-inline-msg"))
            dir_prev.display = False
            dir_next.display = False
        else:
            needs_dir_nav = len(self._preview_directors) > user_per_row
            dir_prev.display = needs_dir_nav
            dir_next.display = needs_dir_nav
            dir_prev.disabled = self._dir_offset <= 0
            dir_next.disabled = self._dir_offset + user_per_row >= len(self._preview_directors)
            dir_slice = self._preview_directors[self._dir_offset : self._dir_offset + user_per_row]
            dir_cards = [
                PersonCard(
                    person_id=d["id"],
                    person_name=d["name"],
                    kind="director",
                    poster_url=d["poster_url"],
                    character=d["character"],
                )
                for d in dir_slice
            ]
            populate_carousel_bar(dir_bar, dir_cards, user_per_row)

        # Cast carousel
        self.query_one("#admin-cast-heading", Static).update(
            f"CAST ({len(self._preview_cast)})"
        )
        cast_bar = self.query_one("#admin-movie-cast-bar", Horizontal)
        cast_prev = self.query_one("#btn-admin-cast-prev", Button)
        cast_next = self.query_one("#btn-admin-cast-next", Button)
        if not self._preview_cast:
            cast_bar.remove_children()
            cast_bar.mount(Static("[dim]No cast recorded.[/]", classes="empty-inline-msg"))
            cast_prev.display = False
            cast_next.display = False
        else:
            needs_cast_nav = len(self._preview_cast) > user_per_row
            cast_prev.display = needs_cast_nav
            cast_next.display = needs_cast_nav
            cast_prev.disabled = self._cast_offset <= 0
            cast_next.disabled = self._cast_offset + user_per_row >= len(self._preview_cast)
            cast_slice = self._preview_cast[self._cast_offset : self._cast_offset + user_per_row]
            cast_cards = [
                PersonCard(
                    person_id=c["id"],
                    person_name=c["name"],
                    kind="actor",
                    poster_url=c["poster_url"],
                    character=c["character"],
                )
                for c in cast_slice
            ]
            populate_carousel_bar(cast_bar, cast_cards, user_per_row)

        # Liked by carousel
        self.query_one("#admin-liked-heading", Static).update(
            f"LIKED BY ({len(self._preview_liked_users)})"
        )
        liked_bar = self.query_one("#admin-movie-liked-bar", Horizontal)
        liked_prev = self.query_one("#btn-admin-liked-prev", Button)
        liked_next = self.query_one("#btn-admin-liked-next", Button)
        if not self._preview_liked_users:
            liked_bar.remove_children()
            liked_bar.mount(Static("[dim]No users have liked this movie yet.[/]", classes="empty-inline-msg"))
            liked_prev.display = False
            liked_next.display = False
        else:
            needs_liked_nav = len(self._preview_liked_users) > user_per_row
            liked_prev.display = needs_liked_nav
            liked_next.display = needs_liked_nav
            liked_prev.disabled = self._liked_offset <= 0
            liked_next.disabled = (
                self._liked_offset + user_per_row >= len(self._preview_liked_users)
            )
            liked_slice = self._preview_liked_users[
                self._liked_offset : self._liked_offset + user_per_row
            ]
            liked_cards = [
                UserCard(
                    username=u["username"],
                    avatar_url=u["avatar_url"],
                    reviews_count=u["reviews_count"],
                    lists_count=u["lists_count"],
                    followers_count=u["followers_count"],
                )
                for u in liked_slice
            ]
            populate_carousel_bar(liked_bar, liked_cards, user_per_row)

        # Watched by carousel
        self.query_one("#admin-watched-heading", Static).update(
            f"WATCHED BY ({len(self._preview_watched_users)})"
        )
        watched_bar = self.query_one("#admin-movie-watched-bar", Horizontal)
        watched_prev = self.query_one("#btn-admin-watched-prev", Button)
        watched_next = self.query_one("#btn-admin-watched-next", Button)
        if not self._preview_watched_users:
            watched_bar.remove_children()
            watched_bar.mount(Static("[dim]No users have marked this movie as watched yet.[/]", classes="empty-inline-msg"))
            watched_prev.display = False
            watched_next.display = False
        else:
            needs_watched_nav = len(self._preview_watched_users) > user_per_row
            watched_prev.display = needs_watched_nav
            watched_next.display = needs_watched_nav
            watched_prev.disabled = self._watched_offset <= 0
            watched_next.disabled = (
                self._watched_offset + user_per_row >= len(self._preview_watched_users)
            )
            watched_slice = self._preview_watched_users[
                self._watched_offset : self._watched_offset + user_per_row
            ]
            watched_cards = [
                UserCard(
                    username=u["username"],
                    avatar_url=u["avatar_url"],
                    reviews_count=u["reviews_count"],
                    lists_count=u["lists_count"],
                    followers_count=u["followers_count"],
                )
                for u in watched_slice
            ]
            populate_carousel_bar(watched_bar, watched_cards, user_per_row)

        # Reviews carousel
        self.query_one("#admin-reviews-heading", Static).update(
            f"REVIEWS ({len(self._preview_reviews)})"
        )
        rev_bar = self.query_one("#admin-movie-reviews-bar", Horizontal)
        rev_prev = self.query_one("#btn-admin-rev-prev", Button)
        rev_next = self.query_one("#btn-admin-rev-next", Button)
        if not self._preview_reviews:
            rev_bar.remove_children()
            rev_bar.mount(Static("[dim]No user reviews yet.[/]", classes="empty-inline-msg"))
            rev_prev.display = False
            rev_next.display = False
        else:
            needs_rev_nav = len(self._preview_reviews) > rev_per_row
            rev_prev.display = needs_rev_nav
            rev_next.display = needs_rev_nav
            rev_prev.disabled = self._rev_offset <= 0
            rev_next.disabled = self._rev_offset + rev_per_row >= len(self._preview_reviews)
            rev_slice = self._preview_reviews[
                self._rev_offset : self._rev_offset + rev_per_row
            ]
            rev_cards: List[Vertical] = []
            for rev in rev_slice:
                owner = str((rev.get("owner") or {}).get("username") or "unknown")
                rev_rating = float(rev.get("rating") or 0.0)
                rev_likes = int(rev.get("likes") or 0)
                created = rev.get("created_at")
                created_str = (
                    created.strftime("%Y-%m-%d")
                    if isinstance(created, datetime)
                    else ""
                )
                content = str(rev.get("content") or "").strip() or "[dim](No review text)[/]"
                if len(content) > 150:
                    content = f"{content[:147]}..."
                rev_cards.append(
                    ClickableReviewCard(
                        str(rev.get("_id") or ""),
                        Horizontal(
                            Static(f"[bold #79c0ff]@{owner}[/]", classes="review-movie-title-link"),
                            Static(
                                f"  [bold #f0883e]★ {rev_rating:.1f}[/]  "
                                f"[bold #3fb950]♥ {rev_likes}[/]  [dim]{created_str}[/]",
                                classes="review-card-meta",
                            ),
                            classes="review-card-header",
                        ),
                        Static(content, classes="review-item-body"),
                        classes="review-item-card admin-clickable-card",
                    )
                )
            populate_carousel_bar(
                rev_bar,
                rev_cards,
                rev_per_row,
                empty_slot_class="carousel-review-empty-slot",
            )

    @on(Button.Pressed, "#btn-admin-dir-prev")
    def _on_admin_dir_prev(self) -> None:
        if self._dir_offset > 0:
            self._dir_offset -= 1
            self._render_admin_preview_carousels()

    @on(Button.Pressed, "#btn-admin-dir-next")
    def _on_admin_dir_next(self) -> None:
        per_row = self._calc_admin_user_cards_per_row()
        if self._dir_offset + per_row < len(self._preview_directors):
            self._dir_offset += 1
            self._render_admin_preview_carousels()

    @on(Button.Pressed, "#btn-admin-cast-prev")
    def _on_admin_cast_prev(self) -> None:
        if self._cast_offset > 0:
            self._cast_offset -= 1
            self._render_admin_preview_carousels()

    @on(Button.Pressed, "#btn-admin-cast-next")
    def _on_admin_cast_next(self) -> None:
        per_row = self._calc_admin_user_cards_per_row()
        if self._cast_offset + per_row < len(self._preview_cast):
            self._cast_offset += 1
            self._render_admin_preview_carousels()

    @on(Button.Pressed, "#btn-admin-liked-prev")
    def _on_admin_liked_prev(self) -> None:
        if self._liked_offset > 0:
            self._liked_offset -= 1
            self._render_admin_preview_carousels()

    @on(Button.Pressed, "#btn-admin-liked-next")
    def _on_admin_liked_next(self) -> None:
        per_row = self._calc_admin_user_cards_per_row()
        if self._liked_offset + per_row < len(self._preview_liked_users):
            self._liked_offset += 1
            self._render_admin_preview_carousels()

    @on(Button.Pressed, "#btn-admin-watched-prev")
    def _on_admin_watched_prev(self) -> None:
        if self._watched_offset > 0:
            self._watched_offset -= 1
            self._render_admin_preview_carousels()

    @on(Button.Pressed, "#btn-admin-watched-next")
    def _on_admin_watched_next(self) -> None:
        per_row = self._calc_admin_user_cards_per_row()
        if self._watched_offset + per_row < len(self._preview_watched_users):
            self._watched_offset += 1
            self._render_admin_preview_carousels()

    @on(Button.Pressed, "#btn-admin-rev-prev")
    def _on_admin_rev_prev(self) -> None:
        if self._rev_offset > 0:
            self._rev_offset -= 1
            self._render_admin_preview_carousels()

    @on(Button.Pressed, "#btn-admin-rev-next")
    def _on_admin_rev_next(self) -> None:
        per_row = self._calc_admin_review_cards_per_row()
        if self._rev_offset + per_row < len(self._preview_reviews):
            self._rev_offset += 1
            self._render_admin_preview_carousels()

    def on_resize(self, _event: Resize) -> None:
        if self.query_one("#admin-movies-browser", Vertical).display:
            self._render_admin_preview_carousels()

    @on(Button.Pressed, "#btn-admin-edit-movie")
    def _on_admin_edit_movie(self) -> None:
        doc = self._current_movie_doc
        if not doc:
            return
        fields = [
            ("title", "Title", str(doc.get("title") or ""), False),
            ("release_year", "Release Year", str(doc.get("release_year") or ""), False),
            ("runtime", "Runtime (minutes)", str(doc.get("runtime") or "0"), False),
            ("rating", "Rating (0.0 - 5.0)", str(doc.get("rating") or "0.0"), False),
            ("genres", "Genres (comma-separated)", ", ".join(doc.get("genres") or []), False),
            ("countries", "Countries (comma-separated)", ", ".join(doc.get("countries") or []), False),
            ("synopsis", "Synopsis", str(doc.get("synopsis") or ""), True),
        ]

        def _after_edit(vals: Optional[Dict[str, str]]) -> None:
            if not vals or self._current_movie_doc is None:
                return
            try:
                mongo = MongoConnection()
                if not mongo.initialized or mongo.database is None:
                    show_error_toast(self, "MongoDB is not connected.")
                    return
                db = mongo.database
                year = int(vals["release_year"].strip() or 0)
                runtime = max(0, int(vals["runtime"].strip() or 0))
                rating = max(0.0, min(5.0, float(vals["rating"].strip() or 0.0)))
                genres = [g.strip() for g in vals["genres"].split(",") if g.strip()]
                countries = [c.strip() for c in vals["countries"].split(",") if c.strip()]
                title = vals["title"].strip() or str(self._current_movie_doc.get("title") or "Untitled")
                decade = (year // 10) * 10 if year else int(self._current_movie_doc.get("decade") or 0)
                db["movies"].update_one(
                    {"_id": self._current_movie_doc["_id"]},
                    {
                        "$set": {
                            "title": title,
                            "release_year": year,
                            "decade": decade,
                            "runtime": runtime,
                            "rating": rating,
                            "genres": genres,
                            "countries": countries,
                            "synopsis": vals["synopsis"].strip(),
                        }
                    },
                )
                show_success_toast(self, f"Updated '{title}' in MongoDB")
                self._load_admin_movies_worker()
            except Exception as exc:
                show_error_toast(self, f"Error updating movie: {exc}")

        self.app.push_screen(AdminEditModal("Edit Movie", fields), _after_edit)

    @on(Button.Pressed, "#btn-admin-delete-movie")
    def _on_admin_delete_movie(self) -> None:
        doc = self._current_movie_doc
        if not doc:
            return
        title = str(doc.get("title") or "Untitled")

        def _after_confirm(confirmed: bool) -> None:
            if not confirmed or self._current_movie_doc is None:
                return
            try:
                mongo = MongoConnection()
                if not mongo.initialized or mongo.database is None:
                    show_error_toast(self, "MongoDB is not connected.")
                    return
                db = mongo.database
                oid = self._current_movie_doc["_id"]
                db["movies"].delete_one({"_id": oid})
                db["reviews"].delete_many({"$or": [{"movie.id": oid}, {"movie.title": title}]})
                self._current_movie_doc = None
                show_success_toast(self, f"Deleted '{title}' from MongoDB")
                self._load_admin_movies_worker()
                self._load_catalog_stats_worker()
            except Exception as exc:
                show_error_toast(self, f"Error deleting movie: {exc}")

        self.app.push_screen(
            ConfirmModal(
                title="Delete Movie",
                message=f"Permanently delete '{title}' and its reviews from MongoDB?",
                confirm_label="Delete",
                confirm_variant="error",
            ),
            _after_confirm,
        )

    @on(PersonCard.Selected)
    def _on_admin_person_card_selected(self, event: PersonCard.Selected) -> None:
        if not self.query_one("#admin-movies-browser", Vertical).display:
            return

        def _after(status: Optional[str]) -> None:
            if status in ("updated", "deleted") and self._current_movie_doc is not None:
                self._load_admin_movie_preview(str(self._current_movie_doc["_id"]))
                self._load_catalog_stats_worker()

        self.app.push_screen(
            AdminEntityScreen(event.kind, event.person_id, event.person_name),
            _after,
        )

    @on(UserCard.Selected)
    def _on_admin_user_card_selected(self, event: UserCard.Selected) -> None:
        if not self.query_one("#admin-movies-browser", Vertical).display:
            return

        def _after(status: Optional[str]) -> None:
            if status in ("updated", "deleted") and self._current_movie_doc is not None:
                self._load_admin_movie_preview(str(self._current_movie_doc["_id"]))
                self._load_catalog_stats_worker()

        self.app.push_screen(
            AdminEntityScreen("user", event.username),
            _after,
        )

    @on(ClickableReviewCard.Selected)
    def _on_admin_review_card_selected(self, event: ClickableReviewCard.Selected) -> None:
        if not self.query_one("#admin-movies-browser", Vertical).display:
            return

        def _after(status: Optional[str]) -> None:
            if status in ("updated", "deleted") and self._current_movie_doc is not None:
                self._load_admin_movie_preview(str(self._current_movie_doc["_id"]))
                self._load_catalog_stats_worker()

        self.app.push_screen(
            AdminEntityScreen("review", event.review_id),
            _after,
        )

    # =========================================================================
    # TAB 2: REQUIREMENTS INSPECTOR
    # =========================================================================

    @on(ListView.Highlighted, "#admin-modules-list")
    def on_module_highlighted(self, event: ListView.Highlighted) -> None:
        mod_list = self.query_one("#admin-modules-list", ListView)
        if mod_list.index is not None and mod_list.index != self._active_module_idx:
            self._load_module(mod_list.index, run_initial=False)

    @on(ListView.Selected, "#admin-modules-list")
    def on_module_selected(self, event: ListView.Selected) -> None:
        self.query_one("#admin-queries-list", ListView).focus()

    def _load_module(self, idx: int, run_initial: bool = False) -> None:
        self._active_module_idx = idx
        module = self._modules[idx]
        self._current_queries = get_queries_by_module(module["id"])

        engine_name = (
            self._current_queries[0].database if self._current_queries else "MongoDB"
        )
        self.query_one("#admin-queries-heading", Static).update(
            f"{module['name'].upper()}  {format_engine_badge(engine_name)}  "
            "[dim](Enter or Ctrl+E to run)[/]"
        )

        q_list = self.query_one("#admin-queries-list", ListView)
        q_list.clear()
        for q in self._current_queries:
            user_tag = " [bold #d2a8ff]👤[/]" if q.requires_active_user else ""
            q_list.append(ListItem(Label(f"[bold]{q.title}[/]{user_tag}"), name=q.id))

        if self._current_queries:
            q_list.index = 0
            self._prepare_query_inputs(self._current_queries[0], execute_now=run_initial)

    @on(ListView.Highlighted, "#admin-queries-list")
    def on_query_highlighted(self, event: ListView.Highlighted) -> None:
        q_list = self.query_one("#admin-queries-list", ListView)
        if q_list.index is not None and 0 <= q_list.index < len(self._current_queries):
            target_q = self._current_queries[q_list.index]
            if self._active_query is None or self._active_query.id != target_q.id:
                self._prepare_query_inputs(target_q, execute_now=False)

    @on(ListView.Selected, "#admin-queries-list")
    def on_query_selected(self, event: ListView.Selected) -> None:
        self._run_current_query()

    def _prepare_query_inputs(self, qspec: QuerySpec, execute_now: bool = False) -> None:
        self._active_query = qspec
        ctx_label = self.query_one("#admin-param-context-label", Static)
        session = AuthService().current_session
        active_uname = session.username if session else ""

        for slot_i in range(MAX_PARAM_SLOTS):
            inp = self.query_one(f"#admin-param-slot-{slot_i}", Input)
            if slot_i < len(qspec.params):
                param = qspec.params[slot_i]
                inp.display = True
                default_val = param.default
                if param.name == "username" and not default_val and active_uname:
                    default_val = active_uname
                inp.value = default_val
                inp.placeholder = f"{param.label}: {param.placeholder}"
                inp.border_title = param.label
            else:
                inp.display = False
                inp.value = ""

        if qspec.params:
            ctx_label.display = False
        else:
            ctx_label.display = True
            ctx_label.update(f"[dim]Active user: @{active_uname or 'guest'}  [/]")

        if execute_now:
            self._run_current_query()
        else:
            self.query_one("#inspector-header", Static).update(
                f"SELECTED: {qspec.title}  │  {format_engine_badge(qspec.database)}  │  "
                f"Columns: {', '.join(qspec.expected_columns)}"
            )

    @on(Button.Pressed, "#btn-admin-execute")
    def on_execute_pressed(self) -> None:
        self._run_current_query()

    @on(Button.Pressed, "#btn-toggle-inspector")
    def on_toggle_inspector_pressed(self) -> None:
        self.action_toggle_inspector()

    @on(Input.Submitted)
    def on_param_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "inp-seed-count":
            self._start_seed_process()
            return
        if self.query_one("#admin-tabs", TabbedContent).active == "tab-inspector":
            self._run_current_query()

    def action_execute_active_query(self) -> None:
        active_tab = self.query_one("#admin-tabs", TabbedContent).active
        if active_tab == "tab-console":
            self._run_adhoc_query()
        elif active_tab == "tab-seed":
            self._start_seed_process()
        elif active_tab == "tab-inspector":
            self._run_current_query()

    def _collect_params(self) -> Dict[str, str]:
        if not self._active_query:
            return {}
        collected: Dict[str, str] = {}
        for slot_i, p in enumerate(self._active_query.params[:MAX_PARAM_SLOTS]):
            inp = self.query_one(f"#admin-param-slot-{slot_i}", Input)
            collected[p.name] = inp.value
        return collected

    def _run_current_query(self) -> None:
        if not self._active_query:
            return
        params = self._collect_params()
        self.query_one("#admin-results-heading", LoadingSpinner).start_spinner(
            f"Running {self._active_query.title}..."
        )
        self._execute_req_worker(self._active_query.id, params)

    @work(thread=True, exclusive=True, group="admin-req")
    def _execute_req_worker(self, query_id: str, params: Dict[str, str]) -> None:
        worker = get_current_worker()
        result: QueryResult = execute_query(query_id, params)
        if not worker.is_cancelled:
            self.app.call_from_thread(self._render_result, result)

    def _render_result(self, result: QueryResult) -> None:
        res_heading = self.query_one("#admin-results-heading", LoadingSpinner)
        res_heading.stop_spinner(hide=False)
        res_heading.update(
            f"{result.title} — {len(result.rows)} rows (total: {result.total_count})  │  "
            f"{format_engine_badge(result.database)}  │  {result.execution_ms:.2f} ms  │  "
            f"{format_source_badge(result.data_source)}"
        )

        table = self.query_one("#admin-results-table", DataTable)
        table.clear(columns=True)
        for col in result.columns:
            table.add_column(col)
        for row in result.rows:
            if isinstance(row, dict):
                table.add_row(*[str(row.get(col, "")) for col in result.columns])
            elif isinstance(row, (list, tuple)):
                table.add_row(*[str(cell) for cell in row])

        insp_header = self.query_one("#inspector-header", Static)
        insp_header.update(
            f"TECHNICAL INSPECTOR [F2]  │  {format_engine_badge(result.database)}  │  "
            f"Source: {format_source_badge(result.data_source)}  │  "
            f"Latency: [bold #3fb950]{result.execution_ms:.2f} ms[/]"
        )

        syntax = Syntax(
            result.raw_query,
            result.query_language,
            theme="monokai",
            line_numbers=True,
            word_wrap=True,
        )
        self.query_one("#inspector-code", Static).update(syntax)

    def action_toggle_inspector(self) -> None:
        panel = self.query_one("#inspector-panel", VerticalScroll)
        self._inspector_visible = not self._inspector_visible
        if self._inspector_visible:
            panel.remove_class("hidden")
        else:
            panel.add_class("hidden")

    # =========================================================================
    # TAB 3: QUERY CONSOLE
    # =========================================================================

    def _set_console_view_mode(self, mode: str) -> None:
        self._console_view_mode = mode
        table_box = self.query_one("#console-table-box", Vertical)
        json_box = self.query_one("#console-json-box", VerticalScroll)
        btn_table = self.query_one("#btn-console-view-table", Button)
        btn_json = self.query_one("#btn-console-view-json", Button)

        if mode == "json":
            table_box.display = False
            json_box.display = True
            btn_table.variant = "default"
            btn_json.variant = "success"
        else:
            table_box.display = True
            json_box.display = False
            btn_table.variant = "success"
            btn_json.variant = "default"

    @on(Button.Pressed, "#btn-console-view-table")
    def _on_console_table_view(self) -> None:
        self._set_console_view_mode("table")

    @on(Button.Pressed, "#btn-console-view-json")
    def _on_console_json_view(self) -> None:
        self._set_console_view_mode("json")

    @on(Select.Changed, "#console-engine-select")
    def on_console_engine_changed(self, event: Select.Changed) -> None:
        engine = str(event.value)
        editor = self.query_one("#console-editor", TextArea)
        editor.load_text(DEFAULT_ADHOC_TEMPLATES.get(engine, ""))
        if engine == "MongoDB":
            editor.language = "json"
        elif engine == "Cassandra":
            editor.language = "sql"
        else:
            editor.language = None

    @on(Button.Pressed, "#btn-clear-adhoc")
    def on_clear_adhoc_pressed(self) -> None:
        engine = str(self.query_one("#console-engine-select", Select).value)
        self.query_one("#console-editor", TextArea).load_text(
            DEFAULT_ADHOC_TEMPLATES.get(engine, "")
        )

    @on(Button.Pressed, "#btn-run-adhoc")
    def on_run_adhoc_pressed(self) -> None:
        self._run_adhoc_query()

    def _run_adhoc_query(self) -> None:
        engine = str(self.query_one("#console-engine-select", Select).value)
        query_text = self.query_one("#console-editor", TextArea).text
        status_label = self.query_one("#console-status", LoadingSpinner)
        status_label.start_spinner(f"Executing ad-hoc query in {engine}...")
        self._execute_adhoc_worker(engine, query_text)

    @work(thread=True, exclusive=True, group="admin-adhoc")
    def _execute_adhoc_worker(self, engine: str, query_text: str) -> None:
        worker = get_current_worker()
        res = execute_raw_query(engine, query_text)
        if not worker.is_cancelled:
            self.app.call_from_thread(self._render_adhoc_result, engine, res)

    def _render_adhoc_result(self, engine: str, res: Dict[str, Any]) -> None:
        status_label = self.query_one("#console-status", LoadingSpinner)
        status_label.stop_spinner(hide=False)
        table = self.query_one("#console-results-table", DataTable)
        json_out = self.query_one("#console-json-output", Static)
        table.clear(columns=True)

        if not res["ok"]:
            status_label.update(
                f"[bold #f85149]✖ Error in {engine} ({res['execution_ms']:.2f} ms): {res['error']}[/]"
            )
            json_out.update(f"[bold #f85149]{res['error']}[/]")
            self._set_console_view_mode("json")
            return

        rows = res["rows"]
        status_label.update(
            f"[bold #3fb950]✔ Query executed in {engine} — {len(rows)} records "
            f"in {res['execution_ms']:.2f} ms[/]"
        )

        if rows and isinstance(rows[0], dict):
            cols = list(rows[0].keys())
            for col in cols:
                table.add_column(str(col))
            for r in rows:
                table.add_row(*[str(r.get(c, "")) for c in cols])

        pretty = json.dumps(rows, indent=2, default=str, ensure_ascii=False)
        json_out.update(Syntax(pretty, "json", theme="monokai", word_wrap=True))

    # =========================================================================
    # TAB 4: TMDB CATALOG
    # =========================================================================

    @on(Button.Pressed, "#btn-start-seed")
    def on_start_seed_pressed(self) -> None:
        self._start_seed_process()

    def _start_seed_process(self) -> None:
        raw_n = self.query_one("#inp-seed-count", Input).value.strip()
        try:
            n = max(1, min(500, int(raw_n)))
        except ValueError:
            n = 25

        include_person = self.query_one("#chk-seed-full-person", Checkbox).value
        pbar = self.query_one("#seed-progress-bar", ProgressBar)
        pbar.update(total=n, progress=0)

        log = self.query_one("#seed-log", RichLog)
        log.clear()
        log.write(
            f"[bold #58a6ff]▶ Starting recursive ingestion of {n} popular movies from TMDB...[/]"
        )
        self.query_one("#seed-summary-status", LoadingSpinner).start_spinner(
            f"Processing 0 / {n} movies..."
        )
        self.query_one("#btn-start-seed", Button).disabled = True
        self._seed_worker(n, include_person)

    @work(thread=True, exclusive=True, group="admin-seed")
    def _seed_worker(self, n: int, include_person: bool) -> None:
        worker = get_current_worker()
        try:
            mongo = MongoConnection()
            db = mongo.database if mongo.initialized else None
        except Exception:
            db = None

        def _progress_cb(curr: int, total: int, title: str, tag: str) -> None:
            if not worker.is_cancelled:
                self.app.call_from_thread(self._on_seed_step, curr, total, title, tag)

        report = CatalogService().populate_popular(
            db=db,
            n=n,
            include_person_details=include_person,
            on_progress=_progress_cb,
        )
        if not worker.is_cancelled:
            self.app.call_from_thread(self._on_seed_complete, report)

    def _on_seed_step(self, curr: int, total: int, title: str, tag: str) -> None:
        pbar = self.query_one("#seed-progress-bar", ProgressBar)
        pbar.update(total=total, progress=curr)
        log = self.query_one("#seed-log", RichLog)

        if tag == "new":
            log.write(f"[bold #3fb950]✔ [{curr}/{total}] NEW:[/] {title} (+ directors/cast)")
        elif tag == "skipped":
            log.write(f"[dim]↷ [{curr}/{total}] ALREADY EXISTS:[/] {title}")
        else:
            log.write(f"[bold #f85149]✖ [{curr}/{total}] ERROR:[/] {title}")

        self.query_one("#seed-summary-status", LoadingSpinner).set_spinner_text(
            f"Processing {curr} / {total}: {title}"
        )

    def _on_seed_complete(self, report: PopulateReport) -> None:
        self.query_one("#btn-start-seed", Button).disabled = False
        status = self.query_one("#seed-summary-status", LoadingSpinner)
        status.stop_spinner(hide=False)
        summary = (
            f"[bold #3fb950]✔ POPULATION COMPLETE:[/] Processed: {report.processed}  │  "
            f"New movies: [bold]{report.new_movies}[/]  │  "
            f"Skipped (duplicates): {report.skipped_existing}  │  "
            f"New actors: [bold]{report.new_actors}[/]  │  "
            f"New directors: [bold]{report.new_directors}[/]  │  "
            f"Errors: {report.errors}"
        )
        status.update(summary)
        self.query_one("#seed-log", RichLog).write(f"\n{summary}")
        self._load_catalog_stats_worker()

    # =========================================================================
    # GLOBAL ADMIN ACTIONS
    # =========================================================================

    def action_goto_tab(self, tab_id: str) -> None:
        self.query_one("#admin-tabs", TabbedContent).active = tab_id

    def action_open_help(self) -> None:
        self.app.push_screen(HelpScreen())

    def action_switch_to_user_view(self) -> None:
        self.app.switch_screen("home")

    def action_logout(self) -> None:
        AuthService().logout()
        self.app.switch_screen("auth")
