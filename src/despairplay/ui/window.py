"""GNOME Settings-style split window bound to engine checks."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from despairplay.engine import (
    AirPlayDevice,
    CheckResult,
    Group,
    ScanResult,
    Status,
    apply_user_fix,
    plan_user_fix,
    run_scan,
)
from despairplay.engine.host import LiveHost
from despairplay.ui.gi_imports import Adw, Gdk, GLib, Gtk, Pango

log = logging.getLogger(__name__)

_TXT_KEYS = ("am", "et", "cn", "tp", "pw")
_SIDEBAR_WIDTH = 280
_SYSTEM_SKELETON = (
    (160, 240),
    (190, 200),
    (150, 280),
    (180, 220),
    (140, 260),
)
_NETWORK_SKELETON = (
    (150, 230),
    (140, 180),
    (170, 250),
    (130, 200),
    (120, 270),
    (90, 210),
)
_AIRPLAY_SKELETON = ((150, 180), (120, 200), (170, 140))


def _heading(text: str) -> Gtk.Label:
    label = Gtk.Label(label=text, xalign=0.0)
    label.add_css_class("heading")
    label.set_margin_start(12)
    label.set_margin_end(12)
    label.set_margin_top(12)
    label.set_margin_bottom(6)
    return label


def _ellipsize_labels(widget: Gtk.Widget) -> None:
    if isinstance(widget, Gtk.Label):
        widget.set_wrap(False)
        widget.set_ellipsize(Pango.EllipsizeMode.END)
        widget.set_xalign(0.0)
    child = widget.get_first_child()
    while child is not None:
        _ellipsize_labels(child)
        child = child.get_next_sibling()


def _muted_row(title: str, subtitle: str) -> Adw.ActionRow:
    row = Adw.ActionRow(title=title, subtitle=subtitle)
    row.set_sensitive(False)
    _ellipsize_labels(row)
    return row


# Circle+tick (not a lone checkmark) so status is shape, not only colour.
_STATUS_ICON = {
    Status.OK: ("emblem-default-symbolic", "success", "OK"),
    Status.WARN: ("dialog-warning-symbolic", "warning", "Warning"),
    Status.FAIL: ("dialog-error-symbolic", "error", "Error"),
}


def _status_image(status: Status, *, pixel_size: int = 28) -> Gtk.Image:
    icon_name, css_class, label = _STATUS_ICON[status]
    image = Gtk.Image(icon_name=icon_name)
    image.set_pixel_size(pixel_size)
    image.add_css_class(css_class)
    image.set_valign(Gtk.Align.CENTER)
    image.update_property([Gtk.AccessibleProperty.LABEL], [label])
    return image


_CSS = """
.ready-bar {
  background-color: alpha(@window_fg_color, 0.08);
  padding: 10px 16px;
}
.ready-bar label {
  font-weight: 600;
}
.ready-bar.is-skeleton .status-icon-slot {
  background-color: alpha(@window_fg_color, 0.12);
  border-radius: 11px;
  animation: skeleton-pulse 1.2s ease-in-out infinite;
}
.ready-bar.is-skeleton image {
  opacity: 0;
}
.ready-bar.is-skeleton label {
  color: transparent;
  background-color: alpha(@window_fg_color, 0.12);
  border-radius: 6px;
  animation: skeleton-pulse 1.2s ease-in-out infinite;
}
.check-card {
  padding: 2px 0;
}
.check-static {
  padding: 10px 16px;
  background-color: transparent;
}
.check-static-title {
  font-weight: 600;
}
.check-card > .check-static + .check-static {
  border-top: 1px solid alpha(@window_fg_color, 0.08);
}
@keyframes skeleton-pulse {
  0% { opacity: 0.4; }
  50% { opacity: 0.85; }
  100% { opacity: 0.4; }
}
.skeleton-bone {
  background-color: alpha(@window_fg_color, 0.12);
  border-radius: 6px;
  animation: skeleton-pulse 1.2s ease-in-out infinite;
}
.skeleton-icon {
  min-width: 28px;
  min-height: 28px;
  border-radius: 14px;
}
"""

_css_installed = False


def _install_css() -> None:
    global _css_installed
    if _css_installed:
        return
    display = Gdk.Display.get_default()
    if display is None:
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(_CSS.encode())
    Gtk.StyleContext.add_provider_for_display(
        display,
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_USER,
    )
    _css_installed = True


def _static_check_row(
    title: str,
    subtitle: str,
    status: Status,
    *,
    fix_id: str | None = None,
    on_fix: Callable[[Gtk.Button, str], None] | None = None,
) -> Gtk.Box:
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    row.add_css_class("check-static")
    row.set_hexpand(True)
    texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    texts.set_hexpand(True)
    title_lbl = Gtk.Label(label=title, xalign=0.0)
    title_lbl.add_css_class("check-static-title")
    sub_lbl = Gtk.Label(label=subtitle, xalign=0.0)
    sub_lbl.add_css_class("dim-label")
    sub_lbl.set_wrap(True)
    sub_lbl.set_xalign(0.0)
    sub_lbl.set_hexpand(True)
    texts.append(title_lbl)
    texts.append(sub_lbl)
    row.append(_status_image(status))
    row.append(texts)
    if fix_id is not None and on_fix is not None:
        button = Gtk.Button(label="Fix")
        button.add_css_class("suggested-action")
        button.set_valign(Gtk.Align.CENTER)
        button.connect("clicked", on_fix, fix_id)
        row.append(button)
    return row


def _skeleton_bone(*, width: int, height: int, circular: bool = False) -> Gtk.Box:
    bone = Gtk.Box()
    bone.add_css_class("skeleton-bone")
    if circular:
        bone.add_css_class("skeleton-icon")
    bone.set_size_request(width, height)
    bone.set_halign(Gtk.Align.START)
    bone.set_valign(Gtk.Align.CENTER)
    bone.set_hexpand(False)
    return bone


def _skeleton_check_row(*, title_width: int, sub_width: int) -> Gtk.Box:
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    row.add_css_class("check-static")
    texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    texts.set_hexpand(True)
    texts.append(_skeleton_bone(width=title_width, height=14))
    texts.append(_skeleton_bone(width=sub_width, height=10))
    row.append(_skeleton_bone(width=28, height=28, circular=True))
    row.append(texts)
    row.update_property([Gtk.AccessibleProperty.LABEL], ["Loading"])
    return row


def _skeleton_sidebar_row(*, title_width: int, sub_width: int) -> Gtk.ListBoxRow:
    inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    inner.set_hexpand(True)
    inner.set_margin_start(12)
    inner.set_margin_end(12)
    inner.set_margin_top(10)
    inner.set_margin_bottom(10)
    texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    texts.set_hexpand(True)
    texts.append(_skeleton_bone(width=title_width, height=12))
    texts.append(_skeleton_bone(width=sub_width, height=8))
    inner.append(_skeleton_bone(width=22, height=22, circular=True))
    inner.append(texts)
    row = Gtk.ListBoxRow()
    row.set_child(inner)
    row.set_selectable(False)
    row.set_activatable(False)
    row.set_sensitive(False)
    row.update_property([Gtk.AccessibleProperty.LABEL], ["Loading"])
    return row


def _fill_skeleton_card(card: Gtk.Box, widths: tuple[tuple[int, int], ...]) -> None:
    while (child := card.get_first_child()) is not None:
        card.remove(child)
    for title_width, sub_width in widths:
        card.append(_skeleton_check_row(title_width=title_width, sub_width=sub_width))


def _group_block(title: str) -> tuple[Gtk.Box, Gtk.Box]:
    block = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    block.set_margin_start(12)
    block.set_margin_end(12)
    block.set_margin_top(12)
    heading = Gtk.Label(label=title, xalign=0.0)
    heading.add_css_class("heading")
    heading.set_margin_start(4)
    card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    card.add_css_class("card")
    card.add_css_class("check-card")
    block.append(heading)
    block.append(card)
    return block, card


def _clear_children(box: Gtk.Box) -> None:
    while (child := box.get_first_child()) is not None:
        box.remove(child)


def _clear_list(box: Gtk.ListBox) -> None:
    row = box.get_row_at_index(0)
    while row is not None:
        box.remove(row)
        row = box.get_row_at_index(0)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.set_title("DespairPlay")
        self.set_default_size(960, 640)
        _install_css()
        self._guard = False
        self._scan_busy = False
        self._first_scan = True
        self._devices: tuple[AirPlayDevice, ...] = ()
        self._selected_key = "overview"
        self._ready_bar = self._build_ready_bar()
        system_block, self._system_rows = _group_block("System")
        network_block, self._network_rows = _group_block("Network")
        issues_block, self._issues_rows = _group_block("Issues")
        self._system_block = system_block
        self._network_block = network_block
        self._issues_block = issues_block
        self._device_banner = Adw.Banner()
        self._device_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._device_content.set_margin_bottom(18)
        self._title = Adw.WindowTitle(title="Overview", subtitle="System and network")
        self._refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        self._refresh_btn.add_css_class("flat")
        self._refresh_btn.set_tooltip_text("Refresh")
        self._refresh_btn.connect("clicked", self._on_refresh)

        toast = Adw.ToastOverlay()
        self._toast = toast
        split = Adw.NavigationSplitView()
        split.set_min_sidebar_width(_SIDEBAR_WIDTH)
        split.set_max_sidebar_width(_SIDEBAR_WIDTH)
        split.set_sidebar_width_fraction(0.0)
        sidebar = Adw.NavigationPage(
            title="DespairPlay",
            child=self._build_sidebar(),
        )
        content = Adw.NavigationPage(title="Overview", child=self._build_content())
        split.set_sidebar(sidebar)
        split.set_content(content)
        toast.set_child(split)
        self.set_content(toast)
        self._timer_id = GLib.timeout_add_seconds(3, self._on_poll)
        self.connect("unmap", self._on_unmap)
        self._show_first_load_skeleton()
        self._start_scan()

    def _build_sidebar(self) -> Adw.ToolbarView:
        header = Adw.HeaderBar()
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)

        self._setup_list = Gtk.ListBox()
        self._setup_list.add_css_class("navigation-sidebar")
        self._setup_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        overview = Adw.ActionRow(title="Overview", subtitle="System and network")
        overview.add_prefix(Gtk.Image(icon_name="emblem-system-symbolic"))
        _ellipsize_labels(overview)
        self._setup_list.append(overview)
        self._setup_list.select_row(self._setup_list.get_row_at_index(0))
        self._setup_list.connect("row-selected", self._on_overview_selected)

        self._airplay_list = Gtk.ListBox()
        self._airplay_list.add_css_class("navigation-sidebar")
        self._airplay_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._airplay_list.connect("row-selected", self._on_airplay_selected)

        this_pc = Gtk.ListBox()
        this_pc.add_css_class("navigation-sidebar")
        this_pc.set_selection_mode(Gtk.SelectionMode.NONE)
        this_pc.append(
            _muted_row("This PC outputs", "Sink list is not implemented yet")
        )

        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        column.set_size_request(_SIDEBAR_WIDTH, -1)
        column.append(self._setup_list)
        column.append(_heading("AirPlay"))
        column.append(self._airplay_list)
        column.append(_heading("This PC"))
        column.append(this_pc)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_propagate_natural_width(False)
        scrolled.set_child(column)
        toolbar.set_content(scrolled)
        toolbar.set_hexpand(False)
        toolbar.set_size_request(_SIDEBAR_WIDTH, -1)
        return toolbar

    def _build_ready_bar(self) -> Gtk.Box:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        bar.add_css_class("ready-bar")
        bar.set_hexpand(True)
        return bar

    def _fill_status_bar(
        self, status: Status, title: str, *, skeleton: bool = False
    ) -> None:
        _clear_children(self._ready_bar)
        icon_slot = Gtk.Box()
        icon_slot.add_css_class("status-icon-slot")
        icon_slot.set_valign(Gtk.Align.CENTER)
        icon_slot.append(_status_image(status, pixel_size=22))
        label = Gtk.Label(label=title, xalign=0.0)
        label.set_valign(Gtk.Align.CENTER)
        self._ready_bar.append(icon_slot)
        self._ready_bar.append(label)
        if skeleton:
            self._ready_bar.add_css_class("is-skeleton")
            self._ready_bar.update_property([Gtk.AccessibleProperty.LABEL], ["Loading"])
        else:
            self._ready_bar.remove_css_class("is-skeleton")
            self._ready_bar.update_property([Gtk.AccessibleProperty.LABEL], [title])
        self._ready_bar.set_visible(True)

    def _build_content(self) -> Adw.ToolbarView:
        header = Adw.HeaderBar()
        header.set_title_widget(self._title)
        header.pack_start(self._refresh_btn)

        overview_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        overview_page.append(self._system_block)
        overview_page.append(self._network_block)
        overview_page.append(self._issues_block)
        overview_page.set_margin_bottom(18)
        overview_scrolled = Gtk.ScrolledWindow()
        overview_scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        overview_scrolled.set_vexpand(True)
        overview_scrolled.set_child(overview_page)
        overview_body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        overview_body.append(self._ready_bar)
        overview_body.append(overview_scrolled)

        device_scrolled = Gtk.ScrolledWindow()
        device_scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        device_scrolled.set_vexpand(True)
        device_scrolled.set_child(self._device_content)
        device_body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        device_body.append(self._device_banner)
        device_body.append(device_scrolled)

        self._stack = Gtk.Stack()
        self._stack.set_vexpand(True)
        self._stack.add_named(overview_body, "overview")
        self._stack.add_named(device_body, "device")
        self._stack.set_visible_child_name("overview")

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(self._stack)
        return toolbar

    def _show_first_load_skeleton(self) -> None:
        self._fill_status_bar(Status.OK, "Ready", skeleton=True)
        self._issues_block.set_visible(False)
        _fill_skeleton_card(self._system_rows, _SYSTEM_SKELETON)
        _fill_skeleton_card(self._network_rows, _NETWORK_SKELETON)
        self._guard = True
        _clear_list(self._airplay_list)
        self._airplay_list.set_selection_mode(Gtk.SelectionMode.NONE)
        for title_width, sub_width in _AIRPLAY_SKELETON:
            self._airplay_list.append(
                _skeleton_sidebar_row(title_width=title_width, sub_width=sub_width)
            )
        self._guard = False

    def _on_refresh(self, _button: Gtk.Button) -> None:
        self._start_scan()

    def _on_poll(self) -> bool:
        if self.get_mapped() and not self._scan_busy:
            self._start_scan()
        return True

    def _on_unmap(self, *_args: object) -> None:
        if self._timer_id:
            GLib.source_remove(self._timer_id)
            self._timer_id = 0

    def _start_scan(self) -> None:
        if self._scan_busy:
            return
        self._scan_busy = True
        self._refresh_btn.set_sensitive(False)

        def work() -> None:
            try:
                result: ScanResult | BaseException = run_scan()
            except Exception as exc:
                log.exception("Scan failed")
                result = exc
            GLib.idle_add(self._apply_scan, result)

        threading.Thread(target=work, daemon=True).start()

    def _end_first_load(self) -> None:
        if not self._first_scan:
            return
        self._first_scan = False
        self._issues_block.set_visible(True)

    def _apply_scan(self, payload: ScanResult | BaseException) -> bool:
        self._scan_busy = False
        self._refresh_btn.set_sensitive(True)
        if isinstance(payload, BaseException):
            self._end_first_load()
            failed = CheckResult(
                check_id="scan",
                title="Scan failed",
                status=Status.FAIL,
                reason=str(payload) or "Could not complete checks",
                evidence="run_scan",
                group=Group.SYSTEM,
            )
            self._fill_card(self._issues_rows, (failed,))
            return False
        self._end_first_load()
        self._devices = payload.devices
        self._fill_airplay_sidebar()
        system = tuple(item for item in payload.checks if item.group is Group.SYSTEM)
        network = tuple(item for item in payload.checks if item.group is Group.NETWORK)
        issues = tuple(item for item in payload.checks if item.status is not Status.OK)
        self._fill_card(self._system_rows, system)
        self._fill_card(self._network_rows, network)
        self._fill_card(self._issues_rows, issues)
        self._update_banner(payload.checks, payload.devices)
        self._restore_selection()
        return False

    def _fill_airplay_sidebar(self) -> None:
        self._guard = True
        _clear_list(self._airplay_list)
        if not self._devices:
            self._airplay_list.set_selection_mode(Gtk.SelectionMode.NONE)
            self._airplay_list.append(
                _muted_row(
                    "No AirPlay speakers on the network.",
                    "Nothing advertised via mDNS",
                )
            )
            self._guard = False
            return
        self._airplay_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        for device in self._devices:
            row = Adw.ActionRow(title=device.name)
            row.add_prefix(Gtk.Image(icon_name="audio-speakers-symbolic"))
            if device.airplay2_only:
                row.set_subtitle("AirPlay 2 only")
                row.add_suffix(Gtk.Image(icon_name="dialog-warning-symbolic"))
            elif device.address:
                row.set_subtitle(f"{device.address}:{device.port}")
            _ellipsize_labels(row)
            self._airplay_list.append(row)
        self._guard = False

    def _restore_selection(self) -> None:
        if self._selected_key == "overview":
            self._show_overview()
            return
        for index, device in enumerate(self._devices):
            if device.key == self._selected_key:
                row = self._airplay_list.get_row_at_index(index)
                if row is not None:
                    self._guard = True
                    self._setup_list.unselect_all()
                    self._airplay_list.select_row(row)
                    self._guard = False
                    self._show_device(device)
                    return
        self._selected_key = "overview"
        self._show_overview()

    def _on_overview_selected(
        self, _box: Gtk.ListBox, row: Gtk.ListBoxRow | None
    ) -> None:
        if self._guard or row is None:
            return
        self._guard = True
        self._airplay_list.unselect_all()
        self._guard = False
        self._selected_key = "overview"
        self._show_overview()

    def _on_airplay_selected(
        self, _box: Gtk.ListBox, row: Gtk.ListBoxRow | None
    ) -> None:
        if self._guard or row is None:
            return
        index = row.get_index()
        if index < 0 or index >= len(self._devices):
            return
        device = self._devices[index]
        self._guard = True
        self._setup_list.unselect_all()
        self._guard = False
        self._selected_key = device.key
        self._show_device(device)

    def _show_overview(self) -> None:
        self._stack.set_visible_child_name("overview")
        self._title.set_title("Overview")
        self._title.set_subtitle("System and network")

    def _show_device(self, device: AirPlayDevice) -> None:
        self._stack.set_visible_child_name("device")
        self._title.set_title(device.name)
        if device.airplay2_only:
            self._title.set_subtitle("AirPlay 2 only")
        elif device.address:
            self._title.set_subtitle(f"{device.address}:{device.port}")
        else:
            self._title.set_subtitle(device.host)
        self._fill_device_page(device)

    def _fill_device_page(self, device: AirPlayDevice) -> None:
        while (child := self._device_content.get_first_child()) is not None:
            self._device_content.remove(child)
        self._device_banner.set_revealed(device.airplay2_only)
        if device.airplay2_only:
            self._device_banner.set_title("AirPlay 2 only")
        block, card = _group_block("This speaker")
        if device.airplay2_only:
            card.append(
                _static_check_row(
                    "Linux cannot send to this speaker",
                    "It advertises AirPlay 2 only. PipeWire sends RAOP (AirPlay 1).",
                    Status.WARN,
                )
            )
        services: list[str] = []
        if device.has_raop:
            services.append("RAOP (AirPlay 1)")
        if device.has_airplay:
            services.append("_airplay._tcp")
        card.append(
            _static_check_row(
                "Services",
                ", ".join(services) if services else "Unknown",
                Status.OK if device.has_raop else Status.WARN,
            )
        )
        reach = device.address or device.host
        if device.port:
            reach = f"{reach}:{device.port}"
        card.append(
            _static_check_row(
                "Address",
                reach or "Unknown",
                Status.OK if device.address else Status.WARN,
            )
        )
        if device.sink_label:
            card.append(
                _static_check_row(
                    "PipeWire sink",
                    device.sink_label,
                    Status.OK,
                )
            )
        else:
            card.append(
                _static_check_row(
                    "PipeWire sink",
                    "No RAOP sink yet",
                    Status.WARN,
                )
            )
        txt_bits = [
            f"{key}={device.txt[key]}" for key in _TXT_KEYS if device.txt.get(key)
        ]
        if txt_bits:
            card.append(_static_check_row("mDNS TXT", ", ".join(txt_bits), Status.OK))
        self._device_content.append(block)

    def _fill_card(self, card: Gtk.Box, results: tuple[CheckResult, ...]) -> None:
        while (child := card.get_first_child()) is not None:
            card.remove(child)
        if not results:
            card.append(
                _static_check_row(
                    "No issues",
                    "Everything in this scan looks ok",
                    Status.OK,
                )
            )
            return
        for result in results:
            card.append(
                _static_check_row(
                    result.title,
                    result.reason,
                    result.status,
                    fix_id=result.fix_id,
                    on_fix=self._on_fix_clicked,
                )
            )

    def _on_fix_clicked(self, _button: Gtk.Button, fix_id: str) -> None:
        commands = plan_user_fix(fix_id, LiveHost())
        if commands is None:
            return
        dialog = Adw.AlertDialog(
            heading="Apply this fix?",
            body="The following will run:\n\n" + "\n".join(commands),
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("apply", "Apply")
        dialog.set_response_appearance("apply", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_fix_response, fix_id)
        dialog.present(self)

    def _on_fix_response(
        self,
        _dialog: Adw.AlertDialog,
        response: str,
        fix_id: str,
    ) -> None:
        if response != "apply":
            return
        try:
            apply_user_fix(fix_id, LiveHost())
        except (OSError, ValueError) as exc:
            log.exception("Fix %s failed", fix_id)
            error = Adw.AlertDialog(heading="Fix failed", body=str(exc))
            error.add_response("ok", "OK")
            error.present(self)
            return
        self._toast.add_toast(Adw.Toast(title="AirPlay discovery enabled"))
        self._start_scan()

    def _update_banner(
        self,
        results: tuple[CheckResult, ...],
        devices: tuple[AirPlayDevice, ...],
    ) -> None:
        all_ok = all(item.status is Status.OK for item in results)
        if all_ok:
            self._fill_status_bar(Status.OK, "Ready")
            return
        if any(item.status is Status.FAIL for item in results):
            self._fill_status_bar(Status.FAIL, "Issues found")
        elif any(item.airplay2_only for item in devices):
            self._fill_status_bar(Status.WARN, "AirPlay 2-only devices")
        else:
            self._fill_status_bar(Status.WARN, "Warnings")
