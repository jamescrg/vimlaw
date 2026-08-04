"""Tests for the UNO redline applier (apps/drive/redline.py).

Most tests drive a real headless LibreOffice and are skipped when it (or
python3-uno) is not installed: apt-get install libreoffice-writer-nogui
python3-uno. Sample drafts are built with odfpy so no binary fixtures are
checked in.
"""

import zipfile

import pytest

from apps.drive import convert, redline
from apps.drive.redline import AppliedEdit, RedlineEdit, RedlineError

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
