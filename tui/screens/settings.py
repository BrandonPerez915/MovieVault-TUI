"""
Application Settings Screen (`SettingsScreen`)
(tui/screens/settings.py).

Allows the user to configure MovieVault preferences:
- Color theme (`app.theme`)
- Poster & avatar terminal rendering (`PosterService().enabled`)
- Poster disk/memory cache management
- Resetting preferences to defaults
"""

from pathlib import Path
from typing import Optional

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Label, Select, Static, Switch

from services.PosterService import CACHE_DIR, PosterService
from services.SettingsService import SettingsService
from tui.toast import show_info_toast, show_success_toast
from tui.widgets.figlet_header import FigletHeader


def _format_theme_label(theme_name: str) -> str:
    """Formats a Textual theme identifier into a readable label."""
    return " ".join(part.capitalize() for part in theme_name.split("-"))


class SettingsScreen(Screen[bool]):
    """Full-screen settings view for MovieVault."""

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True, priority=True),
        Binding("ctrl+r", "reset_defaults", "Reset Defaults", show=True, priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._initial_posters = PosterService().enabled
        self._posters_changed = False
        self._suppress_events = False
        self._ready = False

    def on_mount(self) -> None:
        self.call_after_refresh(self._mark_ready)

    def _mark_ready(self) -> None:
        self._ready = True

    def compose(self) -> ComposeResult:
        settings = SettingsService()
        theme_options = [
            (_format_theme_label(name), name)
            for name in sorted(self.app.available_themes.keys())
        ]
        current_theme = settings.theme if settings.theme in self.app.available_themes else self.app.theme
        posters_enabled = settings.posters_enabled

        yield Static(
            "[bold #58a6ff]⚙️ SETTINGS[/]",
            id="top-bar",
        )

        with VerticalScroll(id="settings-scroll", classes="detail-page-scroll"):
            with Horizontal(classes="detail-top-actions"):
                yield Button("◀ Back [Esc]", variant="default", id="btn-settings-back")
                yield Button("Reset Defaults", variant="default", id="btn-settings-reset")

            yield FigletHeader(
                "Settings",
                font="slant",
                color="#79c0ff",
                subtitle="Customize appearance, poster rendering, navigation, and privacy.",
                id="settings-figlet-header",
            )

            with Vertical(id="settings-center-wrap"):
                with Vertical(id="settings-container"):
                    # Section 1: Appearance
                    with Vertical(classes="settings-section"):
                        yield Static(
                            "[bold #79c0ff]Appearance[/]",
                            classes="settings-section-title",
                        )
                        with Horizontal(classes="settings-row"):
                            with Vertical(classes="settings-label-col"):
                                yield Label("Color Theme", classes="settings-label")
                                yield Static(
                                    "[dim]Applies a Textual color palette across the app immediately.[/]",
                                    classes="settings-hint",
                                )
                            yield Select(
                                theme_options,
                                value=current_theme,
                                allow_blank=False,
                                id="select-app-theme",
                                classes="settings-select",
                            )
                        with Horizontal(classes="settings-row"):
                            with Vertical(classes="settings-label-col"):
                                yield Label("ASCII Figlet Headers", classes="settings-label")
                                yield Static(
                                    "[dim]Render large Figlet banners on main section headers.[/]",
                                    classes="settings-hint",
                                )
                            yield Switch(value=settings.figlet_headers, id="switch-figlet-headers")

                    # Section 2: Posters & Media
                    with Vertical(classes="settings-section"):
                        yield Static(
                            "[bold #79c0ff]Posters & Media[/]",
                            classes="settings-section-title",
                        )
                        with Horizontal(classes="settings-row"):
                            with Vertical(classes="settings-label-col"):
                                yield Label("Render Posters & Avatars", classes="settings-label")
                                yield Static(
                                    "[dim]Disable for faster loading or terminals without truecolor support.[/]",
                                    classes="settings-hint",
                                )
                            yield Switch(value=posters_enabled, id="switch-posters-enabled")
                        with Horizontal(classes="settings-row"):
                            with Vertical(classes="settings-label-col"):
                                yield Label("Local Poster Cache", classes="settings-label")
                                yield Static(
                                    self._cache_summary_text(),
                                    id="settings-cache-summary",
                                    classes="settings-hint",
                                )
                            yield Button(
                                "Clear Cache",
                                variant="warning",
                                id="btn-clear-poster-cache",
                            )

                    # Section 3: Behavior & Navigation
                    with Vertical(classes="settings-section"):
                        yield Static(
                            "[bold #79c0ff]Behavior & Navigation[/]",
                            classes="settings-section-title",
                        )
                        with Horizontal(classes="settings-row"):
                            with Vertical(classes="settings-label-col"):
                                yield Label("Default Landing Tab", classes="settings-label")
                                yield Static(
                                    "[dim]Initial tab opened right after signing in.[/]",
                                    classes="settings-hint",
                                )
                            yield Select(
                                [
                                    ("Home", "tab-home"),
                                    ("Lists", "tab-lists"),
                                    ("Explore", "tab-explore"),
                                    ("Profile", "tab-profile"),
                                ],
                                value=settings.default_tab,
                                allow_blank=False,
                                id="select-default-tab",
                                classes="settings-select",
                            )
                        with Horizontal(classes="settings-row"):
                            with Vertical(classes="settings-label-col"):
                                yield Label("Results Per Page", classes="settings-label")
                                yield Static(
                                    "[dim]Number of movies or rows loaded per page.[/]",
                                    classes="settings-hint",
                                )
                            yield Select(
                                [
                                    ("10 items", "10"),
                                    ("20 items", "20"),
                                    ("30 items", "30"),
                                ],
                                value=str(settings.page_size),
                                allow_blank=False,
                                id="select-page-size",
                                classes="settings-select",
                            )
                        with Horizontal(classes="settings-row"):
                            with Vertical(classes="settings-label-col"):
                                yield Label("Auto-enrich Catalog via TMDB", classes="settings-label")
                                yield Static(
                                    "[dim]Fetch missing movies from TMDB when local search has 0 matches.[/]",
                                    classes="settings-hint",
                                )
                            yield Switch(value=settings.tmdb_fallback, id="switch-tmdb-fallback")

                    # Section 4: Privacy & Account
                    with Vertical(classes="settings-section"):
                        yield Static(
                            "[bold #79c0ff]Privacy & Account[/]",
                            classes="settings-section-title",
                        )
                        with Horizontal(classes="settings-row"):
                            with Vertical(classes="settings-label-col"):
                                yield Label("Public Watch Activity", classes="settings-label")
                                yield Static(
                                    "[dim]Allow followers to see your recently watched movies in Explore.[/]",
                                    classes="settings-hint",
                                )
                            yield Switch(value=settings.public_activity, id="switch-public-activity")
                        with Horizontal(classes="settings-row"):
                            with Vertical(classes="settings-label-col"):
                                yield Label("Remember Active Session", classes="settings-label")
                                yield Static(
                                    "[dim]Keep your signed-in account active between sessions.[/]",
                                    classes="settings-hint",
                                )
                            yield Switch(value=settings.remember_session, id="switch-remember-session")

                    with Horizontal(id="settings-actions-row"):
                        yield Button(
                            "Done",
                            variant="primary",
                            id="btn-settings-done",
                        )

    def _cache_summary_text(self) -> str:
        """Returns a short summary of cached poster files on disk."""
        if not CACHE_DIR.exists():
            return "[dim]0 cached images on disk[/]"
        count = sum(1 for p in CACHE_DIR.iterdir() if p.is_file())
        return f"[dim]{count} cached image(s) in local cache[/]"

    @on(Select.Changed, "#select-app-theme")
    def _on_theme_changed(self, event: Select.Changed) -> None:
        if not self._ready or self._suppress_events or event.value is Select.BLANK:
            return
        theme_name = str(event.value)
        if theme_name in self.app.available_themes and self.app.theme != theme_name:
            self.app.theme = theme_name
            SettingsService().set("theme", theme_name)
            show_info_toast(self, f"Theme changed to {_format_theme_label(theme_name)}")

    @on(Switch.Changed, "#switch-figlet-headers")
    def _on_figlet_headers_toggled(self, event: Switch.Changed) -> None:
        if not self._ready or self._suppress_events:
            return
        SettingsService().set("figlet_headers", bool(event.value))
        self._posters_changed = True
        self.query_one("#settings-figlet-header", FigletHeader).set_header(
            "Settings",
            subtitle="Customize appearance, poster rendering, navigation, and privacy.",
        )
        state = "enabled" if event.value else "disabled"
        show_info_toast(self, f"ASCII Figlet headers {state}")

    @on(Switch.Changed, "#switch-posters-enabled")
    def _on_posters_toggled(self, event: Switch.Changed) -> None:
        if not self._ready or self._suppress_events:
            return
        enabled = bool(event.value)
        PosterService().set_enabled(enabled)
        SettingsService().set("posters_enabled", enabled)
        self._posters_changed = True
        state = "enabled" if enabled else "disabled"
        show_info_toast(self, f"Poster rendering {state}")

    @on(Select.Changed, "#select-default-tab")
    def _on_default_tab_changed(self, event: Select.Changed) -> None:
        if not self._ready or self._suppress_events or event.value is Select.BLANK:
            return
        SettingsService().set("default_tab", str(event.value))
        show_info_toast(self, "Default landing tab updated")

    @on(Select.Changed, "#select-page-size")
    def _on_page_size_changed(self, event: Select.Changed) -> None:
        if not self._ready or self._suppress_events or event.value is Select.BLANK:
            return
        SettingsService().set("page_size", int(str(event.value)))
        show_info_toast(self, f"Results per page set to {event.value}")

    @on(Switch.Changed, "#switch-tmdb-fallback")
    def _on_tmdb_fallback_toggled(self, event: Switch.Changed) -> None:
        if not self._ready or self._suppress_events:
            return
        SettingsService().set("tmdb_fallback", bool(event.value))
        state = "enabled" if event.value else "disabled"
        show_info_toast(self, f"TMDB auto-enrich {state}")

    @on(Switch.Changed, "#switch-public-activity")
    def _on_public_activity_toggled(self, event: Switch.Changed) -> None:
        if not self._ready or self._suppress_events:
            return
        SettingsService().set("public_activity", bool(event.value))
        state = "enabled" if event.value else "disabled"
        show_info_toast(self, f"Public watch activity {state}")

    @on(Switch.Changed, "#switch-remember-session")
    def _on_remember_session_toggled(self, event: Switch.Changed) -> None:
        if not self._ready or self._suppress_events:
            return
        enabled = bool(event.value)
        SettingsService().set("remember_session", enabled)
        if not enabled:
            SettingsService().set("last_username", "")
        state = "enabled" if enabled else "disabled"
        show_info_toast(self, f"Remember session {state}")

    @on(Button.Pressed, "#btn-clear-poster-cache")
    def _on_clear_cache(self) -> None:
        removed = 0
        PosterService()._memory_cache.clear()
        if CACHE_DIR.exists():
            for path in CACHE_DIR.iterdir():
                if path.is_file():
                    try:
                        path.unlink()
                        removed += 1
                    except OSError:
                        pass
        self.query_one("#settings-cache-summary", Static).update(
            self._cache_summary_text()
        )
        show_success_toast(self, f"Cleared {removed} cached poster image(s)")

    @on(Button.Pressed, "#btn-settings-reset")
    def action_reset_defaults(self) -> None:
        SettingsService().reset_defaults()
        self._suppress_events = True
        try:
            self.app.theme = "textual-dark"
            self.query_one("#select-app-theme", Select).value = "textual-dark"
            PosterService().set_enabled(True)
            self.query_one("#switch-posters-enabled", Switch).value = True
            self.query_one("#switch-figlet-headers", Switch).value = True
            self.query_one("#select-default-tab", Select).value = "tab-home"
            self.query_one("#select-page-size", Select).value = "10"
            self.query_one("#switch-tmdb-fallback", Switch).value = True
            self.query_one("#switch-public-activity", Switch).value = True
            self.query_one("#switch-remember-session", Switch).value = True
        finally:
            self._suppress_events = False
        self.query_one("#settings-figlet-header", FigletHeader).set_header(
            "Settings",
            subtitle="Customize appearance, poster rendering, navigation, and privacy.",
        )
        self._posters_changed = True
        show_success_toast(self, "Settings restored to defaults")

    @on(Button.Pressed, "#btn-settings-back")
    @on(Button.Pressed, "#btn-settings-done")
    def action_go_back(self) -> None:
        changed = self._posters_changed or (PosterService().enabled != self._initial_posters)
        self.dismiss(changed)
