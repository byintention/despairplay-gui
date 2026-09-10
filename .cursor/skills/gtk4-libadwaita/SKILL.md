---
name: gtk4-libadwaita
description: >-
  Build and edit the DespairPlay GTK4/libadwaita UI with PyGObject. Use when
  changing windows, widgets, Adw.Application, HeaderBar, PreferencesGroup,
  ActionRow, GI imports, gi.repository, make run, or Linux GTK desktop UI.
---

# GTK4 / libadwaita (PyGObject)

## Must do

1. Read this skill before writing UI code. For widget recipes see [reference.md](reference.md).
2. Import GObject libraries **only** from `despairplay.ui.gi_imports` (`Gtk` 4.0 + `Adw` 1).
3. Put widgets in `src/despairplay/ui/`. Put probes/fixes in `engine/` — tests must not import GTK.
4. Layout: `Adw.ApplicationWindow` → `Adw.NavigationSplitView` (sidebar of Overview / AirPlay / This PC) → each pane `Adw.ToolbarView` + `Adw.HeaderBar` → `set_content()`. Theme `*-symbolic` icons like GNOME Settings. Do not `wpctl set-default` on row click.
5. Distro packages provide GI (`python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`). Never pip-install PyGObject. Venv: `--system-site-packages`. If GI is missing, explain the apt packages and wait — do not `sudo apt` on this workstation.

## Application skeleton

```python
from despairplay.ui.gi_imports import Adw, Gio

class Application(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id="uk.intention.DespairPlay",
            flags=Gio.ApplicationFlags.FLAGS_NONE,  # GLib 2.72 / Ubuntu 22.04
        )

    def do_activate(self) -> None:
        win = self.props.active_window or MainWindow(application=self)
        win.present()
```

`Adw.Application` calls `Adw.init()` for you. Subclasses that override `do_startup` must chain up **before** touching Adw/GTK.

## Do not

- GTK3 APIs: `Window.add()`, `show_all()`, `Gtk.Box.pack_start` as the window chrome.
- `gi.require_version` outside `gi_imports.py`.
- Block the main loop on subprocesses; parse `pw-dump` / D-Bus off-thread or async, then `GLib.idle_add`.
- Import `ui` from `engine` or from default pytest.

## Verify

`make run` must open the window on the developer machine. `make check` stays headless (no GTK import in tests).
