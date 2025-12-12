from django.urls import path

from . import views

app_name = "outlines"

urlpatterns = [
    # Outline list
    path("", views.index, name="index"),
    path("list/", views.outlines_list, name="list"),
    path("filter/", views.outlines_filter, name="filter"),
    path("sort/<str:order>/", views.outlines_sort, name="sort"),
    path(
        "filter/importance/<int:importance_value>/",
        views.outlines_filter_importance,
        name="filter-importance",
    ),
    path(
        "filter/category/<str:category>/",
        views.outlines_filter_category,
        name="filter-category",
    ),
    path(
        "filter/category/",
        views.outlines_filter_category,
        {"category": ""},
        name="filter-category-clear",
    ),
    path("filter/keyword/", views.outlines_filter_keyword, name="filter-keyword"),
    # Outline CRUD
    path("add/", views.outline_add, name="add"),
    path("<int:outline_id>/edit/", views.outline_edit, name="edit"),
    path("<int:outline_id>/title/", views.outline_title, name="title"),
    path("<int:outline_id>/delete/", views.outline_delete, name="delete"),
    path(
        "<int:outline_id>/importance/<int:value>/",
        views.outline_importance,
        name="importance",
    ),
    path(
        "<int:outline_id>/category/<str:value>/",
        views.outline_category,
        name="category",
    ),
    path(
        "<int:outline_id>/category/",
        views.outline_category,
        {"value": ""},
        name="category-clear",
    ),
    # Outline view
    path("<int:outline_id>/", views.outline_standalone, name="standalone"),
    path("<int:outline_id>/tree/", views.outline_tree, name="tree"),
    path("shortcuts/", views.shortcuts_modal, name="shortcuts"),
    # Item operations
    path("item/<int:item_id>/", views.item_content, name="item-content"),
    path("item/<int:item_id>/edit/", views.item_edit, name="item-edit"),
    path("<int:outline_id>/item/create/", views.item_create, name="item-create"),
    path("item/<int:item_id>/split/", views.item_split, name="item-split"),
    path("item/<int:item_id>/delete/", views.item_delete, name="item-delete"),
    path(
        "item/<int:item_id>/join-with-previous/",
        views.item_join_with_previous,
        name="item-join-with-previous",
    ),
    path("item/<int:item_id>/indent/", views.item_indent, name="item-indent"),
    path("item/<int:item_id>/outdent/", views.item_outdent, name="item-outdent"),
    path(
        "item/<int:item_id>/toggle-collapse/",
        views.item_toggle_collapse,
        name="item-toggle-collapse",
    ),
    path("<int:outline_id>/expand-all/", views.expand_all, name="expand-all"),
    path("<int:outline_id>/collapse-all/", views.collapse_all, name="collapse-all"),
    path(
        "<int:outline_id>/set-sources-display/",
        views.set_sources_display,
        name="set-sources-display",
    ),
    path(
        "item/<int:item_id>/toggle-heading/",
        views.item_toggle_heading,
        name="item-toggle-heading",
    ),
    path(
        "item/<int:item_id>/toggle-highlight/",
        views.item_toggle_highlight,
        name="item-toggle-highlight",
    ),
    path(
        "item/<int:item_id>/toggle-quote/",
        views.item_toggle_quote,
        name="item-toggle-quote",
    ),
    # Item sources
    path("item/<int:item_id>/sources/", views.item_sources_modal, name="item-sources"),
    path(
        "item/<int:item_id>/sources/search/",
        views.item_sources_search,
        name="item-sources-search",
    ),
    path(
        "item/<int:item_id>/sources/add/",
        views.item_add_source,
        name="item-add-source",
    ),
    path(
        "item/<int:item_id>/sources/remove/",
        views.item_remove_source,
        name="item-remove-source",
    ),
    path("item/<int:item_id>/move/", views.item_move, name="item-move"),
    path("item/<int:item_id>/move-up/", views.item_move_up, name="item-move-up"),
    path("item/<int:item_id>/move-down/", views.item_move_down, name="item-move-down"),
    # Undo operations
    path(
        "<int:outline_id>/restore-items/",
        views.restore_items,
        name="restore-items",
    ),
    path(
        "item/<int:item_id>/restore-position/",
        views.item_restore_position,
        name="item-restore-position",
    ),
    # Batch operations
    path("<int:outline_id>/batch-indent/", views.batch_indent, name="batch-indent"),
    path("<int:outline_id>/batch-outdent/", views.batch_outdent, name="batch-outdent"),
    # Import/Export
    path("<int:outline_id>/import/", views.import_markdown, name="import"),
    path("<int:outline_id>/import-modal/", views.import_modal, name="import-modal"),
    path("<int:outline_id>/export/", views.export_markdown, name="export"),
    # Search and Replace
    path("item/<int:item_id>/replace/", views.item_replace, name="item-replace"),
    path(
        "<int:outline_id>/search-replace/",
        views.search_replace,
        name="search-replace",
    ),
]
