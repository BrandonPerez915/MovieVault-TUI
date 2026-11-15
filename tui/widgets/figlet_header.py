"""
Reusable PyFiglet ASCII header widget and markup helper (`FigletHeader`)
(tui/widgets/figlet_header.py).
"""

from rich.text import Text
from textual.widgets import Static
import pyfiglet


def render_figlet_markup(
    text: str,
    *,
    font: str = "smslant",
    color: str = "#58a6ff",
    subtitle: str = "",
    max_plain_len: int | None = None,
) -> Text:
    """Renders `text` with pyfiglet as a Rich Text object, optionally appending a dim subtitle."""
    clean_text = (text or "").strip()
    use_plain = max_plain_len is not None and len(clean_text) > max_plain_len
    if not use_plain and pyfiglet is not None and clean_text:
        try:
            raw_ascii = pyfiglet.figlet_format(clean_text, font=font, width=120)
        except Exception:
            raw_ascii = pyfiglet.figlet_format(clean_text, font="standard", width=120)
        lines = [line.rstrip() for line in raw_ascii.splitlines()]
        while lines and not lines[-1]:
            lines.pop()
        while lines and not lines[0]:
            lines.pop(0)
        if lines:
            max_w = max(len(line) for line in lines)
            ascii_body = "\n".join(line.ljust(max_w) for line in lines)
        else:
            ascii_body = clean_text
    else:
        ascii_body = clean_text

    rendered = Text(ascii_body, style=f"bold {color}")
    if subtitle:
        rendered.append(f"\n\n{subtitle}", style="dim")
    return rendered


class FigletHeader(Static):
    """Visual PyFiglet header separated from the content below it."""

    def __init__(
        self,
        title: str,
        *,
        font: str = "smslant",
        color: str = "#58a6ff",
        subtitle: str = "",
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        merged_classes = f"figlet-header {classes}".strip() if classes else "figlet-header"
        super().__init__(
            render_figlet_markup(title, font=font, color=color, subtitle=subtitle),
            id=id,
            classes=merged_classes,
        )
        self._figlet_font = font
        self._figlet_color = color

    def set_header(
        self,
        title: str,
        *,
        subtitle: str = "",
        color: str | None = None,
        max_plain_len: int | None = None,
    ) -> None:
        """Updates the figlet header title and subtitle dynamically."""
        self.update(
            render_figlet_markup(
                title,
                font=self._figlet_font,
                color=color or self._figlet_color,
                subtitle=subtitle,
                max_plain_len=max_plain_len,
            )
        )
