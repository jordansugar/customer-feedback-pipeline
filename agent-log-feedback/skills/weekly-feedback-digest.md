---
name: weekly-feedback-digest
description: Posts a weekly feedback digest to #feedback-ops every Monday summarizing the past 7 days of /log-feedback activity — items processed by source (scan + interactive), issues created per sub-team, Unknown Customer fallback rate, and current FBK pipeline state (Triage + Now/Next) per sub-team. Trigger phrases include "post weekly digest", "weekly feedback summary", "run weekly digest", or when invoked on schedule.
version: 1.1.0
---

# Weekly Feedback Digest

Compile and post the weekly feedback intake summary to #feedback-ops. This runs every Monday automatically — it can also be triggered manually at any time.

**Output:** One top-level message posted to #feedback-ops

---

## Step 1 — Determine the reporting window

- Default window: the **past 7 days** (last Monday 00:00 PT → today 00:00 PT).
- Convert start and end to Unix timestamps for `oldest` / `latest` parameters.
- Label the period as `[Mon Apr X] – [Sun Apr Y]` in the digest header.

---

## Step 2 — Read scan run summaries from #feedback-ops

Read the last 7 days of messages from #feedback-ops:

```
slack_read_channel(channel_id="C0AQSLQ55KM", oldest="<7d_unix_ts>", limit=200)
```

Filter for messages that begin with `📊 /log-feedback scan` — these are the daily run summary posts from Phase 7.6 Step 3. For each matching message, extract:

- **Date / time** of the run
- **Processed count** (N messages)
- **Issues created** (X new)
- **Needs filed** (Y filed, Z added to existing)
- **Skipped counts** (forwards, body-too-long, duplicates)
- **Unknown Customer fallbacks** (D, E%)
- **Source breakdown** (Slack / Salesforce / Intercom / Spreadsheet) — parse from the `Sources:` line if present

---

## Step 2b — Read interactive-mode runs from Notion run log DB

Query the Notion run log database for pages created in the reporting window:

```
notion-query(database_id="335a68c4-8bc6-8063-bbf1-d530fd178128", filter={created_time: {past_7_days: true}})
```

- **Scan pages** are titled `Scan Run — YYYY-MM-DD` — these correspond to the ✅ messages already parsed in Step 2. Use them to cross-check totals if needed; **do not double-count**.
- **Interactive pages** are all other titles (e.g. `Acme Health — 2026-04-07`). For each, read the page body to extract:
  - Accounts processed (from the page title or `Source:` line)
  - Needs filed and issues created (from the "Linear Issues Filed" section — count bullet points)
  - Source type (infer from the `Source:` URL: Slack thread → Slack, salesforce.com → Salesforce, intercom.com → Intercom, notion.so → Notion, etc.)

Sum interactive runs separately; merge into Step 3 totals.

---

## Step 3 — Aggregate weekly stats

Merge stats from both scan and interactive runs:

| Metric | Source |
|--------|--------|
| Total scan runs | count of `✅` messages from #elation-feedback |
| Total interactive runs | count of non-"Scan Run" pages in Notion run log DB |
| Total messages processed | scan runs only |
| Total issues created (new) | both |
| Total needs filed | both |
| Total needs added to existing issues | both |
| Unknown Customer fallbacks | scan runs only |
| By source (Slack / Salesforce / Intercom / Spreadsheet) | scan runs only |
| Interactive | count of needs from interactive runs |

If only interactive runs happened (no scan runs): omit "Messages processed", "Unknown Customer fallbacks", and "By source" — note "No automated scans this week" inline rather than showing zeroes.

---

## Step 4 — Query FBK pipeline state per sub-team

Run all eight queries **in parallel**:

```
list_issues(team="EHRFBK",  state="Triage",   limit=100)
list_issues(team="EBFBK",   state="Triage",   limit=100)
list_issues(team="PTFBK",   state="Triage",   limit=100)
list_issues(team="ENTFBK",  state="Triage",   limit=100)
list_issues(team="EHRFBK",  state="Now/Next", limit=100)
list_issues(team="EBFBK",   state="Now/Next", limit=100)
list_issues(team="PTFBK",   state="Now/Next", limit=100)
list_issues(team="ENTFBK",  state="Now/Next", limit=100)
```

Record Triage and Now/Next counts per sub-team. If a count equals 100 (the limit), note "100+" to avoid implying an exact count.

**Triage health flag:** If any sub-team's Triage count exceeds 20, mark it `⚠️ High` in the digest. This signals that the queue needs attention before the weekly triage session.

---

## Step 5 — Compose and post the digest

### Post to #feedback-ops (`C0AQSLQ55KM`) — top-level message, no `thread_ts`:

```
📊 *Weekly Feedback Digest* — [Mon Apr X] – [Sun Apr Y]

*Activity this week*
• Automated scans: N  |  Interactive runs: N  |  Issues created: X new
• Needs filed: Y new + Z added to existing issues
• Unknown Customer fallbacks: D (E%)
<https://www.notion.so/335a68c48bc68063bbf1d530fd178128|View Notion run logs →>

*By source*
• Slack: N  |  Salesforce: N  |  Intercom: N  |  Spreadsheet rows: N  |  Interactive: N

*FBK pipeline — problem shaping & prioritization*
For each new request in Triage: merge with an existing issue if one covers the same problem, or keep it and move to *Now/Next* (active research priority), *Later/Icebox* (tracking for volume), or *Declined* (out of scope).

• <https://linear.app/elationhealth/team/EHRFBK/triage|EHR> — Triage: N [⚠️ High if >20]  |  Now/Next: N
• <https://linear.app/elationhealth/team/EBFBK/triage|Elation Billing> — Triage: N [⚠️ High if >20]  |  Now/Next: N
• <https://linear.app/elationhealth/team/PTFBK/triage|Patient Engagement> — Triage: N [⚠️ High if >20]  |  Now/Next: N
• <https://linear.app/elationhealth/team/ENTFBK/triage|Enterprise> — Triage: N [⚠️ High if >20]  |  Now/Next: N
```

The `⚠️ High` flag appears only when the Triage count exceeds 20. Example: `Triage: 23 ⚠️ High  |  Now/Next: 5`.

---

## Step 6 — Handle edge cases

**No activity this week (scan runs = 0 AND interactive runs = 0):**
```
📊 *Weekly Feedback Digest* — [Mon Apr X] – [Sun Apr Y]

Looks like the daily scan didn't run this week — no new items to report. To get things back on track:
• Check the scan schedule is active: `/schedule list`
• Kick off a manual scan: `/log-feedback`
<https://www.notion.so/335a68c48bc68063bbf1d530fd178128|View Notion run logs →>

*FBK pipeline — problem shaping & prioritization*
For each new request in Triage: merge with an existing issue if one covers the same problem, or keep it and move to *Now/Next*, *Later/Icebox*, or *Declined*.

• <https://linear.app/elationhealth/team/EHRFBK/triage|EHR> — Triage: N [⚠️ High if >20]  |  Now/Next: N
• <https://linear.app/elationhealth/team/EBFBK/triage|Elation Billing> — Triage: N [⚠️ High if >20]  |  Now/Next: N
• <https://linear.app/elationhealth/team/PTFBK/triage|Patient Engagement> — Triage: N [⚠️ High if >20]  |  Now/Next: N
• <https://linear.app/elationhealth/team/ENTFBK/triage|Enterprise> — Triage: N [⚠️ High if >20]  |  Now/Next: N
```

**Zero items in all Triage queues:**
Add a line: `✅ All Triage queues clear — great work!`

---

## Key rules

1. **Never post partial data.** If any Linear query fails, retry once. If it still fails, omit that sub-team's count and note "unavailable" rather than posting a 0 that could be mistaken for an empty queue.
2. **Always post even if nothing happened.** A zero-activity week is still useful signal (it may mean the scan isn't running).
3. **Post to #feedback-ops only.** Do not post to #elation-feedback.
4. **Post time:** Run at 7:00 AM PT every Monday so the team sees it before their work day starts.
5. **No confirmation gate.** This skill always posts immediately — it is designed for scheduled execution.
6. **Explain the pipeline stages inline.** The blurb above the queue counts must name the merge option and the three Triage decisions (Now/Next, Later/Icebox, Declined) so the message is self-contained for anyone unfamiliar with the workflow.
