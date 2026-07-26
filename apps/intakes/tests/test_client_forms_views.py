import json

import pytest
from django.urls import reverse

from apps.intakes.client_forms.models import FormTemplate

pytestmark = pytest.mark.django_db


class TestFormsLibraryLivesUnderSettings:
    def test_forms_index_renders_in_the_settings_shell(self, client, form_template):
        response = client.get(reverse("intakes:forms-index"))
        assert response.status_code == 200
        # Lights the Settings sidebar item and its subnav, like checklists.
        assert response.context["app"] == "settings"
        assert response.context["subapp"] == "intake-forms"
        assert form_template.name in response.content.decode()

    def test_the_settings_subnav_links_to_it(self, client):
        body = client.get(reverse("settings:profile-index")).content.decode()
        assert reverse("intakes:forms-index") in body
        assert "Intake Forms" in body

    def test_the_intakes_index_is_a_plain_page_again(self, client, intake):
        """Forms left the Intakes tab, so its subnav went with it."""
        response = client.get(reverse("intakes:index"))
        assert response.status_code == 200
        assert intake.name in response.content.decode()
        assert "intakes/subnav.html" not in [t.name for t in response.templates]

    def test_forms_index_requires_login(self, form_template):
        from django.test import Client

        response = Client().get(reverse("intakes:forms-index"))
        assert response.status_code == 302

    def test_forms_are_gated_on_perm_intakes(self, client, user):
        user.role = "USER"
        user.perm_intakes = False
        user.save()
        response = client.get(reverse("intakes:forms-index"))
        assert response.status_code in (302, 403)


class TestTemplateCrud:
    def test_creating_a_form_redirects_into_the_builder(self, client):
        response = client.post(
            reverse("intakes:form-template-new"),
            {"name": "Landlord Questionnaire", "description": "", "intro_text": ""},
        )
        assert response.status_code == 204
        template = FormTemplate.objects.get(name="Landlord Questionnaire")
        assert response["HX-Redirect"] == f"/intakes/forms/{template.id}/"

    def test_duplicating_copies_the_questions_but_not_the_active_flag(
        self, client, form_template
    ):
        response = client.post(
            reverse(
                "intakes:form-template-duplicate",
                kwargs={"template_id": form_template.id},
            )
        )
        assert response.status_code == 204
        copy_of = FormTemplate.objects.get(name="Property Dispute Questionnaire (copy)")
        assert copy_of.schema == form_template.schema
        assert copy_of.is_active is False

    def test_deleting_a_template_keeps_its_submissions(self, client, filled_submission):
        template_id = filled_submission.template_id
        response = client.post(
            reverse("intakes:form-template-delete", kwargs={"template_id": template_id})
        )
        assert response.status_code == 204

        filled_submission.refresh_from_db()
        assert filled_submission.template is None
        assert filled_submission.answers  # the answers are still there
        assert len(filled_submission.schema_snapshot) == 4


class TestBuilderSave:
    def url(self, template):
        return reverse("intakes:form-builder-save", kwargs={"template_id": template.id})

    def post(self, client, template, payload):
        return client.post(
            self.url(template), json.dumps(payload), content_type="application/json"
        )

    def test_builder_page_renders_with_its_config(self, client, form_template):
        response = client.get(
            reverse("intakes:form-builder", kwargs={"template_id": form_template.id})
        )
        assert response.status_code == 200
        config = json.loads(response.context["config"])
        assert config["schema"] == form_template.schema
        assert config["defaults"]["text"]["max_length"] == 255

    def test_save_stores_the_schema_and_bumps_the_version(self, client, form_template):
        before = form_template.version
        response = self.post(
            client,
            form_template,
            {
                "name": "Renamed",
                "schema": [{"type": "text", "label": "Your name", "key": None}],
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["version"] == before + 1

        form_template.refresh_from_db()
        assert form_template.name == "Renamed"
        assert len(form_template.schema) == 1
        # The response echoes the minted key back so the builder can re-hydrate.
        assert body["schema"][0]["key"] == form_template.schema[0]["key"]

    def test_save_preserves_a_key_across_a_relabel(self, client, form_template):
        original = form_template.schema[0]
        self.post(
            client,
            form_template,
            {
                "schema": [
                    {**original, "label": "Where is the property?"},
                ]
            },
        )
        form_template.refresh_from_db()
        assert form_template.schema[0]["key"] == original["key"]
        assert form_template.schema[0]["label"] == "Where is the property?"

    def test_a_bad_schema_is_rejected_with_a_readable_message(
        self, client, form_template
    ):
        response = self.post(
            client, form_template, {"schema": [{"type": "signature", "label": "Sign"}]}
        )
        assert response.status_code == 400
        assert "unknown type" in response.json()["error"]

        form_template.refresh_from_db()
        assert len(form_template.schema) == 4  # untouched

    def test_an_oversized_body_is_refused_before_parsing(self, client, form_template):
        payload = {"schema": [{"type": "text", "label": "x" * 200_000}]}
        response = self.post(client, form_template, payload)
        assert response.status_code == 413

    def test_save_requires_post(self, client, form_template):
        assert client.get(self.url(form_template)).status_code == 405
