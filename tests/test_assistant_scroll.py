import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSISTANT_JS = ROOT / "static" / "assistant.js"


def test_assistant_scroll_uses_conditional_autoscroll():
    """The assistant chat should only auto-scroll when the user is already near the bottom."""
    assert ASSISTANT_JS.exists(), f"{ASSISTANT_JS} not found"
    source = ASSISTANT_JS.read_text()

    # Helpers must exist.
    assert "function isNearBottom()" in source
    assert "function maybeScrollToBottom()" in source
    assert "function scrollToBottom()" in source

    # Only one direct assignment to messagesEl.scrollTop should remain, inside scrollToBottom.
    direct_matches = list(re.finditer(r"messagesEl\.scrollTop\s*=\s*messagesEl\.scrollHeight", source))
    assert len(direct_matches) == 1, (
        f"expected exactly one direct messagesEl.scrollTop assignment, found {len(direct_matches)}"
    )
    match = direct_matches[0]
    func_start = source.rfind("function scrollToBottom()", 0, match.start())
    assert func_start != -1, "direct scroll assignment must live inside scrollToBottom helper"

    # The conditional helper must be invoked in the three content update sites.
    calls = list(re.finditer(r"maybeScrollToBottom\(\)", source))
    assert len(calls) >= 3, f"expected maybeScrollToBottom called at least 3 times, found {len(calls)}"
