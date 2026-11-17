"""
Dedicated Admin Entity Inspector & CRUD Screen (`AdminEntityScreen`)
(tui/screens/admin_entity.py).

Full-screen drill-down view for AdminScreen when clicking any:
- Director / Actor (`kind="director" | "actor"`): bio, metadata, filmography `MovieCard`s, Edit & Delete.
- User (`kind="user"`): profile metadata, created lists + list movies, watched movies,
  liked movies, and written reviews — all interactive, plus Edit & Delete.
- Review (`kind="review"`): full review content, author & movie jump buttons,
  liked-by `UserCard`s, Edit & Delete.
- Movie (`kind="movie"`): movie metadata, synopsis, Edit & Delete (for drill-down from
  filmography, user watched/lists, or reviews).
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from bson import ObjectId
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.events import Click, Resize
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Button, Label, ListItem, ListView, Static
from textual.worker import get_current_worker

from databases.mongodb import MongoConnection
from services.AuthService import AuthService
from services.CatalogService import MovieSummary
from services.TMDBService import TMDBService
from tui.modals import AdminEditModal, ConfirmModal
from tui.toast import show_error_toast, show_success_toast
from tui.widgets.movie_card import MovieCard
from tui.widgets.person_card import populate_carousel_bar
from tui.widgets.poster import PosterImage
from tui.widgets.user_card import UserCard


class ClickableReviewCard(Vertical, can_focus=True):
    """Clickable review card used in Admin views."""

    BINDINGS = [
        Binding("enter", "activate", "Inspect Review", show=False),
        Binding("space", "activate", "Inspect Review", show=False),
    ]

    class Selected(Message):
        def __init__(self, card: "ClickableReviewCard", review_id: str) -> None:
            super().__init__()
            self.card = card
            self.review_id = review_id

        @property
        def control(self) -> "ClickableReviewCard":
            return self.card

    def __init__(self, review_id: str, *children, classes: str = "review-item-card") -> None:
        super().__init__(*children, classes=classes)
        self.review_id = review_id

    def on_click(self, event: Click) -> None:
        event.stop()
        self.post_message(self.Selected(self, self.review_id))

    def action_activate(self) -> None:
        self.post_message(self.Selected(self, self.review_id))


class AdminEntityScreen(Screen[Optional[str]]):
    """Full-screen admin entity detail, relations explorer, and CRUD view."""

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True, priority=True),
    ]

    def __init__(
        self,
        entity_kind: Literal["director", "actor", "user", "review", "movie"],
        identifier: str,
        fallback_name: str = "",
    ) -> None:
        super().__init__()
        self._kind = entity_kind
        self._identifier = identifier
        self._fallback_name = fallback_name
        self._changed_status: Optional[str] = None
        self._doc: Optional[Dict[str, Any]] = None

        # Related collections for interactive carousels
        self._primary_movies: List[MovieSummary] = []
        self._secondary_movies: List[MovieSummary] = []
        self._user_lists: List[Dict[str, Any]] = []
        self._selected_list_movies: List[MovieSummary] = []
        self._reviews: List[Dict[str, Any]] = []
        self._users: List[Dict[str, Any]] = []

        self._primary_offset: int = 0
        self._secondary_offset: int = 0
        self._list_movies_offset: int = 0
        self._rev_offset: int = 0
        self._users_offset: int = 0

    def compose(self) -> ComposeResult:
        with Horizontal(id="top-bar"):
            yield Static("[bold #58a6ff]∅ MOVIEVAULT[/]", id="top-bar-brand")
            yield Static("", id="top-bar-spacer")
            yield Static(
                f"[bold #d2a8ff]Admin Inspector — {self._kind.upper()}[/]",
                id="admin-entity-topbar-tag",
            )

        with VerticalScroll(id="admin-entity-page-scroll", classes="detail-page-scroll"):
            with Horizontal(classes="detail-top-actions"):
                yield Button("◀ Back [Esc]", variant="default", id="btn-ae-back")

            with Vertical(id="admin-entity-hero-col"):
                with Center(id="admin-entity-poster-wrap"):
                    yield PosterImage(
                        poster_url="",
                        title=self._fallback_name or self._identifier,
                        cells_width=18,
                        cells_height=12,
                        size="w185",
                        kind="movie" if self._kind == "movie" else "person",
                        id="ae-poster",
                    )
                yield Static("", id="ae-title-line")
                yield Static("", id="ae-id-line")
                with Horizontal(id="ae-actions-row"):
                    yield Button("Edit", variant="primary", id="btn-ae-edit")
                    yield Button("Delete", variant="error", id="btn-ae-delete")

            with Horizontal(id="ae-jump-row"):
                yield Button("Inspect Movie", variant="default", id="btn-ae-jump-movie")
                yield Button("Inspect Author", variant="default", id="btn-ae-jump-user")

            yield Static("Loading...", id="ae-body")

            # User Lists section (User only)
            with Vertical(id="ae-lists-section"):
                yield Static("CREATED LISTS", id="ae-lists-heading", classes="panel-heading")
                with Horizontal(id="ae-lists-split"):
                    yield ListView(id="ae-lists-listview")
                    with Vertical(id="ae-list-movies-col"):
                        yield Static("", id="ae-selected-list-info")
                        with Horizontal(classes="carousel-row"):
                            yield Button("<", id="btn-ae-listm-prev", classes="carousel-nav-btn")
                            yield Horizontal(id="ae-listm-bar", classes="chips-bar")
                            yield Button(">", id="btn-ae-listm-next", classes="carousel-nav-btn")

            # Primary Movies Carousel (Filmography for Person / Watched for User)
            with Vertical(id="ae-primary-movies-section"):
                yield Static("MOVIES", id="ae-primary-movies-heading", classes="panel-heading")
                with Horizontal(classes="carousel-row"):
                    yield Button("<", id="btn-ae-pm-prev", classes="carousel-nav-btn")
                    yield Horizontal(id="ae-pm-bar", classes="chips-bar")
                    yield Button(">", id="btn-ae-pm-next", classes="carousel-nav-btn")

            # Secondary Movies Carousel (Liked Movies for User)
            with Vertical(id="ae-secondary-movies-section"):
                yield Static("LIKED MOVIES", id="ae-secondary-movies-heading", classes="panel-heading")
                with Horizontal(classes="carousel-row"):
                    yield Button("<", id="btn-ae-sm-prev", classes="carousel-nav-btn")
                    yield Horizontal(id="ae-sm-bar", classes="chips-bar")
                    yield Button(">", id="btn-ae-sm-next", classes="carousel-nav-btn")

            # Reviews Carousel (Reviews written by User)
            with Vertical(id="ae-reviews-section"):
                yield Static("REVIEWS", id="ae-reviews-heading", classes="panel-heading")
                with Horizontal(classes="carousel-row"):
                    yield Button("<", id="btn-ae-rev-prev", classes="carousel-nav-btn review-carousel-nav-btn")
                    yield Horizontal(id="ae-rev-bar", classes="chips-bar")
                    yield Button(">", id="btn-ae-rev-next", classes="carousel-nav-btn review-carousel-nav-btn")

            # Users Carousel (Liked By for Review)
            with Vertical(id="ae-users-section"):
                yield Static("LIKED BY USERS", id="ae-users-heading", classes="panel-heading")
                with Horizontal(classes="carousel-row"):
                    yield Button("<", id="btn-ae-usr-prev", classes="carousel-nav-btn")
                    yield Horizontal(id="ae-usr-bar", classes="chips-bar")
                    yield Button(">", id="btn-ae-usr-next", classes="carousel-nav-btn")

    def on_mount(self) -> None:
        self._load_entity_worker()

    def _get_db(self):
        mongo = MongoConnection()
        if mongo.initialized and mongo.database is not None:
            return mongo.database
        return None

    def _doc_to_summary(self, m: Dict[str, Any]) -> MovieSummary:
        return MovieSummary(
            movie_id=str(m.get("_id") or ""),
            title=str(m.get("title") or "Untitled"),
            release_year=int(m.get("release_year") or 0),
            rating=float(m.get("rating") or 0.0),
            poster_url=str(m.get("poster_url") or ""),
            genres=list(m.get("genres") or []),
            impact_score=float(m.get("impact_score") or 0.0),
        )

    @work(thread=True, exclusive=True, group="admin-entity-load")
    def _load_entity_worker(self) -> None:
        worker = get_current_worker()
        db = self._get_db()
        doc: Optional[Dict[str, Any]] = None
        primary_movies: List[MovieSummary] = []
        secondary_movies: List[MovieSummary] = []
        user_lists: List[Dict[str, Any]] = []
        reviews: List[Dict[str, Any]] = []
        users: List[Dict[str, Any]] = []

        if db is not None:
            try:
                if self._kind in ("director", "actor"):
                    col = "directors" if self._kind == "director" else "actors"
                    if ObjectId.is_valid(self._identifier):
                        doc = db[col].find_one({"_id": ObjectId(self._identifier)})
                    if doc is None and (self._fallback_name or self._identifier):
                        doc = db[col].find_one({"name": self._fallback_name or self._identifier})

                elif self._kind == "user":
                    doc = db["users"].find_one({"username": self._identifier})
                    if doc is not None:
                        uname = str(doc.get("username") or "")
                        # Watched movies
                        watched_titles = [
                            str(w.get("title") or "")
                            for w in (doc.get("watched_movies") or [])
                            if w.get("title")
                        ]
                        watched_oids = [
                            w.get("id") for w in (doc.get("watched_movies") or []) if w.get("id")
                        ]
                        if watched_oids or watched_titles:
                            for m in db["movies"].find(
                                {"$or": [{"_id": {"$in": watched_oids}}, {"title": {"$in": watched_titles}}]}
                            ).limit(30):
                                primary_movies.append(self._doc_to_summary(m))

                        # Liked movies
                        for m in db["movies"].find({"liked_by": uname}).sort("impact_score", -1).limit(30):
                            secondary_movies.append(self._doc_to_summary(m))

                        # Created lists + resolve movie summaries
                        raw_lists = list(doc.get("lists") or [])
                        all_list_oids = []
                        all_list_titles = []
                        for lst in raw_lists:
                            for item in (lst.get("movies") or []):
                                if isinstance(item, dict):
                                    if item.get("id"):
                                        all_list_oids.append(item["id"])
                                    if item.get("title"):
                                        all_list_titles.append(item["title"])
                                elif item:
                                    all_list_titles.append(str(item))
                        movie_map_id: Dict[str, MovieSummary] = {}
                        movie_map_title: Dict[str, MovieSummary] = {}
                        if all_list_oids or all_list_titles:
                            for m in db["movies"].find(
                                {"$or": [{"_id": {"$in": all_list_oids}}, {"title": {"$in": all_list_titles}}]}
                            ):
                                ms = self._doc_to_summary(m)
                                movie_map_id[ms.movie_id] = ms
                                movie_map_title[ms.title.lower()] = ms

                        for lst in raw_lists:
                            resolved_movies: List[MovieSummary] = []
                            for item in (lst.get("movies") or []):
                                if isinstance(item, dict):
                                    mid = str(item.get("id") or "")
                                    mtitle = str(item.get("title") or "")
                                    ms = movie_map_id.get(mid) or movie_map_title.get(mtitle.lower())
                                    if ms:
                                        resolved_movies.append(ms)
                                elif item:
                                    ms = movie_map_title.get(str(item).lower())
                                    if ms:
                                        resolved_movies.append(ms)
                            user_lists.append(
                                {
                                    "name": str(lst.get("name") or "Untitled List"),
                                    "description": str(lst.get("description") or "").strip(),
                                    "movies": resolved_movies,
                                }
                            )

                        # Written reviews
                        reviews = list(
                            db["reviews"].find({"owner.username": uname}).sort("created_at", -1).limit(30)
                        )

                elif self._kind == "review":
                    if ObjectId.is_valid(self._identifier):
                        doc = db["reviews"].find_one({"_id": ObjectId(self._identifier)})
                    if doc is not None:
                        liked_unames = [str(u) for u in (doc.get("liked_by") or []) if u]
                        if liked_unames:
                            for udoc in db["users"].find({"username": {"$in": liked_unames}}):
                                un = str(udoc.get("username") or "")
                                users.append(
                                    {
                                        "username": un,
                                        "avatar_url": str(udoc.get("avatar_url") or ""),
                                        "reviews_count": db["reviews"].count_documents({"owner.username": un}),
                                        "lists_count": len(udoc.get("lists") or []),
                                        "followers_count": int(udoc.get("followers_count") or 0),
                                    }
                                )

                elif self._kind == "movie":
                    if ObjectId.is_valid(self._identifier):
                        doc = db["movies"].find_one({"_id": ObjectId(self._identifier)})
                    if doc is None and (self._fallback_name or self._identifier):
                        doc = db["movies"].find_one({"title": self._fallback_name or self._identifier})
                    if doc is not None:
                        reviews = list(
                            db["reviews"]
                            .find({"$or": [{"movie.id": doc["_id"]}, {"movie.title": doc.get("title", "")}]})
                            .sort("created_at", -1)
                            .limit(25)
                        )
            except Exception:
                pass

        if not worker.is_cancelled:
            self.app.call_from_thread(
                self._render_entity,
                doc,
                primary_movies,
                secondary_movies,
                user_lists,
                reviews,
                users,
            )

    def _render_entity(
        self,
        doc: Optional[Dict[str, Any]],
        primary_movies: List[MovieSummary],
        secondary_movies: List[MovieSummary],
        user_lists: List[Dict[str, Any]],
        reviews: List[Dict[str, Any]],
        users: List[Dict[str, Any]],
    ) -> None:
        self._doc = doc
        self._primary_movies = primary_movies
        self._secondary_movies = secondary_movies
        self._user_lists = user_lists
        self._reviews = reviews
        self._users = users
        self._primary_offset = 0
        self._secondary_offset = 0
        self._list_movies_offset = 0
        self._rev_offset = 0
        self._users_offset = 0

        poster = self.query_one("#ae-poster", PosterImage)
        poster_wrap = self.query_one("#admin-entity-poster-wrap", Center)
        title_line = self.query_one("#ae-title-line", Static)
        id_line = self.query_one("#ae-id-line", Static)
        body = self.query_one("#ae-body", Static)
        jump_row = self.query_one("#ae-jump-row", Horizontal)

        lists_sec = self.query_one("#ae-lists-section", Vertical)
        pm_sec = self.query_one("#ae-primary-movies-section", Vertical)
        sm_sec = self.query_one("#ae-secondary-movies-section", Vertical)
        rev_sec = self.query_one("#ae-reviews-section", Vertical)
        usr_sec = self.query_one("#ae-users-section", Vertical)

        for sec in (lists_sec, pm_sec, sm_sec, rev_sec, usr_sec):
            sec.display = False
        jump_row.display = False

        if doc is None:
            poster_wrap.display = False
            title_line.update("[bold #f85149]Record not found[/]")
            id_line.update("")
            body.update(f"[bold #f85149]{self._kind.capitalize()} not found in MongoDB.[/]")
            self.query_one("#btn-ae-edit", Button).disabled = True
            self.query_one("#btn-ae-delete", Button).disabled = True
            return

        self.query_one("#btn-ae-edit", Button).disabled = False
        self.query_one("#btn-ae-delete", Button).disabled = False

        if self._kind in ("director", "actor"):
            poster_wrap.display = True
            purl = str(doc.get("poster_url") or doc.get("profile_url") or "")
            if not purl and doc.get("tmdb_profile_path"):
                purl = TMDBService().build_image_url(str(doc["tmdb_profile_path"]), "w185")
            name = str(doc.get("name") or "Unknown")
            poster.set_poster(purl, name)
            title_line.update(f"[bold #58a6ff]{name}[/] [dim]({self._kind.capitalize()})[/]")
            id_line.update(f"[dim]MongoDB _id: {doc.get('_id')}[/]")
            body.update(
                "[bold #79c0ff]Biography & Metadata[/]\n\n"
                f"  • [bold]Birth Year:[/] {doc.get('birth_year') or '—'}\n\n"
                f"  • [bold]Nationality:[/] {doc.get('nationality') or '—'}\n\n"
                f"  • [bold]Active:[/] {'Yes' if doc.get('is_active', True) else 'No'}\n\n"
                f"  • [bold]Bio:[/] {str(doc.get('bio') or 'No biography available.').strip()}"
            )

        elif self._kind == "user":
            poster_wrap.display = True
            uname = str(doc.get("username") or "")
            poster.set_poster(str(doc.get("avatar_url") or ""), uname)
            title_line.update(f"[bold #58a6ff]@{uname}[/] [dim]({doc.get('role', 'user')})[/]")
            id_line.update(f"[dim]MongoDB _id: {doc.get('_id')}  │  Email: {doc.get('email') or '—'}[/]")
            created = doc.get("created_at")
            created_str = created.strftime("%Y-%m-%d %H:%M UTC") if isinstance(created, datetime) else "—"
            body.update(
                "[bold #79c0ff]Account Summary[/]\n\n"
                f"  • [bold]Role:[/] {doc.get('role') or 'user'}   │   [bold]Joined:[/] {created_str}\n\n"
                f"  • [bold]Lists:[/] {len(self._user_lists)}   │   "
                f"[bold]Watched:[/] {len(self._primary_movies)}   │   "
                f"[bold]Liked:[/] {len(self._secondary_movies)}   │   "
                f"[bold]Reviews:[/] {len(self._reviews)}\n\n"
                f"  • [bold]Bio:[/] {str(doc.get('bio') or 'No bio.').strip()}"
            )
            lists_sec.display = True
            pm_sec.display = True
            sm_sec.display = True
            rev_sec.display = True
            self.query_one("#ae-lists-heading", Static).update(f"CREATED LISTS ({len(self._user_lists)})")
            self.query_one("#ae-primary-movies-heading", Static).update(
                f"WATCHED MOVIES ({len(self._primary_movies)})"
            )
            self.query_one("#ae-secondary-movies-heading", Static).update(
                f"LIKED MOVIES ({len(self._secondary_movies)})"
            )
            self.query_one("#ae-reviews-heading", Static).update(f"REVIEWS WRITTEN ({len(self._reviews)})")

            lv = self.query_one("#ae-lists-listview", ListView)
            lv.clear()
            for lst in self._user_lists:
                lv.append(ListItem(Label(f"[bold]{lst['name']}[/] [dim]({len(lst['movies'])})[/]")))
            if self._user_lists:
                lv.index = 0
                self._select_user_list(0)
            else:
                self._selected_list_movies = []
                self.query_one("#ae-selected-list-info", Static).update("[dim]User has no lists.[/]")

        elif self._kind == "review":
            poster_wrap.display = False
            owner = str((doc.get("owner") or {}).get("username") or "unknown")
            mtitle = str((doc.get("movie") or {}).get("title") or "Unknown")
            created = doc.get("created_at")
            created_str = created.strftime("%Y-%m-%d %H:%M UTC") if isinstance(created, datetime) else "—"
            title_line.update(f"[bold #58a6ff]Review on {mtitle}[/] by [bold #79c0ff]@{owner}[/]")
            id_line.update(f"[dim]MongoDB _id: {doc.get('_id')}  │  Created: {created_str}[/]")
            jump_row.display = True
            body.update(
                "[bold #79c0ff]Review Details[/]\n\n"
                f"  • [bold]Rating:[/] ★ {doc.get('rating', '—')}   │   "
                f"[bold]Likes:[/] ♥ {int(doc.get('likes') or 0)}\n\n"
                f"  • [bold]Content:[/]\n    {str(doc.get('content') or '').strip()}"
            )
            usr_sec.display = True
            self.query_one("#ae-users-heading", Static).update(f"LIKED BY ({len(self._users)})")

        elif self._kind == "movie":
            poster_wrap.display = True
            mtitle = str(doc.get("title") or "Untitled")
            poster.set_poster(str(doc.get("poster_url") or ""), mtitle)
            title_line.update(f"[bold #58a6ff]{mtitle}[/] [dim]({doc.get('release_year') or '—'})[/]")
            id_line.update(f"[dim]MongoDB _id: {doc.get('_id')}  │  TMDB ID: {doc.get('tmdb_id') or '—'}[/]")
            added_dt = doc.get("added_date")
            added_str = (
                added_dt.strftime("%Y-%m-%d %H:%M UTC")
                if isinstance(added_dt, datetime)
                else doc["_id"].generation_time.strftime("%Y-%m-%d %H:%M UTC")
            )
            body.update(
                "[bold #79c0ff]Synopsis[/]\n\n"
                f"  {str(doc.get('synopsis') or 'No synopsis.').strip()}\n\n"
                "[bold #79c0ff]Metadata[/]\n\n"
                f"  • [bold]Added to DB:[/] {added_str}\n\n"
                f"  • [bold]Rating:[/] ★ {float(doc.get('rating') or 0):.2f}   │   "
                f"[bold]Impact:[/] {float(doc.get('impact_score') or 0):.4f}\n\n"
                f"  • [bold]Genres:[/] {', '.join(doc.get('genres') or []) or '—'}"
            )
            rev_sec.display = True
            self.query_one("#ae-reviews-heading", Static).update(f"REVIEWS ({len(self._reviews)})")

        self._render_carousels()

    def _select_user_list(self, idx: int) -> None:
        if 0 <= idx < len(self._user_lists):
            lst = self._user_lists[idx]
            desc = lst["description"] or "[dim]No description[/]"
            self.query_one("#ae-selected-list-info", Static).update(
                f"[bold #d2a8ff]{lst['name']}[/] — {desc}"
            )
            self._selected_list_movies = lst["movies"]
            self._list_movies_offset = 0
            self._render_carousels()

    @on(ListView.Highlighted, "#ae-lists-listview")
    def _on_user_list_highlighted(self, _event: ListView.Highlighted) -> None:
        lv = self.query_one("#ae-lists-listview", ListView)
        if lv.index is not None:
            self._select_user_list(lv.index)

    @on(ListView.Selected, "#ae-lists-listview")
    def _on_user_list_selected(self, _event: ListView.Selected) -> None:
        lv = self.query_one("#ae-lists-listview", ListView)
        if lv.index is not None:
            self._select_user_list(lv.index)

    def _cards_per_row(self, card_w: int = 23) -> int:
        try:
            w = self.size.width or self.app.size.width
        except Exception:
            w = 0
        if not w:
            return 3
        return max(1, max(card_w, w - 22) // card_w)

    def _render_movie_carousel(
        self,
        items: List[MovieSummary],
        offset: int,
        bar_id: str,
        prev_id: str,
        next_id: str,
        empty_msg: str,
    ) -> None:
        per_row = self._cards_per_row(23)
        bar = self.query_one(bar_id, Horizontal)
        prev_b = self.query_one(prev_id, Button)
        next_b = self.query_one(next_id, Button)
        if not items:
            bar.remove_children()
            bar.mount(Static(f"[dim]{empty_msg}[/]", classes="empty-inline-msg"))
            prev_b.display = False
            next_b.display = False
            return
        needs_nav = len(items) > per_row
        prev_b.display = needs_nav
        next_b.display = needs_nav
        prev_b.disabled = offset <= 0
        next_b.disabled = offset + per_row >= len(items)
        cards = [MovieCard(m) for m in items[offset : offset + per_row]]
        populate_carousel_bar(bar, cards, per_row)

    def _render_carousels(self) -> None:
        if self.query_one("#ae-lists-section", Vertical).display:
            self._render_movie_carousel(
                self._selected_list_movies,
                self._list_movies_offset,
                "#ae-listm-bar",
                "#btn-ae-listm-prev",
                "#btn-ae-listm-next",
                "This list has no movies.",
            )
        if self.query_one("#ae-primary-movies-section", Vertical).display:
            self._render_movie_carousel(
                self._primary_movies,
                self._primary_offset,
                "#ae-pm-bar",
                "#btn-ae-pm-prev",
                "#btn-ae-pm-next",
                "No movies found.",
            )
        if self.query_one("#ae-secondary-movies-section", Vertical).display:
            self._render_movie_carousel(
                self._secondary_movies,
                self._secondary_offset,
                "#ae-sm-bar",
                "#btn-ae-sm-prev",
                "#btn-ae-sm-next",
                "No liked movies.",
            )
        if self.query_one("#ae-reviews-section", Vertical).display:
            rev_per_row = self._cards_per_row(44)
            bar = self.query_one("#ae-rev-bar", Horizontal)
            prev_b = self.query_one("#btn-ae-rev-prev", Button)
            next_b = self.query_one("#btn-ae-rev-next", Button)
            if not self._reviews:
                bar.remove_children()
                bar.mount(Static("[dim]No reviews found.[/]", classes="empty-inline-msg"))
                prev_b.display = False
                next_b.display = False
            else:
                needs_nav = len(self._reviews) > rev_per_row
                prev_b.display = needs_nav
                next_b.display = needs_nav
                prev_b.disabled = self._rev_offset <= 0
                next_b.disabled = self._rev_offset + rev_per_row >= len(self._reviews)
                cards = []
                for rev in self._reviews[self._rev_offset : self._rev_offset + rev_per_row]:
                    mtitle = str((rev.get("movie") or {}).get("title") or "Movie")
                    owner = str((rev.get("owner") or {}).get("username") or "user")
                    head_lbl = f"{mtitle}" if self._kind == "user" else f"@{owner}"
                    rating = float(rev.get("rating") or 0.0)
                    likes = int(rev.get("likes") or 0)
                    content = str(rev.get("content") or "").strip() or "[dim](No text)[/]"
                    if len(content) > 140:
                        content = f"{content[:137]}..."
                    cards.append(
                        ClickableReviewCard(
                            str(rev.get("_id") or ""),
                            Horizontal(
                                Static(f"[bold #79c0ff]{head_lbl}[/]", classes="review-movie-title-link"),
                                Static(
                                    f"  [bold #f0883e]★ {rating:.1f}[/]  [bold #3fb950]♥ {likes}[/]",
                                    classes="review-card-meta",
                                ),
                                classes="review-card-header",
                            ),
                            Static(content, classes="review-item-body"),
                            classes="review-item-card admin-clickable-card",
                        )
                    )
                populate_carousel_bar(bar, cards, rev_per_row, empty_slot_class="carousel-review-empty-slot")
        if self.query_one("#ae-users-section", Vertical).display:
            usr_per_row = self._cards_per_row(23)
            bar = self.query_one("#ae-usr-bar", Horizontal)
            prev_b = self.query_one("#btn-ae-usr-prev", Button)
            next_b = self.query_one("#btn-ae-usr-next", Button)
            if not self._users:
                bar.remove_children()
                bar.mount(Static("[dim]No users yet.[/]", classes="empty-inline-msg"))
                prev_b.display = False
                next_b.display = False
            else:
                needs_nav = len(self._users) > usr_per_row
                prev_b.display = needs_nav
                next_b.display = needs_nav
                prev_b.disabled = self._users_offset <= 0
                next_b.disabled = self._users_offset + usr_per_row >= len(self._users)
                cards = [
                    UserCard(
                        username=u["username"],
                        avatar_url=u["avatar_url"],
                        reviews_count=u["reviews_count"],
                        lists_count=u["lists_count"],
                        followers_count=u["followers_count"],
                    )
                    for u in self._users[self._users_offset : self._users_offset + usr_per_row]
                ]
                populate_carousel_bar(bar, cards, usr_per_row)

    @on(Button.Pressed, "#btn-ae-listm-prev")
    def _on_listm_prev(self) -> None:
        if self._list_movies_offset > 0:
            self._list_movies_offset -= 1
            self._render_carousels()

    @on(Button.Pressed, "#btn-ae-listm-next")
    def _on_listm_next(self) -> None:
        if self._list_movies_offset + self._cards_per_row(23) < len(self._selected_list_movies):
            self._list_movies_offset += 1
            self._render_carousels()

    @on(Button.Pressed, "#btn-ae-pm-prev")
    def _on_pm_prev(self) -> None:
        if self._primary_offset > 0:
            self._primary_offset -= 1
            self._render_carousels()

    @on(Button.Pressed, "#btn-ae-pm-next")
    def _on_pm_next(self) -> None:
        if self._primary_offset + self._cards_per_row(23) < len(self._primary_movies):
            self._primary_offset += 1
            self._render_carousels()

    @on(Button.Pressed, "#btn-ae-sm-prev")
    def _on_sm_prev(self) -> None:
        if self._secondary_offset > 0:
            self._secondary_offset -= 1
            self._render_carousels()

    @on(Button.Pressed, "#btn-ae-sm-next")
    def _on_sm_next(self) -> None:
        if self._secondary_offset + self._cards_per_row(23) < len(self._secondary_movies):
            self._secondary_offset += 1
            self._render_carousels()

    @on(Button.Pressed, "#btn-ae-rev-prev")
    def _on_rev_prev(self) -> None:
        if self._rev_offset > 0:
            self._rev_offset -= 1
            self._render_carousels()

    @on(Button.Pressed, "#btn-ae-rev-next")
    def _on_rev_next(self) -> None:
        if self._rev_offset + self._cards_per_row(44) < len(self._reviews):
            self._rev_offset += 1
            self._render_carousels()

    @on(Button.Pressed, "#btn-ae-usr-prev")
    def _on_usr_prev(self) -> None:
        if self._users_offset > 0:
            self._users_offset -= 1
            self._render_carousels()

    @on(Button.Pressed, "#btn-ae-usr-next")
    def _on_usr_next(self) -> None:
        if self._users_offset + self._cards_per_row(23) < len(self._users):
            self._users_offset += 1
            self._render_carousels()

    def on_resize(self, _event: Resize) -> None:
        if self._doc is not None:
            self._render_carousels()

    # Drill-down navigation on any nested card
    def _open_child_entity(
        self,
        kind: Literal["director", "actor", "user", "review", "movie"],
        identifier: str,
        fallback_name: str = "",
    ) -> None:
        def _after(status: Optional[str]) -> None:
            if status in ("updated", "deleted"):
                self._changed_status = "updated"
                self._load_entity_worker()

        self.app.push_screen(AdminEntityScreen(kind, identifier, fallback_name), _after)

    @on(MovieCard.Selected)
    def _on_movie_selected(self, event: MovieCard.Selected) -> None:
        self._open_child_entity("movie", event.movie_id, event.title)

    @on(UserCard.Selected)
    def _on_user_selected(self, event: UserCard.Selected) -> None:
        self._open_child_entity("user", event.username)

    @on(ClickableReviewCard.Selected)
    def _on_review_selected(self, event: ClickableReviewCard.Selected) -> None:
        self._open_child_entity("review", event.review_id)

    @on(Button.Pressed, "#btn-ae-jump-movie")
    def _on_jump_movie(self) -> None:
        if self._doc:
            m = self._doc.get("movie") or {}
            self._open_child_entity("movie", str(m.get("id") or ""), str(m.get("title") or ""))

    @on(Button.Pressed, "#btn-ae-jump-user")
    def _on_jump_user(self) -> None:
        if self._doc:
            owner = str((self._doc.get("owner") or {}).get("username") or "")
            if owner:
                self._open_child_entity("user", owner)

    # Edit & Delete CRUD
    @on(Button.Pressed, "#btn-ae-edit")
    def _on_edit(self) -> None:
        if self._doc is None:
            return
        doc = self._doc
        if self._kind in ("director", "actor"):
            fields = [
                ("name", "Name", str(doc.get("name") or ""), False),
                ("birth_year", "Birth Year", str(doc.get("birth_year") or ""), False),
                ("nationality", "Nationality", str(doc.get("nationality") or ""), False),
                ("is_active", "Is Active (true/false)", "true" if doc.get("is_active", True) else "false", False),
                ("bio", "Biography", str(doc.get("bio") or ""), True),
            ]
        elif self._kind == "user":
            fields = [
                ("username", "Username", str(doc.get("username") or ""), False),
                ("email", "Email", str(doc.get("email") or ""), False),
                ("role", "Role (user / admin)", str(doc.get("role") or "user"), False),
                ("bio", "Bio", str(doc.get("bio") or ""), True),
            ]
        elif self._kind == "review":
            fields = [
                ("rating", "Rating (0.5 - 5.0)", str(doc.get("rating") or "4.0"), False),
                ("content", "Review Content", str(doc.get("content") or ""), True),
            ]
        else:
            fields = [
                ("title", "Title", str(doc.get("title") or ""), False),
                ("release_year", "Release Year", str(doc.get("release_year") or ""), False),
                ("runtime", "Runtime (minutes)", str(doc.get("runtime") or "0"), False),
                ("rating", "Rating (0.0 - 5.0)", str(doc.get("rating") or "0.0"), False),
                ("genres", "Genres (comma-separated)", ", ".join(doc.get("genres") or []), False),
                ("synopsis", "Synopsis", str(doc.get("synopsis") or ""), True),
            ]

        def _after_edit(vals: Optional[Dict[str, str]]) -> None:
            if vals:
                self._apply_edit(vals)

        self.app.push_screen(AdminEditModal(f"Edit {self._kind.capitalize()}", fields), _after_edit)

    def _apply_edit(self, vals: Dict[str, str]) -> None:
        db = self._get_db()
        if db is None or self._doc is None:
            return
        try:
            if self._kind in ("director", "actor"):
                col = "directors" if self._kind == "director" else "actors"
                old_name = str(self._doc.get("name") or "")
                new_name = vals["name"].strip() or old_name
                raw_year = vals["birth_year"].strip()
                birth_year = int(raw_year) if raw_year.isdigit() else None
                is_active = vals["is_active"].strip().lower() in ("true", "1", "yes", "si")
                db[col].update_one(
                    {"_id": self._doc["_id"]},
                    {
                        "$set": {
                            "name": new_name,
                            "birth_year": birth_year,
                            "nationality": vals["nationality"].strip() or "Unknown",
                            "is_active": is_active,
                            "bio": vals["bio"].strip(),
                        }
                    },
                )
                if new_name != old_name:
                    arr_field = "directors" if self._kind == "director" else "cast"
                    db["movies"].update_many(
                        {f"{arr_field}.id": self._doc["_id"]},
                        {"$set": {f"{arr_field}.$[elem].name": new_name}},
                        array_filters=[{"elem.id": self._doc["_id"]}],
                    )
            elif self._kind == "user":
                old_uname = str(self._doc.get("username") or "")
                new_uname = vals["username"].strip() or old_uname
                role = vals["role"].strip().lower()
                if role not in ("user", "admin"):
                    role = "user"
                db["users"].update_one(
                    {"_id": self._doc["_id"]},
                    {
                        "$set": {
                            "username": new_uname,
                            "email": vals["email"].strip(),
                            "role": role,
                            "bio": vals["bio"].strip(),
                        }
                    },
                )
                if new_uname != old_uname:
                    db["reviews"].update_many(
                        {"owner.username": old_uname},
                        {"$set": {"owner.username": new_uname}},
                    )
                self._identifier = new_uname
            elif self._kind == "review":
                rating = max(0.5, min(5.0, float(vals["rating"].strip())))
                db["reviews"].update_one(
                    {"_id": self._doc["_id"]},
                    {"$set": {"rating": rating, "content": vals["content"].strip()}},
                )
            else:
                year = int(vals["release_year"].strip() or 0)
                runtime = max(0, int(vals["runtime"].strip() or 0))
                rating = max(0.0, min(5.0, float(vals["rating"].strip() or 0.0)))
                genres = [g.strip() for g in vals["genres"].split(",") if g.strip()]
                title = vals["title"].strip() or str(self._doc.get("title") or "Untitled")
                decade = (year // 10) * 10 if year else int(self._doc.get("decade") or 0)
                db["movies"].update_one(
                    {"_id": self._doc["_id"]},
                    {
                        "$set": {
                            "title": title,
                            "release_year": year,
                            "decade": decade,
                            "runtime": runtime,
                            "rating": rating,
                            "genres": genres,
                            "synopsis": vals["synopsis"].strip(),
                        }
                    },
                )
            self._changed_status = "updated"
            show_success_toast(self, f"{self._kind.capitalize()} updated in MongoDB")
            self._load_entity_worker()
        except Exception as exc:
            show_error_toast(self, f"Error updating {self._kind}: {exc}")

    @on(Button.Pressed, "#btn-ae-delete")
    def _on_delete(self) -> None:
        if self._doc is None:
            return
        if self._kind == "user":
            session = AuthService().current_session
            if session and str(self._doc.get("username") or "") == session.username:
                show_error_toast(self, "Cannot delete the currently logged-in admin user.")
                return

        def _after_confirm(confirmed: bool) -> None:
            if not confirmed or self._doc is None:
                return
            db = self._get_db()
            if db is None:
                return
            try:
                if self._kind in ("director", "actor"):
                    col = "directors" if self._kind == "director" else "actors"
                    arr_field = "directors" if self._kind == "director" else "cast"
                    db[col].delete_one({"_id": self._doc["_id"]})
                    db["movies"].update_many({}, {"$pull": {arr_field: {"id": self._doc["_id"]}}})
                elif self._kind == "user":
                    uname = str(self._doc.get("username") or "")
                    db["users"].delete_one({"_id": self._doc["_id"]})
                    db["reviews"].delete_many({"owner.username": uname})
                    db["movies"].update_many({}, {"$pull": {"liked_by": uname, "watched_by": uname}})
                elif self._kind == "review":
                    db["reviews"].delete_one({"_id": self._doc["_id"]})
                else:
                    oid = self._doc["_id"]
                    db["movies"].delete_one({"_id": oid})
                    db["reviews"].delete_many({"$or": [{"movie.id": oid}, {"movie.title": self._doc.get("title", "")}]})
                show_success_toast(self, f"{self._kind.capitalize()} deleted from MongoDB")
                self.dismiss("deleted")
            except Exception as exc:
                show_error_toast(self, f"Error deleting {self._kind}: {exc}")

        self.app.push_screen(
            ConfirmModal(
                title=f"Delete {self._kind.capitalize()}",
                message=f"Permanently delete this {self._kind} from MongoDB?",
                confirm_label="Delete",
                confirm_variant="error",
            ),
            _after_confirm,
        )

    @on(Button.Pressed, "#btn-ae-back")
    def action_go_back(self) -> None:
        self.dismiss(self._changed_status)
