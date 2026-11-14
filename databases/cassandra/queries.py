"""
Apache Cassandra queries repository for MovieVault (backend/databases/cassandra/queries.py).

This module encapsulates queries for Cassandra activity requirements
(Watch history, reviews, review likes, list activity, and followed accounts history)
under the ActivityRepository pattern.

By default, queries with a time window consider the last 30 days from the
query timestamp, or the inclusive `[start_date, end_date]` range when
specified by the user.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from cassandra.cluster import Session


def resolve_date_range(
    start: Optional[str] = None,
    end: Optional[str] = None,
    day_range: int = 30,
) -> Tuple[datetime, datetime]:
    """
    Resolves the date range `[start_dt, end_dt]` (UTC).
    If valid YYYY-MM-DD dates are not provided, returns the last `default_days`
    days (default 30 days) leading up to the current timestamp.
    """
    now = datetime.now(timezone.utc)
    default_start = now - timedelta(days=day_range)

    start_datetime = default_start
    end_datetime = now

    if start and start.strip():
        try:
            parsed_start = datetime.strptime(start.strip(), "%Y-%m-%d")
            start_datetime = parsed_start.replace(tzinfo=timezone.utc)
        except ValueError:
            start_datetime = default_start

    if end and end.strip():
        try:
            parsed_end = datetime.strptime(end.strip(), "%Y-%m-%d")
            end_datetime = parsed_end.replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
        except ValueError:
            end_datetime = now

    return start_datetime, end_datetime


class ActivityRepository:
    """
    Repository class for user activity and history queries in Apache Cassandra.
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        self.session = session

    def _resolve_session(self, session: Optional[Session] = None) -> Optional[Session]:
        """Resolves the session to use: explicit argument or repository instance."""
        return session if session is not None else self.session

    def watch_history(
        self,
        username: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        session: Optional[Session] = None,
    ) -> List[Dict[str, Any]]:
        """
        User watch history.
        Query movie watch history for a user over the last 30 days or within date range.
        Expected columns: watch_date, movie_title, my_rating, liked, viewed_on.
        """
        _active_session = self._resolve_session(session)
        _start_dt, _end_dt = resolve_date_range(start_date, end_date)
        # TODO: Implement CQL query in Cassandra
        return []

    def watch_history_by_genre(
        self,
        username: str,
        genre: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        session: Optional[Session] = None,
    ) -> List[Dict[str, Any]]:
        """
        User watch history filtered by genre.
        Expected columns: watch_date, movie_title, my_rating, like, viewed_on.
        """
        _active_session = self._resolve_session(session)
        _start_dt, _end_dt = resolve_date_range(start_date, end_date)
        # TODO: Implement CQL query in Cassandra
        return []

    def reviews_history(
        self,
        username: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        session: Optional[Session] = None,
    ) -> List[Dict[str, Any]]:
        """
        User review history.
        Expected columns: movie_title, release_year, rating, liked, timestamp, review_content.
        """
        _active_session = self._resolve_session(session)
        _start_dt, _end_dt = resolve_date_range(start_date, end_date)
        # TODO: Implement CQL query in Cassandra
        return []

    def reviews_history_by_rating(
        self,
        username: str,
        min_rating: float,
        max_rating: float,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        session: Optional[Session] = None,
    ) -> List[Dict[str, Any]]:
        """
        User review history filtered by rating range.
        Expected columns: movie_title, release_year, rating, liked, timestamp, review_content.
        """
        _active_session = self._resolve_session(session)
        _start_dt, _end_dt = resolve_date_range(start_date, end_date)
        # TODO: Implement CQL query in Cassandra
        return []

    def movie_reviews_history(
        self,
        movie_title: str,
        session: Optional[Session] = None,
    ) -> List[Dict[str, Any]]:
        """
        Movie review history.
        Expected columns: movie_title, release_year, rating, username, liked, timestamp, review_content.
        """
        _active_session = self._resolve_session(session)
        # TODO: Implement CQL query in Cassandra
        return []

    def liked_reviews_history(
        self,
        username: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        session: Optional[Session] = None,
    ) -> List[Dict[str, Any]]:
        """
        User history of likes given to other reviews.
        Expected columns: username, review_owner, review_rating, liked, movie_title, timestamp.
        """
        _active_session = self._resolve_session(session)
        _start_dt, _end_dt = resolve_date_range(start_date, end_date)
        # TODO: Implement CQL query in Cassandra
        return []

    def list_activity_history(
        self,
        username: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        session: Optional[Session] = None,
    ) -> List[Dict[str, Any]]:
        """
        User activity history regarding lists.
        Expected columns: username, action, content, list_name, timestamp, film_count, list_owner, likes.
        """
        _active_session = self._resolve_session(session)
        _start_dt, _end_dt = resolve_date_range(start_date, end_date)
        # TODO: Implement CQL query in Cassandra
        return []

    def followed_accounts_history(
        self,
        username: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        session: Optional[Session] = None,
    ) -> List[Dict[str, Any]]:
        """
        History of accounts followed by user.
        Expected columns: username, followed_username, followers_count, timestamp.
        """
        _active_session = self._resolve_session(session)
        _start_dt, _end_dt = resolve_date_range(start_date, end_date)
        # TODO: Implement CQL query in Cassandra
        return []


# Default singleton instance
activity_repository = ActivityRepository()


# Module-level convenience functions delegating to default repository
def watch_history(
    username: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    session: Optional[Session] = None,
) -> List[Dict[str, Any]]:
    return activity_repository.watch_history(
        username=username,
        start_date=start_date,
        end_date=end_date,
        session=session,
    )


def watch_history_by_genre(
    username: str,
    genre: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    session: Optional[Session] = None,
) -> List[Dict[str, Any]]:
    return activity_repository.watch_history_by_genre(
        username=username,
        genre=genre,
        start_date=start_date,
        end_date=end_date,
        session=session,
    )


def reviews_history(
    username: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    session: Optional[Session] = None,
) -> List[Dict[str, Any]]:
    return activity_repository.reviews_history(
        username=username,
        start_date=start_date,
        end_date=end_date,
        session=session,
    )


def reviews_history_by_rating(
    username: str,
    min_rating: float,
    max_rating: float,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    session: Optional[Session] = None,
) -> List[Dict[str, Any]]:
    return activity_repository.reviews_history_by_rating(
        username=username,
        min_rating=min_rating,
        max_rating=max_rating,
        start_date=start_date,
        end_date=end_date,
        session=session,
    )


def movie_reviews_history(
    movie_title: str,
    session: Optional[Session] = None,
) -> List[Dict[str, Any]]:
    return activity_repository.movie_reviews_history(
        movie_title=movie_title,
        session=session,
    )


def liked_reviews_history(
    username: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    session: Optional[Session] = None,
) -> List[Dict[str, Any]]:
    return activity_repository.liked_reviews_history(
        username=username,
        start_date=start_date,
        end_date=end_date,
        session=session,
    )


def list_activity_history(
    username: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    session: Optional[Session] = None,
) -> List[Dict[str, Any]]:
    return activity_repository.list_activity_history(
        username=username,
        start_date=start_date,
        end_date=end_date,
        session=session,
    )


def followed_accounts_history(
    username: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    session: Optional[Session] = None,
) -> List[Dict[str, Any]]:
    return activity_repository.followed_accounts_history(
        username=username,
        start_date=start_date,
        end_date=end_date,
        session=session,
    )
