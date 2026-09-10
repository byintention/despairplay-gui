"""Adw application entry."""

from __future__ import annotations

import logging
import sys

from despairplay import __version__
from despairplay.ui.gi_imports import Adw, Gio
from despairplay.ui.window import MainWindow

log = logging.getLogger(__name__)

APP_ID = "uk.intention.DespairPlay"


class Application(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )

    def do_activate(self) -> None:
        window = self.props.active_window
        if window is None:
            window = MainWindow(application=self)
        window.present()


def run(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    log.info("Starting DespairPlay %s", __version__)
    app = Application()
    return int(app.run(argv if argv is not None else sys.argv))
