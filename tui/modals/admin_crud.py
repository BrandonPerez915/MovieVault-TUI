"""
Admin CRUD & Entity Detail Modals (`tui/modals/admin_crud.py`).

Provides:
- `AdminEditModal`: Generic field editor modal for movies, directors, actors, users, and reviews.
- `AdminEntityDetailModal`: Inspects, edits, and deletes a director, actor, user, or review in MongoDB.
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Tuple

from bson import ObjectId
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static, TextArea

from databases.mongodb import MongoConnection
from services.AuthService import AuthService
from tui.modals.common import ConfirmModal
from tui.toast import show_error_toast, show_success_toast
from tui.widgets.poster import PosterImage


class AdminEditModal(ModalScreen[Optional[Dict[str, str]]]):
    """Reusable modal form for editing entity fields in MongoDB."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(
        self,
        title: str,
        fields: List[Tuple[str, str, str, bool]],
    ) -> None:
        """
        `fields`: list of `(field_key, label, initial_value, is_multiline)`.
        """
        super().__init__()
        self._title = title
        self._fields = fields

    def compose(self) -> ComposeResult:
        with Vertical(id="admin-edit-modal-card", classes="modal-card"):
            yield Static(f"[bold #58a6ff]{self._title}[/]", classes="panel-heading")
            with VerticalScroll(id="admin-edit-scroll"):
                for key, label, val, multiline in self._fields:
                    yield Label(label)
                    if multiline:
                        yield TextArea(val, id=f"admin-edit-{key}", classes="admin-edit-textarea")
                    else:
                        yield Input(value=val, id=f"admin-edit-{key}")
            with Horizontal(id="admin-edit-actions", classes="modal-actions"):
                yield Button("Save Changes", variant="success", id="btn-admin-edit-save")
                yield Button("Cancel [Esc]", variant="default", id="btn-admin-edit-cancel")

    @on(Button.Pressed, "#btn-admin-edit-save")
    def _on_save(self) -> None:
        result: Dict[str, str] = {}
        for key, _label, _val, multiline in self._fields:
            if multiline:
                result[key] = self.query_one(f"#admin-edit-{key}", TextArea).text
            else:
                result[key] = self.query_one(f"#admin-edit-{key}", Input).value
        self.dismiss(result)

    @on(Button.Pressed, "#btn-admin-edit-cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)


class AdminEntityDetailModal(ModalScreen[Optional[str]]):
    """Modal showing full DB details + Edit/Delete actions for a Director, Actor, User, or Review."""

    BINDINGS = [
        Binding("escape", "close", "Close", show=True),
    ]

    def __init__(
        self,
        entity_kind: Literal["director", "actor", "user", "review"],
        identifier: str,
        fallback_name: str = "",
    ) -> None:
        super().__init__()
        self._kind = entity_kind
        self._identifier = identifier
        self._fallback_name = fallback_name
        self._doc: Optional[Dict[str, Any]] = None
        self._extra: Dict[str, Any] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="admin-entity-modal-card", classes="modal-card"):
            yield Static(
                f"[bold #58a6ff]ADMIN INSPECTOR — {self._kind.upper()}[/]",
                id="admin-entity-modal-title",
                classes="panel-heading",
            )
            with VerticalScroll(id="admin-entity-scroll"):
                with Horizontal(id="admin-entity-hero"):
                    yield PosterImage(
                        poster_url="",
                        title=self._fallback_name or self._identifier,
                        cells_width=16,
                        cells_height=10,
                        size="w185",
                        kind="person",
                        id="admin-entity-poster",
                    )
                    yield Static("Loading...", id="admin-entity-body")
            with Horizontal(classes="modal-actions"):
                yield Button("Edit", variant="primary", id="btn-admin-entity-edit")
                yield Button("Delete", variant="error", id="btn-admin-entity-delete")
                yield Button("Close [Esc]", variant="default", id="btn-admin-entity-close")

    def on_mount(self) -> None:
        self._load_entity()

    def _get_db(self):
        mongo = MongoConnection()
        if mongo.initialized and mongo.database is not None:
            return mongo.database
        return None

    def _load_entity(self) -> None:
        db = self._get_db()
        if db is None:
            self.query_one("#admin-entity-body", Static).update(
                "[bold #f85149]MongoDB is not connected.[/]"
            )
            return

        doc: Optional[Dict[str, Any]] = None
        extra: Dict[str, Any] = {}

        if self._kind in ("director", "actor"):
            col = "directors" if self._kind == "director" else "actors"
            if ObjectId.is_valid(self._identifier):
                doc = db[col].find_one({"_id": ObjectId(self._identifier)})
            if doc is None and (self._fallback_name or self._identifier):
                doc = db[col].find_one({"name": self._fallback_name or self._identifier})
            if doc is not None:
                field_key = "directors.name" if self._kind == "director" else "cast.name"
                movies = list(
                    db["movies"].find({field_key: doc.get("name", "")}, {"title": 1, "release_year": 1}).limit(15)
                )
                extra["movies"] = [
                    f"{m.get('title', 'Untitled')} ({m.get('release_year') or '—'})"
                    for m in movies
                ]

        elif self._kind == "user":
            doc = db["users"].find_one({"username": self._identifier})
            if doc is not None:
                extra["reviews_count"] = db["reviews"].count_documents(
                    {"owner.username": doc.get("username", "")}
                )

        elif self._kind == "review":
            if ObjectId.is_valid(self._identifier):
                doc = db["reviews"].find_one({"_id": ObjectId(self._identifier)})

        self._doc = doc
        self._extra = extra
        self._render_entity()

    def _render_entity(self) -> None:
        poster = self.query_one("#admin-entity-poster", PosterImage)
        body = self.query_one("#admin-entity-body", Static)

        if self._doc is None:
            poster.display = False
            body.update(f"[bold #f85149]{self._kind.capitalize()} record not found in MongoDB.[/]")
            self.query_one("#btn-admin-entity-edit", Button).disabled = True
            self.query_one("#btn-admin-entity-delete", Button).disabled = True
            return

        doc = self._doc
        if self._kind in ("director", "actor"):
            poster.display = True
            purl = str(doc.get("poster_url") or doc.get("profile_url") or "")
            name = str(doc.get("name") or "Unknown")
            poster.set_poster(purl, name)
            movies_list = ", ".join(self._extra.get("movies") or []) or "None linked"
            body.update(
                f"[bold #79c0ff]{name}[/]\n"
                f"[dim]_id: {doc.get('_id')}[/]\n\n"
                f"• [bold]Birth Year:[/] {doc.get('birth_year') or '—'}\n"
                f"• [bold]Nationality:[/] {doc.get('nationality') or '—'}\n"
                f"• [bold]Active:[/] {'Yes' if doc.get('is_active', True) else 'No'}\n"
                f"• [bold]Bio:[/] {str(doc.get('bio') or 'No biography available.').strip()}\n\n"
                f"• [bold]Filmography ({len(self._extra.get('movies') or [])}):[/] {movies_list}"
            )

        elif self._kind == "user":
            poster.display = True
            uname = str(doc.get("username") or "")
            poster.set_poster(str(doc.get("avatar_url") or ""), uname)
            created = doc.get("created_at")
            created_str = created.strftime("%Y-%m-%d %H:%M UTC") if isinstance(created, datetime) else "—"
            body.update(
                f"[bold #79c0ff]@{uname}[/]  [dim]({doc.get('role', 'user')})[/]\n"
                f"[dim]_id: {doc.get('_id')}[/]\n\n"
                f"• [bold]Email:[/] {doc.get('email') or '—'}\n"
                f"• [bold]Role:[/] {doc.get('role') or 'user'}\n"
                f"• [bold]Created:[/] {created_str}\n"
                f"• [bold]Lists:[/] {len(doc.get('lists') or [])}  │  "
                f"[bold]Watched:[/] {len(doc.get('watched_movies') or [])}  │  "
                f"[bold]Reviews:[/] {self._extra.get('reviews_count', 0)}\n"
                f"• [bold]Bio:[/] {str(doc.get('bio') or 'No bio.').strip()}"
            )

        elif self._kind == "review":
            poster.display = False
            owner = (doc.get("owner") or {}).get("username") or "unknown"
            movie_title = (doc.get("movie") or {}).get("title") or "Unknown"
            created = doc.get("created_at")
            created_str = created.strftime("%Y-%m-%d %H:%M UTC") if isinstance(created, datetime) else "—"
            liked_by = ", ".join(f"@{u}" for u in (doc.get("liked_by") or [])) or "None"
            body.update(
                f"[bold #79c0ff]Review on {movie_title}[/] by [bold]@{owner}[/]\n"
                f"[dim]_id: {doc.get('_id')}[/]\n\n"
                f"• [bold]Rating:[/] ★ {doc.get('rating', '—')}  │  "
                f"[bold]Likes:[/] ♥ {int(doc.get('likes') or 0)}  │  "
                f"[bold]Created:[/] {created_str}\n"
                f"• [bold]Liked by:[/] {liked_by}\n\n"
                f"• [bold]Content:[/]\n  {str(doc.get('content') or '').strip()}"
            )

    @on(Button.Pressed, "#btn-admin-entity-edit")
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
        else:
            fields = [
                ("rating", "Rating (0.5 - 5.0)", str(doc.get("rating") or "4.0"), False),
                ("content", "Review Content", str(doc.get("content") or ""), True),
            ]

        def _after_edit(vals: Optional[Dict[str, str]]) -> None:
            if not vals:
                return
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
            show_success_toast(self, f"{self._kind.capitalize()} updated in MongoDB")
            self.dismiss("updated")
        except Exception as exc:
            show_error_toast(self, f"Error updating {self._kind}: {exc}")

    @on(Button.Pressed, "#btn-admin-entity-delete")
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
                    db["movies"].update_many(
                        {},
                        {"$pull": {arr_field: {"id": self._doc["_id"]}}},
                    )
                elif self._kind == "user":
                    uname = str(self._doc.get("username") or "")
                    db["users"].delete_one({"_id": self._doc["_id"]})
                    db["reviews"].delete_many({"owner.username": uname})
                    db["movies"].update_many(
                        {},
                        {"$pull": {"liked_by": uname, "watched_by": uname}},
                    )
                elif self._kind == "review":
                    db["reviews"].delete_one({"_id": self._doc["_id"]})
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

    @on(Button.Pressed, "#btn-admin-entity-close")
    def action_close(self) -> None:
        self.dismiss(None)
