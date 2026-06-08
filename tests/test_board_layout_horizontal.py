"""Verify CSS fixes for horizontal board layout (ticket #131).

These tests ensure the desktop Kanban layout has:
1. Non-wrapping status titles with ellipsis
2. Non-squishing cards (flex-shrink: 0)
3. Collapsed columns become narrow vertical strips
"""

import re

STYLE_CSS_PATH = "static/style.css"


def read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestHorizontalLayoutCSS:
    def test_desktop_media_query_exists(self):
        css = read(STYLE_CSS_PATH)
        assert "@media (min-width: 769px)" in css, "Expected desktop media query"

    def test_card_flex_shrink_zero_in_desktop(self):
        """Cards inside .cards should not shrink vertically when the column scrolls."""
        css = read(STYLE_CSS_PATH)
        # Extract the full media block (it spans many braces)
        m = re.search(
            r"@media\s*\(\s*min-width:\s*769px\s*\)\s*\{(.+?)\n\}",
            css,
            re.DOTALL,
        )
        assert m, "Could not extract desktop media query block"
        block = m.group(1)
        assert ".board > .group .cards > .card" in block, "Expected card flex-shrink selector in desktop block"
        assert "flex-shrink: 0" in block, "Expected flex-shrink: 0 for cards in desktop block"

    def test_group_title_ellipsis_in_desktop(self):
        """Status names should truncate with ellipsis instead of wrapping."""
        css = read(STYLE_CSS_PATH)
        m = re.search(
            r"@media\s*\(\s*min-width:\s*769px\s*\)\s*\{(.+?)\n\}",
            css,
            re.DOTALL,
        )
        assert m, "Could not extract desktop media query block"
        block = m.group(1)
        assert ".board > .group .group-title" in block, "Expected .group-title selector in desktop block"
        assert "white-space: nowrap" in block, "Expected white-space: nowrap"
        assert "text-overflow: ellipsis" in block, "Expected text-overflow: ellipsis"

    def test_collapsed_column_narrow_strip(self):
        """Collapsed columns shrink to a ~64px vertical strip to fit ticket markers."""
        css = read(STYLE_CSS_PATH)
        m = re.search(
            r"@media\s*\(\s*min-width:\s*769px\s*\)\s*\{(.+?)\n\}",
            css,
            re.DOTALL,
        )
        assert m, "Could not extract desktop media query block"
        block = m.group(1)
        assert ".board > .group.collapsed" in block, "Expected collapsed column selector in desktop block"
        assert "64px" in block, "Expected 64px width for collapsed column"

    def test_collapsed_header_vertical_layout(self):
        """Collapsed column header switches to vertical flex with centered items."""
        css = read(STYLE_CSS_PATH)
        m = re.search(
            r"@media\s*\(\s*min-width:\s*769px\s*\)\s*\{(.+?)\n\}",
            css,
            re.DOTALL,
        )
        assert m, "Could not extract desktop media query block"
        block = m.group(1)
        assert ".board > .group.collapsed .group-header" in block
        assert "flex-direction: column" in block, "Expected column flex on collapsed header"

    def test_collapsed_title_rotated(self):
        """Collapsed column title renders vertically."""
        css = read(STYLE_CSS_PATH)
        m = re.search(
            r"@media\s*\(\s*min-width:\s*769px\s*\)\s*\{(.+?)\n\}",
            css,
            re.DOTALL,
        )
        assert m, "Could not extract desktop media query block"
        block = m.group(1)
        assert "writing-mode: vertical-rl" in block, "Expected vertical writing mode"
        assert "transform: rotate(180deg)" in block, "Expected 180deg rotation"

    def test_collapsed_badge_and_buttons_hidden(self):
        """Add button, count badge, and agent badge are hidden in collapsed state."""
        css = read(STYLE_CSS_PATH)
        m = re.search(
            r"@media\s*\(\s*min-width:\s*769px\s*\)\s*\{(.+?)\n\}",
            css,
            re.DOTALL,
        )
        assert m, "Could not extract desktop media query block"
        block = m.group(1)
        assert ".board > .group.collapsed .group-count" in block
        assert ".board > .group.collapsed .add-btn" in block
        assert ".board > .group.collapsed .badge.agent" in block
        assert "display: none" in block, "Expected display: none for hidden elements"
