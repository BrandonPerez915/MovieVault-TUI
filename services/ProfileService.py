"""
Profile & Personal Lists read service for MovieVault
(backend/services/ProfileService.py).

Provides MongoDB-backed reads for user profiles, followers/following lists,
user reviews, watched movies, personal lists, and per-movie user interaction
state (watched, liked, existing review) persisted across runs.
"""

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from pymongo import DESCENDING
from pymongo.database import Database

from databases.mongodb import MongoConnection
from services.CatalogService import MovieSummary


@dataclass
class UserProfile:
    """Public and private profile summary for a MovieVault user."""

    username: str
    email: str = ""
    created_at: str = ""
    reviews_count: int = 0
    watched_count: int = 0
    lists_count: int = 0
    followers_count: int = 0
    following_count: int = 0
    is_following: bool = False
    avatar_url: str = ""


@dataclass
class UserListSummary:
    """Personal movie list belonging to a user."""

    name: str
    description: str = ""
    movies: List[MovieSummary] = field(default_factory=list)

    @property
    def movies_count(self) -> int:
        return len(self.movies)


class ProfileService:
    """
    Read service powering the Instagram-style Profile view,
    the My Lists management tab, and persistent movie interaction states (Singleton).
    """

    _instance: Optional["ProfileService"] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "ProfileService":
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

    def _resolve_movie_summary(
        self,
        db: Database,
        raw_id: Any,
        title: str,
        fallback_poster: str = "",
    ) -> MovieSummary:
        clean_title = (title or "").strip()
        doc: Optional[Dict[str, Any]] = None
        try:
            if isinstance(raw_id, ObjectId):
                doc = db["movies"].find_one({"_id": raw_id})
            elif raw_id and ObjectId.is_valid(str(raw_id)):
                doc = db["movies"].find_one({"_id": ObjectId(str(raw_id))})
            if doc is None and clean_title:
                # Use idx_title_synopsis_impact ($text) first
                doc = db["movies"].find_one({"$text": {"$search": f'"{clean_title}"'}})
            if doc is None and clean_title:
                doc = db["movies"].find_one(
                    {"title": {"$regex": f"^{re.escape(clean_title)}$", "$options": "i"}}
                )
        except Exception:
            doc = None

        if doc is not None:
            return MovieSummary(
                movie_id=str(doc["_id"]),
                title=doc.get("title", clean_title),
                release_year=int(doc.get("release_year") or 0),
                rating=round(float(doc.get("rating") or 0.0), 2),
                poster_url=doc.get("poster_url") or fallback_poster or "",
                genres=list(doc.get("genres") or []),
                impact_score=float(doc.get("impact_score") or 0.0),
            )

        return MovieSummary(
            movie_id=str(raw_id or clean_title),
            title=clean_title or "Untitled",
            release_year=0,
            rating=0.0,
            poster_url=fallback_poster or "",
            genres=[],
            impact_score=0.0,
        )

    def _collect_followers_set(self, db: Database, username: str) -> List[str]:
        """Returns deduplicated usernames that follow `username` in MongoDB."""
        clean = username.strip().lstrip("@")
        rx = {"$regex": f"^{re.escape(clean)}$", "$options": "i"}
        seen: Dict[str, str] = {}

        user_doc = db["users"].find_one({"username": rx}, {"followers": 1})
        if user_doc:
            for u in user_doc.get("followers") or []:
                if u and str(u).strip():
                    s = str(u).strip()
                    seen[s.lower()] = s

        for doc in db["users"].find({"following": rx}, {"username": 1}):
            uname = str(doc.get("username") or "").strip()
            if uname:
                seen[uname.lower()] = uname

        seen.pop(clean.lower(), None)
        return list(seen.values())

    def _collect_following_set(self, db: Database, username: str) -> List[str]:
        """Returns deduplicated usernames that `username` follows in MongoDB."""
        clean = username.strip().lstrip("@")
        rx = {"$regex": f"^{re.escape(clean)}$", "$options": "i"}
        seen: Dict[str, str] = {}

        user_doc = db["users"].find_one({"username": rx}, {"following": 1})
        if user_doc:
            for u in user_doc.get("following") or []:
                if u and str(u).strip():
                    s = str(u).strip()
                    seen[s.lower()] = s

        for doc in db["users"].find({"followers": rx}, {"username": 1}):
            uname = str(doc.get("username") or "").strip()
            if uname:
                seen[uname.lower()] = uname

        seen.pop(clean.lower(), None)
        return list(seen.values())

    def get_user_profile(
        self,
        viewer_username: str,
        target_username: str,
    ) -> Optional[UserProfile]:
        """
        Retrieves the profile summary for `target_username` as seen by `viewer_username`.
        """
        clean_target = (target_username or "").strip().lstrip("@")
        if not clean_target:
            return None

        clean_viewer = (viewer_username or "").strip().lstrip("@")
        db = self._get_mongo_db()
        if db is None:
            return UserProfile(username=clean_target)

        try:
            rx_target = {"$regex": f"^{re.escape(clean_target)}$", "$options": "i"}
            user_doc = db["users"].find_one({"username": rx_target})
            reviews_count = db["reviews"].count_documents({"owner.username": rx_target})
            user_lists = self.get_user_lists(clean_target)
            _, watched_total = self.get_user_watched_movies(clean_target, page=1, page_size=1)

            if user_doc is None and reviews_count == 0 and not user_lists:
                return None

            canonical_username = (
                user_doc.get("username", clean_target) if user_doc else clean_target
            )
            email = user_doc.get("email", "") if user_doc else ""
            created_raw = user_doc.get("created_at") if user_doc else None
            created_str = (
                created_raw.strftime("%Y-%m-%d")
                if hasattr(created_raw, "strftime")
                else str(created_raw or "")
            )

            followers_list = self._collect_followers_set(db, canonical_username)
            following_list = self._collect_following_set(db, canonical_username)
            is_following = bool(
                clean_viewer
                and clean_viewer.lower() in {u.lower() for u in followers_list}
            )

            return UserProfile(
                username=canonical_username,
                email=email,
                created_at=created_str,
                reviews_count=reviews_count,
                watched_count=watched_total,
                lists_count=len(user_lists),
                followers_count=len(followers_list),
                following_count=len(following_list),
                is_following=is_following,
                avatar_url=str(user_doc.get("avatar_url") or "") if user_doc else "",
            )
        except Exception:
            return UserProfile(username=clean_target)

    def get_user_reviews(
        self,
        username: str,
        page: int = 1,
        page_size: int = 10,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Retrieves paginated reviews published by `username` from `mongodb["reviews"]`.
        """
        clean_user = (username or "").strip().lstrip("@")
        if not clean_user:
            return [], 0

        db = self._get_mongo_db()
        if db is None:
            return [], 0

        try:
            # Resolve canonical username via idx_unique_username first
            user_doc = db["users"].find_one(
                {"username": clean_user}, {"username": 1}
            )
            canonical_user = (
                str(user_doc["username"])
                if user_doc and user_doc.get("username")
                else clean_user
            )
            # Uses idx_username_created_at: [("owner.username", 1), ("created_at", 1)]
            query_filter: Dict[str, Any] = {"owner.username": canonical_user}
            total = db["reviews"].count_documents(query_filter)
            if total == 0:
                query_filter = {
                    "owner.username": {
                        "$regex": f"^{re.escape(clean_user)}$",
                        "$options": "i",
                    }
                }
                total = db["reviews"].count_documents(query_filter)
            if total == 0:
                return [], 0

            skip = max(0, (max(1, page) - 1) * max(1, page_size))
            cursor = (
                db["reviews"]
                .find(query_filter)
                .sort("created_at", DESCENDING)
                .skip(skip)
                .limit(max(1, page_size))
            )

            rows: List[Dict[str, Any]] = []
            for doc in cursor:
                movie_obj = doc.get("movie") or {}
                created = doc.get("created_at")
                created_str = (
                    created.strftime("%Y-%m-%d %H:%M")
                    if hasattr(created, "strftime")
                    else str(created or "")
                )
                rows.append(
                    {
                        "_review_id": str(doc.get("_id", "")),
                        "movie_id": str(movie_obj.get("id") or ""),
                        "movie_title": str(movie_obj.get("title") or "Untitled"),
                        "username": str((doc.get("owner") or {}).get("username") or clean_user),
                        "rating": round(float(doc.get("rating") or 0.0), 1),
                        "likes": int(doc.get("likes") or 0),
                        "liked_by": list(doc.get("liked_by") or []),
                        "comments_count": int(doc.get("comments_count") or 0),
                        "content": str(doc.get("content") or ""),
                        "created_at": created_str,
                    }
                )
            return rows, total
        except Exception:
            return [], 0

    def get_user_watched_movies(
        self,
        username: str,
        page: int = 1,
        page_size: int = 12,
    ) -> Tuple[List[MovieSummary], int]:
        """
        Retrieves paginated movies watched/logged by `username` across:
        1. `users.watched_movies`
        2. `movies.watched_by`
        3. `reviews` authored by `username`
        """
        clean_user = (username or "").strip().lstrip("@")
        if not clean_user:
            return [], 0

        db = self._get_mongo_db()
        if db is None:
            return [], 0

        try:
            rx_user = {"$regex": f"^{re.escape(clean_user)}$", "$options": "i"}
            entries_by_key: Dict[str, Tuple[Any, str, str]] = {}

            # 1. Explicit watched_movies on user document
            user_doc = db["users"].find_one({"username": rx_user}, {"watched_movies": 1})
            if user_doc:
                for m in user_doc.get("watched_movies") or []:
                    title = str(m.get("title") or "").strip()
                    if title:
                        entries_by_key[title.lower()] = (
                            m.get("id"),
                            title,
                            str(m.get("poster_url") or ""),
                        )

            # 2. Movies with username in watched_by
            for mdoc in db["movies"].find(
                {"watched_by": rx_user},
                {"_id": 1, "title": 1, "poster_url": 1},
            ):
                title = str(mdoc.get("title") or "").strip()
                if title and title.lower() not in entries_by_key:
                    entries_by_key[title.lower()] = (
                        mdoc.get("_id"),
                        title,
                        str(mdoc.get("poster_url") or ""),
                    )

            # 3. Movies reviewed by user
            for rdoc in db["reviews"].find({"owner.username": rx_user}, {"movie": 1}).sort(
                "created_at", DESCENDING
            ):
                m_obj = rdoc.get("movie") or {}
                title = str(m_obj.get("title") or "").strip()
                if title and title.lower() not in entries_by_key:
                    entries_by_key[title.lower()] = (
                        m_obj.get("id"),
                        title,
                        "",
                    )

            all_items = list(entries_by_key.values())
            total = len(all_items)
            if total == 0:
                return [], 0

            skip = max(0, (max(1, page) - 1) * max(1, page_size))
            page_slice = all_items[skip : skip + max(1, page_size)]
            summaries = [
                self._resolve_movie_summary(db, mid, mtitle, mposter)
                for mid, mtitle, mposter in page_slice
            ]
            return summaries, total
        except Exception:
            return [], 0

    def get_user_lists(self, username: str) -> List[UserListSummary]:
        """
        Retrieves all personal movie lists belonging to `username` by merging
        `mongodb["lists"]` and `mongodb["users"].lists`.
        """
        clean_user = (username or "").strip().lstrip("@")
        if not clean_user:
            return []

        db = self._get_mongo_db()
        if db is None:
            return []

        try:
            rx_user = {"$regex": f"^{re.escape(clean_user)}$", "$options": "i"}
            merged_lists: Dict[str, List[Any]] = {}

            # Dedicated `lists` collection
            for ldoc in db["lists"].find({"owner.username": rx_user}):
                lname = str(ldoc.get("name") or "").strip()
                if not lname:
                    continue
                ldesc = str(ldoc.get("description") or "").strip()
                lkey = lname.lower()
                if lkey not in merged_lists:
                    merged_lists[lkey] = [lname, ldesc, {}]
                elif ldesc and not merged_lists[lkey][1]:
                    merged_lists[lkey][1] = ldesc
                movies_map = merged_lists[lkey][2]
                for m in ldoc.get("movies") or []:
                    mtitle = str(m.get("title") or "").strip()
                    if mtitle and mtitle.lower() not in movies_map:
                        movies_map[mtitle.lower()] = (
                            m.get("id"),
                            mtitle,
                            str(m.get("poster_url") or ""),
                        )

            # Embedded `lists` array in `users` collection
            user_doc = db["users"].find_one({"username": rx_user}, {"lists": 1})
            if user_doc:
                for ulist in user_doc.get("lists") or []:
                    lname = str(ulist.get("name") or "").strip()
                    if not lname:
                        continue
                    ldesc = str(ulist.get("description") or "").strip()
                    lkey = lname.lower()
                    if lkey not in merged_lists:
                        merged_lists[lkey] = [lname, ldesc, {}]
                    elif ldesc and not merged_lists[lkey][1]:
                        merged_lists[lkey][1] = ldesc
                    movies_map = merged_lists[lkey][2]
                    for m in ulist.get("movies") or []:
                        mtitle = str(m.get("title") or "").strip()
                        if mtitle and mtitle.lower() not in movies_map:
                            movies_map[mtitle.lower()] = (
                                m.get("id"),
                                mtitle,
                                str(m.get("poster_url") or ""),
                            )

            result: List[UserListSummary] = []
            for canonical_name, canonical_desc, movies_map in merged_lists.values():
                movies = [
                    self._resolve_movie_summary(db, mid, mtitle, mposter)
                    for mid, mtitle, mposter in movies_map.values()
                ]
                result.append(
                    UserListSummary(
                        name=canonical_name,
                        description=canonical_desc,
                        movies=movies,
                    )
                )
            return result
        except Exception:
            return []

    def get_followers(
        self,
        username: str,
        viewer_username: str = "",
    ) -> List[Dict[str, Any]]:
        """Retrieves the list of accounts that follow `username`."""
        clean_user = (username or "").strip().lstrip("@")
        if not clean_user:
            return []

        db = self._get_mongo_db()
        if db is None:
            return []

        try:
            clean_viewer = (viewer_username or "").strip().lstrip("@")
            viewer_following = (
                {u.lower() for u in self._collect_following_set(db, clean_viewer)}
                if clean_viewer
                else set()
            )
            followers = self._collect_followers_set(db, clean_user)
            rows: List[Dict[str, Any]] = []
            for f_user in followers:
                f_followers = self._collect_followers_set(db, f_user)
                rows.append(
                    {
                        "username": f_user,
                        "followers_count": len(f_followers),
                        "is_following": f_user.lower() in viewer_following,
                    }
                )
            return rows
        except Exception:
            return []

    def get_following(
        self,
        username: str,
        viewer_username: str = "",
    ) -> List[Dict[str, Any]]:
        """Retrieves the list of accounts followed by `username`."""
        clean_user = (username or "").strip().lstrip("@")
        if not clean_user:
            return []

        db = self._get_mongo_db()
        if db is None:
            return []

        try:
            clean_viewer = (viewer_username or "").strip().lstrip("@")
            viewer_following = (
                {u.lower() for u in self._collect_following_set(db, clean_viewer)}
                if clean_viewer
                else set()
            )
            following = self._collect_following_set(db, clean_user)
            rows: List[Dict[str, Any]] = []
            for f_user in following:
                f_followers = self._collect_followers_set(db, f_user)
                rows.append(
                    {
                        "username": f_user,
                        "followers_count": len(f_followers),
                        "is_following": f_user.lower() in viewer_following,
                    }
                )
            return rows
        except Exception:
            return []

    def get_user_movie_status(
        self,
        username: str,
        movie_title: str,
        movie_id: str = "",
    ) -> Dict[str, Any]:
        """
        Returns the persistent interaction state between `username` and a movie:
            - watched (bool)
            - liked (bool)
            - likes_count (int)
            - existing_review (Optional[Dict[str, Any]])
        """
        state: Dict[str, Any] = {
            "watched": False,
            "liked": False,
            "likes_count": 0,
            "existing_review": None,
        }
        clean_user = (username or "").strip().lstrip("@")
        clean_title = (movie_title or "").strip()
        db = self._get_mongo_db()
        if db is None or not clean_title:
            return state

        try:
            movie_doc: Optional[Dict[str, Any]] = None
            if movie_id and ObjectId.is_valid(movie_id):
                movie_doc = db["movies"].find_one({"_id": ObjectId(movie_id)})
            if movie_doc is None:
                movie_doc = db["movies"].find_one(
                    {"title": {"$regex": f"^{re.escape(clean_title)}$", "$options": "i"}}
                )

            if movie_doc is not None:
                state["likes_count"] = int(movie_doc.get("likes") or 0)
                if clean_user:
                    liked_by = {str(u).lower() for u in (movie_doc.get("liked_by") or [])}
                    watched_by = {str(u).lower() for u in (movie_doc.get("watched_by") or [])}
                    if clean_user.lower() in liked_by:
                        state["liked"] = True
                    if clean_user.lower() in watched_by:
                        state["watched"] = True

            if not clean_user:
                return state

            rx_user = {"$regex": f"^{re.escape(clean_user)}$", "$options": "i"}
            rx_title = {"$regex": f"^{re.escape(clean_title)}$", "$options": "i"}

            user_doc = db["users"].find_one(
                {"username": rx_user},
                {"watched_movies": 1, "liked_movies": 1},
            )
            if user_doc:
                watched_titles = {
                    str(m.get("title") or "").lower()
                    for m in (user_doc.get("watched_movies") or [])
                }
                liked_titles = {
                    str(m.get("title") or "").lower()
                    for m in (user_doc.get("liked_movies") or [])
                }
                if clean_title.lower() in watched_titles:
                    state["watched"] = True
                if clean_title.lower() in liked_titles:
                    state["liked"] = True

            rev_doc = db["reviews"].find_one(
                {"owner.username": rx_user, "movie.title": rx_title}
            )
            if rev_doc is not None:
                state["existing_review"] = {
                    "_id": str(rev_doc.get("_id", "")),
                    "rating": float(rev_doc.get("rating") or 5.0),
                    "content": str(rev_doc.get("content") or ""),
                    "likes": int(rev_doc.get("likes") or 0),
                    "liked_by": list(rev_doc.get("liked_by") or []),
                }
        except Exception:
            pass

        return state
