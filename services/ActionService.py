"""
Letterboxd-style interactive actions service for MovieVault
(backend/services/ActionService.py).

Enables logging movie views and reviews (1 review per movie per user, editable),
marking movies as watched, liking movies and reviews (at most 1 like per user,
persisted across runs), creating/deleting/modifying personal lists, following
and unfollowing users, and editing user profile information.
"""

from typing import Any, Dict, Optional, Tuple
from datetime import datetime, timezone
import re
import json
from bson import ObjectId
import pydgraph
from pymongo.database import Database

from databases.mongodb import MongoConnection
from databases.dgraph import DgraphConnection
from services.AuthService import UserSession
from services.CatalogService import CatalogService
from services.SettingsService import SettingsService


def _safe_object_id(hex_id: Optional[str]) -> ObjectId:
    """Converts a hexadecimal string into a valid ObjectId or generates a new one."""
    if hex_id and ObjectId.is_valid(hex_id):
        return ObjectId(hex_id)
    return ObjectId()


class ActionService:
    """
    Coordinates user action writes (reviewing/logging views, marking watched,
    liking movies/reviews, managing lists, following accounts, and editing profile) (Singleton).
    """

    _instance: Optional["ActionService"] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "ActionService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

    def _get_mongo_db(self) -> Optional[Database]:
        try:
            mongo = MongoConnection()
            if mongo.initialized and mongo.database is not None:
                return mongo.database
        except Exception:
            pass
        return None

    def _resolve_movie_reference(
        self, db: Database, movie_title: str
    ) -> Tuple[ObjectId, str, str]:
        """
        Looks up the movie in `db["movies"]` by title (case-insensitive) to
        obtain its actual ObjectId, canonical title, and poster_url. If it does not
        yet exist in the catalog, queries TMDB via `CatalogService` to ingest it
        along with its directors and cast before referencing it.
        """
        clean_title = movie_title.strip()
        movie_doc = db["movies"].find_one(
            {"$text": {"$search": f'"{clean_title}"'}},
            {"_id": 1, "title": 1, "poster_url": 1},
        )
        if not movie_doc:
            movie_doc = db["movies"].find_one(
                {"title": {"$regex": f"^{re.escape(clean_title)}$", "$options": "i"}},
                {"_id": 1, "title": 1, "poster_url": 1},
            )
        if not movie_doc:
            CatalogService().fallback_by_title(db, clean_title, limit=3)
            movie_doc = db["movies"].find_one(
                {"$text": {"$search": clean_title}},
                {"_id": 1, "title": 1, "poster_url": 1},
            )
            if not movie_doc:
                movie_doc = db["movies"].find_one(
                    {"title": {"$regex": re.escape(clean_title), "$options": "i"}},
                    {"_id": 1, "title": 1, "poster_url": 1},
                )
        if movie_doc:
            return (
                movie_doc["_id"],
                movie_doc.get("title", clean_title),
                movie_doc.get("poster_url", ""),
            )
        return ObjectId(), clean_title, ""

    def _ensure_movie_watched_in_db(
        self,
        db: Database,
        username: str,
        movie_oid: ObjectId,
        resolved_title: str,
        resolved_poster: str,
    ) -> bool:
        """
        Internal helper that marks a movie as watched in `db["movies"].watched_by`
        and `db["users"].watched_movies`. Returns True if newly marked, False if already watched.
        """
        rx_user = {"$regex": f"^{re.escape(username)}$", "$options": "i"}
        already_watched = False

        movie_doc = db["movies"].find_one({"_id": movie_oid}, {"watched_by": 1})
        if movie_doc:
            watched_by = {str(u).lower() for u in (movie_doc.get("watched_by") or [])}
            if username.lower() in watched_by:
                already_watched = True

        user_doc = db["users"].find_one({"username": rx_user}, {"_id": 1, "watched_movies": 1})
        if user_doc is not None:
            watched_list = list(user_doc.get("watched_movies") or [])
            existing_titles = {str(m.get("title") or "").lower() for m in watched_list}
            if resolved_title.lower() in existing_titles:
                already_watched = True

        if already_watched:
            return False

        if movie_doc is not None and SettingsService().public_activity:
            db["movies"].update_one(
                {"_id": movie_oid},
                {"$addToSet": {"watched_by": username}},
            )

        if user_doc is not None:
            watched_list = list(user_doc.get("watched_movies") or [])
            entry: Dict[str, Any] = {"id": movie_oid, "title": resolved_title}
            if resolved_poster:
                entry["poster_url"] = resolved_poster
            watched_list.append(entry)
            db["users"].update_one(
                {"_id": user_doc["_id"]},
                {"$set": {"watched_movies": watched_list}},
            )

        return True

    def _ensure_movie_liked_in_db(
        self,
        db: Database,
        username: str,
        movie_oid: ObjectId,
        resolved_title: str,
        resolved_poster: str,
    ) -> bool:
        """
        Internal helper that registers a single like for `username` on a movie in
        `db["movies"]` (`liked_by` + `likes`) and `db["users"].liked_movies`.
        Returns True if newly liked, False if the user had already liked the movie.
        """
        rx_user = {"$regex": f"^{re.escape(username)}$", "$options": "i"}
        movie_doc = db["movies"].find_one({"_id": movie_oid}, {"liked_by": 1})
        already_liked = False

        if movie_doc is not None:
            liked_by = {str(u).lower() for u in (movie_doc.get("liked_by") or [])}
            if username.lower() in liked_by:
                already_liked = True

        user_doc = db["users"].find_one({"username": rx_user}, {"_id": 1, "liked_movies": 1})
        if user_doc is not None:
            liked_list = list(user_doc.get("liked_movies") or [])
            existing_titles = {str(m.get("title") or "").lower() for m in liked_list}
            if resolved_title.lower() in existing_titles:
                already_liked = True

        if already_liked:
            return False

        if movie_doc is not None:
            db["movies"].update_one(
                {"_id": movie_oid},
                {
                    "$addToSet": {"liked_by": username},
                    "$inc": {"likes": 1},
                },
            )

        if user_doc is not None:
            liked_list = list(user_doc.get("liked_movies") or [])
            entry: Dict[str, Any] = {"id": movie_oid, "title": resolved_title}
            if resolved_poster:
                entry["poster_url"] = resolved_poster
            liked_list.append(entry)
            db["users"].update_one(
                {"_id": user_doc["_id"]},
                {"$set": {"liked_movies": liked_list}},
            )

        return True

    def mark_movie_watched(
        self,
        user: UserSession,
        movie_title: str,
    ) -> Tuple[bool, str]:
        """
        Marks a movie as watched by `user` and persists the state in MongoDB.
        """
        clean_title = (movie_title or "").strip()
        if not clean_title:
            return False, "Movie title is required."

        db = self._get_mongo_db()
        if db is None:
            return False, "MongoDB is not connected."

        try:
            movie_oid, resolved_title, resolved_poster = self._resolve_movie_reference(
                db, clean_title
            )
            newly_marked = self._ensure_movie_watched_in_db(
                db, user.username, movie_oid, resolved_title, resolved_poster
            )
            if not newly_marked:
                rx_user = {"$regex": f"^{re.escape(user.username)}$", "$options": "i"}
                movie_doc = db["movies"].find_one({"_id": movie_oid}, {"watched_by": 1})
                if movie_doc is not None:
                    updated_watched_by = [
                        u
                        for u in (movie_doc.get("watched_by") or [])
                        if str(u).lower() != user.username.lower()
                    ]
                    db["movies"].update_one(
                        {"_id": movie_oid},
                        {"$set": {"watched_by": updated_watched_by}},
                    )
                user_doc = db["users"].find_one(
                    {"username": rx_user}, {"_id": 1, "watched_movies": 1}
                )
                if user_doc is not None:
                    updated_watched_movies = [
                        m
                        for m in (user_doc.get("watched_movies") or [])
                        if str(m.get("title") or "").lower() != resolved_title.lower()
                        and str(m.get("id") or "") != str(movie_oid)
                    ]
                    db["users"].update_one(
                        {"_id": user_doc["_id"]},
                        {"$set": {"watched_movies": updated_watched_movies}},
                    )
                return True, f"Removed '{resolved_title}' from watched movies."
            return True, f"'{resolved_title}' marked as watched by @{user.username}."
        except Exception as exc:
            return False, f"Error marking movie as watched: {exc}"

    def like_movie(
        self,
        user: UserSession,
        movie_title: str,
    ) -> Tuple[bool, str]:
        """
        Toggles a like from `user` on `movie_title` (persisted in MongoDB across runs).
        """
        clean_title = (movie_title or "").strip()
        if not clean_title:
            return False, "Movie title is required."

        db = self._get_mongo_db()
        if db is None:
            return False, "MongoDB is not connected."

        try:
            movie_oid, resolved_title, resolved_poster = self._resolve_movie_reference(
                db, clean_title
            )
            newly_liked = self._ensure_movie_liked_in_db(
                db, user.username, movie_oid, resolved_title, resolved_poster
            )
            if not newly_liked:
                rx_user = {"$regex": f"^{re.escape(user.username)}$", "$options": "i"}
                movie_doc = db["movies"].find_one(
                    {"_id": movie_oid}, {"liked_by": 1, "likes": 1}
                )
                if movie_doc is not None:
                    updated_liked_by = [
                        u
                        for u in (movie_doc.get("liked_by") or [])
                        if str(u).lower() != user.username.lower()
                    ]
                    new_likes = max(0, int(movie_doc.get("likes") or 0) - 1)
                    db["movies"].update_one(
                        {"_id": movie_oid},
                        {"$set": {"liked_by": updated_liked_by, "likes": new_likes}},
                    )
                user_doc = db["users"].find_one(
                    {"username": rx_user}, {"_id": 1, "liked_movies": 1}
                )
                if user_doc is not None:
                    updated_liked_movies = [
                        m
                        for m in (user_doc.get("liked_movies") or [])
                        if str(m.get("title") or "").lower() != resolved_title.lower()
                        and str(m.get("id") or "") != str(movie_oid)
                    ]
                    db["users"].update_one(
                        {"_id": user_doc["_id"]},
                        {"$set": {"liked_movies": updated_liked_movies}},
                    )
                return True, f"Removed like from '{resolved_title}'."
            return True, f"You liked '{resolved_title}'! ♥"
        except Exception as exc:
            return False, f"Error liking movie: {exc}"

    def create_review(
        self,
        user: UserSession,
        movie_title: str,
        release_year: int,
        rating: float,
        content: str,
        liked: bool = False,
        viewed_on: str = "Streaming",
    ) -> Tuple[bool, str]:
        """
        Creates or updates `user`'s review for `movie_title`:
        - Enforces at most 1 review per movie per user.
        - If `user` already reviewed this movie, updates `rating`, `content`, and `created_at`.
        - Automatically marks the movie as watched (and liked if `liked=True`).
        """
        clean_title = (movie_title or "").strip()
        clean_content = (content or "").strip()
        if not clean_title:
            return False, "Movie title is required."
        if rating < 0.5 or rating > 5.0:
            return False, "Rating must be between 0.5 and 5.0 stars."
        if not clean_content:
            return False, "Review content cannot be empty."

        db = self._get_mongo_db()
        if db is None:
            return False, "MongoDB is not connected. Could not save review."

        try:
            movie_oid, resolved_title, resolved_poster = self._resolve_movie_reference(
                db, clean_title
            )
            user_oid = _safe_object_id(user.user_id)
            now = datetime.now(timezone.utc)

            rx_user = {"$regex": f"^{re.escape(user.username)}$", "$options": "i"}
            rx_title = {"$regex": f"^{re.escape(resolved_title)}$", "$options": "i"}

            existing_review = db["reviews"].find_one(
                {
                    "owner.username": rx_user,
                    "$or": [{"movie.id": movie_oid}, {"movie.title": rx_title}],
                }
            )

            self._ensure_movie_watched_in_db(
                db, user.username, movie_oid, resolved_title, resolved_poster
            )
            if liked:
                self._ensure_movie_liked_in_db(
                    db, user.username, movie_oid, resolved_title, resolved_poster
                )

            if existing_review is not None:
                update_ops: Dict[str, Any] = {
                    "$set": {
                        "movie": {"id": movie_oid, "title": resolved_title},
                        "rating": float(rating),
                        "content": clean_content,
                        "created_at": now,
                    }
                }
                existing_liked_by = {
                    str(u).lower() for u in (existing_review.get("liked_by") or [])
                }
                if liked and user.username.lower() not in existing_liked_by:
                    update_ops["$addToSet"] = {"liked_by": user.username}
                    update_ops["$inc"] = {"likes": 1}

                db["reviews"].update_one({"_id": existing_review["_id"]}, update_ops)
                return (
                    True,
                    f"Your review for '{resolved_title}' ({rating:.1f}★) was updated in MongoDB.",
                )

            review_doc: Dict[str, Any] = {
                "movie": {
                    "id": movie_oid,
                    "title": resolved_title,
                },
                "owner": {
                    "id": user_oid,
                    "username": user.username,
                },
                "rating": float(rating),
                "content": clean_content,
                "likes": 1 if liked else 0,
                "liked_by": [user.username] if liked else [],
                "comments_count": 0,
                "created_at": now,
            }
            db["reviews"].insert_one(review_doc)

            return (
                True,
                f"Review for '{resolved_title}' ({rating:.1f}★) saved to MongoDB by @{user.username}.",
            )
        except Exception as exc:
            return False, f"Error saving review to MongoDB: {exc}"

    def like_review(
        self,
        user: UserSession,
        movie_title: str,
        review_owner: str,
    ) -> Tuple[bool, str]:
        """
        Toggles a like from `user` to `review_owner`'s review of `movie_title`.
        Adds a like if not yet liked, or removes the existing like from `liked_by` in MongoDB.
        """
        clean_title = (movie_title or "").strip()
        clean_owner = (review_owner or "").strip().lstrip("@")
        if not clean_title or not clean_owner:
            return False, "Movie title and review author must be specified."

        db = self._get_mongo_db()
        if db is None:
            return False, "MongoDB is not connected."

        try:
            rx_title = {"$regex": f"^{re.escape(clean_title)}$", "$options": "i"}
            rx_owner = {"$regex": f"^{re.escape(clean_owner)}$", "$options": "i"}
            rev_doc = db["reviews"].find_one(
                {"movie.title": rx_title, "owner.username": rx_owner}
            )
            if rev_doc is None:
                return (
                    False,
                    f"No review found from @{clean_owner} for '{clean_title}' in MongoDB.",
                )

            raw_liked_by = list(rev_doc.get("liked_by") or [])
            if any(str(u).lower() == user.username.lower() for u in raw_liked_by):
                new_liked_by = [
                    u for u in raw_liked_by if str(u).lower() != user.username.lower()
                ]
                current_likes = int(rev_doc.get("likes") or 0)
                new_likes = max(0, current_likes - 1)
                db["reviews"].update_one(
                    {"_id": rev_doc["_id"]},
                    {
                        "$set": {
                            "liked_by": new_liked_by,
                            "likes": new_likes,
                        }
                    },
                )
                return (
                    True,
                    f"Like removed from @{clean_owner}'s review of '{clean_title}'.",
                )

            db["reviews"].update_one(
                {"_id": rev_doc["_id"]},
                {
                    "$addToSet": {"liked_by": user.username},
                    "$inc": {"likes": 1},
                },
            )
            return (
                True,
                f"Like registered for @{clean_owner}'s review of '{clean_title}'.",
            )
        except Exception as exc:
            return False, f"Error registering like in MongoDB: {exc}"

    def add_movie_to_list(
        self,
        user: UserSession,
        list_name: str,
        movie_title: str,
        poster_url: str = "",
        description: str = "",
    ) -> Tuple[bool, str]:
        """
        Creates a personal list or adds a movie to an existing list of the user.
        Persists to both `mongodb["lists"]` and `mongodb["users"].lists`.
        """
        clean_list = (list_name or "").strip()
        clean_movie = (movie_title or "").strip()
        clean_desc = (description or "").strip()
        if not clean_list or not clean_movie:
            return False, "List name and movie title are required."

        db = self._get_mongo_db()
        if db is None:
            return False, "MongoDB is not connected."

        try:
            movie_oid, resolved_title, resolved_poster = self._resolve_movie_reference(
                db, clean_movie
            )
            final_poster = (poster_url or "").strip() or resolved_poster
            user_oid = _safe_object_id(user.user_id)

            movie_entry: Dict[str, Any] = {
                "id": movie_oid,
                "title": resolved_title,
            }
            if final_poster:
                movie_entry["poster_url"] = final_poster

            rx_user = {"$regex": f"^{re.escape(user.username)}$", "$options": "i"}
            rx_list = {"$regex": f"^{re.escape(clean_list)}$", "$options": "i"}
            existing_list = db["lists"].find_one(
                {"owner.username": rx_user, "name": rx_list}
            )
            user_doc = db["users"].find_one({"username": rx_user})
            user_lists = list(user_doc.get("lists") or []) if user_doc is not None else []
            matched_idx = next(
                (
                    idx
                    for idx, item in enumerate(user_lists)
                    if str(item.get("name") or "").lower() == clean_list.lower()
                ),
                None,
            )

            # Check if the movie is already present in either `lists` or `users.lists`
            already_in_lists_col = existing_list is not None and any(
                str(m.get("title") or "").lower() == resolved_title.lower()
                for m in (existing_list.get("movies") or [])
            )
            already_in_user_doc = matched_idx is not None and any(
                str(m.get("title") or "").lower() == resolved_title.lower()
                for m in (user_lists[matched_idx].get("movies") or [])
            )
            if already_in_lists_col or already_in_user_doc:
                return (
                    False,
                    f"Movie '{resolved_title}' is already in list '{clean_list}'.",
                )

            if existing_list is None:
                new_list_doc: Dict[str, Any] = {
                    "owner": {
                        "id": user_oid,
                        "username": user.username,
                    },
                    "name": clean_list,
                    "description": clean_desc,
                    "movies": [movie_entry],
                }
                db["lists"].insert_one(new_list_doc)
            else:
                db["lists"].update_one(
                    {"_id": existing_list["_id"]},
                    {"$push": {"movies": movie_entry}},
                )

            if user_doc is not None:
                if matched_idx is None:
                    user_lists.append(
                        {
                            "name": clean_list,
                            "description": clean_desc,
                            "movies": [movie_entry],
                        }
                    )
                else:
                    user_lists[matched_idx].setdefault("movies", []).append(
                        movie_entry
                    )
                db["users"].update_one(
                    {"_id": user_doc["_id"]},
                    {"$set": {"lists": user_lists}},
                )
                user.lists_count = len(user_lists)

            return (
                True,
                f"Movie '{resolved_title}' added to list '{clean_list}' in MongoDB.",
            )
        except Exception as exc:
            return False, f"Error updating list in MongoDB: {exc}"

    def create_list(
        self,
        user: UserSession,
        list_name: str,
        description: str = "",
    ) -> Tuple[bool, str]:
        """
        Creates a new empty personal movie list for `user` in `mongodb["lists"]`
        and `mongodb["users"].lists`.
        """
        clean_name = (list_name or "").strip()
        clean_desc = (description or "").strip()
        if not clean_name:
            return False, "List name is required."

        db = self._get_mongo_db()
        if db is None:
            return False, "MongoDB is not connected."

        try:
            rx_user = {"$regex": f"^{re.escape(user.username)}$", "$options": "i"}
            rx_list = {"$regex": f"^{re.escape(clean_name)}$", "$options": "i"}
            existing = db["lists"].find_one({"owner.username": rx_user, "name": rx_list})
            if existing is not None:
                return False, f"You already have a list named '{clean_name}'."

            user_oid = _safe_object_id(user.user_id)
            db["lists"].insert_one(
                {
                    "owner": {"id": user_oid, "username": user.username},
                    "name": clean_name,
                    "description": clean_desc,
                    "movies": [],
                }
            )

            user_doc = db["users"].find_one({"username": rx_user})
            if user_doc is not None:
                user_lists = list(user_doc.get("lists") or [])
                if not any(
                    str(item.get("name") or "").lower() == clean_name.lower()
                    for item in user_lists
                ):
                    user_lists.append(
                        {
                            "name": clean_name,
                            "description": clean_desc,
                            "movies": [],
                        }
                    )
                    db["users"].update_one(
                        {"_id": user_doc["_id"]},
                        {"$set": {"lists": user_lists}},
                    )
                user.lists_count = len(user_lists)

            return True, f"List '{clean_name}' created in MongoDB."
        except Exception as exc:
            return False, f"Error creating list: {exc}"

    def delete_list(
        self,
        user: UserSession,
        list_name: str,
    ) -> Tuple[bool, str]:
        """
        Deletes a personal movie list owned by `user` from `mongodb["lists"]`
        and `mongodb["users"].lists`.
        """
        clean_name = (list_name or "").strip()
        if not clean_name:
            return False, "List name is required."

        db = self._get_mongo_db()
        if db is None:
            return False, "MongoDB is not connected."

        try:
            rx_user = {"$regex": f"^{re.escape(user.username)}$", "$options": "i"}
            rx_list = {"$regex": f"^{re.escape(clean_name)}$", "$options": "i"}
            db["lists"].delete_many({"owner.username": rx_user, "name": rx_list})

            user_doc = db["users"].find_one({"username": rx_user})
            if user_doc is not None:
                user_lists = [
                    item
                    for item in (user_doc.get("lists") or [])
                    if str(item.get("name") or "").lower() != clean_name.lower()
                ]
                db["users"].update_one(
                    {"_id": user_doc["_id"]},
                    {"$set": {"lists": user_lists}},
                )
                user.lists_count = len(user_lists)

            return True, f"List '{clean_name}' deleted from MongoDB."
        except Exception as exc:
            return False, f"Error deleting list: {exc}"

    def remove_movie_from_list(
        self,
        user: UserSession,
        list_name: str,
        movie_title: str,
    ) -> Tuple[bool, str]:
        """
        Removes `movie_title` from `user`'s `list_name` in both `mongodb["lists"]`
        and `mongodb["users"].lists`.
        """
        clean_list = (list_name or "").strip()
        clean_movie = (movie_title or "").strip()
        if not clean_list or not clean_movie:
            return False, "List name and movie title are required."

        db = self._get_mongo_db()
        if db is None:
            return False, "MongoDB is not connected."

        try:
            rx_user = {"$regex": f"^{re.escape(user.username)}$", "$options": "i"}
            rx_list = {"$regex": f"^{re.escape(clean_list)}$", "$options": "i"}
            rx_movie = {"$regex": f"^{re.escape(clean_movie)}$", "$options": "i"}

            db["lists"].update_many(
                {"owner.username": rx_user, "name": rx_list},
                {"$pull": {"movies": {"title": rx_movie}}},
            )

            user_doc = db["users"].find_one({"username": rx_user})
            if user_doc is not None:
                user_lists = list(user_doc.get("lists") or [])
                for item in user_lists:
                    if str(item.get("name") or "").lower() == clean_list.lower():
                        item["movies"] = [
                            m
                            for m in (item.get("movies") or [])
                            if str(m.get("title") or "").lower() != clean_movie.lower()
                        ]
                db["users"].update_one(
                    {"_id": user_doc["_id"]},
                    {"$set": {"lists": user_lists}},
                )

            return True, f"Movie '{clean_movie}' removed from '{clean_list}'."
        except Exception as exc:
            return False, f"Error removing movie from list: {exc}"

    def follow_user(
        self,
        user: UserSession,
        target_username: str,
    ) -> Tuple[bool, str]:
        """
        Logs that `user` follows `target_username`, persisting in MongoDB (`users`)
        and Dgraph if connected. Prevents duplicate follows.
        """
        clean_target = (target_username or "").strip().lstrip("@")
        if not clean_target:
            return False, "You must enter the username of the account you want to follow."
        if clean_target.lower() == user.username.lower():
            return False, "You cannot follow your own account."

        db = self._get_mongo_db()
        if db is not None:
            try:
                rx_user = {"$regex": f"^{re.escape(user.username)}$", "$options": "i"}
                rx_target = {"$regex": f"^{re.escape(clean_target)}$", "$options": "i"}
                target_doc = db["users"].find_one({"username": rx_target})
                if target_doc is not None:
                    clean_target = target_doc.get("username", clean_target)
                    existing_followers = {
                        str(u).lower() for u in (target_doc.get("followers") or [])
                    }
                    if user.username.lower() in existing_followers:
                        return False, f"You are already following @{clean_target}."

                    db["users"].update_one(
                        {"_id": target_doc["_id"]},
                        {"$addToSet": {"followers": user.username}},
                    )

                user_doc = db["users"].find_one({"username": rx_user})
                if user_doc is not None:
                    existing_following = {
                        str(u).lower() for u in (user_doc.get("following") or [])
                    }
                    if clean_target.lower() in existing_following and target_doc is None:
                        return False, f"You are already following @{clean_target}."
                    db["users"].update_one(
                        {"_id": user_doc["_id"]},
                        {"$addToSet": {"following": clean_target}},
                    )
            except Exception as exc:
                return False, f"Error saving follow in MongoDB: {exc}"

        try:
            dgraph = DgraphConnection()
            if dgraph.initialized and dgraph.client is not None:
                txn = dgraph.client.txn()
                try:
                    mutation_payload = {
                        "uid": f"_:{user.username}",
                        "dgraph.type": "User",
                        "username": user.username,
                        "follows": [
                            {
                                "uid": f"_:{clean_target}",
                                "dgraph.type": "User",
                                "username": clean_target,
                            }
                        ],
                    }
                    mutation = pydgraph.Mutation(
                        set_json=json.dumps(mutation_payload).encode("utf-8")
                    )
                    txn.mutate(mutation, commit_now=True)
                finally:
                    txn.discard()
        except Exception:
            pass

        return True, f"Now following @{clean_target}."

    def unfollow_user(
        self,
        user: UserSession,
        target_username: str,
    ) -> Tuple[bool, str]:
        """
        Removes the follow relationship from `user` to `target_username` in MongoDB.
        """
        clean_target = (target_username or "").strip().lstrip("@")
        if not clean_target:
            return False, "Target username is required."
        if clean_target.lower() == user.username.lower():
            return False, "You cannot unfollow your own account."

        db = self._get_mongo_db()
        if db is not None:
            try:
                rx_user = {"$regex": f"^{re.escape(user.username)}$", "$options": "i"}
                rx_target = {"$regex": f"^{re.escape(clean_target)}$", "$options": "i"}
                user_doc = db["users"].find_one({"username": rx_user})
                if user_doc is not None:
                    new_following = [
                        u
                        for u in (user_doc.get("following") or [])
                        if str(u).lower() != clean_target.lower()
                    ]
                    db["users"].update_one(
                        {"_id": user_doc["_id"]},
                        {"$set": {"following": new_following}},
                    )

                target_doc = db["users"].find_one({"username": rx_target})
                if target_doc is not None:
                    new_followers = [
                        u
                        for u in (target_doc.get("followers") or [])
                        if str(u).lower() != user.username.lower()
                    ]
                    db["users"].update_one(
                        {"_id": target_doc["_id"]},
                        {"$set": {"followers": new_followers}},
                    )
            except Exception as exc:
                return False, f"Error unfollowing in MongoDB: {exc}"

        return True, f"Unfollowed @{clean_target}."

    def update_user_profile(
        self,
        user: UserSession,
        new_username: str,
        new_email: str,
    ) -> Tuple[bool, Optional[UserSession], str]:
        """
        Updates the authenticated user's username and/or email in MongoDB
        and propagates username changes to reviews, lists, and social arrays.
        """
        clean_user = (new_username or "").strip().lstrip("@")
        clean_email = (new_email or "").strip().lower()

        if not clean_user or not clean_email:
            return False, None, "Username and email are required."
        if len(clean_user) < 3 or not re.match(r"^[a-zA-Z0-9_.-]+$", clean_user):
            return False, None, "Username must have at least 3 valid characters."
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", clean_email):
            return False, None, "Invalid email format."

        db = self._get_mongo_db()
        if db is not None:
            try:
                old_username = user.username
                rx_old = {"$regex": f"^{re.escape(old_username)}$", "$options": "i"}
                user_doc = db["users"].find_one({"username": rx_old})

                if user_doc is not None:
                    # Check uniqueness on other documents
                    dup_user = db["users"].find_one(
                        {
                            "_id": {"$ne": user_doc["_id"]},
                            "username": {"$regex": f"^{re.escape(clean_user)}$", "$options": "i"},
                        }
                    )
                    if dup_user is not None:
                        return False, None, f"Username @{clean_user} is already taken."

                    dup_email = db["users"].find_one(
                        {
                            "_id": {"$ne": user_doc["_id"]},
                            "email": {"$regex": f"^{re.escape(clean_email)}$", "$options": "i"},
                        }
                    )
                    if dup_email is not None:
                        return False, None, f"Email {clean_email} is already registered."

                    db["users"].update_one(
                        {"_id": user_doc["_id"]},
                        {"$set": {"username": clean_user, "email": clean_email}},
                    )

                    if old_username != clean_user:
                        db["reviews"].update_many(
                            {"owner.username": rx_old},
                            {"$set": {"owner.username": clean_user}},
                        )
                        db["lists"].update_many(
                            {"owner.username": rx_old},
                            {"$set": {"owner.username": clean_user}},
                        )
            except Exception as exc:
                return False, None, f"Error updating profile in MongoDB: {exc}"

        updated = UserSession(
            user_id=user.user_id,
            username=clean_user,
            email=clean_email,
            lists_count=user.lists_count,
            is_live_db=user.is_live_db,
            avatar_url=user.avatar_url,
        )
        return True, updated, f"Profile updated for @{clean_user}."

    def update_user_avatar(
        self,
        user: UserSession,
        source_path_or_url: str,
    ) -> Tuple[bool, Optional[UserSession], str]:
        """
        Uploads/sets the authenticated user's profile photo from a local file path
        (copied into `public/avatars/`) or an HTTP(S) image URL, and persists
        `avatar_url` in MongoDB.
        """
        raw = (source_path_or_url or "").strip()
        if not raw:
            return False, None, "Please enter a local image path or image URL."

        if raw.lower().startswith(("http://", "https://")):
            final_avatar = raw
        else:
            from pathlib import Path
            from PIL import Image

            src_path = Path(raw).expanduser()
            if not src_path.is_file():
                return False, None, f"Image file not found: {raw}"
            try:
                avatars_dir = Path(__file__).resolve().parent.parent / "public" / "avatars"
                avatars_dir.mkdir(parents=True, exist_ok=True)
                safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", user.username.lower()) or "user"
                dest_path = avatars_dir / f"{safe_name}.png"
                with Image.open(src_path) as im:
                    im.convert("RGB").save(dest_path, format="PNG")
                final_avatar = str(dest_path)
            except Exception as exc:
                return False, None, f"Could not process image file: {exc}"

        db = self._get_mongo_db()
        if db is not None:
            try:
                rx_user = {"$regex": f"^{re.escape(user.username)}$", "$options": "i"}
                db["users"].update_one(
                    {"username": rx_user},
                    {"$set": {"avatar_url": final_avatar}},
                )
            except Exception as exc:
                return False, None, f"Error saving profile photo in MongoDB: {exc}"

        updated = UserSession(
            user_id=user.user_id,
            username=user.username,
            email=user.email,
            favorite_genres=list(user.favorite_genres),
            lists_count=user.lists_count,
            is_live_db=user.is_live_db,
            avatar_url=final_avatar,
        )
        return True, updated, "Profile photo updated."
