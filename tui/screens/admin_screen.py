"""
MovieVault Technical Administration Panel (backend/tui/screens/admin_screen.py).

Includes 3 technical tabs:
1. 🔍 Requirements Inspector (24):
   - Browser for the 24 official requirements without accidental auto-execution
     when using arrow keys; runs in background with `@work(thread=True)`.
   - Detailed technical inspector (F2) with syntax highlighting, latency, total
     matches, and source (`MONGODB LOCAL` vs `TMDB FALLBACK -> SAVED TO MONGODB`).
2. ⚡ Interactive Query Console:
   - Write and execute ad-hoc queries directly on MongoDB (JSON),
     Cassandra (CQL), or Dgraph (DQL).
3. 📦 Populate TMDB Catalog:
   - Populate the database with `N` popular movies from TMDB recursively
     (movie + directors + up to 10 main cast with bio/nationality) without duplicates,
     displaying progress bar and live log.
"""

import json
from typing import Dict, List, Optional

from rich.syntax import Syntax
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
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
from tui.screens.help_screen import HelpScreen

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


def build_admin_header(session: Optional[UserSession]) -> str:
    """Build accessible technical header (symbol + text) with status of the 3 DBs and TMDB."""
    statuses = get_databases_status()

    def dot(key: str, label: str, color: str) -> str:
        st = statuses.get(key, "UNINITIALIZED")
        if st == "INITIALIZED":
            return f"[bold {color}]✔ {label}: CONNECTED[/]"
        return f"[bold #f85149]✖ {label}: OFFLINE[/]"

    mongo_str = dot("mongodb", "MongoDB", "#3fb950")
    cass_str = dot("cassandra", "Cassandra", "#58a6ff")
    dgraph_str = dot("dgraph", "Dgraph", "#d2a8ff")
    tmdb_str = (
        "[bold #79c0ff]✔ TMDB: ACTIVE TOKEN[/]"
        if TMDBService().is_configured
        else "[bold #d29922]✖ TMDB: NO TOKEN[/]"
    )
    user_str = (
        f"[bold #79c0ff]👤 @{session.username}[/]"
        if session
        else "[bold #f0883e]🔒 Admin[/]"
    )
    return (
        f"[bold #f85149]🛠️ ADMIN PANEL[/]  │  {user_str}  │  "
        f"{mongo_str}  {cass_str}  {dgraph_str}  {tmdb_str}"
    )


class AdminScreen(Screen):
    """Admin Panel with Requirements Inspector, Ad-Hoc Console, and TMDB Seeder."""

    BINDINGS = [
        Binding("f1", "open_help", "Help", show=True, priority=True),
        Binding("f2", "toggle_inspector", "Inspector Toggle", show=True, priority=True),
        Binding("f3", "switch_to_user_view", "User View", show=True, priority=True),
        Binding("ctrl+e", "execute_active_query", "Run Query", show=True, priority=True),
        Binding("ctrl+l", "logout", "Go to Login", show=True, priority=True),
        Binding("q", "app.quit", "Quit", show=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._modules: List[Dict[str, str]] = get_modules()
        self._active_module_idx: int = -1
        self._current_queries: List[QuerySpec] = []
        self._active_query: Optional[QuerySpec] = None
        self._inspector_visible: bool = True

    def compose(self) -> ComposeResult:
        session = AuthService().current_session
        yield Static(build_admin_header(session), id="top-bar")

        with TabbedContent(id="admin-tabs"):
            # =================================================================
            # TAB 1: 24 REQUIREMENTS INSPECTOR
            # =================================================================
            with TabPane("🔍 Requirements Inspector (24)", id="tab-inspector"):
                with Horizontal(id="dashboard-body"):
                    with Vertical(id="sidebar"):
                        yield Static("📂 MODULES", classes="panel-heading")
                        mod_items: List[ListItem] = []
                        for m in self._modules:
                            label_markup = (
                                f"[bold]{m['name']}[/]\n"
                                f"[dim]{m['subtitle']}[/]"
                            )
                            mod_items.append(ListItem(Label(label_markup), name=m["id"]))
                        yield ListView(*mod_items, id="admin-modules-list")

                        yield Static(
                            "[bold #d2a8ff]🛠️ ADMIN CONTROLS[/]\n"
                            "• [bold]Enter / Ctrl+E[/]: Run Req\n"
                            "• [bold]F2[/]: Toggle Inspector\n"
                            "• [bold]F3[/]: Go to User View\n"
                            "• [bold]F1[/]: Keyboard Help\n"
                            "• [bold]Ctrl+L[/]: Return to Login",
                            id="sidebar-shortcuts",
                        )

                    with Vertical(id="main-workspace"):
                        with Vertical(id="queries-box"):
                            yield Static(
                                "🔎 MODULE REQUIREMENTS (Press Enter or Ctrl+E to run)",
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

                        with Vertical(id="results-box"):
                            yield Static(
                                "📊 RESULTS",
                                id="admin-results-heading",
                                classes="panel-heading",
                            )
                            yield DataTable(id="admin-results-table")

                        with VerticalScroll(id="inspector-panel"):
                            yield Static(
                                "🛠️ DETAILED TECHNICAL INSPECTOR (Press F2 to toggle)",
                                id="inspector-header",
                            )
                            yield Static("", id="inspector-code")

            # =================================================================
            # TAB 2: INTERACTIVE AD-HOC QUERY CONSOLE
            # =================================================================
            with TabPane("⚡ Interactive Query Console", id="tab-console"):
                with Vertical(id="console-container"):
                    with Horizontal(id="console-toolbar"):
                        yield Label("Database Engine:")
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
                        yield Button("▶ Run Ad-Hoc Query", variant="primary", id="btn-run-adhoc")

                    yield TextArea(
                        DEFAULT_ADHOC_TEMPLATES["MongoDB"],
                        language="json",
                        id="console-editor",
                    )

                    yield Static(
                        "[dim]Select an engine, edit the query, and press 'Run Ad-Hoc Query'.[/]",
                        id="console-status",
                    )

                    with Horizontal(id="console-outputs"):
                        with Vertical(id="console-table-box"):
                            yield Static("📋 Tabular View", classes="panel-heading")
                            yield DataTable(id="console-results-table")
                        with VerticalScroll(id="console-json-box"):
                            yield Static("🧾 JSON Output / Details", classes="panel-heading")
                            yield Static("", id="console-json-output")

            # =================================================================
            # TAB 3: POPULATE CATALOG FROM TMDB (RECURSIVE WITHOUT DUPLICATES)
            # =================================================================
            with TabPane("📦 Populate TMDB Catalog", id="tab-seed"):
                with Vertical(id="seed-container"):
                    yield Static(
                        "[bold #58a6ff]📦 RECURSIVE BULK POPULATION FROM TMDB (`/movie/popular`)[/]\n"
                        "[dim]Downloads N popular movies from TMDB and recursively inserts each movie, "
                        "its directors, and up to 10 main cast members into MongoDB, avoiding duplicates via `tmdb_id`.[/]"
                    )
                    with Horizontal(id="seed-controls-row"):
                        yield Label("Movie count (N):")
                        yield Input(value="25", placeholder="e.g. 50", id="inp-seed-count")
                        yield Checkbox(
                            "Enrich directors and actors with /person/{id} (bio, birth year, nationality)",
                            value=True,
                            id="chk-seed-full-person",
                        )
                        yield Button("🚀 Start Ingestion", variant="success", id="btn-start-seed")

                    yield ProgressBar(total=100, show_eta=True, id="seed-progress-bar")
                    yield Static(
                        "[dim]Ready to start. You can also run `python main.py --seed N` from CLI.[/]",
                        id="seed-summary-status",
                    )
                    yield RichLog(highlight=True, markup=True, id="seed-log")

        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#admin-results-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True

        console_table = self.query_one("#console-results-table", DataTable)
        console_table.cursor_type = "row"
        console_table.zebra_stripes = True

        self._refresh_header()
        self._load_module(0, run_initial=True)

    def on_screen_resume(self) -> None:
        self._refresh_header()

    def _refresh_header(self) -> None:
        session = AuthService().current_session
        self.query_one("#top-bar", Static).update(build_admin_header(session))

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
            f"🔎 {module['name'].upper()}  {format_engine_badge(engine_name)}  "
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
                # Prepares input slots without firing network/DB queries while navigating
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
                f"🛠️ SELECTED: {qspec.title}  │  {format_engine_badge(qspec.database)}  │  "
                f"Expected columns: {', '.join(qspec.expected_columns)}  │  "
                "[bold #3fb950]Press Enter or Ctrl+E to run[/]"
            )

    @on(Button.Pressed, "#btn-admin-execute")
    def on_execute_pressed(self) -> None:
        self._run_current_query()

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
        else:
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
        self.query_one("#admin-results-heading", Static).update(
            f"⏳ Running {self._active_query.title}..."
        )
        self._execute_req_worker(self._active_query.id, params)

    @work(thread=True, exclusive=True, group="admin-req")
    def _execute_req_worker(self, query_id: str, params: Dict[str, str]) -> None:
        worker = get_current_worker()
        result: QueryResult = execute_query(query_id, params)
        if not worker.is_cancelled:
            self.app.call_from_thread(self._render_result, result)

    def _render_result(self, result: QueryResult) -> None:
        res_heading = self.query_one("#admin-results-heading", Static)
        res_heading.update(
            f"📊 {result.title} — {len(result.rows)} rows (total: {result.total_count})  │  "
            f"{format_engine_badge(result.database)}  │  ⏱ {result.execution_ms:.2f} ms  │  "
            f"👤 @{result.active_username}  │  {format_source_badge(result.data_source)}"
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
            f"🛠️ TECHNICAL INSPECTOR [F2]  │  {format_engine_badge(result.database)}  │  "
            f"Source: {format_source_badge(result.data_source)}  │  "
            f"Latency: [bold #3fb950]{result.execution_ms:.2f} ms[/]  │  "
            f"Columns: {', '.join(result.columns)}"
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
    # TAB 2: INTERACTIVE AD-HOC QUERY CONSOLE
    # =========================================================================

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

    @on(Button.Pressed, "#btn-run-adhoc")
    def on_run_adhoc_pressed(self) -> None:
        self._run_adhoc_query()

    def _run_adhoc_query(self) -> None:
        engine = str(self.query_one("#console-engine-select", Select).value)
        query_text = self.query_one("#console-editor", TextArea).text
        status_label = self.query_one("#console-status", Static)
        table = self.query_one("#console-results-table", DataTable)
        json_out = self.query_one("#console-json-output", Static)

        res = execute_raw_query(engine, query_text)
        table.clear(columns=True)

        if not res["ok"]:
            status_label.update(
                f"[bold #f85149]✖ Error in {engine} ({res['execution_ms']:.2f} ms): {res['error']}[/]"
            )
            json_out.update(f"[bold #f85149]{res['error']}[/]")
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
    # TAB 3: RECURSIVE BULK POPULATION FROM TMDB
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
        self.query_one("#seed-summary-status", Static).update(
            f"[bold #58a6ff]⏳ Processing 0 / {n} movies...[/]"
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

        self.query_one("#seed-summary-status", Static).update(
            f"[bold #58a6ff]⏳ Processing {curr} / {total}:[/] {title}"
        )

    def _on_seed_complete(self, report: PopulateReport) -> None:
        self.query_one("#btn-start-seed", Button).disabled = False
        summary = (
            f"[bold #3fb950]✔ POPULATION COMPLETE:[/] Processed: {report.processed}  │  "
            f"New movies: [bold]{report.new_movies}[/]  │  "
            f"Skipped (duplicates): {report.skipped_existing}  │  "
            f"New actors: [bold]{report.new_actors}[/]  │  "
            f"New directors: [bold]{report.new_directors}[/]  │  "
            f"Errors: {report.errors}"
        )
        self.query_one("#seed-summary-status", Static).update(summary)
        self.query_one("#seed-log", RichLog).write(f"\n{summary}")

    def action_open_help(self) -> None:
        self.app.push_screen(HelpScreen())

    def action_switch_to_user_view(self) -> None:
        self.app.switch_screen("home")

    def action_logout(self) -> None:
        AuthService().logout()
        self.app.switch_screen("auth")
