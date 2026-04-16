# /export-to-notion

Export a customer-requests JSON file (downloaded from the HTML app) into a Notion review database.

## Usage
```
/export-to-notion ~/Downloads/customer-requests-2026-04-07.json
```

## Steps

1. **Read the JSON file** at the path provided in `$ARGUMENTS`. Parse it as an array of need objects.

2. **Find or create a parent page** in Notion:
   - Search Notion for a page titled "Customer Request Reviews"
   - If found, use it as the parent. If not found, create a new workspace-level page titled "Customer Request Reviews".

3. **Create the Notion database** under that parent page. Title it `Customer Requests Review — {today's date}`. Use this schema:

```sql
CREATE TABLE (
  "Request" TITLE,
  "Customer" RICH_TEXT,
  "Linked Issue" RICH_TEXT,
  "Issue Status" RICH_TEXT,
  "Domain" RICH_TEXT,
  "Priority" CHECKBOX,
  "Created" DATE,
  "Linear URL" URL,
  "Action" SELECT('No change':gray, 'Prioritize':green, 'Pass':red, 'Needs discussion':yellow),
  "Team Notes" RICH_TEXT,
  "Linear ID" RICH_TEXT
)
```

4. **Populate rows** — batch `notion-create-pages` calls (up to 100 rows per call). For each need in the JSON:
   - `Request` = first 150 characters of `body` (strip newlines)
   - `Customer` = `customer.name`
   - `Linked Issue` = `"{issue.identifier} · {issue.title}"` if issue exists, else blank
   - `Issue Status` = `issue.state` if present, else blank
   - `Domain` = extract from `body` using regex `\*\*Domain:\*\*\s*([^\n*]+)`, else blank
   - `Priority` = `priority` boolean (pass as `"__YES__"` or `"__NO__"` string)
   - `Created` = `createdAt` date (ISO format)
   - `Linear URL` = `url` if present, else blank
   - `Action` = "No change" (default — team will update)
   - `Team Notes` = blank
   - `Linear ID` = `id` (the Linear need UUID — used for sync-back)

5. **Output** the Notion database URL and a count of rows created. Remind the user to share the URL with their team and run `/sync-from-notion [url]` after review.

## Notes
- The JSON file is produced by clicking "⬇ Export" in the customer-requests HTML app
- `Linear ID` is the reference used by `/sync-from-notion` to write changes back to Linear
- The `Action` column is what reviewers should fill in — all other columns are read-only reference
