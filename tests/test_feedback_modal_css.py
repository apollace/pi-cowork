"""Tests for Ticket #182 — Fix Give Feedback modal UI on narrow viewports.

Verifies:
  - .modal-content has min-width: 0 so flex items can shrink below intrinsic child width
  - .modal-content textarea has width: 100% so bare textareas fill the container
"""

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS_PATH = os.path.join(ROOT, "static", "style.css")
TICKET_DETAIL_PATH = os.path.join(ROOT, "templates", "ticket_detail.html")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestFeedbackModalCSS:
    """Verify the targeted CSS fixes exist."""

    def test_modal_content_has_min_width_zero(self):
        css = _read(CSS_PATH)
        # Find the top-level .modal-content rule (not inside @media)
        # Look for the block that has both max-width and min-width
        matches = list(re.finditer(r"\.modal-content\s*\{([^}]+)\}", css))
        assert len(matches) >= 1, ".modal-content rule not found"
        rule = None
        for m in matches:
            if "max-width: 540px" in m.group(1):
                rule = m.group(1)
                break
        assert rule is not None, ".modal-content rule with max-width: 540px not found"
        assert "min-width: 0" in rule, ".modal-content must declare min-width: 0"

    def test_modal_content_textarea_width_100(self):
        css = _read(CSS_PATH)
        # Extract the .modal-content textarea rule
        m = re.search(r"\.modal-content\s+textarea\s*\{([^}]+)\}", css)
        assert m is not None, ".modal-content textarea rule not found"
        rule = m.group(1)
        assert "width: 100%" in rule, ".modal-content textarea must declare width: 100%"

    def test_modals_use_modal_content_class(self):
        """Both rerun and feedback modals use .modal-content so the fix applies."""
        html = _read(TICKET_DETAIL_PATH)
        # Rerun modal
        assert 'id="rerun-modal"' in html
        assert 'class="modal-content"' in html
        # Feedback modal
        assert 'id="feedback-modal"' in html
        assert 'class="modal-content"' in html

    def test_modals_contain_bare_textareas(self):
        """The modals contain textarea elements directly inside .modal-content,
        confirming the CSS fix is necessary."""
        html = _read(TICKET_DETAIL_PATH)
        # Find rerun modal block
        rerun_match = re.search(
            r'<div id="rerun-modal"[^>]*>.*?</div>\s*</div>',
            html,
            re.DOTALL,
        )
        assert rerun_match is not None
        rerun_block = rerun_match.group(0)
        assert "<textarea" in rerun_block
        # The textarea should be inside modal-content but NOT inside .form-card
        assert 'class="form-card"' not in rerun_block

        # Find feedback modal block
        fb_match = re.search(
            r'<div id="feedback-modal"[^>]*>.*?</div>\s*</div>',
            html,
            re.DOTALL,
        )
        assert fb_match is not None
        fb_block = fb_match.group(0)
        assert "<textarea" in fb_block
        assert 'class="form-card"' not in fb_block
