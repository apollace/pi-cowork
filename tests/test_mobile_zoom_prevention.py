"""Tests for Ticket #126 — Remove zoom on focus.

Verifies:
  - Mobile breakpoint forces 16px font-size on text inputs, textareas, and selects
  - Viewport meta tag does NOT restrict scaling (no user-scalable=no, no maximum-scale=1)
"""

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS_PATH = os.path.join(ROOT, "static", "style.css")
BASE_HTML_PATH = os.path.join(ROOT, "templates", "base.html")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestMobileZoomPreventionCSS:
    """Verify the mobile zoom-prevention rule exists and covers known hotspots."""

    def test_media_query_block_exists(self):
        css = _read(CSS_PATH)
        assert "@media (max-width: 768px)" in css
        # Should contain the accessibility comment
        assert "iOS Safari" in css or "auto-zoom" in css or "Mobile zoom-on-focus" in css

    def test_font_size_16px_in_media_query(self):
        css = _read(CSS_PATH)
        # Find the last @media (max-width: 768px) block
        match = None
        for m in re.finditer(r"@media\s*\(\s*max-width:\s*768px\s*\)\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}", css, re.DOTALL):
            match = m
        assert match is not None, "No @media (max-width: 768px) block found"
        block = match.group(1)
        assert "font-size: 16px" in block

    def test_selectors_cover_key_hotspots(self):
        css = _read(CSS_PATH)
        # Find the last @media (max-width: 768px) block
        match = None
        for m in re.finditer(r"@media\s*\(\s*max-width:\s*768px\s*\)\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}", css, re.DOTALL):
            match = m
        assert match is not None
        block = match.group(1)
        # Core form elements
        assert "input[type=\"text\"]" in block
        assert "textarea," in block or "textarea\n" in block
        assert "select," in block or "select\n" in block or ".card-status-select," in block
        # Known small-font hotspots from ticket analysis
        assert ".card-status-select" in block
        assert ".assistant-footer input" in block
        assert ".assistant-setting input" in block
        assert ".system-prompt-textarea" in block
        assert ".inline-select-sm" in block
        assert ".edit-input" in block
        assert ".form-card label > input" in block
        assert ".form-card label > textarea" in block
        assert ".form-card label > select" in block
        assert ".filter-row input" in block
        assert ".filter-row select" in block


class TestViewportMetaTag:
    """Verify the viewport meta tag stays accessible."""

    def test_viewport_does_not_block_scaling(self):
        html = _read(BASE_HTML_PATH)
        # Extract viewport meta tag content
        m = re.search(r'<meta\s+name="viewport"\s+content="([^"]*)"', html, re.IGNORECASE)
        assert m is not None, "Viewport meta tag not found"
        content = m.group(1).lower()
        assert "user-scalable=no" not in content, "Viewport must not disable user scaling"
        assert "maximum-scale=1" not in content, "Viewport must not cap zoom level"
        assert "width=device-width" in content
        assert "initial-scale=1" in content
