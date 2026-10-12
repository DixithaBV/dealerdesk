"""Post-generation checks. The model's reply is only released if every price, stock number and SKU in it
can be traced to a tool result obtained during THIS request. Django-free."""
import re
from decimal import Decimal, InvalidOperation

SKU_RE = re.compile(r"\b([A-Z]{3}-\d{4})\b")
MONEY_RE = re.compile(r"(?:₹|Rs\.?|INR)\s*([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*(?:rupees|INR)\b", re.I)
QTY_RE = re.compile(r"(\d[\d,]*)\s*(?:units?|pcs|pieces|nos|in\s+stock|available|left|remaining)\b"
                    r"|(?:stock|available|availability|quantity)\s*(?:is|of|:|=|-)?\s*(\d[\d,]*)\b", re.I)
PROMO_RE = re.compile(r"(\d+\s*%\s*(off|discount)|free\s+of\s+charge|coupon|promo\s*code|VIKMO-[A-Z0-9-]+)", re.I)


def _dec(s):
    try:
        return Decimal(s.replace(",", ""))
    except InvalidOperation:
        return None


def extract_skus(text):
    return list(dict.fromkeys(SKU_RE.findall(text or "")))


def non_latin_ratio(text):
    """Share of letters outside the Latin scripts (Arabic, CJK, Cyrillic ...)."""
    letters = [c for c in (text or "") if c.isalpha()]
    return sum(1 for c in letters if ord(c) > 0x024F) / len(letters) if letters else 0.0


def check_reply(reply, facts, user_text="", known_skus=None):
    """facts = {"prices": set(Decimal), "quantities": set(int), "skus": set(str)} gathered from this turn's tool results.
    Returns a list of problems (empty = fine)."""
    problems = []
    prices = {Decimal(p) for p in facts.get("prices", set())}
    qtys = set(facts.get("quantities", set())) | {int(n) for n in re.findall(r"\d+", user_text or "")}
    for m in MONEY_RE.finditer(reply):
        amt = _dec(m.group(1) or m.group(2))
        if amt is None:
            continue
        ok = any(amt == p or (p > 0 and amt % p == 0 and amt / p <= 10000) for p in prices)
        if not ok:
            problems.append(f"amount {amt} does not come from a tool result")
    for m in QTY_RE.finditer(reply):
        n = int((m.group(1) or m.group(2)).replace(",", ""))
        if n not in qtys:
            problems.append(f"quantity {n} does not come from a tool result")
    if known_skus is not None:
        for s in extract_skus(reply):
            if s not in known_skus:
                problems.append(f"SKU {s} does not exist")
    if non_latin_ratio(reply) > 0.3 and non_latin_ratio(user_text) < 0.3:
        problems.append("the reply is not in the language the dealer wrote in; answer in English")
    returned = set(facts.get("skus", set()))
    has_figures = bool(MONEY_RE.search(reply) or QTY_RE.search(reply))  # already checked above
    if returned and not (set(extract_skus(reply)) & returned) and not has_figures and "?" not in reply:
        problems.append("the reply does not mention any part the tools returned; answer the question using those parts")
    if PROMO_RE.search(reply) and not PROMO_RE.search(user_text or ""):
        problems.append("reply contains a discount / promo claim that is not in the database")
    return problems


def clean_reply(text):
    """Remove reasoning that some Gemini models leak in front of the answer, e.g. a stray token on its own line
    ("\u1ec7m\n...") or a planning sentence glued to the answer ("Preferences checked. Now replying.Yes, ...")."""
    t = (text or "").strip()
    first, sep, rest = t.partition("\n")
    odd = any(c.isalpha() and ord(c) > 0x024F for c in first)
    if sep and rest.strip() and len(first) <= 40 and (odd or "thought" in first.lower()):
        t = rest.strip()
    t = re.sub(r"^[^\n]{0,80}?\bNow replying\.\s*", "", t)
    return t
