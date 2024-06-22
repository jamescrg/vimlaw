import pytest

pytestmark = pytest.mark.django_db


# -----------------------------------------------------
# matter
# -----------------------------------------------------
def test_string(matter):
    assert str(matter) == f"{matter.name}"


def test_content(matter):
    expectedValues = {
        "name": "Sample Test Matter",
        "description": "Awaiting response from OC",
        "status": "Open",
        "practice_area": "General",
    }
    for key, val in expectedValues.items():
        assert getattr(matter, key) == val


# -----------------------------------------------------
# role
# -----------------------------------------------------
def test_role_string(role):
    assert str(role) == f"{role.name}"


def test_role_content(role):
    expectedValues = {
        "name": "Client",
    }
    for key, val in expectedValues.items():
        assert getattr(role, key) == val


# -----------------------------------------------------
# relationship
# -----------------------------------------------------
def test_relationship_string(relationship):
    string_representation = (
        f"matter: {relationship.matter.id}, "
        f"contact: {relationship.contact.id}, role: {relationship.role.id}"
    )
    assert str(relationship) == string_representation


def test_relationship_content(relationship, matter, contact, role):
    expectedValues = {
        "matter": matter,
        "contact": contact,
        "role": role,
    }
    for key, val in expectedValues.items():
        assert getattr(relationship, key) == val


# -----------------------------------------------------
# proceeding
# -----------------------------------------------------
def test_proceeding_string(proceeding):
    assert str(proceeding) == f"{proceeding.case_number}"


def test_proceeding_content(proceeding, user, matter):
    expectedValues = {
        "user_id": user.id,
        "matter": matter,
        "date_filed": "2020-08-07",
        "forum": "Fulton Superior",
        "case_number": "20CV141360",
        "status": "Concluded",
    }
    for key, val in expectedValues.items():
        assert getattr(proceeding, key) == val


# -----------------------------------------------------
# settlement entry
# -----------------------------------------------------
def test_entry_string(entry):
    assert str(entry) == f"{entry.amount}"


def test_entry_content(entry, user, matter):
    expectedValues = {
        "user_id": user.id,
        "matter": matter,
        "date": "2020-08-07",
        "medium": "Email",
        "type": "Demand",
        "amount": "10000",
        "notes": "With full release",
    }
    for key, val in expectedValues.items():
        assert getattr(entry, key) == val


# -----------------------------------------------------
# fact
# -----------------------------------------------------
def test_fact_string(fact):
    assert str(fact) == f"{fact.description}"


def test_fact_content(fact, user, matter):
    expectedValues = {
        "user_id": user.id,
        "matter": matter,
        "date": "2020-08-07",
        "description": "Email to OC",
        "citation": "Evidence",
        "emphasis": "Yes",
    }
    for key, val in expectedValues.items():
        assert getattr(fact, key) == val
