"""
Accessible state component (Loading / Empty / Error / Success)
(backend/tui/widgets/state_message.py).

Always pairs symbol + explicit label alongside color to guarantee
accessibility in monochrome terminals and for color-blind users.
"""

from tui.toast import show_error_toast
from tui.widgets.loading_spinner import LoadingSpinner


EMPTY_MASCOT_ART = (
    "[bold #58a6ff]"
    "      .---.\n"
    "     / o o \\   🎬\n"
    "    |   ^   | /\n"
    "    |  '-'  |/\n"
    "   /|=======|\\\n"
    "  (_| VAULT |_)\n"
    "    |_______|\n"
    "     _|   |_"
    "[/]"
)


class StateMessage(LoadingSpinner):
    """Displays clear states for loading (with animated spinner), empty results, or errors."""

    def show_loading(self, text: str = "Querying catalog...") -> None:
        self.remove_class("empty-state")
        self.start_spinner(text)

    def show_empty(
        self,
        title: str = "No results found.",
        hint: str = "Try adjusting the filters or populating the catalog.",
    ) -> None:
        self.stop_spinner(hide=False)
        self.add_class("empty-state")
        self.display = True
        self.update(
            f"{EMPTY_MASCOT_ART}\n\n"
            f"[bold #f0883e]∅ NO RESULTS FOUND[/]\n"
            f"[bold #f0f6fc]{title}[/]\n\n"
            f"[dim]{hint}[/]"
        )

    def show_error(self, message: str) -> None:
        self.remove_class("empty-state")
        self.stop_spinner(hide=True)
        show_error_toast(self, message)

    def show_success(self, message: str) -> None:
        self.remove_class("empty-state")
        self.stop_spinner(hide=False)
        self.display = True
        self.update(f"[bold #3fb950]✔ READY:[/] {message}")

    def clear_state(self) -> None:
        self.remove_class("empty-state")
        self.stop_spinner(hide=True)
