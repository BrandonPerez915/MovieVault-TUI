"""
Letterboxd-style interactive modals for MovieVault (backend/tui/modals.py).
"""

from typing import Any, Dict, List, Optional

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from tui.modals.base import BaseModal
from textual.timer import Timer
from textual.widgets import (
    Button,
    Input,
    Label,
    ListItem,
    ListView,
    Select,
    Static,
)
from textual.worker import get_current_worker

from databases.mongodb import MongoConnection
from services.ActionService import ActionService
from services.AuthService import AuthService
from services.CatalogService import CatalogService, MovieSummary
from services.ProfileService import ProfileService
from tui.toast import show_error_toast, show_info_toast, show_success_toast
from tui.widgets.loading_spinner import LoadingSpinner



class ManageListModal(BaseModal[Optional[str]]):
    """Modal to select a personal list (or open CreateListModal) and add a movie."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(self, movie_title: str = "", poster_url: str = "") -> None:
        super().__init__()
        self._initial_movie = (movie_title or "").strip()
        self._initial_poster = (poster_url or "").strip()

    def compose(self) -> ComposeResult:
        movie_label = self._initial_movie or "Selected Movie"
        with Vertical(id="list-modal-card", classes="modal-card"):
            yield Static(
                "[bold #58a6ff]📋 ADD TO PERSONAL LIST (Ctrl+B)[/]\n"
                f"[dim]Movie:[/] [bold #f0f6fc]{movie_label}[/]\n"
                "[dim]Select one of your lists or create a new one.[/]"
            )
            yield LoadingSpinner("", id="list-modal-feedback", classes="modal-feedback")

            yield Label("Select a list:")
            yield Select(
                [("Loading your lists...", "")],
                value="",
                allow_blank=False,
                id="list-select",
            )

            with Horizontal(classes="modal-buttons"):
                yield Button("Add to List", variant="primary", id="btn-save-list")
                yield Button("＋ Create List", variant="success", id="btn-open-create-list")
                yield Button("Cancel [Esc]", variant="default", id="btn-cancel-list")

    def on_mount(self) -> None:
        self.query_one("#list-modal-feedback", LoadingSpinner).start_spinner(
            "Loading your lists..."
        )
        self._load_user_lists()
        self.query_one("#list-select", Select).focus()

    @work(thread=True, exclusive=True)
    def _load_user_lists(self, preselect_name: str = "") -> None:
        worker = get_current_worker()
        session = AuthService().current_session
        if session is None:
            lists = []
        else:
            lists = ProfileService().get_user_lists(session.username)
        if not worker.is_cancelled:
            self.app.call_from_thread(self._populate_list_select, lists, preselect_name)

    def _populate_list_select(
        self, lists: List[Any], preselect_name: str = ""
    ) -> None:
        feedback = self.query_one("#list-modal-feedback", LoadingSpinner)
        feedback.stop_spinner(hide=False)
        feedback.update("")
        sel = self.query_one("#list-select", Select)
        if not lists:
            sel.set_options([("No lists found — click Create List", "")])
            sel.value = ""
            return

        movie_key = self._initial_movie.lower()
        options = []
        for lst in lists:
            already_in = bool(
                movie_key
                and any(m.title.strip().lower() == movie_key for m in lst.movies)
            )
            badge = " [Already added ✓]" if already_in else ""
            options.append(
                (f"{lst.name} ({lst.movies_count} movies){badge}", lst.name)
            )

        sel.set_options(options)
        target = next(
            (val for _, val in options if val.lower() == preselect_name.lower()),
            options[0][1],
        )
        sel.value = target

    @on(Button.Pressed, "#btn-open-create-list")
    def _on_open_create_list(self) -> None:
        session = AuthService().current_session
        feedback = self.query_one("#list-modal-feedback", Static)
        if session is None:
            msg = "You must be logged in to create lists."
            feedback.update(f"[bold #f85149]✖ {msg}[/]")
            show_error_toast(self, msg)
            return

        modal = CreateListModal()

        def _after_create(msg: Optional[str]) -> None:
            if msg:
                feedback.update("")
                show_success_toast(self, msg)
                self._load_user_lists(preselect_name=modal.created_list_name)

        self.app.push_screen(modal, _after_create)

    @on(Button.Pressed, "#btn-cancel-list")
    def on_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-save-list")
    def on_save(self) -> None:
        session = AuthService().current_session
        feedback = self.query_one("#list-modal-feedback", Static)
        if session is None:
            msg = "You must be logged in to manage lists."
            feedback.update(f"[bold #f85149]✖ {msg}[/]")
            show_error_toast(self, msg)
            return

        if not self._initial_movie:
            msg = "No movie selected to add."
            feedback.update(f"[bold #f85149]✖ {msg}[/]")
            show_error_toast(self, msg)
            return

        list_name = str(self.query_one("#list-select", Select).value or "").strip()
        if not list_name:
            msg = "Please select or create a list first."
            feedback.update(f"[bold #f85149]✖ {msg}[/]")
            show_error_toast(self, msg)
            return

        ok, msg = ActionService().add_movie_to_list(
            user=session,
            list_name=list_name,
            movie_title=self._initial_movie,
            poster_url=self._initial_poster,
        )
        if ok:
            self.dismiss(msg)
        elif "already in list" in msg.lower():
            feedback.update("")
            show_info_toast(self, msg, title="ℹ Already in List")
        else:
            feedback.update(f"[bold #f85149]✖ {msg}[/]")
            show_error_toast(self, msg)

    def action_cancel(self) -> None:
        self.dismiss(None)



class CreateListModal(BaseModal[Optional[str]]):
    """Modal to create a new empty personal movie list."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.created_list_name: str = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="create-list-modal-card", classes="modal-card"):
            yield Static(
                "[bold #58a6ff]📋 CREATE NEW PERSONAL LIST[/]\n"
                "[dim]Organize movies into custom collections (e.g. Watchlist, Sci-Fi Top).[/]"
            )
            yield Static("", id="create-list-feedback", classes="modal-feedback")
            yield Label("List name:")
            yield Input(placeholder="e.g. Weekend Watchlist", id="inp-new-list-name")
            yield Label("Description (Optional):")
            yield Input(
                placeholder="e.g. Favorite mind-bending sci-fi films",
                id="inp-new-list-desc",
            )
            with Horizontal(classes="modal-buttons"):
                yield Button("Create List", variant="success", id="btn-confirm-create-list")
                yield Button("Cancel [Esc]", variant="default", id="btn-cancel-create-list")

    def on_mount(self) -> None:
        self.query_one("#inp-new-list-name", Input).focus()

    @on(Button.Pressed, "#btn-cancel-create-list")
    def _on_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-confirm-create-list")
    def _on_create(self) -> None:
        self._submit()

    @on(Input.Submitted, "#inp-new-list-name")
    @on(Input.Submitted, "#inp-new-list-desc")
    def _on_submit_input(self) -> None:
        self._submit()

    def _submit(self) -> None:
        session = AuthService().current_session
        feedback = self.query_one("#create-list-feedback", Static)
        if session is None:
            msg = "You must be logged in to create lists."
            feedback.update(f"[bold #f85149]✖ {msg}[/]")
            show_error_toast(self, msg)
            return

        name = self.query_one("#inp-new-list-name", Input).value
        desc = self.query_one("#inp-new-list-desc", Input).value
        ok, msg = ActionService().create_list(session, name, description=desc)
        if ok:
            self.created_list_name = name.strip()
            self.dismiss(msg)
        else:
            feedback.update(f"[bold #f85149]✖ {msg}[/]")
            show_error_toast(self, msg)

    def action_cancel(self) -> None:
        self.dismiss(None)



class AddMovieToListModal(BaseModal[Optional[str]]):
    """Modal to search local catalog movies (400ms debounce) and add one to a list."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(self, list_name: str) -> None:
        super().__init__()
        self._list_name = (list_name or "").strip()
        self._debounce_timer: Optional[Timer] = None
        self._movies_by_title: Dict[str, MovieSummary] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="add-movie-list-modal-card", classes="modal-card"):
            yield Static(
                f"[bold #58a6ff]＋ ADD MOVIE TO '{self._list_name}'[/]\n"
                "[dim]Search movies saved in your local database and select one to add.[/]"
            )
            yield LoadingSpinner("", id="add-movie-list-feedback", classes="modal-feedback")
            yield Label("Search movie by title:")
            yield Input(
                placeholder="Type to search local catalog...",
                id="inp-search-local-movie",
            )
            yield Label("Available movies:")
            yield ListView(id="add-movie-results-listview")
            with Horizontal(classes="modal-buttons"):
                yield Button(
                    "＋ Add Selected Movie",
                    variant="primary",
                    id="btn-confirm-add-movie",
                )
                yield Button(
                    "Cancel [Esc]",
                    variant="default",
                    id="btn-cancel-add-movie",
                )

    def on_mount(self) -> None:
        self.query_one("#inp-search-local-movie", Input).focus()
        self._start_local_search("")

    @on(Input.Changed, "#inp-search-local-movie")
    def _on_search_input_changed(self, event: Input.Changed) -> None:
        if self._debounce_timer is not None:
            self._debounce_timer.stop()
        query_val = event.value
        self._debounce_timer = self.set_timer(
            0.4, lambda: self._start_local_search(query_val)
        )

    def _start_local_search(self, query: str) -> None:
        self.query_one("#add-movie-list-feedback", LoadingSpinner).start_spinner(
            "Searching local catalog..."
        )
        self._search_movies_worker(query)

    @work(thread=True, exclusive=True)
    def _search_movies_worker(self, query: str) -> None:
        worker = get_current_worker()
        try:
            mongo = MongoConnection()
            db = mongo.database if mongo.initialized else None
        except Exception:
            db = None
        movies = CatalogService().search_movies_local(db, query, limit=15)
        if not worker.is_cancelled:
            self.app.call_from_thread(self._render_search_results, movies)

    def _render_search_results(self, movies: List[MovieSummary]) -> None:
        feedback = self.query_one("#add-movie-list-feedback", LoadingSpinner)
        feedback.stop_spinner(hide=False)
        lv = self.query_one("#add-movie-results-listview", ListView)
        lv.clear()
        self._movies_by_title.clear()

        if not movies:
            feedback.update("[bold #f0883e]∅ No matching movies in local database.[/]")
            return

        feedback.update(f"[dim]{len(movies)} movie(s) found. Select one to add.[/]")
        for m in movies:
            self._movies_by_title[m.title] = m
            year_str = str(m.release_year) if m.release_year else "—"
            rating_str = f"★ {m.rating:.1f}" if m.rating else "★ —"
            lv.append(
                ListItem(
                    Label(f"{m.title} [dim]({year_str})[/]  [bold #f0883e]{rating_str}[/]"),
                    name=m.title,
                )
            )
        lv.index = 0

    def _add_movie_by_title(self, movie_title: str) -> None:
        session = AuthService().current_session
        feedback = self.query_one("#add-movie-list-feedback", LoadingSpinner)
        if session is None:
            msg = "You must be logged in to manage lists."
            feedback.update(f"[bold #f85149]✖ {msg}[/]")
            show_error_toast(self, msg)
            return

        movie = self._movies_by_title.get(movie_title)
        poster_url = movie.poster_url if movie else ""
        ok, msg = ActionService().add_movie_to_list(
            user=session,
            list_name=self._list_name,
            movie_title=movie_title,
            poster_url=poster_url,
        )
        if ok:
            self.dismiss(msg)
        elif "already in list" in msg.lower():
            feedback.update(f"[bold #58a6ff]ℹ {msg}[/]")
            show_info_toast(self, msg)
        else:
            feedback.update(f"[bold #f85149]✖ {msg}[/]")
            show_error_toast(self, msg)

    @on(ListView.Selected, "#add-movie-results-listview")
    def _on_list_item_selected(self, event: ListView.Selected) -> None:
        if event.item.name:
            self._add_movie_by_title(str(event.item.name))

    @on(Button.Pressed, "#btn-confirm-add-movie")
    def _on_confirm_add(self) -> None:
        lv = self.query_one("#add-movie-results-listview", ListView)
        item = lv.highlighted_child
        if item is not None and item.name:
            self._add_movie_by_title(str(item.name))
            return
        msg = "Select a movie from the list first."
        self.query_one("#add-movie-list-feedback", LoadingSpinner).update(
            f"[bold #f85149]✖ {msg}[/]"
        )
        show_error_toast(self, msg)

    @on(Button.Pressed, "#btn-cancel-add-movie")
    def _on_cancel(self) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

