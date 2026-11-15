"""
Multi-database query catalog coordinator for MovieVault
(backend/services/QueryService.py).

Organizes the 24 official requirements into Letterboxd-style sections:
1. Movie & Review Search (MongoDB Reqs 1-6)
2. Talent Impact & Wrapped Stats (MongoDB Reqs 7-8)
3. User Activity & History (Cassandra Reqs 1-8)
4. Discovery & Recommendations (Dgraph Reqs 1-8)

Delegates requirement execution directly to:
- `databases.mongodb.queries`
- `databases.cassandra.queries`
- `databases.dgraph.queries`
"""

from dataclasses import dataclass, field
import json
import time
from typing import Any, Dict, List, Optional

from databases.dgraph.queries import RecommendationsRepository
from databases.cassandra.queries import ActivityRepository
from databases.mongodb.queries import (
    MoviesRepository,
    MongoQueryResult,
)
from databases import MongoConnection, CassandraConnection, DgraphConnection
from services.AuthService import AuthService


class UnifiedDatabaseConnection:
    """Connection hub coordinating MongoDB, Cassandra, and Dgraph connections."""

    _instance: Optional["UnifiedDatabaseConnection"] = None

    @classmethod
    def get_instance(cls) -> "UnifiedDatabaseConnection":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def mongodb(self) -> Any:
        try:
            mongo = MongoConnection()
            return mongo.database if getattr(mongo, "initialized", False) else None
        except Exception:
            return None

    @property
    def cassandra(self) -> Any:
        try:
            cass = CassandraConnection()
            return cass.session if getattr(cass, "initialized", False) else None
        except Exception:
            return None

    @property
    def dgraph(self) -> Any:
        try:
            dg = DgraphConnection()
            return dg.client if getattr(dg, "initialized", False) else None
        except Exception:
            return None

    @property
    def status(self) -> Dict[str, str]:
        return {
            "mongodb": "INITIALIZED" if self.mongodb is not None else "UNINITIALIZED",
            "cassandra": "INITIALIZED" if self.cassandra is not None else "UNINITIALIZED",
            "dgraph": "INITIALIZED" if self.dgraph is not None else "UNINITIALIZED",
        }


@dataclass
class QueryParam:
    """Specification of an input parameter for a query in the TUI."""
    name: str
    label: str
    default: str
    placeholder: str = ""


@dataclass
class QuerySpec:
    """Complete metadata for one of the 24 query requirements."""
    id: str
    req_number: int
    title: str
    database: str  # "MongoDB" | "Cassandra" | "Dgraph"
    module_id: str
    description: str
    params: List[QueryParam] = field(default_factory=list)
    expected_columns: List[str] = field(default_factory=list)
    requires_active_user: bool = False


@dataclass
class QueryResult:
    """Structured result returned after executing a query from the TUI."""
    query_id: str
    title: str
    database: str
    module_id: str
    columns: List[str]
    rows: List[Dict[str, Any]]
    raw_query: str
    query_language: str  # "json" | "sql" | "graphql"
    execution_ms: float
    explanation: str
    is_live: bool = False
    active_username: str = "guest"
    data_source: str = "offline"  # "mongodb" | "tmdb_cached" | "cassandra" | "dgraph" | "offline"
    total_count: int = 0


COLUMN_LABELS: Dict[str, str] = {
    "movie_title": "Title",
    "release_year": "Year",
    "avg_rating": "Rating",
    "rating": "Rating",
    "my_rating": "My Rating",
    "review_rating": "Review Rating",
    "friends_rating": "Friends Rating",
    "synopsis": "Synopsis",
    "username": "Username",
    "likes": "Likes ♥",
    "liked": "Liked",
    "like": "Liked",
    "comments_count": "Comments",
    "content": "Content",
    "review_content": "Review",
    "created_at": "Date",
    "timestamp": "Date",
    "watch_date": "Watch Date",
    "viewed_on": "Platform",
    "actor_name": "Actor / Actress",
    "is_active": "Active",
    "total_movies": "Total Movies",
    "impact_score": "Impact Score",
    "decade_distribution": "Decade Distribution",
    "genre_distribution": "Top Genres",
    "collaborators": "Frequent Collaborators",
    "total_reviews": "Total Reviews",
    "total_ratings": "Total Ratings",
    "top_genres": "Top Genres",
    "top_actors": "Top Actors",
    "top_directors": "Top Directors",
    "avg_likes_per_review": "Avg Likes/Review",
    "user_impact_score": "User Impact Score",
    "review_owner": "Review Author",
    "action": "Action",
    "list_name": "List",
    "film_count": "Films",
    "list_owner": "Creator",
    "followed_username": "Followed Account",
    "followers_count": "Followers",
    "followers": "Followers",
    "views_count": "Watched Films",
    "genre": "Genre",
    "director": "Director",
    "shared_actor": "Shared Actor",
    "shared_movies_count": "Shared Movies",
    "duration_minutes": "Duration (min)",
    "actor": "Actor / Actress",
}


def get_column_label(col_name: str) -> str:
    """Returns readable column label in English."""
    return COLUMN_LABELS.get(col_name, col_name.replace("_", " ").title())


def format_cell_value(col_name: str, val: Any) -> str:
    """Formats cell value for clear and accessible display."""
    if val is None:
        return "—"
    if isinstance(val, bool):
        return "♥ Yes" if val else "No"
    if col_name in ("avg_rating", "rating", "my_rating", "review_rating", "friends_rating"):
        try:
            return f"★ {float(val):.1f}"
        except (ValueError, TypeError):
            return str(val)
    return str(val)


MODULES: List[Dict[str, str]] = [
    {
        "id": "mongo_search",
        "name": "1. Movie & Review Search",
        "subtitle": "MongoDB (Reqs 1-6) • Catalog, Filters, Synopsis & Reviews (Page size 10)",
    },
    {
        "id": "mongo_analytics",
        "name": "2. Talent & Wrapped Stats",
        "subtitle": "MongoDB (Reqs 7-8) • Actor Impact Aggregations & User Profile",
    },
    {
        "id": "cassandra_activity",
        "name": "3. User Activity & History",
        "subtitle": "Apache Cassandra (Reqs 1-8) • Watchlist, Reviews, Likes, Lists & Follows",
    },
    {
        "id": "dgraph_recommendations",
        "name": "4. Recommendations & Discovery",
        "subtitle": "Dgraph (Reqs 1-8) • Suggested Friends & Graph Recommendations",
    },
]


QUERIES: List[QuerySpec] = [
    # ------------- SECTION 1: MOVIE AND REVIEW SEARCH (MONGODB REQS 1-6) -------------
    QuerySpec(
        id="mongo_req_1",
        req_number=1,
        title="Mongo Req 1: Movies by title, decade, and language",
        database="MongoDB",
        module_id="mongo_search",
        description=(
            "Query movies whose titles match the search terms, "
            "filtered by decade range and language, ordered by impact/popularity DESC (10 per page)."
        ),
        params=[
            QueryParam("title", "Title", "Godfather", "Default: Godfather — e.g. Godfather, Inception"),
            QueryParam("start_decade", "Start Decade", "1970", "Default: 1970 — e.g. 1970, 1990"),
            QueryParam("end_decade", "End Decade", "2020", "Default: 2020 — e.g. 2020"),
            QueryParam("language", "Language", "en", "Default: en — e.g. en, es, fr, ko"),
            QueryParam("page", "Page (10/page)", "1", "Default: 1 — e.g. 1"),
        ],
        expected_columns=["movie_title", "release_year", "avg_rating"],
    ),
    QuerySpec(
        id="mongo_req_2",
        req_number=2,
        title="Mongo Req 2: Movies by Genre and Country",
        database="MongoDB",
        module_id="mongo_search",
        description=(
            "Query movies belonging to a particular genre and originating from a specific country "
            "(and optional director), ordered by impact DESC (10 per page)."
        ),
        params=[
            QueryParam("genre", "Genre", "Drama", "Default: Drama — e.g. Drama, Sci-Fi, Crime"),
            QueryParam("country", "Country", "USA", "Default: USA — e.g. USA, Mexico, South Korea"),
            QueryParam("director", "Director (Optional)", "", "Optional (empty = any) — e.g. Alfonso Cuarón"),
            QueryParam("page", "Page (10/page)", "1", "Default: 1 — e.g. 1"),
        ],
        expected_columns=["movie_title", "release_year", "avg_rating"],
    ),
    QuerySpec(
        id="mongo_req_3",
        req_number=3,
        title="Mongo Req 3: Movies by Rating, Director, and Decade",
        database="MongoDB",
        module_id="mongo_search",
        description=(
            "Query movies with average rating >= specified score, directed by a specific director "
            "and produced in a decade range, ordered by impact DESC (10 per page)."
        ),
        params=[
            QueryParam("min_rating", "Min Rating", "4.0", "Default: 4.0 — range 0.5 to 5.0"),
            QueryParam("director", "Director", "Christopher Nolan", "Default: Christopher Nolan — e.g. Christopher Nolan"),
            QueryParam("start_decade", "Start Decade", "2000", "Default: 2000 — e.g. 2000"),
            QueryParam("end_decade", "End Decade", "2020", "Default: 2020 — e.g. 2020"),
            QueryParam("page", "Page (10/page)", "1", "Default: 1 — e.g. 1"),
        ],
        expected_columns=["movie_title", "release_year", "avg_rating"],
    ),
    QuerySpec(
        id="mongo_req_4",
        req_number=4,
        title="Mongo Req 4: Movies by keywords in synopsis",
        database="MongoDB",
        module_id="mongo_search",
        description=(
            "Query movies whose synopses partially include the specified keywords, "
            "ordered by impact DESC (10 per page)."
        ),
        params=[
            QueryParam("keywords", "Synopsis keywords", "dream", "Default: dream — e.g. dream, mafia, space"),
            QueryParam("page", "Page (10/page)", "1", "Default: 1 — e.g. 1"),
        ],
        expected_columns=["movie_title", "release_year", "avg_rating", "synopsis"],
    ),
    QuerySpec(
        id="mongo_req_5",
        req_number=5,
        title="Mongo Req 5: Reviews by keywords in text",
        database="MongoDB",
        module_id="mongo_search",
        description=(
            "Query movie reviews based on keywords in their content, ordered "
            "descending by likes and comments count (10 per page)."
        ),
        params=[
            QueryParam("movie_title", "Movie Title", "Inception", "Default: Inception — e.g. Inception"),
            QueryParam("keywords", "Keywords", "masterpiece", "Default: masterpiece — term in review"),
            QueryParam("page", "Page (10/page)", "1", "Default: 1 — e.g. 1"),
        ],
        expected_columns=[
            "movie_title",
            "username",
            "rating",
            "likes",
            "comments_count",
            "content",
            "created_at",
        ],
    ),
    QuerySpec(
        id="mongo_req_6",
        req_number=6,
        title="Mongo Req 6: Movies by Actor and Director",
        database="MongoDB",
        module_id="mongo_search",
        description=(
            "Query movies featuring a particular actor and/or director, ordered "
            "descending by impact (10 results per page)."
        ),
        params=[
            QueryParam("actor_name", "Actor / Actress", "Leonardo DiCaprio", "Default: Leonardo DiCaprio — e.g. Leonardo DiCaprio"),
            QueryParam("director_name", "Director", "Martin Scorsese", "Default: Martin Scorsese — e.g. Martin Scorsese"),
            QueryParam("page", "Page (10/page)", "1", "Default: 1 — e.g. 1"),
        ],
        expected_columns=["movie_title", "release_year", "avg_rating"],
    ),

    # ------------- SECTION 2: TALENT AND WRAPPED STATISTICS (MONGODB REQS 7–8) -------------
    QuerySpec(
        id="mongo_req_7",
        req_number=7,
        title="Mongo Req 7: Actor Impact Analysis (Aggregation)",
        database="MongoDB",
        module_id="mongo_analytics",
        description=(
            "Detailed analysis per actor: total movies, impact score, "
            "decade distribution, genre distribution, frequent collaborators, and active status."
        ),
        params=[
            QueryParam("actor_name", "Actor / Actress", "Leonardo DiCaprio", "Default: Leonardo DiCaprio — e.g. Leonardo DiCaprio"),
        ],
        expected_columns=[
            "actor_name",
            "is_active",
            "total_movies",
            "impact_score",
            "decade_distribution",
            "genre_distribution",
            "collaborators",
        ],
    ),
    QuerySpec(
        id="mongo_req_8",
        req_number=8,
        title="Mongo Req 8: User Statistics (Wrapped Style)",
        database="MongoDB",
        module_id="mongo_analytics",
        requires_active_user=True,
        description=(
            "Detailed user analysis (Spotify Wrapped style): total reviews, "
            "ratings, favorite genres/actors/directors, average likes per review, and impact."
        ),
        params=[
            QueryParam("username", "Username (empty = active session)", "", "e.g. cinephile_mx"),
        ],
        expected_columns=[
            "username",
            "total_reviews",
            "total_ratings",
            "top_genres",
            "top_actors",
            "top_directors",
            "avg_likes_per_review",
            "user_impact_score",
        ],
    ),

    # ------------- SECTION 3: USER ACTIVITY AND HISTORY (CASSANDRA REQS 1–8) -------------
    QuerySpec(
        id="cassandra_req_1",
        req_number=1,
        title="Cassandra Req 1: User watch history",
        database="Cassandra",
        module_id="cassandra_activity",
        requires_active_user=True,
        description=(
            "Movie watch history of a user in the last 30 days "
            "or optionally within a specific date range, ordered by date DESC."
        ),
        params=[
            QueryParam("username", "Username (empty = active)", "", "Username"),
            QueryParam("start_date", "Start Date (Optional)", "", "Optional: YYYY-MM-DD (default: last 30 days)"),
            QueryParam("end_date", "End Date (Optional)", "", "Optional: YYYY-MM-DD (default: today)"),
        ],
        expected_columns=["watch_date", "movie_title", "my_rating", "liked", "viewed_on"],
    ),
    QuerySpec(
        id="cassandra_req_2",
        req_number=2,
        title="Cassandra Req 2: User watch history filtered by genre",
        database="Cassandra",
        module_id="cassandra_activity",
        requires_active_user=True,
        description=(
            "Movies watched by a user in a specific genre in the last 30 days "
            "or within an inclusive date range, ordered by date DESC."
        ),
        params=[
            QueryParam("username", "Username (empty = active)", "", "Username"),
            QueryParam("genre", "Genre", "Sci-Fi", "Default: Sci-Fi — e.g. Sci-Fi, Drama, Crime"),
            QueryParam("start_date", "Start Date (Optional)", "", "Optional: YYYY-MM-DD (default: last 30 days)"),
            QueryParam("end_date", "End Date (Optional)", "", "Optional: YYYY-MM-DD (default: today)"),
        ],
        expected_columns=["watch_date", "movie_title", "my_rating", "like", "viewed_on"],
    ),
    QuerySpec(
        id="cassandra_req_3",
        req_number=3,
        title="Cassandra Req 3: User review history",
        database="Cassandra",
        module_id="cassandra_activity",
        requires_active_user=True,
        description=(
            "History of reviews written by a user in the last 30 days "
            "or optionally within a date range, ordered by date DESC."
        ),
        params=[
            QueryParam("username", "Username (empty = active)", "", "Username"),
            QueryParam("start_date", "Start Date (Optional)", "", "Optional: YYYY-MM-DD (default: last 30 days)"),
            QueryParam("end_date", "End Date (Optional)", "", "Optional: YYYY-MM-DD (default: today)"),
        ],
        expected_columns=[
            "movie_title",
            "release_year",
            "rating",
            "liked",
            "timestamp",
            "review_content",
        ],
    ),
    QuerySpec(
        id="cassandra_req_4",
        req_number=4,
        title="Cassandra Req 4: User review history by rating",
        database="Cassandra",
        module_id="cassandra_activity",
        requires_active_user=True,
        description=(
            "Reviews written by a user in the last 30 days or date range, "
            "within an inclusive rating range, ordered by date DESC and rating DESC."
        ),
        params=[
            QueryParam("username", "Username (empty = active)", "", "Username"),
            QueryParam("min_rating", "Min Rating", "3.5", "Default: 3.5 — range 0.5 to 5.0"),
            QueryParam("max_rating", "Max Rating", "5.0", "Default: 5.0 — range 0.5 to 5.0"),
            QueryParam("start_date", "Start Date (Optional)", "", "Optional: YYYY-MM-DD (default: last 30 days)"),
            QueryParam("end_date", "End Date (Optional)", "", "Optional: YYYY-MM-DD (default: today)"),
        ],
        expected_columns=[
            "movie_title",
            "release_year",
            "rating",
            "liked",
            "timestamp",
            "review_content",
        ],
    ),
    QuerySpec(
        id="cassandra_req_5",
        req_number=5,
        title="Cassandra Req 5: Movie review history",
        database="Cassandra",
        module_id="cassandra_activity",
        description=(
            "History of all user reviews written for a specific movie, "
            "ordered primarily by date DESC and secondarily by rating DESC."
        ),
        params=[
            QueryParam("movie_title", "Movie Title", "Inception", "Default: Inception — exact movie title"),
        ],
        expected_columns=[
            "movie_title",
            "release_year",
            "rating",
            "username",
            "liked",
            "timestamp",
            "review_content",
        ],
    ),
    QuerySpec(
        id="cassandra_req_6",
        req_number=6,
        title="Cassandra Req 6: Liked reviews history",
        database="Cassandra",
        module_id="cassandra_activity",
        requires_active_user=True,
        description=(
            "History of likes given by a user to reviews by others in the last 30 days "
            "or optionally within a date range, ordered by date DESC."
        ),
        params=[
            QueryParam("username", "Username (empty = active)", "", "Username"),
            QueryParam("start_date", "Start Date (Optional)", "", "Optional: YYYY-MM-DD (default: last 30 days)"),
            QueryParam("end_date", "End Date (Optional)", "", "Optional: YYYY-MM-DD (default: today)"),
        ],
        expected_columns=[
            "username",
            "review_owner",
            "review_rating",
            "liked",
            "movie_title",
            "timestamp",
        ],
    ),
    QuerySpec(
        id="cassandra_req_7",
        req_number=7,
        title="Cassandra Req 7: List activity history",
        database="Cassandra",
        module_id="cassandra_activity",
        requires_active_user=True,
        description=(
            "User activity history regarding lists (creation, update, "
            "or like) in the last 30 days or date range, ordered by date DESC."
        ),
        params=[
            QueryParam("username", "Username (empty = active)", "", "Username"),
            QueryParam("start_date", "Start Date (Optional)", "", "Optional: YYYY-MM-DD (default: last 30 days)"),
            QueryParam("end_date", "End Date (Optional)", "", "Optional: YYYY-MM-DD (default: today)"),
        ],
        expected_columns=[
            "username",
            "action",
            "content",
            "list_name",
            "timestamp",
            "film_count",
            "list_owner",
            "likes",
        ],
    ),
    QuerySpec(
        id="cassandra_req_8",
        req_number=8,
        title="Cassandra Req 8: Followed accounts history",
        database="Cassandra",
        module_id="cassandra_activity",
        requires_active_user=True,
        description=(
            "History of accounts followed by a user in the last 30 days or optionally "
            "in a date range, ordered by date DESC and follower count DESC."
        ),
        params=[
            QueryParam("username", "Username (empty = active)", "", "Username"),
            QueryParam("start_date", "Start Date (Optional)", "", "Optional: YYYY-MM-DD (default: last 30 days)"),
            QueryParam("end_date", "End Date (Optional)", "", "Optional: YYYY-MM-DD (default: today)"),
        ],
        expected_columns=[
            "username",
            "followed_username",
            "followers_count",
            "timestamp",
        ],
    ),

    # ------------- SECTION 4: RECOMMENDATIONS AND DISCOVERY (DGRAPH REQS 1–8) -------------
    QuerySpec(
        id="dgraph_req_1",
        req_number=1,
        title="Dgraph Req 1: Recommended users who liked my review",
        database="Dgraph",
        module_id="dgraph_recommendations",
        requires_active_user=True,
        description=(
            "Recommends up to 10 users to add as friends who liked "
            "reviews on the user's favorite movie, ordered by followers and views DESC."
        ),
        params=[
            QueryParam("username", "Username (empty = active)", "", "Username"),
            QueryParam("favorite_movie_title", "Favorite Movie", "Inception", "Default: Inception — e.g. Inception"),
        ],
        expected_columns=["username", "followers", "views_count"],
    ),
    QuerySpec(
        id="dgraph_req_2",
        req_number=2,
        title="Dgraph Req 2: Movies watched by friends (last 7 days)",
        database="Dgraph",
        module_id="dgraph_recommendations",
        requires_active_user=True,
        description=(
            "Recommends movies watched by friends of the user in the last 7 days with "
            "rating >= filter, ordered by rating DESC and title ASC."
        ),
        params=[
            QueryParam("username", "Username (empty = active)", "", "Username"),
            QueryParam("min_rating", "Min Rating", "4.0", "Default: 4.0 — range 0.5 to 5.0"),
        ],
        expected_columns=["movie_title", "release_year", "friends_rating"],
    ),
    QuerySpec(
        id="dgraph_req_3",
        req_number=3,
        title="Dgraph Req 3: Same-genre movies not in personal list",
        database="Dgraph",
        module_id="dgraph_recommendations",
        requires_active_user=True,
        description=(
            "Recommends up to 10 movies of the same genre as a movie selected from "
            "a personal list, that are not yet in that list, ordered by impact DESC."
        ),
        params=[
            QueryParam("username", "Username (empty = active)", "", "Username"),
            QueryParam("list_name", "Personal List", "Watchlist", "Default: Watchlist — your list name"),
            QueryParam("selected_movie_title", "Movie in List", "Interstellar", "Default: Interstellar — base movie title"),
        ],
        expected_columns=["movie_title", "release_year", "genre", "impact_score"],
    ),
    QuerySpec(
        id="dgraph_req_4",
        req_number=4,
        title="Dgraph Req 4: Movies liked by friends (same director)",
        database="Dgraph",
        module_id="dgraph_recommendations",
        requires_active_user=True,
        description=(
            "Recommends up to 5 movies liked by friends, unwatched by the user, "
            "whose director also directed another movie liked by the user (by impact DESC)."
        ),
        params=[
            QueryParam("username", "Username (empty = active)", "", "Username"),
        ],
        expected_columns=["movie_title", "release_year", "director", "impact_score"],
    ),
    QuerySpec(
        id="dgraph_req_5",
        req_number=5,
        title="Dgraph Req 5: Movies with actor from liked movie",
        database="Dgraph",
        module_id="dgraph_recommendations",
        requires_active_user=True,
        description=(
            "Recommends up to 5 unwatched movies not in the specified list that feature "
            "an actor from a movie the user watched and liked (by impact DESC)."
        ),
        params=[
            QueryParam("username", "Username (empty = active)", "", "Username"),
            QueryParam("list_name", "List to exclude", "Watchlist", "Default: Watchlist — personal list name"),
        ],
        expected_columns=["movie_title", "release_year", "shared_actor", "impact_score"],
    ),
    QuerySpec(
        id="dgraph_req_6",
        req_number=6,
        title="Dgraph Req 6: Potential friends with shared tastes (>=5 movies)",
        database="Dgraph",
        module_id="dgraph_recommendations",
        requires_active_user=True,
        description=(
            "Recommends up to 10 potential friends who rated >= 4 stars at least "
            "5 movies that the user also rated >= 4 stars (by followers and views DESC)."
        ),
        params=[
            QueryParam("username", "Username (empty = active)", "", "Username"),
            QueryParam("min_rating", "Min Rating", "4.0", "Default: 4.0 — range 0.5 to 5.0"),
            QueryParam("min_shared_movies", "Min Shared Movies", "5", "Default: 5 — e.g. 5"),
        ],
        expected_columns=["username", "followers", "views_count", "shared_movies_count"],
    ),
    QuerySpec(
        id="dgraph_req_7",
        req_number=7,
        title="Dgraph Req 7: Unwatched movies in own list liked by friends",
        database="Dgraph",
        module_id="dgraph_recommendations",
        requires_active_user=True,
        description=(
            "Recommends movies in a selected personal list, not yet watched by "
            "the user but liked by friends, ordered by impact DESC."
        ),
        params=[
            QueryParam("username", "Username (empty = active)", "", "Username"),
            QueryParam("list_name", "Personal List", "Watchlist", "Default: Watchlist — your list name"),
        ],
        expected_columns=["movie_title", "release_year", "duration_minutes", "avg_rating"],
    ),
    QuerySpec(
        id="dgraph_req_8",
        req_number=8,
        title="Dgraph Req 8: Movies by Actor+Director combo (liked in last 7 days)",
        database="Dgraph",
        module_id="dgraph_recommendations",
        requires_active_user=True,
        description=(
            "Recommends up to 5 movies sharing the same actor and director combination "
            "found in another movie liked by the user in the last 7 days (by impact DESC)."
        ),
        params=[
            QueryParam("username", "Username (empty = active)", "", "Username"),
        ],
        expected_columns=["movie_title", "release_year", "actor", "director", "impact_score"],
    ),
]


def get_modules() -> List[Dict[str, str]]:
    """Return the list of main application modules."""
    return MODULES


def get_queries_by_module(module_id: str) -> List[QuerySpec]:
    """Return the query specifications belonging to a module."""
    return [q for q in QUERIES if q.module_id == module_id]


def get_query_by_id(query_id: str) -> Optional[QuerySpec]:
    """Look up a QuerySpec by its unique identifier."""
    for q in QUERIES:
        if q.id == query_id:
            return q
    return None


def _parse_int(value: Optional[str], default: int) -> int:
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return default


def _parse_float(value: Optional[str], default: float) -> float:
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return default


def execute_query(query_id: str, params: Dict[str, str]) -> QueryResult:
    """
    Executes the requested requirement by delegating to the corresponding module
    (`mongo_queries.py`, `cassandra_queries.py`, or `dgraph_queries.py`).
    """
    spec = get_query_by_id(query_id)
    if spec is None:
        raise ValueError(f"Unknown requirement: {query_id}")

    t0 = time.perf_counter()
    auth = AuthService()
    session_user = auth.current_session.username if auth.current_session else "guest"

    # If username param is empty, fallback to active session user
    effective_username = (params.get("username") or "").strip() or session_user

    rows: List[Dict[str, Any]] = []
    total_count: int = 0
    mongo_source: str = "mongodb"
    is_live = False
    query_language = "json"
    raw_query = ""

    # -------------------------- MONGODB (Reqs 1–8) --------------------------
    if spec.database == "MongoDB":
        db = None
        try:
            hub = UnifiedDatabaseConnection.get_instance()
            if hub and getattr(hub, "status", {}).get("mongodb") == "INITIALIZED":
                db = hub.mongodb
        except Exception:
            pass
        if db is None:
            try:
                mongo = MongoConnection()
                db = mongo.database if mongo.initialized else None
            except Exception:
                db = None

        is_live = db is not None
        query_language = "json"
        page = max(1, _parse_int(params.get("page"), 1))
        movies_repo = MoviesRepository(database=db)
        m_res: Optional[MongoQueryResult] = None

        if query_id == "mongo_req_1":
            m_res = movies_repo.by_title_decade_language(
                title=params.get("title", ""),
                start_decade=_parse_int(params.get("start_decade"), 1970),
                end_decade=_parse_int(params.get("end_decade"), 2020),
                language=params.get("language", "en"),
                page=page,
                page_size=10,
                database=db,
            )
            raw_query = json.dumps(
                {
                    "repository": "MoviesRepository.by_title_decade_language",
                    "collection": "movies",
                    "index": "idx_title_synopsis_impact / idx_decade_lang_impact",
                    "params": {
                        "title": params.get("title", ""),
                        "start_decade": _parse_int(params.get("start_decade"), 1970),
                        "end_decade": _parse_int(params.get("end_decade"), 2020),
                        "language": params.get("language", "en"),
                        "page": page,
                        "page_size": 10,
                    },
                },
                indent=2,
                ensure_ascii=False,
            )

        elif query_id == "mongo_req_2":
            m_res = movies_repo.by_genre_and_country(
                genre=params.get("genre", ""),
                country=params.get("country", ""),
                director=params.get("director", ""),
                page=page,
                page_size=10,
                database=db,
            )
            raw_query = json.dumps(
                {
                    "repository": "MoviesRepository.by_genre_and_country",
                    "collection": "movies",
                    "index": "idx_genre_impact / idx_country_impact / idx_directors_name_impact",
                    "params": {
                        "genre": params.get("genre", ""),
                        "country": params.get("country", ""),
                        "director": params.get("director", ""),
                        "page": page,
                        "page_size": 10,
                    },
                },
                indent=2,
                ensure_ascii=False,
            )

        elif query_id == "mongo_req_3":
            m_res = movies_repo.by_rating_director_decade(
                min_rating=_parse_float(params.get("min_rating"), 4.0),
                director=params.get("director", ""),
                start_decade=_parse_int(params.get("start_decade"), 2000),
                end_decade=_parse_int(params.get("end_decade"), 2020),
                page=page,
                page_size=10,
                database=db,
            )
            raw_query = json.dumps(
                {
                    "repository": "MoviesRepository.by_rating_director_decade",
                    "collection": "movies",
                    "index": "idx_rating_director_decade_impact / idx_directors_name_impact",
                    "params": {
                        "min_rating": _parse_float(params.get("min_rating"), 4.0),
                        "director": params.get("director", ""),
                        "start_decade": _parse_int(params.get("start_decade"), 2000),
                        "end_decade": _parse_int(params.get("end_decade"), 2020),
                        "page": page,
                        "page_size": 10,
                    },
                },
                indent=2,
                ensure_ascii=False,
            )

        elif query_id == "mongo_req_4":
            m_res = movies_repo.by_synopsis_keywords(
                keywords=params.get("keywords", ""),
                page=page,
                page_size=10,
                database=db,
            )
            raw_query = json.dumps(
                {
                    "repository": "MoviesRepository.by_synopsis_keywords",
                    "collection": "movies",
                    "index": "idx_title_synopsis_impact",
                    "params": {
                        "keywords": params.get("keywords", ""),
                        "page": page,
                        "page_size": 10,
                    },
                },
                indent=2,
                ensure_ascii=False,
            )

        elif query_id == "mongo_req_5":
            m_res = movies_repo.reviews_by_text_keywords(
                movie_title=params.get("movie_title", ""),
                keywords=params.get("keywords", ""),
                page=page,
                page_size=10,
                database=db,
            )
            raw_query = json.dumps(
                {
                    "repository": "MoviesRepository.reviews_by_text_keywords",
                    "collection": "reviews",
                    "index": "idx_movie_likes_comments / idx_text_review_content",
                    "params": {
                        "movie_title": params.get("movie_title", ""),
                        "keywords": params.get("keywords", ""),
                        "page": page,
                        "page_size": 10,
                    },
                },
                indent=2,
                ensure_ascii=False,
            )

        elif query_id == "mongo_req_6":
            m_res = movies_repo.by_actor_and_director(
                actor_name=params.get("actor_name", ""),
                director_name=params.get("director_name", ""),
                page=page,
                page_size=10,
                database=db,
            )
            raw_query = json.dumps(
                {
                    "repository": "MoviesRepository.by_actor_and_director",
                    "collection": "movies",
                    "index": "idx_cast_name_impact / idx_directors_name_impact",
                    "params": {
                        "actor_name": params.get("actor_name", ""),
                        "director_name": params.get("director_name", ""),
                        "page": page,
                        "page_size": 10,
                    },
                },
                indent=2,
                ensure_ascii=False,
            )

        elif query_id == "mongo_req_7":
            m_res = movies_repo.actor_impact_analysis(
                actor_name=params.get("actor_name", ""),
                database=db,
            )
            raw_query = json.dumps(
                {
                    "repository": "MoviesRepository.actor_impact_analysis",
                    "collections": ["movies", "actors"],
                    "index": "idx_actors_name / idx_cast_name_impact",
                    "params": {"actor_name": params.get("actor_name", "")},
                },
                indent=2,
                ensure_ascii=False,
            )

        elif query_id == "mongo_req_8":
            m_res = movies_repo.user_wrapped_statistics(
                username=effective_username,
                database=db,
            )
            raw_query = json.dumps(
                {
                    "repository": "MoviesRepository.user_wrapped_statistics",
                    "collections": ["reviews", "movies", "users"],
                    "index": "idx_username_created_at / idx_unique_username",
                    "params": {"username": effective_username},
                },
                indent=2,
                ensure_ascii=False,
            )

        if m_res is not None:
            rows = m_res.rows
            total_count = m_res.total
            mongo_source = m_res.source

    # -------------------------- CASSANDRA (Reqs 1–8) --------------------------
    elif spec.database == "Cassandra":
        session = None
        try:
            hub = UnifiedDatabaseConnection.get_instance()
            if hub and getattr(hub, "status", {}).get("cassandra") == "INITIALIZED":
                session = hub.cassandra
        except Exception:
            pass
        if session is None:
            try:
                cass = CassandraConnection()
                session = cass.session if cass.initialized else None
            except Exception:
                session = None

        is_live = session is not None
        query_language = "sql"
        start_date = params.get("start_date", "").strip() or None
        end_date = params.get("end_date", "").strip() or None
        activity_repo = ActivityRepository(session=session)

        if query_id == "cassandra_req_1":
            rows = activity_repo.watch_history(
                username=effective_username,
                start_date=start_date,
                end_date=end_date,
            )
            raw_query = (
                f"-- ActivityRepository.watch_history\n"
                f"-- username={effective_username!r}, start_date={start_date!r}, end_date={end_date!r}"
            )

        elif query_id == "cassandra_req_2":
            rows = activity_repo.watch_history_by_genre(
                username=effective_username,
                genre=params.get("genre", ""),
                start_date=start_date,
                end_date=end_date,
            )
            raw_query = (
                f"-- ActivityRepository.watch_history_by_genre\n"
                f"-- username={effective_username!r}, genre={params.get('genre', '')!r}, "
                f"start_date={start_date!r}, end_date={end_date!r}"
            )

        elif query_id == "cassandra_req_3":
            rows = activity_repo.reviews_history(
                username=effective_username,
                start_date=start_date,
                end_date=end_date,
            )
            raw_query = (
                f"-- ActivityRepository.reviews_history\n"
                f"-- username={effective_username!r}, start_date={start_date!r}, end_date={end_date!r}"
            )

        elif query_id == "cassandra_req_4":
            rows = activity_repo.reviews_history_by_rating(
                username=effective_username,
                min_rating=_parse_float(params.get("min_rating"), 3.5),
                max_rating=_parse_float(params.get("max_rating"), 5.0),
                start_date=start_date,
                end_date=end_date,
            )
            raw_query = (
                f"-- ActivityRepository.reviews_history_by_rating\n"
                f"-- username={effective_username!r}, min_rating={params.get('min_rating')}, "
                f"max_rating={params.get('max_rating')}, start_date={start_date!r}, end_date={end_date!r}"
            )

        elif query_id == "cassandra_req_5":
            rows = activity_repo.movie_reviews_history(
                movie_title=params.get("movie_title", ""),
            )
            raw_query = (
                f"-- ActivityRepository.movie_reviews_history\n"
                f"-- movie_title={params.get('movie_title', '')!r}"
            )

        elif query_id == "cassandra_req_6":
            rows = activity_repo.liked_reviews_history(
                username=effective_username,
                start_date=start_date,
                end_date=end_date,
            )
            raw_query = (
                f"-- ActivityRepository.liked_reviews_history\n"
                f"-- username={effective_username!r}, start_date={start_date!r}, end_date={end_date!r}"
            )

        elif query_id == "cassandra_req_7":
            rows = activity_repo.list_activity_history(
                username=effective_username,
                start_date=start_date,
                end_date=end_date,
            )
            raw_query = (
                f"-- ActivityRepository.list_activity_history\n"
                f"-- username={effective_username!r}, start_date={start_date!r}, end_date={end_date!r}"
            )

        elif query_id == "cassandra_req_8":
            rows = activity_repo.followed_accounts_history(
                username=effective_username,
                start_date=start_date,
                end_date=end_date,
            )
            raw_query = (
                f"-- ActivityRepository.followed_accounts_history\n"
                f"-- username={effective_username!r}, start_date={start_date!r}, end_date={end_date!r}"
            )

    # -------------------------- DGRAPH (Reqs 1–8) --------------------------
    elif spec.database == "Dgraph":
        client = None
        try:
            hub = UnifiedDatabaseConnection.get_instance()
            if hub and getattr(hub, "status", {}).get("dgraph") == "INITIALIZED":
                client = hub.dgraph
        except Exception:
            pass
        if client is None:
            try:
                dgraph = DgraphConnection()
                client = dgraph.client if dgraph.initialized else None
            except Exception:
                client = None

        is_live = client is not None
        query_language = "graphql"
        recs_repo = RecommendationsRepository(client=client)

        if query_id == "dgraph_req_1":
            rows = recs_repo.users_who_liked_my_review(
                username=effective_username,
                favorite_movie_title=params.get("favorite_movie_title", ""),
            )
            raw_query = (
                f"# RecommendationsRepository.users_who_liked_my_review\n"
                f"# username={effective_username!r}, favorite_movie_title={params.get('favorite_movie_title', '')!r}"
            )

        elif query_id == "dgraph_req_2":
            rows = recs_repo.movies_watched_by_friends(
                username=effective_username,
                min_rating=_parse_float(params.get("min_rating"), 4.0),
            )
            raw_query = (
                f"# RecommendationsRepository.movies_watched_by_friends\n"
                f"# username={effective_username!r}, min_rating={params.get('min_rating', '4.0')}"
            )

        elif query_id == "dgraph_req_3":
            rows = recs_repo.same_genre_not_in_personal_list(
                username=effective_username,
                list_name=params.get("list_name", ""),
                selected_movie_title=params.get("selected_movie_title", ""),
            )
            raw_query = (
                f"# RecommendationsRepository.same_genre_not_in_personal_list\n"
                f"# username={effective_username!r}, list_name={params.get('list_name', '')!r}, "
                f"selected_movie_title={params.get('selected_movie_title', '')!r}"
            )

        elif query_id == "dgraph_req_4":
            rows = recs_repo.movies_liked_by_friends_same_director(
                username=effective_username,
            )
            raw_query = (
                f"# RecommendationsRepository.movies_liked_by_friends_same_director\n"
                f"# username={effective_username!r}"
            )

        elif query_id == "dgraph_req_5":
            rows = recs_repo.movies_sharing_actor_with_liked_movie(
                username=effective_username,
                list_name=params.get("list_name", ""),
            )
            raw_query = (
                f"# RecommendationsRepository.movies_sharing_actor_with_liked_movie\n"
                f"# username={effective_username!r}, list_name={params.get('list_name', '')!r}"
            )

        elif query_id == "dgraph_req_6":
            rows = recs_repo.friends_by_shared_taste(
                username=effective_username,
                min_rating=_parse_float(params.get("min_rating"), 4.0),
                min_shared_movies=_parse_int(params.get("min_shared_movies"), 5),
            )
            raw_query = (
                f"# RecommendationsRepository.friends_by_shared_taste\n"
                f"# username={effective_username!r}, min_rating={params.get('min_rating', '4.0')}, "
                f"min_shared_movies={params.get('min_shared_movies', '5')}"
            )

        elif query_id == "dgraph_req_7":
            rows = recs_repo.movies_in_own_list_liked_by_friends(
                username=effective_username,
                list_name=params.get("list_name", ""),
            )
            raw_query = (
                f"# RecommendationsRepository.movies_in_own_list_liked_by_friends\n"
                f"# username={effective_username!r}, list_name={params.get('list_name', '')!r}"
            )

        elif query_id == "dgraph_req_8":
            rows = recs_repo.movies_by_recent_actor_director_combo(
                username=effective_username,
            )
            raw_query = (
                f"# RecommendationsRepository.movies_by_recent_actor_director_combo\n"
                f"# username={effective_username!r}"
            )

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    if rows:
        columns = [k for k in rows[0].keys() if not str(k).startswith("_")]
    else:
        columns = list(spec.expected_columns)

    if total_count == 0 and rows:
        total_count = len(rows)

    if not is_live:
        data_source = "offline"
    elif spec.database == "MongoDB":
        data_source = mongo_source
    elif spec.database == "Cassandra":
        data_source = "cassandra"
    else:
        data_source = "dgraph"

    return QueryResult(
        query_id=spec.id,
        title=spec.title,
        database=spec.database,
        module_id=spec.module_id,
        columns=columns,
        rows=rows,
        raw_query=raw_query,
        query_language=query_language,
        execution_ms=elapsed_ms,
        explanation=spec.description,
        is_live=is_live,
        active_username=effective_username,
        data_source=data_source,
        total_count=total_count,
    )


def execute_raw_query(engine: str, query_text: str) -> Dict[str, Any]:
    """
    Executes an ad-hoc query from the Admin Panel interactive console.

    Supports:
    - MongoDB: JSON with `collection`, `filter` (or `pipeline`), `limit`
    - Cassandra: Direct CQL statement (`SELECT ...`)
    - Dgraph: DQL block (`{ q(func: ...) { ... } }`)
    """
    t0 = time.perf_counter()
    clean_query = (query_text or "").strip()

    if not clean_query:
        return {
            "ok": False,
            "error": "Query cannot be empty.",
            "rows": [],
            "execution_ms": 0.0,
        }

    try:
        if engine == "MongoDB":
            try:
                mongo = MongoConnection()
                db = mongo.database if mongo.initialized else None
            except Exception:
                db = None
            if db is None:
                return {
                    "ok": False,
                    "error": "MongoDB is not connected.",
                    "rows": [],
                    "execution_ms": 0.0,
                }
            payload = json.loads(clean_query)
            col_name = payload.get("collection", "movies")
            collection = db[col_name]

            if "pipeline" in payload:
                docs = list(collection.aggregate(payload["pipeline"]))
            else:
                flt = payload.get("filter", {})
                proj = payload.get("projection")
                limit = int(payload.get("limit", 10))
                cursor = collection.find(flt, proj)
                if "sort" in payload and isinstance(payload["sort"], list):
                    cursor = cursor.sort([(k, int(v)) for k, v in payload["sort"]])
                docs = list(cursor.limit(limit))

            for d in docs:
                if "_id" in d:
                    d["_id"] = str(d["_id"])
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            return {
                "ok": True,
                "error": "",
                "rows": docs,
                "execution_ms": elapsed_ms,
            }

        elif engine == "Cassandra":
            try:
                cass = CassandraConnection()
                session = cass.session if cass.initialized else None
            except Exception:
                session = None
            if session is None:
                return {
                    "ok": False,
                    "error": "Cassandra is not connected.",
                    "rows": [],
                    "execution_ms": 0.0,
                }
            rs = session.execute(clean_query)
            docs = [dict(row._asdict()) if hasattr(row, "_asdict") else {"value": str(row)} for row in rs]
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            return {
                "ok": True,
                "error": "",
                "rows": docs,
                "execution_ms": elapsed_ms,
            }

        elif engine == "Dgraph":
            try:
                dg = DgraphConnection()
                client = dg.client if dg.initialized else None
            except Exception:
                client = None
            if client is None:
                return {
                    "ok": False,
                    "error": "Dgraph is not connected.",
                    "rows": [],
                    "execution_ms": 0.0,
                }
            txn = client.txn(read_only=True)
            try:
                resp = txn.query(clean_query)
                data = json.loads(resp.json.decode("utf-8"))
            finally:
                txn.discard()

            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            return {
                "ok": True,
                "error": "",
                "rows": [data] if isinstance(data, dict) else data,
                "execution_ms": elapsed_ms,
            }

        return {
            "ok": False,
            "error": f"Unsupported engine: {engine}",
            "rows": [],
            "execution_ms": 0.0,
        }
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        return {
            "ok": False,
            "error": str(exc),
            "rows": [],
            "execution_ms": elapsed_ms,
        }
