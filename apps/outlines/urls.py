from django.urls import path

from . import views

app_name = "outlines"

urlpatterns = [
    # Outline list
    path("", views.index, name="index"),
    path("list/", views.outlines_list, name="list"),
    # Outline CRUD
    path("add/", views.outline_add, name="add"),
    path("<int:outline_id>/edit/", views.outline_edit, name="edit"),
    path("<int:outline_id>/delete/", views.outline_delete, name="delete"),
    # Outline view
    path("<int:outline_id>/", views.outline_view, name="view"),
    path("<int:outline_id>/standalone/", views.outline_standalone, name="standalone"),
    path("<int:outline_id>/tree/", views.outline_tree, name="tree"),
    path("shortcuts/", views.shortcuts_modal, name="shortcuts"),
    # Item operations
    path("item/<int:item_id>/", views.item_content, name="item-content"),
    path("item/<int:item_id>/edit/", views.item_edit, name="item-edit"),
    path("<int:outline_id>/item/create/", views.item_create, name="item-create"),
    path("item/<int:item_id>/delete/", views.item_delete, name="item-delete"),
    path("item/<int:item_id>/indent/", views.item_indent, name="item-indent"),
    path("item/<int:item_id>/outdent/", views.item_outdent, name="item-outdent"),
    path(
        "item/<int:item_id>/toggle-collapse/",
        views.item_toggle_collapse,
        name="item-toggle-collapse",
    ),
    path("item/<int:item_id>/move/", views.item_move, name="item-move"),
    path("item/<int:item_id>/move-up/", views.item_move_up, name="item-move-up"),
    path("item/<int:item_id>/move-down/", views.item_move_down, name="item-move-down"),
    # Batch operations
    path("<int:outline_id>/batch-indent/", views.batch_indent, name="batch-indent"),
    path("<int:outline_id>/batch-outdent/", views.batch_outdent, name="batch-outdent"),
]
