"""
MovieVault — Main Entry Point (main.py).

Command line options:
- `python main.py`               : Launches the interactive TUI application.
- `python main.py --no-posters`  : Launches the TUI in text mode without rendering posters.
- `python main.py --seed <N>`    : Populates MongoDB with `N` popular movies from TMDB
                                           (recursive: movie + directors + actors without duplicates).
- `python main.py --status`      : Runs connection diagnostics and verifies all 24 requirements.
"""

import sys

from databases import get_databases_status, MongoConnection, close_all_connections
from services.AuthService import AuthService
from services.CatalogService import CatalogService
from services.PosterService import PosterService
from services.QueryService import QUERIES, execute_query
from tui.app import MovieVaultApp


def run_self_diagnostic() -> int:
    """
    Runs a quick diagnostic of connection status (MongoDB, Cassandra, and Dgraph)
    and verifies the catalog of all 24 requirements.
    """
    print("=== MovieVault Connection Status ===")
    for engine, state in get_databases_status().items():
        print(f"  - {engine}: {state}")

    auth = AuthService()
    users = auth.list_demo_users()
    print(f"\n[AuthService] Registered users in MongoDB: {len(users)}")

    print(f"\n[QueryService] Verifying {len(QUERIES)} registered requirements:")
    for spec in QUERIES:
        res = execute_query(spec.id, {})
        print(
            f"  [{res.database}] ({res.query_id}) {res.title} -> "
            f"columns={res.columns} | rows={len(res.rows)} | {res.execution_ms:.2f} ms"
        )

    return 0


def run_cli_seed(count: int) -> int:
    """Populates MongoDB with `count` popular movies from TMDB showing progress."""
    try:
        mongo = MongoConnection()
        db = mongo.database if mongo.initialized else None
    except Exception:
        db = None

    if db is None:
        print("✖ Error: MongoDB is not connected. Check your instance before running --seed.")
        return 1

    print(f"=== Starting recursive population of {count} popular movies from TMDB ===")

    def _on_step(curr: int, total: int, title: str, status: str) -> None:
        symbol = "✔ NEW" if status == "new" else ("↷ EXISTING" if status == "skipped" else "✖ ERROR")
        print(f"  [{curr}/{total}] {symbol}: {title}")

    report = CatalogService().populate_popular(
        db=db,
        n=count,
        include_person_details=True,
        on_progress=_on_step,
    )
    print("\n=== Population Summary ===")
    print(f"  • Requested movies : {report.requested}")
    print(f"  • Processed movies : {report.processed}")
    print(f"  • New movies       : {report.new_movies}")
    print(f"  • Skipped movies   : {report.skipped_existing}")
    print(f"  • New actors       : {report.new_actors}")
    print(f"  • New directors    : {report.new_directors}")
    print(f"  • Errors           : {report.errors}")
    return 0


def main() -> None:
    """Launches the interactive TUI application or executes administrative commands."""
    args = sys.argv[1:]

    try:
        if "--no-posters" in args:
            PosterService().set_enabled(False)

        if "--seed" in args:
            idx = args.index("--seed")
            n_val = 50
            if idx + 1 < len(args):
                try:
                    n_val = max(1, int(args[idx + 1]))
                except ValueError:
                    n_val = 50
            sys.exit(run_cli_seed(n_val))

        if "--status" in args or "--check" in args:
            sys.exit(run_self_diagnostic())

        app = MovieVaultApp()
        app.run()
    finally:
        try:
            close_all_connections()
        except Exception:
            pass


if __name__ == "__main__":
    main()
