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
      "output": "/path/out.odt",       # always written on success
      "author": "Kosmos AI",           # tracked-change attribution
      "edits": [{"old": ..., "new": ..., "replace_all": false}, ...]
    }

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


def _apply_edits(doc, edits):
    results = []
    for index, edit in enumerate(edits):
        old, new = edit["old"], edit["new"]

        finder = doc.createSearchDescriptor()
        finder.SearchString = old
        finder.setPropertyValue("SearchCaseSensitive", True)
        finder.setPropertyValue("SearchRegularExpression", False)
        matches = doc.findAll(finder).Count
        if matches == 0:
            raise DriverError(f"text not found in draft: {old[:120]!r}", index)
        if matches > 1 and not edit.get("replace_all"):
            raise DriverError(
                f"ambiguous edit: {matches} occurrences of {old[:120]!r} "
                "(set replace_all to change every occurrence)",
                index,
            )

        replacer = doc.createReplaceDescriptor()
        replacer.SearchString = old
        replacer.ReplaceString = new
        replacer.setPropertyValue("SearchCaseSensitive", True)
        replacer.setPropertyValue("SearchRegularExpression", False)
        replaced = doc.replaceAll(replacer)
        if replaced != matches:
            raise DriverError(
                f"expected {matches} replacement(s), made {replaced}", index
            )
        results.append({"replacements": replaced})
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

        doc.setPropertyValue("RecordChanges", True)
        if not doc.getPropertyValue("RecordChanges"):
            raise DriverError(
                "change recording could not be enabled (is the document's "
                "tracked-changes protection on?)"
            )

        results = _apply_edits(doc, job["edits"])

        doc.storeToURL(
            _file_url(job["output"]),
            (_prop("FilterName", "writer8"), _prop("Overwrite", True)),
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
