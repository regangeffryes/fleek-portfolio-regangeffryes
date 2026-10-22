import numpy as np
import pandas as pd

def _num(df, col):
    return pd.to_numeric(df[col], errors="coerce") if col in df.columns else pd.Series(np.nan, index=df.index)

def add_segments(raw):
    df = raw.copy()
    owner = df["ownership"].astype("string").str.strip().str.lower()
    broker = _num(df, "broker_reliance_pct")
    manual = _num(df, "manual_orders")
    app_days = _num(df, "app_active_days_6m")
    pdp = _num(df, "pdp_views_6m")
    offers = _num(df, "make_an_offer_6m")
    gmv = _num(df, "gmv_total_6m")
    handpick = _num(df, "handpick_orders")
    bundles = _num(df, "bundle_orders")
    bundle_share = _num(df, "bundle_gmv_share_pct")
    chats = _num(df, "chat_threads")
    video = _num(df, "video_call_requests")

    # Low engagement is defined relative to the business brief and deliberately
    # conservative: at least two weak signals plus evidence of manual ordering.
    low_app = app_days.le(7)
    low_pdp = pdp.le(20)
    low_offers = offers.le(1)
    low_signal_count = low_app.fillna(False).astype(int) + low_pdp.fillna(False).astype(int) + low_offers.fillna(False).astype(int)
    broker_reliant = (
        owner.str.contains("account managed", na=False)
        & broker.ge(50)
        & manual.gt(0)
        & low_signal_count.ge(2)
    )

    # Relative thresholds adapt to the supplied book instead of assuming a
    # fixed GMV definition. Missing values are not imputed to zero.
    valid_gmv = gmv.dropna()
    gmv_median = float(valid_gmv.median()) if len(valid_gmv) else 0
    pdp_cut = float(pdp.dropna().quantile(0.75)) if pdp.notna().any() else float("inf")
    offer_cut = float(offers.dropna().quantile(0.75)) if offers.notna().any() else float("inf")
    high_intent = pdp.ge(pdp_cut) | offers.ge(offer_cut)
    low_spend = gmv.le(gmv_median)

    ownership_self = owner.str.contains("self", na=False)
    ownership_managed = owner.str.contains("account managed", na=False)

    # A product-mix opportunity is a hypothesis, not a proven reason for low spend.
    handpick_led = handpick.gt(bundles) & bundle_share.lt(50)
    low_feature_adoption = chats.fillna(0).eq(0) | video.fillna(0).eq(0)
    self_serve_growth = ownership_self & ( (high_intent & low_spend) | handpick_led | low_feature_adoption )

    segments = []
    for idx in df.index:
        if bool(broker_reliant.loc[idx]):
            segment = "Broker-reliant"
        elif bool(ownership_self.loc[idx]):
            segment = "Self-serve growth opportunity" if bool(self_serve_growth.loc[idx]) else "Healthy self-serve"
        elif bool(ownership_managed.loc[idx]):
            segment = "Healthy account-managed"
        else:
            segment = "Needs review"
        segments.append(segment)
    df["segment"] = segments

    # Assign feature nudges for self-serve customers using observed gaps.
    feature = []
    for idx in df.index:
        if df.at[idx, "segment"] != "Self-serve growth opportunity":
            feature.append("—")
            continue
        p = pdp.loc[idx]; o = offers.loc[idx]; c = chats.loc[idx]; v = video.loc[idx]
        h = handpick.loc[idx]; b = bundles.loc[idx]; bs = bundle_share.loc[idx]
        if pd.notna(h) and pd.notna(b) and pd.notna(bs) and h > b and bs < 50:
            feature.append("Bundles / build-a-bundle")
        elif pd.notna(p) and p >= pdp_cut and (pd.isna(c) or c == 0):
            feature.append("Chat")
        elif pd.notna(o) and o >= offer_cut and (pd.isna(v) or v == 0):
            feature.append("Video call")
        elif pd.isna(c) or c == 0:
            feature.append("Chat")
        elif pd.isna(v) or v == 0:
            feature.append("Video call")
        else:
            feature.append("Bundles / build-a-bundle")
    df["recommended_feature"] = feature
    df.attrs["thresholds"] = {
        "portfolio_median_gmv": gmv_median,
        "pdp_75th_percentile": pdp_cut,
        "offers_75th_percentile": offer_cut,
    }
    return df
