"""
Semantic index over matter materials (documents, notes, library notes,
emails, highlights, timeline facts).

Text is chunked (~6k chars, paragraph-aware, overlapping), embedded
(embeddings.py) and stored as MaterialChunk rows with a pgvector column;
search_materials fuses cosine-nearest chunks with the keyword hits so
the agent finds meaning as well as words. Saves enqueue re-indexing on
qcluster (skipped when the content hash is unchanged); deletes clean up
inline. `manage.py build_semantic_index` backfills.
"""

import hashlib
import logging

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.db.models.signals import post_delete, post_save

from .embeddings import embed_queries, embed_texts

logger = logging.getLogger(__name__)

CHUNK_CHARS = 6000
CHUNK_OVERLAP = 600
MAX_CHUNKS_PER_OBJECT = 200
SEMANTIC_KINDS = ("document", "note", "library", "email", "highlight", "fact")
# Cosine similarity floor: chunks below it are noise, not neighbors.
SIM_FLOOR = 0.30


def chunk_text(text):
    """Split ``text`` into overlapping ~CHUNK_CHARS pieces, preferring
    paragraph and word boundaries."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= CHUNK_CHARS:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_CHARS
        if end < len(text):
            floor = start + CHUNK_CHARS // 2
            cut = text.rfind("\n\n", floor, end)
            if cut == -1:
                cut = text.rfind("\n", floor, end)
            if cut == -1:
                cut = text.rfind(" ", floor, end)
            if cut != -1:
                end = cut
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks[:MAX_CHUNKS_PER_OBJECT]


# ---------------------------------------------------------------------------
# Per-kind extraction
# ---------------------------------------------------------------------------


def _note_kind(note):
    return "library" if note.matter_id is None else "note"


def _source(kind, obj):
    """(matter_id, text) for one object; empty text means do not index."""
    if kind == "document":
        if obj.ai_context == "never" or obj.ocr_status not in (
            "completed",
            "extracted",
        ):
            return obj.matter_id, ""
        return obj.matter_id, (
            f"{obj.name}\n{obj.description or ''}\n{obj.ocr_text or ''}"
        )
    if kind in ("note", "library"):
        return obj.matter_id, f"{obj.title}\n{obj.content or ''}"
    if kind == "email":
        if obj.ai_context == "never":
            return obj.matter_id, ""
        return obj.matter_id, (
            f"{obj.subject or ''}\nFrom: {obj.sender or ''}\n{obj.body_text or ''}"
        )
    if kind == "highlight":
        source = obj.document or obj.caselaw
        matter_id = source.matter_id if source else None
        return matter_id, f"{obj.citation}\n{obj.text or ''}"
    if kind == "fact":
        return obj.matter_id, obj.description or ""
    raise ValueError(f"Unknown semantic kind {kind!r}")


def _model_for(kind):
    from apps.case.models import Document, Fact, Highlight
    from apps.mail.models import Email
    from apps.notes.models import Note

    return {
        "document": Document,
        "note": Note,
        "library": Note,
        "email": Email,
        "highlight": Highlight,
        "fact": Fact,
    }[kind]


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------


def index_object(kind, obj):
    """(Re)index one object; returns the number of chunks written.

    Skips the embedding call when the content hash is unchanged. Notes
    clear both note and library rows so a note moving in or out of the
    library never leaves stale chunks behind.
    """
    from .models import MaterialChunk

    if kind in ("note", "library"):
        kind = _note_kind(obj)
        stale = MaterialChunk.objects.filter(
            kind__in=("note", "library"), object_id=obj.pk
        )
    else:
        stale = MaterialChunk.objects.filter(kind=kind, object_id=obj.pk)

    matter_id, text = _source(kind, obj)
    text = (text or "").strip()
    if not text:
        stale.delete()
        return 0

    content_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
    current = stale.filter(kind=kind)
    if (
        current.filter(content_hash=content_hash).exists()
        and not stale.exclude(content_hash=content_hash).exists()
    ):
        return 0

    chunks = chunk_text(text)
    vectors = embed_texts(chunks)
    with transaction.atomic():
        stale.delete()
        MaterialChunk.objects.bulk_create(
            [
                MaterialChunk(
                    matter_id=matter_id,
                    kind=kind,
                    object_id=obj.pk,
                    chunk_index=i,
                    text=chunk,
                    content_hash=content_hash,
                    embedding=vector,
                )
                for i, (chunk, vector) in enumerate(zip(chunks, vectors))
            ]
        )
    return len(chunks)


def index_object_task(kind, pk):
    """qcluster entry point for save-time re-indexing."""
    obj = _model_for(kind).objects.filter(pk=pk).first()
    if obj is None:
        return
    try:
        index_object(kind, obj)
    except Exception:
        logger.exception("Semantic indexing failed for %s %s", kind, pk)


# ---------------------------------------------------------------------------
# Save/delete hooks
# ---------------------------------------------------------------------------


def _enqueue(kind, pk):
    if not getattr(settings, "SEMANTIC_AUTO_INDEX", True):
        return
    try:
        from django_q.tasks import async_task

        async_task(
            "apps.case.ai.semantic.index_object_task", kind, pk, group="semantic"
        )
    except Exception:
        # Broker down: the backfill command is the catch-up path.
        logger.exception("Could not enqueue semantic indexing for %s %s", kind, pk)


def _drop_chunks(kind, pk):
    from .models import MaterialChunk

    kinds = ("note", "library") if kind in ("note", "library") else (kind,)
    MaterialChunk.objects.filter(kind__in=kinds, object_id=pk).delete()


def connect_signals():
    """Wire save/delete hooks; called once from CaseConfig.ready()."""
    from apps.case.models import Document, Fact, Highlight
    from apps.mail.models import Email
    from apps.notes.models import Note

    hooks = {
        Document: "document",
        Note: "note",
        Email: "email",
        Highlight: "highlight",
        Fact: "fact",
    }
    for model, kind in hooks.items():

        def _saved(sender, instance, kind=kind, **kwargs):
            _enqueue(kind, instance.pk)

        def _deleted(sender, instance, kind=kind, **kwargs):
            try:
                _drop_chunks(kind, instance.pk)
            except Exception:
                logger.exception("Semantic chunk cleanup failed")

        post_save.connect(
            _saved, sender=model, weak=False, dispatch_uid=f"semantic-save-{kind}"
        )
        post_delete.connect(
            _deleted, sender=model, weak=False, dispatch_uid=f"semantic-del-{kind}"
        )


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def semantic_entries(queries, matter, kinds, limit):
    """Per query, the nearest distinct objects: [[{kind, object_id, text,
    similarity, query}, ...], ...]. Empty lists when embedding fails, so
    keyword search degrades gracefully."""
    from pgvector.django import CosineDistance

    from .models import MaterialChunk

    kinds = [k for k in kinds if k in SEMANTIC_KINDS]
    if not kinds:
        return []
    try:
        query_vectors = embed_queries(list(queries))
    except Exception:
        logger.exception("Query embedding failed; semantic pass skipped")
        return []

    scope = Q(pk__in=[])
    matter_kinds = [k for k in kinds if k != "library"]
    if matter_kinds and matter is not None:
        scope |= Q(matter=matter, kind__in=matter_kinds)
    if "library" in kinds:
        scope |= Q(kind="library", matter__isnull=True)

    results = []
    for query, vector in zip(queries, query_vectors):
        rows = (
            MaterialChunk.objects.filter(scope)
            .annotate(distance=CosineDistance("embedding", vector))
            .order_by("distance")[: limit * 3]
        )
        ranked = []
        seen_objects = set()
        for row in rows:
            similarity = 1.0 - float(row.distance)
            if similarity < SIM_FLOOR:
                break
            key = (row.kind, row.object_id)
            if key in seen_objects:
                continue
            seen_objects.add(key)
            ranked.append(
                {
                    "kind": row.kind,
                    "object_id": row.object_id,
                    "text": row.text,
                    "similarity": round(similarity, 3),
                    "query": query,
                }
            )
            if len(ranked) >= limit:
                break
        results.append(ranked)
    return results
