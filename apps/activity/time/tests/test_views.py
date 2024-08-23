from datetime import date

import pytest
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

from apps.activity.time.models import TimeEntry

pytestmark = pytest.mark.django_db


def test_index(client):
    response = client.get("/activity/")
    assert response.status_code == 200

    response = client.get(reverse("activity:time-list"))
    assert response.status_code == 200

    assertTemplateUsed(response, "activity/list.html")
    assert response.context["page"] == "activity"
    assert "summary" in response.context


def test_add_get(client):
    response = client.get("/activity/time/add")
    assert response.status_code == 200
    assertTemplateUsed(response, "activity/time/form.html")
    assert response.context["add"]


def test_add_post(client, entry_data):
    response = client.post(reverse("activity:time-add"), entry_data)
    assert response.status_code == 302
    found = TimeEntry.objects.filter(actions=entry_data["actions"]).first()
    assert found


def test_edit_get(client, entry):
    response = client.get(f"/activity/time/{entry.id}/edit")
    assert response.status_code == 200
    assertTemplateUsed(response, "activity/time/form.html")


def test_edit_post(client, matter, entry):
    data = {
        "date": "2022-12-01",
        "matter": matter.id,
        "actions": "new actions",
        "hours": 2.5,
        "rate": 300,
    }
    response = client.post(f"/activity/time/{entry.id}/edit", data)
    assert response.status_code == 302
    found = TimeEntry.objects.filter(actions="new actions").exists()
    assert found


def test_delete(client, entry):
    response = client.get(f"/activity/time/{entry.id}/delete")
    assert response.status_code == 302
    found = TimeEntry.objects.filter(pk=entry.id).exists()
    assert not found


def test_filter(client):
    response = client.post("/activity/time/filter")
    assert response.status_code == 302
    assertTemplateUsed("activity/time-entries-filter.html")


def test_filter_update(client):
    data = {
        "date_from": "",
        "date_to": "",
        "matter": "",
        "keyword": "",
        "comp": "",
        "entered": "0",
        "order": "date",
        "user": "",
        "tab": "time",
        "invoiced": "1",
    }
    response = client.post("/activity/time/filter", data)
    assert response.status_code == 302
    response = client.get("/activity/time/filter")
    assert response.context["form"]["entered"].value() == "0"


def test_filter_quick(client):
    response = client.get("/activity/time/filter/quick/today")
    assert response.status_code == 302
    response = client.get("/activity/time/filter")
    assert client.session["time_filter"]["date_min"] == date.today().isoformat()


def test_filter_matter(client, matter):
    response = client.get(f"/activity/time/filter/matter/{matter.id}")
    assert response.status_code == 302
    response = client.get("/activity/time/filter")
    assert client.session["time_filter"]["matter"] == matter.id


def test_toggle_entered(client, entry):
    assert entry.entered == 0
    client.get(f"/activity/time/{entry.id}/toggle-entered")
    entry.refresh_from_db()
    assert entry.entered == 1


def test_export(client):
    response = client.get("/activity/export")
    assert response.status_code == 200
