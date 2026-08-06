"""Kosmos Drafting Companion: AI edits land in the open document, live.

Runs inside LibreOffice Writer (installed as an .oxt downloaded from Kosmos,
which bakes the server URL and the user's token into config.json). "Kosmos >
Connect to drafting session" pairs the front document with its active Kosmos
drafting session by filename; a background thread then polls the server
every few seconds, applies queued edit rounds to the live document as
tracked changes attributed to "Kosmos AI", reports each outcome, and pushes
the document back (as ODT bytes) so the AI keeps reading what you see,
including your own hand edits.

The edit operations and their semantics are identical to the server's
headless applier (apps/drive/uno_driver.py): replace, delete_paragraph,
insert_after. A round is wrapped in one undo context; if any edit fails the
whole round is undone, so a round either fully applies or leaves the
document untouched (and it is a single Ctrl+Z for the user either way).
"""

import base64
import json
import os
import tempfile
import threading
import traceback
import urllib.error
import urllib.request

import uno
import unohelper
from com.sun.star.lang import DisposedException
from com.sun.star.task import XJobExecutor

POLL_SECONDS = 2.5
# Poll cycles between document pushes when idle (~30 s), so hand edits keep
# flowing back to the AI's context without a round trip per keystroke.
PUSH_EVERY_CYCLES = 12
HTTP_TIMEOUT = 20
AI_AUTHOR = "Kosmos AI"


class CompanionError(Exception):
    def __init__(self, message, edit_index=None):
        super().__init__(message)
        self.edit_index = edit_index


def _prop(name, value):
    from com.sun.star.beans import PropertyValue

    prop = PropertyValue()
    prop.Name = name
    prop.Value = value
    return prop


def _load_config():
    path = os.path.join(os.path.dirname(__file__), "config.json")
    with open(path, encoding="utf-8") as handle:
        config = json.load(handle)
    return config["server"].rstrip("/"), config["token"]


class Api:
    """Thin JSON client for the Kosmos companion endpoints."""

    def __init__(self, server, token):
        self.base = server + "/case/drafts/companion/api"
        self.token = token

    def _call(self, method, path, payload=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={
                "X-Kosmos-Token": self.token,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))

    def sessions(self):
        return self._call("GET", "/sessions/")["sessions"]

    def hello(self, session_id, odt_b64):
        return self._call("POST", f"/{session_id}/hello/", {"odt_b64": odt_b64})

    def ops(self, session_id):
        return self._call("GET", f"/{session_id}/ops/")

    def result(self, session_id, round_id, payload):
        return self._call("POST", f"/{session_id}/rounds/{round_id}/", payload)


# ---------------------------------------------------------------------------
# Edit application (ported from the server's uno_driver, same semantics)


def _apply_replace(doc, edit, index):
    old, new = edit["old"], edit["new"]

    finder = doc.createSearchDescriptor()
    finder.SearchString = old
    finder.setPropertyValue("SearchCaseSensitive", True)
    finder.setPropertyValue("SearchRegularExpression", False)
    matches = doc.findAll(finder).Count
    if matches == 0:
        raise CompanionError(f"text not found in the document: {old[:120]!r}", index)
    if matches > 1 and not edit.get("replace_all"):
        raise CompanionError(
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
        raise CompanionError(
            f"expected {matches} replacement(s), made {replaced}", index
        )
    return replaced


def _find_paragraph(doc, needle, index):
    matches = []
    enum = doc.getText().createEnumeration()
    while enum.hasMoreElements():
        par = enum.nextElement()
        if par.supportsService("com.sun.star.text.Paragraph") and needle in (
            par.getString()
        ):
            matches.append(par)
    if not matches:
        raise CompanionError(f"no paragraph contains: {needle[:120]!r}", index)
    if len(matches) > 1:
        raise CompanionError(
            f"ambiguous: {len(matches)} paragraphs contain {needle[:120]!r} "
            "(quote more of the paragraph)",
            index,
        )
    return matches[0]


def _apply_delete_paragraph(doc, edit, index):
    par = _find_paragraph(doc, edit["text"], index)
    text = doc.getText()
    cursor = text.createTextCursorByRange(par.getStart())
    cursor.gotoEndOfParagraph(True)
    cursor.goRight(1, True)
    text.insertString(cursor, "", True)


def _apply_insert_after(doc, edit, index):
    from com.sun.star.text.ControlCharacter import PARAGRAPH_BREAK

    par = _find_paragraph(doc, edit["anchor"], index)
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
            raise CompanionError(f"unknown edit op: {op!r}", index)
        results.append({"op": op, "replacements": replaced})
    return results


def _set_profile_name(ctx, given, surname):
    """Set the LibreOffice user name (tracked changes are attributed to it)
    and return the previous values so the caller can restore them."""
    provider = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.configuration.ConfigurationProvider", ctx
    )
    access = provider.createInstanceWithArguments(
        "com.sun.star.configuration.ConfigurationUpdateAccess",
        (_prop("nodepath", "/org.openoffice.UserProfile/Data"),),
    )
    previous = (
        access.getPropertyValue("givenname"),
        access.getPropertyValue("sn"),
    )
    access.setPropertyValue("givenname", given)
    access.setPropertyValue("sn", surname)
    access.commitChanges()
    return previous


def _apply_round(ctx, doc, edits):
    """Apply one round atomically: record changes as Kosmos AI, and undo the
    whole round if any edit fails."""
    doc.setPropertyValue("RecordChanges", True)
    if not doc.getPropertyValue("RecordChanges"):
        raise CompanionError(
            "change recording could not be enabled (is the document's "
            "tracked-changes protection on?)"
        )
    previous_name = _set_profile_name(ctx, AI_AUTHOR, "")
    undo = doc.getUndoManager()
    undo.enterUndoContext("Kosmos AI edits")
    try:
        results = _apply_edits(doc, edits)
    except Exception:
        undo.leaveUndoContext()
        try:
            undo.undo()
        except Exception:
            pass
        raise
    else:
        undo.leaveUndoContext()
        return results
    finally:
        try:
            _set_profile_name(ctx, *previous_name)
        except Exception:
            pass


def _export_odt_b64(doc):
    """A writer8 snapshot of the live document, base64-encoded. storeToURL
    saves a copy; the document's path and modified state are untouched."""
    fd, path = tempfile.mkstemp(suffix=".odt", prefix="kosmos-companion-")
    os.close(fd)
    try:
        doc.storeToURL(
            uno.systemPathToFileUrl(path),
            (_prop("FilterName", "writer8"), _prop("Overwrite", True)),
        )
        with open(path, "rb") as handle:
            return base64.b64encode(handle.read()).decode("ascii")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Connection state and poll loop


class _Connection:
    def __init__(self, ctx, api, doc, session):
        self.ctx = ctx
        self.api = api
        self.doc = doc
        self.session = session  # {"id", "name", "matter"}
        self.stop = threading.Event()
        self.last_note = "connected"
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self):
        cycles = 0
        while not self.stop.is_set():
            try:
                data = self.api.ops(self.session["id"])
                if data.get("status") != "drafting":
                    self.last_note = "session was settled in Kosmos"
                    break
                round_ = data.get("round")
                if round_:
                    self._handle_round(round_)
                    cycles = 0
                else:
                    cycles += 1
                    if cycles >= PUSH_EVERY_CYCLES:
                        self.api.hello(self.session["id"], _export_odt_b64(self.doc))
                        cycles = 0
            except DisposedException:
                self.last_note = "document was closed"
                break
            except Exception as exc:
                # Network blip or server hiccup: note it and keep polling.
                self.last_note = f"retrying after error: {exc}"
            self.stop.wait(POLL_SECONDS)

    def _handle_round(self, round_):
        try:
            results = _apply_round(self.ctx, self.doc, round_["edits"])
            payload = {"ok": True, "results": results}
            self.last_note = f"applied {len(results)} edit(s)"
        except CompanionError as exc:
            payload = {"ok": False, "error": str(exc), "edit_index": exc.edit_index}
            self.last_note = f"round failed: {exc}"
        except DisposedException:
            raise
        except Exception as exc:
            traceback.print_exc()
            payload = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "edit_index": None,
            }
            self.last_note = f"round failed: {exc}"
        try:
            payload["odt_b64"] = _export_odt_b64(self.doc)
        except Exception:
            pass
        self.api.result(self.session["id"], round_["id"], payload)


_connection = None
_lock = threading.Lock()


class Companion(unohelper.Base, XJobExecutor):
    def __init__(self, ctx):
        self.ctx = ctx

    # -- UI helpers

    def _desktop(self):
        return self.ctx.ServiceManager.createInstanceWithContext(
            "com.sun.star.frame.Desktop", self.ctx
        )

    def _message(self, text, title="Kosmos Companion"):
        desktop = self._desktop()
        frame = desktop.getCurrentFrame()
        window = frame.getContainerWindow() if frame else None
        if window is None:
            return
        box = window.getToolkit().createMessageBox(
            window,
            uno.Enum("com.sun.star.awt.MessageBoxType", "INFOBOX"),
            1,  # BUTTONS_OK
            title,
            text,
        )
        box.execute()

    # -- Commands (dispatched from the Kosmos menu)

    def trigger(self, command):
        try:
            if command == "connect":
                self._connect()
            elif command == "disconnect":
                self._disconnect(quiet=False)
            elif command == "status":
                self._status()
        except Exception as exc:
            traceback.print_exc()
            self._message(f"Something went wrong: {exc}")

    def _connect(self):
        global _connection
        try:
            server, token = _load_config()
        except Exception:
            self._message(
                "No configuration found. Download the extension from the "
                "Kosmos Drafts tab (Companion button) so it carries your "
                "server address and token, then reinstall it."
            )
            return

        doc = self._desktop().getCurrentComponent()
        if doc is None or not doc.supportsService("com.sun.star.text.TextDocument"):
            self._message("Open the draft document in Writer first.")
            return
        url = doc.getURL()
        if not url:
            self._message(
                "This document has never been saved. Save it into the "
                "matter's Drive folder and start a drafting session for it "
                "in Kosmos first."
            )
            return
        doc_name = os.path.basename(uno.fileUrlToSystemPath(url))

        api = Api(server, token)
        try:
            sessions = api.sessions()
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                self._message(
                    "The server rejected this extension's token. Download a "
                    "fresh copy from the Kosmos Drafts tab and reinstall it."
                )
            else:
                self._message(f"The Kosmos server answered with an error: {exc}")
            return
        except Exception as exc:
            self._message(f"Could not reach the Kosmos server at {server}: {exc}")
            return

        matches = [s for s in sessions if s["name"] == doc_name]
        if not matches:
            self._message(
                f'No active drafting session found for "{doc_name}". Start '
                "one from the matter's Drafts tab in Kosmos, then connect "
                "again."
            )
            return
        session = matches[0]

        with _lock:
            if _connection is not None:
                self._disconnect(quiet=True)
            try:
                doc.setPropertyValue("ShowChanges", True)
            except Exception:
                pass
            api.hello(session["id"], _export_odt_b64(doc))
            _connection = _Connection(self.ctx, api, doc, session)
            _connection.thread.start()

        self._message(
            f'Connected to the drafting session for "{session["name"]}" '
            f"(matter: {session['matter']}). Edits you approve in the Kosmos "
            "drafting window now appear here as tracked changes, and the AI "
            "reads this document as you have it (hand edits included). "
            "Keep the document open; save whenever you are satisfied."
        )

    def _disconnect(self, quiet=False):
        global _connection
        connection = _connection
        _connection = None
        if connection is not None:
            connection.stop.set()
        if not quiet:
            if connection is None:
                self._message("The companion is not connected.")
            else:
                self._message(
                    f'Disconnected from "{connection.session["name"]}". The '
                    "AI falls back to the server's copy of the draft."
                )

    def _status(self):
        connection = _connection
        if connection is None:
            self._message("Not connected. Use Kosmos > Connect to drafting session.")
        elif not connection.thread.is_alive():
            self._message(
                f'The connection to "{connection.session["name"]}" has '
                f"stopped ({connection.last_note}). Connect again to resume."
            )
        else:
            self._message(
                f'Connected to "{connection.session["name"]}" '
                f"(matter: {connection.session['matter']}). "
                f"Last activity: {connection.last_note}."
            )


g_ImplementationHelper = unohelper.ImplementationHelper()
g_ImplementationHelper.addImplementation(
    Companion, "law.kosmos.Companion", ("com.sun.star.task.Job",)
)
