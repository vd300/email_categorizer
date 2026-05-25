# AI Email Cleaner & Prioritizer

FastAPI backend that helps clean a cluttered Gmail inbox by categorizing emails, summarizing threads, extracting action items, detecting urgency, and drafting replies.

## Features

- Categorizes mail into receipts, invoices, payment dues, renewals, jobs, tasks, conversations, promotions, travel, security, and more.
- Produces short summaries and action items.
- Scores priority and flags urgent messages.
- Drafts reply suggestions.
- Imports raw email payloads immediately, with optional Gmail OAuth sync endpoints.
- Works without an AI key using deterministic heuristics; uses OpenAI when `OPENAI_API_KEY` is configured.
- Docker-ready and deployable to Render, Fly, Railway, Azure Container Apps, or any container host.

## Quick Start

```bash
uv sync --dev
copy .env.example .env
uv run uvicorn app.main:app --reload
```

Open:

- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

## Example Import

```bash
curl -X POST http://localhost:8000/api/v1/emails/import ^
  -H "Content-Type: application/json" ^
  -d "{\"emails\":[{\"sender\":\"billing@example.com\",\"subject\":\"Invoice due tomorrow\",\"body\":\"Your invoice for $149 is due tomorrow. Please pay to avoid late fees.\"}]}"
```

## Main Endpoints

- `POST /api/v1/emails/import` - Import emails for categorization.
- `GET /api/v1/emails` - List emails with filters like `category`, `urgent`, `needs_reply`.
- `GET /api/v1/emails/{email_id}` - Read a processed email.
- `POST /api/v1/emails/{email_id}/draft-reply` - Generate a reply draft.
- `POST /api/v1/emails/reprocess` - Re-run prioritization for stored emails.
- `GET /api/v1/categories/summary` - Inbox category counts and urgent totals.
- `GET /api/v1/gmail/oauth/url` - Start Gmail OAuth.
- `GET /api/v1/gmail/oauth/callback` - OAuth callback.
- `POST /api/v1/gmail/sync` - Sync recent Gmail messages after OAuth.
- `POST /api/v1/gmail/apply-labels` - Create/apply Gmail labels such as `AI Cleaner/job`, `AI Cleaner/invoice`, and `AI Cleaner/urgent`.

## Gmail Setup

1. Create a Google Cloud project.
2. Enable the Gmail API.
3. Create OAuth 2.0 credentials for a web app.
4. Add your callback URL, for local dev:
   `http://localhost:8000/api/v1/gmail/oauth/callback`
5. Put `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REDIRECT_URI` in `.env`.

For local development, keep:

```text
ENVIRONMENT=local
ALLOW_INSECURE_OAUTH_TRANSPORT=true
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/gmail/oauth/callback
```

This allows the OAuth callback to work on `http://localhost`. In production, use HTTPS and set `ALLOW_INSECURE_OAUTH_TRANSPORT=false`.

### Multiple Gmail Profiles

The API supports lightweight multi-user testing with a `profile` query parameter. Each profile gets separate Gmail OAuth credentials and separate stored emails:

```text
GET  /api/v1/gmail/oauth/url?profile=alice
POST /api/v1/gmail/sync?profile=alice
POST /api/v1/gmail/apply-labels?profile=alice
GET  /api/v1/emails?profile=alice
GET  /api/v1/categories/summary?profile=alice
```

Use a stable profile value for each Gmail account, such as `alice`, `bob`, or an internal user id. Calls without `profile` continue to use `default`.

For a production SaaS version, bind `profile` to real authentication and encrypt stored OAuth credentials.

This app uses the Gmail `modify` scope so it can add labels to your Gmail messages. If you previously connected with read-only permission, reconnect Gmail by running `GET /api/v1/gmail/oauth/url` again and approving the updated permission.

## Deployment

### Docker

```bash
docker build -t ai-email-cleaner .
docker run -p 8000:8000 --env-file .env ai-email-cleaner
```

### Render

Push this repository to GitHub and create a Render Blueprint using `render.yaml`. Configure the secret environment variables in the Render dashboard.

For production, use Postgres:

```text
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DB
```

Then add the matching database driver:

```bash
uv add "psycopg[binary]"
```

## Testing

```bash
uv run pytest
```
