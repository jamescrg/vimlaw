// SortableJS integration for group ordering

document.addEventListener('DOMContentLoaded', function() {
    initializeGroupSortable();
});

// Re-initialize after HTMX swaps content
document.body.addEventListener('htmx:afterSwap', function(event) {
    if (event.target.id === 'groups-table' || event.target.closest('#groups-table')) {
        initializeGroupSortable();
    }
});

function getCSRFToken() {
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

function initializeGroupSortable() {
    const groupsTbody = document.getElementById('groups-sortable');

    if (!groupsTbody) {
        return; // Table not found on this page
    }

    // Initialize SortableJS
    Sortable.create(groupsTbody, {
        handle: '.drag-handle',
        animation: 150,
        ghostClass: 'sortable-ghost',
        dragClass: 'sortable-drag',

        onEnd: function(evt) {
            // Collect all group IDs in the new order
            const groupRows = groupsTbody.querySelectorAll('tr[data-group-id]');
            const groupIds = Array.from(groupRows).map(row => row.dataset.groupId);

            // Send the new order to the server
            fetch('/settings/contacts/groups/update-order/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCSRFToken()
                },
                body: JSON.stringify({
                    group_ids: groupIds
                })
            })
            .then(response => response.json())
            .then(data => {
                if (!data.success) {
                    console.error('Failed to update group order:', data.error);
                }
            })
            .catch(error => {
                console.error('Error updating group order:', error);
            });
        }
    });
}
