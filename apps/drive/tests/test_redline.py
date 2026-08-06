"""Tests for the UNO redline applier (apps/drive/redline.py).

Most tests drive a real headless LibreOffice and are skipped when it (or
python3-uno) is not installed: apt-get install libreoffice-writer-nogui
python3-uno. Sample drafts are built with odfpy so no binary fixtures are
checked in.
"""

import zipfile

import pytest

from apps.drive import convert, redline
from apps.drive.redline import (
    AppliedEdit,
    DeleteParagraph,
    InsertParagraphs,
    RedlineEdit,
    RedlineError,
)

needs_uno = pytest.mark.skipif(
    not redline.is_available(),
    reason="LibreOffice + python3-uno required "
    "(apt-get install libreoffice-writer-nogui python3-uno)",
)

OLD_CLAIM = "upon which relief can be granted"
NEW_CLAIM = "entitling Plaintiff to any relief"
BOLD_RUN = "Standard of Review."
DUPLICATED = "The motion is fully briefed."
DELETABLE = "This sentence will be deleted entirely."


def _sample_draft(path):
    """A small motion with a heading, a bold run, and a duplicated phrase."""
    from odf.opendocument import OpenDocumentText
    from odf.style import Style, TextProperties
    from odf.text import H, P, Span

    doc = OpenDocumentText()
    bold = Style(name="TBold", family="text")
    bold.addElement(TextProperties(fontweight="bold"))
    doc.automaticstyles.addElement(bold)

    doc.text.addElement(H(outlinelevel=1, text="MOTION TO DISMISS"))
    doc.text.addElement(P(text=f"Plaintiff has failed to state a claim {OLD_CLAIM}."))
    paragraph = P()
    paragraph.addElement(Span(stylename=bold, text=BOLD_RUN))
    paragraph.addText(" The court accepts all well-pleaded facts as true.")
    doc.text.addElement(paragraph)
    doc.text.addElement(P(text=f"{DUPLICATED} {DUPLICATED}"))
    doc.text.addElement(P(text=DELETABLE))
    doc.save(str(path))
    return path


@pytest.fixture
def draft(tmp_path):
    return _sample_draft(tmp_path / "motion.odt")


def _content_xml(path) -> str:
    with zipfile.ZipFile(path) as archive:
        return archive.read("content.xml").decode("utf-8")


def _markdown(path) -> str:
    return convert.to_markdown(path.read_bytes(), ".odt")


# --------------------------------------------------------------------------- #
# Validation — no LibreOffice needed
# --------------------------------------------------------------------------- #
class TestValidation:
    def test_missing_source(self, tmp_path):
        with pytest.raises(RedlineError, match="not found"):
            redline.apply_redline_edits(
                tmp_path / "nope.odt", [RedlineEdit(old="a", new="b")]
            )

    def test_empty_edit_list(self, draft):
        with pytest.raises(RedlineError, match="no edits"):
            redline.apply_redline_edits(draft, [])

    def test_empty_old_text(self, draft):
        with pytest.raises(RedlineError, match="empty old"):
            redline.apply_redline_edits(draft, [RedlineEdit(old="", new="b")])

    def test_noop_edit(self, draft):
        with pytest.raises(RedlineError, match="changes nothing"):
            redline.apply_redline_edits(draft, [RedlineEdit(old="a", new="a")])

    def test_structural_op_validation(self, draft):
        with pytest.raises(RedlineError, match="empty text"):
            redline.apply_redline_edits(draft, [DeleteParagraph(text="")])
        with pytest.raises(RedlineError, match="anchor and at least one"):
            redline.apply_redline_edits(
                draft, [InsertParagraphs(anchor="x", paragraphs=[])]
            )
        with pytest.raises(RedlineError, match="not contain newlines"):
            redline.apply_redline_edits(
                draft,
                [InsertParagraphs(anchor="x", paragraphs=["one\ntwo"])],
            )

    def test_occurrence_validation(self, draft):
        with pytest.raises(RedlineError, match="positive integer"):
            redline.apply_redline_edits(
                draft, [RedlineEdit(old="a", new="b", occurrence=0)]
            )
        with pytest.raises(RedlineError, match="positive integer"):
            redline.apply_redline_edits(
                draft, [DeleteParagraph(text="a", occurrence=-1)]
            )
        with pytest.raises(RedlineError, match="mutually exclusive"):
            redline.apply_redline_edits(
                draft,
                [RedlineEdit(old="a", new="b", replace_all=True, occurrence=1)],
            )

    def test_newlines_rejected(self, draft):
        with pytest.raises(RedlineError, match="one paragraph") as excinfo:
            redline.apply_redline_edits(
                draft,
                [
                    RedlineEdit(old=DELETABLE, new="fine"),
                    RedlineEdit(old="one\ntwo", new="three"),
                ],
            )
        assert excinfo.value.edit_index == 1


# --------------------------------------------------------------------------- #
# Real LibreOffice
# --------------------------------------------------------------------------- #
@needs_uno
class TestApply:
    def test_edit_becomes_tracked_change(self, draft, tmp_path):
        out = tmp_path / "motion.redline.odt"
        original = draft.read_bytes()

        applied = redline.apply_redline_edits(
            draft, [RedlineEdit(old=OLD_CLAIM, new=NEW_CLAIM)], output_path=out
        )

        assert applied == [
            AppliedEdit(edit=RedlineEdit(old=OLD_CLAIM, new=NEW_CLAIM), replacements=1)
        ]
        # output_path mode leaves the source untouched.
        assert draft.read_bytes() == original

        xml = _content_xml(out)
        # A genuine ODF tracked change, attributed to the default author, with
        # the deleted text preserved in the change region for accept/reject.
        assert "tracked-changes" in xml
        assert "Kosmos AI" in xml
        assert NEW_CLAIM in xml
        assert OLD_CLAIM in xml

        # The "accepted" reading of the document shows only the new text.
        markdown = _markdown(out)
        assert NEW_CLAIM in markdown
        assert OLD_CLAIM not in markdown
        # Untouched content survives, including the bold run.
        assert "MOTION TO DISMISS" in markdown
        assert BOLD_RUN in markdown
        assert 'font-weight="bold"' in xml

    def test_pdf_export_alongside_edits(self, draft, tmp_path):
        pdf = tmp_path / "motion.pdf"
        redline.apply_redline_edits(
            draft, [RedlineEdit(old=OLD_CLAIM, new=NEW_CLAIM)], pdf_path=pdf
        )
        assert pdf.read_bytes()[:5] == b"%PDF-"

    def test_export_pdf_without_edits(self, draft, tmp_path):
        pdf = tmp_path / "v0.pdf"
        original = draft.read_bytes()
        redline.export_pdf(draft, pdf)
        assert pdf.read_bytes()[:5] == b"%PDF-"
        assert draft.read_bytes() == original

    def test_in_place_multiple_edits_and_deletion(self, draft):
        applied = redline.apply_redline_edits(
            draft,
            [
                RedlineEdit(
                    old="accepts all well-pleaded facts as true",
                    new="must accept all well-pleaded facts as true",
                ),
                RedlineEdit(old=DELETABLE, new=""),
            ],
            author="James Craig",
        )

        assert [item.replacements for item in applied] == [1, 1]
        xml = _content_xml(draft)
        assert "tracked-changes" in xml
        assert "James Craig" in xml

        markdown = _markdown(draft)
        assert "must accept all well-pleaded facts" in markdown
        assert DELETABLE not in markdown

    def test_accept_all_changes_produces_clean_copy(self, draft, tmp_path):
        redline.apply_redline_edits(draft, [RedlineEdit(old=OLD_CLAIM, new=NEW_CLAIM)])
        assert "tracked-changes" in _content_xml(draft)

        clean = tmp_path / "clean.odt"
        pdf = tmp_path / "clean.pdf"
        redline.accept_all_changes(draft, clean, pdf)

        xml = _content_xml(clean)
        # No redline structures survive; the deleted text is really gone.
        assert "tracked-changes" not in xml
        assert "changed-region" not in xml
        assert OLD_CLAIM not in xml
        assert NEW_CLAIM in xml
        assert pdf.read_bytes()[:5] == b"%PDF-"
        # The redlined source itself is untouched.
        assert "tracked-changes" in _content_xml(draft)

    def test_structural_ops_track_and_apply(self, draft):
        applied = redline.apply_redline_edits(
            draft,
            [
                DeleteParagraph(text="will be deleted"),
                InsertParagraphs(
                    anchor="upon which relief can be granted",
                    paragraphs=[
                        "The deposit here fails that test.",
                        "Enforcement is therefore barred.",
                    ],
                ),
            ],
        )
        assert [item.replacements for item in applied] == [1, 1]

        xml = _content_xml(draft)
        assert "tracked-changes" in xml

        markdown = _markdown(draft)
        # Accepted view: the paragraph is gone, the new ones follow the anchor.
        assert DELETABLE not in markdown
        claim = markdown.index(OLD_CLAIM)
        first = markdown.index("The deposit here fails that test.")
        second = markdown.index("Enforcement is therefore barred.")
        assert claim < first < second
        assert second < markdown.index(BOLD_RUN.rstrip("."))

    def test_ambiguous_paragraph_needle_fails(self, draft):
        original = draft.read_bytes()
        with pytest.raises(RedlineError, match="paragraphs contain"):
            redline.apply_redline_edits(draft, [DeleteParagraph(text="The")])
        assert draft.read_bytes() == original

    def test_unmatched_edit_is_atomic(self, draft):
        original = draft.read_bytes()
        with pytest.raises(RedlineError, match="not found") as excinfo:
            redline.apply_redline_edits(
                draft,
                [
                    RedlineEdit(old=DELETABLE, new="kept"),
                    RedlineEdit(old="phrase that appears nowhere", new="x"),
                ],
            )
        assert excinfo.value.edit_index == 1
        # First edit was valid, but nothing may be written on failure.
        assert draft.read_bytes() == original

    def test_occurrence_targets_one_match(self, draft):
        # DUPLICATED appears twice in one paragraph; change only the second.
        applied = redline.apply_redline_edits(
            draft,
            [RedlineEdit(old=DUPLICATED, new="Reply briefing remains.", occurrence=2)],
        )
        assert applied[0].replacements == 1
        markdown = _markdown(draft)
        assert markdown.count(DUPLICATED) == 1
        assert markdown.count("Reply briefing remains.") == 1
        assert markdown.index(DUPLICATED) < markdown.index("Reply briefing remains.")
        assert "tracked-changes" in _content_xml(draft)

    def test_occurrence_out_of_range_is_atomic(self, draft):
        original = draft.read_bytes()
        with pytest.raises(RedlineError, match="only 2 found"):
            redline.apply_redline_edits(
                draft, [RedlineEdit(old=DUPLICATED, new="x", occurrence=3)]
            )
        assert draft.read_bytes() == original

    def test_occurrence_disambiguates_paragraph_ops(self, tmp_path):
        """Identical boilerplate paragraphs (the pleading case): occurrence
        picks which one an insert anchors on."""
        from odf.opendocument import OpenDocumentText
        from odf.text import P

        boiler = "Plaintiff restates and incorporates all previous allegations."
        doc = OpenDocumentText()
        doc.text.addElement(P(text="COUNT 1"))
        doc.text.addElement(P(text=boiler))
        doc.text.addElement(P(text="COUNT 2"))
        doc.text.addElement(P(text=boiler))
        doc.text.addElement(P(text="COUNT 3"))
        doc.text.addElement(P(text=boiler))
        path = tmp_path / "pleading.odt"
        doc.save(str(path))

        with pytest.raises(RedlineError, match="3 paragraphs contain"):
            redline.apply_redline_edits(
                path, [InsertParagraphs(anchor=boiler, paragraphs=["New text."])]
            )

        redline.apply_redline_edits(
            path,
            [
                InsertParagraphs(
                    anchor=boiler, paragraphs=["This is a test 3."], occurrence=2
                )
            ],
        )
        markdown = _markdown(path)
        # The insertion lands after the second boilerplate, before COUNT 3.
        assert (
            markdown.index("COUNT 2")
            < markdown.index("This is a test 3.")
            < markdown.index("COUNT 3")
        )

    def test_ambiguous_edit_requires_replace_all(self, draft):
        original = draft.read_bytes()
        with pytest.raises(RedlineError, match="ambiguous") as excinfo:
            redline.apply_redline_edits(
                draft, [RedlineEdit(old=DUPLICATED, new="Briefing is complete.")]
            )
        assert excinfo.value.edit_index == 0
        assert draft.read_bytes() == original

        applied = redline.apply_redline_edits(
            draft,
            [
                RedlineEdit(
                    old=DUPLICATED, new="Briefing is complete.", replace_all=True
                )
            ],
        )
        assert applied[0].replacements == 2
        markdown = _markdown(draft)
        assert DUPLICATED not in markdown
        assert markdown.count("Briefing is complete.") == 2
