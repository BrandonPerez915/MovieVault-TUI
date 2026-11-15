"""
Accessible state component (Loading / Empty / Error / Success)
(backend/tui/widgets/state_message.py).

Always pairs symbol + explicit label alongside color to guarantee
accessibility in monochrome terminals and for color-blind users.
"""

from textual.widgets import Static


class StateMessage(Static):
    """Displays clear states for loading, empty results, or errors."""

    def show_loading(self, text: str = "Querying catalog...") -> None:
        self.display = True
        self.update(f"[bold #58a6ff]⏳ LOADING:[/] {text}")

    def show_empty(
        self,
        title: str = "No results found.",
        hint: str = "Try adjusting the filters or populating the catalog.",
    ) -> None:
        self.display = True
        self.update(f"[bold #f0883e]∅ NO RESULTS:[/] {title}\n[dim]{hint}[/]")

    def show_error(self, message: str) -> None:
        self.display = True
        self.update(f"[bold #f85149]✖ ERROR:[/] {message}")

    def show_success(self, message: str) -> None:
        self.display = True
        self.update(f"[bold #3fb950]✔ READY:[/] {message}")

    def clear_state(self) -> None:
        self.display = False
        self.update("")
