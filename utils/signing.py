"""Signed, expiring tokens for public (no-login) URLs.

The app is otherwise entirely `@login_required`; the invoice payment page is the
first public surface that exposes a specific record. Instead of a guessable
URL, we hand out an opaque token that (a) names the invoice by its `uuid` (never
the sequential pk) and (b) is signed with the project SECRET_KEY and stamped
with a timestamp, so it cannot be forged and expires on its own.

Built on `django.core.signing` (TimestampSigner + JSON). Rotating an invoice's
`uuid` invalidates every outstanding link for it.
"""

from django.core import signing

# Namespacing salt — keeps these tokens from being interchangeable with any
# other use of signing.dumps elsewhere in the project. A separate salt per
# purpose means an invoice token can't open a matter-balance page or vice versa.
_PAY_SALT = "invoicing.invoice-payment"
_REQUEST_SALT = "invoicing.payment-request"
_INTAKE_FORM_SALT = "intakes.client-form"


def make_payment_token(invoice) -> str:
    """Opaque signed token granting payment access to `invoice`."""
    return signing.dumps(str(invoice.uuid), salt=_PAY_SALT)


def read_payment_token(token: str, *, max_age=None) -> str:
    """Return the invoice uuid encoded in `token`.

    Raises `signing.SignatureExpired` if older than `max_age` seconds, or
    `signing.BadSignature` if tampered/invalid. Callers translate these into a
    friendly "link expired / invalid" page.
    """
    return signing.loads(token, salt=_PAY_SALT, max_age=max_age)


def make_form_token(submission) -> str:
    """Opaque signed token granting fill access to a client intake form.

    Signs the submission's uuid, never its pk, so rotating that uuid revokes
    every outstanding link for the form without touching the answers.
    """
    return signing.dumps(str(submission.uuid), salt=_INTAKE_FORM_SALT)


def read_form_token(token: str, *, max_age=None) -> str:
    """Return the FormSubmission uuid encoded in a form token (see
    read_payment_token for the raised exceptions)."""
    return signing.loads(token, salt=_INTAKE_FORM_SALT, max_age=max_age)


def make_request_token(payment_request) -> str:
    """Opaque signed token granting catch-up (full-balance) payment access via a
    PaymentRequest. Signs the request's uuid (never its pk), so paying the link
    ties back to the originating request."""
    return signing.dumps(str(payment_request.uuid), salt=_REQUEST_SALT)


def read_request_token(token: str, *, max_age=None) -> str:
    """Return the PaymentRequest uuid encoded in a request token (see
    read_payment_token for the raised exceptions)."""
    return signing.loads(token, salt=_REQUEST_SALT, max_age=max_age)
