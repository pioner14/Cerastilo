"""
Theme loader for NHJS_N.

Provides functions to load and apply QSS themes.

Usage:
    from core.styles import load_theme, Theme
    load_theme(app, Theme.DARK)

See: spec://ui/themes
"""

import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Theme(Enum):
    """Available themes."""

    LIGHT = "light"
    DARK = "dark"


def get_theme_path(theme: Theme) -> str:
    """Get the absolute path to a theme file.

    Args:
        theme: Theme enum value

    Returns:
        Absolute path to the QSS file
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    theme_file = f"{theme.value}_theme.qss"
    return os.path.join(base_dir, "assets", "styles", theme_file)


def load_theme(theme: Theme) -> str:
    """Load theme stylesheet content.

    Args:
        theme: Theme to load

    Returns:
        QSS stylesheet content

    Raises:
        FileNotFoundError: If theme file doesn't exist
    """
    theme_path = get_theme_path(theme)

    if not os.path.exists(theme_path):
        raise FileNotFoundError(f"Theme file not found: {theme_path}")

    with open(theme_path, "r", encoding="utf-8") as f:
        return f.read()


def apply_theme(app, theme: Theme) -> bool:
    """Apply theme to QApplication.

    Args:
        app: QApplication instance
        theme: Theme to apply

    Returns:
        True if theme was applied successfully, False otherwise
    """
    try:
        stylesheet = load_theme(theme)
        app.setStyleSheet(stylesheet)
        set_current_theme(theme)
        return True
    except FileNotFoundError as e:
        print(f"Error loading theme: {e}")
        return False
    except Exception as e:
        print(f"Error applying theme: {e}")
        return False


def _portal_color_scheme() -> Optional[Theme]:
    """Тема из xdg-desktop-portal (org.freedesktop.appearance color-scheme).

    Портал понимают KDE и GNOME, и он отвечает изнутри nix-shell, где
    gsettings без dconf-бэкенда всегда видит 'default'.
    1 — тёмная, 2 — светлая, 0 / нет ответа — None.
    """
    import re
    import subprocess

    for method in ("ReadOne", "Read"):  # ReadOne — portal v2, Read — старые версии
        try:
            result = subprocess.run(
                [
                    "gdbus",
                    "call",
                    "--session",
                    "--dest",
                    "org.freedesktop.portal.Desktop",
                    "--object-path",
                    "/org/freedesktop/portal/desktop",
                    "--method",
                    f"org.freedesktop.portal.Settings.{method}",
                    "org.freedesktop.appearance",
                    "color-scheme",
                ],
                capture_output=True,
                text=True,
                timeout=3,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
        if result.returncode != 0:
            continue
        match = re.search(r"uint32 (\d+)", result.stdout)
        if match:
            return {1: Theme.DARK, 2: Theme.LIGHT}.get(int(match.group(1)))
    return None


def _kde_window_is_dark(kdeglobals_path: str) -> bool:
    """True, если фон окна в схеме KDE тёмный ([Colors:Window] BackgroundNormal).

    Имя схемы (ColorScheme=...) в kdeglobals есть не всегда — например, при
    AutomaticLookAndFeel там только ColorSchemeHash, — а цвета есть всегда.
    """
    in_window = False
    with open(kdeglobals_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if line.startswith("["):
                in_window = line == "[Colors:Window]"
            elif in_window and line.startswith("BackgroundNormal="):
                try:
                    r, g, b = (int(v) for v in line.split("=", 1)[1].split(",")[:3])
                except ValueError:
                    return False
                return 0.299 * r + 0.587 * g + 0.114 * b < 128
    return False


def get_system_theme() -> Theme:
    """Detect system theme preference.

    Returns:
    Theme.DARK if system prefers dark mode, Theme.LIGHT otherwise
    """
    # Check for dark mode preference on different platforms
    try:
        # Linux - Check gsettings (GNOME, Unity, etc.)
        if os.name == "posix":
            portal_theme = _portal_color_scheme()
            if portal_theme is not None:
                return portal_theme

            import subprocess

            try:
                result = subprocess.run(
                    ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    scheme = result.stdout.strip().strip("'")
                    if scheme == "prefer-dark":
                        return Theme.DARK
                    elif scheme == "prefer-light":
                        return Theme.LIGHT
                    # 'default' — нет явного выбора (и так отвечает gsettings без
                    # dconf, например в nix-shell): проверяем дальше, KDE и т.д.
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

            # Try older GNOME setting
            try:
                result = subprocess.run(
                    ["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    theme_name = result.stdout.strip().strip("'").lower()
                    if "dark" in theme_name:
                        return Theme.DARK
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

            # Check GTK theme config file
            gtk_config_path = os.path.expanduser("~/.config/gtk-3.0/settings.ini")
            if os.path.exists(gtk_config_path):
                with open(gtk_config_path, "r") as f:
                    content = f.read()
                    # Check for prefer-dark-theme setting
                    if "gtk-application-prefer-dark-theme=true" in content:
                        return Theme.DARK
                    # Check theme name for dark keyword
                    if "gtk-theme-name" in content:
                        for line in content.split("\n"):
                            if "gtk-theme-name" in line and "dark" in line.lower():
                                return Theme.DARK

            # Check for KDE Plasma dark mode
            kde_config_path = os.path.expanduser("~/.config/kdeglobals")
            if os.path.exists(kde_config_path):
                with open(kde_config_path, "r") as f:
                    content = f.read()
                    if "ColorScheme=Dark" in content or "ColorScheme=BreezeDark" in content:
                        return Theme.DARK
                if _kde_window_is_dark(kde_config_path):
                    return Theme.DARK
                with open(kde_config_path, "r") as f:
                    content = f.read()
                    # Check for KDE's preferred colors scheme
                    if "KDE" in content:
                        # Check contrast setting - high contrast often means dark
                        for line in content.split("\n"):
                            if line.startswith("contrast="):
                                try:
                                    contrast = int(line.split("=")[1])
                                    if contrast >= 4:  # High contrast often indicates dark theme
                                        return Theme.DARK
                                except (ValueError, IndexError):
                                    pass

        # macOS - check defaults
        if os.name == "posix":  # macOS is also posix
            import subprocess

            try:
                result = subprocess.run(
                    ["defaults", "read", "-g", "AppleInterfaceStyle"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0 and "Dark" in result.stdout:
                    return Theme.DARK
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        # Windows - check registry (requires winreg)
        if os.name == "nt":
            try:
                import winreg

                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                )
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                if value == 0:
                    return Theme.DARK
            except (FileNotFoundError, OSError):
                pass

    except Exception:
        pass

    # Default to light theme
    return Theme.LIGHT


class ThemeManager:
    """Manager for application themes.

    Provides theme switching and persistence.

    Example:
        manager = ThemeManager()
        manager.apply_theme(app, Theme.DARK)

        # Later, switch theme
        manager.toggle_theme(app)
    """

    def __init__(self, settings_service=None):
        """Initialize theme manager.

        Args:
            settings_service: Service for persisting theme preference
        """
        self._current_theme: Optional[Theme] = None
        self._settings = settings_service

    @property
    def current_theme(self) -> Optional[Theme]:
        """Get current theme."""
        return self._current_theme

    def apply_theme(self, app, theme: Theme) -> bool:
        """Apply theme and save preference.

        Args:
            app: QApplication instance
            theme: Theme to apply

        Returns:
            True if successful
        """
        success = apply_theme(app, theme)
        if success:
            self._current_theme = theme
            if self._settings:
                self._settings.save_setting("theme", theme.value)
        return success

    def load_saved_theme(self) -> Theme:
        """Load theme from saved preference or detect system theme.

        Returns:
        Saved theme or system theme
        """
        if self._settings:
            saved = self._settings.get_setting("theme")
            if saved:
                # Handle 'system' as special case
                if saved == "system":
                    return get_system_theme()
                try:
                    return Theme(saved)
                except ValueError:
                    pass

        return get_system_theme()

    def toggle_theme(self, app) -> bool:
        """Toggle between light and dark themes.

        Args:
        app: QApplication instance

        Returns:
        True if successful
        """
        if self._current_theme == Theme.DARK:
            return self.apply_theme(app, Theme.LIGHT)
        else:
            return self.apply_theme(app, Theme.DARK)


class ThemeAwareMixin:
    """Mixin for widgets that need to update when theme changes.

    Provides automatic theme change handling for widgets with inline styles.

    Example:
        class MyWidget(QWidget, ThemeAwareMixin):
            def __init__(self):
                super().__init__()
                self.setup_theme_awareness()

            def apply_theme_styles(self, theme: Theme):
                # Update widget styles based on theme
                if theme == Theme.DARK:
                    self.setStyleSheet("background: #1e1e1e;")
                else:
                    self.setStyleSheet("background: #f5f5f5;")
    """

    def setup_theme_awareness(self):
        """Initialize theme awareness for this widget."""
        self._theme = Theme.LIGHT

    def set_theme(self, theme: Theme):
        """Set the current theme and update styles.

        Args:
            theme: The theme to apply
        """
        self._theme = theme
        self.apply_theme_styles(theme)

    def apply_theme_styles(self, theme: Theme):
        """Apply theme-specific styles. Override in subclasses.

        Args:
            theme: The theme to apply
        """
        pass

    def get_theme_aware_color(self, light_color: str, dark_color: str) -> str:
        """Get appropriate color for current theme.

        Args:
            light_color: Color to use in light theme
            dark_color: Color to use in dark theme

        Returns:
            The appropriate color for the current theme
        """
        return dark_color if self._theme == Theme.DARK else light_color


# --- Semantic palette -------------------------------------------------------
#
# The QSS themes only style what Qt draws from the stylesheet. Colours set
# from Python (QTreeWidgetItem foregrounds, table cell backgrounds, inline
# setStyleSheet on individual widgets) ignore it, which is why the dark theme
# was unreadable in the schedule: dark teal on a dark background, and a
# near-white conflict highlight that glares. Widgets must take those colours
# from the palette below instead of hardcoding hex values.


@dataclass(frozen=True)
class Palette:
    """Semantic colours for one theme."""

    text_primary: str
    text_secondary: str
    text_heading: str
    text_warning: str
    accent: str
    accent_hover: str
    accent_disabled: str
    on_accent: str
    conflict_background: str
    border: str
    hover: str
    surface: str
    surface_subtle: str
    filled_background: str
    filled_hover: str
    filled_border: str
    filled_text: str
    text_success: str
    text_error: str
    warning_background: str
    warning_border: str
    panel: str
    # клетка по статусу уведомления: ждём ответа / подтвердил (отказ — conflict_*)
    notice_waiting_background: str
    notice_waiting_border: str
    notice_confirmed_background: str
    notice_confirmed_border: str
    # залитые кнопки диалогов: основная, опасная (PDF), успех (отправить/Word), нейтральная
    btn_primary: str
    btn_primary_hover: str
    btn_danger: str
    btn_danger_hover: str
    btn_success: str
    btn_success_hover: str
    btn_neutral: str
    btn_neutral_hover: str
    # приглушённый текст и ошибка в HTML предпросмотра письма
    preview_muted: str
    preview_error: str


LIGHT_PALETTE = Palette(  # «Лаванда и пергамент»
    text_primary="#2e2630",
    text_secondary="#65586a",
    text_heading="#573c80",
    text_warning="#a85a14",
    accent="#7656a3",
    accent_hover="#5f4488",
    accent_disabled="#8f8396",
    on_accent="#ffffff",
    conflict_background="#f6dad4",
    border="#d6c9b8",
    hover="#efe7f6",
    surface="#fffdf9",
    surface_subtle="#efe8f6",
    filled_background="#ece3f5",
    filled_hover="#ddd0ec",
    filled_border="#9a7fc2",
    filled_text="#4b3375",
    text_success="#55723c",
    text_error="#b3382d",
    warning_background="#f8ecd4",
    warning_border="#d9a441",
    panel="#f3ece1",
    notice_waiting_background="#f8ecb8",
    notice_waiting_border="#c9a227",
    notice_confirmed_background="#dfe8cf",
    notice_confirmed_border="#7c9a5c",
    btn_primary="#7656a3",
    btn_primary_hover="#5f4488",
    btn_danger="#a63a36",
    btn_danger_hover="#862d2a",
    btn_success="#55723c",
    btn_success_hover="#425a2d",
    btn_neutral="#6b5a4c",
    btn_neutral_hover="#54463a",
    preview_muted="#65586a",
    preview_error="#b3382d",
)

DARK_PALETTE = Palette(
    text_primary="#e0e0e0",
    text_secondary="#b0bec5",
    text_heading="#80cbc4",
    text_warning="#ffb74d",
    accent="#4db6ac",
    accent_hover="#66ccc2",
    accent_disabled="#4a5359",
    on_accent="#0f201f",
    conflict_background="#5d2020",
    border="#455a64",
    hover="#37474f",
    surface="#1b1e22",
    surface_subtle="#232830",
    filled_background="#1e3324",
    filled_hover="#284430",
    filled_border="#66bb6a",
    filled_text="#a5d6a7",
    text_success="#81c784",
    text_error="#ef9a9a",
    warning_background="#3a2a14",
    warning_border="#ffa726",
    panel="#262b31",
    notice_waiting_background="#3d3810",
    notice_waiting_border="#fdd835",
    notice_confirmed_background="#1f5530",
    notice_confirmed_border="#81c784",
    btn_primary="#1565c0",
    btn_primary_hover="#0d47a1",
    btn_danger="#b71c1c",
    btn_danger_hover="#7f0000",
    btn_success="#2e7d32",
    btn_success_hover="#1b5e20",
    btn_neutral="#455a64",
    btn_neutral_hover="#263238",
    preview_muted="#64748b",
    preview_error="#b91c1c",
)

_PALETTES = {Theme.LIGHT: LIGHT_PALETTE, Theme.DARK: DARK_PALETTE}


# Section names are drawn as text in the schedule table, so their colours must
# keep contrast on the background of the active theme. The light values are muted
# lavender/parchment tones, the dark ones the matching 200/300 tints.
SECTION_COLORS = {
    Theme.LIGHT: {
        "fixed": "#5c4d63",
        "treasures": "#6a4c9c",
        "ministry": "#a35a1c",
        "living": "#a63a36",
        "cbs": "#58733a",
        "other": "#65586a",
    },
    Theme.DARK: {
        "fixed": "#90a4ae",
        "treasures": "#64b5f6",
        "ministry": "#ffa726",
        "living": "#ef9a9a",
        "cbs": "#81c784",
        "other": "#b0bec5",
    },
}

EVENT_COLORS = {
    Theme.LIGHT: {
        "memorial": "#795548",
        "circuit_assembly": "#a85a14",
        "regional_convention": "#573c80",
    },
    Theme.DARK: {
        "memorial": "#bcaaa4",
        "circuit_assembly": "#ffab91",
        "regional_convention": "#9fa8da",
    },
}


def section_colors(theme: Optional[Theme] = None) -> dict:
    """Section name colours for the given (or current) theme."""
    return dict(SECTION_COLORS[theme or _current_theme])


def event_colors(theme: Optional[Theme] = None) -> dict:
    """Special event badge colours for the given (or current) theme."""
    return dict(EVENT_COLORS[theme or _current_theme])


_current_theme: Theme = Theme.LIGHT
_theme_listeners: list = []


def set_current_theme(theme: Theme) -> None:
    """Remember the active theme and notify listeners.

    Callers that apply a theme (see `apply_theme`) must go through here so
    widgets using the palette can repaint.
    """
    global _current_theme
    _current_theme = theme
    for listener in list(_theme_listeners):
        try:
            listener(theme)
        except Exception as e:  # a broken listener must not block the theme
            print(f"Theme listener failed: {e}")


def current_theme() -> Theme:
    """The theme the palette currently describes."""
    return _current_theme


def palette() -> Palette:
    """Palette for the active theme."""
    return _PALETTES[_current_theme]


def get_palette(theme: Theme) -> Palette:
    """Palette for an explicit theme, without changing the current one."""
    return _PALETTES[theme]


def register_theme_listener(callback) -> None:
    """Register a callable invoked with the new theme on every change."""
    if callback not in _theme_listeners:
        _theme_listeners.append(callback)


def unregister_theme_listener(callback) -> None:
    """Stop notifying a previously registered listener."""
    if callback in _theme_listeners:
        _theme_listeners.remove(callback)


def bind_style(widget, build) -> None:
    """Set ``widget``'s stylesheet from ``build(palette())`` and keep it in sync.

    The stylesheet is rebuilt on every theme change. Calling it again on the
    same widget replaces the previous binding instead of adding a listener.
    """
    previous = getattr(widget, "_theme_style_listener", None)
    if previous is not None:
        unregister_theme_listener(previous)

    def apply(_theme=None):
        widget.setStyleSheet(build(palette()))

    widget._theme_style_listener = apply
    apply()
    register_theme_listener(apply)
    if previous is None:
        widget.destroyed.connect(
            lambda *_, w=widget: unregister_theme_listener(
                getattr(w, "_theme_style_listener", None)
            )
        )
