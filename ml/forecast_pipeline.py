"""Weekly demand forecast for the 40 SKUs in data/lead_times.csv.

Run from the repo root:   python ml/forecast_pipeline.py
Writes ml/forecast.csv (160 rows) and ml/backtest_report.json.

Model: one global HistGradientBoostingRegressor (scikit-learn, no extra dependency) trained on
log1p(units) with a *direct* strategy per horizon h=1..4. It is blended with a seasonal-aware
baseline ensemble. Rarely-sold SKUs use a TSB/Croston-style rate; brand-new SKUs use a
category-level prior blended with their own few weeks.

Leakage rule: a training row is built from an origin week t (last observed week) and a target
week t+h. A row may be used for a forecast made at cutoff T only if t+h <= T. See `train_rows`.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = Path(__file__).resolve().parent
HORIZONS = (1, 2, 3, 4)
FORECAST_WEEKS = ["2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19"]
SEEDS = (0, 1, 2)
MIN_HIST = 3        # weeks of history needed before an origin can produce training rows
REL_TARGET = True   # model log1p(y) minus the SKU's own trailing level, so it learns shape (promo, Diwali), not scale


# ----------------------------------------------------------------------------- data
def load():
    s = pd.read_csv(DATA / "sales_history.csv", parse_dates=["week_start"])
    y = s.pivot(index="week_start", columns="sku", values="units_sold").sort_index()
    promo = s.pivot(index="week_start", columns="sku", values="promo_flag").sort_index()
    lead = pd.read_csv(DATA / "lead_times.csv")
    skus = list(lead["sku"])
    y, promo = y[skus], promo[skus].fillna(0)
    fut = pd.read_csv(DATA / "promo_calendar.csv", parse_dates=["week_start"])
    fpromo = fut.pivot(index="week_start", columns="sku", values="promo_flag").sort_index()[skus]
    diwali = pd.to_datetime(pd.read_csv(DATA / "festival_calendar.csv")["date"]).tolist()
    cat = pd.read_csv(DATA / "catalogue.csv").set_index("sku")["category"]
    return y, promo, fpromo, diwali, cat.reindex(skus), skus


def monday(d):
    d = pd.Timestamp(d)
    return d - pd.Timedelta(days=d.weekday())


def weeks_to_diwali(week, diwali):
    """Signed weeks from `week` to the Diwali week, using the nearest Diwali; clipped to [-8, 12]."""
    diffs = [(monday(d) - week).days / 7 for d in diwali]
    best = min(diffs, key=lambda x: abs(x))
    return float(np.clip(best, -8, 12))


# ----------------------------------------------------------------------------- features
def tsb_rate(hist: np.ndarray, a=0.15, b=0.15) -> float:
    """Teunter-Syntetos-Babai demand rate for intermittent series."""
    if len(hist) == 0:
        return 0.0
    p = float((hist > 0).mean())
    nz = hist[hist > 0]
    z = float(nz.mean()) if len(nz) else 0.0
    prob = p
    for v in hist:
        prob = prob + b * ((1.0 if v > 0 else 0.0) - prob)
    return prob * z


def feature_row(sku, hist: pd.Series, origin, h, promo_hist, promo_target, diwali, cat_code):
    """Features available at `origin` (last observed week) for target week origin+h.
    `hist` must contain ONLY weeks <= origin (callers slice it)."""
    target = origin + pd.Timedelta(weeks=h)
    v = hist.values.astype(float)
    lv = np.log1p(v)
    n = len(v)

    def tail_mean(k):
        return float(lv[-k:].mean()) if n else np.nan

    def lag(k):
        return float(lv[-k]) if n >= k else np.nan

    last_year_idx = target - pd.Timedelta(weeks=52)
    ly = hist.get(last_year_idx, np.nan)
    ly_near = hist.loc[last_year_idx - pd.Timedelta(weeks=1): last_year_idx + pd.Timedelta(weeks=1)]
    woy = target.isocalendar().week
    return {
        "h": h,
        "n_hist": n,
        "lag1": lag(1), "lag2": lag(2), "lag3": lag(3), "lag4": lag(4),
        "m4": tail_mean(4), "m8": tail_mean(8), "m13": tail_mean(13), "m26": tail_mean(26),
        "sd8": float(lv[-8:].std()) if n >= 3 else np.nan,
        "zero_frac26": float((v[-26:] == 0).mean()) if n else np.nan,
        "ly": float(np.log1p(ly)) if not np.isnan(ly) else np.nan,
        "ly_near": float(np.log1p(ly_near.mean())) if len(ly_near) else np.nan,
        "promo_t": float(promo_target),
        "promo_o": float(promo_hist.get(origin, 0.0)),
        "promo_rate26": float(promo_hist.loc[:origin].tail(26).mean()) if n else 0.0,
        "wtd": weeks_to_diwali(target, diwali),
        "wtd_o": weeks_to_diwali(origin, diwali),
        "woy_s": float(np.sin(2 * np.pi * woy / 52)), "woy_c": float(np.cos(2 * np.pi * woy / 52)),
        "cat": cat_code,
    }


def build_rows(y, promo, fpromo, diwali, cat_codes, origins, with_target=True):
    rows = []
    for sku in y.columns:
        for origin in origins:
            hist = y.loc[:origin, sku].dropna()
            if len(hist) < MIN_HIST:
                continue
            ph = promo.loc[:origin, sku]
            for h in HORIZONS:
                target = origin + pd.Timedelta(weeks=h)
                if with_target:
                    if target not in y.index or np.isnan(y.loc[target, sku]):
                        continue
                    pt, yt = promo.loc[target, sku], y.loc[target, sku]
                else:
                    pt, yt = fpromo.loc[target, sku], np.nan
                r = feature_row(sku, hist, origin, h, ph, pt, diwali, cat_codes[sku])
                r.update(sku=sku, origin=origin, target=target, y=yt)
                rows.append(r)
    return pd.DataFrame(rows)


FEATS = ["h", "n_hist", "lag1", "lag2", "lag3", "lag4", "m4", "m8", "m13", "m26", "sd8", "zero_frac26",
         "ly", "ly_near", "promo_t", "promo_o", "promo_rate26", "wtd", "wtd_o", "woy_s", "woy_c", "cat"]


def train_rows(rows: pd.DataFrame, cutoff) -> pd.DataFrame:
    """LEAKAGE GUARD: keep only rows whose *target* week is <= cutoff (the last week we may know)."""
    return rows[rows["target"] <= pd.Timestamp(cutoff)]


# ----------------------------------------------------------------------------- models
def _level(df):
    """The SKU's own recent level (log scale), known at the origin: mean of the last 8 weeks, else of the last 4."""
    lv = df["m8"].where(df["m8"].notna(), df["m4"])
    return lv.fillna(df["lag1"]).fillna(0.0).values


def fit_predict(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    preds = []
    for seed in SEEDS:
        m = HistGradientBoostingRegressor(
            loss="squared_error", learning_rate=0.05, max_iter=350, max_depth=5,
            min_samples_leaf=25, l2_regularization=1.0, random_state=seed,
            categorical_features=[FEATS.index("cat")],
        )
        off_tr = _level(train) if REL_TARGET else 0.0
        off_te = _level(test) if REL_TARGET else 0.0
        m.fit(train[FEATS], np.log1p(train["y"]) - off_tr)
        preds.append(np.expm1(m.predict(test[FEATS]) + off_te))
    return np.clip(np.mean(preds, axis=0), 0, None)


def baselines(y, sku, origin, h):
    hist = y.loc[:origin, sku].dropna()
    target = origin + pd.Timedelta(weeks=h)
    last = float(hist.iloc[-1])
    avg4 = float(hist.tail(4).mean())
    ly = y[sku].dropna().get(target - pd.Timedelta(weeks=52), np.nan)
    return last, avg4, (float(ly) if not np.isnan(ly) else avg4)


def special_forecast(y, sku, origin, h, cat_mean_level):
    """Rare SKUs (>35% zero weeks) -> TSB; new SKUs (<20 weeks) -> blend of own mean and category prior."""
    hist = y.loc[:origin, sku].dropna().values.astype(float)
    if len(hist) < 20:
        w = len(hist) / 20.0
        return w * float(hist.mean()) + (1 - w) * cat_mean_level
    return tsb_rate(hist)


def is_rare(y, sku, origin):
    h = y.loc[:origin, sku].dropna().tail(52)
    return (h == 0).mean() > 0.35


def forecast_components(y, promo, target_promo, diwali, cat_codes, all_rows, origin):
    """Fit on rows whose target <= origin and return, per (sku, target week), the model forecast, the naive
    baseline and (for rare / new SKUs) a special-case forecast. Blending is done by `blend`."""
    origin = pd.Timestamp(origin)
    train = train_rows(all_rows, origin)
    test = []
    for sku in y.columns:
        hist = y.loc[:origin, sku].dropna()
        if len(hist) == 0:
            continue  # SKU not launched yet at this cutoff
        ph = promo.loc[:origin, sku]
        for h in HORIZONS:
            target = origin + pd.Timedelta(weeks=h)
            pt = target_promo.loc[target, sku] if target in target_promo.index else 0
            r = feature_row(sku, hist, origin, h, ph, pt, diwali, cat_codes[sku])
            r.update(sku=sku, origin=origin, target=target)
            test.append(r)
    test = pd.DataFrame(test)
    test["gbm"] = fit_predict(train, test)
    lvl = {c: float(y.loc[:origin, [s for s in y.columns if cat_codes[s] == c]].tail(8).mean().mean())
           for c in set(cat_codes.values())}
    base, special = [], []
    for _, r in test.iterrows():
        sku, h = r["sku"], int(r["h"])
        last, avg4, _ly = baselines(y, sku, origin, h)
        base.append(0.5 * avg4 + 0.5 * last)
        n_obs = len(y.loc[:origin, sku].dropna())
        special.append(special_forecast(y, sku, origin, h, lvl[cat_codes[sku]]) if (n_obs < 20 or is_rare(y, sku, origin)) else np.nan)
    test["base"], test["special"] = base, special
    test["n_obs"] = [len(y.loc[:origin, s].dropna()) for s in test["sku"]]
    return test


def blend(comp: pd.DataFrame, w: float) -> pd.Series:
    """Common SKUs: w*GBM + (1-w)*baseline. New SKUs (<20 weeks): own-mean/category prior only.
    Rare SKUs: half TSB (intermittent-demand rate), half GBM."""
    common = w * comp["gbm"] + (1 - w) * comp["base"]
    out = np.where(comp["special"].isna(), common, np.where(comp["n_obs"] < 20, comp["special"], 0.5 * comp["special"] + 0.5 * comp["gbm"]))
    return pd.Series(np.clip(out, 0, None), index=comp.index)


# ----------------------------------------------------------------------------- backtest
def metrics(df):
    e = df["pred"] - df["actual"]
    return {"MAE": float(e.abs().mean()), "RMSE": float(np.sqrt((e ** 2).mean())),
            "WAPE": float(e.abs().sum() / max(df["actual"].sum(), 1e-9))}


def main():
    y, promo, fpromo, diwali, cat, skus = load()
    cat_codes = {s: int(pd.Categorical(cat).categories.get_loc(cat[s])) for s in skus}
    last_obs = y.index.max()
    all_origins = list(y.index)
    rows = build_rows(y, promo, fpromo, diwali, cat_codes, all_origins, with_target=True)

    # Rolling-origin backtest: each cutoff trains only on targets <= cutoff.
    cutoffs = [pd.Timestamp(c) for c in
               ["2025-09-15", "2025-12-01", "2026-03-02", "2026-05-18", "2026-06-29", "2026-07-27", "2026-08-24"]]
    rec = []
    for T in cutoffs:
        comp = forecast_components(y, promo, promo, diwali, cat_codes, rows, T)
        for blend_w in (0.0, 0.5, 0.7, 1.0):
            comp["pred"] = blend(comp, blend_w)
            for _, r in comp.iterrows():
                tgt, sku = r["target"], r["sku"]
                if np.isnan(y.loc[tgt, sku]):
                    continue
                last, avg4, ly = baselines(y, sku, T, int(r["h"]))
                rec.append(dict(w=blend_w, cutoff=T, sku=sku, target=tgt, pred=float(r["pred"]),
                                actual=float(y.loc[tgt, sku]), last=last, avg4=avg4, ly=ly))
    bt = pd.DataFrame(rec)
    report = {"cutoffs": [str(c.date()) for c in cutoffs], "by_blend": {}, "baselines": {}}
    base_df = bt[bt.w == 1.0]
    for name in ("last", "avg4", "ly"):
        report["baselines"][name] = metrics(base_df.assign(pred=base_df[name]))
    for w, g in bt.groupby("w"):
        report["by_blend"][str(w)] = metrics(g)
    best_w = min(report["by_blend"], key=lambda k: report["by_blend"][k]["MAE"])
    report["chosen_blend_weight"] = float(best_w)
    best_base = min(report["baselines"], key=lambda k: report["baselines"][k]["MAE"])
    report["best_baseline"] = best_base
    report["improvement_vs_best_baseline_MAE_pct"] = 100 * (
        1 - report["by_blend"][best_w]["MAE"] / report["baselines"][best_base]["MAE"])
    chosen = bt[bt.w == float(best_w)]
    per_sku = chosen.groupby("sku").apply(lambda g: metrics(g)["WAPE"], include_groups=False).sort_values()
    report["worst_skus_by_WAPE"] = {k: round(v, 3) for k, v in per_sku.tail(6).items()}
    # Diwali-window cutoff only (2025-09-15 -> weeks to Oct 6 2025)
    d = chosen[chosen.cutoff == pd.Timestamp("2025-09-15")]
    report["diwali_window_2025"] = {"model": metrics(d), "same_week_last_year_baseline_unavailable": True,
                                    "last_value": metrics(d.assign(pred=d["last"])),
                                    "recent_avg": metrics(d.assign(pred=d["avg4"]))}
    (OUT / "backtest_report.json").write_text(json.dumps(report, indent=2))

    # Final forecast
    comp = forecast_components(y, promo, fpromo, diwali, cat_codes, rows, last_obs)
    comp["pred"] = blend(comp, float(best_w))
    out = pd.DataFrame([(r["sku"], r["target"].strftime("%Y-%m-%d"), round(float(r["pred"]), 3)) for _, r in comp.iterrows()],
                       columns=["sku", "week_start", "forecast_units"]).sort_values(["sku", "week_start"])
    assert len(out) == 160 and set(out.week_start) == set(FORECAST_WEEKS) and (out.forecast_units >= 0).all()
    out.to_csv(OUT / "forecast.csv", index=False)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
