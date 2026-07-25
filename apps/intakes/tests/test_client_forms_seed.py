import copy

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client as DjangoClient

from apps.intakes.client_forms.links import form_path
from apps.intakes.client_forms.models import seed_templates
from apps.intakes.client_forms.render import render_blocks
from apps.intakes.client_forms.schema import FIELD_TYPES, normalize_schema
from apps.intakes.models import FormSubmission, FormTemplate

pytestmark = pytest.mark.django_db


class TestSeedData:
    def test_every_bundled_form_is_a_schema_the_app_accepts(self):
        for form in seed_templates():
            # Raises SchemaError if the bundled file has drifted out of spec.
            normalize_schema(form["schema"])

    def test_bundled_forms_use_only_known_field_types(self):
        for form in seed_templates():
            for field in form["schema"]:
                assert field["type"] in FIELD_TYPES, (form["key"], field["type"])

    def test_bundled_keys_are_unique_within_each_form(self):
        for form in seed_templates():
            keys = [field["key"] for field in form["schema"]]
            assert len(keys) == len(set(keys)), form["key"]

    def test_the_craig_legal_questionnaires_are_all_present(self):
        keys = {form["key"] for form in seed_templates()}
        assert {"inquiry", "intake", "onboarding"} <= keys
        # One supplement per dispute nature the website offers.
        assert sum(1 for key in keys if key.startswith("supplement_")) == 11


class TestSeedCommand:
    def test_creates_every_form(self):
        call_command("seed_intake_forms", verbosity=0)
        assert FormTemplate.objects.count() == len(seed_templates())

    def test_is_safe_to_re_run(self):
        call_command("seed_intake_forms", verbosity=0)
        call_command("seed_intake_forms", verbosity=0)
        assert FormTemplate.objects.count() == len(seed_templates())

    def test_leaves_staff_edits_alone_unless_replacing(self):
        call_command("seed_intake_forms", only=["intake"], verbosity=0)
        template = FormTemplate.objects.get(name="Client Intake")
        template.schema = normalize_schema(
            [{"type": "text", "label": "Hand-written by staff"}]
        )
        template.save()

        call_command("seed_intake_forms", only=["intake"], verbosity=0)
        template.refresh_from_db()
        assert len(template.schema) == 1

        call_command("seed_intake_forms", only=["intake"], replace=True, verbosity=0)
        template.refresh_from_db()
        assert len(template.schema) > 1

    def test_replaying_the_seed_keeps_answers_attached_to_their_questions(self, intake):
        """The whole point of freezing keys in the seed file."""
        call_command("seed_intake_forms", only=["intake"], verbosity=0)
        template = FormTemplate.objects.get(name="Client Intake")
        name_key = next(f["key"] for f in template.schema if f["label"] == "Full Name")

        submission = FormSubmission.objects.create(
            intake=intake,
            template=template,
            template_name=template.name,
            template_version=template.version,
            schema_snapshot=copy.deepcopy(template.schema),
            answers={name_key: "Mohandas Gandhi"},
        )

        call_command("seed_intake_forms", only=["intake"], replace=True, verbosity=0)
        template.refresh_from_db()

        blocks = {
            b["key"]: b for b in render_blocks(template.schema, submission.answers)
        }
        assert blocks[name_key]["label"] == "Full Name"
        assert blocks[name_key]["display"] == "Mohandas Gandhi"

    def test_draft_creates_them_inactive(self):
        call_command("seed_intake_forms", only=["inquiry"], draft=True, verbosity=0)
        assert FormTemplate.objects.get(name="Inquiry").is_active is False

    def test_dry_run_writes_nothing(self):
        call_command("seed_intake_forms", dry_run=True, verbosity=0)
        assert FormTemplate.objects.count() == 0

    def test_an_unknown_key_is_an_error(self):
        with pytest.raises(CommandError, match="Unknown form"):
            call_command("seed_intake_forms", only=["nope"], verbosity=0)


class TestSeededFormsAreUsable:
    @pytest.mark.parametrize("key", ["inquiry", "intake", "onboarding"])
    def test_a_seeded_form_renders_on_the_public_page(self, intake, key):
        """The bundled forms are the widest field-type coverage we have — if
        one of them can't render, the public page has a hole in it."""
        call_command("seed_intake_forms", only=[key], verbosity=0)
        template = FormTemplate.objects.exclude(schema=[]).first()

        submission = FormSubmission.objects.create(
            intake=intake,
            template=template,
            template_name=template.name,
            template_version=template.version,
            schema_snapshot=copy.deepcopy(template.schema),
        )
        response = DjangoClient().get(form_path(submission))
        assert response.status_code == 200

        body = response.content.decode()
        first_question = next(
            f for f in template.schema if f["type"] not in ("heading", "text_block")
        )
        assert first_question["label"] in body
