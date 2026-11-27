"""Add-on interface: extra panels that run inside the dashboard server.

The dashboard works on its own. An add-on is any object with some of the methods below;
pass a list of them to ``server.main(addons=[...])`` from your own launcher.
"""
from __future__ import annotations


class Addon:
    """Base class with no-op defaults. Override what you need."""

    name = "addon"

    def add_arguments(self, parser) -> None:
        """Add command-line options to the dashboard's argparse parser."""

    def start(self, ctx: "AddonContext") -> None:
        """Called once after arguments are parsed and the game reader exists."""

    def state(self) -> dict:
        """Extra keys merged into every /api/state response."""
        return {}

    def handle_get(self, path: str, query: dict) -> tuple[bytes, str, int] | None:
        """Answer a GET for a path the dashboard does not serve itself, or return None.

        /api/ paths reach this only with the page's token, like the built-in ones.
        """
        return None

    def page(self) -> str:
        """HTML (styles, markup, scripts) added at the end of the page. Scripts can use
        the ``SD`` object the page defines."""
        return ""


class AddonContext:
    def __init__(self, args, reader, data_home):
        self.args = args
        self.reader = reader
        self.data_home = data_home
