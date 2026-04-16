---
name: enterprise-intake
description: |
  Enterprise-specific feedback intake. Three modes: (1) scan — scans dedicated enterprise #acct Slack channels and #elation-feedback for unprocessed feedback, invokes /log-feedback to file Linear issues and customer needs; (2) tracker-write — reads recently filed Linear needs for enterprise accounts and writes rows to the Enterprise Feedback Tracker in Notion, run on-demand or via scheduled task; (3) setup — one-time provisioning of a new enterprise account's Notion tracker page and config entry.

  Trigger phrases: "enterprise intake", "scan enterprise", "enterprise-intake scan", "run enterprise intake", "process enterprise feedback", "enterprise tracker write", "set up enterprise page", "provision enterprise account", "create enterprise tracker for", "add enterprise account"
version: 1.2.0
---

# /enterprise-intake

## Purpose

Three modes:

- **`scan`** — Scans enterprise account Slack channels (and #elation-feedback) for unprocessed product feedback, invokes `/log-feedback` to file Linear issues and customer needs. Run once per week per account (or on-demand before QBRs).
- **`tracker-write`** — Reads recently filed Linear customer needs for enterprise accounts and writes rows to the Enterprise Feedback Tracker in Notion. Run on-demand or via a scheduled task (see PDL-187).
- **`setup`** — One-time provisioning of a new enterprise account's Notion tracker page and config entry. Run this once before an account's first `/enterprise-intake scan`.

Use `/log-feedback scan` for non-enterprise channel scanning.

---

## Config

All IDs live in `~/.claude/config/enterprise-accounts.json`.

> **Remote runner note:** This file must be present on whatever machine runs Claude Code (local or remote agent). It is the source of truth for account configuration. A template is at `feedback-pipeline/config/enterprise-accounts.json.template`. For remote agents, seed the file from the Notion Enterprise Account Pages DB before the first run. See `feedback-pipeline/docs/DEPLOYMENT.md` for full setup instructions.


- `enterprise_feedback_tracker.database_id` / `data_source_id` — Enterprise Feedback Tracker DB
- `enterprise_account_pages.parent_page_id` — parent page where account pages live
- `idempotency_db_id` — "Enterprise Intake — Processed Messages" DB (`40de7d459136413bb932e39b37028df3`). Also used by `/log-feedback` (row: `Channel = C0AJW26J6NQ`, `Account = log-feedback`).
  - Columns: `Channel` (title), `Account` (text), `Processed IDs` (comma-separated `ts` values), `Processed Row IDs` (comma-separated `<ts>:row_<N>` entries for spreadsheet batch continuation)
- `idempotency_db_data_source` — `collection://790d11ce-af1f-4d3e-8816-5c23f15eb6b7`
- `accounts[]` — per-account: name, notion_page_id, notion_page_url, slack_channel, slack_channel_id, linear_customer_id, idempotency_page_id, provisioned_date

**Key channel IDs:**
- `#elation-feedback`: `C0AJW26J6NQ`
- `#feedback-ops`: `C0AQSLQ55KM`

---

## Input

**Scan mode:** `/enterprise-intake scan` or `/enterprise-intake scan [account name]`
- No argument → scan all accounts in config
- Account name argument → scan only that account
- Optional: `last Xd` (e.g., `last 14d`) to override default 7-day lookback window

**Tracker-write mode:** `/enterprise-intake tracker-write` or `/enterprise-intake tracker-write [account name]`
- No argument → process all enterprise accounts
- Account name argument → process only that account

**Setup mode:** `/enterprise-intake setup "[Account Name]"`
- Required: exact account name as it appears in Linear (e.g., "Acme Health")
- Optional: CSM name or Slack user ID, Salesforce account URL, account type, provider count, location count, specialties

---

## Setup Mode

**Only execute when `$ARGUMENTS` begins with `setup`.** For scan invocations, skip to Scan Mode below.

### Setup Step 1 — Validate input

1. Read `~/.claude/config/enterprise-accounts.json`.
2. Check if `accounts` array already contains an entry with `name` matching the provided account name (case-insensitive).
   - If found: report `Account already provisioned at [notion_page_url]` and stop. Do NOT create a duplicate page.
3. Confirm account name with user if ambiguous or if no argument was provided.

### Setup Step 2 — Check for existing feedback

Query the Enterprise Feedback Tracker (`data_source_id: d0e99400-bafe-4fe7-8f6e-8c4260772d45`) for any rows where `Account = [account name]`. Record the count — mentioned in the page callout if rows already exist from a prior intake run.

### Setup Step 3 — Create the account page

Create a new Notion page under the Enterprise Account Pages parent (`parent_page_id: 33ba68c48bc6815ba6a8c32cf4743e76`).

**Page title:** `[Account Name] — Product Feedback Tracker`
**Page icon:** 🏥 (or relevant emoji if account specialty is known)

**Page content:**
```
[CALLOUT — blue, icon 💡]
This page is maintained by the CSM. Fill in the Account Context and Problem Statement sections below.
All feedback rows are auto-populated by /enterprise-intake.
[if rows already exist from Setup Step 2]: ⚠️ [N] existing feedback rows are already in the tracker for this account from prior intake runs.

---

## Account Context
| Field | Value |
|---|---|
| **Account type** | Enterprise |
| **Providers** | — |
| **Locations** | — |
| **Specialties** | — |
| **CSM** | [csm_name if provided, else —] |
| **Salesforce** | [salesforce_url if provided, else —] |
| **Health status** | 🟡 Unknown |
| **Last updated** | [today's date] |

---

## Problem Statement
*2–4 sentences describing the core product challenges this account faces. Use customer-friendly language — describe the underlying problems, not feature requests. CSM-maintained.*

---

## Open Feedback
[linked database section — see Setup Step 4]

---

## Resolved & Declined
[linked database section — see Setup Step 4]
```

Capture the new page ID and URL from the response — needed in Setup Steps 4 and 5.

### Setup Step 4 — Add filtered database views

Add two linked views of the Enterprise Feedback Tracker to the new page using `notion-create-view`.

**View 1 — Open Feedback**
- Parent: new account page (page_id from Setup Step 3)
- Database: `d0e99400-bafe-4fe7-8f6e-8c4260772d45`
- View type: table
- Filter: `Account = [account name]` AND `Status NOT IN (Declined, Completed, Canceled)`
- Sort: Priority ascending (P1 first), then Risk Level (HIGH first)
- Group by: Domain
- Name: "Open Feedback"

**View 2 — Resolved & Declined**
- Parent: new account page (page_id from Setup Step 3)
- Database: `d0e99400-bafe-4fe7-8f6e-8c4260772d45`
- View type: table
- Filter: `Account = [account name]` AND `Status IN (Declined, Completed, Canceled)`
- Sort: Date Logged descending
- Name: "Resolved & Declined"

If `notion-create-view` does not support filtered linked views in the current MCP version, note this to the user and provide step-by-step manual instructions (duplicate a view, set filter Account = [name]).

### Setup Step 5 — Register in config

Update `~/.claude/config/enterprise-accounts.json` by appending to the `accounts` array:

```json
{
  "name": "[account name]",
  "notion_page_id": "[page_id from Setup Step 3]",
  "notion_page_url": "[page_url from Setup Step 3]",
  "csm_slack_user_id": "[if known, else null]",
  "slack_channel": null,
  "slack_channel_id": null,
  "linear_customer_id": null,
  "idempotency_page_id": null,
  "provisioned_date": "[today ISO date]"
}
```

The `slack_channel_id` and `linear_customer_id` fields are filled in later — `slack_channel_id` via manual config update, `linear_customer_id` auto-populated on the first `/enterprise-intake scan` run.

### Setup Step 6 — Confirm and report

```
✅ Enterprise page provisioned for [Account Name]

Notion page: [url]
[if existing rows]: [N] existing feedback rows are already visible in the Open Feedback view.

Next steps for CSM:
1. Open the page and fill in Account Context (providers, locations, specialties, health status)
2. Write the Problem Statement (core product challenges, customer-friendly language)
3. Set Priority (P1–P4) on any existing feedback rows
4. Add the account's dedicated Slack channel ID to enterprise-accounts.json:
   "slack_channel_id": "C..." (find in Slack → channel settings → copy channel ID)

To start automated intake:
   Run: /enterprise-intake scan [account name]
```

---

## Scan Mode

**Only execute when `$ARGUMENTS` begins with `scan` or contains no mode keyword.**

### Step 1 — Load accounts and resolve Slack channels

Read `~/.claude/config/enterprise-accounts.json`.

For each account (or the specified account if an argument was provided):

1. If `slack_channel_id` is already set in config: use it directly. This is the expected state for all active accounts.
2. If `slack_channel_id` is null: **do not attempt a live Slack search at runtime.** Channel IDs are stable — if it's missing from config, update `enterprise-accounts.json` manually with the correct channel ID and re-run. Post a warning and skip this account:
   ```
   ⚠️ [Account Name]: slack_channel_id not set in enterprise-accounts.json. Skipping — add the channel ID to config and re-run.
   ```

Run all channel validations in parallel.

### Step 2 — Determine lookback window

Parse time range from arguments: `last 14d` → 14 days ago, `last 3d` → 3 days.
Default: **7 days**.
Convert to Unix timestamp for the `oldest` parameter.

### Step 3 — Load idempotency state

For each account being scanned:

1. Query the "Enterprise Intake — Processed Messages" DB (`idempotency_db_id: 40de7d459136413bb932e39b37028df3`) for a row where `Channel = [channel_id]`.
2. If found: parse `Processed IDs` (comma-separated timestamps) → `already_processed` set; parse `Processed Row IDs` (comma-separated) → `already_processed_rows` set. Store the row's Notion page ID (needed for updates in Post-Processing — Update Idempotency Log).
3. If not found: `already_processed = {}`, `already_processed_rows = {}`. A new row will be created in Post-Processing.

### Step 4 — Scan each enterprise #acct channel

For each account with a resolved channel ID, run:

```
slack_read_channel(channel_id="[acct_channel_id]", oldest="[unix_timestamp]", limit=100)
```

Paginate if more than 100 messages are returned.

For each message:
- **Skip** if `ts` is in `already_processed`
- **Skip** if it has a reply starting with `✅ Logged in Linear:`
- **Skip** bot messages, system events (join/leave, emoji-only reactions)
- **Empty messages:** Read the thread (`slack_read_thread`) to check for substantive content. If none: post reply requesting content, skip. If thread has content: use thread content as the message body.
- **Forwarded messages:** Apply same handling as log-feedback Scan Mode Step 3.

Tag each retained message:
- `source_channel = "[channel_id]"`
- `account_hint = "[canonical account name from config]"` — use the exact `name` field from `enterprise-accounts.json`, not the user's input argument

Run all channel scans in parallel.

### Step 5 — Scan #elation-feedback for enterprise messages

Also run log-feedback Scan Mode logic on `#elation-feedback (C0AJW26J6NQ)`.

Retain only messages that appear to be from enterprise accounts:
- Account name in the message matches an entry in `enterprise-accounts.json` (case-insensitive)
- Message has an `[ENTERPRISE]` prefix
- ENTFBK classification is likely from the content

Tag retained messages with the appropriate `account_hint` (canonical name from config). Non-enterprise messages are ignored — they remain for `/log-feedback scan` to process normally.

### Step 6 — Announce batch

Announce:
> "Enterprise scan found **N messages** across **M accounts** ([account list]). Calling /log-feedback for each account batch — no confirmation gate."

If N = 0 for all accounts: post to #feedback-ops (`C0AQSLQ55KM`):
```
ℹ️ /enterprise-intake scan — [Date]
Nothing new to process across enterprise channels (last Xd). Pipeline healthy.
```
Then stop.

---

## Log-Feedback Delegation

For each account's message batch, call `/log-feedback` with:
- The batch of messages as input (text + source URL per message)
- `account_hint = "[canonical account name]"` as context

log-feedback runs its full pipeline (Fetch & Parse → Issue Search → Write to Linear → Report → Thread Replies → Post-Run Monitoring → Analysis → Archive & Notify). Enterprise Tracker Write is handled separately by tracker-write mode.

**account_hint validation:** Before passing `account_hint` to log-feedback, verify the value matches an entry in `enterprise-accounts.json` exactly (case-insensitive lookup against the `name` field). If the user's input argument was a fuzzy or partial match, resolve it to the canonical name first and log the resolution: `ℹ️ Resolved "[user input]" → "[canonical name]" from enterprise-accounts.json`.

**Order:** Process accounts sequentially (not all in parallel) to avoid context overload. Each account's batch is one log-feedback invocation.

---

## Tracker Write Mode

**Only execute when `$ARGUMENTS` begins with `tracker-write`.** For scan or setup invocations, skip to their respective sections.

Reads recently filed Linear customer needs for enterprise accounts and writes rows to the Notion Enterprise Feedback Tracker. Run on-demand after a scan, or via a scheduled task once PDL-187 is complete.

### TW Step 1 — Load accounts

Read `~/.claude/config/enterprise-accounts.json`. Resolve the target accounts:
- No argument → all accounts in config with a non-null `linear_customer_id`
- Account name argument → only that account
- Skip accounts where `linear_customer_id` is null and warn: `⚠️ [Account Name]: linear_customer_id not set — skipping. Run /enterprise-intake scan first to auto-populate it.`

### TW Step 2 — Fetch recently filed needs from Linear

For each account, query Linear for customer needs associated with that account's `linear_customer_id`. Retrieve needs filed since `last_tracker_write` timestamp stored in `enterprise-accounts.json` for this account (default to last 48 hours if not set).

For each need returned:
- Record: need ID (`Linear Request ID`), need body, associated issue ID and title, issue URL, date filed

Run all account queries in parallel.

### TW Step 3 — Dedup against Notion tracker

For each need, query the Enterprise Feedback Tracker (`data_source_id: d0e99400-bafe-4fe7-8f6e-8c4260772d45`) for a row where `Linear Request ID = [need_id]`. Run all checks in parallel.

- If found: skip — already in tracker.
- If not found: include in the write batch.

If the write batch is empty for all accounts: post to #feedback-ops and stop:
```
ℹ️ /enterprise-intake tracker-write — [Date]
Nothing new to write. All filed enterprise needs are already in the tracker.
```

### TW Step 4 — Domain inference

For each need in the write batch, match the gap description against the JTBD source:

1. Read the `jtbd_source` field from `enterprise-accounts.json`. Can be a local file path, Google Sheets URL, or Notion DB ID. If absent or unavailable: set Domain to null and note `ℹ️ Domain inference skipped — jtbd_source not configured`. Do not fail the run.
2. Find the row(s) where `Product Capability (JTBD)` has the highest word-overlap with the gap description (ignore stopwords: the, a, is, for, in, of, etc.)
3. Use that row's `Product Domain` value — **normalize**: replace `, ` with ` / ` to match Notion select option names.
4. If confidence is low (< 2 overlapping meaningful words): set Domain to null; flag in summary.

Run all domain inferences in parallel.

### TW Step 5 — Map need body to Notion 3-section template

For each need, map the standard Linear need body sections to the Notion "New Feedback" template:

| Linear need body section | Notion page section |
|--------------------------|---------------------|
| Verbatim quote block (`> [...]`) | `## Customer Feedback` |
| `## Problem Statement` | `## Problem Statement` |
| `## Why It Matters` | `## Notes` (approximate — CSM can expand) |
| `**Source:**` line | Preserved under Customer Feedback |
| `**Date received:**` line | Preserved under Customer Feedback |

If a section is missing from the need body, leave the corresponding Notion section blank with a note: `[not provided — see Linear need: [need_url]]`.

### TW Step 6 — Create Notion rows

> **Content is REQUIRED.** Never create a Notion row without populating the page body.

Create all rows in parallel via `notion-create-pages`:
- **parent:** `data_source_id: d0e99400-bafe-4fe7-8f6e-8c4260772d45`
- **Properties:**
  - `Name`: `"[Account] — [Domain]: [gap summary]"` (truncated to ~80 chars; use "Unknown Domain" if null)
  - `Account`: JSON array with the account's Notion page URL (from `enterprise-accounts.json` → `notion_page_url`)
  - `Domain`: matched Product Domain string, or null
  - `Status`: `"Triage"`
  - `Linear Issue ID`: FBK issue identifier (e.g., `"ENTFBK-42"`)
  - `Linear Issue URL`: `"https://linear.app/elationhealth/issue/ENTFBK-42"` — construct from identifier
  - `date:Date Logged:start`: date the need was filed in Linear (ISO string)
  - `Linear Request ID`: need ID (dedup key)
  - `Priority`: null — CSM-maintained
  - **Do NOT set** `CSM Owner` — read-only rollup
  - **No `Risk Level` field** — does not exist in current DB schema
- **Page body:** structured per TW Step 5 mapping

Capture the returned Notion row URL per row.

### TW Step 7 — Update last_tracker_write timestamp

For each account processed, update `enterprise-accounts.json` → set `last_tracker_write` to now (ISO string). This is the cursor for the next run.

### TW Step 8 — Post summary to #feedback-ops

Post a single message to `#feedback-ops` (`C0AQSLQ55KM`):

```
📋 Enterprise Tracker Write — [Date]
• [Account Name]: [N] new row(s) filed
  - [gap summary] | [Linear Issue ID] | Domain: [domain or "⚠️ unmatched — please set manually"] | [Notion row URL]
  ...
• [Account Name 2]: [N] new row(s) filed
  ...

Action needed: Set Priority (P1–P4) on each row. Confirm Domain on any unmatched rows.
```

If multiple accounts had zero new rows, omit them from the message. If ALL accounts had zero new rows, post the ℹ️ zero-result message from TW Step 3 instead.

---

## Post-Processing — Update Idempotency Log

After all accounts are processed (log-feedback complete for each):

For each account scanned:
1. Collect the `ts` values of all messages that were successfully processed (i.e., `✅ Logged in Linear:` was posted or they had no fileable content).
2. Look up the account's idempotency row in the Processed Messages DB:
   - If row exists: `notion-update-page` — append new timestamps to `Processed IDs` (comma-separated, no duplicates); append any new `<ts>:row_<N>` entries to `Processed Row IDs` (comma-separated, no duplicates).
   - If row doesn't exist: `notion-create-pages` in `idempotency_db_id` with `Channel = [channel_id]`, `Account = [account name]`, `Processed IDs = [comma-separated ts values]`, `Processed Row IDs = []`. Store returned page ID in `enterprise-accounts.json` under the account as `idempotency_page_id`.

---

## Key Rules

1. **Channel IDs must be pre-configured.** Never do a live Slack channel search at runtime — channel IDs are stable and must be set in `enterprise-accounts.json` before running scan. If missing, skip and warn.
2. **account_hint must be canonical.** Always resolve the user's input to the exact `name` field in `enterprise-accounts.json` before passing to log-feedback. This ensures enterprise detection fires reliably in log-feedback's Match Customer step.
3. **Idempotency.** Always check processed timestamps before scanning. Always update after processing.
4. **No duplicate logic.** The full feedback pipeline (fetch → search → write → report) is handled entirely by `/log-feedback` — do not replicate it here.
5. **Never create duplicate pages.** In setup mode, always check config first (Setup Step 1).
6. **Exact account name matters.** The `Account` select property in the Enterprise Feedback Tracker is how rows are filtered. The `name` in config must exactly match what `/log-feedback` writes to the `Account` field.
7. **Write config updates.** Persist any new `idempotency_page_id` values back to `enterprise-accounts.json` after each scan run. Persist new account entries after each setup run.
8. **#feedback-ops always gets a summary.** tracker-write posts the enterprise tracker summary after each run. Scan mode posts the ℹ️ zero-result digest if nothing was found in scan.
