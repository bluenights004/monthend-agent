# Connecting Xero and Microsoft 365

*For the person setting up live data. Do this once per firm, then once per client for Xero.*

Secrets (client secrets, tokens) go in your secret manager or in the service's environment file (`/etc/monthend/env`, mode 600). They never go in `config/` or in git. `.env.example` lists every variable.

## Xero

### Choose a connection type

| | Standard OAuth app | Custom connection |
|---|---|---|
| Best for | Many client organisations | One organisation per connection |
| Consent | A person clicks "Allow" once; the app keeps a refresh token | No user consent flow; machine-to-machine |
| Unattended risk | The refresh token expires if unused for 60 days, and rotates on every use | None from refresh tokens |
| Setting | `XERO_AUTH_MODE=authorization_code` | `XERO_AUTH_MODE=client_credentials` |

### Create the app

1. Go to developer.xero.com → My Apps → New app. Choose *Web app* (standard) or *Custom connection*.
2. For a web app, set the redirect URI to `http://localhost:8765/callback`.
3. Scopes. The system only reads:
   `accounting.reports.read accounting.settings.read accounting.transactions.read accounting.contacts.read accounting.attachments.read accounting.budgets.read offline_access`
4. Put the client id and secret in `XERO_CLIENT_ID` and `XERO_CLIENT_SECRET`.

### Connect an organisation (standard app)

```bash
.venv/bin/python -m monthend connect xero
```

A browser opens. Log in as someone with access to the client's Xero, and allow access. The command prints each connected organisation's **tenant id**. Put it in the client's config file (`source.xero_tenant_id`) and switch `source.backend` to `"live"`.

### Verify on one client before relying on it

1. Prepare a run for a month that is already closed, and compare the pack's net profit and balance sheet with the Xero reports.
2. Export the Trial Balance from Xero for the same date and confirm the column convention in `monthend/sources/xero_parse.py` holds for that organisation.
3. Check the receivables workpaper ties. It uses invoice payment dates to work out what was owed at month end, and its tie-out to the ledger exposes any difference.

### Limits and what the system does about them

Xero allows 60 calls per minute and 5,000 per day per organisation. The client paces itself below that, waits for the `Retry-After` time if it is told to slow down, and logs a warning when the daily allowance runs low. A typical month-end uses fewer than 30 calls per client.

### Webhooks (optional)

Webhooks let the overnight run know about late changes. In the Xero app, add a webhook to `https://<your host>/` (Xero only calls HTTPS, so put the receiver behind a reverse proxy or tunnel). Put the signing key in `XERO_WEBHOOK_KEY` and run:

```bash
.venv/bin/python -m monthend webhooks --port 8780
```

Events are verified and queued. They never trigger model work directly.

## Microsoft 365 (Outlook, SharePoint, Excel)

1. In Microsoft Entra admin centre → App registrations → New registration. Name it "Month-end agent", single tenant.
2. Certificates & secrets → New client secret. Put the values in `M365_TENANT_ID`, `M365_CLIENT_ID` and `M365_CLIENT_SECRET`.
3. API permissions → Microsoft Graph → **Application** permissions. Then grant admin consent:
   - `Sites.Selected`. Then grant the app access to the one client-files site only (Graph `POST /sites/{site-id}/permissions`, role `write`, needed for uploading the released pack).
   - `Mail.ReadWrite`, to read client emails and create drafts.
   - `Mail.Send`, only if any client is configured with `"mode": "send"`.
4. **Restrict the mailbox.** Application mail permissions cover every mailbox by default. Use an Exchange application access policy (or RBAC for Applications) to limit the app to the firm mailbox in `source.mailbox`.
5. Set `M365_SHAREPOINT_HOST` (e.g. `yourfirm.sharepoint.com`) and `M365_SHAREPOINT_SITE` (e.g. `sites/Clients`).
6. In each client config, set `source.sharepoint_folder`, e.g. `Clients/Harbour Joinery/{period}`. `{period}` becomes `2026-09`.

The system reads documents from that folder and saves a copy into the run's snapshot. From Outlook it stores only the subject, sender, date and preview of messages near the period. It never stores full email bodies.

## Checklist before going live

- [ ] One past month reproduced and compared to Xero reports.
- [ ] Reviewer names in each client config.
- [ ] `delivery.mode` is `draft` for every client.
- [ ] Mailbox access restricted to the firm mailbox.
- [ ] `var/` is on backed-up storage.
- [ ] Morning summary location (or webhook) agreed with the team.
