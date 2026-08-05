"""Draft chat: converse about an ODT draft; edits land as tracked changes.

Reuses the case-chat machinery (Conversation/Message, the cache status
protocol polled by case:ai-status, the shared message templates) with a
drafting system prompt built around the current version's Markdown facsimile.

The AI proposes changes in a ```draft-edits``` fenced block. The worker
applies the block synchronously through the redline applier (a new
DraftVersion with accumulated tracked changes) and replaces the block in the
stored message with a confirmation, or with the failure reason so both the
user and the AI's later turns can see what went wrong. The draft is never
touched silently: a failed round changes nothing.
"""

import json
import logging
import re
import threading

from django.core.cache import cache

from apps.drafts import services
from apps.drive.redline import (
    DeleteParagraph,
    InsertParagraphs,
    RedlineEdit,
    RedlineError,
)

logger = logging.getLogger(__name__)

DRAFT_EDITS_RE = re.compile(r"```draft-edits\s*\n(.*?)```", re.DOTALL)

CHAT_PREAMBLE = """You are collaborating with the firm on a DRAFT document (a work in
progress, not a filed or executed instrument). Help the attorney improve
it: discuss structure and substance, weigh alternative language, and
propose concrete edits when directed. The draft's current text follows
below as a Markdown facsimile of the underlying word-processor file;
tracked changes from earlier rounds are already reflected in it.

Keep replies brief and pointed: answer the question asked, propose the
language discussed, and stop. The attorney will ask when they want depth."""

EDIT_PROTOCOL = """PROPOSING EDITS. Only when the user directs you to change the draft, end
your reply with exactly one fenced block containing a JSON list of
operations, applied in order:

```draft-edits
[{"old": "<exact text now in the draft>", "new": "<replacement text>", "replace_all": false},
 {"op": "delete_paragraph", "text": "<text identifying the paragraph>"},
 {"op": "insert_after", "anchor": "<text identifying an existing paragraph>", "paragraphs": ["<new paragraph>", "<another new paragraph>"]}]
```

The three operations:
- Replace (no "op" key): rewrites text inside ONE paragraph. "old" must
  occur exactly once in the draft (set "replace_all": true to change every
  occurrence); "new" replaces it outright, and an empty "new" deletes just
  that text. Quote only the text that changes plus enough surrounding words
  to be unique.
- "delete_paragraph": removes one whole paragraph, heading or body. "text"
  is any quote found in exactly one paragraph. Removing a section means one
  op for its heading and one per body paragraph.
- "insert_after": adds new paragraphs immediately after the paragraph
  identified by "anchor". Each list item is the full plain text of one new
  paragraph.

Rules:
- The block is applied immediately as tracked changes (redlines), creating
  a new version of the file. Discussing or suggesting a change is NOT
  direction to make it. Never emit the block unprompted.
- All quoted text is PLAIN TEXT exactly as it reads in the draft: strip the
  facsimile's Markdown markers (**, *, #, etc.), which do not exist in the
  underlying file, and never include newlines inside a string.
- Outside the block, summarize the intent of the edits in a sentence or
  two. Do not restate them line by line."""


def build_system_prompt(session, user):
    from apps.case.ai.context import (
        build_request_info,
        format_matter_overview,
        load_legal_prompt,
    )
    from apps.settings.models import Firm

    company = Firm.objects.first()
    jurisdiction = (company.jurisdiction if company else "") or (
        "United States common law"
    )
    current = session.current_version
    facsimile = current.facsimile if current else "(no working copy)"
    seq = current.seq if current else 0
    return "\n".join(
        [
            build_request_info(user),
            load_legal_prompt(jurisdiction),
            "\n---\n",
            CHAT_PREAMBLE,
            "",
            EDIT_PROTOCOL,
            "",
            format_matter_overview(session.matter),
            "",
            f'THE DRAFT: "{session.name}" (version {seq})',
            "",
            facsimile,
        ]
    )


def _parse_edit_block(raw):
    """Parse one block's JSON into redline op objects, or raise ValueError."""
    data = json.loads(raw)
    if not isinstance(data, list) or not data:
        raise ValueError("draft-edits block is not a non-empty list")
    edits = []
    for entry in data:
        if not isinstance(entry, dict):
            raise ValueError("draft-edits entry is not an object")
        op = entry.get("op", "replace")
        if op == "replace":
            if "old" not in entry:
                raise ValueError("replace entry has no 'old'")
            edits.append(
                RedlineEdit(
                    old=str(entry["old"]),
                    new=str(entry.get("new", "")),
                    replace_all=bool(entry.get("replace_all", False)),
                )
            )
        elif op == "delete_paragraph":
            edits.append(DeleteParagraph(text=str(entry.get("text", ""))))
        elif op == "insert_after":
            paragraphs = entry.get("paragraphs")
            if not isinstance(paragraphs, list):
                raise ValueError("insert_after entry has no paragraphs list")
            edits.append(
                InsertParagraphs(
                    anchor=str(entry.get("anchor", "")),
                    paragraphs=[str(p) for p in paragraphs],
                )
            )
        else:
            raise ValueError(f"unknown draft-edits op: {op!r}")
    return edits


def apply_edit_blocks(response_text, session):
    """Apply any draft-edits blocks, replacing each with the outcome text.

    A malformed block is left in place as visible text and changes nothing
    (mirrors the agenda/intake block contract). A valid block that fails to
    apply is replaced with the failure reason; the AI sees that text in the
    conversation history on the next turn and can correct itself.
    """

    def replace(match):
        try:
            edits = _parse_edit_block(match.group(1).strip())
        except (ValueError, TypeError):
            logger.warning("Unparseable draft-edits block left in place")
            return match.group(0)

        try:
            version = services.apply_edit_round(session, edits)
        except RedlineError as exc:
            if exc.edit_index is not None:
                detail = f"edit {exc.edit_index + 1}: {exc}"
            else:
                detail = str(exc)
            return (
                f"**The proposed edits were not applied** ({detail}). "
                "The draft is unchanged."
            )
        except services.DraftError as exc:
            return f"**The proposed edits were not applied** ({exc})."

        count = len(edits)
        plural = "s" if count != 1 else ""
        return (
            f"**Applied {count} edit{plural} as tracked changes "
            f"(version {version.seq}).** The preview has been updated."
        )

    return DRAFT_EDITS_RE.sub(replace, response_text)


def process_draft_chat(conversation_id, session_id, user_id):
    """Background thread body; same cache protocol as process_ai_request so
    the shared case:ai-status polling cycle works unchanged."""
    from django.contrib.auth import get_user_model

    from apps.case.ai.anthropic_client import send_to_claude
    from apps.case.ai.context import build_chat_history
    from apps.case.ai.gemini_client import send_to_gemini_streaming
    from apps.case.ai.models import Conversation
    from apps.case.ai.tasks import CLAUDE_MODELS, GEMINI_MODELS
    from apps.drafts.models import DraftSession

    cache_key = f"ai_status_{conversation_id}"

    def is_cancelled():
        current = cache.get(cache_key)
        return bool(current) and current.get("status") == "cancelled"

    def update_status(status, message):
        if is_cancelled():
            return
        import time as _time

        current = cache.get(cache_key) or {}
        payload = {
            "status": status,
            "message": message,
            "started_at": current.get("started_at", _time.time()),
        }
        cache.set(cache_key, payload, timeout=600)

    try:
        update_status("context", "Reading the draft...")
        session = DraftSession.objects.get(id=session_id)
        conversation = Conversation.objects.get(id=conversation_id)
        user = get_user_model().objects.get(id=user_id)
        system_context = build_system_prompt(session, user)
        chat_history = build_chat_history(conversation)

        update_status("connecting", "Connecting to AI...")
        llm = conversation.llm
        if llm in GEMINI_MODELS:

            def on_thought(thought):
                update_status("thinking", thought[:300])

            response_text, input_tokens, output_tokens = send_to_gemini_streaming(
                system_context,
                chat_history,
                model=GEMINI_MODELS[llm],
                on_thought=on_thought,
                is_cancelled=is_cancelled,
                conversation_id=conversation.id,
            )
        else:
            update_status("generating", "Generating response...")
            response_text, input_tokens, output_tokens = send_to_claude(
                system_context,
                chat_history,
                model=CLAUDE_MODELS.get(llm, "claude-sonnet-4-6"),
                is_cancelled=is_cancelled,
            )

        if is_cancelled():
            return

        if DRAFT_EDITS_RE.search(response_text):
            update_status("applying", "Applying edits to the draft...")
            response_text = apply_edit_blocks(response_text, session)

        cache.set(
            cache_key,
            {
                "status": "complete",
                "message": "Complete",
                "response": response_text,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "citations": [],
            },
            timeout=600,
        )
    except InterruptedError:
        pass
    except Exception as exc:
        logger.exception("Draft chat request failed")
        if not is_cancelled():
            cache.set(cache_key, {"status": "error", "message": str(exc)}, timeout=600)


def start_worker(conversation, session, user):
    """Seed the status cache and spawn the worker thread."""
    cache.set(
        f"ai_status_{conversation.id}",
        {"status": "starting", "message": "Starting..."},
        timeout=600,
    )
    threading.Thread(
        target=process_draft_chat,
        args=(conversation.id, session.id, user.id),
        daemon=True,
    ).start()
