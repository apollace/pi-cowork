"""Tests for assistant panel z-index fix (Ticket #73).

Verifies that when a chat panel is open, it renders above the toggle
bubble of the OTHER assistant (and all other UI) so the send button and
bottom-right elements are not covered.
"""

import re

STYLE_CSS_PATH = 'static/style.css'


def _read():
    with open(STYLE_CSS_PATH) as f:
        return f.read()


def _extract_rule(css, selector):
    # Find a simple rule like .foo { ... } or .foo.open { ... }
    pattern = re.compile(rf'{re.escape(selector)}\s*\{{([^}}]+)\}}')
    m = pattern.search(css)
    assert m, f'{selector} rule not found in CSS'
    return m.group(1)


class TestAssistantPanelZIndex:
    """Tests for assistant panel z-index hierarchy."""

    def test_assistant_panel_open_z_index(self):
        """.assistant-panel.open must have z-index: 250 to sit above bubbles."""
        body = _extract_rule(_read(), '.assistant-panel.open')
        assert 'z-index: 250' in body, (
            f"Expected 'z-index: 250' in .assistant-panel.open, got:\n{body}"
        )

    def test_board_assistant_panel_open_z_index(self):
        """.board-assistant-panel.open must have z-index: 250 to sit above bubbles."""
        body = _extract_rule(_read(), '.board-assistant-panel.open')
        assert 'z-index: 250' in body, (
            f"Expected 'z-index: 250' in .board-assistant-panel.open, got:\n{body}"
        )

    def test_assistant_panel_base_z_index(self):
        """Base .assistant-panel should still have z-index: 200."""
        css = _read()
        # Use negative lookahead to avoid matching the .open variant
        pattern = re.compile(r'\.assistant-panel\s*(?!\.open)\{([^}]+)\}')
        m = pattern.search(css)
        assert m, '.assistant-panel base rule not found in CSS'
        body = m.group(1)
        assert 'z-index: 200' in body, (
            f"Expected 'z-index: 200' in base .assistant-panel, got:\n{body}"
        )

    def test_board_assistant_panel_base_z_index(self):
        """Base .board-assistant-panel should still have z-index: 200."""
        css = _read()
        pattern = re.compile(r'\.board-assistant-panel\s*(?!\.open)\{([^}]+)\}')
        m = pattern.search(css)
        assert m, '.board-assistant-panel base rule not found in CSS'
        body = m.group(1)
        assert 'z-index: 200' in body, (
            f"Expected 'z-index: 200' in base .board-assistant-panel, got:\n{body}"
        )

    def test_assistant_bubble_z_index(self):
        """.assistant-bubble must have z-index: 201 so 250 is a meaningful fix."""
        body = _extract_rule(_read(), '.assistant-bubble')
        assert 'z-index: 201' in body, (
            f"Expected 'z-index: 201' in .assistant-bubble, got:\n{body}"
        )

    def test_board_assistant_bubble_z_index(self):
        """.board-assistant-bubble must have z-index: 201 so 250 is a meaningful fix."""
        body = _extract_rule(_read(), '.board-assistant-bubble')
        assert 'z-index: 201' in body, (
            f"Expected 'z-index: 201' in .board-assistant-bubble, got:\n{body}"
        )

    def test_z_index_hierarchy(self):
        """Open panels (250) must be greater than bubbles (201)."""
        css = _read()
        panel_open = _extract_rule(css, '.assistant-panel.open')
        bubble = _extract_rule(css, '.assistant-bubble')
        panel_z = int(re.search(r'z-index:\s*(\d+)', panel_open).group(1))
        bubble_z = int(re.search(r'z-index:\s*(\d+)', bubble).group(1))
        assert panel_z > bubble_z, (
            f".assistant-panel.open z-index ({panel_z}) must be > "
            f".assistant-bubble z-index ({bubble_z})"
        )

    def test_board_z_index_hierarchy(self):
        """Open board panel (250) must be greater than board bubble (201)."""
        css = _read()
        panel_open = _extract_rule(css, '.board-assistant-panel.open')
        bubble = _extract_rule(css, '.board-assistant-bubble')
        panel_z = int(re.search(r'z-index:\s*(\d+)', panel_open).group(1))
        bubble_z = int(re.search(r'z-index:\s*(\d+)', bubble).group(1))
        assert panel_z > bubble_z, (
            f".board-assistant-panel.open z-index ({panel_z}) must be > "
            f".board-assistant-bubble z-index ({bubble_z})"
        )
