"""
Dedicated Actor or Director File Screen (`PersonScreen`)
(backend/tui/screens/user/person_screen.py).

Displays:
- Profile photo rendered in terminal (`PosterImage`)
- Complete biographical data (name, birth year, nationality, active status, and biography)
- Film impact analysis (MongoDB Req 7: total movies, impact score,
  decade distribution, genre distribution, and frequent collaborators)
- Interactive filmography (`MovieGrid`), where each movie opens `MovieDetailScreen`.
"""

from typing import Any, Dict, Literal, Optional

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Static
from textual.worker import get_current_worker

from databases.mongodb import MongoConnection
from services.CatalogService import CatalogService, PersonDetail
from services.QueryService import execute_query
from tui.widgets.movie_card import MovieCard
from tui.widgets.movie_grid import MovieGrid
from tui.widgets.poster import PosterImage
from tui.widgets.state_message import StateMessage


class PersonScreen(Screen):
    """Complete file for an actor or director with impact analysis and filmography."""

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True, priority=True),
    ]

    def __init__(
        self,
        person_id_or_name: str,
        kind: Literal["actor", "director"] = "actor",
        display_name: str = "",
    ) -> None:
        super().__init__()
        self._person_key = (person_id_or_name or "").strip()
        self._kind: Literal["actor", "director"] = kind
        self._display_name = (display_name or self._person_key).strip()
        self._person: Optional[PersonDetail] = None

    def compose(self) -> ComposeResult:
        role_label = "ACTOR / ACTRESS" if self._kind == "actor" else "DIRECTOR"
        yield Static(
            f"[bold #58a6ff]🎭 {role_label} FILE[/]  ›  [bold]{self._display_name}[/]",
            id="top-bar",
        )
        with VerticalScroll(classes="detail-page-scroll"):
            with Horizontal(classes="detail-top-actions"):
                yield Button("◀ Back [Esc]", variant="default", id="btn-person-back")

            yield StateMessage(id="person-state-msg")

            with Horizontal(id="person-hero-box"):
                yield PosterImage(
                    poster_url="",
                    title=self._display_name,
                    cells_width=20,
                    cells_height=14,
                    size="w185",
                    kind=self._kind,
                    id="person-photo",
                )
                with Vertical(id="person-meta-box"):
                    yield Static("", id="person-title-banner")
                    yield Static("", id="person-bio-text")
                    yield Static("", id="person-impact-box")

            yield Static(
                "🎬 FILMOGRAPHY IN CATALOG (Press Enter or click a movie)",
                classes="panel-heading",
            )
            yield MovieGrid(page_size=12, id="person-movies-grid", scrollable=False)

        yield Footer()

    def on_mount(self) -> None:
        state = self.query_one("#person-state-msg", StateMessage)
        state.show_loading(f"Loading profile and filmography for {self._display_name}...")
        self._load_person_worker(self._person_key, self._kind, self._display_name)

    @work(thread=True, exclusive=True)
    def _load_person_worker(
        self,
        person_key: str,
        kind: Literal["actor", "director"],
        fallback_name: str,
    ) -> None:
        worker = get_current_worker()
        try:
            mongo = MongoConnection()
            db = mongo.database if mongo.initialized else None
        except Exception:
            db = None
        catalog = CatalogService()

        person = catalog.get_person_detail(db, person_key, kind=kind)
        if person is None and fallback_name and fallback_name != person_key:
            person = catalog.get_person_detail(db, fallback_name, kind=kind)

        impact_row: Optional[Dict[str, Any]] = None
        target_name = person.name if person else fallback_name
        if target_name:
            res = execute_query("mongo_req_7", {"actor_name": target_name})
            if res.rows:
                impact_row = res.rows[0]
            if person is None:
                person = catalog.get_person_detail(db, target_name, kind=kind)

        if not worker.is_cancelled:
            self.app.call_from_thread(self._render_person, person, impact_row)

    def _render_person(
        self,
        person: Optional[PersonDetail],
        impact_row: Optional[Dict[str, Any]],
    ) -> None:
        state = self.query_one("#person-state-msg", StateMessage)
        if person is None and impact_row is None:
            state.show_empty(
                f"Information for '{self._display_name}' was not found.",
                "Verify MongoDB or TMDB connectivity.",
            )
            return

        state.clear_state()
        self._person = person
        name = person.name if person else str(impact_row.get("actor_name", self._display_name))
        birth_str = str(person.birth_year) if (person and person.birth_year) else "N/A"
        nat_str = person.nationality if person else "N/A"
        active_flag = person.is_active if person else bool((impact_row or {}).get("is_active", True))
        active_str = "[bold #3fb950]✔ Active[/]" if active_flag else "[dim]○ Inactive / Retired[/]"

        photo = self.query_one("#person-photo", PosterImage)
        photo.set_poster(person.profile_url if person else "", title=name)

        self.query_one("#person-title-banner", Static).update(
            f"[bold #58a6ff]{name}[/]   {active_str}\n"
            f"[dim]Nationality:[/] [bold]{nat_str}[/]   │   [dim]Birth year:[/] [bold]{birth_str}[/]"
        )

        bio_raw = (person.bio if person else "").strip()
        if not bio_raw:
            bio_raw = "Biography not available at this moment."
        elif len(bio_raw) > 520:
            bio_raw = f"{bio_raw[:520]}..."
        self.query_one("#person-bio-text", Static).update(f"\n[bold #79c0ff]Biography:[/]\n{bio_raw}\n")

        if impact_row:
            self.query_one("#person-impact-box", Static).update(
                "[bold #d2a8ff]📊 FILM IMPACT ANALYSIS (MongoDB Req 7):[/]\n"
                f"  • [bold]Analyzed movies:[/] {impact_row.get('total_movies', 0)}   │   "
                f"[bold]Impact score:[/] [bold #f0883e]{impact_row.get('impact_score', 0.0)}[/]\n"
                f"  • [bold]Decade presence:[/] {impact_row.get('decade_distribution', 'No data')}\n"
                f"  • [bold]Genre distribution:[/] {impact_row.get('genre_distribution', 'No data')}\n"
                f"  • [bold]Frequent collaborators:[/] {impact_row.get('collaborators', 'No data')}"
            )
        else:
            self.query_one("#person-impact-box", Static).update("")

        movies = person.movies if person else []
        grid = self.query_one("#person-movies-grid", MovieGrid)
        grid.set_movies(movies, page=1, total=len(movies), page_size=max(1, len(movies)))

    @on(MovieCard.Selected)
    def _on_movie_selected(self, event: MovieCard.Selected) -> None:
        from tui.screens.user.movie_detail import MovieDetailScreen

        self.app.push_screen(MovieDetailScreen(event.movie_id or event.title))

    @on(Button.Pressed, "#btn-person-back")
    def _on_back(self) -> None:
        self.action_go_back()

    def action_go_back(self) -> None:
        self.app.pop_screen()
