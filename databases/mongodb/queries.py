"""
MongoDB queries repository for MovieVault (backend/databases/mongodb/queries.py).

Implements the official MongoDB queries with a Cache-Aside /
Read-Through strategy to TMDB via `CatalogService` and full utilization
of the indexes defined in `backend/databases/mongodb/schema.py`:
- `actors`: `idx_actors_name`
- `directors`: `idx_directors_name`
- `movies`:
  - `idx_decade_lang_impact`: `[("language.original", 1), ("impact_score", -1), ("decade", 1)]`
  - `idx_genre_impact`: `[("genres", 1), ("impact_score", -1)]`
  - `idx_country_impact`: `[("countries", 1), ("impact_score", -1)]`
  - `idx_rating_director_decade_impact`: `[("rating", 1), ("directors.name", 1), ("decade", 1), ("impact_score", -1)]`
  - `idx_title_synopsis_impact`: `[("title", "text"), ("synopsis", "text"), ("impact_score", -1)]`
  - `idx_cast_name_impact`: `[("cast.name", 1), ("impact_score", -1)]`
  - `idx_directors_name_impact`: `[("directors.name", 1), ("impact_score", -1)]`
  - `idx_impact_score`: `[("impact_score", -1)]`
- `reviews`:
  - `idx_movie_likes_comments`: `[("movie.title", 1), ("likes", -1), ("comments_count", -1)]`
  - `idx_text_review_content`: `[("content", "text")]`
  - `idx_username_created_at`: `[("owner.username", 1), ("created_at", 1)]`
- `users`:
  - `idx_unique_username`: `[("username", 1)]`
  - `idx_unique_email`: `[("email", 1)]`
"""

from collections import Counter
from dataclasses import dataclass, field
import math
import re
from typing import Any, Dict, List, Literal, Optional

from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database

from config import MONGO_DATABASE_NAME, MONGO_URL
from databases.mongodb.connection import MongoConnection
from databases.mongodb.schema import MongoSchema
from services.CatalogService import CatalogService

try:
    global_database: Optional[Database] = MongoConnection.instance(
        MONGO_URL, MONGO_DATABASE_NAME
    ).database
except Exception:
    global_database = None

catalog_service = CatalogService()


@dataclass
class MongoQueryResult:
    """Structured result of a MongoDB query with pagination and source metadata."""

    rows: List[Dict[str, Any]] = field(default_factory=list)
    total: int = 0
    source: str = "mongodb"  # "mongodb" | "tmdb_cached"


class MoviesRepository:
    """
    Repository class for MongoDB movie queries, encapsulating the logic for
    querying movies based on various criteria and handling pagination.
    """

    def __init__(
        self,
        database: Optional[Database] = None,
        catalog_service: Optional[CatalogService] = None,
    ):
        self.database = database
        self.catalog_service = catalog_service or CatalogService()

    def _get_active_database(self, database: Optional[Database] = None) -> Optional[Database]:
        """Resolves the database to use: explicit argument or repository instance."""
        global global_database
        # First, check if an explicit database is provided
        if database is not None:
            return database
        # Next, check if the repository instance has a database
        if self.database is not None:
            return self.database
        # Fallback to the global database instance
        return global_database

    @staticmethod
    def _get_candidate_names(name: str) -> List[str]:
        """Generates a list of candidate names for matching in the database."""
        name = (name or "").strip()
        if not name:
            return []
        return list(dict.fromkeys([name, name.title()]))

    @staticmethod
    def _format_movie(
        document: Dict[str, Any],
        include_synopsis: bool = False,
    ) -> Dict[str, Any]:
        """Formats a MongoDB movie document into a standardized movie dictionary."""
        row: Dict[str, Any] = {
            "movie_title": document.get("title", ""),
            "release_year": int(document.get("release_year") or 0),
            "avg_rating": round(float(document.get("rating") or 0.0), 2),
            "_movie_id": str(document.get("_id", "")),
            "_poster_url": document.get("poster_url", ""),
            "_genres": list(document.get("genres") or []),
        }
        if include_synopsis:
            row["synopsis"] = document.get("synopsis", "")
        return row

    def _find_person(
        self,
        collection_name: Literal["actors", "directors"],
        name: str,
        database: Optional[Database] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Looks up an actor or director using `idx_actors_name` / `idx_directors_name`.
        """
        name = (name or "").strip()
        if not name:
            return None
        active_database = self._get_active_database(database)
        if active_database is None:
            return None

        try:
            collection = active_database[collection_name]
            candidates = self._get_candidate_names(name)

            # Exact index seek on idx_actors_name / idx_directors_name
            for candidate in candidates:
                document = collection.find_one({"name": candidate})
                if document is not None:
                    return document

            # B-tree prefix range scan on idx_actors_name / idx_directors_name
            for prefix in candidates:
                document = collection.find_one(
                    {"name": {"$gte": prefix, "$lt": prefix + "\uffff"}},
                    sort=[("name", ASCENDING)],
                )
                if document is not None:
                    return document

            # Fallback case-insensitive match
            return collection.find_one({"name": {"$regex": re.escape(name), "$options": "i"}})
        except Exception:
            return None

    def _resolve_person(
        self,
        collection_name: Literal["actors", "directors"],
        name: str,
        database: Optional[Database] = None,
    ) -> str:
        """
        Resolves `name` to its canonical `name` stored in `actors` or `directors`.
        """
        document = self._find_person(collection_name, name, database=database)
        if document and document.get("name"):
            return str(document["name"])
        name = (name or "").strip()
        return name.title()

    @staticmethod
    def _genre_filter(self,genre: str) -> Dict[str, Any]:
        """
        Builds an equality / `$in` filter on `genres`.
        """
        genre = (genre or "").strip()
        if not genre:
            return {}
        genre_aliases: Dict[str, List[str]] = {
            "sci-fi": ["Sci-Fi", "Science Fiction"],
            "science fiction": ["Science Fiction", "Sci-Fi"],
            "scifi": ["Sci-Fi", "Science Fiction"],
            "action": ["Action"],
            "adventure": ["Adventure"],
            "animation": ["Animation"],
            "comedy": ["Comedy"],
            "crime": ["Crime"],
            "documentary": ["Documentary"],
            "drama": ["Drama"],
            "family": ["Family"],
            "fantasy": ["Fantasy"],
            "history": ["History"],
            "horror": ["Horror"],
            "music": ["Music"],
            "mystery": ["Mystery"],
            "romance": ["Romance"],
            "thriller": ["Thriller"],
            "war": ["War"],
            "western": ["Western"],
        }
        candidates = genre_aliases.get(
            genre.lower(),
            self._get_candidate_names(genre),
        )
        if len(candidates) == 1:
            return {"genres": candidates[0]}
        return {"genres": {"$in": candidates}}

    @staticmethod
    def _country_filter(self, country: str) -> Dict[str, Any]:
        """
        Builds an equality / `$in` filter on `countries`.
        """
        country = (country or "").strip()
        if not country:
            return {}

        UNITED_STATES_ALIASES = ["United States of America", "United States", "USA", "US"]
        UNITED_KINGDOM_ALIASES = ["United Kingdom", "UK", "GB"]
        MEXICO_ALIASES = ["Mexico", "México", "MX"]
        KOREA_ALIASES = ["South Korea", "Korea", "KR"]
        JAPAN_ALIASES = ["Japan", "JP"]
        FRANCE_ALIASES = ["France", "FR"]
        SPAIN_ALIASES = ["Spain", "España", "ES"]
        CANADA_ALIASES = ["Canada", "CA"]
        GERMANY_ALIASES = ["Germany", "DE"]
        ITALY_ALIASES = ["Italy", "IT"]

        country_aliases: Dict[str, List[str]] = {
            "usa": UNITED_STATES_ALIASES,
            "us": UNITED_STATES_ALIASES,
            "united states": UNITED_STATES_ALIASES,
            "united states of america": UNITED_STATES_ALIASES,
            "uk": UNITED_KINGDOM_ALIASES,
            "united kingdom": UNITED_KINGDOM_ALIASES,
            "gb": UNITED_KINGDOM_ALIASES,
            "mexico": MEXICO_ALIASES,
            "méxico": MEXICO_ALIASES,
            "mx": MEXICO_ALIASES,
            "south korea": KOREA_ALIASES,
            "korea": KOREA_ALIASES,
            "kr": KOREA_ALIASES,
            "japan": JAPAN_ALIASES,
            "jp": JAPAN_ALIASES,
            "france": FRANCE_ALIASES,
            "fr": FRANCE_ALIASES,
            "spain": SPAIN_ALIASES,
            "es": SPAIN_ALIASES,
            "canada": CANADA_ALIASES,
            "germany": GERMANY_ALIASES,
            "italy": ITALY_ALIASES,
        }

        candidates = country_aliases.get(
            country.lower(),
            self._get_candidate_names(country),
        )

        if len(candidates) == 1:
            return {"countries": candidates[0]}
        return {"countries": {"$in": candidates}}

    def _paginated_find(
        self,
        filters: Dict[str, Any],
        page: int,
        page_size: int = 10,
        include_synopsis: bool = False,
        database: Optional[Database] = None,
    ) -> tuple[List[Dict[str, Any]], int]:
        """
        Executes a paginated find query on the MongoDB `movies` collection.
        """
        active_database = self._get_active_database(database)
        if active_database is None:
            return [], 0

        try:
            total = active_database["movies"].count_documents(filters)
            if total == 0:
                return [], 0

            skip = max(0, (page - 1) * page_size)
            projection: Dict[str, Any] = {
                "title": 1,
                "release_year": 1,
                "rating": 1,
                "poster_url": 1,
                "genres": 1,
                "impact_score": 1,
            }
            if include_synopsis:
                projection["synopsis"] = 1

            cursor = (
                active_database["movies"]
                .find(filters, projection)
                .sort("impact_score", DESCENDING)
                .skip(skip)
                .limit(page_size)
            )
            rows = [self._format_movie(document, include_synopsis=include_synopsis) for document in cursor]
            return rows, total
        except Exception:
            return [], 0

    def _resolve_review_movie_title(self, title: str, database: Optional[Database] = None) -> str:
        """
        Resolves `title` to the canonical `movie.title`.
        """
        title = (title or "").strip()
        if not title:
            return ""

        active_database = self._get_active_database(database)
        if active_database is None:
            return title

        try:
            reviews_collection = active_database["reviews"]
            candidates = self._get_candidate_names(title)

            for candidate in candidates:
                document = reviews_collection.find_one(
                    {"movie.title": candidate}, {"movie.title": 1}
                )
                if document and (document.get("movie") or {}).get("title"):
                    return str(document["movie"]["title"])

            for prefix in candidates:
                document = reviews_collection.find_one(
                    {"movie.title": {"$gte": prefix, "$lt": prefix + "\uffff"}},
                    {"movie.title": 1},
                )
                if document and (document.get("movie") or {}).get("title"):
                    return str(document["movie"]["title"])

            movie_document = active_database["movies"].find_one(
                {"$text": {"$search": f'"{title}"'}}, {"title": 1}
            )
            if movie_document and movie_document.get("title"):
                return str(movie_document["title"])
        except Exception:
            pass

        return title

    # ------------------------- QUERIES -------------------------

    def by_title_decade_language(
        self,
        title: str,
        start_decade: int,
        end_decade: int,
        language: str,
        page: int = 1,
        page_size: int = 10,
        database: Optional[Database] = None,
    ) -> MongoQueryResult:
        """Requirement 1: Movies by Title, Decade, and Language."""

        active_database = self._get_active_database(database)
        if active_database is None:
            return MongoQueryResult()

        title = (title or "").strip()
        language = (language or "").strip().lower()

        filters: Dict[str, Any] = {
            "decade": {"$gte": int(start_decade), "$lte": int(end_decade)},
        }
        if language:
            filters["language.original"] = language
        if title:
            filters["$text"] = {"$search": title}

        try:
            rows, total = self._paginated_find(filters, page, page_size, database=active_database)
            source = "mongodb"

            # If no results found, attempt to fetch movies by title from TMDB and cache in MongoDB
            if total == 0 and page == 1 and title:
                added = self.catalog_service.fallback_by_title(
                    active_database, title, limit=page_size
                )

                if added > 0:
                    rows, total = self._paginated_find(
                        filters, page, page_size, database=active_database
                    )

                    if total > 0:
                        source = "tmdb_cached"

            return MongoQueryResult(rows=rows, total=total, source=source)
        except Exception:
            return MongoQueryResult(rows=[], total=0, source="mongodb")

    def by_genre_and_country(
        self,
        genre: str,
        country: str,
        director: str = "",
        page: int = 1,
        page_size: int = 10,
        database: Optional[Database] = None,
    ) -> MongoQueryResult:
        """Requirement 2: Movies by Genre and Country (and optional director)."""

        active_database = self._get_active_database(database)
        if active_database is None:
            return MongoQueryResult()

        genre = (genre or "").strip()
        country = (country or "").strip()
        director = (director or "").strip()

        try:
            def _query_filter() -> Dict[str, Any]:
                query: Dict[str, Any] = {}
                if genre:
                    query.update(self._genre_filter(genre))
                if country:
                    query.update(self._country_filter(country))
                if director:
                    resolved_director = self._resolve_person(
                        "directors", director, database=active_database
                    )
                    query["directors.name"] = resolved_director
                return query

            query_filter = _query_filter()
            rows, total = self._paginated_find(
                query_filter, page, page_size, database=active_database
            )
            source = "mongodb"

            if total == 0 and page == 1 and (genre or country):
                added = self.catalog_service.fallback_by_genre_country(
                    active_database, genre, country, director, limit=page_size
                )

                if added > 0:
                    query_filter = _query_filter()
                    rows, total = self._paginated_find(
                        query_filter, page, page_size, database=active_database
                    )

                    if total > 0:
                        source = "tmdb_cached"

            return MongoQueryResult(rows=rows, total=total, source=source)
        except Exception:
            return MongoQueryResult(rows=[], total=0, source="mongodb")

    def by_rating_director_decade(
        self,
        min_rating: float,
        director: str,
        start_decade: int,
        end_decade: int,
        page: int = 1,
        page_size: int = 10,
        database: Optional[Database] = None,
    ) -> MongoQueryResult:
        """Requirement 3: Movies by Rating, Director, and Decade."""

        active_database = self._get_active_database(database)
        if active_database is None:
            return MongoQueryResult()

        director = (director or "").strip()

        try:
            def _query_filter() -> Dict[str, Any]:
                query: Dict[str, Any] = {
                    "rating": {"$gte": float(min_rating)},
                    "decade": {"$gte": int(start_decade), "$lte": int(end_decade)},
                }
                if director:
                    resolved_director = self._resolve_person(
                        "directors", director, database=active_database
                    )
                    query["directors.name"] = resolved_director
                return query

            query_filter = _query_filter()
            rows, total = self._paginated_find(
                query_filter, page, page_size, database=active_database
            )
            source = "mongodb"

            if total == 0 and page == 1 and director:

                added = self.catalog_service.fallback_by_rating_director_decades(
                    active_database,
                    min_rating=float(min_rating),
                    director=director,
                    start_decade=int(start_decade),
                    end_decade=int(end_decade),
                    limit=page_size,
                )

                if added > 0:
                    query_filter = _query_filter()
                    rows, total = self._paginated_find(
                        query_filter, page, page_size, database=active_database
                    )

                    if total > 0:
                        source = "tmdb_cached"

            return MongoQueryResult(rows=rows, total=total, source=source)
        except Exception:
            return MongoQueryResult(rows=[], total=0, source="mongodb")

    def by_synopsis_keywords(
        self,
        keywords: str,
        page: int = 1,
        page_size: int = 10,
        database: Optional[Database] = None,
    ) -> MongoQueryResult:
        """Requirement 4: Movies by keywords in title/synopsis."""

        active_database = self._get_active_database(database)
        if active_database is None:
            return MongoQueryResult()

        keywords = (keywords or "").strip()
        query_filter: Dict[str, Any] = (
            {"$text": {"$search": keywords}} if keywords else {}
        )

        try:
            rows, total = self._paginated_find(
                query_filter,
                page,
                page_size,
                include_synopsis=True,
                database=active_database,
            )
            source = "mongodb"

            if total == 0 and page == 1 and keywords:
                added = self.catalog_service.fallback_by_synopsis_keywords(
                    active_database, keywords, limit=page_size
                )

                if added > 0:
                    rows, total = self._paginated_find(
                        query_filter,
                        page,
                        page_size,
                        include_synopsis=True,
                        database=active_database,
                    )

                    if total > 0:
                        source = "tmdb_cached"

            return MongoQueryResult(rows=rows, total=total, source=source)
        except Exception:
            return MongoQueryResult(rows=[], total=0, source="mongodb")

    def reviews_by_text_keywords(
        self,
        movie_title: str,
        keywords: str,
        page: int = 1,
        page_size: int = 10,
        database: Optional[Database] = None,
    ) -> MongoQueryResult:
        """Requirement 5: Reviews by text keywords and/or movie title."""

        active_database = self._get_active_database(database)
        if active_database is None:
            return MongoQueryResult()

        movie_title = (movie_title or "").strip()
        keywords = (keywords or "").strip()

        try:
            query_filter: Dict[str, Any] = {}
            if movie_title:
                resolved_title = self._resolve_review_movie_title(movie_title, database=active_database)
                query_filter["movie.title"] = resolved_title
            if keywords:
                query_filter["$text"] = {"$search": keywords}

            total = active_database["reviews"].count_documents(query_filter)
            skip = max(0, (page - 1) * page_size)
            cursor = (
                active_database["reviews"]
                .find(query_filter)
                .sort([("likes", DESCENDING), ("comments_count", DESCENDING)])
                .skip(skip)
                .limit(page_size)
            )

            rows: List[Dict[str, Any]] = []

            for document in cursor:
                created = document.get("created_at")
                created_str = (
                    created.strftime("%Y-%m-%d %H:%M")
                    if hasattr(created, "strftime")
                    else str(created or "")
                )
                rows.append(
                    {
                        "movie_title": (document.get("movie") or {}).get("title", ""),
                        "username": (document.get("owner") or {}).get("username", ""),
                        "rating": round(float(document.get("rating") or 0.0), 1),
                        "likes": int(document.get("likes") or 0),
                        "comments_count": int(document.get("comments_count") or 0),
                        "content": document.get("content", ""),
                        "created_at": created_str,
                        "_review_id": str(document.get("_id", "")),
                        "_liked_by": list(document.get("liked_by") or []),
                    }
                )

            return MongoQueryResult(rows=rows, total=total, source="mongodb")
        except Exception:
            return MongoQueryResult(rows=[], total=0, source="mongodb")

    def by_actor_and_director(
        self,
        actor_name: str,
        director_name: str,
        page: int = 1,
        page_size: int = 10,
        database: Optional[Database] = None,
    ) -> MongoQueryResult:
        """Requirement 6: Movies by Actor and/or Director."""

        active_database = self._get_active_database(database)
        if active_database is None:
            return MongoQueryResult()

        actor = (actor_name or "").strip()
        director = (director_name or "").strip()

        try:
            def _query_filter() -> Dict[str, Any]:
                query: Dict[str, Any] = {}
                if actor:
                    query["cast.name"] = self._resolve_person(
                        "actors", actor, database=active_database
                    )
                if director:
                    query["directors.name"] = self._resolve_person(
                        "directors", director, database=active_database
                    )
                return query

            query_filter = _query_filter()
            rows, total = self._paginated_find(
                query_filter, page, page_size, database=active_database
            )
            source = "mongodb"

            if total == 0 and page == 1 and (actor or director):
                added = self.catalog_service.fallback_by_actor_director(
                    active_database, actor, director, limit=page_size
                )

                if added > 0:
                    query_filter = _query_filter()
                    rows, total = self._paginated_find(
                        query_filter, page, page_size, database=active_database
                    )

                    if total > 0:
                        source = "tmdb_cached"

            return MongoQueryResult(rows=rows, total=total, source=source)
        except Exception:
            return MongoQueryResult(rows=[], total=0, source="mongodb")

    def actor_impact_analysis(
        self,
        actor_name: str,
        database: Optional[Database] = None,
    ) -> MongoQueryResult:
        """Requirement 7: Actor Impact Analysis (Aggregation)."""

        active_database = self._get_active_database(database)
        if active_database is None:
            return MongoQueryResult()

        actor_name = (actor_name or "").strip()
        if not actor_name:
            return MongoQueryResult()

        try:
            actor_document = self._find_person("actors", actor_name, database=active_database)
            resolved_name = (
                str(actor_document["name"])
                if actor_document and actor_document.get("name")
                else self._resolve_person("actors", actor_name, database=active_database)
            )

            match_filter: Dict[str, Any] = {"cast.name": resolved_name}
            source = "mongodb"

            if active_database["movies"].count_documents(match_filter) == 0:
                added = self.catalog_service.fallback_actor_filmography(
                    active_database, actor_name, limit=12
                )

                if added > 0:
                    source = "tmdb_cached"
                    actor_document = self._find_person("actors", actor_name, database=active_database)

                    if actor_document and actor_document.get("name"):
                        resolved_name = str(actor_document["name"])
                        match_filter = {"cast.name": resolved_name}

            pipeline = [
                {"$match": match_filter},
                {"$sort": {"impact_score": DESCENDING}},
                {
                    "$project": {
                        "title": 1,
                        "decade": 1,
                        "genres": 1,
                        "directors": 1,
                        "cast": 1,
                        "rating": 1,
                        "ratings_count": 1,
                        "impact_score": {
                            "$ifNull": [
                                "$impact_score",
                                {
                                    "$multiply": [
                                        "$rating",
                                        {"$log10": {"$add": [1, "$ratings_count"]}},
                                    ]
                                },
                            ]
                        },
                    }
                },
            ]

            documents = list(active_database["movies"].aggregate(pipeline))
            if not documents:
                return MongoQueryResult(rows=[], total=0, source=source)

            is_active = bool(actor_document.get("is_active", True)) if actor_document else True
            total_movies = len(documents)
            avg_impact = round(
                sum(float(d.get("impact_score") or 0.0) for d in documents)
                / max(1, total_movies),
                3,
            )

            decade_counter: Counter[int] = Counter()
            genre_counter: Counter[str] = Counter()
            collaborators_counter: Counter[str] = Counter()

            for document in documents:
                decade = int(document.get("decade") or 0)

                if decade:
                    decade_counter[decade] += 1

                for genre in document.get("genres") or []:
                    if genre:
                        genre_counter[str(genre)] += 1

                for director in document.get("directors") or []:
                    director_name = (director.get("name") or "").strip()

                    if director_name and director_name.lower() != resolved_name.lower():
                        collaborators_counter[f"{director_name} (Dir.)"] += 1

                for cast_member in document.get("cast") or []:
                    cast_member_name = (cast_member.get("name") or "").strip()

                    if cast_member_name and cast_member_name.lower() != resolved_name.lower():
                        collaborators_counter[cast_member_name] += 1

            decade_str = ", ".join(
                f"{decade}s: {count}" for decade, count in sorted(decade_counter.items())
            )
            genre_str = ", ".join(
                f"{genre}: {count}" for genre, count in genre_counter.most_common(5)
            )
            collab_str = ", ".join(
                f"{name} ({count})" for name, count in collaborators_counter.most_common(5)
            )

            row = {
                "actor_name": resolved_name,
                "is_active": is_active,
                "total_movies": total_movies,
                "impact_score": avg_impact,
                "decade_distribution": decade_str or "No data",
                "genre_distribution": genre_str or "No data",
                "collaborators": collab_str or "No registered collaborators",
            }
            return MongoQueryResult(rows=[row], total=1, source=source)
        except Exception:
            return MongoQueryResult(rows=[], total=0, source="mongodb")

    def user_wrapped_statistics(
        self,
        username: str,
        database: Optional[Database] = None,
    ) -> MongoQueryResult:
        """Request 8: User Wrapped Statistics (Aggregation)."""

        active_database = self._get_active_database(database)
        if active_database is None:
            return MongoQueryResult()

        user = (username or "").strip().lstrip("@")
        if not user:
            return MongoQueryResult()

        try:
            user_document = active_database["users"].find_one(
                {"username": user}, {"username": 1}
            )
            resolved_user = (
                str(user_document["username"])
                if user_document and user_document.get("username")
                else user
            )

            pipeline = [
                {"$match": {"owner.username": resolved_user}},
                {"$sort": {"created_at": ASCENDING}},
                {
                    "$lookup": {
                        "from": "movies",
                        "localField": "movie.id",
                        "foreignField": "_id",
                        "as": "movie_doc",
                    }
                },
            ]
            reviews = list(active_database["reviews"].aggregate(pipeline))
            if not reviews:
                empty_row = {
                    "username": resolved_user,
                    "total_reviews": 0,
                    "total_ratings": 0,
                    "top_genres": "No activity yet",
                    "top_actors": "No activity yet",
                    "top_directors": "No activity yet",
                    "avg_likes_per_review": 0.0,
                    "user_impact_score": 0.0,
                }
                return MongoQueryResult(rows=[empty_row], total=1, source="mongodb")

            total_reviews = len(reviews)
            total_ratings = sum(1 for review in reviews if review.get("rating") is not None)
            total_likes = sum(int(review.get("likes") or 0) for review in reviews)
            avg_likes = round(total_likes / max(1, total_reviews), 2)

            genre_counter: Counter[str] = Counter()
            actor_counter: Counter[str] = Counter()
            director_counter: Counter[str] = Counter()

            for review in reviews:
                movie_documents = review.get("movie_doc") or []

                if not movie_documents:
                    movie_title = (review.get("movie") or {}).get("title", "")

                    if movie_title:
                        found = active_database["movies"].find_one(
                            {"$text": {"$search": f'"{movie_title}"'}}
                        )

                        if found:
                            movie_documents = [found]

                for movie in movie_documents:

                    for genre in movie.get("genres") or []:
                        if genre:
                            genre_counter[str(genre)] += 1

                    for actor in (movie.get("cast") or [])[:5]:
                        if actor.get("name"):
                            actor_counter[actor["name"]] += 1

                    for director in movie.get("directors") or []:
                        if director.get("name"):
                            director_counter[director["name"]] += 1

            user_impact = round(
                avg_likes * math.log10(1 + total_reviews) + (total_reviews * 0.5),
                2,
            )

            row = {
                "username": resolved_user,
                "total_reviews": total_reviews,
                "total_ratings": total_ratings,
                "top_genres": ", ".join(genre for genre, _ in genre_counter.most_common(3)) or "N/A",
                "top_actors": ", ".join(actor for actor, _ in actor_counter.most_common(3)) or "N/A",
                "top_directors": ", ".join(director for director, _ in director_counter.most_common(3)) or "N/A",
                "avg_likes_per_review": avg_likes,
                "user_impact_score": user_impact,
            }
            return MongoQueryResult(rows=[row], total=1, source="mongodb")
        except Exception:
            return MongoQueryResult(rows=[], total=0, source="mongodb")


# Default singleton instance
movies_repository = MoviesRepository(database=global_database, catalog_service=catalog_service)


# Module-level convenience functions delegating to default repository
def by_title_decade_language(*args: Any, **kwargs: Any) -> MongoQueryResult:
    return movies_repository.by_title_decade_language(*args, **kwargs)


def by_genre_and_country(*args: Any, **kwargs: Any) -> MongoQueryResult:
    return movies_repository.by_genre_and_country(*args, **kwargs)


def by_rating_director_decade(*args: Any, **kwargs: Any) -> MongoQueryResult:
    return movies_repository.by_rating_director_decade(*args, **kwargs)


def by_synopsis_keywords(*args: Any, **kwargs: Any) -> MongoQueryResult:
    return movies_repository.by_synopsis_keywords(*args, **kwargs)


def reviews_by_text_keywords(*args: Any, **kwargs: Any) -> MongoQueryResult:
    return movies_repository.reviews_by_text_keywords(*args, **kwargs)


def by_actor_and_director(*args: Any, **kwargs: Any) -> MongoQueryResult:
    return movies_repository.by_actor_and_director(*args, **kwargs)


def actor_impact_analysis(*args: Any, **kwargs: Any) -> MongoQueryResult:
    return movies_repository.actor_impact_analysis(*args, **kwargs)


def user_wrapped_statistics(*args: Any, **kwargs: Any) -> MongoQueryResult:
    return movies_repository.user_wrapped_statistics(*args, **kwargs)
