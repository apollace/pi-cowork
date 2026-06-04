"""Tests for Ticket #123 — Compact Top Header Actions on board page.

Verifies that:
1. board.html adds .board-page-header to .page-header wrapper
2. #new-ticket-btn uses .btn-compact-primary with exact styles
3. #manage-boards-btn uses .btn-compact-secondary with exact styles
4. Mobile (@media max-width: 768px) keeps .board-page-header inline (flex-direction: row)
5. Title truncation styles are present (.board-page-header h1)
"""

import re

BOARD_HTML_PATH = "templates/board.html"
STYLE_CSS_PATH = "static/style.css"


def read(path):
    with open(path) as f:
        return f.read()


class TestBoardHtml:
    """Tests for HTML class additions in board.html."""

    def test_page_header_has_board_page_header(self):
        html = read(BOARD_HTML_PATH)
        assert 'class="page-header board-page-header"' in html, (
            "Expected .board-page-header on .page-header wrapper"
        )

    def test_new_ticket_btn_has_compact_primary(self):
        html = read(BOARD_HTML_PATH)
        assert "btn-compact-primary" in html
        # Class may appear before or after id
        assert re.search(
            r'class="[^"]*btn-compact-primary[^"]*"[^>]*id="new-ticket-btn"',
            html,
        ) or re.search(
            r'id="new-ticket-btn"[^>]*class="[^"]*btn-compact-primary[^"]*"',
            html,
        )

    def test_manage_boards_btn_has_compact_secondary(self):
        html = read(BOARD_HTML_PATH)
        assert "btn-compact-secondary" in html
        assert re.search(
            r'class="[^"]*btn-compact-secondary[^"]*"[^>]*id="manage-boards-btn"',
            html,
        ) or re.search(
            r'id="manage-boards-btn"[^>]*class="[^"]*btn-compact-secondary[^"]*"',
            html,
        )


class TestCompactButtonCss:
    """Tests for compact button styles in style.css."""

    def test_new_ticket_btn_background(self):
        css = read(STYLE_CSS_PATH)
        m = re.search(r"#new-ticket-btn\.btn-compact-primary\s*\{([^}]+)\}", css)
        assert m, "Missing #new-ticket-btn.btn-compact-primary rule"
        body = m.group(1)
        assert "background: #2563EB" in body, (
            f"Expected background: #2563EB, got:\n{body}"
        )

    def test_new_ticket_btn_text_color(self):
        css = read(STYLE_CSS_PATH)
        m = re.search(r"#new-ticket-btn\.btn-compact-primary\s*\{([^}]+)\}", css)
        assert m
        body = m.group(1)
        assert "color: #fff" in body, (
            f"Expected color: #fff, got:\n{body}"
        )

    def test_new_ticket_btn_font_size(self):
        css = read(STYLE_CSS_PATH)
        m = re.search(r"#new-ticket-btn\.btn-compact-primary\s*\{([^}]+)\}", css)
        assert m
        body = m.group(1)
        assert "font-size: 13px" in body, (
            f"Expected font-size: 13px, got:\n{body}"
        )

    def test_new_ticket_btn_font_weight(self):
        css = read(STYLE_CSS_PATH)
        m = re.search(r"#new-ticket-btn\.btn-compact-primary\s*\{([^}]+)\}", css)
        assert m
        body = m.group(1)
        assert "font-weight: 500" in body, (
            f"Expected font-weight: 500, got:\n{body}"
        )

    def test_new_ticket_btn_padding(self):
        css = read(STYLE_CSS_PATH)
        m = re.search(r"#new-ticket-btn\.btn-compact-primary\s*\{([^}]+)\}", css)
        assert m
        body = m.group(1)
        assert "padding: 8px 14px" in body, (
            f"Expected padding: 8px 14px, got:\n{body}"
        )

    def test_new_ticket_btn_border_radius(self):
        css = read(STYLE_CSS_PATH)
        m = re.search(r"#new-ticket-btn\.btn-compact-primary\s*\{([^}]+)\}", css)
        assert m
        body = m.group(1)
        assert "border-radius: 8px" in body, (
            f"Expected border-radius: 8px, got:\n{body}"
        )

    def test_new_ticket_btn_border_none(self):
        css = read(STYLE_CSS_PATH)
        m = re.search(r"#new-ticket-btn\.btn-compact-primary\s*\{([^}]+)\}", css)
        assert m
        body = m.group(1)
        assert "border: none" in body, (
            f"Expected border: none, got:\n{body}"
        )

    def test_manage_boards_btn_background(self):
        css = read(STYLE_CSS_PATH)
        m = re.search(r"#manage-boards-btn\.btn-compact-secondary\s*\{([^}]+)\}", css)
        assert m, "Missing #manage-boards-btn.btn-compact-secondary rule"
        body = m.group(1)
        assert "background: #FFFFFF" in body, (
            f"Expected background: #FFFFFF, got:\n{body}"
        )

    def test_manage_boards_btn_border(self):
        css = read(STYLE_CSS_PATH)
        m = re.search(r"#manage-boards-btn\.btn-compact-secondary\s*\{([^}]+)\}", css)
        assert m
        body = m.group(1)
        assert "border: 1px solid #E2E8F0" in body, (
            f"Expected border: 1px solid #E2E8F0, got:\n{body}"
        )

    def test_manage_boards_btn_text_color(self):
        css = read(STYLE_CSS_PATH)
        m = re.search(r"#manage-boards-btn\.btn-compact-secondary\s*\{([^}]+)\}", css)
        assert m
        body = m.group(1)
        assert "color: #334155" in body, (
            f"Expected color: #334155, got:\n{body}"
        )

    def test_manage_boards_btn_font_size(self):
        css = read(STYLE_CSS_PATH)
        m = re.search(r"#manage-boards-btn\.btn-compact-secondary\s*\{([^}]+)\}", css)
        assert m
        body = m.group(1)
        assert "font-size: 13px" in body, (
            f"Expected font-size: 13px, got:\n{body}"
        )

    def test_manage_boards_btn_font_weight(self):
        css = read(STYLE_CSS_PATH)
        m = re.search(r"#manage-boards-btn\.btn-compact-secondary\s*\{([^}]+)\}", css)
        assert m
        body = m.group(1)
        assert "font-weight: 500" in body, (
            f"Expected font-weight: 500, got:\n{body}"
        )

    def test_manage_boards_btn_padding(self):
        css = read(STYLE_CSS_PATH)
        m = re.search(r"#manage-boards-btn\.btn-compact-secondary\s*\{([^}]+)\}", css)
        assert m
        body = m.group(1)
        assert "padding: 8px 14px" in body, (
            f"Expected padding: 8px 14px, got:\n{body}"
        )

    def test_manage_boards_btn_border_radius(self):
        css = read(STYLE_CSS_PATH)
        m = re.search(r"#manage-boards-btn\.btn-compact-secondary\s*\{([^}]+)\}", css)
        assert m
        body = m.group(1)
        assert "border-radius: 8px" in body, (
            f"Expected border-radius: 8px, got:\n{body}"
        )


class TestMobileOverride:
    """Tests for mobile layout override on board page header."""

    def _find_media_block_containing(self, css, needle):
        """Find an @media (max-width: 768px) block that contains `needle`."""
        # Split by @media and scan each block
        parts = css.split("@media")
        for part in parts:
            if "max-width: 768px" not in part:
                continue
            # The block content starts after the first '{' and ends at the matching '}'
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

    def test_board_page_header_mobile_flex_direction(self):
        css = read(STYLE_CSS_PATH)
        block = self._find_media_block_containing(css, ".board-page-header {")
        assert block is not None, "Missing .board-page-header rule inside @media (max-width: 768px)"
        m = re.search(r"\.board-page-header\s*\{([^}]+)\}", block)
        assert m
        body = m.group(1)
        assert "flex-direction: row" in body, (
            f"Expected flex-direction: row in mobile .board-page-header, got:\n{body}"
        )

    def test_board_page_header_mobile_align_items(self):
        css = read(STYLE_CSS_PATH)
        block = self._find_media_block_containing(css, ".board-page-header {")
        assert block is not None
        m = re.search(r"\.board-page-header\s*\{([^}]+)\}", block)
        assert m
        body = m.group(1)
        assert "align-items: center" in body, (
            f"Expected align-items: center in mobile .board-page-header, got:\n{body}"
        )

    def test_board_page_header_mobile_gap(self):
        css = read(STYLE_CSS_PATH)
        block = self._find_media_block_containing(css, ".board-page-header {")
        assert block is not None
        m = re.search(r"\.board-page-header\s*\{([^}]+)\}", block)
        assert m
        body = m.group(1)
        assert "gap: 0.5rem" in body, (
            f"Expected gap: 0.5rem in mobile .board-page-header, got:\n{body}"
        )

    def test_board_page_header_mobile_margin_bottom(self):
        css = read(STYLE_CSS_PATH)
        block = self._find_media_block_containing(css, ".board-page-header {")
        assert block is not None
        m = re.search(r"\.board-page-header\s*\{([^}]+)\}", block)
        assert m
        body = m.group(1)
        assert "margin-bottom: 0.75rem" in body, (
            f"Expected margin-bottom: 0.75rem in mobile .board-page-header, got:\n{body}"
        )

    def test_board_page_header_h1_truncation(self):
        css = read(STYLE_CSS_PATH)
        m = re.search(r"\.board-page-header\s+h1\s*\{([^}]+)\}", css)
        assert m, "Missing .board-page-header h1 truncation rule"
        body = m.group(1)
        assert "text-overflow: ellipsis" in body, (
            f"Expected text-overflow: ellipsis, got:\n{body}"
        )
        assert "white-space: nowrap" in body, (
            f"Expected white-space: nowrap, got:\n{body}"
        )
        assert "overflow: hidden" in body, (
            f"Expected overflow: hidden, got:\n{body}"
        )

    def test_board_page_header_h1_truncation_mobile(self):
        css = read(STYLE_CSS_PATH)
        block = self._find_media_block_containing(css, ".board-page-header h1 {")
        assert block is not None, "Missing .board-page-header h1 truncation rule inside mobile media query"
        m = re.search(r"\.board-page-header\s+h1\s*\{([^}]+)\}", block)
        assert m
        body = m.group(1)
        assert "text-overflow: ellipsis" in body
        assert "white-space: nowrap" in body
        assert "overflow: hidden" in body


class TestNoRegression:
    """Ensure other page headers are not affected."""

    def test_other_pages_do_not_have_board_page_header(self):
        """Other templates should not be forced to pick up these styles."""
        import os
        import glob

        for path in glob.glob("templates/*.html"):
            if path == BOARD_HTML_PATH:
                continue
            with open(path) as f:
                content = f.read()
            assert "board-page-header" not in content, (
                f"{path} should not contain board-page-header class"
            )
