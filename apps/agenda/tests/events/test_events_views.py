import pytest
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

from apps.agenda.events.models import Event

pytestmark = pytest.mark.django_db


def test_index(client):
    response = client.get("/events/")
    assert response.status_code == 200
    response = client.get(reverse("agenda:events-list"))
    assert response.status_code == 200
    assert response.context["app"] == "agenda"


def test_add_get(client):
    # test without a selected folder
    response = client.get("/events/add")
    assert response.status_code == 200
    assertTemplateUsed(response, "agenda/events/form.html")


def test_add_post(client, matter, event_data):
    response = client.post("/events/add", event_data)
    assert response.status_code == 302
    found = Event.objects.filter(description=event_data["description"]).first()
    assert found


def test_edit_get(client, event):
    response = client.get(f"/events/{event.id}/edit/test")
    assert response.status_code == 200
    assertTemplateUsed(response, "agenda/events/form.html")


def test_edit_post(client, user, matter, event):
    data = {
        "user_id": user.id,
        "matter": matter.id,
        "date": "2022-12-28",
        "party": "Opposing",
        "description": "File Answer",
        "status": "Complete",
    }
    response = client.post(f"/events/{event.id}/edit", data)
    assert response.status_code == 302
    found = Event.objects.filter(status="Complete").exists()
    assert found


def test_delete(client, event):
    response = client.get(f"/events/{event.id}/delete")
    assert response.status_code == 302
    found = Event.objects.filter(pk=event.id).exists()
    assert not found
