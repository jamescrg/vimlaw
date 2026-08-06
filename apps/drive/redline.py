"""Apply AI-proposed edits to an ODT draft as tracked changes (redlines).

The AI never touches ODT bytes directly: it proposes plain-text old/new
replacements and this module applies them through headless LibreOffice, which
records each one as a native tracked change attributed to the given author.
The reviewer then accepts or rejects the redlines in LibreOffice exactly as
with a human collaborator's edits — untouched text is preserved byte-for-byte,
which is the whole reason to edit natively instead of round-tripping through
pandoc.

LibreOffice is driven over UNO by apps/drive/uno_driver.py, executed under
settings.UNO_PYTHON (normally /usr/bin/python3 with the python3-uno package)
because the project venv has no UNO bindings. Each job launches a throwaway
soffice with its own user profile, so concurrent jobs cannot contend.

Atomicity: the driver only ever writes a fresh output file; in-place edits are
an os.replace() after the whole edit list succeeds. A failed edit (text not
found, or ambiguous without replace_all) means nothing changes on disk.

Three operations: RedlineEdit (plain-text replacement inside one paragraph),
DeleteParagraph (remove a whole paragraph, mark included), and
InsertParagraphs (new paragraphs after an anchor paragraph). No operation's
text may contain newlines; paragraph structure is expressed through the
structural ops, never through embedded line breaks. Table surgery and
reordering stay manual.
"""

import json
import logging
import os
import shutil
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

DRIVER_PATH = Path(__file__).with_name("uno_driver.py")
DEFAULT_AUTHOR = "Kosmos AI"
DEFAULT_TIMEOUT = 180  # seconds; covers soffice cold start plus the edits


class RedlineError(Exception):
    """Raised when a redline job cannot be applied.

    ``edit_index`` is the zero-based index of the offending edit when the
    failure is specific to one (text not found, ambiguous), else None.
    """

    def __init__(self, message, edit_index=None):
        super().__init__(message)
        self.edit_index = edit_index


@dataclass(frozen=True)
class RedlineEdit:
    """One plain-text replacement inside a paragraph; empty ``new`` deletes.

    ``occurrence`` targets the Nth match (1-based, top of document down)
    when ``old`` appears more than once; None requires a unique match
    (unless ``replace_all``).
    """

    old: str
    new: str
    replace_all: bool = False
    occurrence: int | None = None


@dataclass(frozen=True)
class DeleteParagraph:
    """Remove one whole paragraph (its mark included), as a tracked deletion.

    ``text`` is any quote that identifies the paragraph; when several
    paragraphs contain it (pleading boilerplate repeats verbatim),
    ``occurrence`` picks the Nth from the top.
    """

    text: str
    occurrence: int | None = None


@dataclass(frozen=True)
class InsertParagraphs:
    """Insert new paragraphs after an anchor paragraph, as tracked insertions.

    ``anchor`` is any quote that identifies one existing paragraph
    (``occurrence`` disambiguates repeats); ``paragraphs`` is one string per
    new paragraph.
    """

    anchor: str
    paragraphs: tuple
    occurrence: int | None = None

    def __init__(self, anchor, paragraphs, occurrence=None):
        object.__setattr__(self, "anchor", anchor)
        object.__setattr__(self, "paragraphs", tuple(paragraphs))
        object.__setattr__(self, "occurrence", occurrence)


@dataclass(frozen=True)
class AppliedEdit:
    edit: object
    replacements: int


def edit_to_dict(edit):
    """The op's wire form: the driver job entry, also stored on CompanionRound."""
    if isinstance(edit, RedlineEdit):
        data = {
            "op": "replace",
            "old": edit.old,
            "new": edit.new,
            "replace_all": edit.replace_all,
        }
    elif isinstance(edit, DeleteParagraph):
        data = {"op": "delete_paragraph", "text": edit.text}
    elif isinstance(edit, InsertParagraphs):
        data = {
            "op": "insert_after",
            "anchor": edit.anchor,
            "paragraphs": list(edit.paragraphs),
        }
    else:
        raise TypeError(f"not a redline edit: {edit!r}")
    if edit.occurrence is not None:
        data["occurrence"] = edit.occurrence
    return data


@lru_cache(maxsize=1)
def is_available() -> bool:
    """True when the soffice binary and a UNO-capable python are both present."""
    if shutil.which(settings.SOFFICE_BIN) is None:
        return False
    try:
        probe = subprocess.run(
            [settings.UNO_PYTHON, "-c", "import uno"],
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


def _no_newlines(index, *texts):
    if any("\n" in text or "\r" in text for text in texts):
        raise RedlineError(
            "an edit's text must not contain newlines; replacements stay "
            "within one paragraph, and each inserted paragraph is its own "
            "list item",
            index,
        )


def _check_occurrence(index, edit):
    if edit.occurrence is not None and (
        not isinstance(edit.occurrence, int) or edit.occurrence < 1
    ):
        raise RedlineError("occurrence must be a positive integer", index)


def _validate(edits):
    if not edits:
        raise RedlineError("no edits to apply")
    for index, edit in enumerate(edits):
        if isinstance(edit, (RedlineEdit, DeleteParagraph, InsertParagraphs)):
            _check_occurrence(index, edit)
        if isinstance(edit, RedlineEdit):
            if not edit.old:
                raise RedlineError("edit has empty old text", index)
            if edit.old == edit.new:
                raise RedlineError(
                    "edit changes nothing (old and new are identical)", index
                )
            if edit.replace_all and edit.occurrence is not None:
                raise RedlineError(
                    "replace_all and occurrence are mutually exclusive", index
                )
            _no_newlines(index, edit.old, edit.new)
        elif isinstance(edit, DeleteParagraph):
            if not edit.text:
                raise RedlineError("delete_paragraph has empty text", index)
            _no_newlines(index, edit.text)
        elif isinstance(edit, InsertParagraphs):
            if not edit.anchor or not edit.paragraphs:
                raise RedlineError(
                    "insert_after needs an anchor and at least one paragraph",
                    index,
                )
            if not all(edit.paragraphs):
                raise RedlineError("insert_after has an empty paragraph", index)
            _no_newlines(index, edit.anchor, *edit.paragraphs)
        else:
            raise RedlineError(f"not a redline edit: {edit!r}", index)


def apply_redline_edits(
    source_path,
    edits,
    *,
    author=DEFAULT_AUTHOR,
    output_path=None,
    pdf_path=None,
    timeout=DEFAULT_TIMEOUT,
):
    """Apply ``edits`` to the ODT at ``source_path`` as tracked changes.

    Args:
        source_path: the ODT to edit.
        edits: sequence of RedlineEdit. Applied in order; a later edit sees the
            document as earlier ones left it.
        author: tracked-change attribution shown in LibreOffice.
        output_path: write the redlined document here, leaving the source
            untouched (the "new version" mode). None edits in place.
        pdf_path: also export a PDF of the redlined result — rendered with the
            tracked changes shown, while the document is still open (no extra
            soffice start).
        timeout: seconds before the job (including soffice startup) is killed.

    Returns:
        A list of AppliedEdit, one per input edit.

    Raises:
        RedlineError: on validation failure, an unmatched or ambiguous edit,
            timeout, or any LibreOffice-side failure. The source file is never
            modified on failure.
    """
    source = Path(source_path)
    if not source.is_file():
        raise RedlineError(f"source file not found: {source}")
    edits = list(edits)
    _validate(edits)

    in_place = output_path is None
    if in_place:
        # Same directory as the source so os.replace stays on one filesystem.
        fd, output = tempfile.mkstemp(
            dir=source.parent, prefix=f".{source.stem}.", suffix=".redline.odt"
        )
        os.close(fd)
    else:
        output = str(output_path)

    try:
        result = _run_driver(
            {
                "soffice": settings.SOFFICE_BIN,
                "source": str(source),
                "output": output,
                "pdf": str(pdf_path) if pdf_path else None,
                "author": author,
                "edits": [edit_to_dict(e) for e in edits],
            },
            timeout,
        )
        applied = [
            AppliedEdit(edit=edit, replacements=item["replacements"])
            for edit, item in zip(edits, result["edits"])
        ]
        if in_place:
            os.replace(output, source)
        logger.info(
            "applied %d redline edit(s) to %s (author=%s, in_place=%s, pdf=%s)",
            len(applied),
            source,
            author,
            in_place,
            bool(pdf_path),
        )
        return applied
    finally:
        if in_place and os.path.exists(output):
            os.unlink(output)


def accept_all_changes(
    source_path, output_path, pdf_path=None, *, timeout=DEFAULT_TIMEOUT
):
    """Write a clean copy of the ODT with every tracked change accepted.

    Used by accept-and-publish: the redlined source is untouched; the output
    (and optional PDF) contain the settled text with no redline marks.
    """
    source = Path(source_path)
    if not source.is_file():
        raise RedlineError(f"source file not found: {source}")
    _run_driver(
        {
            "soffice": settings.SOFFICE_BIN,
            "source": str(source),
            "output": str(output_path),
            "pdf": str(pdf_path) if pdf_path else None,
            "author": DEFAULT_AUTHOR,
            "edits": [],
            "accept_changes": True,
        },
        timeout,
    )


def export_pdf(source_path, pdf_path, *, timeout=DEFAULT_TIMEOUT):
    """Export the ODT at ``source_path`` to PDF without applying any edits.

    Used for a drafting session's version 0 preview. Existing tracked changes
    in the document are rendered as shown (redline marks), matching how later
    versions' PDFs look.
    """
    source = Path(source_path)
    if not source.is_file():
        raise RedlineError(f"source file not found: {source}")
    _run_driver(
        {
            "soffice": settings.SOFFICE_BIN,
            "source": str(source),
            "output": None,
            "pdf": str(pdf_path),
            "author": DEFAULT_AUTHOR,
            "edits": [],
        },
        timeout,
    )


def _run_driver(job, timeout):
    """Run uno_driver.py with ``job``, returning the parsed result dict."""
    spec_fd, spec_path = tempfile.mkstemp(prefix="redline-job-", suffix=".json")
    try:
        with os.fdopen(spec_fd, "w", encoding="utf-8") as handle:
            json.dump(job, handle)

        # start_new_session makes the driver a process-group leader, so a
        # timeout kill also takes down the soffice it spawned.
        proc = subprocess.Popen(
            [settings.UNO_PYTHON, str(DRIVER_PATH), spec_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            raise RedlineError(f"redline job timed out after {timeout}s")

        result = _parse_result(stdout, stderr)
        if not result.get("ok"):
            raise RedlineError(
                result.get("error", "unknown redline driver failure"),
                result.get("edit_index"),
            )
        return result
    finally:
        os.unlink(spec_path)


def _parse_result(stdout: bytes, stderr: bytes) -> dict:
    """The driver's last stdout line is the JSON result."""
    for line in reversed(stdout.decode("utf-8", errors="replace").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                break
    snippet = stderr.decode("utf-8", errors="replace").strip()[-500:]
    raise RedlineError(f"redline driver produced no result: {snippet or 'no output'}")
