import pytest
from pytest_django.asserts import assertTemplateUsed

pytestmark = pytest.mark.django_db


def test_index(client, matter):
    response = client.get(f"/matters/{matter.id}/events")
    assert response.status_code == 301
    assertTemplateUsed("matters/activity/events.html")
