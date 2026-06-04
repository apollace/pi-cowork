"""Tests for scroll safe-zone for embedded AI agent FAB (Ticket #124).

Verifies that:
1. .container has bottom padding of 80px to clear the 56px FAB + 24px breathing room
2. The mobile .container override also preserves the 80px bottom padding
3. .assistant-bubble uses position: fixed, bottom/right 16px, and z-index >= 50
"""

import re

STYLE_CSS_PATH = 'static/style.css'


def read(path):
    with open(path) as f:
        return f.read()


def _find_media_block_containing(css, needle):
    """Find an @media (max-width: 768px) block that contains `needle`."""
    parts = css.split("@media")
    for part in parts:
        if "max-width: 768px" not in part:
            continue
        brace = part.find("{")
        if brace == -1:
            continue
        depth = 0
        end = -1
        for i, ch in enumerate(part[brace:], start=brace):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end == -1:
            continue
        block = part[brace + 1:end]
        if needle in block:
            return block
    return None


class TestContainerSafeZone:
    """Tests for scroll container bottom padding."""

    def test_container_has_bottom_safe_zone_padding(self):
        """.container must have padding-bottom: 80px for FAB clearance."""
        css = read(STYLE_CSS_PATH)
        m = re.search(r'\.container\s*\{([^}]+)\}', css)
        assert m, '.container rule not found in CSS'
        body = m.group(1)
        assert 'padding-bottom: 80px' in body, (
            f"Expected 'padding-bottom: 80px' in .container, got:\n{body}"
        )

    def test_container_mobile_retains_safe_zone_padding(self):
        """Mobile .container must also keep padding-bottom: 80px."""
        css = read(STYLE_CSS_PATH)
        block = _find_media_block_containing(css, ".container {")
        assert block is not None, "Missing .container rule inside @media (max-width: 768px)"
        assert 'padding-bottom: 80px' in block, (
            f"Expected 'padding-bottom: 80px' in mobile .container, got:\n{block}"
        )

    def test_container_base_top_padding_unchanged(self):
        """Base .container should still have 1.5rem overall padding."""
        css = read(STYLE_CSS_PATH)
        m = re.search(r'\.container\s*\{([^}]+)\}', css)
        assert m, '.container rule not found in CSS'
        body = m.group(1)
        assert 'padding: 1.5rem' in body, (
            f"Expected 'padding: 1.5rem' in .container, got:\n{body}"
        )

    def test_container_mobile_shorthand_padding_present(self):
        """Mobile .container should still set general padding via shorthand."""
        css = read(STYLE_CSS_PATH)
        block = _find_media_block_containing(css, ".container {")
        assert block is not None, "Missing .container rule inside @media (max-width: 768px)"
        assert 'padding: 1rem' in block, (
            f"Expected 'padding: 1rem' in mobile .container, got:\n{block}"
        )


class TestAssistantBubblePosition:
    """Tests for FAB fixed positioning and z-index."""

    def test_assistant_bubble_position_fixed(self):
        """.assistant-bubble must use position: fixed."""
        css = read(STYLE_CSS_PATH)
        m = re.search(r'\.assistant-bubble\s*\{([^}]+)\}', css)
        assert m, '.assistant-bubble rule not found in CSS'
        body = m.group(1)
        assert 'position: fixed' in body, (
            f"Expected 'position: fixed' in .assistant-bubble, got:\n{body}"
        )

    def test_assistant_bubble_bottom_right_16px(self):
        """.assistant-bubble must sit at bottom: 1rem and right: 1rem (16px)."""
        css = read(STYLE_CSS_PATH)
        m = re.search(r'\.assistant-bubble\s*\{([^}]+)\}', css)
        assert m, '.assistant-bubble rule not found in CSS'
        body = m.group(1)
        assert 'bottom: 1rem' in body, (
            f"Expected 'bottom: 1rem' in .assistant-bubble, got:\n{body}"
        )
        assert 'right: 1rem' in body, (
            f"Expected 'right: 1rem' in .assistant-bubble, got:\n{body}"
        )

    def test_assistant_bubble_z_index_at_least_50(self):
        """.assistant-bubble z-index must be 50 or higher."""
        css = read(STYLE_CSS_PATH)
        m = re.search(r'\.assistant-bubble\s*\{([^}]+)\}', css)
        assert m, '.assistant-bubble rule not found in CSS'
        body = m.group(1)
        z_match = re.search(r'z-index:\s*(\d+)', body)
        assert z_match, f"Expected z-index in .assistant-bubble, got:\n{body}"
        z = int(z_match.group(1))
        assert z >= 50, (
            f"Expected z-index >= 50 in .assistant-bubble, got {z}"
        )

    def test_assistant_bubble_dimensions_56px(self):
        """.assistant-bubble width/height must be 3.5rem (56px)."""
        css = read(STYLE_CSS_PATH)
        m = re.search(r'\.assistant-bubble\s*\{([^}]+)\}', css)
        assert m, '.assistant-bubble rule not found in CSS'
        body = m.group(1)
        assert 'width: 3.5rem' in body, (
            f"Expected 'width: 3.5rem' in .assistant-bubble, got:\n{body}"
        )
        assert 'height: 3.5rem' in body, (
            f"Expected 'height: 3.5rem' in .assistant-bubble, got:\n{body}"
        )
