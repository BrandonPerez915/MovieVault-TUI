"""
Dedicated Movie Search Results Screen (`SearchResultsScreen`)
(backend/tui/screens/user/search_results_screen.py).

Executes the selected query in the background (`@work(thread=True)`),
displays a paginated card grid (`MovieGrid`) with 10 movies per page,
and gracefully informs the user when the catalog was enriched with new
movies from TMDB.
"""

from typing import Dict

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Static
from textual.worker import get_current_worker

from services.CatalogService import MovieSummary
from services.QueryService import QueryResult, execute_query
from tui.screens.user.movie_detail_screen import MovieDetailScreen
from tui.widgets.movie_card import MovieCard
from tui.widgets.movie_grid import MovieGrid
from tui.widgets.state_message import StateMessage


class SearchResultsScreen(Screen):
    """Displays paginated search results in a poster card grid."""

    BINDINGS = [
        Binding("escape", "go_back", "Back to Search", show=True, priority=True),
    ]

    def __init__(
        self,
        query_id: str,
        params: Dict[str, str],
        breadcrumb: str = "Search results",
    ) -> None:
        super().__init__()
        self._query_id = query_id
        self._params = dict(params)
        self._breadcrumb = breadcrumb
        self._page = max(1, int(self._params.get("page") or "1"))

    def compose(self) -> ComposeResult:
        yield Static(
            f"[bold #58a6ff]🔍 SEARCH MOVIES[/]  ›  [bold]{self._breadcrumb}[/]",
            id="top-bar",
        )
        with Vertical(classes="detail-page-container"):
            with Horizontal(classes="detail-top-actions"):
                yield Button("◀ New Search [Esc]", variant="default", id="btn-search-back")
                yield Static("", id="search-summary-banner")

            yield StateMessage(id="search-state-msg")
            yield MovieGrid(page_size=10, id="search-results-grid")

        yield Footer()

    def on_mount(self) -> None:
        self._run_page(self._page)

    def _run_page(self, page: int) -> None:
        self._page = max(1, page)
        self._params["page"] = str(self._page)
        state = self.query_one("#search-state-msg", StateMessage)
        state.show_loading(
            "Querying catalog (if no local matches exist, TMDB will be searched)..."
        )
        self._execute_search_worker(self._query_id, dict(self._params))

    @work(thread=True, exclusive=True)
    def _execute_search_worker(self, query_id: str, params: Dict[str, str]) -> None:
        worker = get_current_worker()
        res = execute_query(query_id, params)
        if not worker.is_cancelled:
            self.app.call_from_thread(self._render_search_result, res)

    def _render_search_result(self, result: QueryResult) -> None:
        state = self.query_one("#search-state-msg", StateMessage)
        banner = self.query_one("#search-summary-banner", Static)
        grid = self.query_one("#search-results-grid", MovieGrid)

        summaries = [
            MovieSummary(
                movie_id=str(r.get("_movie_id") or r.get("movie_title") or ""),
                title=str(r.get("movie_title") or "Untitled"),
                release_year=int(r.get("release_year") or 0),
                rating=float(r.get("avg_rating") or r.get("rating") or 0.0),
                poster_url=str(r.get("_poster_url") or ""),
                genres=list(r.get("_genres") or []),
            )
            for r in result.rows
        ]

        grid.set_movies(
            summaries,
            page=self._page,
            total=result.total_count,
            page_size=10,
        )

        if not summaries:
            banner.update("")
            state.show_empty(
                "No movies matched these criteria.",
                "Try broadening the decade range or modifying search keywords.",
            )
            return

        if result.data_source == "tmdb_cached":
            state.show_success(
                "✨ Found new movies on TMDB and saved them to your catalog."
            )
        else:
            state.clear_state()

        banner.update(
            f"[bold #79c0ff]{result.total_count} movies found[/]  "
            "[dim](Press Enter or click a poster to view details)[/]"
        )
        grid.focus_first_card()

    @on(MovieGrid.PageRequested)
    def _on_page_requested(self, event: MovieGrid.PageRequested) -> None:
        self._run_page(event.page)

    @on(MovieCard.Selected)
    def _on_card_selected(self, event: MovieCard.Selected) -> None:
        self.app.push_screen(MovieDetailScreen(event.movie_id or event.title))

    @on(Button.Pressed, "#btn-search-back")
    def _on_back(self) -> None:
        self.action_go_back()

    def action_go_back(self) -> None:
        self.app.pop_screen()
