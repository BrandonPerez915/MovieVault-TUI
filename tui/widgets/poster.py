"""
Terminal poster widget for MovieVault (backend/tui/widgets/poster.py).

Renders movie posters and actor/director photos in the background
using `@work(thread=True)` and `PosterService` (`rich-pixels` + `Pillow`),
with immediate fallback to an accessible text frame when there is no image
or when text-only mode (`--no-posters` / key `p`) is active.
"""

from typing import Any, Optional

from textual import work
from textual.timer import Timer
from textual.widgets import Static
from textual.worker import get_current_worker

from services.PosterService import PosterService
from tui.widgets.loading_spinner import SPINNER_FRAMES


def _build_placeholder_markup(title: str, width: int, height: int, subtitle: str = "NO POSTER") -> str:
    clean_title = (title or "Movie").strip()
    inner_w = max(8, width - 4)
    lines = [
        f"[dim]┌{'─' * (inner_w + 2)}┐[/]",
        f"[dim]│[/] [bold #79c0ff]{subtitle[:inner_w]:^{inner_w}}[/] [dim]│[/]",
        f"[dim]├{'─' * (inner_w + 2)}┤[/]",
    ]
    words = clean_title.split()
    wrapped: list[str] = []
    curr = ""
    for w in words:
        if len(curr) + len(w) + 1 <= inner_w:
            curr = f"{curr} {w}".strip()
        else:
            if curr:
                wrapped.append(curr)
            curr = w[:inner_w]
    if curr:
        wrapped.append(curr)

    body_rows = max(2, height - 4)
    for row_idx in range(body_rows):
        txt = wrapped[row_idx] if row_idx < len(wrapped) else ""
        lines.append(f"[dim]│[/] {txt:^{inner_w}} [dim]│[/]")

    lines.append(f"[dim]└{'─' * (inner_w + 2)}┘[/]")
    return "\n".join(lines)


class PosterImage(Static):
    """Widget that downloads and renders a poster or photo in the background."""

    def __init__(
        self,
        poster_url: str = "",
        title: str = "",
        cells_width: int = 16,
        cells_height: int = 12,
        size: str = "w185",
        kind: str = "movie",
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__("", id=id, classes=classes)
        self._poster_url = (poster_url or "").strip()
        self._poster_title = (title or "").strip()
        self._poster_cells_w = cells_width
        self._poster_cells_h = cells_height
        self._poster_tmdb_size = size
        self._poster_kind = kind
        self._is_loading_poster: bool = False
        self._spinner_frame: int = 0
        self._spinner_timer: Optional[Timer] = None

    def on_mount(self) -> None:
        self._spinner_timer = self.set_interval(
            0.08,
            self._tick_poster_spinner,
            pause=True,
        )
        self.reload_poster()

    def _tick_poster_spinner(self) -> None:
        if not self._is_loading_poster:
            return
        self._spinner_frame = (self._spinner_frame + 1) % len(SPINNER_FRAMES)
        frame = SPINNER_FRAMES[self._spinner_frame]
        self.update(
            _build_placeholder_markup(
                self._poster_title,
                self._poster_cells_w,
                self._poster_cells_h,
                subtitle=f"{frame} LOADING...",
            )
        )

    def _stop_poster_spinner(self) -> None:
        self._is_loading_poster = False
        if self._spinner_timer is not None:
            self._spinner_timer.pause()

    def refresh_poster(self) -> None:
        self.reload_poster()

    def set_poster(self, poster_url: str, title: str = "") -> None:
        self._poster_url = (poster_url or "").strip()
        if title:
            self._poster_title = title.strip()
        self.reload_poster()

    def reload_poster(self) -> None:
        poster_svc = PosterService()
        if not poster_svc.enabled:
            self._stop_poster_spinner()
            self.update(
                _build_placeholder_markup(
                    self._poster_title,
                    self._poster_cells_w,
                    self._poster_cells_h,
                    subtitle="TEXT MODE",
                )
            )
            return

        if not self._poster_url:
            self._stop_poster_spinner()
            default_pixels = poster_svc.render_poster(
                path_or_url="",
                cells_width=self._poster_cells_w,
                cells_height=self._poster_cells_h,
                size=self._poster_tmdb_size,
                kind=self._poster_kind,
            )
            if default_pixels is not None:
                self.update(default_pixels)
            return

        self._is_loading_poster = True
        self._spinner_frame = 0
        frame = SPINNER_FRAMES[0]
        self.update(
            _build_placeholder_markup(
                self._poster_title,
                self._poster_cells_w,
                self._poster_cells_h,
                subtitle=f"{frame} LOADING...",
            )
        )
        if self._spinner_timer is not None:
            self._spinner_timer.resume()
        self._fetch_and_render_worker(
            self._poster_url,
            self._poster_title,
            self._poster_cells_w,
            self._poster_cells_h,
            self._poster_tmdb_size,
            self._poster_kind,
        )

    def _finish_poster_load(self, pixels: Any) -> None:
        self._stop_poster_spinner()
        if pixels is not None:
            self.update(pixels)

    @work(thread=True, exclusive=True)
    def _fetch_and_render_worker(
        self,
        url: str,
        title: str,
        cells_w: int,
        cells_h: int,
        size: str,
        kind: str = "movie",
    ) -> None:
        worker = get_current_worker()
        pixels = PosterService().render_poster(
            path_or_url=url,
            cells_width=cells_w,
            cells_height=cells_h,
            size=size,
            kind=kind,
        )
        if worker.is_cancelled:
            return
        self.app.call_from_thread(self._finish_poster_load, pixels)
