"""Наблюдатель за сменой системной темы (сигнал портала SettingChanged)."""

from unittest.mock import Mock

from ui.theme_watcher import SystemThemeWatcher


class _Msg:
    def __init__(self, *args):
        self._args = list(args)

    def arguments(self):
        return self._args


def test_color_scheme_change_triggers_callback(qapp):
    cb = Mock()
    w = SystemThemeWatcher(cb)
    w._on_setting_changed(_Msg("org.freedesktop.appearance", "color-scheme", 1))
    cb.assert_called_once()


def test_other_settings_are_ignored(qapp):
    cb = Mock()
    w = SystemThemeWatcher(cb)
    w._on_setting_changed(_Msg("org.freedesktop.appearance", "accent-color", 1))
    w._on_setting_changed(_Msg("org.gnome.desktop.interface", "color-scheme", 1))
    cb.assert_not_called()


def test_callback_error_does_not_propagate(qapp):
    w = SystemThemeWatcher(Mock(side_effect=RuntimeError("boom")))
    w._on_setting_changed(_Msg("org.freedesktop.appearance", "color-scheme", 1))  # не падает
