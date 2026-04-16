# /sync-from-notion

Read a Notion review database (created by `/export-to-notion`) and sync team decisions back to Linear.

## Usage
```
/sync-from-notion https://notion.so/elation/Customer-Requests-Review-...
```

## Steps

1. **Fetch the Notion database** at the URL in `$ARGUMENTS` using `notion-fetch`. Get the data source ID from the `<data-source>` tag in the response.

2. **Read all rows** — fetch the full page list from the data source. For each row, extract:
   - `Linear ID` — the need UUID for Linear API calls
   - `Action` — the team's decision
   - `Team Notes` — any notes the team added
   - `Request` — the request text (for the summary)
   - `Customer` — customer name (for the summary)

3. **Apply changes to Linear** for all rows where `Action` ≠ "No change":

   | Action | What to do in Linear |
   |--------|----------------------|
   | **Prioritize** | `customerNeedUpdate(id, { priority: 1 })` via Linear GraphQL |
   | **Pass** | No change in Linear — log in summary for manual cleanup |
   | **Needs discussion** | No change in Linear — surface in summary with Team Notes |

   Use the Linear API key stored in the app's localStorage (ask user to provide it if needed — it's the same key used by the HTML app):
   ```
   POST https://api.linear.app/graphql
   Authorization: <api-key>

   mutation UpdateNeedPriority($id: String!, $priority: Float) {
     customerNeedUpdate(id: $id, input: { priority: $priority }) { success }
   }
   ```

4. **Mark synced rows in Notion** — for each row that was actioned (Prioritize / Pass / Needs discussion), update the `Action` field to append " ✓" using `notion-update-page` so the team knows it's been processed.

5. **Print a summary**:
   ```
   Sync complete — {date}
   ✅ Prioritized: {n} requests
   ⏭ Passed: {n} requests (no Linear change — review manually if needed)
   💬 Needs discussion: {n} requests
      - "{request preview}" ({customer}) — Notes: "{team notes}"
   ```

## Notes
- The Linear API key is the same one saved in the customer-requests HTML app's localStorage
- Only rows with `Action` ≠ "No change" are processed — unreviewed rows are skipped
- Run this command after your team has finished reviewing and setting Action values in Notion
- Safe to run multiple times — rows already marked with " ✓" will be skipped on re-run
