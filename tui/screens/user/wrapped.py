"""
Dedicated User Wrapped Screen (`WrappedScreen`)
(tui/screens/user/wrapped_screen.py).

Displays the user's cinematic Wrapped summary in a full scrollable screen:
- PyFiglet header with the user's @username
- User summary metrics (reviews, ratings, avg likes, impact score)
- Horizontal bar chart of Favorite Genres with metric calculation explanation
- Interactive `PersonCard`s for Favorite Actors and Favorite Directors
"""

from typing import Any, Dict, List

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Static
from textual.worker import get_current_worker

from services.QueryService import execute_query
from tui.screens.user.person import PersonScreen
from tui.widgets.figlet_header import FigletHeader
from tui.widgets.person_card import PersonCard, populate_carousel_bar
from tui.widgets.state_message import StateMessage


_BAR_COLORS = ("#58a6ff", "#3fb950", "#d2a8ff", "#f0883e", "#79c0ff", "#ff7b72")


def _build_genre_bar_chart(
    breakdown: List[Dict[str, Any]],
    total_reviews: int,
) -> str:
    """Renders a Rich-formatted horizontal bar chart for genre frequencies."""
    if not breakdown:
        return "[dim]No genre data available yet. Write reviews to see your genre breakdown.[/]"

    max_count = max(int(item.get("count") or 0) for item in breakdown) or 1
    total_mentions = sum(int(item.get("count") or 0) for item in breakdown) or 1
    bar_width = 32
    lines: List[str] = []

    for idx, item in enumerate(breakdown):
        name = str(item.get("name") or "Unknown")[:16]
        count = int(item.get("count") or 0)
        filled = max(1, round((count / max_count) * bar_width)) if count > 0 else 0
        empty = max(0, bar_width - filled)
        pct = round((count / total_mentions) * 100)
        color = _BAR_COLORS[idx % len(_BAR_COLORS)]
        bar_str = f"[{color}]{'█' * filled}[/][#30363d]{'░' * empty}[/]"
        lines.append(
            f"  [bold #f0f6fc]{name:<16}[/]  {bar_str}  "
            f"[bold {color}]{count}[/] [dim]({pct}% of {total_reviews} review(s))[/]"
        )

    return "\n".join(lines)


class WrappedScreen(Screen):
    """Full-screen Spotify-Wrapped-style user statistics view."""

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True, priority=True),
    ]

    def __init__(self, username: str) -> None:
        super().__init__()
        self._username = (username or "").strip().lstrip("@")

    def compose(self) -> ComposeResult:
        yield Static(
            f"[bold #d2a8ff]📊 MOVIEVAULT WRAPPED[/]  ›  [bold]{self._username}[/]",
            id="top-bar",
        )
        with VerticalScroll(classes="detail-page-scroll"):
            with Horizontal(classes="detail-top-actions"):
                yield Button("◀ Back [Esc]", variant="default", id="btn-wrapped-back")

            yield FigletHeader(
                self._username,
                font="slant",
                color="#d2a8ff",
                subtitle="MovieVault Wrapped — Your Cinematic Year in Review",
                id="wrapped-figlet-header",
            )

            yield StateMessage(id="wrapped-state-msg")

            with Vertical(id="wrapped-content-box"):
                yield Static("", id="wrapped-summary-card", classes="wrapped-summary-card")

                with Vertical(id="wrapped-genres-section", classes="wrapped-section-card"):
                    yield Static(
                        "[bold #58a6ff]🎬 FAVORITE GENRES[/]",
                        classes="wrapped-section-title",
                    )
                    yield Static("", id="wrapped-genres-explanation", classes="wrapped-explanation")
                    yield Static("", id="wrapped-genres-chart")

                with Vertical(id="wrapped-actors-section", classes="wrapped-section-card"):
                    yield Static(
                        "[bold #79c0ff]🎭 FAVORITE ACTORS[/]",
                        classes="wrapped-section-title",
                    )
                    yield Static(
                        "[dim]Calculated by counting the top 5 billed actors in every movie you reviewed.[/]",
                        classes="wrapped-explanation",
                    )
                    yield Horizontal(id="wrapped-actors-row", classes="wrapped-cards-row")

                with Vertical(id="wrapped-directors-section", classes="wrapped-section-card"):
                    yield Static(
                        "[bold #f0883e]🎥 FAVORITE DIRECTORS[/]",
                        classes="wrapped-section-title",
                    )
                    yield Static(
                        "[dim]Calculated by counting the directors of every movie you reviewed.[/]",
                        classes="wrapped-explanation",
                    )
                    yield Horizontal(id="wrapped-directors-row", classes="wrapped-cards-row")

        yield Footer()

    def on_mount(self) -> None:
        self._load_wrapped()

    def _load_wrapped(self) -> None:
        self.query_one("#wrapped-content-box", Vertical).display = False
        self.query_one("#wrapped-state-msg", StateMessage).show_loading(
            f"Computing Wrapped statistics for @{self._username}..."
        )
        self._run_wrapped_worker()

    @work(thread=True, exclusive=True)
    def _run_wrapped_worker(self) -> None:
        worker = get_current_worker()
        res = execute_query("mongo_req_8", {"username": self._username})
        if not worker.is_cancelled:
            self.app.call_from_thread(self._render_wrapped, res.rows)

    def _render_wrapped(self, rows: List[Dict[str, Any]]) -> None:
        state = self.query_one("#wrapped-state-msg", StateMessage)
        content_box = self.query_one("#wrapped-content-box", Vertical)
        if not rows:
            content_box.display = False
            state.show_empty(
                f"No Wrapped data available yet for @{self._username}.",
                "Publish reviews to generate your cinematic statistics.",
            )
            return

        state.clear_state()
        content_box.display = True
        r = rows[0]

        total_reviews = int(r.get("total_reviews") or 0)
        total_ratings = int(r.get("total_ratings") or 0)
        avg_likes = float(r.get("avg_likes_per_review") or 0.0)
        impact_score = float(r.get("user_impact_score") or 0.0)
        resolved_user = str(r.get("username") or self._username)

        self.query_one("#wrapped-summary-card", Static).update(
            f"[bold #d2a8ff]{resolved_user} — Overview[/]\n\n"
            f"  • [bold #3fb950]Published reviews:[/] {total_reviews}    "
            f"  • [bold #f0883e]Movies rated:[/] {total_ratings}    "
            f"  • [bold #79c0ff]Avg likes / review:[/] {avg_likes}    "
            f"  • [bold #d2a8ff]User Impact Score:[/] {impact_score}"
        )

        # Favorite Genres bar chart + metric explanation
        breakdown = list(r.get("_genre_breakdown") or [])
        if not breakdown:
            raw_genres = str(r.get("top_genres") or "")
            if raw_genres and raw_genres not in ("N/A", "No activity yet"):
                parts = [g.strip() for g in raw_genres.split(",") if g.strip()]
                breakdown = [
                    {"name": g, "count": max(1, len(parts) - idx)}
                    for idx, g in enumerate(parts)
                ]

        self.query_one("#wrapped-genres-explanation", Static).update(
            f"[dim]How this is calculated:[/] Each bar counts how many of your "
            f"[bold]{total_reviews}[/] reviewed movie(s) belong to that genre in MongoDB."
        )
        self.query_one("#wrapped-genres-chart", Static).update(
            _build_genre_bar_chart(breakdown, total_reviews)
        )

        # Favorite Actors cards
        actor_cards_data = list(r.get("_actor_cards") or [])
        if not actor_cards_data:
            raw_actors = str(r.get("top_actors") or "")
            if raw_actors and raw_actors not in ("N/A", "No activity yet"):
                actor_cards_data = [
                    {"id": a.strip(), "name": a.strip(), "poster_url": "", "count": 1}
                    for a in raw_actors.split(",")
                    if a.strip()
                ]
        actors_row = self.query_one("#wrapped-actors-row", Horizontal)
        actors_row.remove_children()
        if actor_cards_data:
            cards = [
                PersonCard(
                    person_id=str(a.get("id") or a["name"]),
                    person_name=str(a["name"]),
                    kind="actor",
                    poster_url=str(a.get("poster_url") or ""),
                    character=f"{a.get('count', 1)} reviewed film(s)",
                )
                for a in actor_cards_data
            ]
            populate_carousel_bar(actors_row, cards, len(cards))
        else:
            actors_row.mount(Static("[dim]No favorite actors recorded yet.[/]"))

        # Favorite Directors cards
        director_cards_data = list(r.get("_director_cards") or [])
        if not director_cards_data:
            raw_dirs = str(r.get("top_directors") or "")
            if raw_dirs and raw_dirs not in ("N/A", "No activity yet"):
                director_cards_data = [
                    {"id": d.strip(), "name": d.strip(), "poster_url": "", "count": 1}
                    for d in raw_dirs.split(",")
                    if d.strip()
                ]
        directors_row = self.query_one("#wrapped-directors-row", Horizontal)
        directors_row.remove_children()
        if director_cards_data:
            cards = [
                PersonCard(
                    person_id=str(d.get("id") or d["name"]),
                    person_name=str(d["name"]),
                    kind="director",
                    poster_url=str(d.get("poster_url") or ""),
                    character=f"{d.get('count', 1)} reviewed film(s)",
                )
                for d in director_cards_data
            ]
            populate_carousel_bar(directors_row, cards, len(cards))
        else:
            directors_row.mount(Static("[dim]No favorite directors recorded yet.[/]"))

    @on(PersonCard.Selected)
    def _on_person_selected(self, event: PersonCard.Selected) -> None:
        self.app.push_screen(
            PersonScreen(
                event.person_id or event.person_name,
                kind=event.kind,
                display_name=event.person_name,
            )
        )

    @on(Button.Pressed, "#btn-wrapped-back")
    def _on_back(self) -> None:
        self.action_go_back()

    def action_go_back(self) -> None:
        self.app.pop_screen()
