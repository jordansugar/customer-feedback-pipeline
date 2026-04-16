---
name: log-feedback
description: This skill should be used when the user provides any source of product gap or customer feedback and asks to log it in Linear. Accepts any input format — Slack thread URL, Notion page URL, Salesforce case URL, Intercom conversation URL, CSV file or text, pasted raw text, or structured notes. Also supports scan mode: "/log-feedback scan" or "/log-feedback #elation-feedback last Xd" reads the #elation-feedback channel, skips already-processed messages, and batch-logs everything new directly to Linear Triage without a confirmation gate. Trigger phrases include "log this in Linear", "file these gaps", "create customer needs from this", "send this feedback to Linear", "convert this to Linear issues", "file this in FEEDBACK", "scan elation-feedback", or any request to create Linear issues, customer records, or customer needs from feedback data.
version: 1.0.0
---

# Feedback → Linear

Convert any source of product gap or customer feedback into Linear FEEDBACK issues and customer needs. Supports single accounts, multi-account batches, Slack thread URLs, Salesforce case URLs, Intercom conversation URLs, and scan mode.

**Input:** Any of — `/log-feedback scan`, Slack thread URL, Notion page URL, Salesforce case URL, Intercom conversation URL, CSV (file path or pasted), or raw text
**Output:** Linear FEEDBACK issues (in Triage) + customer needs linked to every gap–issue pairing

**Modes:**
- **Interactive mode** (default): Fetch and classify automatically, present results, wait for confirmation before any Linear writes.
- **Scan mode** (`/log-feedback scan` or `/log-feedback #elation-feedback last Xd`): Read #elation-feedback, skip already-processed messages, write directly to Linear Triage with no confirmation gate.

---

## Configuration & Reference

### Enterprise Pre-Check

**Run before anything else, every time** (both modes).

Load `~/.claude/config/enterprise-accounts.json` and extract the `accounts[]` array. Build a set of lowercase account names: `known_enterprise_accounts`. Used in the Match Customer step to detect enterprise accounts reliably even when no `account_hint` is provided.

If the file is missing or unreadable: set `known_enterprise_accounts = {}` and continue. Log a warning if enterprise-flagged processing is expected.

### Sub-Team Reference

Every gap and issue belongs to one of four sub-teams:

| Sub-team | Linear team key | Covers |
|----------|----------------|--------|
| EHRFBK | `EHRFBK` | EHR Feedback — clinical documentation, FHIR, compliance, orders, imaging, flowsheets, prescribing, specialty workflows |
| EBFBK | `EBFBK` | Elation Billing Feedback — billing workflows, claims, ERA/EOB, coding, RCM integrations |
| PTFBK | `PTFBK` | Patient Engagement Feedback — patient portal, scheduling, messaging, intake forms, care gap outreach |
| ENTFBK | `ENTFBK` | Enterprise Feedback — API, HDB, RBAC, SSO, multi-location, workspaces, Scale, Governance |

**Classification rules (use judgment; these are guidelines):**
- Clinical documentation, FHIR, compliance, imaging, orders, specialty workflows → EHRFBK
- Billing, claims, payments, coding, RCM → EBFBK
- Patient portal, **scheduling**, patient communication, patient-facing forms, care outreach → PTFBK
- API, HDB, roles/permissions, enterprise scale, multi-site, workspaces, Governance → ENTFBK
- **LOW confidence in sub-team → fall back to parent `FBK` team.** Do not force a sub-team assignment when the gap is ambiguous.

---

## Scan Mode

**Skip this section entirely for interactive/manual runs.** Only execute when `$ARGUMENTS` contains `scan`, `#elation-feedback`, or a date range pattern like `last 7d`.

### Step 1 — Determine lookback window
- Parse time range from arguments: `last 7d` → 7 days ago, `last 3d` → 3 days, etc.
- Default to **7 days** if no range is specified.
- Convert to Unix timestamp for `oldest` parameter.

### Step 2 — Read #elation-feedback
```
slack_read_channel(channel_id="C0AJW26J6NQ", oldest="<unix_timestamp>", limit=100)
```
If more than 100 messages are returned, paginate until all messages in the window are fetched.

### Step 3 — Load idempotency state

Load the idempotency state for #elation-feedback before filtering:
1. Query the idempotency DB (`40de7d459136413bb932e39b37028df3`) for a row where `Channel = C0AJW26J6NQ`.
2. If found: parse `Processed IDs` (comma-separated) → `already_processed` set; parse `Processed Row IDs` (comma-separated) → `already_processed_rows` set. Store the row's Notion page ID (needed for updates in Post-Run Monitoring).
3. If not found: `already_processed = {}`, `already_processed_rows = {}`. A new row will be created in Post-Run Monitoring.

For each message, check if it should be skipped:
- **Skip** if it has a reply starting with `✅ Logged in Linear:` — the processed marker written by Thread Replies.
- **Skip** if its `ts` appears in `already_processed`.
  - **Spreadsheet messages:** A spreadsheet message with some rows in `already_processed_rows` (format `<ts>:row_<N>`, e.g., `1775233538.779769:row_12`) is **not** fully skipped — pass it to Step 4, which will skip the already-processed rows and continue from where the last run left off.
- **Skip** bot messages and messages that are themselves `✅` replies.
- **Skip** pure system events (join/leave, emoji-only reactions, canvas update notifications).
- **Forwarded messages (hidden attachments):** When a real user's message text contains forwarding language — phrases like "throwing into #elation-feedback", "forwarding this", "sharing this to #channel", "cc @user" alongside a channel mention, or "logging this here" — treat it as an intentional feedback submission with a forwarded Slack message attached. The Slack MCP tool does **not** render forwarded/shared message attachments; only the sender's comment text is visible. Do **not** skip these as meta-comments. Instead:
  - Read the message's thread (`slack_read_thread`) to check if the feedback content was pasted as a reply.
  - If the thread contains substantive feedback content: use it as the input for Fetch & Parse.
  - If the thread has no substantive content: post a reply asking the sender to paste the original forwarded content as a thread reply, then skip for this run. Do **not** mark with `✅ Logged in Linear:`.
  - Reply format:
    ```
    👋 This message looks like a forwarded feedback submission, but the attached content isn't visible to the scan tool (Slack attachments aren't accessible via the API).
    Please paste the original feedback content as a reply in this thread and the next scan will pick it up automatically.
    *Sent using @Claude*
    ```
- **Empty messages:** If a message from a real user has no substantive text, no attachments, and no forwarding language, do **not** skip it immediately. Read its thread (`slack_read_thread`) to check whether the feedback content has been pasted there as a reply.
  - If the thread contains substantive feedback content: use that thread content as the input for Fetch & Parse (treat it the same as if the content were in the parent message body).
  - If the thread has no substantive content (or no replies at all): post a reply in the thread asking the sender to paste the original feedback content, then skip it for this run. Do **not** mark it with `✅ Logged in Linear:` — the next scan should re-evaluate it once content is present.
  - Reply format when requesting content:
    ```
    👋 This message appears to be empty — no feedback content was found here or in this thread.
    If you have feedback to log, please paste the original content as a reply in this thread and the next scan will pick it up automatically.
    *Sent using @Claude*
    ```

### Step 4 — Detect and expand spreadsheet inputs

For each remaining message, check if it contains any of:
- A Google Sheets URL (contains `docs.google.com/spreadsheets`)
- A `.csv` or `.xlsx` file attachment
- A Google Drive link to a CSV file (`drive.google.com` with a file ID)

If none of the above are detected, pass the message to Fetch & Parse as-is. If detected, run the full expansion pipeline below before passing.

#### 4a — Fetch the spreadsheet content

**Google Sheets URL:** Convert the standard Sheets URL to a CSV export URL and fetch:
```
Standard:  https://docs.google.com/spreadsheets/d/<ID>/edit#gid=<GID>
CSV export: https://docs.google.com/spreadsheets/d/<ID>/export?format=csv&gid=<GID>
```
If `gid` is absent, use `gid=0` (first sheet). Fetch with `WebFetch`.

- **If the fetch succeeds and returns CSV data:** proceed to 4b.
- **If the fetch returns an HTML auth wall** (response contains `<title>Sign in` or `accounts.google.com` redirect): the sheet is private. Post a thread reply and skip for this run:
  ```
  🔒 This Google Sheet is private — the scan can't access it.
  To process this spreadsheet, please set sharing to "Anyone with the link can view" and the next scan will pick it up automatically.
  Alternatively, export to CSV and paste the content directly in this thread.
  *Sent using @Claude*
  ```
  Do **not** mark with `✅ Logged in Linear:` — re-evaluate after the CSM updates sharing.

**`.csv` file attachment or pasted CSV text:** Read directly.

**`.xlsx` file attachment:** Use available tools to read the file content and convert to row data.

**Google Drive CSV link:** Attempt `WebFetch`. Apply the same auth wall handling if the response is an HTML login page.

#### 4b — Schema normalization

Extract the header row and map each column to a canonical field name using fuzzy matching:

| Canonical field | Common header variants — and close synonyms |
|----------------|---------------------------------------------|
| `account_name` | account, account name, practice, customer — and close synonyms |
| `website_url` | website, url, domain, web — and close synonyms |
| `contact_name` | contact, contact name, poc, csm contact — and close synonyms |
| `gap_description` | feedback, gap, gap description, pain point, feature request — and close synonyms |
| `product_area` | product area, area, module, category — and close synonyms |
| `risk_level` | risk, priority, risk level, severity — and close synonyms |
| `churn_risk` | churn, churn risk, at risk — and close synonyms |
| `source` | source, context, meeting, touchpoint — and close synonyms |
| `notes` | notes, comments, additional context — and close synonyms |

**Matching rules:**
- Exact match (case-insensitive) → HIGH confidence, use silently
- Contains match (e.g., header "Account Name (required)" contains "account name") → HIGH confidence
- Substring or edit-distance match → MEDIUM confidence, flag in announcement
- No match → log as unmapped; pass raw column header + value through as `notes`

**If any MEDIUM-confidence mappings exist**, announce before processing:
```
⚠️ Spreadsheet column mapping — please verify:
  "Customer" → account_name (medium confidence)
  "Pain Point" → gap_description (medium confidence)
Unmapped columns (passed through as notes): "QBR Date", "CSM Owner"
Processing N rows with these mappings…
```

**Required fields:** `account_name` and `gap_description` are required. If either cannot be mapped with at least MEDIUM confidence, post a thread reply and skip:
```
⚠️ Could not identify required columns in this spreadsheet.
Needed: "Account Name" and "Gap Description" (or equivalents).
Found headers: [list headers here].
Please rename the columns to match the standard template and re-drop the link.
Standard template: [link from PDL-142 CSM guide]
*Sent using @Claude*
```

#### 4c — Row-level idempotency

Before processing rows, check `already_processed_rows` for entries in the format `<message_ts>:row_<N>`. Collect the set of already-processed row indices for this spreadsheet message. Skip those rows — process only the unprocessed ones.

#### 4d — Batch size cap (50 rows per run)

Count the number of **unprocessed** rows (after applying 4c). If more than 50:
1. Take only the first 50 rows for this run.
2. After completing Thread Replies for these rows, post a thread reply to the original #elation-feedback message:
   ```
   📋 Spreadsheet has N rows total — processed rows [X]–[Y] this run.
   Rows [Y+1]–[N] will be picked up on the next scan automatically.
   *Sent using @Claude*
   ```
3. Do **not** mark the message with `✅ Logged in Linear:` yet — it must remain unresolved so the next scan picks up the continuation.
4. After all rows in a spreadsheet are processed (final batch), post the `✅ Logged in Linear:` thread reply covering all rows.

#### 4e — Expand into discrete inputs

Each unprocessed row becomes one discrete input item for Fetch & Parse, with:
- **Text:** The mapped field values formatted as structured text (account name, gap, risk level, etc.)
- **Source URL:** The original Google Sheets / Drive URL (or "Spreadsheet attachment from #elation-feedback" if a file)
- **Row index:** Tracked for idempotency updates in Post-Run Monitoring

Announce the batch:
> "Scan found **N unprocessed messages** in #elation-feedback (last Xd) — including N spreadsheet rows expanded from M sheets. Processing as batch — no confirmation gate."

**Gap dedup within the sheet:** Before passing rows to Fetch & Parse, scan all rows for near-identical gap descriptions within the same account. Merge duplicates into a single input item, noting the row count.

If N = 0: post the zero-result summary (see Post-Run Monitoring) and stop.

---

## Fetch & Parse

`$ARGUMENTS` may contain **one or more inputs** — space, comma, or newline separated. These can be mixed types (e.g., two Slack URLs plus a Notion URL). Detect every item and process all in parallel.

### Multiple inputs
If more than one URL or input is detected, fetch all of them **in parallel** and merge their parsed content before continuing. Treat the combined result as one unified input for gap extraction.

### Slack Thread URL
For each `slack.com` URL, fetch the thread:
```
slack_read_thread(thread_url="...")
```
Parse the returned messages as raw text. Extract all account names and feedback mentioned across the thread — a single thread often contains feedback from multiple customers.

**Empty / forwarded message handling:** If the fetched message has empty or near-empty text (fewer than 20 meaningful characters), it may be a forwarded/shared message. Before discarding:
1. Inspect the message's `attachments` array and any `message_ref` or `files` metadata for an `original_url`, `permalink`, or `url_private` field — Slack's shared-message payload often includes a pointer to the original.
2. If an original URL is found: fetch it via `slack_read_thread(thread_url="<original_url>")` and use that content instead.
3. If no original URL is found: record it as `⚠️ Unreadable forward` and surface it in the confirmation table (interactive mode) or the daily summary (scan mode) with the message timestamp and a note to paste content manually.

### Salesforce Case URL
For each URL matching `lightning.force.com` or `salesforce.com/lightning/r/Case/`:
- Fetch the case content using `WebFetch` or the browser tool to retrieve the case subject, description, account name, and case number.
- If the case is not accessible (auth wall), note it as `⚠️ SF case inaccessible — paste case body manually` and surface in confirmation/summary.
- Use the full Salesforce case URL as the `**Source:**` in the customer need body.

### Intercom Conversation URL
For each URL matching `app.intercom.com/a/inbox` or similar Intercom patterns:
- Fetch the conversation content using `WebFetch`.
- Extract customer name, company, and the conversation thread.
- Use the full Intercom URL as the `**Source:**` in the customer need body.

### Notion URL
For each Notion URL or page ID, fetch it using the `notion-fetch` MCP tool. Parse the returned content as raw text.

### CSV (file path or pasted text)
If the input is a file path, read the file. If it's pasted CSV text, parse it directly.

Expected columns (flexible — adapt to whatever headers are present):
- Account/practice name
- Website URL
- Provider count, location count, specialties
- Per gap: risk area, risk level (HIGH / MEDIUM / LOW), gap description, churn precedent

### Raw text / pasted notes
Parse the text directly, using judgment to extract the structured fields below.

### Scan mode batch
If arriving from Scan Mode: each item in the batch is already fetched text + source URL. Apply the same extraction logic below. Do **not** re-fetch already-fetched content.

### Enterprise mode (from /enterprise-intake)
If `account_hint` is provided as context, use it to pre-populate the account name for all messages in the batch. Treat `account_hint` as HIGH confidence — only override it if the message body explicitly names a different account.

### Embedded links
After fetching and parsing all primary inputs, scan the full combined text for embedded **document-type URLs only**: Notion pages, Google Docs, and Confluence pages. Fetch each in parallel and incorporate the retrieved content as additional context.

Do **not** re-fetch Slack thread URLs, Salesforce URLs, or Intercom URLs found in the parsed text — those are handled by their dedicated sections above and any re-fetch here would be redundant.

---

**From any format, extract one or more account blocks:**

**Account profile (per account):**
- Account/practice name
- Website URL (to derive the domain)
- Provider count and location count
- Specialties

**Per gap (per account):**
- Risk area (e.g., "Cardiology", "Scheduling")
- Risk level: HIGH, MEDIUM, or LOW — infer from context if not explicit
- Gap description (what Elation can't do)
- Churn precedent (yes/no and context if available)
- **Sub-team:** Classify each gap into EHRFBK, EBFBK, PTFBK, or ENTFBK using the Sub-Team Reference above

A single input may contain **multiple accounts** (batch mode) or a single account with 3–10 gaps.

### Batch Detection
After parsing, list every distinct account found. If more than one account is detected, announce:
> "Found **N accounts**: [Account A], [Account B], ... — processing all as a batch."

---

## Issue Search & Classification

### Search for matching FEEDBACK issues

For each gap, derive 2–3 tight keyword terms (e.g., for a cardiology imaging gap: `"pacs imaging"`, `"cardiology device"`). Search within the gap's classified sub-team — run **all gap searches in parallel**:

```
list_issues(team="[EHRFBK|EBFBK|PTFBK|ENTFBK|FBK]", query="[terms]", limit=25, includeArchived=false)
```

One search call per gap, scoped to its classified sub-team. For gaps where sub-team confidence is LOW, search the parent `FBK` team instead. Collect and deduplicate results.

If a candidate looks relevant from title/summary alone, proceed to classification — only call `get_issue` for full details when the title is ambiguous and you need the description to decide.

Do **not** fetch all issues. Do **not** search across all teams at once. Do **not** paginate.

### Classify each gap

For each gap, decide:

- **Maps to existing issue:** The existing issue's scope explicitly covers this gap. Don't over-match — a general "specialty workflows" issue only counts if the specific specialty is mentioned.
- **Needs new issue:** No existing issue adequately covers this gap.

A gap can map to **multiple** existing issues. Each pairing produces one customer need in Write to Linear.

Match confidence levels:
- **HIGH** — gap aligns with both the issue title and body; explicit scope overlap
- **MED** — keyword overlap with title or body, but not both; reasonable but not certain
- **LOW** — tangential or inferred match; PM should review before accepting

Build two lists:
1. Gaps requiring new issues + their proposed titles
2. Gaps with existing issue matches + FBK IDs + confidence level

---

## Confirmation Checkpoint

**Scan mode: skip this section entirely.** Proceed directly to Write to Linear.

**Interactive mode:** Present a combined table for all accounts. Group rows by account. Show the Confidence column only for MED or LOW matches:

| Account | Gap | Risk | Sub-team | Issue | Action |
|---------|-----|------|----------|-------|--------|
| Acme Health | Scheduling gap | HIGH | PTFBK | [FBK-42](url): Multi-provider scheduling | Existing |

Show below the table:
- Total new issues to create
- Total customer needs to file (one per gap–issue pair)
- Any LOW-confidence matches requiring explicit PM acceptance
- Any `⚠️ Unreadable forward` items requiring manual input

Then stop and say:
> **"Reply `y` to approve all and file in Linear, or let me know which rows to change."**

- `y` / `yes` / `approve all` → proceed immediately
- Any other response → treat as edits, update the plan, re-confirm

Do not call any Linear write tools until the user confirms.

---

## Write to Linear

Run in this order: create issues first (needs require issue IDs), then look up customers, then dedup, then create needs.

### Create new issues

Create all new issues in parallel:

- **team:** The gap's classified sub-team (`EHRFBK`, `EBFBK`, `PTFBK`, or `ENTFBK`). If sub-team confidence is LOW, use the parent `FBK` team.
- **state:** Triage
- **labels:** Infer from gap type:
  - **EHRFBK:** Imaging/PACS/devices → `["Standard EHR", "Orders & Reports - Ancillary/Imaging"]` | Documentation/notes/flowsheets → `["Standard EHR", "Encounter Documentation (Notes & Visit Notes)"]` | FHIR/compliance → `["Standard EHR", "Compliance & Interoperability"]` | Behavioral health/specialty → `["Standard EHR", "Encounter Documentation (Notes & Visit Notes)"]`
  - **EBFBK:** Billing/claims/coding/RCM → `["Elation Billing"]`
  - **PTFBK:** Scheduling → `["Patient Engagement", "Scheduling"]` | Portal/messaging/intake → `["Patient Engagement"]`
  - **ENTFBK:** RBAC/Governance → `["Standard EHR", "Governance (Roles & Access)"]` | Multi-location/scale/workspaces → `["Standard EHR", "Scale (ex. Workspaces, Enterprise patient search)"]` | API/HDB/integrations → `["Integrations"]`
  - **FBK fallback:** Omit sub-team labels; apply only the most generic label that fits
- **description:** Roadmap-scoped only — zero customer names, account details, ARR, or account-specific context (that lives in the customer need). Two sections:
  - `**Gap today:**` — what Elation currently can't do, in general product terms
  - `**What's needed:**` — the capability required, with bullet points if multi-part
- **title:** Customer-agnostic. Describe the capability gap, not the customer's situation.
- **links:** If a source URL was provided, attach it with title = "[Account Name] Feedback"

Collect all new issue IDs from the responses — needed for creating needs.

### Match customer

Run **all customer lookups in parallel** — one `list_customers` call per distinct account:

```
list_customers(query="[account name]")
```

- **If found:** Use the existing customer ID. Do not create a duplicate.
- **If not found:** Use the **Unknown Customer (Product Feedback)** record — ID `unknown-customer-product-feedback-9d8cde7c840a`. Do **not** create a new customer record under any circumstances. The customer database syncs to Salesforce and must only be written to through that system.

Save each account → customer ID mapping. Track the count of Unknown Customer fallbacks for the Post-Run Monitoring summary.

**Enterprise detection:** Use the `known_enterprise_accounts` set loaded in Configuration & Reference. If the matched account name (lowercase) appears in that set — or if `account_hint` matches an entry:
- Log explicitly: `ℹ️ Enterprise mode: [Account Name] matched enterprise-accounts.json.`
- If the account's `linear_customer_id` is null and a real customer ID was matched (not Unknown Customer): update `enterprise-accounts.json` with the matched customer ID immediately.
- If `account_hint` was provided and no customer match was found, still treat the account as enterprise based on `account_hint` alone.

Note: Notion Enterprise Tracker Write is handled by `/enterprise-intake tracker-write` as a separate job — not by this skill.

### Duplicate need detection

Before filing any needs, check for existing needs to avoid double-filing. Run **all checks in parallel** — one `get_issue(id=FBK-XXX)` per **unique issue ID** (one call covers all customers on that issue):

Inspect the returned customer needs. For each (customer ID, issue ID) pairing, if a need already exists for that customer on that issue, **skip** it and mark it as `Already filed` in the Report.

If `get_issue` does not return customer need data, skip this check and proceed.

### Create customer needs

**4,000-character limit:** Before creating any need, estimate the body character count.

- **If the body fits within 4,000 chars:** create as normal.
- **If the body exceeds 4,000 chars:** trim the verbatim quote (the `> [...]` block) to fit — preserve the Problem Statement and Why It Matters sections in full. Append this note immediately after the trimmed quote:
  ```
  ⚠️ Quote trimmed to fit 4,000-char limit. Full source: [source URL]
  ```
  Then create the need with the trimmed body.
- **Only skip entirely** if the non-quote sections alone (Problem Statement + Why It Matters + metadata) exceed 4,000 chars. Mark it `Skipped — body too long (non-quote content exceeds limit)` in the Report. This should be extremely rare.

Never silently drop a need due to length — trimmed is better than missing.

Create all needs that passed the length check in parallel.

**Body structure** — the need is the primary record and must stand alone if reassigned to a different issue. Customer-specific context belongs here, not in the issue description.

Use this template for all customer needs:

```
**[Customer Account Name]**
> [Verbatim quote or full raw text from the source. For Slack threads, include relevant messages verbatim. For CSV/structured text, include the original row(s) or paragraph. Do not paraphrase when you can quote directly.]

**Source:** [Full URL to Slack thread / SF case / Intercom / #acct channel — linked]
**Date received:** [today's date]

---

## Problem Statement
[1–3 sentences on the underlying product gap and its operational impact]

## Why It Matters
[1–2 sentences on operational impact, compliance requirements, scale implications, patient population context, or churn risk if present]
```

- **customer:** ID from customer matching step
- **issue:** FBK issue ID — one `save_customer_need` call per issue when a gap maps to multiple
- **priority:** `1` for HIGH or MEDIUM risk gaps; `0` for LOW risk gaps

If any `save_customer_need` calls time out, retry them immediately — transient MCP timeouts are common.

---

## Report

Return the results as a **markdown table only** — never as a list. Every row must appear in the table; do not summarize rows outside it.

| Account | Gap | Risk | Sub-team | Issue ID | Title | Action | Customer |
|---------|-----|------|----------|----------|-------|--------|---------|
| Acme | Scheduling | HIGH | PTFBK | [FBK-42](url) | Multi-provider scheduling | Need filed | Matched |

- Issue ID cells must be hyperlinked to the Linear issue URL.
- Do **not** collapse rows, summarize gaps, or emit any list items in place of table rows.

Include a one-line summary below the table: `Filed X needs across Y issues (Z new issues created). W duplicates skipped. N accounts used Unknown Customer. S items skipped (body too long). U unreadable forwards require manual input. E empty messages awaiting content.`

---

## Thread Replies

After filing is complete, reply with a `✅ Logged in Linear:` summary in the **#elation-feedback thread** for every feedback message that was processed. Fire all replies **in parallel** — one `slack_send_message` call per message, all at once.

**Always reply in #elation-feedback (C0AJW26J6NQ)** — never in the original source thread. The ✅ trigger phrase is monitored by Slack workflow automations in #elation-feedback specifically.

### Identifying the correct #elation-feedback message

**Scan mode input** (messages read from C0AJW26J6NQ in Scan Mode):
Use each message's `ts` as `thread_ts` when calling `slack_send_message`.

**Specific Slack URL input** (e.g., `https://elation.slack.com/archives/.../p...`):
- If the URL is already in C0AJW26J6NQ, extract `message_ts` from the `p` parameter (insert `.` before the last 6 digits: `p1775233538779769` → `1775233538.779769`) and reply there.
- If the URL points to a different channel (a source thread), read C0AJW26J6NQ to find the forwarded notification message that links to that source URL, then reply to that #elation-feedback message.

### Reply format

For each #elation-feedback message, send using `slack_send_message(channel_id="C0AJW26J6NQ", thread_ts="...", message="...")`:

```
✅ Logged in Linear:
• [FBK-42](issue_url) — Multi-provider scheduling | [request](need_url_if_available, else issue_url)
• [FBK-101](issue_url) — PACS device integration | [request](need_url_if_available, else issue_url)
```

- **issue_url**: the Linear issue URL (e.g., `https://linear.app/elationhealth/issue/ENTFBK-48/...`)
- **need_url**: the URL returned by `save_customer_need` — use it if non-null; otherwise fall back to the issue URL

The reply **must always begin with the exact text `✅ Logged in Linear:`** — never vary or omit it. Only list issues/needs sourced from that specific feedback message. If any needs were skipped, append: `⚠️ 1 need skipped — [reason]. File manually.`

Do not post a reply if no needs were filed from that message.

---

## Post-Run Monitoring

**Skip this section for interactive/manual runs.**

Run Steps 1–3 in parallel after Thread Replies completes. Step 4 (anomaly alerts) runs only when triggered.

### Step 1 — Update idempotency log

Write processed message identifiers to the shared idempotency DB (`40de7d459136413bb932e39b37028df3`), also used by `/enterprise-intake`:
- **Row exists** (page ID from Scan Mode Step 3): call `notion-update-page` — append new `ts` values to `Processed IDs` (comma-separated, no duplicates); append new `<ts>:row_<N>` values to `Processed Row IDs` (comma-separated, no duplicates).
- **Row doesn't exist**: call `notion-create-pages` in DB `40de7d459136413bb932e39b37028df3` with:
  - `Channel = C0AJW26J6NQ`
  - `Account = log-feedback`
  - `Processed IDs = <comma-separated ts values>`
  - `Processed Row IDs = <comma-separated row entries>`
  - Store the returned page ID in the page body (first line) so future runs can retrieve it by querying `Channel = C0AJW26J6NQ`.
- **Standard messages:** Add `ts` to `Processed IDs`.
- **Spreadsheet rows:** Add one `<ts>:row_<N>` entry per successfully processed row to `Processed Row IDs` (e.g., `1775233538.779769:row_3`).

### Step 2 — Stats payload (for Archive & Notify)

Assemble the run stats string — embedded in the Archive & Notify consolidated post:

```
Processed: N messages | Issues created: X | Needs filed: Y | Needs added to existing: Z
Skipped — unreadable forwards: A | Skipped — body too long: B | Duplicates: C | Empty messages awaiting content: E
Unknown Customer fallbacks: D
Next scheduled run: [tomorrow at same time, or "not scheduled"]
```

If N = 0 (zero-result run), skip Archive & Notify Step 2 entirely — the `ℹ️` digest to #feedback-ops (Step 3 below) is sufficient.

### Step 3 — Daily digest to #feedback-ops (every run)

After every scan run — regardless of whether anomalies occurred — post a digest to **#feedback-ops** (`C0AQSLQ55KM`):

```
📊 /log-feedback scan — [Date], [Time]
Processed: N messages | Issues: X new | Needs: Y filed, Z added to existing
Skipped: A unreadable forwards | B body-too-long | C duplicates | E empty messages (replied, awaiting content)
Unknown Customer fallbacks: D (E% of needs)
Sources: S Slack | SF Salesforce | I Intercom | SP Spreadsheet rows
[Notion run log URL]

```
Note: the trailing blank line is intentional — prevents the Slack MCP attribution from appending to the URL.

If N = 0 (nothing to process):
```
ℹ️ /log-feedback scan — [Date], [Time]
Nothing new to process in #elation-feedback (last Xd). Pipeline healthy.
```

**Source breakdown:** Track each message's origin tag from Scan Mode (`[Slack]`, `[SF Case]`, `[Intercom]`, `[Spreadsheet]`) and count by category. If source tags are not present, label all as `Slack`.

### Step 4 — Anomaly alerts to #feedback-ops (only when triggered)

If any of the following are true, **additionally** post a separate alert to `#feedback-ops` (`C0AQSLQ55KM`). DM `UBJAEBL58` as fallback only if the channel post fails.

| Condition | Alert trigger |
|-----------|--------------|
| Run stopped early due to an unhandled error | Always |
| `slack_read_channel` returned messages but 0 were processed | If no `✅` replies exist on those messages (indicates a filter bug, not normal idempotency) |
| Unknown Customer fallback rate > 15% | e.g., 3+ fallbacks in a 20-need run |
| Any Linear write (issue or need) returned an error not resolved by retry | Always |

Alert format:
```
⚠️ /log-feedback scan alert — [Date]
Issue: [description of the anomaly]
Action needed: [specific thing to check or fix]
Affected messages/issues: [list ts values or issue IDs if applicable]
```

Multiple anomalies in a single run → one combined alert post.

---

## Analysis

After the Report table, always print a brief analysis of the feedback just logged. This runs automatically — no user prompt needed.

**Scan mode:** Keep the analysis to **3 bullets max**, focused on cross-account patterns and roadmap implications only. Skip per-account breakdowns — those details live in the customer needs.

**Interactive mode:** Cover the following, using only what's present in the input (skip sections with nothing to say):

**Account signal**
- Account tier, ARR, and type (integration partner, independent practice, enterprise, etc.)
- Any churn risk or escalation urgency mentioned

**Gap themes**
- What product area(s) do the gaps cluster around?
- Are the gaps tactical/incremental improvements or fundamental capability gaps?

**Cross-account patterns** *(batch mode only)*
- Do multiple accounts share the same gap category? Call this out explicitly.
- Note if the same issue recurs across different account types or sizes.

**Implications for the roadmap**
- Are these gaps likely already on the roadmap (matched to existing issues), or uncovered territory (all new issues)?
- Is there a pattern that suggests a missing label, team, or roadmap theme?

**Format:** 3–6 bullet points (3 max in scan mode). Be specific — reference account names, gap titles, and issue IDs. No generic statements.

---

## Archive & Notify

After printing the Analysis, automatically run both steps below — no confirmation needed.

**Step 1 — Create Notion run log page** using `notion-create-pages`:
- **database_id:** `335a68c4-8bc6-8063-bbf1-d530fd178128`
- **Name property:**
  - *Interactive mode:* `[Account Name] — [YYYY-MM-DD]`
  - *Scan mode:* `Scan Run — [YYYY-MM-DD]`
- **Content:**
  1. `**Source:**` line(s) linking to all original input URLs
  2. **Linear Issues Filed** — bullet list of every issue ID and title filed (e.g., `- [FBK-42](url) — Multi-provider scheduling`)
  3. The Analysis bullet points verbatim
  4. **Appendix: Filed Gaps** — the full Report table, exactly as printed, including every row and the one-line summary. Also include verbatim quotes used in the customer need bodies — one block per gap, labelled with the account and gap name.

**Step 2 — Post summary**

*Interactive mode* — post to **#feedback-ops** (`C0AQSLQ55KM`) (top-level message, no `thread_ts`):
```
📋 *Feedback logged* — [Account list] | [N needs filed across N issues (X new)]
[One-line summary of the top gap themes, ≤ 15 words]
[Notion page URL]

```
Note: the trailing blank line is intentional — it prevents the Slack MCP's `*Sent using @Claude*` attribution from being appended to the Notion URL on the same line.

*Scan mode* — **skip this step entirely.** The `📊` digest in #feedback-ops (Post-Run Monitoring Step 3) covers all stats. Only the per-message `✅ Logged in Linear:` thread replies (Thread Replies) are posted to #elation-feedback in scan mode.

- **Notion URL:** use the `url` field returned by `notion-create-pages` in Step 1. Include it in the #feedback-ops digest (Post-Run Monitoring Step 3).
- Step 1 (Notion page creation) still runs in scan mode.

---

## Key Rules

1. **Issue before need.** Create all new issues before any customer needs — needs require issue IDs.
2. **Never create customers.** If no match, use Unknown Customer (Product Feedback) (`unknown-customer-product-feedback-9d8cde7c840a`). The customer database syncs to Salesforce — do not write to it directly.
3. **Parallelize everything.** Gap searches, customer lookups, duplicate checks, issue creates, and need creates all run in parallel.
4. **Enterprise detection.** The `known_enterprise_accounts` set is loaded in Configuration & Reference before any processing begins. When an enterprise account is matched, update `enterprise-accounts.json` with the resolved `linear_customer_id` if not already set. Notion tracker writes are handled separately by `/enterprise-intake tracker-write`.
