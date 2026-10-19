# Changelog

Each `## <tag>` section becomes the notes of the GitHub release with that tag.

## v1.1.6
- **Updates from GitHub**: PC Hub checks this repository's releases at startup and every 6 hours, downloads app and
  plugin updates by itself, verifies them and asks you to restart. Settings › About: auto check, auto download,
  check now, project page.
- **Notifications**: every notification now goes away by itself, with a slide-in/out animation and a line that shows
  how long is left (hover to pause). Settings › Notifications: style (PC Hub or Windows), duration, keep the ones with
  buttons, try one.
- Plugin notifications (`notify`) now use PC Hub's cards too (or Windows', if you prefer).

## v1.1.5
- Much lower CPU: PC Monitor reads all processes in one system call and redraws only what changes; OLED Saver's
  webcam analysis costs about 5× less; the mouse hook does almost nothing while the mouse moves; timers tick only when
  something counts.
- OLED Saver head pose no longer depends on distance or light (recalibrate once).
- Commissions: hourly billing with time tracking, extra costs, CSV/PDF export. Restart PC Hub from Settings/tray.
  Plugin restart reloads the plugin's code.

## v1.1.4
- New **Macros** plugin (keys, text, clicks, waits, programs, recording, autoclicker; global or per app).
- Brand-new built-in plugins can arrive as plugin updates.

## v1.1.3
- Single-plugin updates (PC Hub keeps its version). OLED Saver: steadier distraction detection.

## v1.1.2
- OLED Saver: distraction calibration, instant wake.

## v1.1.1
- OLED Saver: pick the monitors to darken, wake only by looking while distracted. Commissions plugin.

## v1.0.0
- First version: core, Home, tray, hotkeys, glass/clay styles, PC Monitor, Timers, Cleaner, installer.
