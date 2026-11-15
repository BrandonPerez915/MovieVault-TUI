"""
Catalog and Recursive Ingestion Service for MovieVault
(backend/services/CatalogService.py).

Responsibilities:
1. Ensure partial unique indexes on `tmdb_id` in `movies`, `actors`, and `directors`.
2. Ingest movies from TMDB recursively (movie + directors + top 10 cast
   with complete biographical data from `/person/{id}`), preventing duplicates
   across all collections via atomic upserts (`$setOnInsert`).
3. Populate the database with `N` popular movies from TMDB (`populate_popular`).
4. Provide targeted fallbacks for MongoDB requirements when a local query returns no results.
5. Provide enriched read queries for the Letterboxd-style interface
   (movie details, actor/director details, and paginated grids).
"""

from dataclasses import dataclass, field
import math
import re
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from services.TMDBService import TMDBService


@dataclass
class PopulateReport:
    """Summary returned when populating the catalog with N popular movies from TMDB."""
    requested: int
    processed: int = 0
    new_movies: int = 0
    skipped_existing: int = 0
    new_actors: int = 0
    new_directors: int = 0
    errors: int = 0


@dataclass
class MovieSummary:
    """Summarized movie data for grid cards (`MovieCard`)."""
    movie_id: str
    title: str
    release_year: int
    rating: float
    poster_url: str = ""
    genres: List[str] = field(default_factory=list)
    impact_score: float = 0.0


@dataclass
class MovieDetail:
    """Full movie details for `MovieDetailScreen`."""
    movie_id: str
    title: str
    release_year: int
    decade: int
    poster_url: str
    synopsis: str
    rating: float
    ratings_count: int
    likes: int
    impact_score: float
    genres: List[str]
    countries: List[str]
    language_original: str
    language_availables: List[str]
    directors: List[Dict[str, str]]  # [{"id": str, "name": str, "poster_url": str}]
    cast: List[Dict[str, str]]       # [{"id": str, "name": str, "character": str, "poster_url": str}]
    available_streaming: List[str]
    runtime: int = 0


@dataclass
class PersonDetail:
    """Full actor or director details for `PersonScreen`."""
    person_id: str
    kind: Literal["actor", "director"]
    name: str
    birth_year: Optional[int]
    nationality: str
    bio: str
    is_active: bool
    profile_url: str = ""
    movies: List[MovieSummary] = field(default_factory=list)


class CatalogService:
    """Manages recursive ingestion without duplicates and catalog reads (Singleton)."""

    _instance: Optional["CatalogService"] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "CatalogService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._indexes_ensured: bool = False
        self._initialized = True

    def ensure_indexes(self, db: Optional[Database]) -> None:
        """Creates all schema indexes (`MongoSchema.create_indexes`) and partial unique indexes on `tmdb_id`."""
        if db is None or self._indexes_ensured:
            return
        try:
            from databases.mongodb.schema import MongoSchema
            from databases.mongodb.validators import (
                ACTORS_VALIDATOR,
                DIRECTORS_VALIDATOR,
                MOVIES_VALIDATOR,
            )

            try:
                if hasattr(db, "list_collection_names"):
                    MongoSchema.create_collection(db, "actors", ACTORS_VALIDATOR)
                    MongoSchema.create_collection(db, "directors", DIRECTORS_VALIDATOR)
                    MongoSchema.create_collection(db, "movies", MOVIES_VALIDATOR)
            except Exception:
                pass

            MongoSchema.create_indexes(db)
            for col_name in ("movies", "actors", "directors"):
                db[col_name].create_index(
                    [("tmdb_id", ASCENDING)],
                    unique=True,
                    name=f"idx_unique_tmdb_{col_name}",
                    partialFilterExpression={"tmdb_id": {"$exists": True}},
                )
            self._migrate_embedded_people(db)
            self._indexes_ensured = True
        except Exception:
            pass

    def _migrate_embedded_people(self, db: Database) -> None:
        """
        Ensures all existing movie documents in `db["movies"]` store only `id`, `name`,
        and `poster_url` (plus `character` for `cast`), removing legacy `director_id` /
        `actor_id` fields and backfilling `poster_url` from `actors` and `directors`.
        """
        try:
            for doc in db["movies"].find({}, {"directors": 1, "cast": 1}):
                raw_dirs = doc.get("directors") or []
                raw_cast = doc.get("cast") or []
                needs_update = any(
                    "director_id" in d or "poster_url" not in d for d in raw_dirs
                ) or any(
                    "actor_id" in a or "poster_url" not in a for a in raw_cast
                )
                if not needs_update:
                    continue

                clean_dirs: List[Dict[str, Any]] = []
                for d in raw_dirs:
                    d_oid = d.get("id") or d.get("director_id")
                    d_name = d.get("name", "")
                    d_poster = d.get("poster_url") or ""
                    if not d_poster:
                        p_doc = (
                            db["directors"].find_one({"_id": d_oid})
                            if d_oid
                            else None
                        )
                        if p_doc is None and d_name:
                            p_doc = db["directors"].find_one({"name": d_name})
                        if p_doc:
                            d_poster = (
                                p_doc.get("poster_url")
                                or p_doc.get("profile_url")
                                or ""
                            )
                    clean_dirs.append(
                        {
                            "id": d_oid,
                            "name": d_name,
                            "poster_url": d_poster,
                        }
                    )

                clean_cast: List[Dict[str, Any]] = []
                for a in raw_cast:
                    a_oid = a.get("id") or a.get("actor_id")
                    a_name = a.get("name", "")
                    a_char = a.get("character", "")
                    a_poster = a.get("poster_url") or ""
                    if not a_poster:
                        p_doc = (
                            db["actors"].find_one({"_id": a_oid})
                            if a_oid
                            else None
                        )
                        if p_doc is None and a_name:
                            p_doc = db["actors"].find_one({"name": a_name})
                        if p_doc:
                            a_poster = (
                                p_doc.get("poster_url")
                                or p_doc.get("profile_url")
                                or ""
                            )
                    clean_cast.append(
                        {
                            "id": a_oid,
                            "name": a_name,
                            "character": a_char,
                            "poster_url": a_poster,
                        }
                    )

                db["movies"].update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"directors": clean_dirs, "cast": clean_cast}},
                )
        except Exception:
            pass

    def _extract_nationality(self, place_of_birth: Optional[str]) -> str:
        if not place_of_birth or not place_of_birth.strip():
            return "Unknown"
        parts = [p.strip() for p in place_of_birth.split(",") if p.strip()]
        return parts[-1] if parts else "Unknown"

    def _extract_birth_year(self, birthday: Optional[str]) -> Optional[int]:
        if not birthday or len(birthday.strip()) < 4:
            return None
        try:
            year = int(birthday.strip()[:4])
            return year if 1800 <= year <= 2100 else None
        except ValueError:
            return None

    def ingest_person(
        self,
        db: Database,
        collection_name: Literal["actors", "directors"],
        tmdb_person_id: Optional[int],
        fallback_name: str,
        include_full_details: bool = True,
        fallback_profile_path: str = "",
    ) -> Tuple[ObjectId, bool]:
        """
        Inserts or retrieves an actor/director avoiding duplicates:
        1. Searches by `tmdb_id` (if available).
        2. Searches by exact case-insensitive `name` (and sets `tmdb_id` if missing).
        3. If new and `include_full_details=True`, queries `/person/{id}` in TMDB
           for birth year, nationality, biography, active status, and photo.
        4. Performs atomic upsert with `$setOnInsert`.

        Returns `(object_id, was_created)`.
        """
        clean_name = (fallback_name or "").strip() or "Unknown"
        col = db[collection_name]
        tmdb = TMDBService()

        # 1. Search by tmdb_id
        if tmdb_person_id is not None:
            existing_by_id = col.find_one(
                {"tmdb_id": int(tmdb_person_id)},
                {"_id": 1, "poster_url": 1, "profile_url": 1},
            )
            if existing_by_id:
                if (
                    fallback_profile_path
                    and not existing_by_id.get("poster_url")
                    and not existing_by_id.get("profile_url")
                ):
                    img_url = tmdb.build_image_url(fallback_profile_path, "w185")
                    try:
                        col.update_one(
                            {"_id": existing_by_id["_id"]},
                            {"$set": {"poster_url": img_url, "profile_url": img_url}},
                        )
                    except Exception:
                        pass
                return existing_by_id["_id"], False

        # 2. Search by exact name (using idx_actors_name / idx_directors_name)
        existing_by_name = col.find_one(
            {"name": clean_name},
            {"_id": 1, "tmdb_id": 1, "poster_url": 1, "profile_url": 1},
        )
        if existing_by_name is None:
            existing_by_name = col.find_one(
                {"name": {"$regex": f"^{re.escape(clean_name)}$", "$options": "i"}},
                {"_id": 1, "tmdb_id": 1, "poster_url": 1, "profile_url": 1},
            )
        if existing_by_name:
            updates: Dict[str, Any] = {}
            if tmdb_person_id is not None and "tmdb_id" not in existing_by_name:
                updates["tmdb_id"] = int(tmdb_person_id)
            if (
                fallback_profile_path
                and not existing_by_name.get("poster_url")
                and not existing_by_name.get("profile_url")
            ):
                img_url = tmdb.build_image_url(fallback_profile_path, "w185")
                updates["poster_url"] = img_url
                updates["profile_url"] = img_url
            if updates:
                try:
                    col.update_one(
                        {"_id": existing_by_name["_id"]},
                        {"$set": updates},
                    )
                except Exception:
                    pass
            return existing_by_name["_id"], False

        # 3. Query biographical details in TMDB if person is new
        birth_year: Optional[int] = None
        nationality = "Unknown"
        bio = ""
        is_active = True
        profile_path = (fallback_profile_path or "").strip()
        resolved_name = clean_name

        if include_full_details and tmdb_person_id is not None and tmdb.is_configured:
            try:
                p_data = tmdb.person_details(int(tmdb_person_id))
                if p_data:
                    resolved_name = (p_data.get("name") or clean_name).strip()
                    birth_year = self._extract_birth_year(p_data.get("birthday"))
                    nationality = self._extract_nationality(p_data.get("place_of_birth"))
                    bio = (p_data.get("biography") or "").strip()
                    is_active = p_data.get("deathday") in (None, "")
                    profile_path = (
                        p_data.get("profile_path") or fallback_profile_path or ""
                    ).strip()
            except Exception:
                pass

        person_doc: Dict[str, Any] = {
            "name": resolved_name,
            "birth_year": birth_year,
            "nationality": nationality,
            "bio": bio,
            "is_active": is_active,
        }
        if tmdb_person_id is not None:
            person_doc["tmdb_id"] = int(tmdb_person_id)
        if profile_path:
            img_url = tmdb.build_image_url(profile_path, "w185")
            person_doc["tmdb_profile_path"] = profile_path
            person_doc["profile_url"] = img_url
            person_doc["poster_url"] = img_url

        # 4. Atomic upsert
        if tmdb_person_id is not None:
            try:
                res = col.update_one(
                    {"tmdb_id": int(tmdb_person_id)},
                    {"$setOnInsert": person_doc},
                    upsert=True,
                )
                if res.upserted_id is not None:
                    return res.upserted_id, True
                found = col.find_one({"tmdb_id": int(tmdb_person_id)}, {"_id": 1})
                if found:
                    return found["_id"], False
            except DuplicateKeyError:
                found = col.find_one({"tmdb_id": int(tmdb_person_id)}, {"_id": 1})
                if found:
                    return found["_id"], False

        res_insert = col.insert_one(person_doc)
        return res_insert.inserted_id, True

    def ingest_movie(
        self,
        db: Optional[Database],
        tmdb_id: int,
        include_person_details: bool = True,
    ) -> Tuple[Optional[Dict[str, Any]], bool, int, int]:
        """
        Ingests a movie by `tmdb_id` recursively along with its directors and
        up to 10 main cast members, avoiding duplicates.

        Returns `(movie_doc, was_created, new_actors_count, new_directors_count)`.
        """
        if db is None or not tmdb_id:
            return None, False, 0, 0

        self.ensure_indexes(db)
        movies_col = db["movies"]

        # Check if already exists by tmdb_id before calling TMDB
        existing_by_id = movies_col.find_one({"tmdb_id": int(tmdb_id)})
        if existing_by_id is not None:
            return existing_by_id, False, 0, 0

        tmdb = TMDBService()
        if not tmdb.is_configured:
            return None, False, 0, 0

        try:
            details = tmdb.movie_details(int(tmdb_id))
        except Exception:
            return None, False, 0, 0

        title = (details.get("title") or details.get("original_title") or "").strip()
        release_date = (details.get("release_date") or "").strip()
        if not title or len(release_date) < 4:
            return None, False, 0, 0

        try:
            release_year = int(release_date[:4])
        except ValueError:
            return None, False, 0, 0

        if release_year < 1888 or release_year > 2100:
            return None, False, 0, 0

        # Check if already exists by title + year (legacy document without tmdb_id)
        existing_by_title = movies_col.find_one(
            {
                "title": {"$regex": f"^{re.escape(title)}$", "$options": "i"},
                "release_year": release_year,
            }
        )
        if existing_by_title is not None:
            if "tmdb_id" not in existing_by_title:
                try:
                    movies_col.update_one(
                        {"_id": existing_by_title["_id"]},
                        {"$set": {"tmdb_id": int(tmdb_id)}},
                    )
                    existing_by_title["tmdb_id"] = int(tmdb_id)
                except Exception:
                    pass
            return existing_by_title, False, 0, 0

        decade = (release_year // 10) * 10
        poster_path = (details.get("poster_path") or "").strip()
        poster_url = tmdb.build_image_url(poster_path, "w500") if poster_path else ""

        orig_lang = (details.get("original_language") or "en").strip().lower()
        spoken = [
            (lang.get("iso_639_1") or "").strip().lower()
            for lang in details.get("spoken_languages", [])
            if lang.get("iso_639_1")
        ]
        if orig_lang and orig_lang not in spoken:
            spoken.insert(0, orig_lang)

        genres = [
            g.get("name", "").strip()
            for g in details.get("genres", [])
            if g.get("name")
        ]
        countries = [
            (c.get("name") or c.get("iso_3166_1") or "").strip()
            for c in details.get("production_countries", [])
            if c.get("name") or c.get("iso_3166_1")
        ]

        credits_data = details.get("credits", {})
        directors_embedded: List[Dict[str, Any]] = []
        seen_director_ids = set()
        new_directors_count = 0

        for crew_member in credits_data.get("crew", []):
            if crew_member.get("job") == "Director" and crew_member.get("name"):
                person_tmdb_id = crew_member.get("id")
                d_name = crew_member["name"].strip()
                dedup_key = person_tmdb_id or d_name.lower()
                if dedup_key in seen_director_ids:
                    continue
                seen_director_ids.add(dedup_key)

                crew_profile_path = (crew_member.get("profile_path") or "").strip()
                d_oid, created_dir = self.ingest_person(
                    db=db,
                    collection_name="directors",
                    tmdb_person_id=person_tmdb_id,
                    fallback_name=d_name,
                    include_full_details=include_person_details,
                    fallback_profile_path=crew_profile_path,
                )
                if created_dir:
                    new_directors_count += 1
                d_poster_url = (
                    tmdb.build_image_url(crew_profile_path, "w185")
                    if crew_profile_path
                    else ""
                )
                if not d_poster_url:
                    d_doc = db["directors"].find_one(
                        {"_id": d_oid}, {"poster_url": 1, "profile_url": 1}
                    )
                    if d_doc:
                        d_poster_url = (
                            d_doc.get("poster_url") or d_doc.get("profile_url") or ""
                        )
                directors_embedded.append(
                    {
                        "id": d_oid,
                        "name": d_name,
                        "poster_url": d_poster_url,
                    }
                )

        cast_embedded: List[Dict[str, Any]] = []
        seen_actor_ids = set()
        new_actors_count = 0

        for cast_member in credits_data.get("cast", [])[:10]:
            if cast_member.get("name"):
                person_tmdb_id = cast_member.get("id")
                a_name = cast_member["name"].strip()
                dedup_key = person_tmdb_id or a_name.lower()
                if dedup_key in seen_actor_ids:
                    continue
                seen_actor_ids.add(dedup_key)

                cast_profile_path = (cast_member.get("profile_path") or "").strip()
                a_oid, created_act = self.ingest_person(
                    db=db,
                    collection_name="actors",
                    tmdb_person_id=person_tmdb_id,
                    fallback_name=a_name,
                    include_full_details=include_person_details,
                    fallback_profile_path=cast_profile_path,
                )
                if created_act:
                    new_actors_count += 1
                a_poster_url = (
                    tmdb.build_image_url(cast_profile_path, "w185")
                    if cast_profile_path
                    else ""
                )
                if not a_poster_url:
                    a_doc = db["actors"].find_one(
                        {"_id": a_oid}, {"poster_url": 1, "profile_url": 1}
                    )
                    if a_doc:
                        a_poster_url = (
                            a_doc.get("poster_url") or a_doc.get("profile_url") or ""
                        )
                cast_embedded.append(
                    {
                        "id": a_oid,
                        "name": a_name,
                        "character": (cast_member.get("character") or "").strip(),
                        "poster_url": a_poster_url,
                    }
                )

        tmdb_vote_avg = float(details.get("vote_average") or 0.0)
        rating = round(min(5.0, max(0.0, tmdb_vote_avg / 2.0)), 2)
        ratings_count = max(0, int(details.get("vote_count") or 0))
        impact_score = round(rating * math.log10(1 + ratings_count), 4)
        runtime = max(0, int(details.get("runtime") or 0))

        providers_results = details.get("watch/providers", {}).get("results", {})
        streaming_set = set()
        for region_code in ("MX", "US"):
            region_data = providers_results.get(region_code, {})
            for provider in region_data.get("flatrate", []):
                p_name = (provider.get("provider_name") or "").strip()
                if p_name:
                    streaming_set.add(p_name)

        movie_doc: Dict[str, Any] = {
            "tmdb_id": int(tmdb_id),
            "title": title,
            "release_year": release_year,
            "poster_url": poster_url,
            "tmdb_poster_path": poster_path,
            "decade": decade,
            "language": {
                "original": orig_lang,
                "availables": spoken or [orig_lang],
            },
            "genres": genres,
            "countries": countries,
            "directors": directors_embedded,
            "cast": cast_embedded,
            "synopsis": (details.get("overview") or "").strip(),
            "rating": rating,
            "ratings_count": ratings_count,
            "likes": 0,
            "awards": [],
            "impact_score": impact_score,
            "available_streaming": sorted(streaming_set),
            "runtime": runtime,
        }

        try:
            res = movies_col.update_one(
                {"tmdb_id": int(tmdb_id)},
                {"$setOnInsert": movie_doc},
                upsert=True,
            )
            if res.upserted_id is not None:
                movie_doc["_id"] = res.upserted_id
                return movie_doc, True, new_actors_count, new_directors_count
            saved = movies_col.find_one({"tmdb_id": int(tmdb_id)})
            return saved, False, new_actors_count, new_directors_count
        except DuplicateKeyError:
            saved = movies_col.find_one({"tmdb_id": int(tmdb_id)})
            return saved, False, new_actors_count, new_directors_count

    def populate_popular(
        self,
        db: Optional[Database],
        n: int,
        include_person_details: bool = True,
        on_progress: Optional[Callable[[int, int, str, str], None]] = None,
    ) -> PopulateReport:
        """
        Populates MongoDB with `n` popular movies from TMDB `/movie/popular`,
        recursively inserting their directors and cast without duplicates.

        `on_progress(current_idx, total_n, movie_title, status_tag)` is invoked
        after each movie (`status_tag` in `{"new", "skipped", "error"}`).
        """
        target = max(1, int(n))
        report = PopulateReport(requested=target)
        if db is None:
            return report

        tmdb = TMDBService()
        if not tmdb.is_configured:
            return report

        self.ensure_indexes(db)
        page = 1
        max_pages = max(1, math.ceil(target / 20.0) + 5)

        while report.processed < target and page <= max_pages:
            try:
                items = tmdb.popular(page=page)
            except Exception:
                report.errors += 1
                break

            if not items:
                break

            for item in items:
                if report.processed >= target:
                    break
                tmdb_id = item.get("id")
                raw_title = (item.get("title") or f"ID #{tmdb_id}").strip()
                report.processed += 1

                if not tmdb_id:
                    report.errors += 1
                    if on_progress:
                        on_progress(report.processed, target, raw_title, "error")
                    continue

                doc, created, new_act, new_dir = self.ingest_movie(
                    db=db,
                    tmdb_id=int(tmdb_id),
                    include_person_details=include_person_details,
                )
                if doc is None:
                    report.errors += 1
                    if on_progress:
                        on_progress(report.processed, target, raw_title, "error")
                elif created:
                    report.new_movies += 1
                    report.new_actors += new_act
                    report.new_directors += new_dir
                    if on_progress:
                        on_progress(
                            report.processed,
                            target,
                            doc.get("title", raw_title),
                            "new",
                        )
                else:
                    report.skipped_existing += 1
                    if on_progress:
                        on_progress(
                            report.processed,
                            target,
                            doc.get("title", raw_title),
                            "skipped",
                        )

            page += 1

        return report

    # =========================================================================
    # REQUIREMENT FALLBACKS (TMDB -> RECURSIVE INGESTION IN MONGODB)
    # =========================================================================

    def _ingest_candidate_list(
        self,
        db: Database,
        candidates: List[Dict[str, Any]],
        limit: int = 10,
    ) -> int:
        count = 0
        for item in candidates[:limit]:
            tmdb_id = item.get("id")
            if not tmdb_id:
                continue
            doc, _, _, _ = self.ingest_movie(db, int(tmdb_id))
            if doc is not None:
                count += 1
        return count

    def fallback_by_title(self, db: Optional[Database], title: str, limit: int = 10) -> int:
        """Fallback Req 1: searches TMDB by title and ingests results."""
        if db is None or not (title or "").strip():
            return 0
        tmdb = TMDBService()
        if not tmdb.is_configured:
            return 0
        try:
            candidates = tmdb.search_movies(title.strip(), page=1)
            return self._ingest_candidate_list(db, candidates, limit=limit)
        except Exception:
            return 0

    def fallback_by_genre_country(
        self,
        db: Optional[Database],
        genre: str,
        country: str,
        director: str = "",
        limit: int = 10,
    ) -> int:
        """Fallback Req 2: uses `/discover/movie` with genre, country, and optional director."""
        if db is None:
            return 0
        tmdb = TMDBService()
        if not tmdb.is_configured:
            return 0
        try:
            filters: Dict[str, Any] = {}
            gid = tmdb.resolve_genre_id(genre)
            if gid is not None:
                filters["with_genres"] = str(gid)
            iso = tmdb.resolve_country_code(country)
            if iso:
                filters["with_origin_country"] = iso
            if director and director.strip():
                people = tmdb.search_person(director.strip())
                if people and people[0].get("id"):
                    filters["with_crew"] = str(people[0]["id"])
            if not filters:
                return 0
            candidates = tmdb.discover(**filters)
            return self._ingest_candidate_list(db, candidates, limit=limit)
        except Exception:
            return 0

    def fallback_by_rating_director_decades(
        self,
        db: Optional[Database],
        min_rating: float,
        director: str,
        start_decade: int,
        end_decade: int,
        limit: int = 10,
    ) -> int:
        """Fallback Req 3: discovers movies on TMDB by director, decade range, and rating."""
        if db is None or not (director or "").strip():
            return 0
        tmdb = TMDBService()
        if not tmdb.is_configured:
            return 0
        try:
            people = tmdb.search_person(director.strip())
            if not people or not people[0].get("id"):
                return 0
            director_id = people[0]["id"]
            end_year = int(end_decade) + 9
            candidates = tmdb.discover(
                with_crew=str(director_id),
                **{
                    "vote_average.gte": max(0.0, min(10.0, float(min_rating) * 2.0)),
                    "primary_release_date.gte": f"{int(start_decade)}-01-01",
                    "primary_release_date.lte": f"{end_year}-12-31",
                },
            )
            return self._ingest_candidate_list(db, candidates, limit=limit)
        except Exception:
            return 0

    def fallback_by_synopsis_keywords(
        self,
        db: Optional[Database],
        keywords: str,
        limit: int = 10,
    ) -> int:
        """Fallback Req 4: searches by keyword in TMDB (with `/search/movie` backup)."""
        clean = (keywords or "").strip()
        if db is None or not clean:
            return 0
        tmdb = TMDBService()
        if not tmdb.is_configured:
            return 0
        try:
            kw_results = tmdb.search_keyword(clean)
            candidates: List[Dict[str, Any]] = []
            if kw_results and kw_results[0].get("id"):
                kw_ids = "|".join(str(k["id"]) for k in kw_results[:3] if k.get("id"))
                candidates = tmdb.discover(with_keywords=kw_ids)
            if not candidates:
                candidates = tmdb.search_movies(clean, page=1)
            return self._ingest_candidate_list(db, candidates, limit=limit)
        except Exception:
            return 0

    def fallback_by_actor_director(
        self,
        db: Optional[Database],
        actor_name: str,
        director_name: str,
        limit: int = 10,
    ) -> int:
        """Fallback Req 6: discovers movies by actor and/or director on TMDB."""
        if db is None:
            return 0
        tmdb = TMDBService()
        if not tmdb.is_configured:
            return 0
        try:
            filters: Dict[str, Any] = {}
            if actor_name and actor_name.strip():
                actors = tmdb.search_person(actor_name.strip())
                if actors and actors[0].get("id"):
                    filters["with_cast"] = str(actors[0]["id"])
            if director_name and director_name.strip():
                directors = tmdb.search_person(director_name.strip())
                if directors and directors[0].get("id"):
                    filters["with_crew"] = str(directors[0]["id"])
            if not filters:
                return 0
            candidates = tmdb.discover(**filters)
            return self._ingest_candidate_list(db, candidates, limit=limit)
        except Exception:
            return 0

    def fallback_actor_filmography(
        self,
        db: Optional[Database],
        actor_name: str,
        limit: int = 12,
    ) -> int:
        """Fallback Req 7: searches actor on TMDB and ingests their most popular movies."""
        clean = (actor_name or "").strip()
        if db is None or not clean:
            return 0
        tmdb = TMDBService()
        if not tmdb.is_configured:
            return 0
        try:
            people = tmdb.search_person(clean)
            if not people or not people[0].get("id"):
                return 0
            pid = int(people[0]["id"])
            self.ingest_person(db, "actors", pid, people[0].get("name", clean), True)
            credits = tmdb.person_movie_credits(pid)
            cast_movies = credits.get("cast", [])
            cast_movies.sort(key=lambda m: float(m.get("popularity") or 0.0), reverse=True)
            return self._ingest_candidate_list(db, cast_movies, limit=limit)
        except Exception:
            return 0

    # =========================================================================
    # READ QUERIES FOR USER INTERFACE (LETTERBOXD FLOWS)
    # =========================================================================

    def _doc_to_summary(self, doc: Dict[str, Any]) -> MovieSummary:
        return MovieSummary(
            movie_id=str(doc.get("_id", "")),
            title=doc.get("title", "Untitled"),
            release_year=int(doc.get("release_year") or 0),
            rating=float(doc.get("rating") or 0.0),
            poster_url=doc.get("poster_url", ""),
            genres=list(doc.get("genres") or []),
            impact_score=float(doc.get("impact_score") or 0.0),
        )

    def get_popular(
        self,
        db: Optional[Database],
        page: int = 1,
        page_size: int = 12,
    ) -> Tuple[List[MovieSummary], int]:
        """Returns a page of catalog movies ordered by `impact_score`."""
        if db is None:
            return [], 0
        try:
            total = db["movies"].count_documents({})
            skip = max(0, (page - 1) * page_size)
            cursor = (
                db["movies"]
                .find(
                    {},
                    {
                        "title": 1,
                        "release_year": 1,
                        "rating": 1,
                        "poster_url": 1,
                        "genres": 1,
                        "impact_score": 1,
                    },
                )
                .sort("impact_score", DESCENDING)
                .skip(skip)
                .limit(page_size)
            )
            items = [self._doc_to_summary(d) for d in cursor]
            return items, total
        except Exception:
            return [], 0

    def search_movies_local(
        self,
        db: Optional[Database],
        query: str = "",
        limit: int = 15,
    ) -> List[MovieSummary]:
        """Searches movies only in local MongoDB (no TMDB fallback)."""
        if db is None:
            return []
        clean = (query or "").strip()
        filt: Dict[str, Any] = {}
        if clean:
            filt["title"] = {"$regex": re.escape(clean), "$options": "i"}
        try:
            cursor = (
                db["movies"]
                .find(
                    filt,
                    {
                        "title": 1,
                        "release_year": 1,
                        "rating": 1,
                        "poster_url": 1,
                        "genres": 1,
                        "impact_score": 1,
                    },
                )
                .sort("impact_score", DESCENDING)
                .limit(max(1, limit))
            )
            return [self._doc_to_summary(d) for d in cursor]
        except Exception:
            return []

    def get_movies_by_genres(
        self,
        db: Optional[Database],
        per_genre_limit: int = 16,
    ) -> Tuple[List[Tuple[str, List[MovieSummary]]], int]:
        """
        Groups catalog movies by genre (ordered by `impact_score` descending)
        for the Netflix-style Home screen. Returns `(genre_sections, total_movies)`.
        """
        if db is None:
            return [], 0
        try:
            total = db["movies"].count_documents({})
            if total == 0:
                return [], 0
            cursor = (
                db["movies"]
                .find(
                    {},
                    {
                        "title": 1,
                        "release_year": 1,
                        "rating": 1,
                        "poster_url": 1,
                        "genres": 1,
                        "impact_score": 1,
                    },
                )
                .sort("impact_score", DESCENDING)
            )
            grouped: Dict[str, List[MovieSummary]] = {}
            for doc in cursor:
                summary = self._doc_to_summary(doc)
                raw_genres = [
                    str(g).strip()
                    for g in (doc.get("genres") or [])
                    if str(g).strip()
                ]
                if not raw_genres:
                    raw_genres = ["Other"]
                for g in raw_genres:
                    bucket = grouped.setdefault(g, [])
                    if len(bucket) < per_genre_limit:
                        bucket.append(summary)

            sections = sorted(
                grouped.items(),
                key=lambda kv: (-len(kv[1]), kv[0].lower()),
            )
            return sections, total
        except Exception:
            return [], 0

    def get_movie_detail(
        self,
        db: Optional[Database],
        movie_id_or_title: str,
    ) -> Optional[MovieDetail]:
        """Returns the full movie details by its `_id` or `title`."""
        if db is None or not movie_id_or_title:
            return None
        clean = movie_id_or_title.strip()
        doc: Optional[Dict[str, Any]] = None
        try:
            if ObjectId.is_valid(clean):
                doc = db["movies"].find_one({"_id": ObjectId(clean)})
            if doc is None:
                # Use idx_title_synopsis_impact ($text) first
                doc = db["movies"].find_one({"$text": {"$search": f'"{clean}"'}})
            if doc is None:
                doc = db["movies"].find_one(
                    {"title": {"$regex": f"^{re.escape(clean)}$", "$options": "i"}}
                )
            if doc is None:
                # Attempt TMDB fallback if not present in MongoDB
                self.fallback_by_title(db, clean, limit=3)
                doc = db["movies"].find_one({"$text": {"$search": clean}})
                if doc is None:
                    doc = db["movies"].find_one(
                        {"title": {"$regex": re.escape(clean), "$options": "i"}}
                    )
        except Exception:
            return None

        if doc is None:
            return None

        lang_obj = doc.get("language") or {}
        directors = [
            {
                "id": str(d.get("id") or ""),
                "name": d.get("name", ""),
                "poster_url": d.get("poster_url", ""),
            }
            for d in (doc.get("directors") or [])
            if d.get("name")
        ]
        cast = [
            {
                "id": str(a.get("id") or ""),
                "name": a.get("name", ""),
                "character": a.get("character", ""),
                "poster_url": a.get("poster_url", ""),
            }
            for a in (doc.get("cast") or [])
            if a.get("name")
        ]

        return MovieDetail(
            movie_id=str(doc["_id"]),
            title=doc.get("title", ""),
            release_year=int(doc.get("release_year") or 0),
            decade=int(doc.get("decade") or 0),
            poster_url=doc.get("poster_url", ""),
            synopsis=doc.get("synopsis", ""),
            rating=float(doc.get("rating") or 0.0),
            ratings_count=int(doc.get("ratings_count") or 0),
            likes=int(doc.get("likes") or 0),
            impact_score=float(doc.get("impact_score") or 0.0),
            genres=list(doc.get("genres") or []),
            countries=list(doc.get("countries") or []),
            language_original=str(lang_obj.get("original") or "en"),
            language_availables=list(lang_obj.get("availables") or []),
            directors=directors,
            cast=cast,
            available_streaming=list(doc.get("available_streaming") or []),
            runtime=int(doc.get("runtime") or 0),
        )

    def get_person_detail(
        self,
        db: Optional[Database],
        person_id_or_name: str,
        kind: Literal["actor", "director"] = "actor",
    ) -> Optional[PersonDetail]:
        """Returns biographical data and filmography for an actor or director."""
        if db is None or not person_id_or_name:
            return None

        col_name = "actors" if kind == "actor" else "directors"
        clean = person_id_or_name.strip()
        doc: Optional[Dict[str, Any]] = None
        try:
            if ObjectId.is_valid(clean):
                doc = db[col_name].find_one({"_id": ObjectId(clean)})
            if doc is None:
                # Exact match using idx_actors_name / idx_directors_name
                doc = db[col_name].find_one({"name": clean})
            if doc is None:
                doc = db[col_name].find_one(
                    {"name": {"$regex": f"^{re.escape(clean)}$", "$options": "i"}}
                )
        except Exception:
            return None

        if doc is None:
            return None

        name = doc.get("name", clean)
        tmdb = TMDBService()

        # If record has empty biographical details but has tmdb_id, enrich on demand
        if (
            not doc.get("bio")
            and doc.get("nationality") in (None, "Unknown")
            and doc.get("tmdb_id")
            and tmdb.is_configured
        ):
            try:
                p_data = tmdb.person_details(int(doc["tmdb_id"]))
                if p_data:
                    updates = {
                        "birth_year": self._extract_birth_year(p_data.get("birthday")),
                        "nationality": self._extract_nationality(p_data.get("place_of_birth")),
                        "bio": (p_data.get("biography") or "").strip(),
                        "is_active": p_data.get("deathday") in (None, ""),
                    }
                    if p_data.get("profile_path"):
                        img_url = tmdb.build_image_url(p_data["profile_path"], "w185")
                        updates["tmdb_profile_path"] = p_data["profile_path"]
                        updates["profile_url"] = img_url
                        updates["poster_url"] = img_url
                    db[col_name].update_one({"_id": doc["_id"]}, {"$set": updates})
                    doc.update(updates)
            except Exception:
                pass

        # Exact match on cast.name / directors.name sorted by impact_score DESCENDING
        # uses idx_cast_name_impact / idx_directors_name_impact directly
        field_key = "cast.name" if kind == "actor" else "directors.name"
        movies_cursor = (
            db["movies"]
            .find(
                {field_key: name},
                {
                    "title": 1,
                    "release_year": 1,
                    "rating": 1,
                    "poster_url": 1,
                    "genres": 1,
                    "impact_score": 1,
                },
            )
            .sort("impact_score", DESCENDING)
            .limit(24)
        )
        filmography = [self._doc_to_summary(m) for m in movies_cursor]

        profile_url = doc.get("poster_url") or doc.get("profile_url") or ""
        if not profile_url and doc.get("tmdb_profile_path"):
            profile_url = tmdb.build_image_url(doc["tmdb_profile_path"], "w185")

        return PersonDetail(
            person_id=str(doc["_id"]),
            kind=kind,
            name=name,
            birth_year=doc.get("birth_year"),
            nationality=doc.get("nationality") or "Unknown",
            bio=doc.get("bio") or "",
            is_active=bool(doc.get("is_active", True)),
            profile_url=profile_url,
            movies=filmography,
        )

    def find_movie_by_title(
        self,
        db: Optional[Database],
        title: str,
    ) -> Optional[MovieSummary]:
        """Searches a movie by title to enrich Cassandra/Dgraph results (uses idx_title_synopsis_impact)."""
        if db is None or not (title or "").strip():
            return None
        clean = title.strip()
        projection = {
            "title": 1,
            "release_year": 1,
            "rating": 1,
            "poster_url": 1,
            "genres": 1,
            "impact_score": 1,
        }
        doc = db["movies"].find_one(
            {"$text": {"$search": f'"{clean}"'}},
            projection,
        )
        if doc is None:
            doc = db["movies"].find_one(
                {"title": {"$regex": f"^{re.escape(clean)}$", "$options": "i"}},
                projection,
            )
        return self._doc_to_summary(doc) if doc else None
