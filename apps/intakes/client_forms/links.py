"""Build the public link for a client intake form."""

from django.urls import reverse

from utils.links import absolute
from utils.signing import make_form_token


def form_path(submission) -> str:
    """Root-relative fill URL, e.g. /form/<signed-token>/."""
    return reverse("intake_forms:fill", kwargs={"token": make_form_token(submission)})


def form_url(submission, request=None) -> str:
    """Absolute fill URL for emails and copy-to-clipboard.

    A fresh token is minted on every call, so resending simply hands out a new
    one against the same submission — nothing to expire or clean up.
    """
    return absolute(form_path(submission), request)
