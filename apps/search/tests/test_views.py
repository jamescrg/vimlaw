import pytest
from pytest_django.asserts import assertTemplateUsed

pytestmark = pytest.mark.django_db


def test_index(client, folder, contact):
    response = client.get("/search/")
    assert response.status_code == 200
    assertTemplateUsed("search/content.html")


def test_results(client, contact, matter, intake):
    data = {"search_text": "Gandhi"}
    response = client.post("/search/results", data)
    assert response.status_code == 200
    assert len(response.context["contacts"]) == 1
    assert len(response.context["intakes"]) == 1
