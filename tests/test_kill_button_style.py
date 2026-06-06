"""Tests for the kill button styling (Ticket #44).

Verifies that:
1. .kill-btn uses ghost/outlined style (not solid red) in CSS
2. The kill button on ticket_detail uses .kill-btn class (not .danger)
3. The kill button on run_live uses .kill-btn class
4. .btn.danger is NOT affected (still solid red)
5. Board sidebar kill button uses .kill-btn class
"""

import re

STYLE_CSS_PATH = "static/style.css"
RUN_LIVE_PATH = "templates/run_live.html"
TICKET_DETAIL_PATH = "templates/ticket_detail.html"
APP_JS_PATH = "static/app.js"


def read(path):
    with open(path) as f:
        return f.read()


class TestKillBtnCss:
    """Tests for .kill-btn CSS rules."""

    def test_kill_btn_has_danger_soft_background(self):
        """Kill btn default background should be light pink, not solid red."""
        css = read(STYLE_CSS_PATH)
        m = re.search(r"\.kill-btn\s*\{([^}]+)\}", css)
        assert m, ".kill-btn rule not found in CSS"
        body = m.group(1)
        assert "var(--danger-soft)" in body, f"Expected background: var(--danger-soft) in .kill-btn, got:\n{body}"

    def test_kill_btn_text_color_is_dark_red(self):
        """Kill btn text should be dark red (#991b1b), not white."""
        css = read(STYLE_CSS_PATH)
        m = re.search(r"\.kill-btn\s*\{([^}]+)\}", css)
        assert m, ".kill-btn rule not found in CSS"
        body = m.group(1)
        assert "#991b1b" in body, f"Expected color: #991b1b in .kill-btn, got:\n{body}"

    def test_kill_btn_not_solid_red_background(self):
        """Kill btn should NOT have background: var(--danger) (solid red)."""
        css = read(STYLE_CSS_PATH)
        m = re.search(r"\.kill-btn\s*\{([^}]+)\}", css)
        assert m, ".kill-btn rule not found in CSS"
        body = m.group(1)
        # The default .kill-btn rule should not have a solid danger background
        # It should only appear in :hover
        lines = [line.strip() for line in body.split(";") if line.strip()]
        for line in lines:
            if line.startswith("background"):
                assert "var(--danger-soft)" in line or "transparent" in line, (
                    f"Expected background with var(--danger-soft) in .kill-btn default state, got: {line}"
                )

    def test_kill_btn_hover_fills_solid_red(self):
        """On hover, kill btn should fill with solid danger red."""
        css = read(STYLE_CSS_PATH)
        m = re.search(r"\.kill-btn:hover[^{]*\{([^}]+)\}", css)
        assert m, ".kill-btn:hover rule not found in CSS"
        body = m.group(1)
        assert "var(--danger)" in body or "#ef4444" in body, f"Expected solid danger background on hover, got:\n{body}"

    def test_danger_btn_still_solid_red(self):
        """The .btn.danger class should still have solid red background."""
        css = read(STYLE_CSS_PATH)
        m = re.search(r"\.btn\.danger\s*\{([^}]+)\}", css)
        assert m, ".btn.danger rule not found in CSS"
        body = m.group(1)
        assert "var(--danger)" in body, f"Expected solid var(--danger) background in .btn.danger, got:\n{body}"
        assert "color:#fff" in body.replace(" ", "").replace(";", ""), (
            f"Expected white text in .btn.danger, got:\n{body}"
        )


class TestKillBtnHtml:
    """Tests for kill button HTML in templates/JS."""

    def test_run_live_kill_btn_has_kill_btn_class(self):
        """run_live.html kill button should use .btn.kill-btn class."""
        html = read(RUN_LIVE_PATH)
        # Find the kill button element
        assert "btn kill-btn" in html, 'Expected "btn kill-btn" in run_live.html'

    def test_ticket_detail_kill_btn_uses_kill_btn_not_danger(self):
        """ticket_detail.html kill button should use .kill-btn, not .danger."""
        html = read(TICKET_DETAIL_PATH)
        # The kill button in the agent runs section should use kill-btn class
        m = re.search(r'class="btn small kill-btn"', html)
        assert m, 'Expected class="btn small kill-btn" for kill button in ticket_detail.html'
        # It should NOT use "btn small danger" for the Kill button
        # (other danger buttons like Reject are fine)
        kill_btn_lines = [line for line in html.split("\n") if "🛑 Kill" in line]
        for line in kill_btn_lines:
            assert 'class="btn small kill-btn"' in line, (
                f"Kill button should use kill-btn class, not danger class: {line}"
            )

    def test_appjs_kill_btn_class(self):
        """Board sidebar kill button in app.js should use .kill-btn class."""
        js = read(APP_JS_PATH)
        assert 'class="kill-btn"' in js, "Expected kill-btn class on kill button in app.js"

    def test_run_live_kill_btn_not_only_danger(self):
        """run_live.html kill btn should NOT have class 'btn danger'."""
        html = read(RUN_LIVE_PATH)
        # The kill button should use kill-btn, not just danger
        kill_btn_match = re.search(r'id="kill-btn"[^>]*class="[^"]*"', html)
        if kill_btn_match:
            classes = kill_btn_match.group(0)
            assert "kill-btn" in classes, f"Kill button should have kill-btn class: {classes}"
