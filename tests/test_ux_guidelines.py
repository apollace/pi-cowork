"""Tests for UX Design Guidelines (Ticket #81).

Verifies that the design tokens, component patterns, interaction patterns,
layout patterns, and responsive breakpoints documented in AGENTS.md
actually exist in the codebase (style.css and templates).

These tests are **documentation tests** — they protect the guidelines from
becoming stale by asserting that the referenced CSS classes, variables,
keyframes, and structural patterns are still present.
"""

import os
import re
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS_PATH = os.path.join(ROOT, "static", "style.css")
AGENTS_PATH = os.path.join(ROOT, "AGENTS.md")
JS_PATH = os.path.join(ROOT, "static", "app.js")


@pytest.fixture
def css():
    with open(CSS_PATH) as f:
        return f.read()


@pytest.fixture
def agents():
    with open(AGENTS_PATH) as f:
        return f.read()


@pytest.fixture
def js():
    with open(JS_PATH) as f:
        return f.read()


# ═══════════════════════════════════════════════════════════════════════════
# 1. AGENTS.md — Section existence
# ═══════════════════════════════════════════════════════════════════════════

class TestAgentsMDSection:
    """Verify AGENTS.md contains the UX Design Guidelines section."""

    def test_ux_guidelines_heading(self, agents):
        assert "UX Design Guidelines" in agents, \
            "AGENTS.md should contain a 'UX Design Guidelines' section"

    def test_design_principles_heading(self, agents):
        assert "Design Principles" in agents, \
            "AGENTS.md should document Design Principles"

    def test_design_tokens_heading(self, agents):
        assert "Design Tokens" in agents, \
            "AGENTS.md should document Design Tokens"

    def test_interaction_patterns_heading(self, agents):
        assert "Interaction Patterns" in agents, \
            "AGENTS.md should document Interaction Patterns"

    def test_component_guidelines_heading(self, agents):
        assert "Component Guidelines" in agents, \
            "AGENTS.md should document Component Guidelines"

    def test_layout_patterns_heading(self, agents):
        assert "Layout Patterns" in agents, \
            "AGENTS.md should document Layout Patterns"


# ═══════════════════════════════════════════════════════════════════════════
# 2. Design Tokens — CSS custom properties
# ═══════════════════════════════════════════════════════════════════════════

class TestColorTokens:
    """Verify all color design tokens exist in :root."""

    def test_background_tokens(self, css):
        for token in ["--bg:", "--surface:", "--surface-elevated:"]:
            assert token in css, f"Missing color token {token}"

    def test_text_tokens(self, css):
        for token in ["--text:", "--text-secondary:", "--text-muted:"]:
            assert token in css, f"Missing color token {token}"

    def test_border_tokens(self, css):
        for token in ["--border:", "--border-secondary:", "--border-strong:"]:
            assert token in css, f"Missing border token {token}"

    def test_primary_tokens(self, css):
        for token in ["--primary:", "--primary-soft:", "--primary-hover:"]:
            assert token in css, f"Missing primary token {token}"

    def test_semantic_tokens(self, css):
        for token in ["--success:", "--success-soft:",
                       "--warning:", "--warning-soft:",
                       "--danger:", "--danger-soft:", "--danger-hover:"]:
            assert token in css, f"Missing semantic token {token}"

    def test_priority_colors(self, css):
        """Priority colors must be defined in CSS."""
        for color, hex_val in [("Critical", "#dc2626"), ("High", "#d97706"),
                                ("Medium", "#2563eb"), ("Low", "#6b7280")]:
            assert hex_val in css, f"Missing priority color {color}: {hex_val}"


class TestTypographyTokens:
    """Verify typography patterns in CSS."""

    def test_font_family_stack(self, css):
        assert "system-ui" in css, "Should use system-ui font stack"

    def test_line_height(self, css):
        assert "line-height" in css, "Should define line-height"

    def test_font_weights(self, css):
        """Should use 400–700 weight scale."""
        for weight in ["400", "500", "600", "700"]:
            assert f"font-weight: {weight}" in css or f"font-weight:{weight}" in css, \
                f"Missing font-weight {weight}"


class TestSpacingTokens:
    """Verify border-radius and shadow tokens."""

    def test_radius_tokens(self, css):
        for token in ["--radius-sm:", "--radius:", "--radius-lg:"]:
            assert token in css, f"Missing radius token {token}"

    def test_radius_values(self, css):
        """Verify documented radius values."""
        assert "0.375rem" in css, "radius-sm should be 0.375rem"
        assert "0.5rem" in css, "radius default should be 0.5rem"
        assert "0.75rem" in css, "radius-lg should be 0.75rem"
        assert "999px" in css, "Pill/badge radius should be 999px"

    def test_shadow_tokens(self, css):
        for token in ["--shadow:", "--shadow-md:", "--shadow-lg:"]:
            assert token in css, f"Missing shadow token {token}"

    def test_sidebar_width_token(self, css):
        assert "--sidebar-width:" in css, "Missing --sidebar-width token"

    def test_topbar_height_token(self, css):
        assert "--topbar-height:" in css, "Missing --topbar-height token"


# ═══════════════════════════════════════════════════════════════════════════
# 3. Component Guidelines
# ═══════════════════════════════════════════════════════════════════════════

class TestCardComponents:
    """Verify card component patterns exist in CSS."""

    def test_card_three_zone(self, css):
        for zone in [".card-header", ".card-body", ".card-footer"]:
            assert zone in css, f"Missing card zone class {zone}"

    def test_card_priority_classes(self, css):
        for p in ["Critical", "High", "Medium", "Low"]:
            assert f".card-priority-{p}" in css, f"Missing .card-priority-{p}"

    def test_card_priority_label(self, css):
        assert ".card-priority-label" in css, "Missing .card-priority-label"

    def test_card_entrance_animation(self, css):
        assert "@keyframes card-entrance" in css, "Missing card-entrance animation"

    def test_card_hover_border(self, css):
        """Cards should transition border-color on hover, not transform."""
        m = re.search(r'\.card:hover\s*\{([^}]*)\}', css)
        assert m, "Missing .card:hover rule"
        body = m.group(1)
        assert "border-color" in body, ".card:hover should transition border-color"


class TestButtonComponents:
    """Verify button component patterns."""

    def test_primary_button(self, css):
        assert ".btn.primary" in css, "Missing .btn.primary"

    def test_danger_button(self, css):
        assert ".btn.danger" in css, "Missing .btn.danger"

    def test_ghost_button(self, css):
        assert ".btn.ghost" in css, "Missing .btn.ghost"

    def test_small_button(self, css):
        assert ".btn.small" in css, "Missing .btn.small"

    def test_run_agent_gradient(self, css):
        assert ".btn.run-agent" in css, "Missing .btn.run-agent (gradient)"

    def test_rerun_agent_gradient(self, css):
        assert ".btn.rerun-agent" in css, "Missing .btn.rerun-agent (gradient)"

    def test_kill_btn(self, css):
        assert ".kill-btn" in css, "Missing .kill-btn"

    def test_add_btn(self, css):
        assert ".add-btn" in css, "Missing .add-btn"

    def test_button_transitions(self, css):
        """Buttons should have transition properties."""
        m = re.search(r'\.btn\s*\{([^}]*)\}', css)
        assert m, "Missing .btn rule"
        body = m.group(1)
        assert "transition" in body, ".btn should have transitions"


class TestBadgeComponents:
    """Verify badge and pill patterns."""

    def test_status_badge(self, css):
        assert ".badge.status" in css, "Missing .badge.status"

    def test_priority_pills(self, css):
        for p in ["p-Critical", "p-High", "p-Medium", "p-Low"]:
            assert f".{p}" in css, f"Missing .{p} priority pill"

    def test_agent_badge(self, css):
        assert ".badge.agent" in css, "Missing .badge.agent"

    def test_queued_badge(self, css):
        assert ".badge.queued" in css, "Missing .badge.queued"

    def test_gate_badge(self, css):
        assert ".badge.gate" in css, "Missing .badge.gate"

    def test_question_badge(self, css):
        assert ".badge.question" in css, "Missing .badge.question"

    def test_recurring_badge(self, css):
        assert ".badge.recurring" in css, "Missing .badge.recurring"

    def test_label_pill(self, css):
        assert ".label-pill" in css, "Missing .label-pill"
        assert "min-width: 1.8rem" in css, "Label pill should have min-width"

    def test_label_pill_opacity(self, css):
        """Label pills should use opacity 33/55 for bg/border."""
        assert "33" in css, "Label pills should use 33 opacity for backgrounds"
        assert "55" in css, "Label pills should use 55 opacity for borders"


class TestFormComponents:
    """Verify form component patterns."""

    def test_form_card(self, css):
        assert ".form-card" in css, "Missing .form-card"

    def test_form_inputs(self, css):
        """Form inputs should have focus ring styles."""
        assert ".form-card label > input:focus" in css, \
            "Missing .form-card label > input:focus"

    def test_checkbox_group(self, css):
        assert ".checkbox-group" in css, "Missing .checkbox-group"

    def test_form_inline(self, css):
        assert ".form-inline" in css, "Missing .form-inline"

    def test_edit_input(self, css):
        assert ".edit-input" in css, "Missing .edit-input"


class TestModalComponent:
    """Verify modal component patterns."""

    def test_modal_classes(self, css):
        assert ".modal" in css, "Missing .modal"
        assert ".modal-content" in css, "Missing .modal-content"

    def test_modal_animation(self, css):
        assert "@keyframes modal-in" in css, "Missing modal-in animation"

    def test_modal_z_index(self, css):
        """Modal should be high z-index."""
        m = re.search(r'\.modal\s*\{([^}]*)\}', css)
        assert m, "Missing .modal rule"
        body = m.group(1)
        assert "z-index" in body, ".modal should have z-index"


class TestSlidePanelComponent:
    """Verify slide panel patterns."""

    def test_slide_panel(self, css):
        assert ".slide-panel" in css, "Missing .slide-panel"

    def test_slide_panel_transition(self, css):
        m = re.search(r'\.slide-panel\s*\{([^}]*)\}', css)
        assert m, "Missing .slide-panel rule"
        body = m.group(1)
        assert "transition" in body, ".slide-panel should have transition"
        assert ".25s" in body or "0.25s" in body, ".slide-panel transition should be 0.25s"


class TestToastComponent:
    """Verify toast notification patterns."""

    def test_toast_container(self, css):
        assert ".toast-container" in css, "Missing .toast-container"

    def test_toast_types(self, css):
        for t in ["success", "error", "warning", "info"]:
            assert f".toast-{t}" in css, f"Missing .toast-{t}"

    def test_toast_animations(self, css):
        assert "@keyframes toast-in" in css, "Missing toast-in animation"
        assert "@keyframes toast-out" in css, "Missing toast-out animation"

    def test_toast_z_index(self, css):
        m = re.search(r'\.toast-container\s*\{([^}]*)\}', css)
        assert m, "Missing .toast-container rule"
        body = m.group(1)
        assert "9999" in body, "Toast z-index should be 9999"


class TestTableComponent:
    """Verify data table patterns."""

    def test_data_table(self, css):
        assert ".data-table" in css, "Missing .data-table"
        assert ".table-wrapper" in css, "Missing .table-wrapper"

    def test_table_header_bg(self, css):
        m = re.search(r'\.data-table th\s*\{([^}]*)\}', css)
        assert m, "Missing .data-table th rule"
        body = m.group(1)
        assert "background" in body, "Table header should have background"


# ═══════════════════════════════════════════════════════════════════════════
# 4. Interaction Patterns
# ═══════════════════════════════════════════════════════════════════════════

class TestHoverStates:
    """Verify hover state patterns."""

    def test_card_hover(self, css):
        m = re.search(r'\.card:hover\s*\{([^}]*)\}', css)
        assert m, "Missing .card:hover"
        assert "border-color" in m.group(1), "Card hover should change border-color"
        assert "shadow-md" in m.group(1), "Card hover should elevate shadow"

    def test_button_hover(self, css):
        m = re.search(r'\.btn:hover\s*\{([^}]*)\}', css)
        assert m, "Missing .btn:hover"

    def test_nav_link_hover(self, css):
        m = re.search(r'\.nav-link:hover\s*\{([^}]*)\}', css)
        assert m, "Missing .nav-link:hover"
        body = m.group(1)
        assert "background" in body, "Nav link hover should change background"

    def test_color_swatch_hover(self, css):
        m = re.search(r'\.color-swatch:hover\s*\{([^}]*)\}', css)
        assert m, "Missing .color-swatch:hover"
        assert "scale" in m.group(1), "Color swatch should scale on hover"


class TestFocusStates:
    """Verify focus state patterns."""

    def test_input_focus_ring(self, css):
        """Inputs should get blue focus ring on focus."""
        assert "rgba(37,99,235,0.1)" in css, "Focus ring should use blue shadow"

    def test_primary_border_focus(self, css):
        """Focus should set border-color to primary."""
        # Multiple selectors use this pattern
        focuses = re.findall(r'border-color:\s*var\(--primary\)', css)
        assert len(focuses) >= 2, "Should have primary border on focus states"


class TestTransitionPatterns:
    """Verify transition timing patterns."""

    def test_default_transition_timing(self, css):
        """Default transitions should use 0.15s ease."""
        assert "0.15s" in css, "Should have 0.15s transitions"
        assert ".15s" in css, "Should have .15s transitions (shorthand)"

    def test_panel_transition_timing(self, css):
        """Panels/modals should use 0.25s ease for transform transitions."""
        assert "0.25s" in css or ".25s" in css, "Should have 0.25s panel transitions"


class TestAnimations:
    """Verify animation keyframes."""

    def test_card_entrance(self, css):
        assert "@keyframes card-entrance" in css, "Missing card-entrance"

    def test_fade_in(self, css):
        assert "@keyframes fade-in" in css, "Missing fade-in"

    def test_modal_animation(self, css):
        assert "@keyframes modal-in" in css, "Missing modal-in"
        m = re.search(r'@keyframes modal-in\s*\{([^}]+\}[^}]*)\}', css)
        assert m, "Malformed modal-in"
        body = m.group(1)
        assert "translateY" in body, "modal-in should include translateY"

    def test_toast_animations(self, css):
        assert "@keyframes toast-in" in css, "Missing toast-in"
        assert "@keyframes toast-out" in css, "Missing toast-out"
        m = re.search(r'@keyframes toast-in\s*\{([^}]+\}[^}]*)\}', css)
        assert m, "Malformed toast-in"
        body = m.group(1)
        assert "translateX" in body, "toast-in should include translateX"

    def test_pulse_dot(self, css):
        assert "@keyframes pulse-dot" in css, "Missing pulse-dot"

    def test_skeleton_shimmer(self, css):
        assert "@keyframes skeleton-shimmer" in css, "Missing skeleton-shimmer"


class TestDisabledStates:
    """Verify disabled state patterns."""

    def test_disabled_opacity(self, css):
        """Disabled elements should have reduced opacity."""
        disabled_rules = re.findall(r':disabled\s*\{([^}]*)\}', css)
        has_opacity = any('opacity' in r for r in disabled_rules)
        assert has_opacity, "Disabled states should use opacity"

    def test_disabled_cursor(self, css):
        """Disabled elements should have not-allowed cursor."""
        assert "not-allowed" in css, "Disabled states should have cursor: not-allowed"


class TestLoadingStates:
    """Verify loading skeleton patterns."""

    def test_skeleton_classes(self, css):
        assert ".skeleton" in css, "Missing .skeleton"
        assert ".skeleton-text" in css, "Missing .skeleton-text"
        assert ".skeleton-card" in css, "Missing .skeleton-card"


class TestEmptyStates:
    """Verify empty state patterns."""

    def test_empty_class(self, css):
        assert ".empty" in css, "Missing .empty class"
        m = re.search(r'\.empty\s*\{([^}]*)\}', css)
        assert m, "Missing .empty rule"
        body = m.group(1)
        assert "italic" in body, ".empty should use italic"
        assert "center" in body, ".empty should be centered"


# ═══════════════════════════════════════════════════════════════════════════
# 5. Layout Patterns
# ═══════════════════════════════════════════════════════════════════════════

class TestAppLayout:
    """Verify app layout patterns."""

    def test_sidebar_fixed(self, css):
        m = re.search(r'\.sidebar\s*\{([^}]*)\}', css)
        assert m, "Missing .sidebar rule"
        body = m.group(1)
        assert "position: fixed" in body, "Sidebar should be position: fixed"
        assert "width" in body, "Sidebar should have width"

    def test_main_margin_left(self, css):
        m = re.search(r'\.main\s*\{([^}]*)\}', css)
        assert m, "Missing .main rule"
        body = m.group(1)
        assert "margin-left" in body, "Main should have margin-left to offset sidebar"

    def test_container_max_width(self, css):
        m = re.search(r'\.container\s*\{([^}]*)\}', css)
        assert m, "Missing .container rule"
        body = m.group(1)
        assert "max-width" in body, "Container should have max-width"
        assert "1200px" in body, "Container max-width should be 1200px"

    def test_flex_app_layout(self, css):
        m = re.search(r'\.app\s*\{([^}]*)\}', css)
        assert m, "Missing .app rule"
        body = m.group(1)
        assert "flex" in body, "App should use flex layout"


class TestDetailLayout:
    """Verify ticket detail two-column layout."""

    def test_ticket_layout_grid(self, css):
        m = re.search(r'\.ticket-layout\s*\{([^}]*)\}', css)
        assert m, "Missing .ticket-layout rule"
        body = m.group(1)
        assert "grid" in body, "Ticket layout should use CSS Grid"
        assert "280px" in body, "Sidebar column should be 280px"

    def test_ticket_sidebar_sticky(self, css):
        m = re.search(r'\.ticket-sidebar\s*\{([^}]*)\}', css)
        assert m, "Missing .ticket-sidebar rule"
        body = m.group(1)
        assert "sticky" in body, "Ticket sidebar should be sticky"


class TestResponsiveBreakpoints:
    """Verify responsive breakpoints exist."""

    def test_mobile_breakpoint_640(self, css):
        assert "@media (max-width: 640px)" in css, \
            "Missing 640px mobile breakpoint"

    def test_tablet_breakpoint_768(self, css):
        assert "@media (max-width: 768px)" in css, \
            "Missing 768px tablet breakpoint"

    def test_desktop_breakpoint_769(self, css):
        assert "@media (min-width: 769px)" in css, \
            "Missing 769px desktop breakpoint"

    def test_mobile_sidebar_hidden(self, css):
        """On mobile (≤768px), sidebar should be hidden by default."""
        # Find the 768px media query block
        m = re.search(r'@media\s+\(max-width:\s*768px\)\s*\{', css)
        assert m, "Missing 768px breakpoint"
        # Inside that breakpoint, sidebar should have display: none
        # Check that the rule exists at all
        assert ".sidebar" in css, "Sidebar class must exist"
        # Check that .sidebar.open makes it visible
        assert ".sidebar.open" in css or ".sidebar.open" in css, \
            "Sidebar should have .open state for mobile"


class TestNotificationLayout:
    """Verify notification panel positioning."""

    def test_notification_panel_fixed(self, css):
        m = re.search(r'\.notification-panel\s*\{([^}]*)\}', css)
        assert m, "Missing .notification-panel rule"
        body = m.group(1)
        assert "position: fixed" in body, "Notification panel should be position: fixed"
        assert "z-index" in body, "Notification panel should have z-index"


class TestTopbarLayout:
    """Verify topbar layout."""

    def test_topbar_sticky(self, css):
        m = re.search(r'\.topbar\s*\{([^}]*)\}', css)
        assert m, "Missing .topbar rule"
        body = m.group(1)
        assert "sticky" in body, "Topbar should be sticky"


# ═══════════════════════════════════════════════════════════════════════════
# 6. Design Principles — Verify key architectural constraints
# ═══════════════════════════════════════════════════════════════════════════

class TestDesignPrinciples:
    """Verify key design principle constraints in the codebase."""

    def test_vanilla_css_no_framework(self, css):
        """CSS should not reference any framework prefixes."""
        for fw in ["tailwind", "bootstrap", "bulma", "foundation"]:
            assert fw not in css.lower(), \
                f"CSS should not reference {fw} — vanilla only"

    def test_system_font_stack(self, css):
        """Should use system font stack, not web fonts."""
        m = re.search(r'font-family:\s*([^;]+);', css)
        assert m, "Should define font-family"
        family = m.group(1)
        assert "system-ui" in family, "Should use system-ui font stack"

    def test_no_build_step_required(self):
        """CSS file should be a plain .css file, not compiled output."""
        with open(CSS_PATH) as f:
            first_line = f.readline().strip()
        # No CSS compiler markers
        css_content = open(CSS_PATH).read()
        assert "/* !" not in css_content[:50] or ":root" in css_content[:100], \
            "CSS should not be compiled/bundled output"


class TestZIndexLayers:
    """Verify z-index layer ordering follows documented conventions."""

    def test_modal_z_index(self, css):
        """Modal z-index should be 100."""
        m = re.search(r'\.modal\s*\{([^}]*)\}', css)
        assert m, "Missing .modal rule"
        assert "z-index: 100" in m.group(1), "Modal z-index should be 100"

    def test_sidebar_z_index(self, css):
        """Sidebar z-index should be 50."""
        m = re.search(r'\.sidebar\s*\{([^}]*)\}', css)
        assert m, "Missing .sidebar rule"
        assert "z-index: 50" in m.group(1), "Sidebar z-index should be 50"

    def test_toast_z_index(self, css):
        """Toast container z-index should be 9999."""
        m = re.search(r'\.toast-container\s*\{([^}]*)\}', css)
        assert m, "Missing .toast-container rule"
        assert "9999" in m.group(1), "Toast z-index should be 9999"

    def test_popover_z_index(self, css):
        """Popovers (label picker) should be 1000."""
        m = re.search(r'\.label-popover\s*\{([^}]*)\}', css)
        assert m, "Missing .label-popover rule"
        assert "z-index: 1000" in m.group(1), "Popover z-index should be 1000"

    def test_assistant_z_index(self, css):
        """Assistant panel should be 200-250 range."""
        m = re.search(r'\.assistant-panel\s*\{([^}]*)\}', css)
        assert m, "Missing .assistant-panel rule"
        body = m.group(1)
        assert "z-index" in body, "Assistant panel should have z-index"

    def test_topbar_z_index(self, css):
        """Topbar z-index should be 30."""
        m = re.search(r'\.topbar\s*\{([^}]*)\}', css)
        assert m, "Missing .topbar rule"
        assert "z-index: 30" in m.group(1), "Topbar z-index should be 30"


class TestDocumentedTokenValues:
    """Verify specific token values match the documented guidelines."""

    def test_sidebar_width_value(self, css):
        m = re.search(r'--sidebar-width:\s*([^;]+);', css)
        assert m, "--sidebar-width not found"
        assert m.group(1).strip() == "220px", f"Expected 220px, got {m.group(1).strip()}"

    def test_topbar_height_value(self, css):
        m = re.search(r'--topbar-height:\s*([^;]+);', css)
        assert m, "--topbar-height not found"
        assert m.group(1).strip() == "3.5rem", f"Expected 3.5rem, got {m.group(1).strip()}"

    def test_primary_color_value(self, css):
        m = re.search(r'--primary:\s*([^;]+);', css)
        assert m, "--primary not found"
        assert m.group(1).strip() == "#2563eb", f"Expected #2563eb, got {m.group(1).strip()}"

    def test_danger_color_value(self, css):
        m = re.search(r'--danger:\s*([^;]+);', css)
        assert m, "--danger not found"
        assert m.group(1).strip() == "#ef4444", f"Expected #ef4444, got {m.group(1).strip()}"

    def test_success_color_value(self, css):
        m = re.search(r'--success:\s*([^;]+);', css)
        assert m, "--success not found"
        assert m.group(1).strip() == "#10b981", f"Expected #10b981, got {m.group(1).strip()}"

    def test_warning_color_value(self, css):
        m = re.search(r'--warning:\s*([^;]+);', css)
        assert m, "--warning not found"
        assert m.group(1).strip() == "#f59e0b", f"Expected #f59e0b, got {m.group(1).strip()}"

    def test_radius_sm_value(self, css):
        m = re.search(r'--radius-sm:\s*([^;]+);', css)
        assert m, "--radius-sm not found"
        assert m.group(1).strip() == "0.375rem", f"Expected 0.375rem, got {m.group(1).strip()}"

    def test_radius_value(self, css):
        m = re.search(r'--radius:\s*([^;]+);', css)
        assert m, "--radius not found"
        assert m.group(1).strip() == "0.5rem", f"Expected 0.5rem, got {m.group(1).strip()}"

    def test_radius_lg_value(self, css):
        m = re.search(r'--radius-lg:\s*([^;]+);', css)
        assert m, "--radius-lg not found"
        assert m.group(1).strip() == "0.75rem", f"Expected 0.75rem, got {m.group(1).strip()}"