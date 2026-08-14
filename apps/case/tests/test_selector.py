from unittest.mock import patch

import pytest

from apps.case.ai.selector import (
    ManifestItem,
    _fallback_by_importance,
    _parse_selector_response,
    build_manifest,
    format_manifest_for_prompt,
    select_context,
)

pytestmark = pytest.mark.django_db


def test_parses_selected_items():
    assert _parse_selector_response(
        '{"selected": [{"type": "document", "id": 3}, {"type": "note", "id": "7"}]}'
    ) == [("document", 3), ("note", 7)]


def test_null_selected_means_nothing_selected():
    assert _parse_selector_response('{"selected": null}') == []


def test_strips_markdown_fences():
    assert _parse_selector_response('```json\n{"selected": []}\n```') == []


@pytest.fixture
def library_note(user):
    from apps.notes.models import Note, NoteFolder

    root = NoteFolder.objects.create(name="Firm Library")
    sub = NoteFolder.objects.create(name="Evidence", parent=root)
    return Note.objects.create(
        author=user,
        title="Hearsay Exceptions",
        folder=sub,
        summary="Georgia hearsay exceptions outline.",
        content="Present sense impression, excited utterance. " * 30,
    )


class TestLibraryManifest:
    def test_library_notes_join_manifest(self, matter, library_note):
        items, content_map = build_manifest(matter)
        lib = [i for i in items if i.item_type == "library"]
        assert len(lib) == 1
        assert lib[0].item_id == library_note.id
        assert lib[0].category == "Library: Firm Library/Evidence"
        assert lib[0].description == "Georgia hearsay exceptions outline."
        key = ("library", library_note.id)
        assert key in content_map
        assert "Hearsay Exceptions" in content_map[key]
        assert "(Firm Library/Evidence)" in content_map[key]

    def test_include_library_false_suppresses(self, matter, library_note):
        items, _ = build_manifest(matter, include_library=False)
        assert not [i for i in items if i.item_type == "library"]

    def test_lib_label_in_prompt(self):
        item = ManifestItem(
            item_type="library",
            item_id=9,
            name="Guide",
            category="Library: Guides",
            date=None,
            description="A guide.",
            word_count=100,
            importance=4,
        )
        text = format_manifest_for_prompt([item], 1000)
        assert "[LIB-9]" in text


def _mk(item_type, item_id, words=100, importance=4):
    return ManifestItem(
        item_type=item_type,
        item_id=item_id,
        name=f"{item_type}-{item_id}",
        category="",
        date=None,
        description="",
        word_count=words,
        importance=importance,
    )


class TestLibrarySelection:
    def test_short_circuit_without_library(self):
        items = [_mk("document", 1)]
        content_map = {("document", 1): "doc text"}
        with patch("apps.case.ai.selector.send_to_gemini") as send:
            selected, unselected = select_context(items, content_map, "q", 10_000)
        assert not send.called
        assert selected == ["doc text"]

    def test_library_bypasses_short_circuit(self):
        items = [_mk("document", 1), _mk("library", 2)]
        content_map = {("document", 1): "doc text", ("library", 2): "lib text"}
        with patch(
            "apps.case.ai.selector.send_to_gemini",
            return_value=('{"selected": [{"type": "library", "id": 2}]}', 1, 1),
        ) as send:
            selected, unselected = select_context(items, content_map, "q", 10_000)
        assert send.called
        assert selected == ["lib text"]
        assert [i.item_id for i in unselected] == [1]

    def test_fallback_never_picks_library(self):
        items = [_mk("library", 1, importance=7), _mk("document", 2, importance=1)]
        content_map = {("library", 1): "lib", ("document", 2): "doc"}
        keys = _fallback_by_importance(items, content_map, 10_000)
        assert ("library", 1) not in keys
        assert ("document", 2) in keys


class TestEffortTiers:
    def test_thorough_selection_uses_pro_model_and_addendum(self):
        items = [_mk("document", 1), _mk("library", 2)]
        content_map = {("document", 1): "doc text", ("library", 2): "lib text"}
        with patch(
            "apps.case.ai.selector.send_to_gemini",
            return_value=('{"selected": []}', 1, 1),
        ) as send:
            select_context(items, content_map, "q", 10_000, thorough=True)
        assert send.called
        assert send.call_args.kwargs["model"] == "gemini-pro-latest"
        assert "High-effort selection" in send.call_args.kwargs["system_context"]

    def test_default_selection_stays_on_flash(self):
        items = [_mk("document", 1), _mk("library", 2)]
        content_map = {("document", 1): "doc text", ("library", 2): "lib text"}
        with patch(
            "apps.case.ai.selector.send_to_gemini",
            return_value=('{"selected": []}', 1, 1),
        ) as send:
            select_context(items, content_map, "q", 10_000)
        assert send.call_args.kwargs["model"] == "gemini-2.5-flash"
        assert "High-effort selection" not in send.call_args.kwargs["system_context"]
