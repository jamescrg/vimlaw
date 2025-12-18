from django.urls import path

from apps.case import views
from apps.case.ai import views as ai
from apps.case.documents import views as documents
from apps.case.facts import views as facts
from apps.case.highlights import views as highlights
from apps.case.labels import views as labels
from apps.case.notes import views as notes
from apps.case.search import views as search

app_name = "case"

urlpatterns = [
    # Root case URL - redirects to last viewed matter
    path("case/", views.case_index, name="case-index"),
    path("case/no-matter/", views.no_matter, name="no-matter"),
    # Matter selection (legacy support - redirects to new URL structure)
    path(
        "case/select-matter/<int:matter_id>/",
        views.select_matter,
        name="select-matter",
    ),
    # ==========================================================================
    # MATTER-SCOPED ROUTES (list, filter, add operations)
    # ==========================================================================
    # Documents
    path(
        "case/<int:matter_id>/documents/",
        documents.index,
        name="documents-index",
    ),
    path(
        "case/<int:matter_id>/documents/list/",
        documents.documents_list,
        name="documents-list",
    ),
    path(
        "case/<int:matter_id>/documents/add/",
        documents.documents_add,
        name="documents-add",
    ),
    path(
        "case/<int:matter_id>/documents/filter/",
        documents.documents_filter,
        name="documents-filter",
    ),
    path(
        "case/<int:matter_id>/documents/filter/label/<int:label_id>/",
        documents.documents_filter_label,
        name="documents-filter-label",
    ),
    path(
        "case/<int:matter_id>/documents/filter/category/",
        documents.documents_filter_category,
        name="documents-filter-category-clear",
    ),
    path(
        "case/<int:matter_id>/documents/filter/category/<str:category>/",
        documents.documents_filter_category,
        name="documents-filter-category",
    ),
    path(
        "case/<int:matter_id>/documents/filter/proceeding/",
        documents.documents_filter_proceeding,
        name="documents-filter-proceeding-clear",
    ),
    path(
        "case/<int:matter_id>/documents/filter/proceeding/<int:proceeding_id>/",
        documents.documents_filter_proceeding,
        name="documents-filter-proceeding",
    ),
    path(
        "case/<int:matter_id>/documents/filter/keyword/",
        documents.documents_filter_keyword,
        name="documents-filter-keyword",
    ),
    path(
        "case/<int:matter_id>/documents/filter/importance/<int:importance_value>/",
        documents.documents_filter_importance,
        name="documents-filter-importance",
    ),
    path(
        "case/<int:matter_id>/documents/sort/<str:order>/",
        documents.documents_sort,
        name="documents-sort",
    ),
    path(
        "case/<int:matter_id>/documents/bulk-update/",
        documents.bulk_documents_update,
        name="documents-bulk-update",
    ),
    path(
        "case/<int:matter_id>/documents/clear-selection/",
        documents.clear_document_selection,
        name="documents-clear-selection",
    ),
    path(
        "case/<int:matter_id>/documents/get-proceedings-and-labels/",
        documents.get_proceedings_and_labels,
        name="get-proceedings-and-labels",
    ),
    # Highlights (matter-scoped)
    path(
        "case/<int:matter_id>/highlights/",
        highlights.highlights_index,
        name="highlights-index",
    ),
    path(
        "case/<int:matter_id>/highlights/list/",
        highlights.highlights_list,
        name="highlights-list",
    ),
    path(
        "case/<int:matter_id>/highlights/filter/",
        highlights.highlights_filter,
        name="highlights-filter",
    ),
    path(
        "case/<int:matter_id>/highlights/filter/document/",
        highlights.highlights_filter_document,
        name="highlights-filter-document-clear",
    ),
    path(
        "case/<int:matter_id>/highlights/filter/document/<int:document_id>/",
        highlights.highlights_filter_document,
        name="highlights-filter-document",
    ),
    path(
        "case/<int:matter_id>/highlights/filter/keyword/",
        highlights.highlights_filter_keyword,
        name="highlights-filter-keyword",
    ),
    path(
        "case/<int:matter_id>/highlights/filter/importance/<int:importance_value>/",
        highlights.highlights_filter_importance,
        name="highlights-filter-importance",
    ),
    path(
        "case/<int:matter_id>/highlights/filter/sort/<str:order>/",
        highlights.highlights_filter_sort,
        name="highlights-filter-sort",
    ),
    path(
        "case/<int:matter_id>/highlights/filter/default/",
        highlights.highlights_filter_default,
        name="highlights-filter-default",
    ),
    # Facts (matter-scoped)
    path("case/<int:matter_id>/facts/", facts.facts_index, name="facts-index"),
    path("case/<int:matter_id>/facts/list/", facts.facts_list, name="facts-list"),
    path("case/<int:matter_id>/facts/add/", facts.facts_add, name="facts-add"),
    path("case/<int:matter_id>/facts/filter/", facts.facts_filter, name="facts-filter"),
    path(
        "case/<int:matter_id>/facts/filter/keyword/",
        facts.facts_filter_keyword,
        name="facts-filter-keyword",
    ),
    path(
        "case/<int:matter_id>/facts/filter/importance/<int:importance_value>/",
        facts.facts_filter_importance,
        name="facts-filter-importance",
    ),
    path(
        "case/<int:matter_id>/facts/sort/<str:order>/",
        facts.facts_sort,
        name="facts-sort",
    ),
    path("case/<int:matter_id>/facts/print/", facts.facts_print, name="facts-print"),
    path("case/<int:matter_id>/facts/pdf/", facts.facts_pdf, name="facts-pdf"),
    # Notes (matter-scoped)
    path("case/<int:matter_id>/notes/", notes.notes_index, name="notes-index"),
    path("case/<int:matter_id>/notes/list/", notes.notes_list, name="notes-list"),
    path("case/<int:matter_id>/notes/add/", notes.notes_add, name="notes-add"),
    path("case/<int:matter_id>/notes/filter/", notes.notes_filter, name="notes-filter"),
    path(
        "case/<int:matter_id>/notes/filter/keyword/",
        notes.notes_filter_keyword,
        name="notes-filter-keyword",
    ),
    path(
        "case/<int:matter_id>/notes/filter/importance/<int:importance_value>/",
        notes.notes_filter_importance,
        name="notes-filter-importance",
    ),
    path(
        "case/<int:matter_id>/notes/filter/category/<str:category>/",
        notes.notes_filter_category,
        name="notes-filter-category",
    ),
    path(
        "case/<int:matter_id>/notes/filter/category/",
        notes.notes_filter_category,
        {"category": ""},
        name="notes-filter-category-clear",
    ),
    path(
        "case/<int:matter_id>/notes/filter/topic/<str:topic>/",
        notes.notes_filter_topic,
        name="notes-filter-topic",
    ),
    path(
        "case/<int:matter_id>/notes/filter/topic/",
        notes.notes_filter_topic,
        {"topic": ""},
        name="notes-filter-topic-clear",
    ),
    path(
        "case/<int:matter_id>/notes/sort/<str:order>/",
        notes.notes_sort,
        name="notes-sort",
    ),
    path(
        "case/<int:matter_id>/notes/shortcuts/",
        notes.notes_shortcuts,
        name="notes-shortcuts",
    ),
    # Labels (matter-scoped)
    path("case/<int:matter_id>/labels/", labels.labels_index, name="labels-index"),
    path("case/<int:matter_id>/labels/list/", labels.labels_list, name="labels-list"),
    path("case/<int:matter_id>/labels/add/", labels.add_label, name="add-label"),
    path(
        "case/<int:matter_id>/labels/filter/",
        labels.labels_filter,
        name="filter-labels",
    ),
    path(
        "case/<int:matter_id>/labels/sort/<str:order>/",
        labels.labels_sort,
        name="sort-labels",
    ),
    # Search (matter-scoped)
    path("case/<int:matter_id>/search/", search.search_index, name="search-index"),
    path("case/<int:matter_id>/search/list/", search.search_list, name="search-list"),
    path(
        "case/<int:matter_id>/search/results/",
        search.search_results,
        name="search-results",
    ),
    path(
        "case/<int:matter_id>/search/query/",
        search.search_query,
        name="search-query",
    ),
    path(
        "case/<int:matter_id>/search/filter/",
        search.search_filter,
        name="search-filter",
    ),
    path(
        "case/<int:matter_id>/search/filter/type/",
        search.search_filter_type,
        name="search-filter-type-clear",
    ),
    path(
        "case/<int:matter_id>/search/filter/type/<str:result_type>/",
        search.search_filter_type,
        name="search-filter-type",
    ),
    path(
        "case/<int:matter_id>/search/clear/",
        search.search_clear,
        name="search-clear",
    ),
    # AI Chat (matter-scoped)
    path("case/<int:matter_id>/ai/", ai.ai_index, name="ai-index"),
    path("case/<int:matter_id>/ai/list/", ai.ai_list, name="ai-list"),
    path("case/<int:matter_id>/ai/messages/", ai.message_list, name="ai-messages"),
    path("case/<int:matter_id>/ai/send/", ai.send_message, name="ai-send"),
    path(
        "case/<int:matter_id>/ai/conversations/",
        ai.conversation_list,
        name="ai-conversations",
    ),
    path(
        "case/<int:matter_id>/ai/conversations/new/",
        ai.new_conversation_view,
        name="ai-new-conversation-view",
    ),
    path(
        "case/<int:matter_id>/ai/create-prompt/",
        ai.create_prompt,
        name="ai-create-prompt",
    ),
    # ==========================================================================
    # OBJECT-SPECIFIC ROUTES (operate on specific objects by ID)
    # ==========================================================================
    # Document operations
    path(
        "case/documents/<int:document_id>/edit/",
        documents.documents_edit,
        name="documents-edit",
    ),
    path(
        "case/documents/<int:document_id>/edit-name/",
        documents.documents_edit_name,
        name="documents-edit-name",
    ),
    path(
        "case/documents/<int:document_id>/delete/",
        documents.documents_delete,
        name="documents-delete",
    ),
    path(
        "case/documents/<int:document_id>/download/",
        documents.download_document,
        name="documents-download",
    ),
    path(
        "case/documents/<int:document_id>/date/",
        documents.document_date,
        name="document-date",
    ),
    path(
        "case/documents/<int:document_id>/category/<str:category>/",
        documents.document_category,
        name="document-category",
    ),
    path(
        "case/documents/<int:document_id>/proceeding/<int:proceeding_id>/",
        documents.document_proceeding,
        name="document-proceeding",
    ),
    path(
        "case/documents/<int:document_id>/importance/<int:importance>/",
        documents.document_importance,
        name="document-importance",
    ),
    path(
        "case/documents/<int:document_id>/toggle-select/",
        documents.toggle_document_select,
        name="documents-toggle-select",
    ),
    path(
        "case/documents/<int:document_id>/row/",
        documents.document_row,
        name="document-row",
    ),
    path(
        "case/documents/<int:document_id>/ocr-badge/",
        documents.ocr_badge,
        name="ocr-badge",
    ),
    path(
        "case/documents/<int:document_id>/view/",
        documents.document_viewer,
        name="viewer",
    ),
    path(
        "case/documents/<int:document_id>/serve/",
        documents.serve_document,
        name="serve",
    ),
    path(
        "case/documents/<int:document_id>/ocr-status/",
        documents.ocr_status,
        name="ocr-status",
    ),
    path(
        "case/documents/<int:document_id>/retry-ocr/",
        documents.retry_ocr,
        name="retry-ocr",
    ),
    path(
        "case/documents/<int:document_id>/highlights/add/",
        highlights.add_highlight,
        name="add-highlight",
    ),
    path(
        "case/documents/<int:document_id>/highlights/",
        highlights.highlights_for_document,
        name="highlights-for-document",
    ),
    # Highlight operations
    path(
        "case/highlights/<int:highlight_id>/detail/",
        highlights.highlight_detail,
        name="highlight-detail",
    ),
    path(
        "case/highlights/<int:highlight_id>/edit/",
        highlights.edit_highlight,
        name="edit-highlight",
    ),
    path(
        "case/highlights/<int:highlight_id>/delete/",
        highlights.delete_highlight,
        name="delete-highlight",
    ),
    path(
        "case/highlights/<int:highlight_id>/importance/<int:importance>/",
        highlights.highlight_importance,
        name="highlight-importance",
    ),
    path(
        "case/highlights/<int:highlight_id>/link/",
        highlights.highlight_link,
        name="highlight-link",
    ),
    # Fact operations
    path("case/facts/<int:fact_id>/edit/", facts.facts_edit, name="facts-edit"),
    path("case/facts/<int:fact_id>/delete/", facts.facts_delete, name="facts-delete"),
    path(
        "case/facts/<int:fact_id>/edit-description/",
        facts.facts_edit_description,
        name="facts-edit-description",
    ),
    path(
        "case/facts/<int:fact_id>/update-description/",
        facts.facts_update_description,
        name="facts-update-description",
    ),
    path(
        "case/facts/<int:fact_id>/sources/",
        facts.fact_sources_modal,
        name="fact-sources",
    ),
    path(
        "case/facts/<int:fact_id>/sources/search/",
        facts.fact_sources_search,
        name="fact-sources-search",
    ),
    path(
        "case/facts/<int:fact_id>/sources/add/",
        facts.fact_add_source,
        name="fact-add-source",
    ),
    path(
        "case/facts/<int:fact_id>/sources/remove/",
        facts.fact_remove_source,
        name="fact-remove-source",
    ),
    path(
        "case/facts/<int:fact_id>/importance/<int:importance>/",
        facts.fact_importance,
        name="fact-importance",
    ),
    # Note operations
    path("case/notes/<int:note_id>/", notes.note_view, name="note-view"),
    path(
        "case/notes/<int:note_id>/content-partial/",
        notes.note_content_partial,
        name="note-content-partial",
    ),
    path(
        "case/notes/<int:note_id>/sidebar-sort/<str:sort_key>/",
        notes.sidebar_sort,
        name="note-sidebar-sort",
    ),
    path("case/notes/<int:note_id>/edit/", notes.note_edit, name="notes-edit"),
    path("case/notes/<int:note_id>/delete/", notes.note_delete, name="notes-delete"),
    path("case/notes/<int:note_id>/content/", notes.note_content, name="note-content"),
    path(
        "case/notes/<int:note_id>/category/<str:value>/",
        notes.note_category,
        name="note-category",
    ),
    path(
        "case/notes/<int:note_id>/importance/<int:value>/",
        notes.note_importance,
        name="note-importance",
    ),
    path(
        "case/notes/<int:note_id>/autosave/",
        notes.note_autosave,
        name="note-autosave",
    ),
    path(
        "case/notes/<int:note_id>/title/",
        notes.note_title,
        name="note-title",
    ),
    path(
        "case/notes/<int:note_id>/reference-search/",
        notes.reference_search,
        name="note-reference-search",
    ),
    path(
        "case/notes/<int:note_id>/import/",
        notes.note_import_modal,
        name="note-import-modal",
    ),
    path(
        "case/notes/<int:note_id>/citations/",
        notes.reference_citations,
        name="note-citations",
    ),
    # Label operations
    path(
        "case/labels/<int:label_id>/edit/",
        labels.edit_label,
        name="edit-label",
    ),
    path(
        "case/labels/<int:label_id>/delete/",
        labels.delete_label,
        name="delete-label",
    ),
    path(
        "case/labels/apply/<str:object_type>/<int:object_id>/",
        labels.labels_apply_modal,
        name="labels-apply-modal",
    ),
    path(
        "case/labels/search/<str:object_type>/<int:object_id>/",
        labels.labels_search,
        name="labels-search",
    ),
    path(
        "case/labels/add-to/<str:object_type>/<int:object_id>/",
        labels.add_label_to,
        name="add-label-to",
    ),
    path(
        "case/labels/remove-from/<str:object_type>/<int:object_id>/",
        labels.remove_label_from,
        name="remove-label-from",
    ),
    path(
        "case/labels/create-and-apply/<str:object_type>/<int:object_id>/",
        labels.labels_create_and_apply,
        name="labels-create-and-apply",
    ),
    # AI conversation operations
    path(
        "case/ai/status/<int:conv_id>/",
        ai.ai_status,
        name="ai-status",
    ),
    path(
        "case/ai/conversations/<int:conv_id>/",
        ai.select_conversation,
        name="ai-select-conversation",
    ),
    path(
        "case/ai/conversations/<int:conv_id>/view/",
        ai.conversation_view,
        name="ai-conversation-view",
    ),
    path(
        "case/ai/conversations/<int:conv_id>/delete/",
        ai.delete_conversation,
        name="ai-delete-conversation",
    ),
    path(
        "case/ai/conversations/<int:conv_id>/rename/",
        ai.rename_conversation,
        name="ai-rename-conversation",
    ),
    path(
        "case/ai/conversations/<int:conv_id>/rename-form/",
        ai.rename_form,
        name="ai-rename-form",
    ),
    path(
        "case/ai/conversations/<int:conv_id>/upload/",
        ai.chat_upload,
        name="ai-chat-upload",
    ),
    path(
        "case/ai/conversations/<int:conv_id>/attachments/",
        ai.chat_attachment_status,
        name="ai-attachment-status",
    ),
    path(
        "case/ai/attachments/<int:attachment_id>/delete/",
        ai.delete_attachment,
        name="ai-delete-attachment",
    ),
    # ==========================================================================
    # LEGACY ROUTES (redirect to new structure)
    # ==========================================================================
    # Old document routes - redirect to case_index which handles matter selection
    path("documents/", views.case_index, name="index"),
]
