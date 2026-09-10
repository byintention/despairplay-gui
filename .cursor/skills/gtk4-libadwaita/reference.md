# libadwaita widget recipes

Official refs: [PyGObject imports](https://pygobject.gnome.org/guide/imports.html), [Adwaita application](https://pygobject.gnome.org/tutorials/libadwaita/application.html), [libadwaita style classes](https://gnome.pages.gitlab.gnome.org/libadwaita/doc/1-latest/style-classes.html).

## Window chrome

GNOME Settings pattern: `Adw.NavigationSplitView` with a `navigation-sidebar` `Gtk.ListBox` (Overview, then AirPlay devices, then This PC sinks). Each content pane is `Adw.ToolbarView` + `Adw.HeaderBar`. See `docs/DESIGN.md`.

```python
split = Adw.NavigationSplitView(min_sidebar_width=240)
sidebar_page = Adw.NavigationPage(title="DespairPlay", child=sidebar_toolbar)
content_page = Adw.NavigationPage(title="Overview", child=content_toolbar)
split.set_sidebar(sidebar_page)
split.set_content(content_page)
window.set_content(split)
window.set_default_size(960, 640)
```

Use `Adw.WindowTitle(title=..., subtitle=...)` as `header.set_title_widget(...)` when the subtitle carries overall status.

Icons: theme symbolic names only (`audio-speakers-symbolic`, `audio-headphones-symbolic`, `audio-card-symbolic`, `computer-symbolic`, `view-refresh-symbolic`). Prefer PipeWire `device.icon-name` when it is already `*-symbolic`.

## Checklist rows

Prefer `Adw.PreferencesPage` wrapping groups, even if this is not a settings app — it matches GNOME spacing.

- `Adw.Banner` — problems only (issues / AirPlay 2-only). All-clear: light grey `.ready-bar` with green circle-tick then “Ready”.
- `Adw.PreferencesGroup` — Audio system, Network.
- `Adw.ActionRow` — sidebar navigation only. Check results are static `Gtk.Box` cards (no boxed-list hover). Fix will be a real button later.
- OK: `emblem-default-symbolic` (circle + tick), 28px, CSS `success`. Warn: triangle. Fail: circle with bar. Shapes first, colour second.
- `Gtk.Button(label="Fix")` via `row.add_suffix(button)` only when a fix id exists. `add_css_class("suggested-action")` for the safe default fix.
- `Adw.StatusPage` — empty/placeholder states (`icon_name`, `title`, `description`).
- `Adw.ToastOverlay` wrapping the toolbar view for “Avahi enabled” toasts after a fix.

Status icons: `emblem-default-symbolic` (OK), `dialog-warning-symbolic`, `dialog-error-symbolic`. Speakers: `audio-speakers-symbolic`.

## Refresh

- Full check suite: window map + header Refresh.
- Device appearance: `GLib.timeout_add_seconds(3, callback)` returning `True` to repeat. Cancel on unmap.
- Store check results in engine dataclasses; the UI only binds them to rows. Do not parse `pw-dump` in widgets.

## Threading

`Gio.Task` or `threading.Thread` + `GLib.idle_add(update_rows, results)`. Never update widgets off the main thread. Subprocess helpers belong in `engine/`, returning data.

## CSS

Avoid custom CSS unless libadwaita classes cannot express it. If needed, load via `Gtk.CssProvider` at `do_startup` after chaining up, or as `style.css` on the Gio resource base path (Adw.Application loads it automatically when using GResources).

## Typing

mypy `ignore_missing_imports` for `gi.repository.*`. Annotate callbacks; use `Any` for constructor `**kwargs` on GObject subclasses. Do not add incomplete `.pyi` files that fight PyGObject.
