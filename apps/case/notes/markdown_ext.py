"""Markdown extension for rendering note references."""

import re

from markdown import Extension
from markdown.preprocessors import Preprocessor

from apps.case.models import Document, Highlight


class NoteReferencePreprocessor(Preprocessor):
    """Convert [[doc:id|label]] and [[hl:id|label]] to HTML spans."""

    DOC_PATTERN = re.compile(r"\[\[doc:(\d+)\|([^\]]+)\]\]")
    HL_PATTERN = re.compile(r"\[\[hl:(\d+)\|([^\]]+)\]\]")

    def run(self, lines):
        new_lines = []
        for line in lines:
            line = self.DOC_PATTERN.sub(self._replace_document, line)
            line = self.HL_PATTERN.sub(self._replace_highlight, line)
            new_lines.append(line)
        return new_lines

    def _replace_document(self, match):
        doc_id = int(match.group(1))
        label = match.group(2)

        try:
            document = Document.objects.get(pk=doc_id)
            citation = document.citation
            return (
                f'<a href="/case/documents/view/{doc_id}/" '
                f'target="_blank" class="note-ref note-ref-document" '
                f'title="{document.name}">{label} {citation}</a>'
            )
        except Document.DoesNotExist:
            return '<span class="note-ref note-ref-missing">[Missing document]</span>'

    def _replace_highlight(self, match):
        hl_id = int(match.group(1))
        label = match.group(2)

        try:
            highlight = Highlight.objects.select_related("document").get(pk=hl_id)
            citation = highlight.citation
            return (
                f'<a href="/case/highlights/{hl_id}/" '
                f'target="_blank" class="note-ref note-ref-highlight" '
                f'title="{highlight.text[:100]}...">{label} {citation}</a>'
            )
        except Highlight.DoesNotExist:
            return '<span class="note-ref note-ref-missing">[Missing highlight]</span>'


class NoteReferenceExtension(Extension):
    """Markdown extension to render note references."""

    def extendMarkdown(self, md):
        md.preprocessors.register(
            NoteReferencePreprocessor(md), "note_references", priority=25
        )


def makeExtension(**kwargs):
    return NoteReferenceExtension(**kwargs)
