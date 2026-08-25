"""
Gemini embeddings for semantic material search.

One model, one dimensionality, used for both documents and queries
(asymmetric task types tune the vectors for retrieval). Distances are
cosine, which is scale-invariant, so the vectors are stored as returned.
"""

import logging

from django.conf import settings
from google.genai import types

from google import genai

logger = logging.getLogger(__name__)

EMBED_MODEL = "gemini-embedding-001"
EMBED_DIM = 768
EMBED_BATCH = 100


def embed_texts(texts, task_type="RETRIEVAL_DOCUMENT"):
    """Vectors for ``texts`` (ordered), batched under the API limit."""
    texts = [t if t.strip() else " " for t in texts]
    if not texts:
        return []
    # A wedged connection must fail, not hang a backfill or a search.
    client = genai.Client(
        api_key=settings.GEMINI_API_KEY,
        http_options=types.HttpOptions(timeout=60_000),
    )
    vectors = []
    for start in range(0, len(texts), EMBED_BATCH):
        result = client.models.embed_content(
            model=EMBED_MODEL,
            contents=texts[start : start + EMBED_BATCH],
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=EMBED_DIM,
            ),
        )
        vectors.extend([e.values for e in result.embeddings])
    return vectors


def embed_queries(queries):
    """Query-side vectors (RETRIEVAL_QUERY pairs with RETRIEVAL_DOCUMENT)."""
    return embed_texts(list(queries), task_type="RETRIEVAL_QUERY")
