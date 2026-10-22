# Fleek Portfolio Copilot

A Streamlit account-management decision tool for the Fleek retention case study. It is designed to help an AM team prioritise two different jobs:

1. **Reduce unnecessary brokering** by identifying account-managed customers whose actual behaviour suggests reliance on manual ordering.
2. **Grow self-serve spend** by surfacing high-intent customers and recommending a relevant product-feature nudge.

The tool is rules-based and explainable. It drafts actions for a human to review; it does not send customer messages automatically.

## Features

- Imports the supplied Excel workbook (`Accounts` and `new_accounts` tabs).
- Cleans text/numeric fields and reports missing or malformed values.
- Uses `account_id` as the stable upsert key to add new accounts and update existing ones.
- Stores account data and action statuses in a local SQLite database.
- Segments by behaviour, not ownership alone.
- Prioritises actions and drafts account-specific outreach/call notes.
- Supports action status tracking and an import history.
- Includes a repeat-import test and an explicit second-run workflow.

## Run locally

Requires Python 3.10+.

```bash
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell
# .venv\Scripts\Activate.ps1

pip install -r requirements.txt
streamlit run app.py
```

Open the local URL Streamlit prints in your terminal. Go to **Import data**.

### First run

1. Upload the original case-study workbook.
2. Select **Initial portfolio — import Accounts tab**.
3. Click **Process import**.

### Second run

1. Upload the same workbook again.
2. Select **Second-run batch — import new_accounts tab only**.
3. Click **Process import**.
4. The app should insert previously unseen IDs and update the five IDs that overlap the original portfolio. Re-importing the same batch should not create duplicates.

Use **Reset local demo database** in the sidebar to reset the demo before recording a clean walkthrough.

## Data model and assumptions

- `account_id` is the unique stable key.
- Missing metrics remain missing rather than being silently converted to zero.
- Known ownership strings are normalised.
- A broker-reliant candidate must be account-managed, have at least 50% broker reliance, have at least one manual order, and show at least two of three weak digital signals: no more than 7 app-active days, no more than 20 PDP views, and no more than 1 offer in the six-month window.
- Self-serve growth opportunities are identified using portfolio-relative high-intent thresholds and/or a potential handpick/bundle mix opportunity. The rules are starting hypotheses and should be reviewed with actual portfolio distributions.
- Missing GMV trend is explicitly surfaced as missing. A reported decline is a reason to verify the monthly series, not proof of churn.
- Bundle is only a proxy for non-handpick product types. Build-a-bundle usage is not separately tracked.
- Drafts are suggestions for an AM to review and edit, not automated outbound communication.

## Architecture

```text
Excel workbook / incoming batch
            |
            v
  Validate + normalise data
            |
            v
 SQLite keyed upsert by account_id
            |
            v
 Behavioural segmentation
            |
            v
 Explainable next-best-action rules
            |
            v
 Streamlit dashboard + human review
            |
            v
 Action status / notes + import log
```

## Scale and production considerations

The case-study version uses SQLite for a simple local demo and keyed upserts. The transformation code is separated from the UI so the same logic can be reused in a scheduled job or agent workflow.

For a production book of 30,000+ accounts, use a managed persistent database, add authentication/role-based access, structured logging, automated scheduled ingestion, monitoring, backups and tests. Do not rely on a hosted app's local filesystem for durable state. Do not commit the supplied real anonymised portfolio data to a public repository; follow the interviewer's data-handling instructions.

## Project structure

- `app.py` — Streamlit interface and workflow.
- `data_processing.py` — workbook reading, cleaning, SQLite persistence, import log and action state.
- `segmentation.py` — behavioural segments and feature-nudge selection.
- `recommendations.py` — priorities, explanations and draft outreach.
- `tests/test_processing.py` — core ingestion regression tests.
