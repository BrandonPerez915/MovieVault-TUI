"""
Login and Registration Screen for MovieVault (backend/tui/screens/auth_screen.py).
"""

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Label, Static

from services.AuthService import AuthService
from tui.screens.help import HelpScreen
from tui.toast import show_error_toast
from tui.widgets.figlet_header import FigletHeader


class AuthScreen(Screen):
    """Interactive screen for Login, Registration, and navigation to User View or Admin Panel."""

    BINDINGS = [
        Binding("f1", "open_help", "Help", show=True, priority=True),
        Binding("ctrl+r", "toggle_register", "Toggle Login/Register", show=True, priority=True),
        Binding("ctrl+g", "continue_guest", "Explore (User)", show=True, priority=True),
        Binding("ctrl+a", "open_admin", "Admin Panel", show=False, priority=True),
        Binding("ctrl+q", "app.quit", "Quit", show=True, priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._is_register_mode = False

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold #58a6ff]∅ MOVIEVAULT[/]  │  [dim]Your cinematic diary[/]",
            id="top-bar",
        )
        with Container(id="auth-card"):
            yield FigletHeader(
                "MovieVault",
                font="slant",
                color="#58a6ff",
                subtitle="SIGN IN — Discover movies, write reviews, and curate your lists",
                id="auth-title",
            )

            yield Label("Username:")
            yield Input(
                placeholder="Enter your username...",
                id="input-username",
                classes="auth-input",
            )

            yield Label("Email (required for registration):", id="lbl-email")
            yield Input(
                placeholder="user@example.com",
                id="input-email",
                classes="auth-input",
            )

            yield Label("Password:")
            yield Input(
                placeholder="Minimum 6 characters",
                password=True,
                id="input-password",
                classes="auth-input",
            )

            yield Label("Confirm Password:", id="lbl-confirm")
            yield Input(
                placeholder="Repeat password",
                password=True,
                id="input-confirm",
                classes="auth-input",
            )

            with Horizontal(id="auth-buttons"):
                yield Button("Sign In [Enter]", variant="primary", id="btn-submit")
                yield Button("Create Account [Ctrl+R]", variant="default", id="btn-toggle-mode")
                yield Button("Explore [Ctrl+G]", variant="warning", id="btn-guest")

    def on_mount(self) -> None:
        self._sync_mode_visibility()
        self.query_one("#input-username", Input).focus()

    def _sync_mode_visibility(self) -> None:
        lbl_email = self.query_one("#lbl-email", Label)
        inp_email = self.query_one("#input-email", Input)
        lbl_confirm = self.query_one("#lbl-confirm", Label)
        inp_confirm = self.query_one("#input-confirm", Input)
        btn_submit = self.query_one("#btn-submit", Button)
        btn_toggle = self.query_one("#btn-toggle-mode", Button)
        title = self.query_one("#auth-title", FigletHeader)

        if self._is_register_mode:
            lbl_email.display = True
            inp_email.display = True
            lbl_confirm.display = True
            inp_confirm.display = True
            btn_submit.label = "Register Account [Enter]"
            btn_toggle.label = "Back to Sign In [Ctrl+R]"
            title.set_header(
                "MovieVault",
                subtitle="CREATE ACCOUNT — Rate movies, follow friends, and organize watchlists",
            )
        else:
            lbl_email.display = False
            inp_email.display = False
            lbl_confirm.display = False
            inp_confirm.display = False
            btn_submit.label = "Sign In [Enter]"
            btn_toggle.label = "Create Account [Ctrl+R]"
            title.set_header(
                "MovieVault",
                subtitle="SIGN IN — Discover movies, write reviews, and curate your lists",
            )

    def action_open_help(self) -> None:
        self.app.push_screen(HelpScreen())

    def action_toggle_register(self) -> None:
        self._is_register_mode = not self._is_register_mode
        self._sync_mode_visibility()

    def action_continue_guest(self) -> None:
        self.app.switch_screen("home")

    def action_open_admin(self) -> None:
        self.app.switch_screen("admin")

    @on(Button.Pressed, "#btn-toggle-mode")
    def on_toggle_pressed(self) -> None:
        self.action_toggle_register()

    @on(Button.Pressed, "#btn-guest")
    def on_guest_pressed(self) -> None:
        self.action_continue_guest()

    @on(Button.Pressed, "#btn-submit")
    def on_submit_pressed(self) -> None:
        self._submit_form()

    @on(Input.Submitted)
    def on_input_submitted(self) -> None:
        self._submit_form()

    def _submit_form(self) -> None:
        auth = AuthService()
        username = self.query_one("#input-username", Input).value
        password = self.query_one("#input-password", Input).value

        if self._is_register_mode:
            email = self.query_one("#input-email", Input).value
            confirm = self.query_one("#input-confirm", Input).value
            ok, session, msg = auth.register(username, email, password, confirm)
        else:
            ok, session, msg = auth.login(username, password)

        if ok:
            if session is not None and session.is_admin:
                self.app.switch_screen("admin")
            else:
                self.app.switch_screen("home")
        else:
            show_error_toast(self, msg)
