"""Regression test for the startup crash KeyError: 'window_edge'.

Every palette must define the full token set consumed by _stylesheet;
a token added to one palette but not the others crashes launch for
users with the other theme persisted.
"""
from __future__ import annotations

import unittest

from cove_converter.ui import theme


class ThemeTokenParity(unittest.TestCase):
    def test_all_palettes_share_token_set(self) -> None:
        key_sets = {name: set(p) for name, p in theme._PALETTES.items()}
        reference = key_sets["dark"]
        for name, keys in key_sets.items():
            self.assertEqual(
                keys, reference,
                f"palette '{name}' token set differs from 'dark': "
                f"missing={sorted(reference - keys)} extra={sorted(keys - reference)}",
            )

    def test_stylesheet_builds_for_every_theme(self) -> None:
        for name in theme._PALETTES:
            css = theme._stylesheet(name)
            self.assertTrue(css.strip(), f"empty stylesheet for theme '{name}'")


if __name__ == "__main__":
    unittest.main()
