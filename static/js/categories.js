// SortableJS integration for the matter Categories tab — drag rows to set the
// Fee Claim Report section order. Mirrors groups.js; the endpoint comes from
// the tbody's data-reorder-url so the script stays matter-agnostic.

document.addEventListener('DOMContentLoaded', function() {
    initializeCategorySortable();
});

// Re-initialize after HTMX swaps in the categories list (add/edit/delete reload
// the tab body, replacing the sortable tbody).
document.body.addEventListener('htmx:afterSwap', function(event) {
    const target = event.target;
    if (target && target.querySelector && target.querySelector('#categories-sortable')) {
        initializeCategorySortable();
    }
});

function initializeCategorySortable() {
    const categoriesTbody = document.getElementById('categories-sortable');

    if (!categoriesTbody) {
        return; // Table not found on this page
    }

    // Avoid stacking instances if this runs again on the same element.
    const existing = Sortable.get(categoriesTbody);
    if (existing) {
        existing.destroy();
    }

    Sortable.create(categoriesTbody, {
        handle: '.drag-handle',
        animation: 150,
        ghostClass: 'sortable-ghost',
        dragClass: 'sortable-drag',

        onEnd: function() {
            const rows = categoriesTbody.querySelectorAll('tr[data-category-id]');
            const categoryIds = Array.from(rows).map(row => row.dataset.categoryId);

            fetch(categoriesTbody.dataset.reorderUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCategoriesCSRFToken()
                },
                body: JSON.stringify({
                    category_ids: categoryIds
                })
            })
            .then(response => response.json())
            .then(data => {
                if (!data.success) {
                    console.error('Failed to update category order:', data.error);
                }
            })
            .catch(error => {
                console.error('Error updating category order:', error);
            });
        }
    });
}

function getCategoriesCSRFToken() {
    const bodyElement = document.querySelector('body');
    const hxHeaders = bodyElement.getAttribute('hx-headers');

    if (hxHeaders) {
        try {
            const headers = JSON.parse(hxHeaders);
            return headers['X-CSRFToken'] || '';
        } catch (e) {
            console.error('Failed to parse CSRF token from hx-headers');
            return '';
        }
    }
    return '';
}
