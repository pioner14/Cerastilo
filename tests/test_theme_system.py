"""Tests for theme system."""

import unittest
from unittest.mock import patch, MagicMock
import os

from core.styles import Theme, get_system_theme, ThemeManager


class TestSystemThemeDetection(unittest.TestCase):
    """Test system theme detection."""

    def setUp(self):
        # Эти тесты проверяют запасные способы (gsettings, файлы) — портал
        # отключаем, чтобы он не забирал вызовы subprocess.run и не ходил в D-Bus.
        patcher = patch("core.styles._portal_color_scheme", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch("os.name", "posix")
    @patch("subprocess.run")
    def test_gsettings_color_scheme_prefer_dark(self, mock_run):
        """Test detection of prefer-dark color-scheme."""
        mock_run.return_value = MagicMock(returncode=0, stdout="'prefer-dark'\n")

        result = get_system_theme()
        self.assertEqual(result, Theme.DARK)

    @patch("os.name", "posix")
    @patch("subprocess.run")
    def test_gsettings_color_scheme_prefer_light(self, mock_run):
        """Test detection of prefer-light color-scheme."""
        mock_run.return_value = MagicMock(returncode=0, stdout="'prefer-light'\n")

        result = get_system_theme()
        self.assertEqual(result, Theme.LIGHT)

    @patch("os.name", "posix")
    @patch("subprocess.run")
    def test_gsettings_gtk_theme_dark(self, mock_run):
        """Test detection of dark GTK theme."""
        # First call (color-scheme) fails, second (gtk-theme) succeeds
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout=""),
            MagicMock(returncode=0, stdout="'Adwaita-dark'\n"),
        ]

        result = get_system_theme()
        self.assertEqual(result, Theme.DARK)

    @patch("os.name", "posix")
    @patch("subprocess.run")
    @patch("os.path.exists", return_value=True)
    def test_gtk_config_prefer_dark_theme(self, mock_exists, mock_run):
        """Test detection of gtk-application-prefer-dark-theme=true."""
        # gsettings returns nothing (old system)
        mock_run.return_value = MagicMock(returncode=1, stdout="")

        config_content = """
[Settings]
gtk-theme-name=Adwaita
gtk-application-prefer-dark-theme=true
"""
        with patch(
            "builtins.open",
            MagicMock(
                return_value=MagicMock(
                    __enter__=MagicMock(return_value=MagicMock(read=lambda: config_content))
                )
            ),
        ):
            result = get_system_theme()
            self.assertEqual(result, Theme.DARK)

    @patch("os.name", "posix")
    @patch("subprocess.run")
    @patch("os.path.exists", return_value=True)
    def test_gtk_config_dark_theme_name(self, mock_exists, mock_run):
        """Test detection of dark theme name in GTK config."""
        # gsettings returns nothing (old system)
        mock_run.return_value = MagicMock(returncode=1, stdout="")

        config_content = """
[Settings]
gtk-theme-name=Breeze-Dark
gtk-application-prefer-dark-theme=false
"""
        with patch(
            "builtins.open",
            MagicMock(
                return_value=MagicMock(
                    __enter__=MagicMock(return_value=MagicMock(read=lambda: config_content))
                )
            ),
        ):
            result = get_system_theme()
            self.assertEqual(result, Theme.DARK)

    @patch("os.name", "posix")
    @patch("subprocess.run")
    @patch("os.path.exists", return_value=True)
    def test_kde_breeze_dark(self, mock_exists, mock_run):
        """Test detection of KDE BreezeDark."""
        # gsettings returns nothing
        mock_run.return_value = MagicMock(returncode=1, stdout="")

        config_content = """
[General]
ColorScheme=BreezeDark
"""
        with patch(
            "builtins.open",
            MagicMock(
                return_value=MagicMock(
                    __enter__=MagicMock(return_value=MagicMock(read=lambda: config_content))
                )
            ),
        ):
            result = get_system_theme()
            self.assertEqual(result, Theme.DARK)

    @patch("os.name", "posix")
    @patch("os.path.exists", return_value=False)
    @patch("subprocess.run")
    def test_default_light_theme(self, mock_run, mock_exists):
        """Test default to light theme when no dark theme detected."""
        mock_run.return_value = MagicMock(returncode=1, stdout="")

        result = get_system_theme()
        self.assertEqual(result, Theme.LIGHT)


class TestThemeManager(unittest.TestCase):
    """Test ThemeManager class."""

    def test_load_saved_theme_with_system(self):
        """Test that 'system' value returns system theme."""
        settings = MagicMock()
        settings.get_setting.return_value = "system"

        with patch("core.styles.get_system_theme", return_value=Theme.LIGHT):
            manager = ThemeManager(settings)
            result = manager.load_saved_theme()
            self.assertEqual(result, Theme.LIGHT)

    def test_load_saved_theme_with_dark(self):
        """Test that 'dark' value returns dark theme."""
        settings = MagicMock()
        settings.get_setting.return_value = "dark"

        manager = ThemeManager(settings)
        result = manager.load_saved_theme()
        self.assertEqual(result, Theme.DARK)

    def test_load_saved_theme_with_light(self):
        """Test that 'light' value returns light theme."""
        settings = MagicMock()
        settings.get_setting.return_value = "light"

        manager = ThemeManager(settings)
        result = manager.load_saved_theme()
        self.assertEqual(result, Theme.LIGHT)


if __name__ == "__main__":
    unittest.main()


class TestPortalAndKdeDetection(unittest.TestCase):
    """xdg-desktop-portal и цвета KDE (kdeglobals)."""

    @patch("subprocess.run")
    def test_portal_prefer_dark(self, mock_run):
        from core.styles import _portal_color_scheme

        mock_run.return_value = MagicMock(returncode=0, stdout="(<uint32 1>,)\n")
        self.assertEqual(_portal_color_scheme(), Theme.DARK)

    @patch("subprocess.run")
    def test_portal_prefer_light(self, mock_run):
        from core.styles import _portal_color_scheme

        mock_run.return_value = MagicMock(returncode=0, stdout="(<uint32 2>,)\n")
        self.assertEqual(_portal_color_scheme(), Theme.LIGHT)

    @patch("subprocess.run")
    def test_portal_old_read_method_fallback(self, mock_run):
        from core.styles import _portal_color_scheme

        mock_run.side_effect = [
            MagicMock(returncode=1, stdout=""),  # ReadOne нет
            MagicMock(returncode=0, stdout="(<<uint32 1>>,)\n"),  # Read
        ]
        self.assertEqual(_portal_color_scheme(), Theme.DARK)

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_portal_no_gdbus(self, _mock_run):
        from core.styles import _portal_color_scheme

        self.assertIsNone(_portal_color_scheme())

    def _kdeglobals(self, background):
        import tempfile

        f = tempfile.NamedTemporaryFile("w", suffix="kdeglobals", delete=False)
        f.write(
            f"[General]\nColorSchemeHash=abc\n\n[Colors:Window]\nBackgroundNormal={background}\n"
        )
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_kde_dark_window_background(self):
        from core.styles import _kde_window_is_dark

        self.assertTrue(_kde_window_is_dark(self._kdeglobals("30,34,51")))

    def test_kde_light_window_background(self):
        from core.styles import _kde_window_is_dark

        self.assertFalse(_kde_window_is_dark(self._kdeglobals("239,240,241")))

    @patch("os.name", "posix")
    @patch("core.styles._portal_color_scheme", return_value=None)
    @patch("core.styles._kde_window_is_dark", return_value=True)
    @patch("subprocess.run")
    def test_gsettings_default_does_not_mask_kde_dark(self, mock_run, _kde, _portal):
        """gsettings 'default' (nix-shell без dconf) не должен давать светлую тему раньше KDE."""
        mock_run.return_value = MagicMock(returncode=0, stdout="'default'\n")
        with (
            patch("os.path.exists", side_effect=lambda p: p.endswith("kdeglobals")),
            patch("builtins.open", unittest.mock.mock_open(read_data="[General]\n")),
        ):
            self.assertEqual(get_system_theme(), Theme.DARK)
