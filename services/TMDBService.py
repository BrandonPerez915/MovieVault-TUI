"""
TMDB (The Movie Database) HTTP API v3 client for MovieVault
(backend/services/TMDBService.py).

Encapsulates all HTTP requests to TMDB with a reusable session, basic
rate limiting (~35 req/s), HTTP 429 retry, and in-memory caching for
static catalogs (genres and countries).
"""

import time
from typing import Any, Dict, List, Optional
import requests

from config import TMDB_API_URL, TMDB_IMAGE_URL, TMDB_READ_ACCESS_TOKEN


class TMDBService:
    """Pure HTTP client for TMDB API v3 (Singleton)."""

    _instance: Optional["TMDBService"] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "TMDBService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, timeout_seconds: float = 8.0) -> None:
        if getattr(self, "_initialized", False):
            return
        self._base_url = TMDB_API_URL.rstrip("/")
        raw_img = TMDB_IMAGE_URL.rstrip("/")
        if "/t/p/" in raw_img:
            self._image_root_url = raw_img.split("/t/p/")[0] + "/t/p"
        else:
            self._image_root_url = "https://image.tmdb.org/t/p"
        self._default_image_base_url = raw_img
        self._token = TMDB_READ_ACCESS_TOKEN.strip()
        self._timeout = timeout_seconds
        self._session = requests.Session()
        self._last_request_ts: float = 0.0
        self._min_interval_sec: float = 0.028  # ~35 req/s
        self._genre_cache: Optional[Dict[str, int]] = None
        self._country_cache: Optional[Dict[str, str]] = None
        self._initialized = True

    @property
    def is_configured(self) -> bool:
        """Indicates whether the TMDB read access token is configured."""
        return bool(self._token)

    def build_image_url(self, path: Optional[str], size: str = "w500") -> str:
        """Constructs full TMDB image URL at the requested size."""
        if not path:
            return ""
        clean = path.strip()
        if clean.startswith("http://") or clean.startswith("https://"):
            if "/t/p/" in clean and size:
                prefix, rest = clean.split("/t/p/", 1)
                parts = rest.split("/", 1)
                if len(parts) == 2:
                    return f"{prefix}/t/p/{size}/{parts[1]}"
            return clean
        if not clean.startswith("/"):
            clean = f"/{clean}"
        return f"{self._image_root_url}/{size}{clean}"

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }

    def _throttle(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_request_ts
        if elapsed < self._min_interval_sec:
            time.sleep(self._min_interval_sec - elapsed)
        self._last_request_ts = time.monotonic()

    def get_json(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Performs a GET request to TMDB with simple retry on HTTP 429."""
        if not self.is_configured:
            return {}

        self._throttle()
        url = f"{self._base_url}/{path.lstrip('/')}"
        response = self._session.get(
            url,
            headers=self._headers(),
            params=params or {},
            timeout=self._timeout,
        )
        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", "1.5"))
            time.sleep(min(retry_after, 5.0))
            response = self._session.get(
                url,
                headers=self._headers(),
                params=params or {},
                timeout=self._timeout,
            )
        response.raise_for_status()
        return response.json()

    def popular(self, page: int = 1) -> List[Dict[str, Any]]:
        """Fetches a page of popular movies (`/movie/popular`)."""
        data = self.get_json("/movie/popular", params={"page": max(1, page)})
        return data.get("results", [])

    def search_movies(self, query: str, page: int = 1) -> List[Dict[str, Any]]:
        """Searches movies by title (`/search/movie`)."""
        clean = (query or "").strip()
        if not clean:
            return []
        data = self.get_json(
            "/search/movie",
            params={"query": clean, "include_adult": "false", "page": max(1, page)},
        )
        return data.get("results", [])

    def discover(self, **filters: Any) -> List[Dict[str, Any]]:
        """Queries `/discover/movie` with given filters."""
        params: Dict[str, Any] = {
            "include_adult": "false",
            "sort_by": "popularity.desc",
        }
        params.update({k: v for k, v in filters.items() if v is not None and v != ""})
        data = self.get_json("/discover/movie", params=params)
        return data.get("results", [])

    def movie_details(self, tmdb_id: int) -> Dict[str, Any]:
        """Fetches full movie details with credits and watch providers."""
        return self.get_json(
            f"/movie/{tmdb_id}",
            params={"append_to_response": "credits,watch/providers,keywords"},
        )

    def person_details(self, person_id: int) -> Dict[str, Any]:
        """Fetches full biographical details of a person (`/person/{id}`)."""
        return self.get_json(f"/person/{person_id}")

    def person_movie_credits(self, person_id: int) -> Dict[str, Any]:
        """Fetches filmography of a person (`/person/{id}/movie_credits`)."""
        return self.get_json(f"/person/{person_id}/movie_credits")

    def search_person(self, name: str) -> List[Dict[str, Any]]:
        """Searches actors or directors by name (`/search/person`)."""
        clean = (name or "").strip()
        if not clean:
            return []
        data = self.get_json(
            "/search/person",
            params={"query": clean, "include_adult": "false", "page": 1},
        )
        return data.get("results", [])

    def search_keyword(self, text: str) -> List[Dict[str, Any]]:
        """Searches keywords in TMDB (`/search/keyword`)."""
        clean = (text or "").strip()
        if not clean:
            return []
        data = self.get_json("/search/keyword", params={"query": clean, "page": 1})
        return data.get("results", [])

    def genre_map(self) -> Dict[str, int]:
        """Returns a `{lowercase_name: genre_id}` dictionary in English and Spanish."""
        if self._genre_cache is not None:
            return self._genre_cache

        mapping: Dict[str, int] = {
            "action": 28,
            "accion": 28,
            "acción": 28,
            "adventure": 12,
            "aventura": 12,
            "animation": 16,
            "animacion": 16,
            "animación": 16,
            "comedy": 35,
            "comedia": 35,
            "crime": 80,
            "crimen": 80,
            "documentary": 99,
            "documental": 99,
            "drama": 18,
            "family": 10751,
            "familia": 10751,
            "fantasy": 14,
            "fantasia": 14,
            "fantasía": 14,
            "history": 36,
            "historia": 36,
            "horror": 27,
            "terror": 27,
            "music": 10402,
            "musica": 10402,
            "música": 10402,
            "mystery": 9648,
            "misterio": 9648,
            "romance": 10749,
            "science fiction": 878,
            "sci-fi": 878,
            "ciencia ficcion": 878,
            "ciencia ficción": 878,
            "thriller": 53,
            "suspenso": 53,
            "war": 10752,
            "guerra": 10752,
            "western": 37,
        }
        try:
            data = self.get_json("/genre/movie/list", params={"language": "en"})
            for g in data.get("genres", []):
                if g.get("name") and g.get("id"):
                    mapping[g["name"].strip().lower()] = int(g["id"])
        except Exception:
            pass

        self._genre_cache = mapping
        return mapping

    def resolve_genre_id(self, genre_name: str) -> Optional[int]:
        """Resolves TMDB genre ID from an English or Spanish genre name."""
        clean = (genre_name or "").strip().lower()
        if not clean:
            return None
        gmap = self.genre_map()
        if clean in gmap:
            return gmap[clean]
        for key, gid in gmap.items():
            if clean in key or key in clean:
                return gid
        return None

    def resolve_country_code(self, country: str) -> Optional[str]:
        """Resolves a country name or code to a 2-letter ISO-3166-1 code."""
        clean = (country or "").strip()
        if not clean:
            return None
        if len(clean) == 2 and clean.isalpha():
            return clean.upper()

        common = {
            "usa": "US",
            "united states": "US",
            "united states of america": "US",
            "estados unidos": "US",
            "mexico": "MX",
            "méxico": "MX",
            "uk": "GB",
            "united kingdom": "GB",
            "reino unido": "GB",
            "france": "FR",
            "francia": "FR",
            "spain": "ES",
            "españa": "ES",
            "south korea": "KR",
            "corea del sur": "KR",
            "korea": "KR",
            "japan": "JP",
            "japon": "JP",
            "japón": "JP",
            "italy": "IT",
            "italia": "IT",
            "germany": "DE",
            "alemania": "DE",
            "canada": "CA",
            "canadá": "CA",
            "argentina": "AR",
            "brazil": "BR",
            "brasil": "BR",
        }
        low = clean.lower()
        if low in common:
            return common[low]

        if self._country_cache is None:
            self._country_cache = {}
            try:
                rows = self.get_json("/configuration/countries")
                if isinstance(rows, list):
                    for item in rows:
                        iso = item.get("iso_3166_1")
                        eng = (item.get("english_name") or "").strip().lower()
                        nat = (item.get("native_name") or "").strip().lower()
                        if iso and eng:
                            self._country_cache[eng] = iso
                        if iso and nat:
                            self._country_cache[nat] = iso
            except Exception:
                pass

        return self._country_cache.get(low)
