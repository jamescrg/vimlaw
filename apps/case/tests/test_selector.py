from apps.case.ai.selector import _parse_selector_response


def test_parses_selected_items():
    assert _parse_selector_response(
        '{"selected": [{"type": "document", "id": 3}, {"type": "note", "id": "7"}]}'
    ) == [("document", 3), ("note", 7)]


def test_null_selected_means_nothing_selected():
    assert _parse_selector_response('{"selected": null}') == []


def test_strips_markdown_fences():
    assert _parse_selector_response('```json\n{"selected": []}\n```') == []
