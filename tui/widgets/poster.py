"""
Terminal poster widget for MovieVault (backend/tui/widgets/poster.py).

Renders movie posters and actor/director photos in the background
using `@work(thread=True)` and `PosterService` (`rich-pixels` + `Pillow`),
with immediate fallback to an accessible text frame when there is no image
or when text-only mode (`--no-posters` / key `p`) is active.
"""

from textual import work
from textual.widgets import Static
from textual.worker import get_current_worker

from services.PosterService import PosterService


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
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__("", id=id, classes=classes)
        self._poster_url = (poster_url or "").strip()
        self._poster_title = (title or "").strip()
        self._poster_cells_w = cells_width
        self._poster_cells_h = cells_height
        self._poster_tmdb_size = size

    def on_mount(self) -> None:
        self.reload_poster()

    def set_poster(self, poster_url: str, title: str = "") -> None:
        self._poster_url = (poster_url or "").strip()
        if title:
            self._poster_title = title.strip()
        self.reload_poster()

    def reload_poster(self) -> None:
        poster_svc = PosterService()
        if not poster_svc.enabled:
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
            self.update(
                _build_placeholder_markup(
                    self._poster_title,
                    self._poster_cells_w,
                    self._poster_cells_h,
                    subtitle="NO POSTER",
                )
            )
            return

        self.update(
            _build_placeholder_markup(
                self._poster_title,
                self._poster_cells_w,
                self._poster_cells_h,
                subtitle="LOADING...",
            )
        )
        self._fetch_and_render_worker(
            self._poster_url,
            self._poster_title,
            self._poster_cells_w,
            self._poster_cells_h,
            self._poster_tmdb_size,
        )

    @work(thread=True, exclusive=True)
    def _fetch_and_render_worker(
        self,
        url: str,
        title: str,
        cells_w: int,
        cells_h: int,
        size: str,
    ) -> None:
        worker = get_current_worker()
        pixels = PosterService().render_poster(
            path_or_url=url,
            cells_width=cells_w,
            cells_height=cells_h,
            size=size,
        )
        if worker.is_cancelled:
            return
        if pixels is not None:
            self.app.call_from_thread(self.update, pixels)
        else:
            fallback = _build_placeholder_markup(
                title, cells_w, cells_h, subtitle="NO POSTER"
            )
            self.app.call_from_thread(self.update, fallback)
