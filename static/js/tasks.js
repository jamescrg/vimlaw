// SortableJS integration for task custom ordering

document.addEventListener('DOMContentLoaded', function() {
    initializeTaskSortable();
});

// Re-initialize after HTMX swaps content
document.body.addEventListener('htmx:afterSwap', function(event) {
    // Check if the swapped content is the tasks list
    if (event.target.id === 'tasks' || event.target.closest('#tasks')) {
        initializeTaskSortable();
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

function initializeTaskSortable() {
    const tasksTable = document.querySelector('.tasks-table');
    const tasksTbody = document.getElementById('tasks-sortable');

    if (!tasksTable || !tasksTbody) {
        return; // Table not found on this page
    }

    // Check if custom_order mode is active
    const isCustomOrderActive = tasksTable.dataset.customOrderActive === 'true';

    if (!isCustomOrderActive) {
        return; // Don't initialize sorting if not in custom order mode
    }

    // Initialize SortableJS
    Sortable.create(tasksTbody, {
        handle: '.drag-handle', // Only allow dragging from the drag handle
        animation: 150,
        ghostClass: 'sortable-ghost',
        dragClass: 'sortable-drag',
        // forceFallback: true, // Disable native drag-and-drop to remove cursor icon

        onEnd: function(evt) {
            // Collect all task IDs in the new order
            const taskRows = tasksTbody.querySelectorAll('tr[data-task-id]');
            const taskIds = Array.from(taskRows).map(row => row.dataset.taskId);

            // Send the new order to the server
            fetch('/agenda/tasks/update-order/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCSRFToken()
                },
                body: JSON.stringify({
                    task_ids: taskIds
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    console.log('Task order updated successfully');
                } else {
                    console.error('Failed to update task order:', data.error);
                    showFeedback('Failed to save order', 'error');
                    // Optionally reload the list to restore original order
                    htmx.trigger('#tasks', 'tasksListChanged');
                }
            })
            .catch(error => {
                console.error('Error updating task order:', error);
                showFeedback('Network error', 'error');
                // Optionally reload the list to restore original order
                htmx.trigger('#tasks', 'tasksListChanged');
            });
        }
    });
}

function showFeedback(message, type) {
    // Create a simple feedback toast/notification
    const feedback = document.createElement('div');
    feedback.className = `task-order-feedback ${type}`;
    feedback.textContent = message;
    feedback.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 12px 20px;
        background: ${type === 'success' ? '#28a745' : '#dc3545'};
        color: white;
        border-radius: 4px;
        z-index: 9999;
        animation: fadeIn 0.3s, fadeOut 0.3s 2s;
    `;

    document.body.appendChild(feedback);

    // Remove after 2.5 seconds
    setTimeout(() => {
        feedback.remove();
    }, 2500);
}

// Add CSS for animations
const style = document.createElement('style');
style.textContent = `
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(-10px); }
        to { opacity: 1; transform: translateY(0); }
    }

    @keyframes fadeOut {
        from { opacity: 1; }
        to { opacity: 0; }
    }

    .sortable-ghost {
        opacity: 0.4;
    }

    .sortable-chosen {
        background-color: #f0f0f0;
    }

    .drag-handle {
        cursor: grab;
        user-select: none;
    }

    .drag-handle:active {
        cursor: grabbing;
    }
`;
document.head.appendChild(style);
