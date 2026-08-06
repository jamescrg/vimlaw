"""Standalone UNO driver: apply tracked-change edits to an ODT file.

This script is executed by settings.UNO_PYTHON (normally /usr/bin/python3 with
the python3-uno system package) — never imported by Django code, because the
project venv has no UNO bindings. The public entry point is
apps.drive.redline.apply_redline_edits, which spawns this script.

Usage: python3 uno_driver.py <job.json>

Job spec:
    {
      "soffice": "soffice",            # binary to launch
      "source": "/path/draft.odt",     # never modified by this script
      "output": "/path/out.odt",       # ODT written on success (optional)
      "pdf": "/path/out.pdf",          # PDF export of the result (optional)
      "author": "Kosmos AI",           # tracked-change attribution
      "edits": [
        {"op": "replace", "old": ..., "new": ..., "replace_all": false},
        {"op": "delete_paragraph", "text": ...},
        {"op": "insert_after", "anchor": ..., "paragraphs": [...]}
      ]
    }

"op" defaults to "replace". delete_paragraph/insert_after locate the single
body paragraph containing their quote (ambiguity is an error) and edit via
text cursors, so LibreOffice records them as tracked paragraph deletions/
insertions like any other change.

With "edits": [] the document is only re-exported (used for a session's
version 0 PDF); at least one of "output"/"pdf" must be set. With
"accept_changes": true, every tracked change is accepted after the edits
are applied and before saving, yielding a clean document (used by
accept-and-publish). The PDF is
exported while the document is still open, so it costs no extra soffice
start, and — because change display is on — it shows the redlines exactly
as LibreOffice would print them.

The script launches a throwaway headless soffice with its own user profile
(concurrency-safe, no profile-lock contention), enables change recording, and
applies each edit as a plain-text find/replace — LibreOffice itself records
the tracked insertions/deletions. Edits are validated before application: an
edit whose old text is absent, or ambiguous without replace_all, aborts the
job before anything is written.

Prints one JSON object to stdout:
    {"ok": true, "edits": [{"replacements": 1}, ...]}
    {"ok": false, "error": "...", "edit_index": 2}   # edit_index may be null
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import uuid

SOFFICE_START_TIMEOUT = 60  # seconds to wait for the UNO pipe to come up


class DriverError(Exception):
    def __init__(self, message, edit_index=None):
        super().__init__(message)
        self.edit_index = edit_index


def _file_url(path):
    import uno

    return uno.systemPathToFileUrl(os.path.abspath(path))


def _prop(name, value):
    from com.sun.star.beans import PropertyValue

    prop = PropertyValue()
    prop.Name = name
    prop.Value = value
    return prop


def _connect(pipe_name):
    """Resolve the remote component context, retrying while soffice boots."""
    import uno
    from com.sun.star.connection import NoConnectException

    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local
    )
    url = f"uno:pipe,name={pipe_name};urp;StarOffice.ComponentContext"
    deadline = time.monotonic() + SOFFICE_START_TIMEOUT
    while True:
        try:
            return resolver.resolve(url)
        except NoConnectException:
            if time.monotonic() > deadline:
                raise DriverError(
                    "timed out waiting for soffice to accept UNO connections"
                )
            time.sleep(0.25)


def _set_author(ctx, author):
    """Set the user profile name; LibreOffice attributes tracked changes to it."""
    provider = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.configuration.ConfigurationProvider", ctx
    )
    access = provider.createInstanceWithArguments(
        "com.sun.star.configuration.ConfigurationUpdateAccess",
        (_prop("nodepath", "/org.openoffice.UserProfile/Data"),),
    )
    access.setPropertyValue("givenname", author)
    access.setPropertyValue("sn", "")
    access.commitChanges()


def _apply_replace(doc, edit, index):
    old, new = edit["old"], edit["new"]
    occurrence = edit.get("occurrence")

    finder = doc.createSearchDescriptor()
    finder.SearchString = old
    finder.setPropertyValue("SearchCaseSensitive", True)
    finder.setPropertyValue("SearchRegularExpression", False)
    found = doc.findAll(finder)
    matches = found.Count
    if matches == 0:
        raise DriverError(f"text not found in draft: {old[:120]!r}", index)

    if occurrence:
        if occurrence > matches:
            raise DriverError(
                f"occurrence {occurrence} of {old[:120]!r} requested but only "
                f"{matches} found",
                index,
            )
        target = found.getByIndex(occurrence - 1)
        cursor = target.getText().createTextCursorByRange(target)
        # insertString over a selection replaces it; recorded as a tracked
        # delete+insert like replaceAll's changes.
        target.getText().insertString(cursor, new, True)
        return 1

    if matches > 1 and not edit.get("replace_all"):
        raise DriverError(
            f"ambiguous edit: {matches} occurrences of {old[:120]!r} "
            "(set occurrence to pick one, or replace_all to change every one)",
            index,
        )

    replacer = doc.createReplaceDescriptor()
    replacer.SearchString = old
    replacer.ReplaceString = new
    replacer.setPropertyValue("SearchCaseSensitive", True)
    replacer.setPropertyValue("SearchRegularExpression", False)
    replaced = doc.replaceAll(replacer)
    if replaced != matches:
        raise DriverError(f"expected {matches} replacement(s), made {replaced}", index)
    return replaced


def _find_paragraph(doc, needle, index, occurrence=None):
    """The body paragraph containing ``needle`` (tables are skipped).

    Requires a unique match unless ``occurrence`` picks the Nth (1-based).
    """
    matches = []
    enum = doc.getText().createEnumeration()
    while enum.hasMoreElements():
        par = enum.nextElement()
        if par.supportsService("com.sun.star.text.Paragraph") and needle in (
            par.getString()
        ):
            matches.append(par)
    if not matches:
        raise DriverError(f"no paragraph contains: {needle[:120]!r}", index)
    if occurrence:
        if occurrence > len(matches):
            raise DriverError(
                f"occurrence {occurrence} requested but only {len(matches)} "
                f"paragraphs contain {needle[:120]!r}",
                index,
            )
        return matches[occurrence - 1]
    if len(matches) > 1:
        raise DriverError(
            f"ambiguous: {len(matches)} paragraphs contain {needle[:120]!r} "
            "(quote more of the paragraph, or set occurrence to pick one)",
            index,
        )
    return matches[0]


def _apply_delete_paragraph(doc, edit, index):
    par = _find_paragraph(doc, edit["text"], index, edit.get("occurrence"))
    text = doc.getText()
    cursor = text.createTextCursorByRange(par.getStart())
    cursor.gotoEndOfParagraph(True)
    # Swallow the paragraph mark too (False at document end: text-only delete
    # there, which is still the right outcome for a final paragraph).
    cursor.goRight(1, True)
    text.insertString(cursor, "", True)


def _apply_insert_after(doc, edit, index):
    from com.sun.star.text.ControlCharacter import PARAGRAPH_BREAK

    par = _find_paragraph(doc, edit["anchor"], index, edit.get("occurrence"))
    text = doc.getText()
    cursor = text.createTextCursorByRange(par.getEnd())
    for ptext in edit["paragraphs"]:
        text.insertControlCharacter(cursor, PARAGRAPH_BREAK, False)
        text.insertString(cursor, ptext, False)


def _apply_edits(doc, edits):
    results = []
    for index, edit in enumerate(edits):
        op = edit.get("op", "replace")
        if op == "replace":
            replaced = _apply_replace(doc, edit, index)
        elif op == "delete_paragraph":
            _apply_delete_paragraph(doc, edit, index)
            replaced = 1
        elif op == "insert_after":
            _apply_insert_after(doc, edit, index)
            replaced = 1
        else:
            raise DriverError(f"unknown edit op: {op!r}", index)
        results.append({"op": op, "replacements": replaced})
    return results


def run(job):
    pipe_name = "kosmos_redline_" + uuid.uuid4().hex
    profile_dir = tempfile.mkdtemp(prefix="kosmos-uno-")
    proc = subprocess.Popen(
        [
            job.get("soffice", "soffice"),
            "--headless",
            "--invisible",
            "--nologo",
            "--norestore",
            "--nodefault",
            "--nolockcheck",
            f"-env:UserInstallation=file://{profile_dir}",
            f"--accept=pipe,name={pipe_name};urp;",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    desktop = None
    doc = None
    try:
        ctx = _connect(pipe_name)
        _set_author(ctx, job.get("author") or "Kosmos AI")
        desktop = ctx.ServiceManager.createInstanceWithContext(
            "com.sun.star.frame.Desktop", ctx
        )
        doc = desktop.loadComponentFromURL(
            _file_url(job["source"]), "_blank", 0, (_prop("Hidden", True),)
        )
        if doc is None:
            raise DriverError(f"soffice could not open {job['source']}")

        results = []
        if job["edits"]:
            doc.setPropertyValue("RecordChanges", True)
            if not doc.getPropertyValue("RecordChanges"):
                raise DriverError(
                    "change recording could not be enabled (is the document's "
                    "tracked-changes protection on?)"
                )
            results = _apply_edits(doc, job["edits"])

        if job.get("accept_changes"):
            # Recording off first so acceptance itself isn't tracked, then
            # accept every redline in the document.
            doc.setPropertyValue("RecordChanges", False)
            dispatcher = ctx.ServiceManager.createInstanceWithContext(
                "com.sun.star.frame.DispatchHelper", ctx
            )
            frame = doc.getCurrentController().getFrame()
            dispatcher.executeDispatch(frame, ".uno:AcceptAllTrackedChanges", "", 0, ())

        if job.get("output"):
            doc.storeToURL(
                _file_url(job["output"]),
                (_prop("FilterName", "writer8"), _prop("Overwrite", True)),
            )
        if job.get("pdf"):
            doc.storeToURL(
                _file_url(job["pdf"]),
                (_prop("FilterName", "writer_pdf_Export"), _prop("Overwrite", True)),
            )
        return {"ok": True, "edits": results}
    finally:
        try:
            if doc is not None:
                doc.close(False)
        except Exception:
            pass
        try:
            if desktop is not None:
                desktop.terminate()
        except Exception:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(profile_dir, ignore_errors=True)


def main():
    try:
        import uno  # noqa: F401
    except ImportError:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "this interpreter has no UNO bindings "
                    "(apt-get install python3-uno, or point settings.UNO_PYTHON "
                    "at a python that has them)",
                    "edit_index": None,
                }
            )
        )
        return 1

    with open(sys.argv[1], encoding="utf-8") as handle:
        job = json.load(handle)
    try:
        result = run(job)
    except DriverError as exc:
        result = {"ok": False, "error": str(exc), "edit_index": exc.edit_index}
    except Exception as exc:
        traceback.print_exc()
        result = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "edit_index": None,
        }
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
