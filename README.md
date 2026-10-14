# VIKMO DealerDesk — AI / ML track

**Track: `aiml`.** Required parts: products / inventory / dealers, DRAFT orders, **Dealer Assistant (Part C)**, **Forecasting + reorder (Part D)**.
Optional parts also built: full order engine (confirm / dispatch / deliver / cancel, GST, order numbers, idempotency), supplier sync (Part B), dealer-portal frontend (Part E, plain HTML/JS, no build step — open `http://localhost:8000/`).

Video walkthrough (assistant tool-calling loop): **<paste your unlisted YouTube / Loom / Drive link here>**

## LLM provider

**Google Gemini**, model **`gemini-3.5-flash-lite`** (override with `GEMINI_MODEL`). If a model is overloaded (503), rate limited or retired (404) the client fails over to `gemini-flash-lite-latest`, then `gemini-flash-latest`, then `gemini-2.5-flash`. Thinking is set to the lowest level so tool-calling replies take a few seconds. Native function calling over the official `generateContent` REST endpoint using `requests` (no SDK). Key from `GEMINI_API_KEY`. Free tier: https://aistudio.google.com/apikey

## Run (Linux / macOS)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # set DATABASE_URL and GEMINI_API_KEY
python manage.py migrate --noinput
python manage.py seed_data      # safe to run twice
python manage.py runserver 0.0.0.0:8000 --noreload
```

Windows PowerShell: see `SETUP_WINDOWS.md`.

## Tests

```bash
python -m unittest discover -s tests -t .      # no DB / no key needed: retrieval, guard, sanitiser, Gemini client, supplier feed, forecast file + reorder maths
python manage.py test                           # Django tests (need DATABASE_URL; they create a test database): API, order rules, real-PostgreSQL concurrency, sync, assistant with a scripted fake LLM
python manage.py makemigrations --check         # must report "No changes detected"
python supplier_mock/mock_supplier.py &         # then, with the app running on :8000:
python smoke_test.py --base-url http://localhost:8000 --track aiml     # needs a real GEMINI_API_KEY for the assistant check
```

The Django tests use a scripted fake model so they need no API key; the production code path (`assistant/views.py:get_llm`) always uses real Gemini.

## Re-creating the forecast

`pip install -r ml/requirements-ml.txt && python ml/forecast_pipeline.py` writes `ml/forecast.csv` (160 rows) and `ml/backtest_report.json`. The Django app only reads the committed CSV.

## Layout

`catalog/` products, inventory, dealers · `orders/` order engine · `supplier/` sync · `assistant/` Gemini client, tools, retrieval, guard · `forecasting/` forecast + reorder endpoints · `ml/` pipeline + `forecast.csv` · `frontend/` portal · `data/` untouched assignment files · `DECISIONS.md`.

## Assumptions

- `DJANGO_DEBUG` defaults to `0` so that unknown URLs and server errors return the JSON error shape.
- Re-running `seed_data` never overwrites existing rows (so live stock is not reset).
- Chat `dealer_id` is optional; without it the assistant can search and check stock but refuses to create orders.
- If Gemini is unreachable the chat endpoint still answers `200` with a short apology rather than an error.
