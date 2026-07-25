import pytest

from apps.intakes.client_forms.schema import (
    MAX_FIELDS,
    SchemaError,
    blank_field,
    normalize_schema,
    validate_answers,
)


def one(field):
    """Normalize a single field and hand back the stored object."""
    return normalize_schema([field])[0]


class TestNormalizeSchema:
    def test_mints_a_key_for_a_new_field(self):
        field = one({"type": "text", "label": "Property address", "key": None})
        assert field["key"].startswith("property_address_")

    def test_preserves_an_existing_key(self):
        field = one({"type": "text", "label": "Renamed", "key": "original_a1b2c3"})
        assert field["key"] == "original_a1b2c3"

    def test_duplicate_keys_are_reminted_so_answers_cannot_collide(self):
        schema = normalize_schema(
            [
                {"type": "text", "label": "One", "key": "shared_a1b2c3"},
                {"type": "text", "label": "Two", "key": "shared_a1b2c3"},
            ]
        )
        assert schema[0]["key"] == "shared_a1b2c3"
        assert schema[1]["key"] != "shared_a1b2c3"

    def test_rejects_an_unknown_type(self):
        with pytest.raises(SchemaError, match="unknown type"):
            normalize_schema([{"type": "signature", "label": "Sign here"}])

    def test_rejects_a_field_with_no_label(self):
        with pytest.raises(SchemaError, match="needs a label"):
            normalize_schema([{"type": "text", "label": "  "}])

    def test_rejects_a_choice_field_with_no_options(self):
        with pytest.raises(SchemaError, match="at least one option"):
            normalize_schema([{"type": "select", "label": "Pick", "options": []}])

    def test_rejects_more_than_max_fields(self):
        too_many = [{"type": "text", "label": f"Q{n}"} for n in range(MAX_FIELDS + 1)]
        with pytest.raises(SchemaError, match="at most"):
            normalize_schema(too_many)

    def test_drops_keys_the_type_does_not_declare(self):
        field = one(
            {
                "type": "text",
                "label": "Address",
                "rows": 40,
                "evil": "<script>",
                "options": [{"label": "nope"}],
            }
        )
        assert "evil" not in field
        assert "rows" not in field
        assert "options" not in field

    def test_blank_option_rows_are_dropped_not_rejected(self):
        field = one(
            {
                "type": "radio",
                "label": "Own or rent?",
                "options": [{"label": "Own"}, {"label": "   "}, {"label": "Rent"}],
            }
        )
        assert [o["label"] for o in field["options"]] == ["Own", "Rent"]

    def test_layout_blocks_cannot_be_required(self):
        assert (
            one({"type": "heading", "label": "Part 2", "required": True})["required"]
            is False
        )

    def test_blank_field_carries_every_declared_default(self):
        assert blank_field("textarea")["rows"] == 4
        assert blank_field("checkboxes")["options"] == []


class TestValidateAnswers:
    @pytest.fixture
    def schema(self):
        return normalize_schema(
            [
                {"type": "text", "label": "Name", "required": True},
                {"type": "email", "label": "Email"},
                {"type": "number", "label": "Acres", "min": "1", "max": "10"},
                {
                    "type": "checkboxes",
                    "label": "Documents",
                    "options": [{"label": "Deed"}, {"label": "Survey"}],
                    "min_selected": 1,
                },
            ]
        )

    def keys(self, schema):
        return {field["label"]: field["key"] for field in schema}

    def test_partial_save_skips_required(self, schema):
        cleaned, errors = validate_answers(schema, {}, partial=True)
        assert errors == {}
        assert cleaned == {}

    def test_full_validation_flags_a_missing_required_field(self, schema):
        _cleaned, errors = validate_answers(schema, {}, partial=False)
        assert errors[self.keys(schema)["Name"]] == "This question is required."

    def test_unknown_answer_keys_are_discarded(self, schema):
        cleaned, _errors = validate_answers(
            schema, {"not_a_field": "smuggled"}, partial=True
        )
        assert cleaned == {}

    def test_rejects_an_invalid_email(self, schema):
        keys = self.keys(schema)
        _cleaned, errors = validate_answers(
            schema, {keys["Email"]: "not-an-email"}, partial=True
        )
        assert "valid email" in errors[keys["Email"]]

    def test_enforces_numeric_bounds(self, schema):
        keys = self.keys(schema)
        _cleaned, errors = validate_answers(schema, {keys["Acres"]: "99"}, partial=True)
        assert "10 or less" in errors[keys["Acres"]]

    def test_phone_is_normalized_to_digits(self):
        schema = normalize_schema([{"type": "phone", "label": "Phone"}])
        key = schema[0]["key"]
        cleaned, errors = validate_answers(
            schema, {key: "(406) 363-1234"}, partial=True
        )
        assert errors == {}
        assert cleaned[key] == "4063631234"

    def test_checkbox_values_must_be_on_the_form(self, schema):
        keys = self.keys(schema)
        real = schema[3]["options"][0]["value"]
        cleaned, _errors = validate_answers(
            schema, {keys["Documents"]: [real, "forged"]}, partial=True
        )
        assert cleaned[keys["Documents"]] == [real]

    def test_min_selected_enforced_only_on_submit(self, schema):
        keys = self.keys(schema)
        _cleaned, partial_errors = validate_answers(
            schema, {keys["Documents"]: []}, partial=True
        )
        assert keys["Documents"] not in partial_errors

        _cleaned, errors = validate_answers(
            schema,
            {keys["Name"]: "Gandhi", keys["Documents"]: []},
            partial=False,
        )
        assert keys["Documents"] not in errors  # empty is unanswered, not too few

        _cleaned, errors = validate_answers(
            schema,
            {
                keys["Name"]: "Gandhi",
                keys["Documents"]: [schema[3]["options"][0]["value"]],
            },
            partial=False,
        )
        assert errors == {}

    def test_a_select_rejects_a_value_not_on_the_form(self):
        schema = normalize_schema(
            [{"type": "select", "label": "Pick", "options": [{"label": "Boundary"}]}]
        )
        key = schema[0]["key"]
        _cleaned, errors = validate_answers(schema, {key: "forged"}, partial=True)
        assert "listed options" in errors[key]

    def test_yes_no_stores_a_boolean(self):
        schema = normalize_schema([{"type": "yesno", "label": "Written contract?"}])
        key = schema[0]["key"]
        cleaned, _errors = validate_answers(schema, {key: "no"}, partial=True)
        assert cleaned[key] is False

    def test_false_counts_as_an_answer_to_a_required_yes_no(self):
        schema = normalize_schema(
            [{"type": "yesno", "label": "Written contract?", "required": True}]
        )
        key = schema[0]["key"]
        _cleaned, errors = validate_answers(schema, {key: False}, partial=False)
        assert errors == {}
