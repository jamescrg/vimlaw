from django.urls import path

from apps.documents.views import (
    add_highlight,
    add_label,
    bulk_document_update,
    clear_document_selection,
    delete_highlight,
    delete_label,
    document_category,
    document_date,
    document_proceeding,
    document_row,
    document_viewer,
    documents_add,
    documents_delete,
    documents_edit,
    documents_filter,
    documents_filter_category,
    documents_filter_keyword,
    documents_filter_label,
    documents_list,
    documents_sort,
    download_document,
    edit_label,
    fact_add_source,
    fact_remove_source,
    fact_sources_modal,
    fact_sources_search,
    get_proceedings_and_labels,
    highlight_link,
    highlights_filter,
    highlights_filter_document,
    highlights_filter_keyword,
    highlights_index,
    highlights_list,
    index,
    labels_filter,
    labels_index,
    labels_list,
    labels_sort,
    ocr_badge,
    ocr_status,
    retry_ocr,
    select_matter,
    serve_document,
    timeline_add,
    timeline_delete,
    timeline_edit,
    timeline_edit_description,
    timeline_index,
    timeline_list,
    timeline_pdf,
    timeline_print,
    timeline_update_description,
    toggle_document_select,
)

app_name = "documents"

urlpatterns = [
    # Documents
    path("documents/", index, name="index"),
    path("documents/list/", documents_list, name="list"),
    path(
        "documents/select-matter/<int:matter_id>/", select_matter, name="select-matter"
    ),
    path("documents/add/", documents_add, name="add"),
    path("documents/add/<int:matter_id>/", documents_add, name="add-with-matter"),
    path("documents/edit/<int:document_id>/", documents_edit, name="edit"),
    path("documents/delete/<int:document_id>/", documents_delete, name="delete"),
    path("documents/filter/", documents_filter, name="filter"),
    path(
        "documents/filter/label/<int:label_id>/",
        documents_filter_label,
        name="filter-label",
    ),
    path(
        "documents/filter/category/",
        documents_filter_category,
        name="filter-category-clear",
    ),
    path(
        "documents/filter/category/<str:category>/",
        documents_filter_category,
        name="filter-category",
    ),
    path(
        "documents/filter/keyword/",
        documents_filter_keyword,
        name="filter-keyword",
    ),
    path("documents/sort/<str:order>/", documents_sort, name="sort"),
    path("documents/download/<int:document_id>/", download_document, name="download"),
    # Inline editing
    path(
        "documents/<int:document_id>/date/",
        document_date,
        name="document-date",
    ),
    path(
        "documents/<int:document_id>/category/<str:category>/",
        document_category,
        name="document-category",
    ),
    path(
        "documents/<int:document_id>/proceeding/<int:proceeding_id>/",
        document_proceeding,
        name="document-proceeding",
    ),
    path(
        "documents/get-proceedings-and-labels/",
        get_proceedings_and_labels,
        name="get-proceedings-and-labels",
    ),
    path("documents/bulk-update/", bulk_document_update, name="bulk-update"),
    path(
        "documents/toggle-select/<int:document_id>/",
        toggle_document_select,
        name="toggle-select",
    ),
    path(
        "documents/clear-selection/", clear_document_selection, name="clear-selection"
    ),
    path("documents/row/<int:document_id>/", document_row, name="document-row"),
    path("documents/ocr-badge/<int:document_id>/", ocr_badge, name="ocr-badge"),
    # Labels
    path("documents/labels/", labels_index, name="labels-index"),
    path("documents/labels/list/", labels_list, name="labels-list"),
    path("documents/labels/add/", add_label, name="add-label"),
    path("documents/labels/edit/<int:label_id>/", edit_label, name="edit-label"),
    path("documents/labels/delete/<int:label_id>/", delete_label, name="delete-label"),
    path("documents/labels/filter/", labels_filter, name="filter-labels"),
    path("documents/labels/sort/<str:order>/", labels_sort, name="sort-labels"),
    # PDF Viewer
    path("documents/view/<int:document_id>/", document_viewer, name="viewer"),
    path("documents/serve/<int:document_id>/", serve_document, name="serve"),
    # OCR endpoints
    path("documents/ocr-status/<int:document_id>/", ocr_status, name="ocr-status"),
    path("documents/retry-ocr/<int:document_id>/", retry_ocr, name="retry-ocr"),
    # Highlight endpoints
    path(
        "documents/<int:document_id>/highlights/add/",
        add_highlight,
        name="add-highlight",
    ),
    path(
        "documents/highlights/<int:highlight_id>/delete/",
        delete_highlight,
        name="delete-highlight",
    ),
    path(
        "documents/highlights/<int:highlight_id>/",
        highlight_link,
        name="highlight-link",
    ),
    # Highlights subapp
    path("documents/highlights/", highlights_index, name="highlights-index"),
    path("documents/highlights/list/", highlights_list, name="highlights-list"),
    path("documents/highlights/filter/", highlights_filter, name="highlights-filter"),
    path(
        "documents/highlights/filter/document/",
        highlights_filter_document,
        name="highlights-filter-document",
    ),
    path(
        "documents/highlights/filter/document/<int:document_id>/",
        highlights_filter_document,
        name="highlights-filter-document",
    ),
    path(
        "documents/highlights/filter/keyword/",
        highlights_filter_keyword,
        name="highlights-filter-keyword",
    ),
    # Timeline subapp
    path("documents/timeline/", timeline_index, name="timeline-index"),
    path("documents/timeline/list/", timeline_list, name="timeline-list"),
    path("documents/timeline/add/", timeline_add, name="timeline-add"),
    path("documents/timeline/<int:fact_id>/edit/", timeline_edit, name="timeline-edit"),
    path(
        "documents/timeline/<int:fact_id>/delete/",
        timeline_delete,
        name="timeline-delete",
    ),
    path("documents/timeline/print/", timeline_print, name="timeline-print"),
    path("documents/timeline/pdf/", timeline_pdf, name="timeline-pdf"),
    path(
        "documents/timeline/<int:fact_id>/edit-description/",
        timeline_edit_description,
        name="timeline-edit-description",
    ),
    path(
        "documents/timeline/<int:fact_id>/update-description/",
        timeline_update_description,
        name="timeline-update-description",
    ),
    path(
        "documents/timeline/<int:fact_id>/sources/",
        fact_sources_modal,
        name="fact-sources",
    ),
    path(
        "documents/timeline/<int:fact_id>/sources/search/",
        fact_sources_search,
        name="fact-sources-search",
    ),
    path(
        "documents/timeline/<int:fact_id>/sources/add/",
        fact_add_source,
        name="fact-add-source",
    ),
    path(
        "documents/timeline/<int:fact_id>/sources/remove/",
        fact_remove_source,
        name="fact-remove-source",
    ),
]
