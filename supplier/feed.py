"""Supplier feed client + cleaning. Django-free so it can be tested against supplier_mock directly."""
import math
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import requests

MAX_ATTEMPTS = 5
MAX_RETRY_AFTER = 20.0
TOTAL_BUDGET_SECONDS = 105  # the endpoint must answer within 120 s


class SupplierUnavailable(Exception):
    pass


def fetch_all(base_url, api_key, sleep=time.sleep, session=None, max_attempts=MAX_ATTEMPTS, budget=TOTAL_BUDGET_SECONDS):
    """Fetch every page. Returns (items, pages_fetched, requests_made). Raises SupplierUnavailable."""
    s = session or requests.Session()
    url = base_url.rstrip("/") + "/v1/products"
    started = time.monotonic()
    items, pages, made, cursor = [], 0, 0, None
    while True:
        params = {"limit": 20}
        if cursor:
            params["cursor"] = cursor
        body = None
        for attempt in range(1, max_attempts + 1):
            if time.monotonic() - started > budget:
                raise SupplierUnavailable("time budget exhausted")
            made += 1
            wait, status, resp = 0.0, None, None
            try:
                resp = s.get(url, params=params, headers={"X-Api-Key": api_key}, timeout=10)
                status = resp.status_code
            except requests.RequestException:
                status = None  # connection error -> retry
            if status == 200:
                try:
                    body = resp.json()
                    if not isinstance(body, dict) or not isinstance(body.get("items"), list):
                        raise ValueError("bad body")
                    break
                except ValueError:
                    wait = 0.2 * 2 ** (attempt - 1)  # garbled 200: treat like a temporary failure
            elif status == 429:
                try:
                    wait = float(resp.headers.get("Retry-After", 1))
                except (TypeError, ValueError):
                    wait = 1.0
                wait = min(max(wait, 0.0), MAX_RETRY_AFTER) + 0.05
            elif status is None or status >= 500:
                wait = min(0.25 * 2 ** (attempt - 1), 2.0)
            else:  # 401 / 400 / other 4xx: retrying cannot help
                raise SupplierUnavailable(f"supplier returned HTTP {status}")
            if attempt == max_attempts:
                raise SupplierUnavailable(f"page failed after {max_attempts} attempts (last status {status})")
            sleep(wait)
        pages += 1
        items.extend(body["items"])
        cursor = body.get("next_cursor")
        if not cursor:
            return items, pages, made


def parse_price(v):
    """Positive amount with at most 2 decimals -> Decimal, else None."""
    if v is None or isinstance(v, bool):
        return None
    try:
        d = Decimal(str(v).strip())
    except InvalidOperation:
        return None
    if not d.is_finite() or d <= 0 or d.as_tuple().exponent < -2:
        return None
    return d.quantize(Decimal("0.01"))


def parse_ts(v):
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def clean(items):
    """Returns (unique_valid {sku: item}, rejected [{supplier_sku, reason}]).
    Invalid items are removed BEFORE de-duplication, so an invalid newer copy can never win."""
    rejected, valid = [], []
    for it in items:
        if not isinstance(it, dict):
            rejected.append({"supplier_sku": None, "reason": "item is not an object"}); continue
        sup = it.get("supplier_sku")
        sku = it.get("sku")
        if not isinstance(sku, str) or not sku.strip():
            rejected.append({"supplier_sku": sup, "reason": "missing sku"}); continue
        price = parse_price(it.get("price"))
        if price is None:
            rejected.append({"supplier_sku": sup, "reason": "invalid price"}); continue
        valid.append({**it, "sku": sku.strip(), "_price": price, "_ts": parse_ts(it.get("updated_at"))})
    best = {}
    for it in valid:  # on equal timestamps the later-seen copy wins
        cur = best.get(it["sku"])
        if cur is None or it["_ts"] >= cur["_ts"]:
            best[it["sku"]] = it
    return best, rejected
