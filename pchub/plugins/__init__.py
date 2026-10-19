"""Built-in plugins, in default sidebar order. Add a new built-in plugin here.
(The PyInstaller spec bundles every pchub submodule, so nothing else is needed for the exe.)"""

BUILTIN_PLUGINS = [
    "pchub.plugins.oled_saver.plugin",
    "pchub.plugins.system_monitor.plugin",
    "pchub.plugins.timer.plugin",
    "pchub.plugins.reminders.plugin",
    "pchub.plugins.calendar.plugin",
    "pchub.plugins.commissions.plugin",
    "pchub.plugins.macros.plugin",
    "pchub.plugins.cleaner.plugin",
]
