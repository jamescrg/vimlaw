from django.urls import path

from apps.case import views
from apps.case.ai import views as ai
from apps.case.documents import views as documents
from apps.case.facts import views as facts
from apps.case.highlights import views as highlights
from apps.case.labels import views as labels
from apps.case.search import views as search

app_name = "case"

urlpatterns = [
    # Documents (document list subtab)
    path("documents/", documents.index, name="index"),
    path("documents/list/", documents.documents_list, name="documents-list"),
    path(
        "documents/select-matter/<int:matter_id>/",
        views.select_matter,
        name="select-matter",
    ),
    path("documents/add/", documents.documents_add, name="documents-add"),
    path(
        "documents/add/<int:matter_id>/",
        documents.documents_add,
        name="documents-add-with-matter",
    ),
    path(
        "documents/edit/<int:document_id>/",
        documents.documents_edit,
        name="documents-edit",
    ),
    path(
        "documents/edit-name/<int:document_id>/",
        documents.documents_edit_name,
        name="documents-edit-name",
    ),
    path(
        "documents/delete/<int:document_id>/",
        documents.documents_delete,
        name="documents-delete",
    ),
    path("documents/filter/", documents.documents_filter, name="documents-filter"),
    path(
        "documents/filter/label/<int:label_id>/",
        documents.documents_filter_label,
        name="documents-filter-label",
    ),
    path(
        "documents/filter/category/",
        documents.documents_filter_category,
        name="documents-filter-category-clear",
    ),
    path(
        "documents/filter/category/<str:category>/",
        documents.documents_filter_category,
        name="documents-filter-category",
    ),
    path(
        "documents/filter/keyword/",
        documents.documents_filter_keyword,
        name="documents-filter-keyword",
    ),
    path(
        "documents/filter/importance/<int:importance_value>/",
        documents.documents_filter_importance,
        name="documents-filter-importance",
    ),
    path(
        "documents/sort/<str:order>/", documents.documents_sort, name="documents-sort"
    ),
    path(
        "documents/download/<int:document_id>/",
        documents.download_document,
        name="documents-download",
    ),
    # Inline editing
    path(
        "documents/<int:document_id>/date/",
        documents.document_date,
        name="document-date",
    ),
    path(
        "documents/<int:document_id>/category/<str:category>/",
        documents.document_category,
        name="document-category",
    ),
    path(
        "documents/<int:document_id>/proceeding/<int:proceeding_id>/",
        documents.document_proceeding,
        name="document-proceeding",
    ),
    path(
        "documents/<int:document_id>/importance/<int:importance>/",
        documents.document_importance,
        name="document-importance",
    ),
    path(
        "documents/get-proceedings-and-labels/",
        documents.get_proceedings_and_labels,
        name="get-proceedings-and-labels",
    ),
    path(
        "documents/bulk-update/",
        documents.bulk_documents_update,
        name="documents-bulk-update",
    ),
    path(
        "documents/toggle-select/<int:document_id>/",
        documents.toggle_document_select,
        name="documents-toggle-select",
    ),
    path(
        "documents/clear-selection/",
        documents.clear_document_selection,
        name="documents-clear-selection",
    ),
    path(
        "documents/row/<int:document_id>/", documents.document_row, name="document-row"
    ),
    path(
        "documents/ocr-badge/<int:document_id>/", documents.ocr_badge, name="ocr-badge"
    ),
    # Labels
    path("case/labels/", labels.labels_index, name="labels-index"),
    path("case/labels/list/", labels.labels_list, name="labels-list"),
    path("case/labels/add/", labels.add_label, name="add-label"),
    path("case/labels/edit/<int:label_id>/", labels.edit_label, name="edit-label"),
    path(
        "case/labels/delete/<int:label_id>/", labels.delete_label, name="delete-label"
    ),
    path("case/labels/filter/", labels.labels_filter, name="filter-labels"),
    path("case/labels/sort/<str:order>/", labels.labels_sort, name="sort-labels"),
    # Label application (to documents/highlights/facts)
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
    # PDF Viewer
    path("documents/view/<int:document_id>/", documents.document_viewer, name="viewer"),
    path("documents/serve/<int:document_id>/", documents.serve_document, name="serve"),
    # OCR endpoints
    path(
        "documents/ocr-status/<int:document_id>/",
        documents.ocr_status,
        name="ocr-status",
    ),
    path(
        "documents/retry-ocr/<int:document_id>/", documents.retry_ocr, name="retry-ocr"
    ),
    # Highlight endpoints
    path(
        "documents/<int:document_id>/highlights/add/",
        highlights.add_highlight,
        name="add-highlight",
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
        "case/highlights/<int:highlight_id>/",
        highlights.highlight_link,
        name="highlight-link",
    ),
    # Highlights subapp
    path("case/highlights/", highlights.highlights_index, name="highlights-index"),
    path(
        "case/highlights/for/<int:document_id>/",
        highlights.highlights_for_document,
        name="highlights-for-document",
    ),
    path("case/highlights/list/", highlights.highlights_list, name="highlights-list"),
    path(
        "case/highlights/filter/",
        highlights.highlights_filter,
        name="highlights-filter",
    ),
    path(
        "case/highlights/filter/document/",
        highlights.highlights_filter_document,
        name="highlights-filter-document",
    ),
    path(
        "case/highlights/filter/document/<int:document_id>/",
        highlights.highlights_filter_document,
        name="highlights-filter-document",
    ),
    path(
        "case/highlights/filter/keyword/",
        highlights.highlights_filter_keyword,
        name="highlights-filter-keyword",
    ),
    path(
        "case/highlights/filter/importance/<int:importance_value>/",
        highlights.highlights_filter_importance,
        name="highlights-filter-importance",
    ),
    path(
        "case/highlights/filter/sort/<str:order>/",
        highlights.highlights_filter_sort,
        name="highlights-filter-sort",
    ),
    path(
        "case/highlights/filter/default/",
        highlights.highlights_filter_default,
        name="highlights-filter-default",
    ),
    # Facts subapp
    path("case/facts/", facts.facts_index, name="facts-index"),
    path("case/facts/list/", facts.facts_list, name="facts-list"),
    path("case/facts/filter/", facts.facts_filter, name="facts-filter"),
    path(
        "case/facts/filter/keyword/",
        facts.facts_filter_keyword,
        name="facts-filter-keyword",
    ),
    path(
        "case/facts/filter/importance/<int:importance_value>/",
        facts.facts_filter_importance,
        name="facts-filter-importance",
    ),
    path("case/facts/sort/<str:order>/", facts.facts_sort, name="facts-sort"),
    path("case/facts/add/", facts.facts_add, name="facts-add"),
    path("case/facts/<int:fact_id>/edit/", facts.facts_edit, name="facts-edit"),
    path(
        "case/facts/<int:fact_id>/delete/",
        facts.facts_delete,
        name="facts-delete",
    ),
    path("case/facts/print/", facts.facts_print, name="facts-print"),
    path("case/facts/pdf/", facts.facts_pdf, name="facts-pdf"),
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
    # Search subapp
    path("case/search/", search.search_index, name="search-index"),
    path("case/search/list/", search.search_list, name="search-list"),
    path("case/search/results/", search.search_results, name="search-results"),
    path("case/search/query/", search.search_query, name="search-query"),
    path("case/search/filter/", search.search_filter, name="search-filter"),
    path(
        "case/search/filter/type/",
        search.search_filter_type,
        name="search-filter-type-clear",
    ),
    path(
        "case/search/filter/type/<str:result_type>/",
        search.search_filter_type,
        name="search-filter-type",
    ),
    path("case/search/clear/", search.search_clear, name="search-clear"),
    # AI Chat
    path("case/ai/", ai.ai_index, name="ai-index"),
    path("case/ai/list/", ai.ai_list, name="ai-list"),
    path("case/ai/messages/", ai.message_list, name="ai-messages"),
    path("case/ai/send/", ai.send_message, name="ai-send"),
    path("case/ai/status/<int:conv_id>/", ai.ai_status, name="ai-status"),
    path("case/ai/conversations/", ai.conversation_list, name="ai-conversations"),
    path(
        "case/ai/conversations/new/",
        ai.new_conversation_view,
        name="ai-new-conversation-view",
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
        "case/ai/create-prompt/",
        ai.create_prompt,
        name="ai-create-prompt",
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
]
