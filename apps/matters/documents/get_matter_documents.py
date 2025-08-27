from apps.documents.filters import DocumentsFilter


def get_matter_documents(request, matter):
    filter_data = request.session.get("matters_documents_filter", {})

    has_existing_filter = any(key != "matter" for key in filter_data.keys())

    if has_existing_filter:
        filter_data = {
            **filter_data,
            "matter": matter.id,
        }

        filter = DocumentsFilter(filter_data)
    else:
        default_filter = {"matter": matter.id, "order_by": "-uploaded_at"}

        filter = DocumentsFilter(default_filter)

    documents = filter.qs

    return {"documents": documents}
