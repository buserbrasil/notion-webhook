# Notion Webhook

Small FastAPI service that receives Notion webhook callbacks. It validates the `X-Notion-Signature`, handles the initial subscription handshake, fetches the full Notion entity (page or database) on each event, and can store the rendered Markdown snapshot in PostgreSQL.

## What this project solves

- Expose `/webhook/notion` so you can plug a Notion integration and receive live updates without polling.
- Keep verification and signature validation simple so you can provision webhooks quickly.
- Optionally persist the latest Markdown snapshot (plus metadata) for each page/database to drive downstream workflows.

For architecture, setup instructions, deployment notes, and troubleshooting guides, see [AGENT.md](AGENT.md).
