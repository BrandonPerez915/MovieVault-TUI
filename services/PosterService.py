"""
Poster download, disk cache, and terminal rendering service for MovieVault
(backend/services/PosterService.py).

Uses `Pillow` (`LANCZOS`) and `rich_pixels.Pixels` (`HalfcellRenderer`) to
convert movie posters and actor/director photos into Unicode color blocks
compatible with Python 3.11 and any terminal emulator.
"""

from collections import OrderedDict
import hashlib
from io import BytesIO
from pathlib import Path
from typing import Any, Optional, Tuple

from PIL import Image
import requests
from rich_pixels import HalfcellRenderer, Pixels

from config import ROOT_DIR
from services.TMDBService import TMDBService

CACHE_DIR = ROOT_DIR / "data" / "cache" / "posters"


class PosterService:
    """Manages downloading, memory/disk caching, and conversion to `Pixels` (Singleton)."""

    _instance: Optional["PosterService"] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "PosterService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, max_memory_items: int = 128) -> None:
        if getattr(self, "_initialized", False):
            return
        self._enabled: bool = True
        self._max_memory = max_memory_items
        self._memory_cache: "OrderedDict[str, Image.Image]" = OrderedDict()
        self._session = requests.Session()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._initialized = True

    @property
    def enabled(self) -> bool:
        """Indicates whether image rendering is enabled."""
        return self._enabled

    def set_enabled(self, value: bool) -> None:
        """Globally enables or disables poster rendering (`--no-posters` / `p` key)."""
        self._enabled = bool(value)

    def toggle_enabled(self) -> bool:
        """Toggles poster rendering state and returns the new value."""
        self._enabled = not self._enabled
        return self._enabled

    def _normalize_url(self, path_or_url: str, size: str = "w185") -> str:
        clean = (path_or_url or "").strip()
        if not clean:
            return ""
        return TMDBService().build_image_url(clean, size=size)

    def _cache_file_for_url(self, url: str) -> Path:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return CACHE_DIR / f"{digest}.jpg"

    def _remember_in_memory(self, key: str, img: Image.Image) -> None:
        self._memory_cache[key] = img
        self._memory_cache.move_to_end(key)
        while len(self._memory_cache) > self._max_memory:
            self._memory_cache.popitem(last=False)

    def get_image(self, path_or_url: str, size: str = "w185") -> Optional[Image.Image]:
        """
        Retrieves a `PIL.Image.Image` from:
        1. Memory LRU cache
        2. Disk cache (`backend/data/cache/posters/`)
        3. HTTP download or local file
        """
        if not self._enabled or not path_or_url or not path_or_url.strip():
            return None

        clean = path_or_url.strip()
        local_path = Path(clean)
        if local_path.is_file():
            try:
                with Image.open(local_path) as im:
                    loaded = im.convert("RGB")
                self._remember_in_memory(clean, loaded)
                return loaded
            except Exception:
                return None

        url = self._normalize_url(clean, size=size)
        if not url:
            return None

        if url in self._memory_cache:
            self._memory_cache.move_to_end(url)
            return self._memory_cache[url]

        cache_file = self._cache_file_for_url(url)
        if cache_file.is_file():
            try:
                with Image.open(cache_file) as im:
                    loaded = im.convert("RGB")
                self._remember_in_memory(url, loaded)
                return loaded
            except Exception:
                pass

        try:
            resp = self._session.get(url, timeout=6.0)
            resp.raise_for_status()
            with Image.open(BytesIO(resp.content)) as im:
                loaded = im.convert("RGB")
            try:
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                loaded.save(cache_file, format="JPEG", quality=85)
            except Exception:
                pass
            self._remember_in_memory(url, loaded)
            return loaded
        except Exception:
            return None

    def to_pixels(
        self,
        image: Image.Image,
        cells_width: int = 16,
        cells_height: Optional[int] = None,
    ) -> Pixels:
        """
        Resizes `image` with `LANCZOS` filter preserving poster aspect ratio
        (2:3) and converts it into a `rich_pixels.Pixels` object with `HalfcellRenderer`.

        Each height cell in the terminal contains 2 vertical pixels (half-cell `▀`),
        so `pixel_height = cells_height * 2`.
        """
        w_cells = max(6, int(cells_width))
        if cells_height is None:
            # 2:3 aspect ratio on screen considering 1 cell ≈ 1x2 pixels
            h_cells = max(4, round(w_cells * 0.75))
        else:
            h_cells = max(4, int(cells_height))

        target_size: Tuple[int, int] = (w_cells, h_cells * 2)
        resized = image.convert("RGB").resize(target_size, Image.Resampling.LANCZOS)
        return Pixels.from_image(resized, renderer=HalfcellRenderer())

    def render_poster(
        self,
        path_or_url: str,
        cells_width: int = 16,
        cells_height: Optional[int] = None,
        size: str = "w185",
    ) -> Optional[Pixels]:
        """Downloads/retrieves the image and returns its `Pixels` renderable ready for Textual."""
        img = self.get_image(path_or_url, size=size)
        if img is None:
            return None
        return self.to_pixels(img, cells_width=cells_width, cells_height=cells_height)
