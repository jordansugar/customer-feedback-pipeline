---
name: fetch-external-gaps
description: Daily pull of Intercom conversations and Salesforce cases/opportunities from the past 24 hours. Uses AI to identify product gap signals and posts high-confidence matches to #elation-feedback for the /log-feedback daily scan to pick up. Stage 1 of the pipeline (Intercom/SF → #elation-feedback → Linear). Also triggered by the daily scheduled task at 4:00 AM PT. Trigger phrases include "fetch external gaps", "run intercom sf pull", "pull intercom feedback", "sync salesforce intercom", or when invoked on schedule.
version: 1.1.0
---

# Fetch External Gaps → #elation-feedback

Fetch recent conversations and cases from Intercom and Salesforce, identify product gap signals using AI, and post high-confidence matches to #elation-feedback so the `/log-feedback` daily scan picks them up.

**Credentials:** Read from `~/.claude/config/integrations.json`. If missing or incomplete, post an alert to #feedback-ops and stop.

**Output:** Zero or more formatted messages posted to #elation-feedback (`C0AJW26J6NQ`) + one run summary to #feedback-ops (`C0AQSLQ55KM`).

---

## Phase 0 — Load config and determine window

**Credential loading — in priority order:**

1. Read `~/.claude/config/integrations.json` if it exists and all required fields are non-empty and not `REPLACE_ME`. Use these values.
2. If the file is missing or any field is `REPLACE_ME` / empty, fall back to environment variables:
   - `INTERCOM_ACCESS_TOKEN`
   - `SF_INSTANCE_URL`, `SF_CLIENT_ID`, `SF_CLIENT_SECRET`, `SF_USERNAME`, `SF_PASSWORD`, `SF_SECURITY_TOKEN`
3. If neither source provides all required credentials, post an alert to #feedback-ops and stop:
   ```
   ⚠️ fetch-external-gaps — credentials not configured
   Action needed: set credentials in ~/.claude/config/integrations.json or via environment variables.
   See feedback-pipeline/docs/DEPLOYMENT.md for setup instructions.
   ```

The expected `integrations.json` structure (for reference):

```json
{
  "intercom": {
    "access_token": "<token>"
  },
  "salesforce": {
    "instance_url": "https://<instance>.my.salesforce.com",
    "client_id": "<connected-app-client-id>",
    "client_secret": "<connected-app-client-secret>",
    "username": "<sf-username>",
    "password": "<sf-password>",
    "security_token": "<sf-security-token>"
  }
}
```

**Lookback window:** Default to **last 24 hours**. Set `window_start` = now − 24h as a Unix timestamp. If invoked with an explicit range (e.g., `last 48h`), parse it.

---

## Phase 1 — Authenticate to Salesforce

Use the SF Username-Password OAuth flow to get a short-lived access token. This token is used for all SOQL queries in Phase 2.

```
POST https://<instance_url>/services/oauth2/token
Content-Type: application/x-www-form-urlencoded

grant_type=password
&client_id=<client_id>
&client_secret=<client_secret>
&username=<username>
&password=<password><security_token>
```

Note: the password and security token are concatenated with no separator.

On success: store `access_token` and `instance_url` from the response for use in Phase 2.

On failure: post a #feedback-ops alert and stop:
```
⚠️ fetch-external-gaps — Salesforce auth failed
Issue: <error from SF response>
Action needed: verify credentials in ~/.claude/config/integrations.json
```

---

## Phase 2 — Fetch data in parallel

Run all three fetches simultaneously.

### 2a — Intercom conversations

```
GET https://api.intercom.io/conversations
Headers:
  Authorization: Bearer <access_token>
  Accept: application/json
  Intercom-Version: 2.11
Query params:
  created_after=<window_start_unix>
  per_page=50
  order=desc
```

From the response, collect each conversation's:
- `id` — used to build the Intercom URL
- `source.author.name` — customer name (may be a contact name, not necessarily company)
- `source.body` — opening message text (HTML — strip tags)
- `contacts.contacts[0].id` — contact ID (use to look up company if needed)
- `created_at` — timestamp
- `conversation_parts.total_count` — if > 0 and the source body is short (<100 chars), fetch the full conversation parts to get more context (see note below)

**Constructing the Intercom URL:** `https://app.intercom.com/a/inbox/conversations/<id>`

**Fetching full conversation parts (when needed):**
```
GET https://api.intercom.io/conversations/<id>
Headers: same as above
```
Use `conversation_parts.conversation_parts[]` entries where `part_type = "comment"` and `author.type = "user"` to get customer messages.

**Company lookup (when account name is unclear):** If `source.author.name` appears to be a person's name rather than a company, look up the contact:
```
GET https://api.intercom.io/contacts/<contact_id>
```
Use `companies.companies[0].name` as the account name if present. Fall back to the contact's name.

Paginate if `pages.next` is present and the total would otherwise be cut off.

### 2b — Salesforce Support Cases

Run this SOQL query via the SF REST API:
```
GET <instance_url>/services/data/v60.0/query
Headers:
  Authorization: Bearer <sf_access_token>
  Accept: application/json
Query param:
  q=SELECT Id, CaseNumber, Subject, Description, Account.Name, CreatedDate, Status, Type
    FROM Case
    WHERE CreatedDate >= YESTERDAY
      AND Type != 'Feedback'
      AND Subject != null
    ORDER BY CreatedDate DESC
    LIMIT 200
```

> **Schema note:** If your org uses a different field for Feedback categorization (e.g., `Category__c = 'Feedback'` or `RecordType.Name = 'Feedback'`), adjust the WHERE clause accordingly. The intent is to exclude items already handled by the PDL-137 Salesforce Feedback auto-post workflow.

For each record, collect:
- `Id` → URL: `<instance_url>/lightning/r/Case/<Id>/view`
- `CaseNumber`
- `Subject`
- `Description`
- `Account.Name`
- `CreatedDate`

### 2c — Salesforce Expansion Opportunities

```
GET <instance_url>/services/data/v60.0/query
Headers: same as 2b
Query param:
  q=SELECT Id, Name, Description, Account.Name, CloseDate, StageName, Amount
    FROM Opportunity
    WHERE CreatedDate >= YESTERDAY
      AND (StageName LIKE '%Expansion%' OR Type = 'Existing Business')
      AND Description != null
    ORDER BY CreatedDate DESC
    LIMIT 100
```

> **Schema note:** Adjust the StageName/Type filter to match how your org tracks expansion opportunities. The intent is to catch upsell/expansion deals where a product gap may be blocking growth.

For each record:
- `Id` → URL: `<instance_url>/lightning/r/Opportunity/<Id>/view`
- `Name`
- `Description`
- `Account.Name`
- `StageName`

---

## Phase 3 — AI classification

For each item from Phase 2, evaluate whether it contains a **product gap signal**. This is the core AI filtering step — be selective. The goal is signal, not noise.

**Classify as a product gap signal (HIGH confidence) if any of the following are true:**
- Customer explicitly states Elation cannot do something they need
- Customer requests a specific feature or capability that does not exist today
- Customer describes a manual workaround they use because the system doesn't support a workflow
- Customer mentions evaluating or switching to a competing product for a specific capability
- A CSM or AE notes that a product gap is blocking a deal or causing churn risk

**Classify as NOT a product gap signal (skip) if:**
- It is a how-to / training question ("how do I…?")
- It is a bug report about something that should already work (not a missing capability)
- It is a billing, payment, or account administration question
- It is a general complaint with no specific feature request
- It is internal (Elation employee talking to another Elation employee with no customer signal)
- It is spam, auto-reply, or out-of-office
- The description is too short or vague to classify (fewer than 30 meaningful words)

**Ambiguous cases:** If you cannot clearly determine whether a product gap is present, classify as LOW confidence and skip. Only post HIGH-confidence signals.

For each item, produce:
- `confidence`: HIGH | LOW | SKIP
- `gap_summary`: one sentence describing the specific gap (HIGH only)
- `account_name`: best available account/company name

---

## Phase 4 — Dedup check

Before posting, read the last 24 hours of #elation-feedback to check for items already posted from the same source URLs:

```
slack_read_channel(channel_id="C0AJW26J6NQ", oldest="<window_start_unix>", limit=200)
```

For each HIGH-confidence item, check whether a message already exists in #elation-feedback that contains the item's source URL. If found → mark as `Already posted` and skip. This prevents duplicates when the skill is re-run or the window overlaps.

---

## Phase 5 — Post to #elation-feedback

For each HIGH-confidence item that passed the dedup check, post to #elation-feedback (`C0AJW26J6NQ`) as a **top-level message** (no `thread_ts`):

```
[Intercom] <Account Name> — <Subject or first 80 chars of message>
<Body text — first 800 characters, with HTML stripped>
Source: <full URL>
```

or for Salesforce:

```
[SF Case <CaseNumber>] <Account Name> — <Subject>
<Description — first 800 characters>
Source: <full URL>
```

or for Salesforce Opportunities:

```
[SF Opportunity] <Account Name> — <Opportunity Name>
<Description — first 800 characters>
Source: <full URL>
```

**Truncation:** If body/description exceeds 800 characters, truncate at the last complete sentence before the limit and append `…`.

**Rate limiting:** Post all messages with a 1-second pause between each to avoid Slack rate limit errors.

---

## Phase 6 — Run summary to #feedback-ops

After posting (or if nothing to post), post a summary to #feedback-ops (`C0AQSLQ55KM`):

**Normal run (some items found):**
```
📥 fetch-external-gaps — [Date], [Time]
Fetched: N Intercom | M SF Cases | P SF Opportunities
AI classified: X high-confidence signals posted to #elation-feedback
Skipped: Y low-confidence | Z already posted | W no gap signal
```

**Zero signals:**
```
📥 fetch-external-gaps — [Date], [Time]
Fetched: N Intercom | M SF Cases | P SF Opportunities
No product gap signals found. Pipeline healthy.
```

**Partial failure (one source errored but others succeeded):**
```
📥 fetch-external-gaps — [Date], [Time]
⚠️ Intercom fetch failed: <error> — SF items processed normally.
SF: X signals posted | Y skipped
Action: check Intercom credentials or retry manually.
```

---

## Key rules

1. **High-confidence only.** When in doubt, skip. A false positive floods #elation-feedback and trains people to ignore it. A false negative is caught on the next day's run.
2. **Never post PII.** Strip or omit email addresses, phone numbers, and patient-identifiable information from posted bodies. Account/company names are fine.
3. **Always post the summary.** Even if zero items are posted. Silence = the job stopped running.
4. **Retry on timeout.** If a Slack `send_message` call times out, retry once before marking as failed.
5. **Credentials never in posts.** Never include API tokens or credentials in any Slack message or Notion page.
6. **Graceful partial failure.** If Intercom fails but SF succeeds (or vice versa), continue with the available source and note the failure in the summary. Do not abort the whole run.
