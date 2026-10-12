"""Catalogue text is DATA. Before any catalogue text reaches the model we drop sentences that try to give
instructions, and we cap its length. Django-free."""
import re

_INJECTION = re.compile(
    r"(ignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier)|disregard|for\s+ai\b|note\s+for|assistants?\b|"
    r"\[\s*(system|assistant|admin|user)\s*\]|\bsystem\s*(prompt|message)?\s*:|admin\s+mode|developer\s+mode|jailbreak|"
    r"you\s+are\s+now|instruction|override|reveal|prompt|tell\s+the\s+(customer|dealer|user)|"
    r"(\d+\s*%\s*off)|\bdiscount|coupon|promo\s*code|\bcode\b|without\s+check|confirm\s+the\s+(dealer'?s\s+)?order|"
    r"always\s+(say|reply|respond|answer)|<\s*/?\s*(system|assistant|instructions?)\s*>)", re.I)
_BRACKETS = re.compile(r"\[[^\]]{0,200}\]")


def clean_text(text, max_len=140):
    """Return only the harmless leading sentences of a catalogue string."""
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", str(text).strip())
    keep = []
    for s in sentences:
        if _INJECTION.search(s):
            break  # everything after a suspicious sentence is dropped too
        keep.append(_BRACKETS.sub("", s).strip())
    return " ".join(keep)[:max_len].strip()


def looks_like_injection(text):
    return bool(_INJECTION.search(text or ""))
