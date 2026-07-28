# Mailgun inbound route: intake from forwarded email

Forward a prospective client's email (or a Zoom voicemail transcription
email) to `intake@mail.craiglegal.law`. Mailgun POSTs the parsed message to
`/api/inbound-email/`; the app verifies the signature, checks the sender,
and a worker task asks the AI to extract intake fields. The result is a new
Open intake whose first note holds the original message text. If extraction
fails, the intake is still created from the raw message and the stored
`InboundEmail` row records the error (visible in the Django admin).

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

2. **Route.** Mailgun dashboard > Receiving > Create Route:
   - Expression type: Match Recipient, `intake@mail.craiglegal.law`
   - Action: Forward, `https://kosmos.craiglegal.law/api/inbound-email/`
   - Also check "Stop" so no later route fires.

3. **Signing key.** Mailgun dashboard > Settings > API Security > HTTP
   webhook signing key. Put it in `config/.env`:

   ```
   MAILGUN_WEBHOOK_SIGNING_KEY=key-...
   ```

   While the variable is empty, signature verification is not enforced (so
   the webhook can be deployed before the key is configured).

4. Restart gunicorn and the qcluster worker.

## Smoke test

Forward any email from a firm address to `intake@mail.craiglegal.law`. An
Open intake with a first note ("Email In" or "VM In") should appear in the
intakes list within a minute. If nothing appears, check the `InboundEmail`
rows in the admin: no row means the message was rejected at the webhook
(signature or sender); a `failed` row means the AI call failed but a
fallback intake should still be linked.
