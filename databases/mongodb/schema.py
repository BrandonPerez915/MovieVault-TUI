"""
Schema and index initialization module for MongoDB in MovieVault.
Defines JSON Schema validators for dedicated collections ('movies', 'reviews',
'users', 'actors', 'directors', and 'lists') with foreign key references (ObjectId),
ensuring relational integrity in a document-based architecture.
"""

from typing import Any, Dict, Optional
from pymongo import ASCENDING, DESCENDING, TEXT
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import OperationFailure

from databases.mongodb.connection import MongoConnection
from databases.mongodb.validators import (
    ACTORS_VALIDATOR,
    DIRECTORS_VALIDATOR,
    LISTS_VALIDATOR,
    MOVIES_VALIDATOR,
    REVIEWS_VALIDATOR,
    USERS_VALIDATOR,
)


class MongoSchema:
    """
    Provides methods to create collections with validation and to establish
    indexes that optimize query performance across the MovieVault application.
    """

    def __new__(cls):
        raise NotImplementedError(
            "MongoSchema is a static utility class and cannot be instantiated."
        )

    def __init__(self):
        raise NotImplementedError(
            "MongoSchema is a static utility class and cannot be instantiated."
        )

    @staticmethod
    def create_collection(
        database: Database,
        name: str,
        validator: Dict[str, Any],
    ) -> None:
        """Creates a collection with a JSON Schema validator or updates it if it already exists."""
        collections = database.list_collection_names()
        if name not in collections:
            database.create_collection(name, validator=validator)
        else:
            database.command(
                "collMod",
                name,
                validator=validator,
                validationLevel="moderate",
            )

    @staticmethod
    def _ensure_single_text_index(
        collection: Collection,
        keys: list,
        name: str,
        **kwargs: Any,
    ) -> None:
        """
        Ensures the target text index exists on `collection`.
        MongoDB allows at most one text index per collection; if a legacy or
        conflicting text index exists (e.g. with a different name or without
        `language_override`), it is dropped first before creating `name`.
        """
        try:
            existing_indexes = collection.index_information()

            for index_name, index_info in existing_indexes.items():
                index_fields = index_info.get("key", [])

                # If any _fts (full-text search) or any index with type "text" exists, check conflicts
                is_text_index = any(
                    index_field == "_fts" or
                    index_type == "text"
                    for index_field, index_type in index_fields
                )

                if is_text_index and (
                    index_name != name
                    or index_info.get("language_override") != kwargs.get("language_override", "language")
                ):
                    try:
                        collection.drop_index(index_name)
                    except Exception:
                        pass
            collection.create_index(keys, name=name, **kwargs)
        except OperationFailure:
            # Fallback: if an IndexOptionsConflict still occurs, drop conflicting text indexes and retry
            try:
                for index_name, index_info in collection.index_information().items():
                    index_fields = index_info.get("key", [])

                    is_text_index = any(
                        index_field == "_fts" or
                        index_type == "text"
                        for index_field, index_type in index_fields
                    )

                    if is_text_index:
                        collection.drop_index(index_name)

                collection.create_index(keys, name=name, **kwargs)
            except Exception:
                pass

    @staticmethod
    def create_indexes(database: Database) -> None:
        """
        Creates optimal indexes in MongoDB to satisfy the requirements across collections:
        - actors: index on name (`idx_actors_name`)
        - directors: index on name (`idx_directors_name`)
        - movies:
            compound indexes for language.original/impact_score/decade (`idx_decade_lang_impact`),
            genres/impact_score (`idx_genre_impact`), countries/impact_score (`idx_country_impact`),
            rating/directors.name/decade/impact_score (`idx_rating_director_decade_impact`),
            text index on title + synopsis + impact_score (`idx_title_synopsis_impact`),
            cast.name/impact_score (`idx_cast_name_impact`),
            directors.name/impact_score (`idx_directors_name_impact`),
            and single-field index on impact_score (`idx_impact_score`).
        - reviews:
            movie.title/likes/comments_count (`idx_movie_likes_comments`),
            text index on content (`idx_text_review_content`),
            and owner.username/created_at (`idx_username_created_at`).
        - users:
            unique indexes on username (`idx_unique_username`) and email (`idx_unique_email`).
        """
        # INDEXES FOR 'actors' COLLECTION
        actors = database["actors"]
        actors.create_index([("name", ASCENDING)], name="idx_actors_name")

        # INDEXES FOR 'directors' COLLECTION
        directors = database["directors"]
        directors.create_index([("name", ASCENDING)], name="idx_directors_name")

        # INDEXES FOR 'movies' COLLECTION
        movies = database["movies"]

        # Requirement 1: Search by decade range and language, sorted by impact
        movies.create_index(
            [
                ("language.original", ASCENDING),
                ("impact_score", DESCENDING),
                ("decade", ASCENDING),
            ],
            name="idx_decade_lang_impact",
        )

        # Requirement 2: Filter by genre, country, sorted by impact
        movies.create_index(
            [("genres", ASCENDING), ("impact_score", DESCENDING)],
            name="idx_genre_impact",
        )
        movies.create_index(
            [("countries", ASCENDING), ("impact_score", DESCENDING)],
            name="idx_country_impact",
        )

        # Requirement 3: Filter by rating, director, decade, sorted by impact
        movies.create_index(
            [
                ("rating", ASCENDING),
                ("directors.name", ASCENDING),
                ("decade", ASCENDING),
                ("impact_score", DESCENDING),
            ],
            name="idx_rating_director_decade_impact",
        )

        # Requirement 1 & 4: Single compound TEXT index on movie title and synopsis, sorted by impact.
        # Note: `language_override="text_language"` prevents collision with the `language: {original, availables}` object field.
        MongoSchema._ensure_single_text_index(
            movies,
            [
                ("title", TEXT),
                ("synopsis", TEXT),
                ("impact_score", DESCENDING),
            ],
            name="idx_title_synopsis_impact",
            default_language="english",
            language_override="text_language",
            weights={"title": 10, "synopsis": 1},
        )

        # Requirement 6 & 7: Indexes for cast actor name and director name, sorted by impact score
        movies.create_index(
            [("cast.name", ASCENDING), ("impact_score", DESCENDING)],
            name="idx_cast_name_impact",
        )
        movies.create_index(
            [("directors.name", ASCENDING), ("impact_score", DESCENDING)],
            name="idx_directors_name_impact",
        )

        # Single-field index on impact score
        movies.create_index([("impact_score", DESCENDING)], name="idx_impact_score")

        # INDEXES FOR 'reviews' COLLECTION
        reviews = database["reviews"]
        # Requirement 5: Reviews for a movie, sorted by likes and comments count
        reviews.create_index(
            [
                ("movie.title", ASCENDING),
                ("likes", DESCENDING),
                ("comments_count", DESCENDING),
            ],
            name="idx_movie_likes_comments",
        )

        # Requirement 5: Keyword text search on review content
        MongoSchema._ensure_single_text_index(
            reviews,
            [("content", TEXT)],
            name="idx_text_review_content",
            default_language="english",
            language_override="text_language",
        )

        # Requirement 8 & User profile historical reviews lookup
        reviews.create_index(
            [("owner.username", ASCENDING), ("created_at", ASCENDING)],
            name="idx_username_created_at",
        )

        # INDEXES FOR 'users' COLLECTION
        users = database["users"]
        users.create_index(
            [("username", ASCENDING)], unique=True, name="idx_unique_username"
        )
        users.create_index(
            [("email", ASCENDING)], unique=True, name="idx_unique_email"
        )

    @staticmethod
    def setup(database: Optional[Database] = None) -> Database:
        """Entry point to initialize all collections and indexes in MongoDB."""
        if database is None:
            database = MongoConnection.instance().database

        MongoSchema.create_collection(database, "actors", ACTORS_VALIDATOR)
        MongoSchema.create_collection(database, "directors", DIRECTORS_VALIDATOR)
        MongoSchema.create_collection(database, "movies", MOVIES_VALIDATOR)
        MongoSchema.create_collection(database, "reviews", REVIEWS_VALIDATOR)
        MongoSchema.create_collection(database, "users", USERS_VALIDATOR)
        MongoSchema.create_collection(database, "lists", LISTS_VALIDATOR)
        MongoSchema.create_indexes(database)
        return database
