import io
import pandas as pd
import streamlit as st

from data_processing import (
    EXPECTED_COLUMNS, clean_accounts, read_workbook, ingest_accounts,
    get_accounts, get_import_log, get_action_state, save_action_state,
    get_database_path, reset_demo_database
)
from segmentation import add_segments
from recommendations import add_recommendations
from status_display import STATUS_OPTIONS, show_status, parse_status

st.set_page_config(page_title="Fleek Portfolio Copilot", page_icon="🧵", layout="wide")

st.title("Fleek Portfolio Copilot")
st.caption("A repeatable account-management workflow: protect spend, reduce unnecessary brokering and grow self-serve customers.")

with st.sidebar:
    st.header("Portfolio controls")
    st.caption("Local demo database: data/fleek_portfolio.sqlite")
    st.info("Use the original workbook for the first import. For the second run, choose the new_accounts tab only.")
    if st.button("Reset local demo database", type="secondary"):
        reset_demo_database()
        st.success("Local database reset. Refresh the app to start again.")

tab_overview, tab_migration, tab_growth, tab_actions, tab_ingest, tab_method = st.tabs([
    "Overview", "Migration", "Self-serve growth", "Action queue", "Import data", "Method & assumptions"
])

def portfolio_frame():
    raw = get_accounts()
    if raw.empty:
        return raw
    return add_recommendations(add_segments(raw))

def money(value):
    if pd.isna(value):
        return "—"
    return f"£{value:,.0f}"

def show_table(df, columns):
    available = [c for c in columns if c in df.columns]
    view = df[available].copy()
    if "priority" in view.columns:
        def priority_colour(value):
            palette = {"P1": "#f8caca", "P2": "#fff0bd", "P3": "#d7f0df"}
            return f"background-color: {palette[value]}; color: #202020" if value in palette else ""
        st.dataframe(view.style.map(priority_colour, subset=["priority"]), use_container_width=True, hide_index=True)
    else:
        st.dataframe(view, use_container_width=True, hide_index=True)

df = portfolio_frame()

with tab_ingest:
    st.subheader("Import or update the portfolio")
    st.write("Upload the supplied Excel workbook. The app uses account_id as the stable key, updates matching accounts and inserts new IDs.")
    uploaded = st.file_uploader("Choose Fleek portfolio workbook (.xlsx)", type=["xlsx"], key="portfolio_upload")
    mode = st.radio(
        "What are you importing?",
        [
            "Initial portfolio — import Accounts tab",
            "Second-run batch — import new_accounts tab only",
        ],
        help="Use the first option once. Then choose the second option to demonstrate the supplied second-run batch."
    )
    if uploaded is not None and st.button("Process import", type="primary"):
        try:
            workbook_bytes = uploaded.getvalue()
            sheets = read_workbook(io.BytesIO(workbook_bytes))
            sheet_name = "Accounts" if mode.startswith("Initial") else "new_accounts"
            if sheet_name not in sheets:
                st.error(f"Workbook does not contain the required '{sheet_name}' tab.")
            else:
                cleaned, quality = clean_accounts(sheets[sheet_name])
                result = ingest_accounts(cleaned, source=sheet_name, quality=quality)
                st.success(
                    f"Import complete: {result['inserted']} new accounts added, "
                    f"{result['updated']} existing accounts updated, "
                    f"{result['unchanged']} unchanged, {result['rejected']} rejected."
                )
                st.write("Data-quality summary")
                st.json(quality)
                st.write("Import record")
                st.json(result)
                st.rerun()
        except Exception as exc:
            st.error(f"Import failed: {exc}")
            st.exception(exc)

with tab_overview:
    if df.empty:
        st.info("Start in **Import data** to load the Accounts tab.")
    else:
        st.subheader("Portfolio at a glance")
        total_gmv = pd.to_numeric(df["gmv_total_6m"], errors="coerce").sum()
        broker = df[df["segment"] == "Broker-reliant"]
        broker_gmv = pd.to_numeric(broker["gmv_total_6m"], errors="coerce").sum()
        priority = int(df["priority"].isin(["P1", "P2"]).sum())
        selfserve = df[df["segment"].str.contains("Self-serve", na=False)]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Accounts", f"{len(df):,}")
        c2.metric("6-month GMV", money(total_gmv))
        c3.metric("Broker-reliant accounts", f"{len(broker):,}")
        c4.metric("Priority actions", f"{priority:,}")
        st.caption(f"GMV associated with broker-reliant accounts: {money(broker_gmv)}. This is exposure to manage carefully, not automatically revenue at risk.")
        left, right = st.columns(2)
        with left:
            st.markdown("**Accounts by behavioural segment**")
            st.bar_chart(df["segment"].value_counts())
        with right:
            st.markdown("**GMV by segment**")
            gmv_segment = df.groupby("segment", dropna=False)["gmv_total_6m"].sum().sort_values(ascending=False)
            st.bar_chart(gmv_segment)
        st.markdown("**Highest-priority actions**")
        top = df.sort_values(["priority_rank", "gmv_total_6m"], ascending=[True, False]).head(12)
        show_table(top, ["account_id", "ownership", "segment", "gmv_total_6m", "gmv_trend_pct", "priority", "recommended_action", "reason"])

with tab_migration:
    st.subheader("Migration: reduce unnecessary brokering without losing spend")
    if df.empty:
        st.info("Import the portfolio to see migration candidates.")
    else:
        migration = df[df["segment"] == "Broker-reliant"].copy()
        st.write(f"**{len(migration)}** accounts meet the initial behavioural rule. Review the evidence before contacting customers.")
        if not migration.empty:
            migration["gmv_display"] = migration["gmv_total_6m"].map(money)
            show_table(migration.sort_values(["priority_rank", "gmv_total_6m"], ascending=[True, False]), [
                "account_id", "buyer_persona", "country", "gmv_display", "broker_reliance_pct",
                "manual_orders", "app_active_days_6m", "pdp_views_6m", "make_an_offer_6m",
                "priority", "reason", "recommended_action", "draft_outreach"
            ])
        st.caption("Migration should be staged: demonstrate discovery and ordering, support the first self-serve purchase, then monitor spend and intervene if it drops.")

with tab_growth:
    st.subheader("Self-serve: grow spend while keeping customers independent")
    if df.empty:
        st.info("Import the portfolio to see growth opportunities.")
    else:
        growth = df[df["segment"].isin(["Self-serve growth opportunity", "Healthy self-serve"])].copy()
        growth = growth[growth["segment"] == "Self-serve growth opportunity"]
        st.write(f"**{len(growth)}** self-serve accounts currently meet the growth-opportunity rule.")
        if not growth.empty:
            growth["gmv_display"] = growth["gmv_total_6m"].map(money)
            show_table(growth.sort_values(["priority_rank", "gmv_total_6m"], ascending=[True, False]), [
                "account_id", "buyer_persona", "country", "gmv_display", "pdp_views_6m",
                "make_an_offer_6m", "chat_threads", "video_call_requests", "handpick_orders",
                "bundle_orders", "recommended_feature", "priority", "reason", "draft_outreach"
            ])
        st.caption("Bundle is a proxy for non-handpick product types; the source data does not separately track build-a-bundle usage.")

with tab_actions:
    st.subheader("Daily action queue")
    if df.empty:
        st.info("Import the portfolio to generate the action queue.")
    else:
        f1, f2, f3 = st.columns(3)
        segments = ["All"] + sorted(df["segment"].dropna().unique().tolist())
        priorities = ["All", "P1", "P2", "P3"]
        statuses = ["All", "Pending", "In progress", "Completed", "Needs review"]
        selected_segment = f1.selectbox("Segment", segments)
        selected_priority = f2.selectbox("Priority", priorities)
        selected_status = f3.selectbox("Action status", statuses)
        queue = df.copy()
        if selected_segment != "All":
            queue = queue[queue["segment"] == selected_segment]
        if selected_priority != "All":
            queue = queue[queue["priority"] == selected_priority]
        state_rows = []
        for _, row in queue.iterrows():
            state = get_action_state(row["account_id"], row["action_key"])
            state_rows.append(state)
        if state_rows:
            queue["action_status"] = [x.get("status", "Pending") for x in state_rows]
        else:
            queue["action_status"] = []
        if selected_status != "All":
            queue = queue[queue["action_status"] == selected_status]
        queue = queue.sort_values(["priority_rank", "gmv_total_6m"], ascending=[True, False])
        st.caption("Priority: 🔴 P1 = urgent, 🟡 P2 = follow up, 🟢 P3 = routine. These are decision-support flags, not guaranteed outcomes.")
        st.write(f"{len(queue)} actions match your filters.")
        st.markdown("**Edit action statuses in the table**")
        st.caption("Click any cell under Action status, choose a colour-coded option, then click Save status changes. Draft messages are edited below.")
        editor_cols = ["account_id", "segment", "priority", "gmv_total_6m", "recommended_action", "recommended_feature", "reason", "action_status"]
        editor_view = queue[editor_cols].copy().reset_index(drop=True)
        editor_view["priority"] = editor_view["priority"].map({"P1": "🔴 P1 — High", "P2": "🟡 P2 — Medium", "P3": "🟢 P3 — Low"}).fillna(editor_view["priority"])
        editor_view["action_status"] = editor_view["action_status"].map(show_status)
        edited_queue = st.data_editor(
            editor_view,
            use_container_width=True,
            hide_index=True,
            key="queue_status_editor",
            disabled=[c for c in editor_cols if c != "action_status"],
            column_config={
                "action_status": st.column_config.SelectboxColumn("Action status", options=STATUS_OPTIONS, required=True, width="medium"),
                "priority": st.column_config.TextColumn("Priority", width="medium"),
                "reason": st.column_config.TextColumn("Reason", width="large"),
            },
        )
        changed = edited_queue["action_status"].ne(editor_view["action_status"])
        st.caption(f"{int(changed.sum())} unsaved status change(s).")
        if st.button("Save status changes", type="primary", disabled=not changed.any()):
            for i in edited_queue.index[changed]:
                original = queue.iloc[int(i)]
                current = get_action_state(original["account_id"], original["action_key"])
                save_action_state(
                    original["account_id"], original["action_key"],
                    parse_status(edited_queue.at[i, "action_status"]),
                    current.get("note", ""), current.get("draft_override"),
                )
            st.success(f"Saved {int(changed.sum())} action status update(s).")
            st.rerun()
        st.divider()
        st.markdown("**Review an account action**")
        account_ids = queue["account_id"].astype(str).tolist()
        if account_ids:
            selected_id = st.selectbox("Account", account_ids, key="action_account")
            selected_row = queue[queue["account_id"].astype(str) == selected_id].iloc[0]
            current_state = get_action_state(selected_id, selected_row["action_key"])
            st.markdown(f"**{selected_row['recommended_action']}**")
            st.write(selected_row["reason"])
            st.caption("Edit this draft for the customer. Your changes are saved only when you click Save action & draft; no message is sent.")
            draft_key = f"draft_{selected_id}_{selected_row['action_key']}"
            # A different account/action gets its own editor, preserving unsaved edits during reruns.
            if draft_key not in st.session_state:
                st.session_state[draft_key] = (current_state.get("draft_override")
                    if current_state.get("draft_override") is not None
                    else str(selected_row["draft_outreach"]))
            edited_draft = st.text_area("Editable outreach message", height=170, key=draft_key)
            if st.button("Show text to copy"):
                st.code(edited_draft, language=None)
                st.info("Select and copy the message above. It has not been sent.")
            current_status = current_state.get("status", "Pending")
            current_label = show_status(current_status)
            new_status_label = st.selectbox("Action status", STATUS_OPTIONS, index=STATUS_OPTIONS.index(current_label), key=f"status_{selected_id}_{selected_row['action_key']}")
            new_status = parse_status(new_status_label)
            note = st.text_input("Internal note (optional)", value=current_state.get("note", ""), key=f"note_{selected_id}")
            if st.button("Save action & draft", type="primary"):
                save_action_state(selected_id, selected_row["action_key"], new_status, note, edited_draft)
                st.success("Action status and edited message saved.")
                st.rerun()
        else:
            st.info("No accounts match the selected filters.")

with tab_method:
    st.subheader("Decision logic and operating model")
    st.markdown("""
**Data flow**
1. Upload the workbook or next batch.
2. Validate columns, normalise text and coerce numeric fields.
3. Upsert by `account_id`; keep action status separate from account metrics.
4. Recalculate segment, priority, rationale and next-best action.
5. A human reviews high-impact actions, edits the draft and records the outcome.

**Behavioural segmentation**
- Broker-reliant: account-managed, meaningful manual orders, high broker reliance, and at least two low digital-engagement signals.
- Healthy account-managed: account-managed but not meeting the broker-reliant rule.
- Self-serve growth opportunity: self-serve ownership plus high intent relative to the portfolio and relatively low six-month GMV, or a clear handpick / bundle adoption gap.
- Healthy self-serve: other self-serve accounts.

**Guardrails**
- Blank values remain missing; they are not silently treated as zero.
- Missing trend is not automatically interpreted as a decline.
- Recommendations are rules-based and explainable; they are not claims of causal impact.
- Draft messages are not sent automatically. An account manager can edit and save a message in the Action queue.
- Action statuses are editable in the queue table with colour-coded dropdown choices; click Save status changes to persist them.
- Saved drafts and action statuses use local SQLite storage; Streamlit Community Cloud restarts can erase this data.
- The supplied workbook is real anonymised data: do not publish it in a public repository.

**Scale**
The data-processing logic is separated from the UI and uses keyed upserts. For a 30,000-account production portfolio, use a managed persistent database, add structured logs and scheduled jobs, and avoid relying on a hosted app's local filesystem for durable storage.
""")
    st.subheader("Recent imports")
    log = get_import_log()
    if log:
        st.dataframe(pd.DataFrame(log), use_container_width=True, hide_index=True)
    else:
        st.caption("No imports recorded yet.")
