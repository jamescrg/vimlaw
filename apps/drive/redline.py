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

Edits are single-paragraph by design (v1): old/new must not contain newlines.
Restructuring — renumbering, reordering, table surgery — stays manual until
the simple case is proven.
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
    """One plain-text replacement; empty ``new`` is a pure deletion."""

    old: str
    new: str
    replace_all: bool = False


@dataclass(frozen=True)
class AppliedEdit:
    edit: RedlineEdit
    replacements: int


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


def _validate(edits):
    if not edits:
        raise RedlineError("no edits to apply")
    for index, edit in enumerate(edits):
        if not edit.old:
            raise RedlineError("edit has empty old text", index)
        if edit.old == edit.new:
            raise RedlineError(
                "edit changes nothing (old and new are identical)", index
            )
        if any("\n" in text or "\r" in text for text in (edit.old, edit.new)):
            raise RedlineError(
                "edits must stay within one paragraph (no newlines); split a "
                "multi-paragraph change into one edit per paragraph",
                index,
            )


def apply_redline_edits(
    source_path,
    edits,
    *,
    author=DEFAULT_AUTHOR,
    output_path=None,
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

    spec_fd, spec_path = tempfile.mkstemp(prefix="redline-job-", suffix=".json")
    try:
        with os.fdopen(spec_fd, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "soffice": settings.SOFFICE_BIN,
                    "source": str(source),
                    "output": output,
                    "author": author,
                    "edits": [
                        {"old": e.old, "new": e.new, "replace_all": e.replace_all}
                        for e in edits
                    ],
                },
                handle,
            )

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

        applied = [
            AppliedEdit(edit=edit, replacements=item["replacements"])
            for edit, item in zip(edits, result["edits"])
        ]
        if in_place:
            os.replace(output, source)
        logger.info(
            "applied %d redline edit(s) to %s (author=%s, in_place=%s)",
            len(applied),
            source,
            author,
            in_place,
        )
        return applied
    finally:
        os.unlink(spec_path)
        if in_place and os.path.exists(output):
            os.unlink(output)


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
