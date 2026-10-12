`forecast_pipeline.py` builds `forecast.csv` (160 rows: 40 SKUs × weeks 2026-09-28, 10-05, 10-12, 10-19) and `backtest_report.json` (rolling-origin validation).
Run from the repo root: `pip install -r ml/requirements-ml.txt && python ml/forecast_pipeline.py`. Method and validation: see DECISIONS.md Q6-Q7.
