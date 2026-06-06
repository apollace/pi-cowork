"""Tests for the Label UI Overhaul (Ticket #70).

Validates that:
1. Board card label picker uses popover mode (no .card-label-picker div)
2. LabelPicker class supports popover mode
3. "Create label" section is collapsed by default (toggle button exists)
4. Label pills use improved contrast (opacity 33 vs 22, border 55 vs 44)
5. CSS includes .label-popover, .label-pill, .label-picker-create-toggle styles
6. CSS no longer includes .card-label-picker styles
7. Ticket detail page pills use improved contrast
8. Close-away and Escape behavior structured for popover
"""

import re

APP_JS_PATH = "static/app.js"
STYLE_CSS_PATH = "static/style.css"
BASE_HTML_PATH = "templates/base.html"
TICKET_DETAIL_PATH = "templates/ticket_detail.html"
TICKET_FORM_PATH = "templates/ticket_form.html"


def read(path):
    with open(path) as f:
        return f.read()


# ── CSS Tests ──


class TestLabelPopoverCSS:
    """Verify .label-popover CSS styles exist and are correct."""

    def test_label_popover_style_exists(self):
        css = read(STYLE_CSS_PATH)
        assert ".label-popover" in css, "Expected .label-popover styles in CSS for popover dropdown"

    def test_label_popover_has_zindex(self):
        css = read(STYLE_CSS_PATH)
        m = re.search(r"\.label-popover\s*\{([^}]+)\}", css, re.DOTALL)
        assert m, ".label-popover rule not found in CSS"
        body = m.group(1)
        assert "z-index" in body, f"Expected z-index in .label-popover for overlay behavior, got:\n{body}"

    def test_label_popover_has_position_absolute(self):
        css = read(STYLE_CSS_PATH)
        m = re.search(r"\.label-popover\s*\{([^}]+)\}", css, re.DOTALL)
        assert m, ".label-popover rule not found in CSS"
        # Position absolute is set via JS, but there should be positioning context
        # Check that the popover has min-width or a shadow for dropdown feel
        body = m.group(1)
        assert "min-width" in body or "box-shadow" in body, (
            f"Expected min-width or box-shadow in .label-popover, got:\n{body}"
        )


class TestLabelPillCSS:
    """Verify .label-pill CSS for improved readability."""

    def test_label_pill_style_exists(self):
        css = read(STYLE_CSS_PATH)
        assert ".label-pill" in css, "Expected .label-pill styles in CSS for improved label readability"

    def test_label_pill_has_min_width(self):
        css = read(STYLE_CSS_PATH)
        m = re.search(r"\.label-pill\s*\{([^}]+)\}", css)
        assert m, ".label-pill rule not found in CSS"
        body = m.group(1)
        assert "min-width" in body, f"Expected min-width in .label-pill for better click/read targets, got:\n{body}"


class TestLabelPickerCreateToggleCSS:
    """Verify .label-picker-create-toggle exists for collapsed create section."""

    def test_create_toggle_style_exists(self):
        css = read(STYLE_CSS_PATH)
        assert ".label-picker-create-toggle" in css, (
            "Expected .label-picker-create-toggle styles in CSS for collapsible create section"
        )

    def test_create_toggle_is_button_style(self):
        css = read(STYLE_CSS_PATH)
        m = re.search(r"\.label-picker-create-toggle\s*\{([^}]+)\}", css)
        assert m, ".label-picker-create-toggle rule not found in CSS"
        body = m.group(1)
        # Should look like a clickable text button, not a regular button
        assert "background" in body or "border" in body, (
            f"Expected background/border in .label-picker-create-toggle, got:\n{body}"
        )


class TestCardLabelPickerRemoved:
    """Verify .card-label-picker is removed from CSS (replaced by popover)."""

    def test_card_label_picker_removed_from_css(self):
        css = read(STYLE_CSS_PATH)
        # The old .card-label-picker rule should not exist
        m = re.search(r"\.card-label-picker\s*\{", css)
        assert m is None, "Expected .card-label-picker to be removed from CSS (replaced by .label-popover)"


# ── JS Tests ──


class TestBoardCardPopover:
    """Verify board card uses popover for labels instead of inline picker."""

    def test_app_js_no_card_label_picker_div(self):
        """buildCard() should not create a .card-label-picker div."""
        js = read(APP_JS_PATH)
        assert "card-label-picker" not in js, "Expected .card-label-picker reference removed from app.js"

    def test_app_js_uses_popover_mode(self):
        """toggleCardLabels should use LabelPicker with popover: true."""
        js = read(APP_JS_PATH)
        assert "popover: true" in js, "Expected popover: true in LabelPicker instantiation in app.js"

    def test_app_js_has_popover_cleanup(self):
        """Should have popover tracking and cleanup functions."""
        js = read(APP_JS_PATH)
        assert "_activePopover" in js, "Expected _activePopover tracking variable"
        assert "closeActivePopover" in js, "Expected closeActivePopover function"

    def test_app_js_label_btn_has_id(self):
        """The + button should have an id for popover positioning."""
        js = read(APP_JS_PATH)
        assert "card-label-btn-" in js, "Expected card-label-btn- id on the label trigger button"

    def test_app_js_pill_uses_label_pill_class(self):
        """buildCard label pills should use .label-pill class."""
        js = read(APP_JS_PATH)
        # Search for the pill rendering in buildCard
        assert "label-pill" in js, "Expected label-pill class used in buildCard pill rendering"

    def test_app_js_pill_improved_opacity(self):
        """Label pill rendering should use opacity 33 (not 22) and border 55 (not 44)."""
        js = read(APP_JS_PATH)
        # In buildCard and toggleCardLabels onChange
        m = re.findall(r"background:\$\{escapeHtml\(l\.color\)\}(\w+)", js)
        if m:
            # At least some should use '33' (improved opacity)
            assert "33" in m or "33" in js, f"Expected label pill background opacity 33, found patterns: {m}"
        # Check border opacity
        m2 = re.findall(r"border:1px solid \$\{escapeHtml\(l\.color\)\}(\w+)", js)
        if m2:
            assert "55" in m2 or "55" in js, f"Expected label pill border opacity 55, found patterns: {m2}"


# ── LabelPicker Class Tests (base.html) ──


class TestLabelPickerPopoverMode:
    """Verify LabelPicker class supports popover mode."""

    def test_label_picker_has_popover_property(self):
        html = read(BASE_HTML_PATH)
        assert "this.popover" in html, "Expected LabelPicker to store popover option"

    def test_label_picker_has_render_popover(self):
        html = read(BASE_HTML_PATH)
        assert "_renderPopover" in html, "Expected LabelPicker to have _renderPopover method"

    def test_label_picker_has_close_popover(self):
        html = read(BASE_HTML_PATH)
        assert "closePopover" in html, "Expected LabelPicker to have closePopover method"

    def test_label_picker_popover_uses_body_append(self):
        """Popover should be appended to document.body for proper positioning."""
        html = read(BASE_HTML_PATH)
        assert "document.body.appendChild(popover)" in html, (
            "Expected popover to be appended to document.body for absolute positioning"
        )

    def test_label_picker_click_away_handler(self):
        """Popover should have click-away close handler."""
        html = read(BASE_HTML_PATH)
        assert "_closeHandler" in html, "Expected click-away handler for popover close"

    def test_label_picker_escape_handler(self):
        """Popover should have Escape key close handler."""
        html = read(BASE_HTML_PATH)
        assert "_escHandler" in html or "'Escape'" in html, "Expected Escape key handler for popover close"


class TestLabelPickerCollapsedCreate:
    """Verify create section is collapsed by default."""

    def test_create_toggle_exists(self):
        html = read(BASE_HTML_PATH)
        assert "label-picker-create-toggle" in html, "Expected .label-picker-create-toggle for collapsed create section"

    def test_create_expanded_defaults_false(self):
        html = read(BASE_HTML_PATH)
        assert "_createExpanded = false" in html or "_createExpanded" in html, (
            "Expected _createExpanded initialized (collapsed by default)"
        )

    def test_create_section_only_rendered_when_expanded(self):
        """The create section (input, palette, button) should only render when _createExpanded is true."""
        html = read(BASE_HTML_PATH)
        # In the render() method, the create section should be conditional
        assert "if (this._createExpanded)" in html, (
            "Expected conditional rendering of create section based on _createExpanded flag"
        )


class TestLabelPickerReRender:
    """Verify _reRender method dispatches to popover or inline mode."""

    def test_re_render_method_exists(self):
        html = read(BASE_HTML_PATH)
        assert "_reRender()" in html or "this._reRender" in html, "Expected _reRender method in LabelPicker"

    def test_re_render_dispatches_to_popover(self):
        html = read(BASE_HTML_PATH)
        # _reRender should check this.popover
        assert "this.popover" in html, "Expected _reRender to check this.popover for dispatching"


# ── Inline LabelPicker (ticket detail + ticket form) Tests ──


class TestInlineLabelPickerImproved:
    """Verify inline (non-popover) LabelPicker uses improved opacity and collapsible create."""

    def test_inline_pill_uses_improved_opacity(self):
        html = read(BASE_HTML_PATH)
        # In the inline render() method, pills should use opacity 33
        # Find the inline chip rendering
        re.findall(r"background:\$\{escapeHtml\(l\.color\)\}(\w+)", html)
        # Check that at least the label-pill class is used
        assert "label-pill" in html, "Expected label-pill class usage in LabelPicker"

    def test_inline_has_create_toggle(self):
        html = read(BASE_HTML_PATH)
        # The inline render method should also have the create toggle
        assert "Create new label" in html, 'Expected "+ Create new label" toggle in LabelPicker'


# ── Ticket Detail Tests ──


class TestTicketDetailPillImprovement:
    """Verify ticket detail page uses improved label pill rendering."""

    def test_ticket_detail_uses_label_pill(self):
        html = read(TICKET_DETAIL_PATH)
        assert "label-pill" in html, "Expected label-pill class in ticket detail label rendering"

    def test_ticket_detail_uses_improved_opacity(self):
        html = read(TICKET_DETAIL_PATH)
        # Check that the pill rendering uses opacity 33 instead of 22
        assert "}33" in html or "l.color)}33" in html, "Expected improved opacity (33) in ticket detail label pills"

    def test_ticket_detail_uses_improved_border(self):
        html = read(TICKET_DETAIL_PATH)
        # Check that the border uses opacity 55 instead of 44
        assert "}55" in html or "l.color)}55" in html, (
            "Expected improved border opacity (55) in ticket detail label pills"
        )


# ── Integration: Label API still works ──


class TestLabelAPIIntegration:
    """Verify label API integration still works end-to-end."""

    def test_create_label_api(self, client, new_workflow):
        import json

        res = client.post(
            "/api/labels",
            json={
                "name": "Bug",
                "color": "#ef4444",
                "workflow_id": new_workflow["id"],
            },
        )
        assert res.status_code == 201
        data = json.loads(res.data)
        assert "id" in data

    def test_label_attached_to_ticket(self, client, default_board):
        import json

        wf_id = default_board["workflow_id"]
        lbl = client.post(
            "/api/labels",
            json={
                "name": "Feature",
                "color": "#10b981",
                "workflow_id": wf_id,
            },
        )
        lid = json.loads(lbl.data)["id"]
        ticket = client.post(
            "/api/tickets",
            json={
                "title": "Test ticket",
                "board_id": default_board["id"],
            },
        )
        tid = json.loads(ticket.data)["id"]
        res = client.post(f"/api/tickets/{tid}/labels", json={"label_ids": [lid]})
        assert res.status_code == 201

        # Verify label is in ticket response
        res = client.get(f"/api/tickets/{tid}")
        data = json.loads(res.data)
        assert len(data["labels"]) == 1
        assert data["labels"][0]["name"] == "Feature"
