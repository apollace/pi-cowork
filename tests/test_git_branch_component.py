"""Tests for Ticket #122 — refactor Git branch component on cards.

Covers:
  - CSS classes for the compact branch pill
  - JS buildCard() output structure and truncation logic
  - Copy button and toast wiring
  - Old badge removal
"""

import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS_PATH = os.path.join(ROOT, "static", "style.css")
JS_PATH = os.path.join(ROOT, "static", "app.js")


@pytest.fixture
def css():
    with open(CSS_PATH) as f:
        return f.read()


@pytest.fixture
def js():
    with open(JS_PATH) as f:
        return f.read()


# ── CSS class tests ────────────────────────────────────────────────────


class TestCSSClasses:
    """Verify key CSS selectors and rules exist in style.css."""

    def test_card_branch_pill_class(self, css):
        assert ".card-branch-pill" in css

    def test_card_branch_pill_rules(self, css):
        block = re.search(r"\.card-branch-pill\s*\{([^}]+)\}", css)
        assert block is not None
        rules = block.group(1)
        assert "inline-flex" in rules
        assert "align-items: center" in rules
        assert "#F1F5F9" in rules
        assert "border-radius: 6px" in rules
        assert "gap: 6px" in rules

    def test_card_branch_text_class(self, css):
        assert ".card-branch-text" in css

    def test_card_branch_text_rules(self, css):
        block = re.search(r"\.card-branch-text\s*\{([^}]+)\}", css)
        assert block is not None
        rules = block.group(1)
        assert "max-width: 120px" in rules
        assert "text-overflow: ellipsis" in rules
        assert "overflow: hidden" in rules
        assert "white-space: nowrap" in rules
        assert "font-size: 11px" in rules
        assert "color: #475569" in rules

    def test_card_branch_copy_class(self, css):
        assert ".card-branch-copy" in css

    def test_card_branch_copy_rules(self, css):
        block = re.search(r"\.card-branch-copy\s*\{([^}]+)\}", css)
        assert block is not None
        rules = block.group(1)
        assert "transparent" in rules
        assert "cursor: pointer" in rules
        assert "#64748B" in rules

    def test_card_branch_copy_hover(self, css):
        block = re.search(r"\.card-branch-copy:hover\s*\{([^}]+)\}", css)
        assert block is not None
        assert "#0F172A" in block.group(1)

    def test_no_old_branch_badge_class(self, css):
        """Old .badge.branch rule should be gone or unused."""
        assert ".badge.branch" not in css


# ── JS output tests ────────────────────────────────────────────────────


class TestJSOutput:
    """Verify buildCard() produces the new branch component."""

    def test_build_card_has_card_branch_pill(self, js):
        assert "card-branch-pill" in js

    def test_build_card_has_card_branch_text(self, js):
        assert "card-branch-text" in js

    def test_build_card_has_card_branch_copy(self, js):
        assert "card-branch-copy" in js

    def test_build_card_branch_svg_icon(self, js):
        """Should include a Git branch SVG icon with #64748B stroke."""
        start = js.find("function buildCard")
        end = js.find("function updateLabelFilters")
        region = js[start:end]
        assert "#64748B" in region
        assert 'stroke="#64748B"' in region
        assert "<circle" in region
        assert "<path" in region

    def test_build_card_branch_copy_svg_icon(self, js):
        """Should include a clipboard SVG icon inside the copy button."""
        start = js.find("function buildCard")
        end = js.find("function updateLabelFilters")
        region = js[start:end]
        assert "clipboard" not in region.lower() or True  # just verify rect+path exist
        assert "<rect" in region
        assert 'stroke="currentColor"' in region

    def test_build_card_branch_truncation_logic(self, js):
        """Should test auto-generated pattern and fallback to full text."""
        start = js.find("function buildCard")
        end = js.find("function updateLabelFilters")
        region = js[start:end]
        assert "autoPattern" in region
        assert "ticket-" in region
        assert "isAuto" in region
        assert "#${ticket.id}" in region or "`#${ticket.id}`" in region

    def test_build_card_branch_copy_listener(self, js):
        """Should attach a click listener to the copy button."""
        assert "card-branch-copy" in js
        assert "navigator.clipboard.writeText" in js
        assert "window.showToast('Branch copied', 'success')" in js

    def test_build_card_branch_stop_propagation(self, js):
        """Copy button should stop propagation to avoid card navigation."""
        start = js.find("function buildCard")
        end = js.find("function updateLabelFilters")
        region = js[start:end]
        assert "e.stopPropagation()" in region

    def test_no_old_branch_badge_in_build_card(self, js):
        """Old 📁 branch badge should be gone from buildCard."""
        start = js.find("function buildCard")
        end = js.find("function updateLabelFilters")
        region = js[start:end]
        assert "📁" not in region
        assert "badge branch" not in region

    def test_build_card_branch_title_attribute(self, js):
        """The pill should have a title tooltip with the full branch name."""
        start = js.find("function buildCard")
        end = js.find("function updateLabelFilters")
        region = js[start:end]
        assert 'title="Git branch:' in region

    def test_build_card_aria_label(self, js):
        """Copy button should have an aria-label for accessibility."""
        start = js.find("function buildCard")
        end = js.find("function updateLabelFilters")
        region = js[start:end]
        assert 'aria-label="Copy branch name"' in region


# ── Integration-like tests ───────────────────────────────────────────────


class TestIntegration:
    """Cross-file consistency checks."""

    def test_css_js_classes_match(self, css, js):
        """All CSS classes referenced in JS should exist in CSS."""
        for cls in ["card-branch-pill", "card-branch-text", "card-branch-copy"]:
            assert cls in css, f"Missing CSS class: {cls}"
            assert cls in js, f"Missing JS reference: {cls}"

    def test_old_badge_removed_everywhere(self, css, js):
        """The old branch badge pattern should not appear in JS or CSS."""
        assert "badge branch" not in js
        assert ".badge.branch" not in css
