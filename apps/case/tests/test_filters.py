import pytest

from apps.case.documents.filters import FilesFilter
from apps.case.facts.filters import FactsFilter
from apps.case.highlights.filters import HighlightsFilter
from apps.case.models import Document, Fact, Highlight

pytestmark = pytest.mark.django_db


class TestFilesFilter:
    def test_filter_by_keyword_in_name(self, matter, document):
        queryset = Document.objects.filter(matter=matter)
        filter_obj = FilesFilter({"keyword": "Test"}, queryset=queryset, matter=matter)
        assert document in filter_obj.qs

    def test_filter_by_keyword_in_description(self, matter, document):
        queryset = Document.objects.filter(matter=matter)
        filter_obj = FilesFilter(
            {"keyword": "test document"}, queryset=queryset, matter=matter
        )
        assert document in filter_obj.qs

    def test_filter_by_keyword_no_match(self, matter, document):
        queryset = Document.objects.filter(matter=matter)
        filter_obj = FilesFilter(
            {"keyword": "nonexistent"}, queryset=queryset, matter=matter
        )
        assert document not in filter_obj.qs

    def test_filter_by_category(self, matter, document):
        queryset = Document.objects.filter(matter=matter)
        filter_obj = FilesFilter(
            {"category": "Evidence"}, queryset=queryset, matter=matter
        )
        assert document in filter_obj.qs

    def test_filter_by_category_no_match(self, matter, document):
        queryset = Document.objects.filter(matter=matter)
        filter_obj = FilesFilter(
            {"category": "Discovery"}, queryset=queryset, matter=matter
        )
        assert document not in filter_obj.qs

    def test_filter_by_date_from(self, matter, document):
        queryset = Document.objects.filter(matter=matter)
        filter_obj = FilesFilter(
            {"date_from": "2024-01-01"}, queryset=queryset, matter=matter
        )
        assert document in filter_obj.qs

    def test_filter_by_date_to(self, matter, document):
        queryset = Document.objects.filter(matter=matter)
        filter_obj = FilesFilter(
            {"date_to": "2024-12-31"}, queryset=queryset, matter=matter
        )
        assert document in filter_obj.qs

    def test_filter_by_importance(self, matter, document):
        queryset = Document.objects.filter(matter=matter)
        filter_obj = FilesFilter({"importance": "5"}, queryset=queryset, matter=matter)
        assert document in filter_obj.qs

    def test_filter_by_label(self, matter, document, label):
        document.labels.add(label)
        queryset = Document.objects.filter(matter=matter)
        filter_obj = FilesFilter({"label": label.id}, queryset=queryset, matter=matter)
        assert document in filter_obj.qs

    def test_order_by_name(self, matter, document):
        queryset = Document.objects.filter(matter=matter)
        filter_obj = FilesFilter({"order_by": "name"}, queryset=queryset, matter=matter)
        assert list(filter_obj.qs) == list(queryset.order_by("name"))

    def test_order_by_name_descending(self, matter, document):
        queryset = Document.objects.filter(matter=matter)
        filter_obj = FilesFilter(
            {"order_by": "-name"}, queryset=queryset, matter=matter
        )
        assert list(filter_obj.qs) == list(queryset.order_by("-name"))

    def test_proceeding_queryset_filtered(self, matter, proceeding):
        queryset = Document.objects.filter(matter=matter)
        filter_obj = FilesFilter({}, queryset=queryset, matter=matter)
        assert proceeding in filter_obj.filters["proceeding"].queryset


class TestHighlightsFilter:
    def test_filter_by_keyword_in_slug(self, matter, highlight):
        queryset = Highlight.objects.filter(document__matter=matter)
        filter_obj = HighlightsFilter(
            {"keyword": "Test"}, queryset=queryset, matter=matter
        )
        assert highlight in filter_obj.qs

    def test_filter_by_keyword_in_text(self, matter, highlight):
        queryset = Highlight.objects.filter(document__matter=matter)
        filter_obj = HighlightsFilter(
            {"keyword": "highlighted"}, queryset=queryset, matter=matter
        )
        assert highlight in filter_obj.qs

    def test_filter_by_keyword_no_match(self, matter, highlight):
        queryset = Highlight.objects.filter(document__matter=matter)
        filter_obj = HighlightsFilter(
            {"keyword": "nonexistent"}, queryset=queryset, matter=matter
        )
        assert highlight not in filter_obj.qs

    def test_filter_by_document(self, matter, document, highlight):
        queryset = Highlight.objects.filter(document__matter=matter)
        filter_obj = HighlightsFilter(
            {"document": document.id}, queryset=queryset, matter=matter
        )
        assert highlight in filter_obj.qs

    def test_filter_by_importance(self, matter, highlight):
        queryset = Highlight.objects.filter(document__matter=matter)
        filter_obj = HighlightsFilter(
            {"importance": "5"}, queryset=queryset, matter=matter
        )
        assert highlight in filter_obj.qs

    def test_filter_by_label(self, matter, highlight, label):
        highlight.labels.add(label)
        queryset = Highlight.objects.filter(document__matter=matter)
        filter_obj = HighlightsFilter(
            {"label": label.id}, queryset=queryset, matter=matter
        )
        assert highlight in filter_obj.qs

    def test_order_by_slug(self, matter, highlight):
        queryset = Highlight.objects.filter(document__matter=matter)
        filter_obj = HighlightsFilter(
            {"order_by": "slug"}, queryset=queryset, matter=matter
        )
        assert list(filter_obj.qs) == list(queryset.order_by("slug"))

    def test_document_queryset_filtered(self, matter, document):
        queryset = Highlight.objects.filter(document__matter=matter)
        filter_obj = HighlightsFilter({}, queryset=queryset, matter=matter)
        assert document in filter_obj.filters["document"].queryset


class TestFactsFilter:
    def test_filter_by_keyword(self, matter, fact):
        queryset = Fact.objects.filter(matter=matter)
        filter_obj = FactsFilter(
            {"keyword": "Important"}, queryset=queryset, matter=matter
        )
        assert fact in filter_obj.qs

    def test_filter_by_keyword_no_match(self, matter, fact):
        queryset = Fact.objects.filter(matter=matter)
        filter_obj = FactsFilter(
            {"keyword": "nonexistent"}, queryset=queryset, matter=matter
        )
        assert fact not in filter_obj.qs

    def test_filter_by_date_start(self, matter, fact):
        queryset = Fact.objects.filter(matter=matter)
        filter_obj = FactsFilter(
            {"date_start": "2024-01-01"}, queryset=queryset, matter=matter
        )
        assert fact in filter_obj.qs

    def test_filter_by_date_end(self, matter, fact):
        queryset = Fact.objects.filter(matter=matter)
        filter_obj = FactsFilter(
            {"date_end": "2024-12-31"}, queryset=queryset, matter=matter
        )
        assert fact in filter_obj.qs

    def test_filter_by_importance(self, matter, fact):
        queryset = Fact.objects.filter(matter=matter)
        filter_obj = FactsFilter({"importance": "5"}, queryset=queryset, matter=matter)
        assert fact in filter_obj.qs

    def test_filter_by_label(self, matter, fact, label):
        fact.labels.add(label)
        queryset = Fact.objects.filter(matter=matter)
        filter_obj = FactsFilter({"label": label.id}, queryset=queryset, matter=matter)
        assert fact in filter_obj.qs

    def test_order_by_description(self, matter, fact):
        queryset = Fact.objects.filter(matter=matter)
        filter_obj = FactsFilter(
            {"order_by": "description"}, queryset=queryset, matter=matter
        )
        assert list(filter_obj.qs) == list(queryset.order_by("description"))

    def test_label_queryset_filtered(self, matter, label):
        queryset = Fact.objects.filter(matter=matter)
        filter_obj = FactsFilter({}, queryset=queryset, matter=matter)
        assert label in filter_obj.filters["label"].queryset
