"""Render test for the public pay page under the Confido processor.

Confirms the page actually emits Confido's client-side surface — the
hosted-fields SDK script, the iframe container divs with Confido's exact ids,
and the payment-session token as the public key — with the network (the
`paymentSessionCreate` call inside `client_config`) mocked out.
"""

from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse

from utils.signing import make_payment_token

pytestmark = pytest.mark.django_db


def test_pay_page_renders_confido_hosted_fields(settings, sent_invoice):
    settings.PAYMENT_PROCESSOR = "confido"
    settings.CONFIDO_API_KEY = "f_secret_test"
    settings.CONFIDO_OPERATING_BANK_ACCOUNT_ID = "ba_operating"
    settings.CONFIDO_HOSTED_FIELDS_URL = "https://js.test/hosted-fields.js"

    session = {
        "data": {"paymentSessionCreate": {"paymentSessionToken": "pay_pub_render"}}
    }

    class _Resp:
        status_code = 200

        def json(self):
            return session

    url = reverse("pay:invoice", kwargs={"token": make_payment_token(sent_invoice)})
    with patch("apps.invoicing.processors.confido.requests.post", return_value=_Resp()):
        response = Client().get(url)

    assert response.status_code == 200
    html = response.content.decode()
    # SDK loaded + initialized against the session token.
    assert "https://js.test/hosted-fields.js" in html
    assert "confidoHostedFields" in html
    assert "pay_pub_render" in html
    # Card + ACH iframe containers with Confido's required ids.
    for container_id in (
        'id="card-number"',
        'id="card-exp"',
        'id="card-cvv"',
        'id="routing-number"',
        'id="account-number"',
        'id="account-holder-name"',
    ):
        assert container_id in html, container_id
