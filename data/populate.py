"""
MovieVault — Database Population Script (`data/populate.py`).

Populates the database with:
1. 50 popular movies from TMDB recursively (including their actors and directors).
2. 30 test users with varied watchlists, descriptions, watched movies, movie likes, and reviews.
3. Rich user-to-user social interactions (follows and cross-user review likes).
4. Exports the created usernames, emails, and passwords to `users.txt`.

Usage:
    ./.venv/bin/python data/populate.py
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from databases import MongoConnection, close_all_connections
from services.ActionService import ActionService
from services.AuthService import AuthService, UserSession
from services.CatalogService import CatalogService
from services.TMDBService import TMDBService
from config import ROOT_DIR

TARGET_MOVIES = 50
TARGET_USERS = 30
OUTPUT_USERS_FILE = ROOT_DIR / "users.txt"

USER_PROFILES: List[Tuple[str, str]] = [
    ("cinephile_alex", "Alex!Vault01"),
    ("sofia_noir", "Sofia!Vault02"),
    ("marco_scifi", "Marco!Vault03"),
    ("elena_frames", "Elena!Vault04"),
    ("lucas_reel", "Lucas!Vault05"),
    ("valeria_cut", "Valeria!Vault06"),
    ("diego_imdb", "Diego!Vault07"),
    ("camila_lens", "Camila!Vault08"),
    ("mateo_imax", "Mateo!Vault09"),
    ("lucia_indie", "Lucia!Vault10"),
    ("nicolas_35mm", "Nicolas!Vault11"),
    ("paula_oscar", "Paula!Vault12"),
    ("andres_plot", "Andres!Vault13"),
    ("fernanda_cam", "Fernanda!Vault14"),
    ("gabriel_arc", "Gabriel!Vault15"),
    ("renata_score", "Renata!Vault16"),
    ("tomas_noir", "Tomas!Vault17"),
    ("mariana_cine", "Mariana!Vault18"),
    ("santiago_pov", "Santiago!Vault19"),
    ("daniela_film", "Daniela!Vault20"),
    ("emilio_edit", "Emilio!Vault21"),
    ("natalia_cast", "Natalia!Vault22"),
    ("sebastian_reel", "Sebastian!Vault23"),
    ("karla_drama", "Karla!Vault24"),
    ("rodrigo_shot", "Rodrigo!Vault25"),
    ("andrea_scene", "Andrea!Vault26"),
    ("javier_spool", "Javier!Vault27"),
    ("monica_stage", "Monica!Vault28"),
    ("ricardo_crew", "Ricardo!Vault29"),
    ("claudia_take", "Claudia!Vault30"),
]

LIST_TEMPLATES: List[Tuple[str, str]] = [
    ("Must Watch Classics", "Essential films everyone should experience at least once."),
    ("Weekend Marathon", "High-energy picks ideal for a Saturday movie night."),
    ("Mind Bending Plots", "Stories packed with twists, mystery, and nonlinear pacing."),
    ("Visual Masterpieces", "Cinematography, lighting, and production design at their peak."),
    ("Comfort Rewatches", "Movies I can always come back to after a long week."),
    ("Director Spotlight", "Standout works from visionary filmmakers."),
    ("Late Night Thrillers", "Tense, gripping cinema best watched after midnight."),
    ("Critics & Awards", "Acclaimed performances and award-winning storytelling."),
    ("Hidden & Underrated", "Titles that deserve a much larger audience."),
    ("Soundtrack Gems", "Films elevated by unforgettable musical scores."),
]

REVIEW_TEMPLATES: List[str] = [
    "Incredibly engaging from start to finish. The pacing never drops and the cast delivers.",
    "Stunning cinematography and a memorable score. Easily one of my favorite watches recently.",
    "Smart writing with genuine emotional weight. The final act completely won me over.",
    "Solid performances all around, even if the middle section slows down a little.",
    "A bold visual experience with standout direction and sharp editing throughout.",
    "Watched this on a whim and was blown away by the atmosphere and tension.",
    "Great character chemistry and thoughtful dialogue. Definitely worth a rewatch.",
    "Ambitious, stylish, and deeply entertaining. Kept me hooked until the credits.",
    "Strong premise and great execution; a couple of predictable beats, still very enjoyable.",
    "Masterclass in visual storytelling. Every frame feels deliberate and expressive.",
]

VIEWED_ON_OPTIONS: List[str] = ["Theater", "Streaming", "IMAX", "Blu-ray", "Festival"]
RATING_OPTIONS: List[float] = [2.5, 3.0, 3.5, 4.0, 4.5, 5.0]


def _connect_mongo() -> Any:
    mongo = MongoConnection()
    if not mongo.initialized:
        raise RuntimeError("MongoDB is not connected. Verify MONGO_URI and your running instance.")
    return mongo.database


def populate_movies(db: Any, target_count: int = TARGET_MOVIES) -> List[Dict[str, Any]]:
    """Populates `target_count` movies recursively from TMDB (with actors & directors)."""
    tmdb = TMDBService()
    if not tmdb.is_configured:
        raise RuntimeError("TMDB API key/token is not configured in .env.")

    print(f"=== [1/4] Populating {target_count} movies recursively from TMDB ===")

    def _on_progress(curr: int, total: int, title: str, status: str) -> None:
        tag = "NEW" if status == "new" else ("SKIPPED" if status == "skipped" else "ERROR")
        print(f"  [{curr}/{total}] [{tag}] {title}")

    report = CatalogService().populate_popular(
        db=db,
        n=target_count,
        include_person_details=True,
        on_progress=_on_progress,
    )
    print(
        f"  Summary -> new_movies={report.new_movies}, skipped={report.skipped_existing}, "
        f"new_actors={report.new_actors}, new_directors={report.new_directors}, errors={report.errors}"
    )

    movies = list(
        db["movies"].find(
            {},
            {"_id": 1, "title": 1, "release_year": 1, "poster_url": 1},
        ).limit(max(target_count, 50))
    )
    if not movies:
        raise RuntimeError("No movies found in MongoDB after TMDB population.")
    return movies


def create_test_users(
    auth: AuthService,
    profiles: List[Tuple[str, str]],
) -> List[Tuple[UserSession, str]]:
    """Registers (or logs in) all 30 test users and returns `(session, raw_password)` pairs."""
    print(f"\n=== [2/4] Creating {len(profiles)} test users ===")
    sessions: List[Tuple[UserSession, str]] = []

    for index, (username, password) in enumerate(profiles, start=1):
        email = f"{username}@movievault.demo"
        ok, session, msg = auth.register(username, email, password, password)
        if not ok or session is None:
            ok_login, login_session, login_msg = auth.login(username, password)
            if ok_login and login_session is not None:
                session = login_session
                print(f"  [{index}/{len(profiles)}] [EXISTING] @{username}")
            else:
                print(f"  [{index}/{len(profiles)}] [WARN] @{username}: {msg} | {login_msg}")
                continue
        else:
            print(f"  [{index}/{len(profiles)}] [CREATED] @{username}")
        sessions.append((session, password))

    return sessions


def populate_user_activity(
    database: Any,
    actions: ActionService,
    users: List[Tuple[UserSession, str]],
    movies: List[Dict[str, Any]],
    random_generator: random.Random,
) -> List[Tuple[str, str]]:
    """
    Creates distinct lists, watched movies, movie likes, and reviews per user.
    Returns a list of `(review_owner_username, movie_title)` pairs for cross-user liking.
    """
    print("\n=== [3/4] Generating lists, watched movies, likes, and reviews ===")
    created_reviews: List[Tuple[str, str]] = []

    for index, (session, _) in enumerate(users, start=1):
        # Personal Lists (2-4 per user, each with 4-8 movies)
        num_lists = random_generator.randint(2, 4)
        chosen_lists = random_generator.sample(LIST_TEMPLATES, k=num_lists)

        for list_name, list_description in chosen_lists:
            actions.create_list(session, list_name, description=list_description)
            list_movies = random_generator.sample(movies, k=min(len(movies), random_generator.randint(4, 8)))

            for movie in list_movies:
                actions.add_movie_to_list(
                    session,
                    list_name,
                    str(movie.get("title") or ""),
                    poster_url=str(movie.get("poster_url") or ""),
                    description=list_description,
                )

        # Reviews (5-9 per user, automatically marks watched and optionally liked)
        num_reviews = random_generator.randint(5, min(9, len(movies)))
        review_movies = random_generator.sample(movies, k=num_reviews)
        reviewed_titles = set()

        for movie in review_movies:
            title = str(movie.get("title") or "").strip()

            if not title:
                continue

            year = int(movie.get("release_year") or 2020)
            rating = random_generator.choice(RATING_OPTIONS)
            liked = random_generator.random() < 0.65
            viewed_on = random_generator.choice(VIEWED_ON_OPTIONS)
            content = random_generator.choice(REVIEW_TEMPLATES)
            ok, _ = actions.create_review(
                session,
                movie_title=title,
                release_year=year,
                rating=rating,
                content=content,
                liked=liked,
                viewed_on=viewed_on,
            )

            if ok:
                reviewed_titles.add(title.lower())
                created_reviews.append((session.username, title))

        # Extra watched & liked movies beyond reviewed ones
        remaining = [m for m in movies if str(m.get("title") or "").lower() not in reviewed_titles]
        extra_watched = random_generator.sample(remaining, k=min(len(remaining), random_generator.randint(4, 7)))

        for movie in extra_watched:
            title = str(movie.get("title") or "").strip()

            if not title:
                continue

            # Ensure watched without toggling off if already watched
            movie_document = database["movies"].find_one({"_id": movie["_id"]}, {"watched_by": 1, "liked_by": 1})
            watched_by = {str(u).lower() for u in ((movie_document or {}).get("watched_by") or [])}

            if session.username.lower() not in watched_by:
                actions.mark_movie_watched(session, title)

            liked_by = {str(u).lower() for u in ((movie_document or {}).get("liked_by") or [])}
            if random_generator.random() < 0.5 and session.username.lower() not in liked_by:
                actions.like_movie(session, title)

        print(
            f"  [{index}/{len(users)}] @{session.username}: "
            f"{num_lists} lists, {len(reviewed_titles)} reviews, +{len(extra_watched)} watched"
        )

    return created_reviews


def populate_social_interactions(
    db: Any,
    actions: ActionService,
    users: List[Tuple[UserSession, str]],
    created_reviews: List[Tuple[str, str]],
    rng: random.Random,
) -> None:
    """Forces dense follow graphs and cross-user review likes."""
    print("\n=== [4/4] Generating social interactions (follows & review likes) ===")
    total_follows = 0
    total_review_likes = 0

    all_sessions = [s for s, _ in users]
    for session in all_sessions:
        others = [o for o in all_sessions if o.username.lower() != session.username.lower()]
        follow_targets = rng.sample(others, k=min(len(others), rng.randint(6, 12)))
        for target in follow_targets:
            ok, _ = actions.follow_user(session, target.username)
            if ok:
                total_follows += 1

        # Like 10-18 reviews authored by other users
        other_reviews = [
            (owner, title)
            for owner, title in created_reviews
            if owner.lower() != session.username.lower()
        ]
        if other_reviews:
            picks = rng.sample(other_reviews, k=min(len(other_reviews), rng.randint(10, 18)))
            for owner, title in picks:
                # Only like if not already liked so we don't toggle off an existing like
                rev_doc = db["reviews"].find_one(
                    {"owner.username": owner, "movie.title": title},
                    {"liked_by": 1},
                )
                liked_by = {str(u).lower() for u in ((rev_doc or {}).get("liked_by") or [])}
                if session.username.lower() not in liked_by:
                    ok, _ = actions.like_review(session, title, owner)
                    if ok:
                        total_review_likes += 1

    print(f"  Summary -> follows_created={total_follows}, review_likes_created={total_review_likes}")


def export_users_file(
    users: List[Tuple[UserSession, str]],
    output_path: Path = OUTPUT_USERS_FILE,
) -> Path:
    """Writes all created test users and their passwords to `users.txt`."""
    lines = [
        "# MovieVault Demo Users",
        "# Format: username | email | password",
        "#" + "-" * 60,
    ]
    for session, password in users:
        email = session.email or f"{session.username}@movievault.demo"
        lines.append(f"{session.username} | {email} | {password}")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n✔ Exported {len(users)} users to {output_path}")
    return output_path


def run_populate(seed: int = 42) -> int:
    random_generator = random.Random(seed)
    database = _connect_mongo()
    movies = populate_movies(database, target_count=TARGET_MOVIES)

    auth = AuthService()
    actions = ActionService()

    users = create_test_users(auth, USER_PROFILES[:TARGET_USERS])
    created_reviews = populate_user_activity(database, actions, users, movies, random_generator)
    populate_social_interactions(database, actions, users, created_reviews, random_generator)
    export_users_file(users, OUTPUT_USERS_FILE)
    return 0


def main() -> None:
    run_populate()
    close_all_connections()


if __name__ == "__main__":
    main()
