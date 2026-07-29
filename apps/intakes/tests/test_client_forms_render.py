import copy

import pytest

from apps.intakes.client_forms.render import (
    answer_display,
    orphan_answers,
    render_blocks,
)
from apps.intakes.client_forms.schema import normalize_schema

pytestmark = pytest.mark.django_db


def by_key(blocks):
    return {block["key"]: block for block in blocks}


class TestSnapshotIsFrozen:
    def test_snapshot_survives_a_heavy_template_edit(
        self, filled_submission, form_template, answer_keys
    ):
        """The headline guarantee: gut the template, and an old submission
        still renders exactly the form that was asked, with its answers."""
        original = copy.deepcopy(filled_submission.schema_snapshot)

        # Delete a question, relabel another, reorder, add a new one, bump.
        edited = [f for f in form_template.schema if f["label"] != "When did it start?"]
        for field in edited:
            if field["label"] == "Property address":
                field["label"] = "Address of the property in dispute"
        edited.reverse()
        edited.append({"type": "textarea", "label": "Anything else?", "key": None})
        form_template.schema = normalize_schema(edited)
        form_template.version += 1
        form_template.save()

        filled_submission.refresh_from_db()
        assert filled_submission.schema_snapshot == original

        blocks = render_blocks(
            filled_submission.schema_snapshot, filled_submission.answers
        )
        assert [b["label"] for b in blocks] == [
            "Property address",
            "The dispute",
            "Nature of dispute",
            "When did it start?",
        ]
        answers = by_key(blocks)
        assert answers[answer_keys["Property address"]]["display"] == "225 Paper Street"
        assert answers[answer_keys["Nature of dispute"]]["display"] == "Boundary"
        assert answers[answer_keys["When did it start?"]]["display"] == "March 1, 2024"

    def test_answers_survive_a_relabel_because_the_key_does_not_change(
        self, filled_submission, answer_keys
    ):
        key = answer_keys["Property address"]
        snapshot = copy.deepcopy(filled_submission.schema_snapshot)
        snapshot[0]["label"] = "Where is the property?"

        block = by_key(render_blocks(snapshot, filled_submission.answers))[key]
        assert block["label"] == "Where is the property?"
        assert block["display"] == "225 Paper Street"

    def test_deleting_the_template_leaves_the_submission_readable(
        self, filled_submission, form_template
    ):
        form_template.delete()
        filled_submission.refresh_from_db()

        assert filled_submission.template is None
        assert filled_submission.template_name == "Property Dispute Questionnaire"
        assert len(render_blocks(filled_submission.schema_snapshot)) == 4

    def test_drift_is_reported_once_the_template_moves_on(
        self, form_submission, form_template
    ):
        assert form_submission.template_drifted is False
        form_template.version += 1
        form_template.save()
        form_submission.refresh_from_db()
        assert form_submission.template_drifted is True


class TestRenderBlocks:
    def test_a_retired_field_type_renders_instead_of_raising(self):
        """A snapshot written by a future build that we no longer understand
        must degrade, not 500."""
        snapshot = [{"key": "sig_a1b2c3", "type": "signature", "label": "Sign here"}]
        blocks = render_blocks(snapshot, {"sig_a1b2c3": "Mohandas Gandhi"})

        assert blocks[0]["kind"] == "unknown"
        assert blocks[0]["display"] == "Mohandas Gandhi"

    def test_layout_blocks_carry_no_answer(self, form_submission):
        blocks = render_blocks(form_submission.schema_snapshot)
        heading = next(b for b in blocks if b["kind"] == "heading")
        assert heading["label"] == "The dispute"
        assert heading["answered"] is False

    def test_choice_display_uses_the_label_not_the_stored_value(self):
        schema = normalize_schema(
            [
                {
                    "type": "checkboxes",
                    "label": "Documents",
                    "options": [{"label": "Deed"}, {"label": "Survey"}],
                }
            ]
        )
        field = schema[0]
        values = [option["value"] for option in field["options"]]
        assert answer_display(field, values) == "Deed, Survey"

    def test_unanswered_fields_report_no_display(self, form_submission):
        blocks = render_blocks(form_submission.schema_snapshot, form_submission.answers)
        assert all(b["display"] == "" for b in blocks)
        assert all(b["answered"] is False for b in blocks)

    def test_input_attributes_come_from_the_field_spec(self):
        schema = normalize_schema(
            [{"type": "textarea", "label": "Summary", "rows": 6, "max_length": 500}]
        )
        block = render_blocks(schema)[0]
        assert block["attrs"]["rows"] == 6
        assert block["attrs"]["maxlength"] == 500

    def test_selected_options_are_marked(self, filled_submission, answer_keys):
        block = by_key(
            render_blocks(filled_submission.schema_snapshot, filled_submission.answers)
        )[answer_keys["Nature of dispute"]]
        assert [o["label"] for o in block["options"] if o["selected"]] == ["Boundary"]


class TestOrphanAnswers:
    def test_answers_with_no_field_are_surfaced_not_dropped(self, filled_submission):
        filled_submission.answers["retired_a1b2c3"] = "an old answer"
        orphans = orphan_answers(
            filled_submission.schema_snapshot, filled_submission.answers
        )
        assert orphans == [("retired_a1b2c3", "an old answer")]

    def test_a_clean_submission_has_none(self, filled_submission):
        assert (
            orphan_answers(filled_submission.schema_snapshot, filled_submission.answers)
            == []
        )
