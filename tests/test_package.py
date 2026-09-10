from __future__ import annotations

from despairplay import __version__


def test_version() -> None:
    assert __version__ == "0.1.0"


def test_engine_imports_without_gtk() -> None:
    import despairplay.engine as engine

    assert engine.__doc__
