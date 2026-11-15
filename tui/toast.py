"""
Toast notification helpers for MovieVault (tui/toast.py).

Wraps Textual's built-in `App.notify()` toast system so errors, warnings,
and action feedback appear as non-intrusive floating toasts.
"""

from typing import Any, Literal

from textual.app import App


def _resolve_app(context: Any) -> App | None:
    if isinstance(context, App):
        return context
    try:
        return context.app
    except Exception:
        return None


def show_toast(
    context: Any,
    message: str,
    *,
    title: str = "",
    severity: Literal["information", "warning", "error"] = "information",
    timeout: float = 4.0,
) -> None:
    """Displays a floating toast notification on the active Textual app."""
    app = _resolve_app(context)
    if app is None:
        return
    try:
        app.notify(
            str(message),
            title=title,
            severity=severity,
            timeout=timeout,
        )
    except Exception:
        pass


def show_error_toast(
    context: Any,
    message: str,
    title: str = "✖ Error",
    timeout: float = 4.5,
) -> None:
    """Displays an error toast notification."""
    show_toast(context, message, title=title, severity="error", timeout=timeout)


def show_info_toast(
    context: Any,
    message: str,
    title: str = "ℹ Info",
    timeout: float = 4.0,
) -> None:
    """Displays an informational toast notification (yellow/warning style)."""
    show_toast(context, message, title=title, severity="warning", timeout=timeout)


def show_success_toast(
    context: Any,
    message: str,
    title: str = "✔ Done",
    timeout: float = 3.5,
) -> None:
    """Displays a confirmation toast notification."""
    show_toast(context, message, title=title, severity="information", timeout=timeout)
