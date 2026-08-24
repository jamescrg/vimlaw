"""Watson search registration for Documents app models."""

from watson import search as watson

from apps.case.models import Document, Fact, Highlight
from apps.mail.models import Email
from apps.notes.models import Note

# Register Document model for search
watson.register(
    Document,
    fields=("name", "description", "ocr_text"),
)

# Register Highlight model for search
watson.register(
    Highlight,
    fields=("slug", "text"),
)

# Register Fact model for search
watson.register(
    Fact,
    fields=("description",),
)

# Register Note model for search
watson.register(
    Note,
    fields=("title", "content"),
)

# Register Email for search (agent search_materials; synced rows are
# created one at a time, so watson's save signal indexes them). Existing
# rows need one `manage.py buildwatson` after deploy.
watson.register(
    Email,
    fields=("subject", "body_text", "sender"),
)
