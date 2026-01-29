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


def test_results_by_case_number(client, proceeding):
    """Test that searching by case number finds the proceeding."""
    data = {"search_text": "2024-CV-12345"}
    response = client.post("/search/results", data)
    assert response.status_code == 200
    assert len(response.context["proceedings"]) == 1
    assert response.context["proceedings"][0] == proceeding
    assert response.context["proceedings"][0].matter == proceeding.matter


def test_results_by_partial_case_number(client, proceeding):
    """Test that partial case number matches work."""
    data = {"search_text": "CV-12345"}
    response = client.post("/search/results", data)
    assert response.status_code == 200
    assert len(response.context["proceedings"]) == 1
    assert response.context["proceedings"][0] == proceeding


def test_results_by_digit_only_case_number(client, proceeding):
    """Test that digit-only search finds proceedings via case number."""
    data = {"search_text": "12345"}
    response = client.post("/search/results", data)
    assert response.status_code == 200
    assert len(response.context["proceedings"]) == 1
    assert response.context["proceedings"][0] == proceeding


def test_results_by_fuzzy_case_number(client, proceeding):
    """Test that fuzzy case number matching works (ignores dashes, case-insensitive)."""
    # proceeding has case_number="2024-CV-12345"
    # Search without dashes and different case
    data = {"search_text": "2024cv12345"}
    response = client.post("/search/results", data)
    assert response.status_code == 200
    assert len(response.context["proceedings"]) == 1
    assert response.context["proceedings"][0] == proceeding


def test_results_by_fuzzy_partial_case_number(client, proceeding):
    """Test that fuzzy partial case number matching works."""
    # Search for partial without dashes
    data = {"search_text": "cv12345"}
    response = client.post("/search/results", data)
    assert response.status_code == 200
    assert len(response.context["proceedings"]) == 1
    assert response.context["proceedings"][0] == proceeding
