"""Agent tools: handlers, budget, dedupe, and the parallel batch runner."""

import json
import time
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.case.ai.agent_tools import (
    AgentBudget,
    build_agent_tools,
    make_agent_executor,
    run_tool_batch,
)
from apps.case.models import CaseLaw
from apps.mail.models import Email
from apps.notes.models import Note, NoteFolder

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _no_semantic_pass(monkeypatch):
    """These tests exercise the keyword and fuzzy paths; the semantic
    pass is faked out (test_semantic.py covers it)."""
    monkeypatch.setattr("apps.case.ai.agent_tools.semantic_entries", lambda *a, **k: [])


def call(name, **kwargs):
    return {"id": f"call_{name}", "name": name, "input": kwargs}


def run(execute_batch, name, **kwargs):
    outcome = execute_batch([call(name, **kwargs)])[0]
    return json.loads(outcome["content"]), outcome


@pytest.fixture
def text_document(document):
    document.ocr_text = "Alpha " * 50 + "spoliation letter " + "omega " * 50
    document.ocr_status = "completed"
    document.save(update_fields=["ocr_text", "ocr_status"])
    return document


@pytest.fixture
def executor(matter):
    events = []
    execute = make_agent_executor(matter, None, on_event=events.append)
    execute.events = events
    return execute


class TestSpecs:
    def test_every_tool_has_a_schema(self):
        specs = build_agent_tools()
        names = {spec["name"] for spec in specs}
        assert {"search_materials", "read_document", "read_matter_section"} <= names
        for spec in specs:
            assert spec["input_schema"]["type"] == "object"
            assert spec["description"]


class TestReadDocument:
    def test_full_read(self, executor, text_document):
        payload, outcome = run(executor, "read_document", doc_id=text_document.id)
        assert not outcome["is_error"]
        assert payload["text"] == text_document.ocr_text
        assert payload["next_offset"] is None
        assert payload["budget"]["calls_left"] == 39
        step = executor.events[-1]
        assert step["type"] == "tool" and not step["pending"]
        assert step["label"].startswith("Read *Test Document*")
        assert step["title"] == "Read *Test Document*"
        assert step["detail"].endswith("chars")
        assert step["chars"] == len(text_document.ocr_text)

    def test_parts(self, matter, text_document):
        budget = AgentBudget(default_read_chars=100, max_read_chars=100)
        execute = make_agent_executor(matter, None, budget=budget)
        first, _ = run(execute, "read_document", doc_id=text_document.id)
        assert len(first["text"]) == 100
        assert first["truncated"] and first["next_offset"] == 100
        second, _ = run(
            execute,
            "read_document",
            doc_id=text_document.id,
            offset=first["next_offset"],
        )
        assert second["text"] == text_document.ocr_text[100:200]
        assert second["offset"] == 100

    def test_never_document_refused(self, executor, text_document):
        text_document.ai_context = "never"
        text_document.save(update_fields=["ai_context"])
        payload, outcome = run(executor, "read_document", doc_id=text_document.id)
        assert outcome["is_error"]
        assert "excluded" in payload["error"]

    def test_unknown_document(self, executor):
        payload, outcome = run(executor, "read_document", doc_id=999_999)
        assert outcome["is_error"]
        assert executor.events[-1]["error"]
        # The elbow line carries the error; the call line keeps its title.
        assert executor.events[-1]["title"].startswith("Reading document")

    def test_no_text(self, executor, document):
        payload, outcome = run(executor, "read_document", doc_id=document.id)
        assert outcome["is_error"]
        assert "no extracted text" in payload["error"]

    def test_summary_and_description_in_payload(self, executor, text_document):
        text_document.description = "Letter to opposing counsel"
        text_document.summary = "A preservation demand covering the ESI at issue."
        text_document.save(update_fields=["description", "summary"])
        payload, outcome = run(executor, "read_document", doc_id=text_document.id)
        assert not outcome["is_error"]
        assert payload["description"] == "Letter to opposing counsel"
        assert payload["summary"] == (
            "A preservation demand covering the ESI at issue."
        )

    def test_blank_summary_and_description_omitted(self, executor, text_document):
        text_document.description = ""
        text_document.summary = None
        text_document.save(update_fields=["description", "summary"])
        payload, outcome = run(executor, "read_document", doc_id=text_document.id)
        assert not outcome["is_error"]
        assert "description" not in payload
        assert "summary" not in payload


class TestBudget:
    def test_repeat_is_free_and_flagged(self, executor, text_document):
        run(executor, "read_document", doc_id=text_document.id)
        payload, outcome = run(executor, "read_document", doc_id=text_document.id)
        assert not outcome["is_error"]
        assert "already made this exact call" in payload["note"]
        assert payload["text"] == text_document.ocr_text
        assert executor.events[-1]["repeat"] is True
        assert executor.events[-1]["detail"].endswith("repeat, not charged")
        usage = executor.usage()
        assert usage["tool_calls"] == 1
        assert usage["chars_read"] == len(text_document.ocr_text)

    def test_call_cap(self, matter):
        execute = make_agent_executor(
            matter, None, budget=AgentBudget(max_tool_calls=2)
        )
        run(execute, "read_matter_section", section="overview")
        run(execute, "read_matter_section", section="contacts")
        payload, outcome = run(execute, "read_matter_section", section="tasks")
        assert outcome["is_error"]
        assert "Tool budget exhausted" in payload["error"]
        assert execute.usage()["tool_calls"] == 2

    def test_read_cap(self, matter, text_document):
        execute = make_agent_executor(matter, None, budget=AgentBudget(max_chars=10))
        first, _ = run(execute, "read_document", doc_id=text_document.id)
        assert len(first["text"]) == 10
        payload, outcome = run(execute, "read_matter_section", section="overview")
        assert outcome["is_error"]
        assert "Reading budget exhausted" in payload["error"]

    def test_unknown_tool(self, executor):
        payload, outcome = run(executor, "open_material", x=1)
        assert outcome["is_error"]
        assert "Unknown tool" in payload["error"]

    def test_cancelled(self, matter, text_document):
        execute = make_agent_executor(matter, None, is_cancelled=lambda: True)
        payload, outcome = run(execute, "read_document", doc_id=text_document.id)
        assert outcome["is_error"]
        assert execute.usage()["tool_calls"] == 0


class TestSearch:
    def test_hits_and_seen_flags(self, executor, text_document, fact):
        from watson import search as watson

        watson.default_search_engine.update_obj_index(text_document)
        payload, outcome = run(executor, "search_materials", query="spoliation")
        assert not outcome["is_error"]
        kinds = {hit["kind"] for hit in payload["hits"]}
        assert "document" in kinds
        doc_hit = next(h for h in payload["hits"] if h["kind"] == "document")
        assert doc_hit["handle"] == f"doc:{text_document.id}"
        assert "spoliation" in doc_hit["snippet"]
        assert "summary" not in doc_hit
        assert doc_hit["seen"] is False
        assert executor.events[-1]["label"].startswith('Searched "spoliation"')
        assert executor.events[-1]["title"] == 'Searched "spoliation"'
        assert "hits" in executor.events[-1]["detail"]

        again, _ = run(executor, "search_materials", query="spoliation letter")
        assert any(h["seen"] for h in again["hits"])

    def test_email_hits(self, executor, matter):
        from watson import search as watson

        email = Email.objects.create(
            matter=matter,
            gmail_id="m1",
            thread_id="t1",
            sender="oc@example.com",
            recipients="james@example.com",
            subject="Depo dates",
            body_text="How about the spoliation letter on Tuesday?",
            date=timezone.now(),
        )
        watson.default_search_engine.update_obj_index(email)
        payload, _ = run(
            executor, "search_materials", query="spoliation", kinds=["email"]
        )
        assert payload["hits"][0]["handle"] == "thread:t1"
        assert payload["hits"][0]["name"] == "Depo dates"
        assert "spoliation" in payload["hits"][0]["snippet"]

    def test_phrase_or_and_variants(self, executor, matter, user):
        from watson import search as watson

        note_a = Note.objects.create(
            matter=matter,
            title="Deposit memo",
            content="The earnest money deposit was returned to the buyer.",
        )
        note_b = Note.objects.create(
            matter=matter,
            title="Wire note",
            content="Money for the deposit arrived by wire.",
        )
        for note in (note_a, note_b):
            watson.default_search_engine.update_obj_index(note)

        phrase, _ = run(
            executor, "search_materials", query='"earnest money"', kinds=["note"]
        )
        assert [h["id"] for h in phrase["hits"]] == [note_a.id]

        either, _ = run(
            executor, "search_materials", query="earnest OR wire", kinds=["note"]
        )
        assert {h["id"] for h in either["hits"]} == {note_a.id, note_b.id}

        merged, outcome = run(
            executor,
            "search_materials",
            queries=["earnest money", "deposit arrived"],
            kinds=["note"],
        )
        by_id = {h["id"]: h for h in merged["hits"]}
        assert by_id[note_a.id]["matched"] == ["earnest money"]
        assert by_id[note_b.id]["matched"] == ["deposit arrived"]
        step = executor.events[-1]
        assert step["title"] == 'Searched "earnest money" and 1 more'
        assert "2 hits" in step["detail"]

    def test_document_and_library_summaries_in_hits(
        self, executor, matter, user, text_document
    ):
        from watson import search as watson

        text_document.summary = "A preservation demand covering the ESI at issue."
        text_document.save(update_fields=["summary"])
        watson.default_search_engine.update_obj_index(text_document)
        root = NoteFolder.objects.create(name="Firm Library")
        lib = Note.objects.create(
            author=user,
            folder=root,
            title="Spoliation guide",
            content="How to send a spoliation letter.",
            summary="Checklist for preservation demands.",
        )
        watson.default_search_engine.update_obj_index(lib)
        payload, _ = run(executor, "search_materials", query="spoliation")
        by_kind = {h["kind"]: h for h in payload["hits"]}
        assert by_kind["document"]["summary"] == (
            "A preservation demand covering the ESI at issue."
        )
        assert by_kind["library"]["summary"] == ("Checklist for preservation demands.")

    def test_fuzzy_fallback_on_typo(self, executor, matter, user):
        from watson import search as watson

        note = Note.objects.create(
            matter=matter,
            title="Spoliation Letter",
            content="Preservation demand sent to opposing counsel.",
        )
        watson.default_search_engine.update_obj_index(note)
        payload, outcome = run(
            executor, "search_materials", query="spoilation leter", kinds=["note"]
        )
        assert not outcome["is_error"]
        assert "near matches" in payload["note"]
        assert payload["hits"][0]["id"] == note.id
        assert payload["hits"][0]["fuzzy"] is True

    def test_empty_query(self, executor):
        payload, outcome = run(executor, "search_materials", query="  ")
        assert outcome["is_error"]


class TestOtherReads:
    def test_email_thread(self, executor, matter):
        for i in range(2):
            Email.objects.create(
                matter=matter,
                gmail_id=f"m{i}",
                thread_id="t9",
                sender="oc@example.com",
                recipients="james@example.com",
                subject="Depo dates",
                body_text=f"Body {i}",
                date=timezone.now() - timedelta(days=2 - i),
            )
        payload, outcome = run(executor, "read_email_thread", thread_id="t9")
        assert not outcome["is_error"]
        assert payload["messages"] == 2
        assert "Body 0" in payload["text"] and "Body 1" in payload["text"]
        assert executor.events[-1]["kind"] == "email"

    def test_note_and_library_note(self, executor, matter, user):
        note = Note.objects.create(matter=matter, title="Memo", content="Matter memo")
        root = NoteFolder.objects.create(name="Firm Library")
        lib = Note.objects.create(
            author=user, folder=root, title="Guide", content="Library guide"
        )
        payload, _ = run(executor, "read_note", note_id=note.id)
        assert payload["text"] == "Matter memo" and payload["library"] is False
        payload, _ = run(executor, "read_note", note_id=lib.id)
        assert payload["text"] == "Library guide" and payload["library"] is True
        assert payload["folder"] == "Firm Library"

    def test_other_matter_note_refused(self, executor, user, contact, practice_area):
        from apps.matters.models import Matter

        other = Matter.objects.create(
            user=user,
            name="Other",
            status="Open",
            date_start="2024-01-01",
            practice_area=practice_area,
            client=contact,
        )
        note = Note.objects.create(matter=other, title="Secret", content="x")
        payload, outcome = run(executor, "read_note", note_id=note.id)
        assert outcome["is_error"]

    def test_caselaw_opinion_is_cached(self, executor, matter, monkeypatch):
        from django.core.cache import cache

        cache.clear()
        calls = []

        def fake_fetch(caselaw):
            calls.append(caselaw.id)
            return "OPINION TEXT"

        monkeypatch.setattr(
            "apps.case.ai.context._fetch_caselaw_opinion_text", fake_fetch
        )
        case = CaseLaw.objects.create(
            matter=matter,
            citation="1 Ga. 1",
            case_name="Smith v. Jones",
            court="Supreme Court of Georgia",
            notes="Key holding on fees.",
        )
        payload, _ = run(executor, "read_caselaw", caselaw_id=case.id)
        assert "OPINION TEXT" in payload["text"]
        assert "Key holding" in payload["text"]
        fresh = make_agent_executor(matter, None)
        run(fresh, "read_caselaw", caselaw_id=case.id)
        assert calls == [case.id]

    def test_matter_section(self, executor, matter):
        payload, outcome = run(executor, "read_matter_section", section="overview")
        assert not outcome["is_error"]
        assert "Test Matter" in payload["text"]
        payload, outcome = run(executor, "read_matter_section", section="nope")
        assert outcome["is_error"]


class TestBatchRunner:
    def test_order_preserved_with_parallel_workers(self):
        calls = [{"id": str(i), "name": "t", "input": {"i": i}} for i in range(6)]

        def slow_then_fast(call):
            time.sleep(0.05 * (5 - call["input"]["i"]))
            return {"id": call["id"], "name": "t", "content": "{}", "is_error": False}

        outcomes = run_tool_batch(calls, slow_then_fast, max_workers=4)
        assert [o["id"] for o in outcomes] == [str(i) for i in range(6)]

    def test_inline_path(self):
        seen = []

        def record(call):
            seen.append(call["id"])
            return {"id": call["id"], "name": "t", "content": "{}", "is_error": False}

        run_tool_batch([{"id": "a", "name": "t", "input": {}}], record, max_workers=4)
        run_tool_batch(
            [
                {"id": "b", "name": "t", "input": {}},
                {"id": "c", "name": "t", "input": {}},
            ],
            record,
            max_workers=1,
        )
        assert seen == ["a", "b", "c"]

    def test_handler_exception_becomes_error_outcome(self, matter, text_document):
        # Inline path: pool threads would open their own DB connections and
        # miss the test transaction's rows.
        execute = make_agent_executor(
            matter, None, budget=AgentBudget(parallel_workers=1)
        )
        outcomes = execute(
            [
                call("read_document", doc_id=text_document.id),
                call("read_matter_section", section="overview"),
                call("read_document", doc_id="not-an-id"),
            ]
        )
        assert [o["is_error"] for o in outcomes] == [False, False, True]
        assert [o["id"] for o in outcomes] == [
            "call_read_document",
            "call_read_matter_section",
            "call_read_document",
        ]


class TestResearchTools:
    def _cache_opinion(self, cluster_id, text, case_name="Smith v. Jones"):
        from django.core.cache import cache as django_cache

        django_cache.set(
            f"agent_opinion_cluster_{cluster_id}",
            {
                "cluster_id": cluster_id,
                "case_name": case_name,
                "citation": "278 Ga. App. 206 (2006)",
                "date_filed": "2006-03-01",
                "url": "",
                "text": text,
            },
            60,
        )

    def test_search_caselaw_merges_and_flags_published(
        self, executor, matter, monkeypatch
    ):
        matter.jurisdiction = "State of Georgia"
        matter.save(update_fields=["jurisdiction"])
        calls = []

        def fake_search(
            query, court="", limit=5, order_by="score desc", filed_after=""
        ):
            calls.append({"query": query, "court": court, "filed_after": filed_after})
            return [
                {
                    "case_name": "Valdosta Hotel Props. v. White",
                    "citation": ["278 Ga. App. 206", "628 S.E.2d 642"],
                    "court": "Georgia Court of Appeals",
                    "date_filed": "2006-03-17",
                    "cluster_id": 111,
                    "snippet": "<mark>joinder</mark> under 9-11-21",
                    "score": 1.0,
                    "cite_count": 40,
                    "courtlistener_url": "",
                },
                {
                    "case_name": "Slip Op. v. Recent",
                    "citation": [],
                    "court": "Georgia Court of Appeals",
                    "date_filed": "2026-06-01",
                    "cluster_id": 222,
                    "snippet": "",
                    "score": 0.5,
                    "cite_count": 0,
                    "courtlistener_url": "",
                },
            ], 200

        monkeypatch.setattr(
            "apps.case.research.courtlistener.search_opinions", fake_search
        )
        payload, outcome = run(
            executor,
            "search_caselaw",
            queries=['"9-11-21" "9-11-15"', '"9-11-21" joinder'],
            filed_after="2000-01-01",
        )
        assert not outcome["is_error"]
        # Both variants hit the same clusters: merged, matched flags both.
        assert payload["total"] == 2
        assert payload["state"] == "ga"
        assert all(call["court"] == "ga gactapp" for call in calls)
        assert all(call["filed_after"] == "2000-01-01" for call in calls)
        anchor = payload["hits"][0]
        assert anchor["published"] is True
        assert anchor["citation"] == "278 Ga. App. 206, 628 S.E.2d 642"
        assert "<mark>" not in anchor["snippet"]
        assert anchor["matched"] == ['"9-11-21" "9-11-15"', '"9-11-21" joinder']
        assert payload["hits"][1]["published"] is False

    def test_search_caselaw_all_queries_failed(self, executor, monkeypatch):
        monkeypatch.setattr(
            "apps.case.research.courtlistener.search_opinions",
            lambda *a, **k: ([], 400),
        )
        payload, outcome = run(executor, "search_caselaw", query="bad query")
        assert outcome["is_error"]
        assert "failed" in payload["error"]

    def test_lookup_citation_found_and_not(self, executor, monkeypatch):
        from apps.case.courtlistener import CaseLookupResult

        results = {
            "267 Ga. App. 431": CaseLookupResult(
                found=True,
                case_name="Bircoll v. Rosenthal",
                citation="267 Ga. App. 431",
                court="Georgia Court of Appeals",
                cluster_id=333,
            ),
            "1 Fake 1": CaseLookupResult(found=False, error="not found"),
        }
        monkeypatch.setattr(
            "apps.case.courtlistener.lookup_citation", lambda c: results[c]
        )
        payload, outcome = run(executor, "lookup_citation", citation="267 Ga. App. 431")
        assert not outcome["is_error"]
        assert payload["found"] and payload["cluster_id"] == 333
        payload, outcome = run(executor, "lookup_citation", citation="1 Fake 1")
        assert not outcome["is_error"]
        assert payload["found"] is False and "note" in payload

    def test_read_opinion_fetches_once_then_caches(self, executor, monkeypatch):
        from django.core.cache import cache as django_cache

        django_cache.delete("agent_opinion_cluster_444")
        fetches = []

        def fake_cluster(cluster_id):
            fetches.append(cluster_id)
            return {
                "case_name": "Dollar Concrete v. Watson",
                "citations": [
                    {"volume": 207, "reporter": "Ga. App.", "page": "452", "type": 1}
                ],
                "date_filed": "1993-02-01",
                "sub_opinions": ["https://x/api/rest/v4/opinions/9001/"],
                "absolute_url": "/opinion/444/x/",
            }

        from apps.case.courtlistener import OpinionResult

        monkeypatch.setattr("apps.case.courtlistener.fetch_cluster", fake_cluster)
        monkeypatch.setattr(
            "apps.case.courtlistener.fetch_opinion",
            lambda oid: OpinionResult(
                found=True, opinion_id=oid, plain_text="OPINION " * 30
            ),
        )
        payload, outcome = run(executor, "read_opinion", cluster_id=444)
        assert not outcome["is_error"]
        assert payload["case_name"] == "Dollar Concrete v. Watson"
        assert "OPINION" in payload["text"]
        assert outcome["is_error"] is False
        assert fetches == [444]

        # Second, different call (offset) is served from the cache.
        payload, _ = run(executor, "read_opinion", cluster_id=444, offset=8)
        assert fetches == [444]
        assert payload["offset"] == 8

    def test_read_opinion_unknown_cluster(self, executor, monkeypatch):
        from django.core.cache import cache as django_cache

        django_cache.delete("agent_opinion_cluster_555")
        monkeypatch.setattr("apps.case.courtlistener.fetch_cluster", lambda cid: {})
        payload, outcome = run(executor, "read_opinion", cluster_id=555)
        assert outcome["is_error"]

    def test_search_in_opinions_isolation_and_offsets(self, executor, monkeypatch):
        from django.core.cache import cache as django_cache

        text = (
            "pad " * 100 + "the joinder rule" + " pad" * 100 + " the joinder rule again"
        )
        self._cache_opinion(666, text)
        django_cache.delete("agent_opinion_cluster_667")
        monkeypatch.setattr("apps.case.courtlistener.fetch_cluster", lambda cid: {})
        payload, outcome = run(
            executor,
            "search_in_opinions",
            cluster_ids=[666, 667],
            query="the joinder rule",
            snippet_size=120,
        )
        assert not outcome["is_error"]
        by_id = {r["cluster_id"]: r for r in payload["results"]}
        good = by_id[666]
        assert good["match_count"] == 2
        assert all("the joinder rule" in s["text"] for s in good["snippets"])
        first = good["snippets"][0]["position"]
        assert text[first : first + len("the joinder rule")] == "the joinder rule"
        assert "error" in by_id[667]

    def test_search_in_opinions_zero_matches_ok(self, executor):
        self._cache_opinion(668, "nothing relevant here")
        payload, outcome = run(
            executor, "search_in_opinions", cluster_ids=[668], query="spoliation"
        )
        assert not outcome["is_error"]
        assert payload["results"][0]["match_count"] == 0
