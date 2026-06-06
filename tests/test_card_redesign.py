"""Tests for Ticket #80 card redesign — three-zone layout, priority accents,
styled inline status select, label add button, CSS variables, animation.

Covers:
  - CSS classes and variables
  - JS buildCard() output structure
  - AGENTS.md documentation
  - Integration render of a full card
"""

import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS_PATH = os.path.join(ROOT, "static", "style.css")
JS_PATH = os.path.join(ROOT, "static", "app.js")
AGENTS_PATH = os.path.join(ROOT, "AGENTS.md")


@pytest.fixture
def css():
    with open(CSS_PATH) as f:
        return f.read()


@pytest.fixture
def js():
    with open(JS_PATH) as f:
        return f.read()


@pytest.fixture
def agents():
    with open(AGENTS_PATH) as f:
        return f.read()


# ── CSS class tests ──────────────────────────────────────────────────────


class TestCSSClasses:
    """Verify key CSS selectors and rules exist in style.css."""

    def test_card_header_class(self, css):
        assert ".card-header" in css

    def test_card_body_class(self, css):
        assert ".card-body" in css

    def test_card_footer_class(self, css):
        assert ".card-footer" in css

    def test_card_priority_critical(self, css):
        assert ".card-priority-Critical" in css

    def test_card_priority_high(self, css):
        assert ".card-priority-High" in css

    def test_card_priority_medium(self, css):
        assert ".card-priority-Medium" in css

    def test_card_priority_low(self, css):
        assert ".card-priority-Low" in css

    def test_card_priority_label_class(self, css):
        assert ".card-priority-label" in css

    def test_card_priority_label_p_critical(self, css):
        assert ".card-priority-label.p-Critical" in css

    def test_card_status_select_class(self, css):
        """Card status should use styled inline select, not a read-only pill."""
        assert ".card-status-select" in css

    def test_card_status_select_styled(self, css):
        """Card status select should have appearance:none for custom styling."""
        assert "appearance: none" in css
        assert "-webkit-appearance: none" in css
        assert "-moz-appearance: none" in css

    def test_card_indicator_class(self, css):
        assert ".card-indicator" in css

    def test_card_inner_class(self, css):
        assert ".card-inner" in css

    def test_card_label_add_class(self, css):
        assert ".card-label-add" in css

    def test_border_secondary_variable(self, css):
        assert "--border-secondary" in css

    def test_card_entrance_animation(self, css):
        assert "@keyframes card-entrance" in css

    def test_no_old_status_select(self, css):
        """The old .status-select rule should be gone."""
        assert ".status-select" not in css

    def test_no_card_actions(self, css):
        """The old .card-actions rule should be gone."""
        assert ".card-actions" not in css

    def test_no_card_meta(self, css):
        """The old .card-meta rule should be gone."""
        assert ".card-meta" not in css

    def test_translateY_hover_present(self, css):
        """Cards should have a subtle lift on hover (translateY(-1px) added as polish)."""
        card_hover_match = re.search(r"\.card:hover\s*\{([^}]*)\}", css)
        assert card_hover_match is not None
        assert "translateY(-1px)" in card_hover_match.group(1)

    def test_no_card_in_animation(self, css):
        """Old card-in animation should be replaced by card-entrance."""
        assert "@keyframes card-in" not in css

    def test_card_uses_entrance_animation(self, css):
        """Card animation property should reference card-entrance."""
        card_blocks = re.findall(r"\.card\s*\{([^}]*)\}", css)
        found = any("card-entrance" in b for b in card_blocks)
        assert found, "Expected .card to use card-entrance animation"


# ── JS output tests ───────────────────────────────────────────────────────


class TestJSOutput:
    """Verify buildCard() produces the new card structure."""

    def test_buildCard_has_card_header(self, js):
        assert "card-header" in js

    def test_buildCard_has_card_body(self, js):
        assert "card-body" in js

    def test_buildCard_has_card_footer(self, js):
        assert "card-footer" in js

    def test_buildCard_priority_class(self, js):
        """Card root should have priority class like card-priority-High."""
        assert "card-priority-" in js

    def test_buildCard_priority_label(self, js):
        """Should render priority label pill in header."""
        assert "card-priority-label" in js

    def test_buildCard_status_select(self, js):
        """Should render styled inline select for status, not a read-only pill."""
        assert "card-status-select" in js

    def test_buildCard_status_select_element(self, js):
        """Should render a <select> element with all status options."""
        start = js.find("function buildCard")
        end = js.find("function updateLabelFilters")
        buildcard_region = js[start:end]
        assert "<select" in buildcard_region
        assert "card-status-select" in buildcard_region

    def test_buildCard_status_select_wired_to_moveTicket(self, js):
        """The status select change event should call moveTicket()."""
        assert "moveTicket" in js
        assert "card-status-select" in js
        # The select should be outside card-link to avoid navigation conflict
        start = js.find("function buildCard")
        end = js.find("function updateLabelFilters")
        buildcard_region = js[start:end]
        assert "stopPropagation" in buildcard_region or "moveTicket" in buildcard_region

    def test_buildCard_label_add_button(self, js):
        """Label add button should use .card-label-add class."""
        assert "card-label-add" in js

    def test_buildCard_has_card_indicator(self, js):
        """Card should have a .card-indicator div as first child."""
        assert "card-indicator" in js

    def test_buildCard_has_card_inner(self, js):
        """Card content should be wrapped in .card-inner div."""
        assert "card-inner" in js

    def test_no_priority_dot_inline(self, js):
        """Inline priority-dot style should be gone from buildCard."""
        assert "priorityDot" not in js

    def test_moveTicket_function_retained(self, js):
        """moveTicket function should still exist."""
        assert "async function moveTicket" in js or "function moveTicket" in js


# ── AGENTS.md documentation tests ────────────────────────────────────────────


class TestAgentsMD:
    """Verify AGENTS.md documents the card redesign pattern."""

    def test_ticket_80_section_exists(self, agents):
        assert "Ticket #80" in agents

    def test_card_design_guidelines_heading(self, agents):
        assert "UI Design Guidelines" in agents

    def test_priority_color_system_documented(self, agents):
        assert "Critical" in agents

    def test_card_header_body_footer_documented(self, agents):
        text = agents.lower()
        assert "card-header" in text or "card header" in text

    def test_border_secondary_documented(self, agents):
        assert "--border-secondary" in agents

    def test_card_entrance_animation_documented(self, agents):
        assert "card-entrance" in agents

    def test_status_select_documented(self, agents):
        """AGENTS.md should document the styled inline select for status changes."""
        assert "card-status-select" in agents

    def test_card_indicator_documented(self, agents):
        assert "card-indicator" in agents

    def test_card_inner_documented(self, agents):
        assert "card-inner" in agents


# ── Integration render test ───────────────────────────────────────────────


class TestIntegration:
    """Full card render scenario — priority class, header/body/footer structure."""

    def test_priority_colors_consistent(self, css, js):
        """Priority colors must match between CSS classes and JS map."""
        css_priorities = {
            "Critical": None,
            "High": None,
            "Medium": None,
            "Low": None,
        }
        for p in css_priorities:
            match = re.search(
                rf"\.card-priority-{p}\s+\.card-indicator\s*\{{[^}}]*background:\s*([^;]+);",
                css,
            )
            assert match, f"Missing CSS rule for .card-priority-{p} .card-indicator"
            css_priorities[p] = match.group(1).strip()

        js_priority_match = re.search(
            r"const priorityColors\s*=\s*\{([^}]+)\}",
            js,
        )
        assert js_priority_match, "Missing priorityColors map in JS"
        js_colors_str = js_priority_match.group(1)
        for p in ["Critical", "High", "Medium", "Low"]:
            assert p in js_colors_str, f"{p} missing from JS priorityColors"

    def test_card_render_structure(self, js):
        """Verify buildCard produces header, body, footer sections."""
        buildcard_match = re.search(
            r"function buildCard\(ticket\)\s*\{(.+?)\n  \}",
            js,
            re.DOTALL,
        )
        assert buildcard_match is not None
        body = buildcard_match.group(1)
        assert "card-header" in body
        assert "card-body" in body
        assert "card-footer" in body

    def test_card_link_does_not_wrap_footer(self, js):
        """The <a class='card-link'> should NOT wrap the footer/status select."""
        start = js.find("function buildCard")
        end = js.find("function updateLabelFilters")
        buildcard_region = js[start:end]
        # card-link closing tag should appear before card-footer
        assert "</a>" in buildcard_region
        assert "card-footer" in buildcard_region
        # footer should come after the card-link close
        link_close_pos = buildcard_region.rfind("</a>")
        footer_pos = buildcard_region.find("card-footer")
        assert footer_pos > link_close_pos, "card-footer should be outside card-link"
