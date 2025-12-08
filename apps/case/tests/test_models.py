import pytest

from apps.case.abbreviate import bluebook_abbreviate
from apps.case.models import Label

pytestmark = pytest.mark.django_db


# -----------------------------------------------------
# Label model tests
# -----------------------------------------------------
class TestLabel:
    def test_str(self, label):
        assert str(label) == "Important"

    def test_content(self, label, matter):
        assert label.name == "Important"
        assert label.color == "red"
        assert label.matter == matter

    def test_is_global_false(self, label):
        assert label.is_global is False

    def test_is_global_true(self, global_label):
        assert global_label.is_global is True

    def test_unique_constraint(self, matter):
        """Labels must have unique names within a matter."""
        Label.objects.create(matter=matter, name="Unique", color="blue")
        with pytest.raises(Exception):  # IntegrityError
            Label.objects.create(matter=matter, name="Unique", color="red")


# -----------------------------------------------------
# Document model tests
# -----------------------------------------------------
class TestDocument:
    def test_str(self, document):
        assert str(document) == "Test Document"

    def test_content(self, document, matter, user):
        assert document.name == "Test Document"
        assert document.description == "A test document"
        assert document.category == "Evidence"
        assert document.matter == matter
        assert document.uploaded_by == user

    def test_citation_auto_generated(self, document):
        """Citation should use bluebook abbreviation when no manual override."""
        document.name = "Plaintiff's Motion for Summary Judgment"
        document.abbreviated_name = None
        document.save()
        # Should end with period and be in parentheses
        assert document.citation.startswith("(")
        assert document.citation.endswith(")")

    def test_citation_manual_override(self, document):
        """Citation should use abbreviated_name when provided."""
        document.abbreviated_name = "Custom Abbrev"
        document.save()
        assert document.citation == "(Custom Abbrev.)"

    def test_citation_no_double_period(self, document):
        """Citation should not have double periods."""
        document.abbreviated_name = "Already Has Period."
        document.save()
        assert document.citation == "(Already Has Period.)"

    def test_category_set_to_record_when_proceeding(self, document, proceeding):
        """Category should be set to Record when proceeding is assigned."""
        document.category = "Evidence"
        document.proceeding = proceeding
        document.save()
        assert document.category == "Record"

    def test_importance_default(self, document):
        assert document.importance == 5

    def test_labels_relationship(self, document, label):
        document.labels.add(label)
        assert label in document.labels.all()


# -----------------------------------------------------
# Highlight model tests
# -----------------------------------------------------
class TestHighlight:
    def test_str(self, highlight):
        assert str(highlight) == "Test Highlight - Page 1"

    def test_content(self, highlight, document, user):
        assert highlight.slug == "Test Highlight"
        assert highlight.document == document
        assert highlight.page_number == 1
        assert highlight.paragraph_number == "5"
        assert highlight.color == "yellow"
        assert highlight.created_by == user

    def test_citation_with_paragraph(self, highlight):
        """Citation should include paragraph symbol when paragraph_number set."""
        citation = highlight.citation
        assert "¶ 5" in citation

    def test_citation_without_paragraph(self, highlight):
        """Citation should use 'at [page]' when no paragraph_number."""
        highlight.paragraph_number = None
        highlight.save()
        citation = highlight.citation
        assert "at 1" in citation

    def test_citation_preserves_abbreviation_period(self, highlight):
        """Citation should preserve the period after abbreviated words."""
        highlight.paragraph_number = None
        highlight.save()
        citation = highlight.citation
        # Should be "(Abbrev. at 1.)" not "(Abbrev at 1.)"
        assert ". at " in citation

    def test_importance_default(self, highlight):
        assert highlight.importance == 5

    def test_labels_relationship(self, highlight, label):
        highlight.labels.add(label)
        assert label in highlight.labels.all()

    def test_coordinates_json(self, highlight):
        """Coordinates should be stored as JSON."""
        assert "rects" in highlight.coordinates
        assert len(highlight.coordinates["rects"]) == 1


# -----------------------------------------------------
# Fact model tests
# -----------------------------------------------------
class TestFact:
    def test_str(self, fact):
        assert str(fact) == "Important event occurred"

    def test_content(self, fact, user, matter):
        assert fact.description == "Important event occurred"
        assert fact.user == user
        assert fact.matter == matter
        assert str(fact.date) == "2024-01-25"

    def test_importance_default(self, fact):
        assert fact.importance == 5

    def test_documents_relationship(self, fact, document):
        fact.documents.add(document)
        assert document in fact.documents.all()

    def test_highlights_relationship(self, fact, highlight):
        fact.highlights.add(highlight)
        assert highlight in fact.highlights.all()

    def test_labels_relationship(self, fact, label):
        fact.labels.add(label)
        assert label in fact.labels.all()


# -----------------------------------------------------
# Abbreviation function tests
# -----------------------------------------------------
class TestBluebookAbbreviate:
    def test_motion_abbreviation(self):
        result = bluebook_abbreviate("Motion for Summary Judgment")
        assert "Mot." in result
        assert "Summ." in result
        assert "J." in result

    def test_plaintiffs_possessive(self):
        result = bluebook_abbreviate("Plaintiff's Motion")
        assert "Pl's" in result
        assert "Mot." in result

    def test_defendants_possessive(self):
        result = bluebook_abbreviate("Defendant's Response")
        assert "Def's" in result
        assert "Resp." in result

    def test_and_is_omitted(self):
        """'and' is omitted from abbreviated titles."""
        result = bluebook_abbreviate("Motion and Brief")
        assert "and" not in result.lower()
        assert "Mot." in result
        assert "Br." in result

    def test_short_words_omitted(self):
        result = bluebook_abbreviate("Motion for the Summary of Judgment")
        # 'for', 'the', 'of' should be omitted
        assert " for " not in result.lower()
        assert " the " not in result.lower()
        assert " of " not in result.lower()

    def test_deposition_abbreviation(self):
        result = bluebook_abbreviate("Deposition of John Smith")
        assert "Dep." in result

    def test_exhibit_abbreviation(self):
        result = bluebook_abbreviate("Exhibit A")
        assert "Ex." in result

    def test_memorandum_abbreviation(self):
        result = bluebook_abbreviate("Memorandum of Law")
        assert "Mem." in result
        assert "L." in result

    def test_long_word_abbreviated(self):
        """Words 8+ letters not in map should be abbreviated to 3 letters."""
        result = bluebook_abbreviate("Confidential Document")
        # "Confidential" is 12 letters, should become "Con."
        assert "Con." in result
