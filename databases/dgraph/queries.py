"""
Dgraph queries (DQL) repository for MovieVault (backend/databases/dgraph/queries.py).

This module encapsulates queries for Dgraph social and graph recommendation requirements
(Social recommendations of users and movies based on affinity graphs, lists,
directors, and actors) under the RecommendationsRepository pattern.
"""

from typing import Any, Dict, List, Optional
import pydgraph


class RecommendationsRepository:
    """
    Repository class for social recommendations and graph discovery queries in Dgraph.
    """

    def __init__(self, client: Optional[pydgraph.DgraphClient] = None) -> None:
        self.client = client

    def _resolve_client(
        self, client: Optional[pydgraph.DgraphClient] = None
    ) -> Optional[pydgraph.DgraphClient]:
        """Resolves the client to use: explicit argument or repository instance."""
        return client if client is not None else self.client

    def users_who_liked_my_review(
        self,
        username: str,
        favorite_movie_title: str,
        client: Optional[pydgraph.DgraphClient] = None,
    ) -> List[Dict[str, Any]]:
        """
        User recommendation based on liking my review.
        Query up to 10 users to add as friends who liked reviews written about
        favorite movie, sorted by popularity and watched count.
        Expected columns: username, followers, views_count.
        """
        _active_client = self._resolve_client(client)
        # TODO: Implement DQL query in Dgraph
        return []

    def movies_watched_by_friends(
        self,
        username: str,
        min_rating: float = 4.0,
        client: Optional[pydgraph.DgraphClient] = None,
    ) -> List[Dict[str, Any]]:
        """
        Movie recommendations watched recently by friends with rating >= threshold.
        Expected columns: movie_title, release_year, friends_rating.
        """
        _active_client = self._resolve_client(client)
        # TODO: Implement DQL query in Dgraph
        return []

    def same_genre_not_in_personal_list(
        self,
        username: str,
        list_name: str,
        selected_movie_title: str,
        client: Optional[pydgraph.DgraphClient] = None,
    ) -> List[Dict[str, Any]]:
        """
        Recommendation of same-genre movies not in personal list.
        Expected columns: movie_title, release_year, genre, impact_score.
        """
        _active_client = self._resolve_client(client)
        # TODO: Implement DQL query in Dgraph
        return []

    def movies_liked_by_friends_same_director(
        self,
        username: str,
        client: Optional[pydgraph.DgraphClient] = None,
    ) -> List[Dict[str, Any]]:
        """
        Recommendation of movies liked by friends sharing a director with a movie the user liked.
        Expected columns: movie_title, release_year, director, impact_score.
        """
        _active_client = self._resolve_client(client)
        # TODO: Implement DQL query in Dgraph
        return []

    def movies_sharing_actor_with_liked_movie(
        self,
        username: str,
        list_name: str,
        client: Optional[pydgraph.DgraphClient] = None,
    ) -> List[Dict[str, Any]]:
        """
        Recommendation of movies sharing an actor with a movie the user liked.
        Expected columns: movie_title, release_year, shared_actor, impact_score.
        """
        _active_client = self._resolve_client(client)
        # TODO: Implement DQL query in Dgraph
        return []

    def friends_by_shared_taste(
        self,
        username: str,
        min_rating: float = 4.0,
        min_shared_movies: int = 5,
        client: Optional[pydgraph.DgraphClient] = None,
    ) -> List[Dict[str, Any]]:
        """
        Recommendation of potential friends based on shared taste.
        Expected columns: username, followers, views_count, shared_movies_count.
        """
        _active_client = self._resolve_client(client)
        # TODO: Implement DQL query in Dgraph
        return []

    def movies_in_own_list_liked_by_friends(
        self,
        username: str,
        list_name: str,
        client: Optional[pydgraph.DgraphClient] = None,
    ) -> List[Dict[str, Any]]:
        """
        Recommendation of unwatched movies in user's list liked by friends.
        Expected columns: movie_title, release_year, duration_minutes, avg_rating.
        """
        _active_client = self._resolve_client(client)
        # TODO: Implement DQL query in Dgraph
        return []

    def movies_by_recent_actor_director_combo(
        self,
        username: str,
        client: Optional[pydgraph.DgraphClient] = None,
    ) -> List[Dict[str, Any]]:
        """
        Movie recommendations by Actor + Director pair from a movie liked in last 7 days.
        Expected columns: movie_title, release_year, actor, director, impact_score.
        """
        _active_client = self._resolve_client(client)
        # TODO: Implement DQL query in Dgraph
        return []


# Default singleton instance
recommendations_repository = RecommendationsRepository()


# Module-level convenience functions delegating to default repository
def users_who_liked_my_review(
    username: str,
    favorite_movie_title: str,
    client: Optional[pydgraph.DgraphClient] = None,
) -> List[Dict[str, Any]]:
    return recommendations_repository.users_who_liked_my_review(
        username=username,
        favorite_movie_title=favorite_movie_title,
        client=client,
    )


def movies_watched_by_friends(
    username: str,
    min_rating: float = 4.0,
    client: Optional[pydgraph.DgraphClient] = None,
) -> List[Dict[str, Any]]:
    return recommendations_repository.movies_watched_by_friends(
        username=username,
        min_rating=min_rating,
        client=client,
    )


def same_genre_not_in_personal_list(
    username: str,
    list_name: str,
    selected_movie_title: str,
    client: Optional[pydgraph.DgraphClient] = None,
) -> List[Dict[str, Any]]:
    return recommendations_repository.same_genre_not_in_personal_list(
        username=username,
        list_name=list_name,
        selected_movie_title=selected_movie_title,
        client=client,
    )


def movies_liked_by_friends_same_director(
    username: str,
    client: Optional[pydgraph.DgraphClient] = None,
) -> List[Dict[str, Any]]:
    return recommendations_repository.movies_liked_by_friends_same_director(
        username=username,
        client=client,
    )


def movies_sharing_actor_with_liked_movie(
    username: str,
    list_name: str,
    client: Optional[pydgraph.DgraphClient] = None,
) -> List[Dict[str, Any]]:
    return recommendations_repository.movies_sharing_actor_with_liked_movie(
        username=username,
        list_name=list_name,
        client=client,
    )


def friends_by_shared_taste(
    username: str,
    min_rating: float = 4.0,
    min_shared_movies: int = 5,
    client: Optional[pydgraph.DgraphClient] = None,
) -> List[Dict[str, Any]]:
    return recommendations_repository.friends_by_shared_taste(
        username=username,
        min_rating=min_rating,
        min_shared_movies=min_shared_movies,
        client=client,
    )


def movies_in_own_list_liked_by_friends(
    username: str,
    list_name: str,
    client: Optional[pydgraph.DgraphClient] = None,
) -> List[Dict[str, Any]]:
    return recommendations_repository.movies_in_own_list_liked_by_friends(
        username=username,
        list_name=list_name,
        client=client,
    )


def movies_by_recent_actor_director_combo(
    username: str,
    client: Optional[pydgraph.DgraphClient] = None,
) -> List[Dict[str, Any]]:
    return recommendations_repository.movies_by_recent_actor_director_combo(
        username=username,
        client=client,
    )
