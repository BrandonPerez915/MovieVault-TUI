"""
Dedicated Query Results Screen (`QueryResultsScreen`)
(tui/screens/user/query_results_screen.py).

Executes Activity (Cassandra) and For You / Recommendations (Dgraph) queries
in the background (`@work(thread=True)`) and displays tabular results in a
dedicated screen, matching `SearchResultsScreen`'s navigation flow.
"""

from typing import Any, Dict, List

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Static
from textual.worker import get_current_worker

from services.QueryService import (
    QueryResult,
    execute_query,
    format_cell_value,
    get_column_label,
)
from tui.screens.user.movie_detail import MovieDetailScreen
from tui.widgets.state_message import StateMessage


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

        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#query-results-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True

        state = self.query_one("#query-state-msg", StateMessage)
        state.show_loading(self._loading_msg)
        self._execute_worker(self._query_id, dict(self._params))

    @work(thread=True, exclusive=True)
    def _execute_worker(self, query_id: str, params: Dict[str, str]) -> None:
        worker = get_current_worker()
        res = execute_query(query_id, params)
        if not worker.is_cancelled:
            self.app.call_from_thread(self._render_result, res)

    def _render_result(self, result: QueryResult) -> None:
        self._rows = list(result.rows)
        state = self.query_one("#query-state-msg", StateMessage)
        banner = self.query_one("#query-summary-banner", Static)
        table = self.query_one("#query-results-table", DataTable)
        table.clear(columns=True)

        for col in result.columns:
            table.add_column(get_column_label(col))

        if not result.rows:
            banner.update("")
            state.show_empty(self._empty_title, self._empty_hint)
            return

        state.clear_state()
        for r in result.rows:
            table.add_row(*[format_cell_value(c, r.get(c)) for c in result.columns])

        has_movie_titles = any(r.get("movie_title") for r in result.rows)
        hint = (
            "  [dim](Press Enter or click a row to view movie details)[/]"
            if has_movie_titles
            else ""
        )
        banner.update(f"[bold #79c0ff]{len(result.rows)} results found[/]{hint}")
        table.focus()

    @on(DataTable.RowSelected, "#query-results-table")
    def _on_row_selected(self, event: DataTable.RowSelected) -> None:
        idx = event.cursor_row
        if 0 <= idx < len(self._rows):
            title = self._rows[idx].get("movie_title")
            if title:
                self.app.push_screen(MovieDetailScreen(str(title)))

    @on(Button.Pressed, "#btn-query-back")
    def _on_back(self) -> None:
        self.action_go_back()

    def action_go_back(self) -> None:
        self.app.pop_screen()
