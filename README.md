# BAM vs Heijmans dashboard

A market dashboard comparing Koninklijke BAM Groep and Koninklijke Heijmans.

## How it works

- `index.html` is the dashboard.
- `scripts/fetch_data.py` fetches share prices (Yahoo Finance) and headlines (Google News).
- `.github/workflows/update-data.yml` runs that script on GitHub every 15 minutes during
  Euronext trading hours (every 3 hours otherwise) and saves the result in `data/data.json`.
- The dashboard reads `data/data.json` from its own site, so no proxy servers are involved.

If a source fails, the last real data is kept and the page shows its age. No data is made up.

## Notes

- Prices are delayed by about 15 minutes plus the schedule interval.
- GitHub may run scheduled jobs a few minutes late, and pauses them after 60 days without
  activity in the repository.
- Yahoo Finance data is for personal use. Keep the link for personal and demo use.
- Not investment advice.
