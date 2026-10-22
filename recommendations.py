import hashlib
import pandas as pd

def _safe(value, fallback="not available"):
    if pd.isna(value):
        return fallback
    return value

def add_recommendations(raw):
    df = raw.copy()
    actions, reasons, drafts, priorities, ranks, keys = [], [], [], [], [], []
    for _, r in df.iterrows():
        account = str(r.get("account_id", "Unknown account"))
        segment = r.get("segment", "Needs review")
        gmv = pd.to_numeric(pd.Series([r.get("gmv_total_6m")]), errors="coerce").iloc[0]
        gmv_text = f"£{gmv:,.0f}" if pd.notna(gmv) else "unknown GMV"
        trend = pd.to_numeric(pd.Series([r.get("gmv_trend_pct")]), errors="coerce").iloc[0]
        broker = pd.to_numeric(pd.Series([r.get("broker_reliance_pct")]), errors="coerce").iloc[0]
        manual = pd.to_numeric(pd.Series([r.get("manual_orders")]), errors="coerce").iloc[0]
        app = pd.to_numeric(pd.Series([r.get("app_active_days_6m")]), errors="coerce").iloc[0]
        pdp = pd.to_numeric(pd.Series([r.get("pdp_views_6m")]), errors="coerce").iloc[0]
        offers = pd.to_numeric(pd.Series([r.get("make_an_offer_6m")]), errors="coerce").iloc[0]
        feature = r.get("recommended_feature", "—")
        if pd.isna(feature):
            feature = "—"

        if segment == "Broker-reliant":
            action = "Run a staged self-serve migration"
            reason = (
                f"Account-managed with {broker:.0f}% broker reliance and {manual:.0f} manual orders; "
                f"app active days={_safe(app)}, PDP views={_safe(pdp)}, offers={_safe(offers)}. "
                "Introduce a supported first self-serve purchase and monitor spend."
            )
            draft = (
                f"Hi there — I'd like to make it easier for you to find and order stock directly on Fleek, "
                f"while keeping support available when you need it. Could we walk through your next order together "
                f"so you can try the self-serve flow? We'll keep an eye on your buying experience and spend as we make the switch."
            )
            priority = "P1" if pd.notna(gmv) and gmv >= 1000 else "P2"
        elif segment == "Self-serve growth opportunity":
            action = f"Nudge toward {feature.lower()}"
            reason = (
                f"Self-serve account with a potential engagement or product-mix opportunity. "
                f"Signals: PDP views={_safe(pdp)}, offers={_safe(offers)}, six-month GMV={gmv_text}. "
                "Validate the customer's need before treating this as a confirmed growth lever."
            )
            draft = (
                f"Hi there — based on how you've been browsing and buying on Fleek, I thought "
                f"{feature.lower()} could be worth exploring for your next stock order. "
                f"Would it be useful if I shared a quick guide or showed you how it works? "
                f"You can continue ordering independently, and I'm here if you need help."
            )
            priority = "P2" if pd.notna(gmv) and gmv >= 300 else "P3"
        elif segment == "Healthy account-managed":
            action = "Maintain relationship; review self-serve mix"
            reason = (
                f"Account-managed, but behaviour does not meet the broker-reliant rule. "
                f"Broker reliance={_safe(broker)}, app active days={_safe(app)}. "
                "Review account goals and only migrate if it improves the customer experience."
            )
            draft = (
                "Account review note: check upcoming stock needs, current buying process and whether any order types "
                "would be easier for the customer to place themselves. Do not assume broker reliance from ownership alone."
            )
            priority = "P3"
        elif segment == "Healthy self-serve":
            action = "Protect self-serve habit; monitor growth"
            reason = "Self-serve customer not currently flagged by the growth-opportunity rule. Protect the low-friction buying experience."
            draft = "Account review note: monitor spend and feature adoption; reach out only with a relevant, specific reason."
            priority = "P3"
        else:
            action = "Review data and account context"
            reason = "Ownership or behavioural evidence is incomplete or inconsistent; human review is needed before a commercial intervention."
            draft = "Internal review note: validate account ownership, data completeness and recent customer context before contacting."
            priority = "P1"
        # Missing or steeply negative trend raises review urgency, but never overrides segment logic alone.
        if pd.isna(trend):
            reason += " GMV trend is missing; do not infer decline from missing data."
        elif trend <= -50 and segment != "Needs review":
            reason += f" Reported GMV trend is {trend:.0f}%; verify the monthly series before acting on the trend."
            if priority == "P3":
                priority = "P2"
        action_key = hashlib.sha256(f"{account}|{action}|{feature}".encode()).hexdigest()[:16]
        actions.append(action); reasons.append(reason); drafts.append(draft); priorities.append(priority)
        keys.append(action_key)
        ranks.append({"P1": 1, "P2": 2, "P3": 3}.get(priority, 4))
    df["recommended_action"] = actions
    df["reason"] = reasons
    df["draft_outreach"] = drafts
    df["priority"] = priorities
    df["priority_rank"] = ranks
    df["action_key"] = keys
    return df
