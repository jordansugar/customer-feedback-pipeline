# Feedback Pipeline — Deployment Guide

This document describes everything required to run the feedback pipeline on any machine (local or remote Claude Code agent).

## Pipeline overview

```
Stage 1: fetch-external-gaps  (4:00 AM PT daily)
  Intercom + Salesforce APIs → AI filter → #elation-feedback

Stage 2: process-feedback-channel  (6:00 AM PT daily)
  #elation-feedback → /log-feedback scan → Linear Triage + Notion run log

Stage 3: weekly-feedback-digest  (7:00 AM PT every Monday)
  #feedback-ops scan + Linear queue counts → #feedback-ops digest
```

Manual skills: `/log-feedback`, `/enterprise-intake`

---

## Required files

### 1. `~/.claude/config/integrations.json`

Required by: `fetch-external-gaps`

Copy from `config/integrations.json.template` and fill in credentials.

| Field | Description |
|-------|-------------|
| `intercom.access_token` | Intercom access token — Settings → Integrations → API |
| `salesforce.instance_url` | SF org URL, e.g. `https://elation.my.salesforce.com` |
| `salesforce.client_id` | Connected App consumer key |
| `salesforce.client_secret` | Connected App consumer secret |
| `salesforce.username` | SF username (email) |
| `salesforce.password` | SF password |
| `salesforce.security_token` | SF security token (from SF Settings → Reset Security Token) |

**Alternative: environment variables.** If `integrations.json` is absent or has `REPLACE_ME` values, the skill falls back to reading from env vars:

```bash
export INTERCOM_ACCESS_TOKEN="..."
export SF_INSTANCE_URL="https://elation.my.salesforce.com"
export SF_CLIENT_ID="..."
export SF_CLIENT_SECRET="..."
export SF_USERNAME="..."
export SF_PASSWORD="..."
export SF_SECURITY_TOKEN="..."
```

Env vars take lowest priority — the config file always wins if present.

---

### 2. `~/.claude/config/enterprise-accounts.json`

Required by: `enterprise-intake`, `log-feedback` (enterprise tracker write)

Copy from `config/enterprise-accounts.json.template` and fill in values.

| Field | Description |
|-------|-------------|
| `enterprise_feedback_tracker.database_id` | Notion DB ID for the Enterprise Feedback Tracker |
| `enterprise_feedback_tracker.data_source_id` | Notion data source ID (`d0e99400-bafe-4fe7-8f6e-8c4260772d45`) |
| `enterprise_account_pages.parent_page_id` | Notion parent page for account pages (`33ba68c48bc68015ba6a8c32cf4743e76`) |
| `idempotency_db_id` | Enterprise Intake Processed Messages DB (`40de7d459136413bb932e39b37028df3`) |
| `jtbd_source` | Path or URL to JTBD taxonomy (local file path, Google Sheets URL, or Notion DB ID). Used for domain inference in the Enterprise Tracker Write phase. Set to `null` to skip domain inference. |
| `accounts[].slack_channel_id` | Must be set manually before first scan. Find in Slack: channel settings → copy channel ID. |

**For remote agents:** The `enterprise-accounts.json` file is not auto-generated. Seed it from the Notion Enterprise Account Pages DB before first run, or copy from another machine running the pipeline.

---

## Skill files

Skills live in `feedback-pipeline/skills/` and are symlinked to `~/.claude/commands/`:

```bash
# Set up symlinks on a new machine
cd ~/.claude/commands
ln -sf /path/to/feedback-pipeline/skills/log-feedback.md log-feedback.md
ln -sf /path/to/feedback-pipeline/skills/fetch-external-gaps.md fetch-external-gaps.md
ln -sf /path/to/feedback-pipeline/skills/enterprise-intake.md enterprise-intake.md
ln -sf /path/to/feedback-pipeline/skills/weekly-feedback-digest.md weekly-feedback-digest.md
ln -sf /path/to/feedback-pipeline/skills/export-to-notion.md export-to-notion.md
ln -sf /path/to/feedback-pipeline/skills/sync-from-notion.md sync-from-notion.md
```

---

## Scheduled tasks

Scheduled tasks live in `~/.claude/scheduled-tasks/`. All three pipeline tasks are pre-configured:

| Folder | Skill invoked | Schedule |
|--------|--------------|----------|
| `fetch-external-gaps/` | `/fetch-external-gaps` | Daily 4:00 AM PT |
| `process-feedback-channel/` | `/log-feedback #elation-feedback last 2d` | Daily 6:00 AM PT |
| `weekly-feedback-digest/` | `/weekly-feedback-digest` | Mondays 7:00 AM PT |

To verify tasks are registered with Claude Code's remote task system:

```bash
# List all scheduled tasks
claude schedule list
```

---

## Slack channel IDs

| Channel | ID |
|---------|----|
| `#elation-feedback` | `C0AJW26J6NQ` |
| `#feedback-ops` | `C0AQSLQ55KM` |

---

## Linear team IDs

| Team | ID |
|------|----|
| FBK (parent) | `FBK` |
| EHR Feedback | `EHRFBK` |
| Elation Billing Feedback | `EBFBK` |
| Patient Engagement Feedback | `PTFBK` |
| Enterprise Feedback | `ENTFBK` |

---

## Notion DB IDs

| Resource | ID |
|----------|----|
| Run log DB | `335a68c4-8bc6-8063-bbf1-d530fd178128` |
| Enterprise Feedback Tracker | `d0e99400-bafe-4fe7-8f6e-8c4260772d45` (data source) |
| Enterprise Intake Processed Messages (idempotency) | `40de7d459136413bb932e39b37028df3` |
| Enterprise Account Pages parent | `33ba68c4-8bc6-8015-ba6a-8c32cf4743e76` |

---

## Health checks

After setup, verify the pipeline end-to-end:

1. **`fetch-external-gaps`:** Run manually — confirm a `📥 fetch-external-gaps` summary posts to `#feedback-ops`. If credentials are wrong, an alert posts there instead.
2. **`process-feedback-channel`:** Run `/log-feedback #elation-feedback last 2d` — confirm it reads the channel, posts `✅` thread replies, and writes a Notion run page.
3. **`weekly-feedback-digest`:** Run `/weekly-feedback-digest` manually — confirm it finds last week's `📊 /log-feedback scan` posts in `#feedback-ops` and produces a populated stats section.

---

## Security

- **Never commit `integrations.json` or `enterprise-accounts.json` to git.** Both files contain credentials and are listed in `.gitignore`.
- The `config/*.template` files in this repo contain only `REPLACE_ME` placeholders — safe to commit.
- Credentials should never appear in Slack messages, Notion pages, or Linear issue bodies.
