"""Formatting helpers for feeding synced emails into AI context.

The thread is the context unit: one item per Gmail thread (not per message),
matching how correspondence is actually discussed. Shared by
apps/case/ai/context.py (always-included and incremental collection) and
apps/case/ai/selector.py (the auto-item manifest).
"""


def group_by_thread(emails):
    """Group Email rows into threads, oldest message first within each.

    Falls back to ``gmail_id`` as the key for rows with no thread id, so a
    stray message still forms a one-message thread.
    """
    threads = {}
    for email in sorted(emails, key=lambda e: e.date or e.created_at):
        threads.setdefault(email.thread_id or email.gmail_id, []).append(email)
    return list(threads.values())


def thread_subject(emails):
    return next((e.subject for e in emails if e.subject), "(no subject)")


def format_email_thread(emails, omitted_earlier=0):
    """Format a thread's messages (oldest first) for an AI prompt.

    ``omitted_earlier`` marks messages hidden by an incremental ``since``
    cutoff so the model knows the thread has prior history.
    """
    total = len(emails) + omitted_earlier
    parts = [
        f"**Email thread: {thread_subject(emails)}** "
        f"({total} message{'s' if total != 1 else ''})"
    ]
    if omitted_earlier:
        parts.append(
            f"(thread continues earlier: {omitted_earlier} older "
            f"message{'s' if omitted_earlier != 1 else ''} not shown)"
        )
    for email in emails:
        line = (
            f"--- From: {email.sender or '(unknown)'} | "
            f"To: {email.recipients or '(undisclosed)'}"
        )
        if email.date:
            line += f" | Date: {email.date.strftime('%b %d, %Y %H:%M')}"
        parts.append(line)
        if email.body_text:
            parts.append(email.body_text)
        if email.attachments:
            atts = ", ".join(
                f"{a.get('filename', '?')} ({a.get('size', 0):,} bytes)"
                for a in email.attachments
            )
            parts.append(f"Attachments (not imported, available in Gmail): {atts}")
    return "\n".join(parts)
