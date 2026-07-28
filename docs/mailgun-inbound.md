# Mailgun inbound route: intake from forwarded email

Forward a prospective client's email (or a Zoom voicemail transcription
email) to `intake-kosmos@mail.craiglegal.law`. Mailgun POSTs the parsed message to
`/api/inbound-email/`; the app verifies the signature, checks the sender,
and a worker task asks the AI to extract intake fields. The result is a new
Open intake whose first note holds the original message text. If extraction
fails, the intake is still created from the raw message and the stored
`InboundEmail` row records the error (visible in the Django admin).

Follow-ups work the same way: forward them to the same address. When the
extracted sender email (or, failing that, a 10-digit phone match) matches
an existing intake, the message is logged as a note on that intake instead
of opening a duplicate; the most recent matching intake wins. A follow-up
landing on an Unresponsive intake flips it back to Open (the caller
resurfacing is what that status was waiting on); every other status is
left alone.

Only mail sent FROM an active firm user's login email is accepted; anything
else (spam sent straight to the intake address) is dropped without a trace.
Forward from the same address that is on your Kosmos user account, or the
message will be silently ignored.

## One-time setup

1. **DNS.** Add MX records on `mail.craiglegal.law` (the Mailgun sending
   subdomain; this does not affect mail for `craiglegal.law` itself):

   ```
   mail.craiglegal.law.  MX 10 mxa.mailgun.org.
   mail.craiglegal.law.  MX 10 mxb.mailgun.org.
   ```

2. **Route.** The Mailgun plan's route quota is 1 and the slot was already
   held by the billing-replies safety net (replies sent to the From address
   `billing@mail.craiglegal.law` instead of the Reply-To). Everything shares
   one route (route id `6a4ba62d934b42fdb0585a6c`):
   - Expression:
     `match_recipient("(billing|intake-kosmos|intake-kosmos-dev)@mail\.craiglegal\.law")`
   - Actions: `forward("billing@craiglegal.law")`,
     `forward("https://kosmos.craiglegal.law/api/inbound-email/")`,
     `forward("https://kosmos.dev-server.io/api/inbound-email/")`, `stop()`
   - Every matched message goes to BOTH webhooks; each instance only
     processes mail for the address it owns (`INTAKE_INBOUND_RECIPIENT` in
     `config/.env`: `intake-kosmos` on prod, `intake-kosmos-dev` on dev) and drops the
     rest. Forward to `intake-kosmos-dev@mail.craiglegal.law` to integration-test
     against the dev server at any time; the nightly dev DB reload sweeps
     the test intakes away.
   - The billing inbox also receives a copy of everything the route matches,
     including intake forwards (add a Gmail filter on
     `to:(intake-kosmos@mail.craiglegal.law OR intake-kosmos-dev@mail.craiglegal.law)` to
     auto-archive the copies if the noise bothers you).
   - If the route needs recreating, use the API; the dashboard's route form
     fails with unhelpful errors:

   ```
   curl -s --user 'api:<MAILGUN_API_KEY>' https://api.mailgun.net/v3/routes \
     -F priority=0 \
     -F description='Billing replies to Workspace + intake forwards to Kosmos prod and dev' \
     -F expression='match_recipient("(billing|intake-kosmos|intake-kosmos-dev)@mail\.craiglegal\.law")' \
     -F action='forward("billing@craiglegal.law")' \
     -F action='forward("https://kosmos.craiglegal.law/api/inbound-email/")' \
     -F action='forward("https://kosmos.dev-server.io/api/inbound-email/")' \
     -F action='stop()'
   ```

3. **Signing key.** Mailgun dashboard > Settings > API Security > HTTP
   webhook signing key. Put it in `config/.env`:

   ```
   MAILGUN_WEBHOOK_SIGNING_KEY=key-...
   ```

   While the variable is empty, signature verification is not enforced (so
   the webhook can be deployed before the key is configured).

4. Restart gunicorn and the qcluster worker.

## Smoke test

Forward any email from a firm address to `intake-kosmos@mail.craiglegal.law` (or
`intake-kosmos-dev@mail.craiglegal.law` to test against the dev server). An
Open intake with a first note ("Email In" or "VM In") should appear in the
intakes list within a minute. If nothing appears, check the `InboundEmail`
rows in the admin: no row means the message was rejected at the webhook
(signature or sender); a `failed` row means the AI call failed but a
fallback intake should still be linked.
