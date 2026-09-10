"""Central GI version pins. Import Adw/Gtk/Gio/GLib from here, nowhere else."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

__all__ = ["Adw", "GLib", "Gdk", "Gio", "Gtk", "Pango"]
