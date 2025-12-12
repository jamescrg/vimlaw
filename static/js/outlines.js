/**
 * Outlines App - Keyboard Navigation and Item Operations
 */

(function() {
  'use strict';

  // Track currently focused item and selection
  let focusedItemId = null;
  let selectedItemIds = new Set();
  let selectionAnchorId = null;  // Where shift+arrow selection started
  let pendingCursorPosition = null;  // 'start', 'end', 'first', 'last', or 'click'
  let pendingCursorX = null;  // X coordinate to match when positioning cursor
  let pendingClickY = null;  // Y coordinate for click positioning

  // Drag selection state
  let dragStartItemId = null;  // Item where drag started
  let isDragSelecting = false;  // Whether we've switched to item selection mode

  // Undo stack
  const undoStack = [];
  const MAX_UNDO_SIZE = 50;
  let editStartContent = null;  // Content when edit mode started (for undo)

  // Push operation to undo stack
  function pushUndo(operation) {
    undoStack.push(operation);
    if (undoStack.length > MAX_UNDO_SIZE) {
      undoStack.shift();
    }
  }

  // Serialize an item and its children for undo (used for delete)
  function serializeItem(itemEl) {
    if (!itemEl) return null;
    const itemId = itemEl.dataset.itemId;
    const contentEl = itemEl.querySelector(':scope > .item-row .item-content');
    const inputEl = itemEl.querySelector(':scope > .item-row .item-input');
    const content = contentEl?.textContent || inputEl?.value || '';
    const children = Array.from(itemEl.querySelectorAll(':scope > .item-children > .outline-item'))
      .map(child => serializeItem(child));
    return {
      id: itemId,
      parentId: itemEl.dataset.parentId || null,
      order: parseInt(itemEl.dataset.order) || 0,
      content: content,
      collapsed: itemEl.classList.contains('collapsed'),
      heading: itemEl.hasAttribute('data-heading'),
      highlight: itemEl.querySelector(':scope > .item-row')?.classList.contains('hl-yellow') || false,
      children: children
    };
  }

  // Undo the last operation
  function undo() {
    if (undoStack.length === 0) return;

    const op = undoStack.pop();

    switch (op.type) {
      case 'edit_content':
        undoEditContent(op);
        break;
      case 'delete_item':
        undoDeleteItem(op);
        break;
      case 'create_item':
        undoCreateItem(op);
        break;
      case 'indent':
      case 'outdent':
      case 'move_up':
      case 'move_down':
        undoStructuralChange(op);
        break;
      case 'toggle_collapse':
      case 'toggle_heading':
      case 'toggle_highlight':
        undoToggle(op);
        break;
    }
  }

  // Undo handlers
  function undoEditContent(op) {
    fetch(`/outlines/item/${op.itemId}/update/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-CSRFToken': getCSRFToken()
      },
      body: `content=${encodeURIComponent(op.oldContent)}`
    }).then(response => {
      if (response.ok) {
        const itemEl = getItemElement(op.itemId);
        if (itemEl) {
          const contentEl = itemEl.querySelector('.item-content');
          if (contentEl) contentEl.textContent = op.oldContent;
          const inputEl = itemEl.querySelector('.item-input');
          if (inputEl) {
            inputEl.value = op.oldContent;
            autoResizeTextarea(inputEl);
          }
        }
      }
    });
  }

  function undoDeleteItem(op) {
    fetch(`/outlines/${getOutlineId()}/restore-items/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCSRFToken()
      },
      body: JSON.stringify({ items: op.deletedItems })
    }).then(response => {
      if (response.ok) {
        refreshTree();
      }
    });
  }

  function undoCreateItem(op) {
    fetch(`/outlines/item/${op.itemId}/delete/`, {
      method: 'POST',
      headers: {
        'X-CSRFToken': getCSRFToken()
      }
    }).then(response => {
      if (response.ok) {
        const itemEl = getItemElement(op.itemId);
        if (itemEl) itemEl.remove();
      }
    });
  }

  function undoStructuralChange(op) {
    fetch(`/outlines/item/${op.itemId}/restore-position/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCSRFToken()
      },
      body: JSON.stringify({
        parent_id: op.oldParentId,
        order: op.oldOrder
      })
    }).then(response => {
      if (response.ok) {
        refreshTree();
      }
    });
  }

  function undoToggle(op) {
    // Just call the toggle endpoint again to flip it back
    let endpoint;
    switch (op.type) {
      case 'toggle_collapse':
        endpoint = `/outlines/item/${op.itemId}/toggle-collapse/`;
        break;
      case 'toggle_heading':
        endpoint = `/outlines/item/${op.itemId}/toggle-heading/`;
        break;
      case 'toggle_highlight':
        endpoint = `/outlines/item/${op.itemId}/toggle-highlight/`;
        break;
    }
    fetch(endpoint, {
      method: 'POST',
      headers: {
        'X-CSRFToken': getCSRFToken()
      }
    }).then(response => {
      if (response.ok) {
        refreshTreeAndFocus(op.itemId);
      }
    });
  }

  // Refresh the entire tree (used after undo operations)
  function refreshTree() {
    const outlineId = getOutlineId();
    if (!outlineId) return;
    htmx.ajax('GET', `/outlines/${outlineId}/tree/`, {
      target: '#outline-tree',
      swap: 'innerHTML'
    });
  }

  // Get CSRF token for HTMX requests
  function getCSRFToken() {
    return document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
           document.querySelector('meta[name="csrf-token"]')?.content;
  }

  // Get outline ID from container
  function getOutlineId() {
    const container = document.getElementById('outline-tree');
    return container?.dataset.outlineId;
  }

  // Get all visible items in document order
  function getVisibleItems() {
    return Array.from(document.querySelectorAll('.outline-item:not(.collapsed .outline-item)'));
  }

  // Get item element by ID
  function getItemElement(itemId) {
    return document.querySelector(`.outline-item[data-item-id="${itemId}"]`);
  }

  // Set focus on an item (visual focus, not edit mode)
  function setFocusedItem(itemElement, keepSelection = false) {
    // Remove focus from previous item
    document.querySelectorAll('.outline-item.focused').forEach(el => {
      el.classList.remove('focused');
    });

    if (itemElement) {
      itemElement.classList.add('focused');
      focusedItemId = itemElement.dataset.itemId;

      if (!keepSelection) {
        // Clear selection and select only this item
        clearSelection();
        selectItem(itemElement);
      }

      // Scroll into view if needed
      itemElement.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    } else {
      focusedItemId = null;
    }
  }

  // Get currently focused item element
  function getFocusedItem() {
    if (focusedItemId) {
      return getItemElement(focusedItemId);
    }
    return document.querySelector('.outline-item.focused');
  }

  // Select a single item
  function selectItem(itemElement) {
    if (!itemElement) return;
    const itemId = itemElement.dataset.itemId;
    selectedItemIds.add(itemId);
    itemElement.classList.add('selected');
    updateMultiSelectState();
  }

  // Deselect a single item
  function deselectItem(itemElement) {
    if (!itemElement) return;
    const itemId = itemElement.dataset.itemId;
    selectedItemIds.delete(itemId);
    itemElement.classList.remove('selected');
    updateMultiSelectState();
  }

  // Clear all selections
  function clearSelection() {
    document.querySelectorAll('.outline-item.selected').forEach(el => {
      el.classList.remove('selected');
    });
    selectedItemIds.clear();
    selectionAnchorId = null;
    updateMultiSelectState();
  }

  // Update multi-select class on container
  function updateMultiSelectState() {
    const container = document.querySelector('.outline-items');
    if (container) {
      container.classList.toggle('has-multi-select', selectedItemIds.size >= 2);
    }
  }

  // Handle shift+arrow selection with anchor tracking
  function handleShiftArrow(direction) {
    const focusedItem = getFocusedItem();
    if (!focusedItem) return;

    const items = getVisibleItems();
    const focusedIndex = items.findIndex(el => el.dataset.itemId === focusedItemId);

    // Get target item based on direction
    const targetIndex = direction === 'down' ? focusedIndex + 1 : focusedIndex - 1;
    if (targetIndex < 0 || targetIndex >= items.length) return;

    const targetItem = items[targetIndex];

    // If no anchor, start selection from current item
    if (!selectionAnchorId) {
      selectionAnchorId = focusedItemId;
      selectItem(focusedItem);
    }

    const anchorIndex = items.findIndex(el => el.dataset.itemId === selectionAnchorId);

    // Determine if we're expanding or contracting selection
    const movingAwayFromAnchor =
      (direction === 'down' && focusedIndex >= anchorIndex) ||
      (direction === 'up' && focusedIndex <= anchorIndex);

    if (movingAwayFromAnchor) {
      // Expanding: select the target item
      selectItem(targetItem);
    } else {
      // Contracting: deselect the current focused item (unless it's the anchor)
      if (focusedItemId !== selectionAnchorId) {
        deselectItem(focusedItem);
      }
    }

    // Move focus to target
    setFocusedItem(targetItem, true);
    updateSelectionHighlight();
  }

  // Select a range of items between two item IDs
  function selectRange(fromId, toId) {
    const items = getVisibleItems();
    const fromIndex = items.findIndex(el => el.dataset.itemId === fromId);
    const toIndex = items.findIndex(el => el.dataset.itemId === toId);

    if (fromIndex === -1 || toIndex === -1) return;

    const start = Math.min(fromIndex, toIndex);
    const end = Math.max(fromIndex, toIndex);

    for (let i = start; i <= end; i++) {
      selectItem(items[i]);
    }
  }

  // Get all selected items
  function getSelectedItems() {
    return Array.from(document.querySelectorAll('.outline-item.selected'));
  }

  // Update visual highlight - only show when 2+ items selected
  function updateSelectionHighlight() {
    const selected = getSelectedItems();
    if (selected.length >= 2) {
      document.getElementById('outline-tree')?.classList.add('has-multiselect');
    } else {
      document.getElementById('outline-tree')?.classList.remove('has-multiselect');
    }
  }

  // Delete all selected items
  function deleteSelectedItems() {
    const selected = getSelectedItems();
    if (selected.length === 0) return;

    // Confirm deletion for multiple items
    const count = selected.length;
    if (!confirm(`Delete ${count} item${count > 1 ? 's' : ''}?`)) {
      return;
    }

    // Capture items for undo before deletion
    const deletedItems = selected.map(item => serializeItem(item));
    pushUndo({
      type: 'delete_item',
      deletedItems: deletedItems
    });

    // Find item to focus after deletion
    const lastSelected = selected[selected.length - 1];
    let nextFocus = getNextItem(lastSelected);
    if (!nextFocus || selected.includes(nextFocus)) {
      nextFocus = getPreviousItem(selected[0]);
    }

    // Delete each selected item
    const deletePromises = selected.map(item => {
      return fetch(`/outlines/item/${item.dataset.itemId}/delete/`, {
        method: 'POST',
        headers: {
          'X-CSRFToken': getCSRFToken()
        }
      });
    });

    Promise.all(deletePromises).then(() => {
      selected.forEach(item => item.remove());
      clearSelection();
      if (nextFocus && !selected.includes(nextFocus)) {
        setFocusedItem(nextFocus);
      }
    });
  }

  // Enter edit mode on an item
  function editItem(itemElement) {
    if (!itemElement) return;

    const contentWrapper = itemElement.querySelector('.item-content-wrapper');
    if (contentWrapper) {
      // Trigger click to enter edit mode
      htmx.trigger(contentWrapper, 'click');
    }
  }

  // Focus an item's input or make it editable (legacy function name)
  // cursorPos: 'start', 'end', 'first', 'last', or null (default browser behavior)
  // cursorX: optional X coordinate to match when using 'first' or 'last'
  function focusItem(itemElement, cursorPos = null, cursorX = null) {
    pendingCursorPosition = cursorPos;
    pendingCursorX = cursorX;
    setFocusedItem(itemElement);
    editItem(itemElement);
  }

  // Find previous visible item
  function getPreviousItem(currentItem) {
    const items = getVisibleItems();
    const index = items.indexOf(currentItem);
    return index > 0 ? items[index - 1] : null;
  }

  // Find next visible item
  function getNextItem(currentItem) {
    const items = getVisibleItems();
    const index = items.indexOf(currentItem);
    return index < items.length - 1 ? items[index + 1] : null;
  }

  // Create new item after current
  function createItemAfter(currentItemId, content = '') {
    const outlineId = getOutlineId();
    if (!outlineId) return;

    const currentItem = getItemElement(currentItemId);
    const parentId = currentItem?.dataset.parentId || '';

    fetch(`/outlines/${outlineId}/item/create/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-CSRFToken': getCSRFToken()
      },
      body: `after_id=${currentItemId}&parent_id=${parentId}&content=${encodeURIComponent(content)}`
    })
    .then(response => response.text())
    .then(html => {
      // Insert new item after current
      const currentEl = getItemElement(currentItemId);
      if (currentEl) {
        currentEl.insertAdjacentHTML('afterend', html);
        // Focus the new item's input
        const newItem = currentEl.nextElementSibling;
        if (newItem) {
          htmx.process(newItem);
          // Push undo for the new item
          pushUndo({
            type: 'create_item',
            itemId: newItem.dataset.itemId
          });
          setTimeout(() => focusItem(newItem), 50);
        }
      }
    });
  }

  // Split item: create new sibling and move children to it
  function splitItem(currentItemId, content = '') {
    const currentItem = getItemElement(currentItemId);
    if (!currentItem) return;

    fetch(`/outlines/item/${currentItemId}/split/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-CSRFToken': getCSRFToken()
      },
      body: `content=${encodeURIComponent(content)}`
    })
    .then(response => response.text())
    .then(html => {
      const currentEl = getItemElement(currentItemId);
      if (currentEl) {
        // Remove children from current item (they've been moved server-side)
        const childrenContainer = currentEl.querySelector(':scope > .item-children');
        if (childrenContainer) {
          childrenContainer.remove();
        }
        // Insert new item after current
        currentEl.insertAdjacentHTML('afterend', html);
        const newItem = currentEl.nextElementSibling;
        if (newItem) {
          htmx.process(newItem);
          pushUndo({
            type: 'create_item',
            itemId: newItem.dataset.itemId
          });
          setTimeout(() => focusItem(newItem), 50);
        }
      }
    });
  }

  // Create new item before current (for Enter at position 0)
  function createItemBefore(currentItemId) {
    const outlineId = getOutlineId();
    if (!outlineId) return;

    fetch(`/outlines/${outlineId}/item/create/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-CSRFToken': getCSRFToken()
      },
      body: `before_id=${currentItemId}`
    })
    .then(response => response.text())
    .then(html => {
      // Insert new item before current
      const currentEl = getItemElement(currentItemId);
      if (currentEl) {
        currentEl.insertAdjacentHTML('beforebegin', html);
        // Focus the new item's input
        const newItem = currentEl.previousElementSibling;
        if (newItem) {
          htmx.process(newItem);
          // Push undo for the new item
          pushUndo({
            type: 'create_item',
            itemId: newItem.dataset.itemId
          });
          setTimeout(() => focusItem(newItem), 50);
        }
      }
    });
  }

  // Create new item at end of outline (for + button)
  window.createNewItem = function() {
    const outlineId = getOutlineId();
    if (!outlineId) return;

    // Find the last root item
    const items = document.querySelectorAll('.outline-tree > .outline-items > .outline-item');
    const lastItem = items[items.length - 1];
    const lastItemId = lastItem?.dataset.itemId || '';

    fetch(`/outlines/${outlineId}/item/create/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-CSRFToken': getCSRFToken()
      },
      body: `after_id=${lastItemId}&parent_id=`
    })
    .then(response => response.text())
    .then(html => {
      const itemsContainer = document.querySelector('.outline-tree > .outline-items');
      if (itemsContainer) {
        itemsContainer.insertAdjacentHTML('beforeend', html);
        const newItem = itemsContainer.lastElementChild;
        if (newItem) {
          htmx.process(newItem);
          // Push undo for the new item
          pushUndo({
            type: 'create_item',
            itemId: newItem.dataset.itemId
          });
          setTimeout(() => focusItem(newItem), 50);
        }
      }
    });
  };

  // Join item with previous item (when pressing backspace at position 0)
  function joinWithPreviousItem(itemId) {
    const itemEl = getItemElement(itemId);
    if (!itemEl) return;

    const prevItem = getPreviousItem(itemEl);
    if (!prevItem) return;

    const prevItemId = prevItem.dataset.itemId;
    const prevInput = prevItem.querySelector('.item-input');
    const prevContent = prevInput ? prevInput.value : prevItem.querySelector('.item-content')?.textContent || '';
    const cursorPos = prevContent.length;  // Cursor goes where the join happens

    fetch(`/outlines/item/${itemId}/join-with-previous/`, {
      method: 'POST',
      headers: {
        'X-CSRFToken': getCSRFToken()
      }
    })
    .then(response => response.text())
    .then(html => {
      if (html) {
        // Replace previous item with updated HTML
        prevItem.outerHTML = html;
        // Remove current item
        itemEl.remove();
        // Focus the joined item at the join point
        const newPrevItem = getItemElement(prevItemId);
        if (newPrevItem) {
          htmx.process(newPrevItem);
          focusItem(newPrevItem, cursorPos);
        }
      }
    });
  }

  // Delete item
  function deleteItem(itemId) {
    const itemEl = getItemElement(itemId);
    if (!itemEl) return;

    // Capture item for undo before deletion
    const deletedItem = serializeItem(itemEl);
    pushUndo({
      type: 'delete_item',
      deletedItems: [deletedItem]
    });

    const prevItem = getPreviousItem(itemEl);

    fetch(`/outlines/item/${itemId}/delete/`, {
      method: 'POST',
      headers: {
        'X-CSRFToken': getCSRFToken()
      }
    })
    .then(response => {
      if (response.ok) {
        itemEl.remove();
        if (prevItem) {
          setTimeout(() => focusItem(prevItem), 50);
        }
      }
    });
  }

  // Refresh the outline tree and focus an item
  function refreshTreeAndFocus(itemId, keepSelection = false, enterEditMode = false, cursorPos = null) {
    const outlineId = getOutlineId();
    if (!outlineId) return;

    // Save selection state before refresh
    const savedSelection = keepSelection ? Array.from(selectedItemIds) : [];
    const savedAnchor = keepSelection ? selectionAnchorId : null;

    const treeContainer = document.getElementById('outline-tree');
    if (treeContainer) {
      htmx.ajax('GET', `/outlines/${outlineId}/tree/`, {
        target: treeContainer,
        swap: 'innerHTML'
      }).then(() => {
        setTimeout(() => {
          // Restore selection state
          if (keepSelection && savedSelection.length > 0) {
            selectionAnchorId = savedAnchor;
            savedSelection.forEach(id => {
              const el = getItemElement(id);
              if (el) selectItem(el);
            });
          }

          const item = getItemElement(itemId);
          if (item) {
            setFocusedItem(item, keepSelection);
            if (enterEditMode) {
              editItem(item);
              // Restore cursor position after edit mode is entered
              if (cursorPos !== null) {
                setTimeout(() => {
                  const input = item.querySelector('.item-input');
                  if (input) {
                    input.setSelectionRange(cursorPos, cursorPos);
                  }
                }, 60);
              }
            }
          }
          updateSelectionHighlight();
        }, 50);
      });
    }
  }

  // Indent item (make child of previous sibling) - optimistic UI update
  function indentItem(itemId, keepSelection = false, enterEditMode = false, cursorPos = null) {
    const itemEl = getItemElement(itemId);
    if (!itemEl) return;

    // Find previous sibling
    const prevSibling = itemEl.previousElementSibling;
    if (!prevSibling || !prevSibling.classList.contains('outline-item')) {
      // Can't indent - no previous sibling
      return;
    }

    // Capture state for undo before making changes
    pushUndo({
      type: 'indent',
      itemId: itemId,
      oldParentId: itemEl.dataset.parentId || null,
      oldOrder: parseInt(itemEl.dataset.order) || 0
    });

    // Expand parent if collapsed - need to refresh from server to get all children
    if (prevSibling.classList.contains('collapsed')) {
      // Toggle collapse on server and refresh the parent item
      fetch(`/outlines/item/${prevSibling.dataset.itemId}/toggle-collapse/`, {
        method: 'POST',
        headers: { 'X-CSRFToken': getCSRFToken() }
      }).then(response => {
        if (response.ok) {
          return response.text();
        }
      }).then(html => {
        if (html) {
          // Replace the parent with expanded version from server
          const template = document.createElement('template');
          template.innerHTML = html.trim();
          const newParent = template.content.firstChild;
          prevSibling.replaceWith(newParent);

          // Process HTMX attributes on the new element
          htmx.process(newParent);

          // Now append our item to the children
          const childrenContainer = newParent.querySelector(':scope > .item-children');
          if (childrenContainer) {
            childrenContainer.appendChild(itemEl);
          }

          // Update data attributes
          itemEl.dataset.parentId = newParent.dataset.itemId;

          // Restore focus/edit mode
          if (enterEditMode) {
            editItem(itemEl);
            if (cursorPos !== null) {
              setTimeout(() => {
                const input = itemEl.querySelector('.item-input');
                if (input) {
                  input.setSelectionRange(cursorPos, cursorPos);
                }
              }, 60);
            }
          }
        }
      });

      // POST indent to server
      fetch(`/outlines/item/${itemId}/indent/`, {
        method: 'POST',
        headers: { 'X-CSRFToken': getCSRFToken() }
      });
      return;
    }

    // Optimistic DOM update (for non-collapsed parents)
    let childrenContainer = prevSibling.querySelector(':scope > .item-children');
    if (!childrenContainer) {
      // Create children container
      childrenContainer = document.createElement('div');
      childrenContainer.className = 'item-children';
      prevSibling.appendChild(childrenContainer);

      // Add collapse toggle before the bullet (if not already present)
      const itemRow = prevSibling.querySelector(':scope > .item-row');
      const existingToggle = itemRow?.querySelector('.collapse-toggle');
      if (itemRow && !existingToggle) {
        const bullet = itemRow.querySelector('.item-bullet');
        if (bullet) {
          bullet.insertAdjacentHTML('beforebegin', `<button class="collapse-toggle" title="Collapse">
            <i class="bi bi-chevron-down"></i>
          </button>`);
        }
      }
    }

    // Move the item
    childrenContainer.appendChild(itemEl);

    // Update data attributes
    itemEl.dataset.parentId = prevSibling.dataset.itemId;

    // Restore focus/edit mode
    if (enterEditMode) {
      editItem(itemEl);
      if (cursorPos !== null) {
        setTimeout(() => {
          const input = itemEl.querySelector('.item-input');
          if (input) {
            input.setSelectionRange(cursorPos, cursorPos);
          }
        }, 60);
      }
    }

    // POST to server in background
    fetch(`/outlines/item/${itemId}/indent/`, {
      method: 'POST',
      headers: {
        'X-CSRFToken': getCSRFToken()
      }
    }).then(response => {
      if (!response.ok) {
        // Revert on error - refresh tree
        refreshTreeAndFocus(itemId, keepSelection, enterEditMode, cursorPos);
      }
    });
  }

  // Outdent item (move to parent's level) - optimistic UI update
  function outdentItem(itemId, keepSelection = false, enterEditMode = false, cursorPos = null) {
    const itemEl = getItemElement(itemId);
    if (!itemEl) return;

    // Find parent item
    const parentChildren = itemEl.parentElement;
    if (!parentChildren || !parentChildren.classList.contains('item-children')) {
      // Already at root level
      return;
    }
    const parentItem = parentChildren.closest('.outline-item');
    if (!parentItem) return;

    // Find grandparent container (where we'll insert)
    const grandparentChildren = parentItem.parentElement;

    // Capture state for undo before making changes
    pushUndo({
      type: 'outdent',
      itemId: itemId,
      oldParentId: itemEl.dataset.parentId || null,
      oldOrder: parseInt(itemEl.dataset.order) || 0
    });

    // Optimistic DOM update - insert after parent
    if (grandparentChildren) {
      grandparentChildren.insertBefore(itemEl, parentItem.nextElementSibling);
    }

    // Update data attributes
    itemEl.dataset.parentId = parentItem.dataset.parentId || '';

    // Clean up empty children container
    if (parentChildren.children.length === 0) {
      parentChildren.remove();
      // Remove collapse toggle
      const collapseToggle = parentItem.querySelector(':scope > .item-row > .collapse-toggle');
      if (collapseToggle) {
        collapseToggle.remove();
      }
    }

    // Restore focus/edit mode
    if (enterEditMode) {
      editItem(itemEl);
      if (cursorPos !== null) {
        setTimeout(() => {
          const input = itemEl.querySelector('.item-input');
          if (input) {
            input.setSelectionRange(cursorPos, cursorPos);
          }
        }, 60);
      }
    }

    // POST to server in background
    fetch(`/outlines/item/${itemId}/outdent/`, {
      method: 'POST',
      headers: {
        'X-CSRFToken': getCSRFToken()
      }
    }).then(response => {
      if (!response.ok) {
        // Revert on error - refresh tree
        refreshTreeAndFocus(itemId, keepSelection, enterEditMode, cursorPos);
      }
    });
  }

  // Batch indent multiple items
  function batchIndent(itemIds, focusItemId) {
    const outlineId = getOutlineId();
    if (!outlineId) return;

    fetch(`/outlines/${outlineId}/batch-indent/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCSRFToken()
      },
      body: JSON.stringify({ item_ids: itemIds })
    })
    .then(response => {
      if (response.ok) {
        refreshTreeAndFocus(focusItemId, true);
      }
    });
  }

  // Batch outdent multiple items
  function batchOutdent(itemIds, focusItemId) {
    const outlineId = getOutlineId();
    if (!outlineId) return;

    fetch(`/outlines/${outlineId}/batch-outdent/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCSRFToken()
      },
      body: JSON.stringify({ item_ids: itemIds })
    })
    .then(response => {
      if (response.ok) {
        refreshTreeAndFocus(focusItemId, true);
      }
    });
  }

  // Move item up among siblings (optimistic UI)
  function moveItemUp(itemId, keepSelection = false, enterEditMode = false, cursorPos = null) {
    const itemEl = getItemElement(itemId);
    if (!itemEl) return;

    // Find previous sibling (must be an outline-item)
    const prevSibling = itemEl.previousElementSibling;

    // If no previous sibling, try cross-parent move
    if (!prevSibling || !prevSibling.classList.contains('outline-item')) {
      // Check if we're inside item-children (has a parent)
      const parentChildren = itemEl.parentElement;
      if (!parentChildren?.classList.contains('item-children')) return;

      const parentItem = parentChildren.closest('.outline-item');
      if (!parentItem) return;

      // Find parent's previous sibling (the "above parent")
      const aboveParent = parentItem.previousElementSibling;
      if (!aboveParent?.classList.contains('outline-item')) return;

      // Capture state for undo
      pushUndo({
        type: 'move_up',
        itemId: itemId,
        oldParentId: itemEl.dataset.parentId || null,
        oldOrder: parseInt(itemEl.dataset.order) || 0
      });

      // Handle collapsed above parent - expand it first
      if (aboveParent.classList.contains('collapsed')) {
        // Expand and fetch children from server, then append item
        fetch(`/outlines/item/${aboveParent.dataset.itemId}/toggle-collapse/`, {
          method: 'POST',
          headers: { 'X-CSRFToken': getCSRFToken() }
        }).then(response => {
          if (response.ok) return response.text();
        }).then(html => {
          if (html) {
            const template = document.createElement('template');
            template.innerHTML = html.trim();
            const newAboveParent = template.content.firstChild;
            aboveParent.replaceWith(newAboveParent);
            htmx.process(newAboveParent);

            // Move item to above parent's children (last position)
            let childrenContainer = newAboveParent.querySelector(':scope > .item-children');
            if (!childrenContainer) {
              childrenContainer = document.createElement('div');
              childrenContainer.className = 'item-children';
              newAboveParent.appendChild(childrenContainer);
            }
            childrenContainer.appendChild(itemEl);
            itemEl.dataset.parentId = newAboveParent.dataset.itemId;

            // Clean up old parent if now empty
            if (parentChildren.children.length === 0) {
              parentChildren.remove();
              const collapseToggle = parentItem.querySelector(':scope > .item-row > .collapse-toggle');
              if (collapseToggle) collapseToggle.remove();
            }

            if (enterEditMode) focusItem(itemEl, cursorPos);
          }
        });

        // POST move to server
        fetch(`/outlines/item/${itemId}/move-up/`, {
          method: 'POST',
          headers: { 'X-CSRFToken': getCSRFToken() }
        });
        return;
      }

      // Above parent is not collapsed - do optimistic DOM update
      let childrenContainer = aboveParent.querySelector(':scope > .item-children');
      if (!childrenContainer) {
        childrenContainer = document.createElement('div');
        childrenContainer.className = 'item-children';
        aboveParent.appendChild(childrenContainer);

        // Add collapse toggle
        const itemRow = aboveParent.querySelector(':scope > .item-row');
        const existingToggle = itemRow?.querySelector('.collapse-toggle');
        if (itemRow && !existingToggle) {
          const bullet = itemRow.querySelector('.item-bullet');
          if (bullet) {
            bullet.insertAdjacentHTML('beforebegin', `<button class="collapse-toggle" title="Collapse">
              <i class="bi bi-chevron-down"></i>
            </button>`);
          }
        }
      }
      childrenContainer.appendChild(itemEl);
      itemEl.dataset.parentId = aboveParent.dataset.itemId;

      // Clean up old parent if now empty
      if (parentChildren.children.length === 0) {
        parentChildren.remove();
        const collapseToggle = parentItem.querySelector(':scope > .item-row > .collapse-toggle');
        if (collapseToggle) collapseToggle.remove();
      }

      if (enterEditMode) focusItem(itemEl, cursorPos);

      // POST to server
      fetch(`/outlines/item/${itemId}/move-up/`, {
        method: 'POST',
        headers: { 'X-CSRFToken': getCSRFToken() }
      });
      return;
    }

    // Normal case: swap with previous sibling
    // Capture state for undo
    pushUndo({
      type: 'move_up',
      itemId: itemId,
      oldParentId: itemEl.dataset.parentId || null,
      oldOrder: parseInt(itemEl.dataset.order) || 0
    });

    // Optimistic DOM update: swap positions
    const parent = itemEl.parentNode;
    parent.insertBefore(itemEl, prevSibling);

    // Restore focus/selection state
    if (keepSelection && selectedItemIds.size > 0) {
      selectedItemIds.forEach(id => {
        const el = getItemElement(id);
        if (el) el.classList.add('selected');
      });
    }
    if (enterEditMode) {
      focusItem(itemEl, cursorPos);
    }

    // POST to server in background
    fetch(`/outlines/item/${itemId}/move-up/`, {
      method: 'POST',
      headers: {
        'X-CSRFToken': getCSRFToken()
      }
    })
    .then(response => {
      if (!response.ok) {
        // Server rejected - refresh to get correct state
        refreshTreeAndFocus(itemId, keepSelection, enterEditMode, cursorPos);
      }
    })
    .catch(() => {
      // Network error - refresh to get correct state
      refreshTreeAndFocus(itemId, keepSelection, enterEditMode, cursorPos);
    });
  }

  // Move item down among siblings (optimistic UI)
  function moveItemDown(itemId, keepSelection = false, enterEditMode = false, cursorPos = null) {
    const itemEl = getItemElement(itemId);
    if (!itemEl) return;

    // Find next sibling (must be an outline-item)
    const nextSibling = itemEl.nextElementSibling;

    // If no next sibling, try cross-parent move
    if (!nextSibling || !nextSibling.classList.contains('outline-item')) {
      // Check if we're inside item-children (has a parent)
      const parentChildren = itemEl.parentElement;
      if (!parentChildren?.classList.contains('item-children')) return;

      const parentItem = parentChildren.closest('.outline-item');
      if (!parentItem) return;

      // Find parent's next sibling (the "below parent")
      const belowParent = parentItem.nextElementSibling;
      if (!belowParent?.classList.contains('outline-item')) return;

      // Capture state for undo
      pushUndo({
        type: 'move_down',
        itemId: itemId,
        oldParentId: itemEl.dataset.parentId || null,
        oldOrder: parseInt(itemEl.dataset.order) || 0
      });

      // Handle collapsed below parent - expand it first
      if (belowParent.classList.contains('collapsed')) {
        // Expand and fetch children from server, then prepend item
        fetch(`/outlines/item/${belowParent.dataset.itemId}/toggle-collapse/`, {
          method: 'POST',
          headers: { 'X-CSRFToken': getCSRFToken() }
        }).then(response => {
          if (response.ok) return response.text();
        }).then(html => {
          if (html) {
            const template = document.createElement('template');
            template.innerHTML = html.trim();
            const newBelowParent = template.content.firstChild;
            belowParent.replaceWith(newBelowParent);
            htmx.process(newBelowParent);

            // Move item to below parent's children (first position)
            let childrenContainer = newBelowParent.querySelector(':scope > .item-children');
            if (!childrenContainer) {
              childrenContainer = document.createElement('div');
              childrenContainer.className = 'item-children';
              newBelowParent.appendChild(childrenContainer);
            }
            childrenContainer.insertBefore(itemEl, childrenContainer.firstChild);
            itemEl.dataset.parentId = newBelowParent.dataset.itemId;

            // Clean up old parent if now empty
            if (parentChildren.children.length === 0) {
              parentChildren.remove();
              const collapseToggle = parentItem.querySelector(':scope > .item-row > .collapse-toggle');
              if (collapseToggle) collapseToggle.remove();
            }

            if (enterEditMode) focusItem(itemEl, cursorPos);
          }
        });

        // POST move to server
        fetch(`/outlines/item/${itemId}/move-down/`, {
          method: 'POST',
          headers: { 'X-CSRFToken': getCSRFToken() }
        });
        return;
      }

      // Below parent is not collapsed - do optimistic DOM update
      let childrenContainer = belowParent.querySelector(':scope > .item-children');
      if (!childrenContainer) {
        childrenContainer = document.createElement('div');
        childrenContainer.className = 'item-children';
        belowParent.appendChild(childrenContainer);

        // Add collapse toggle
        const itemRow = belowParent.querySelector(':scope > .item-row');
        const existingToggle = itemRow?.querySelector('.collapse-toggle');
        if (itemRow && !existingToggle) {
          const bullet = itemRow.querySelector('.item-bullet');
          if (bullet) {
            bullet.insertAdjacentHTML('beforebegin', `<button class="collapse-toggle" title="Collapse">
              <i class="bi bi-chevron-down"></i>
            </button>`);
          }
        }
      }
      // Insert at first position
      childrenContainer.insertBefore(itemEl, childrenContainer.firstChild);
      itemEl.dataset.parentId = belowParent.dataset.itemId;

      // Clean up old parent if now empty
      if (parentChildren.children.length === 0) {
        parentChildren.remove();
        const collapseToggle = parentItem.querySelector(':scope > .item-row > .collapse-toggle');
        if (collapseToggle) collapseToggle.remove();
      }

      if (enterEditMode) focusItem(itemEl, cursorPos);

      // POST to server
      fetch(`/outlines/item/${itemId}/move-down/`, {
        method: 'POST',
        headers: { 'X-CSRFToken': getCSRFToken() }
      });
      return;
    }

    // Normal case: swap with next sibling
    // Capture state for undo
    pushUndo({
      type: 'move_down',
      itemId: itemId,
      oldParentId: itemEl.dataset.parentId || null,
      oldOrder: parseInt(itemEl.dataset.order) || 0
    });

    // Optimistic DOM update: swap positions (insert after next sibling)
    const parent = itemEl.parentNode;
    parent.insertBefore(itemEl, nextSibling.nextSibling);

    // Restore focus/selection state
    if (keepSelection && selectedItemIds.size > 0) {
      selectedItemIds.forEach(id => {
        const el = getItemElement(id);
        if (el) el.classList.add('selected');
      });
    }
    if (enterEditMode) {
      focusItem(itemEl, cursorPos);
    }

    // POST to server in background
    fetch(`/outlines/item/${itemId}/move-down/`, {
      method: 'POST',
      headers: {
        'X-CSRFToken': getCSRFToken()
      }
    })
    .then(response => {
      if (!response.ok) {
        // Server rejected - refresh to get correct state
        refreshTreeAndFocus(itemId, keepSelection, enterEditMode, cursorPos);
      }
    })
    .catch(() => {
      // Network error - refresh to get correct state
      refreshTreeAndFocus(itemId, keepSelection, enterEditMode, cursorPos);
    });
  }

  // Global keydown handler for item inputs
  window.handleItemKeydown = function(event, input) {
    const itemId = input.dataset.itemId;
    const itemEl = getItemElement(itemId);

    switch (event.key) {
      case 'Enter':
        if (event.shiftKey) {
          // Allow Shift+Enter to insert newline
          return;
        }
        event.preventDefault();
        if (input.value === '') {
          // Delete empty item and exit
          deleteItem(itemId);
        } else if (input.selectionStart === 0) {
          // Cursor at position 0 - create new item ABOVE (Workflowy behavior)
          htmx.trigger(input, 'blur');
          setTimeout(() => createItemBefore(itemId), 100);
        } else {
          // Split at cursor: text before stays, text after goes to new item
          const cursorPos = input.selectionStart;
          const textBefore = input.value.substring(0, cursorPos);
          const textAfter = input.value.substring(cursorPos);

          // Update current item with text before cursor
          input.value = textBefore;

          // Check if item has children
          const hasChildren = itemEl?.querySelector(':scope > .item-children > .outline-item');

          // Trigger save of current item, then create new item
          htmx.trigger(input, 'blur');
          if (hasChildren) {
            // Use split to move children to new item
            setTimeout(() => splitItem(itemId, textAfter), 100);
          } else {
            setTimeout(() => createItemAfter(itemId, textAfter), 100);
          }
        }
        break;

      case 'Backspace':
        if (event.metaKey || event.ctrlKey) {
          // Ctrl+Backspace: delete item regardless of content
          event.preventDefault();
          deleteItem(itemId);
        } else if (input.value === '') {
          // Delete if empty
          event.preventDefault();
          deleteItem(itemId);
        } else if (input.selectionStart === 0 && input.selectionEnd === 0) {
          // At position 0 with content: join with previous item
          event.preventDefault();
          htmx.trigger(input, 'blur');
          setTimeout(() => joinWithPreviousItem(itemId), 50);
        }
        break;

      case 'Tab':
        event.preventDefault();
        const cursorPos = input.selectionStart;
        // Save first (if not empty), then indent/outdent
        if (input.value !== '') {
          htmx.trigger(input, 'blur');
        }
        setTimeout(() => {
          if (event.shiftKey) {
            outdentItem(itemId, false, true, cursorPos);
          } else {
            indentItem(itemId, false, true, cursorPos);
          }
        }, 100);
        break;

      case 'ArrowUp':
        if (event.metaKey || event.ctrlKey) {
          // Move item up (optimistic - instant)
          event.preventDefault();
          const cursorPosUp = input.selectionStart;
          htmx.trigger(input, 'blur');
          moveItemUp(itemId, false, true, cursorPosUp);
        } else if (event.shiftKey) {
          // Three-stage shift selection (going up)
          const allTextSelected = input.selectionStart === 0 && input.selectionEnd === input.value.length;
          const itemIsSelected = selectedItemIds.size >= 1 && selectedItemIds.has(itemId);
          const selectionAtStart = input.selectionStart === 0;

          if (allTextSelected && itemIsSelected) {
            // Stage 3: Extend item selection upward
            event.preventDefault();
            htmx.trigger(input, 'blur');
            setTimeout(() => handleShiftArrow('up'), 50);
          } else if (allTextSelected) {
            // Stage 2: Select the item itself
            event.preventDefault();
            htmx.trigger(input, 'blur');
            selectItem(itemEl);
          } else if (selectionAtStart) {
            // Selection is at start of text - select all
            event.preventDefault();
            input.setSelectionRange(0, input.value.length);
          }
          // Otherwise let browser handle normal shift+up text selection
        } else if (input.selectionStart === input.selectionEnd) {
          // No text selection - check if on first visual line
          const { isFirstLine } = getCursorLine(input);
          if (isFirstLine) {
            const prevItem = getPreviousItem(itemEl);
            if (prevItem) {
              event.preventDefault();
              htmx.trigger(input, 'blur');
              setTimeout(() => focusItem(prevItem, 'start'), 50);
            }
          }
        }
        break;

      case 'ArrowDown':
        if (event.metaKey || event.ctrlKey) {
          // Move item down (optimistic - instant)
          event.preventDefault();
          const cursorPosDown = input.selectionStart;
          htmx.trigger(input, 'blur');
          moveItemDown(itemId, false, true, cursorPosDown);
        } else if (event.shiftKey) {
          // Three-stage shift selection (going down)
          const allTextSelected = input.selectionStart === 0 && input.selectionEnd === input.value.length;
          const itemIsSelected = selectedItemIds.size >= 1 && selectedItemIds.has(itemId);
          const selectionAtEnd = input.selectionEnd === input.value.length;

          if (allTextSelected && itemIsSelected) {
            // Stage 3: Extend item selection downward
            event.preventDefault();
            htmx.trigger(input, 'blur');
            setTimeout(() => handleShiftArrow('down'), 50);
          } else if (allTextSelected) {
            // Stage 2: Select the item itself
            event.preventDefault();
            htmx.trigger(input, 'blur');
            selectItem(itemEl);
          } else if (selectionAtEnd) {
            // Selection is at end of text - select all
            event.preventDefault();
            input.setSelectionRange(0, input.value.length);
          }
          // Otherwise let browser handle normal shift+down text selection
        } else if (input.selectionStart === input.selectionEnd) {
          // No text selection - check if on last visual line
          const { isLastLine } = getCursorLine(input);
          if (isLastLine) {
            const nextItem = getNextItem(itemEl);
            if (nextItem) {
              event.preventDefault();
              htmx.trigger(input, 'blur');
              setTimeout(() => focusItem(nextItem, 'start'), 50);
            }
          }
        }
        break;

      case 'Escape':
        event.preventDefault();
        if (input.value === '') {
          // Delete empty item
          deleteItem(itemId);
        } else {
          // Cancel edit - restore original content
          htmx.trigger(input.closest('.item-content-wrapper'), 'htmx:abort');
          htmx.ajax('GET', `/outlines/item/${itemId}/`, {
            target: input.closest('.item-content-wrapper'),
            swap: 'innerHTML'
          });
        }
        break;

      case 'h':
      case 'H':
        // Ctrl+Shift+H to toggle heading
        if ((event.metaKey || event.ctrlKey) && event.shiftKey) {
          event.preventDefault();
          const content = input.value;
          // Send content along with heading request (avoids blur which auto-deletes empty items)
          htmx.ajax('POST', `/outlines/item/${itemId}/toggle-heading/`, {
            target: `#outline-item-${itemId}`,
            swap: 'outerHTML',
            values: { content: content }
          });
        }
        break;

      case ';':
        // Ctrl+; for add source
        if (event.metaKey || event.ctrlKey) {
          event.preventDefault();
          const itemRow = input.closest('.item-row');
          if (itemRow) {
            htmx.ajax('GET', `/outlines/item/${itemId}/sources/`, {
              target: itemRow,
              swap: 'afterend'
            });
          }
        }
        break;

      case 'z':
        // Ctrl+Z for undo
        if ((event.metaKey || event.ctrlKey) && !event.shiftKey) {
          event.preventDefault();
          undo();
        }
        break;
    }
  };

  // Detect if cursor is on first/last visual line of textarea
  function getCursorLine(textarea) {
    const pos = textarea.selectionStart;
    const text = textarea.value;

    // Create measurer
    const measurer = document.createElement('div');
    document.body.appendChild(measurer);

    // Copy styles
    const style = window.getComputedStyle(textarea);
    const width = textarea.getBoundingClientRect().width;
    measurer.style.cssText = `
      position: absolute;
      visibility: hidden;
      white-space: pre-wrap;
      word-wrap: break-word;
      overflow-wrap: break-word;
      width: ${width}px;
      font-size: ${style.fontSize};
      font-family: ${style.fontFamily};
      line-height: ${style.lineHeight};
      padding: ${style.padding};
      box-sizing: ${style.boxSizing};
    `;

    // Build content with markers at cursor position and end of text
    const before = text.substring(0, pos);
    const after = text.substring(pos);
    measurer.textContent = '';

    const beforeNode = document.createTextNode(before);
    // Wrap the first character after cursor in a span to measure its line position
    const firstCharAfter = after.charAt(0) || '\u200B';
    const restAfter = after.substring(1);
    const cursorMarker = document.createElement('span');
    cursorMarker.textContent = firstCharAfter;
    const afterNode = document.createTextNode(restAfter);
    const endMarker = document.createElement('span');
    endMarker.textContent = '\u200B';

    measurer.appendChild(beforeNode);
    measurer.appendChild(cursorMarker);
    measurer.appendChild(afterNode);
    measurer.appendChild(endMarker);

    const lineHeight = parseFloat(style.lineHeight);
    const measurerRect = measurer.getBoundingClientRect();
    const cursorRect = cursorMarker.getBoundingClientRect();
    const endRect = endMarker.getBoundingClientRect();

    const markerTop = cursorRect.top - measurerRect.top;
    const endMarkerTop = endRect.top - measurerRect.top;

    // First line: marker is within first lineHeight from top
    // Last line: cursor and end of text are on the same visual line
    const isFirstLine = markerTop < lineHeight;
    const isLastLine = Math.abs(endMarkerTop - markerTop) < lineHeight * 0.5;

    // Get cursor X position relative to measurer
    const cursorX = cursorRect.left - measurerRect.left;

    // Clean up
    measurer.remove();

    return { isFirstLine, isLastLine, cursorX };
  }

  // Find the best cursor position on a specific line (first or last) to match a target X
  function findCursorPositionForX(textarea, targetX, targetLine) {
    const text = textarea.value;
    if (!text) return 0;

    // Create measurer
    const measurer = document.createElement('div');
    document.body.appendChild(measurer);

    const style = window.getComputedStyle(textarea);
    const width = textarea.getBoundingClientRect().width;
    // lineHeight might be 'normal' or a number - compute actual pixel value
    let lineHeight = parseFloat(style.lineHeight);
    if (isNaN(lineHeight) || lineHeight < 10) {
      // If it's a multiplier or 'normal', calculate from font-size
      const fontSize = parseFloat(style.fontSize);
      lineHeight = fontSize * (parseFloat(style.lineHeight) || 1.4);
    }

    measurer.style.cssText = `
      position: absolute;
      visibility: hidden;
      white-space: pre-wrap;
      word-wrap: break-word;
      overflow-wrap: break-word;
      width: ${width}px;
      font-size: ${style.fontSize};
      font-family: ${style.fontFamily};
      font-weight: ${style.fontWeight};
      line-height: ${style.lineHeight};
      padding: ${style.padding};
      box-sizing: ${style.boxSizing};
    `;

    // First, find the range of characters on the target line
    // Measure each character to find line boundaries
    let lineStart = 0;
    let lineEnd = text.length;

    // Build full content with end marker to get total height
    measurer.textContent = text + '\u200B';
    const measurerRect = measurer.getBoundingClientRect();
    const totalHeight = measurer.scrollHeight;

    // Determine target Y range based on targetLine
    let targetYMin, targetYMax;
    if (targetLine === 'first') {
      // Measure actual first character position
      measurer.innerHTML = '';
      const firstMarker = document.createElement('span');
      firstMarker.textContent = text.charAt(0) || '\u200B';
      measurer.appendChild(firstMarker);
      measurer.appendChild(document.createTextNode(text.substring(1)));
      const firstY = firstMarker.getBoundingClientRect().top - measurer.getBoundingClientRect().top;
      targetYMin = firstY - lineHeight * 0.5;
      targetYMax = firstY + lineHeight * 0.5;
    } else {
      // Last line - find where the last line starts
      measurer.innerHTML = '';
      const endMarker = document.createElement('span');
      endMarker.textContent = '\u200B';
      measurer.appendChild(document.createTextNode(text));
      measurer.appendChild(endMarker);
      const endY = endMarker.getBoundingClientRect().top - measurer.getBoundingClientRect().top;
      targetYMin = endY - lineHeight * 0.5;
      targetYMax = endY + lineHeight * 0.5;
    }

    // For single-line text or first line, just find the X position directly
    // Search all characters and find the one closest to targetX on the target line
    let bestPos = targetLine === 'first' ? 0 : text.length;
    let bestDist = Infinity;

    // Sample positions to check (more samples for longer text)
    const step = Math.max(1, Math.floor(text.length / 50));
    const positions = [];
    for (let i = 0; i <= text.length; i += step) {
      positions.push(i);
    }
    // Always include the last position
    if (positions[positions.length - 1] !== text.length) {
      positions.push(text.length);
    }

    for (const i of positions) {
      measurer.innerHTML = '';
      const beforeText = text.substring(0, i);
      const charAtPos = text.charAt(i) || '\u200B';
      const beforeNode = document.createTextNode(beforeText);
      const marker = document.createElement('span');
      marker.textContent = charAtPos;
      measurer.appendChild(beforeNode);
      measurer.appendChild(marker);

      const newMeasurerRect = measurer.getBoundingClientRect();
      const markerRect = marker.getBoundingClientRect();
      const y = markerRect.top - newMeasurerRect.top;
      const x = markerRect.left - newMeasurerRect.left;

      if (y >= targetYMin && y <= targetYMax) {
        const dist = Math.abs(x - targetX);
        if (dist < bestDist) {
          bestDist = dist;
          bestPos = i;
        }
      }
    }

    // If we found a good position, refine it by checking nearby characters
    if (bestDist < Infinity) {
      const refineStart = Math.max(0, bestPos - step);
      const refineEnd = Math.min(text.length, bestPos + step);

      for (let i = refineStart; i <= refineEnd; i++) {
        measurer.innerHTML = '';
        const beforeText = text.substring(0, i);
        const charAtPos = text.charAt(i) || '\u200B';
        const beforeNode = document.createTextNode(beforeText);
        const marker = document.createElement('span');
        marker.textContent = charAtPos;
        measurer.appendChild(beforeNode);
        measurer.appendChild(marker);

        const newMeasurerRect = measurer.getBoundingClientRect();
        const markerRect = marker.getBoundingClientRect();
        const y = markerRect.top - newMeasurerRect.top;
        const x = markerRect.left - newMeasurerRect.left;

        if (y >= targetYMin && y <= targetYMax) {
          const dist = Math.abs(x - targetX);
          if (dist < bestDist) {
            bestDist = dist;
            bestPos = i;
          }
        }
      }
    }

    measurer.remove();
    return bestPos;
  }

  // Find cursor position from click coordinates relative to textarea
  function findCursorPositionFromClick(textarea, clickX, clickY) {
    const text = textarea.value;
    if (!text) return 0;

    // Create measurer
    const measurer = document.createElement('div');
    document.body.appendChild(measurer);

    const style = window.getComputedStyle(textarea);
    const width = textarea.getBoundingClientRect().width;
    let lineHeight = parseFloat(style.lineHeight);
    if (isNaN(lineHeight) || lineHeight < 10) {
      const fontSize = parseFloat(style.fontSize);
      lineHeight = fontSize * (parseFloat(style.lineHeight) || 1.4);
    }

    measurer.style.cssText = `
      position: absolute;
      visibility: hidden;
      white-space: pre-wrap;
      word-wrap: break-word;
      overflow-wrap: break-word;
      width: ${width}px;
      font-size: ${style.fontSize};
      font-family: ${style.fontFamily};
      font-weight: ${style.fontWeight};
      line-height: ${style.lineHeight};
      padding: ${style.padding};
      box-sizing: ${style.boxSizing};
    `;

    // First, determine which visual line was clicked by finding the line's Y range
    // Sample to find all unique line Y positions
    const step = Math.max(1, Math.floor(text.length / 50));
    const lineYPositions = new Set();

    for (let i = 0; i <= text.length; i += step) {
      measurer.innerHTML = '';
      const beforeText = text.substring(0, i);
      const charAtPos = text.charAt(i) || '\u200B';
      measurer.appendChild(document.createTextNode(beforeText));
      const marker = document.createElement('span');
      marker.textContent = charAtPos;
      measurer.appendChild(marker);

      const y = marker.getBoundingClientRect().top - measurer.getBoundingClientRect().top;
      lineYPositions.add(Math.round(y));
    }

    // Find which line the click is on (click Y should be within lineHeight of line top)
    const sortedLineYs = Array.from(lineYPositions).sort((a, b) => a - b);
    let targetLineY = sortedLineYs[0];
    for (const lineY of sortedLineYs) {
      // Click is on this line if clickY is between lineY and lineY + lineHeight
      if (clickY >= lineY && clickY < lineY + lineHeight) {
        targetLineY = lineY;
        break;
      }
      // Also select this line if it's the closest one above the click
      if (lineY <= clickY) {
        targetLineY = lineY;
      }
    }

    // Now find the best X position on that line
    let bestPos = 0;
    let bestXDist = Infinity;

    for (let i = 0; i <= text.length; i++) {
      measurer.innerHTML = '';
      const beforeText = text.substring(0, i);
      const charAtPos = text.charAt(i) || '\u200B';
      measurer.appendChild(document.createTextNode(beforeText));
      const marker = document.createElement('span');
      marker.textContent = charAtPos;
      measurer.appendChild(marker);

      const newMeasurerRect = measurer.getBoundingClientRect();
      const markerRect = marker.getBoundingClientRect();
      const y = Math.round(markerRect.top - newMeasurerRect.top);
      const x = markerRect.left - newMeasurerRect.left;

      // Only consider characters on the target line
      if (Math.abs(y - targetLineY) < lineHeight * 0.5) {
        const xDist = Math.abs(x - clickX);
        if (xDist < bestXDist) {
          bestXDist = xDist;
          bestPos = i;
        }
      }
    }

    measurer.remove();
    return bestPos;
  }

  // Auto-resize textarea to fit content using a hidden measuring div
  window.autoResizeTextarea = function(textarea) {
    if (!textarea) return;

    // Create or get the measuring div
    let measurer = document.getElementById('textarea-measurer');
    if (!measurer) {
      measurer = document.createElement('div');
      measurer.id = 'textarea-measurer';
      measurer.style.cssText = 'position:absolute;visibility:hidden;white-space:pre-wrap;word-wrap:break-word;';
      document.body.appendChild(measurer);
    }

    // Copy styles that affect text measurement
    const style = window.getComputedStyle(textarea);
    measurer.style.width = style.width;
    measurer.style.fontSize = style.fontSize;
    measurer.style.fontFamily = style.fontFamily;
    measurer.style.lineHeight = style.lineHeight;
    measurer.style.padding = style.padding;
    measurer.style.boxSizing = style.boxSizing;

    // Set content (add extra character for cursor line)
    measurer.textContent = textarea.value + '\n';

    // Set textarea height to match measured height
    textarea.style.height = measurer.offsetHeight + 'px';
  }

  // Capture click position before htmx swap
  document.body.addEventListener('click', function(event) {
    // Don't overwrite if cursor position was already set programmatically
    if (pendingCursorPosition !== null) return;

    const contentWrapper = event.target.closest('.item-content-wrapper');
    if (contentWrapper && !event.target.classList.contains('item-input')) {
      // Store click position relative to the content wrapper
      const rect = contentWrapper.getBoundingClientRect();
      pendingCursorPosition = 'click';
      pendingCursorX = event.clientX - rect.left;
      pendingClickY = event.clientY - rect.top;
    }
  }, true);  // Use capture phase to run before htmx

  // Auto-focus input when edit mode is triggered
  document.body.addEventListener('htmx:afterSwap', function(event) {
    const input = event.target.querySelector('.item-input');
    if (input) {
      // Capture initial content for undo
      editStartContent = input.value;

      // Wait for browser to lay out the element before measuring
      requestAnimationFrame(() => {
        input.focus();
        // Auto-resize textarea first so measurements are accurate
        autoResizeTextarea(input);

        // Position cursor based on pending position
        if (pendingCursorPosition === 'end') {
          input.setSelectionRange(input.value.length, input.value.length);
        } else if (pendingCursorPosition === 'start') {
          input.setSelectionRange(0, 0);
        } else if (pendingCursorPosition === 'first' || pendingCursorPosition === 'last') {
          // Find best cursor position on target line matching X coordinate
          if (pendingCursorX !== null) {
            const pos = findCursorPositionForX(input, pendingCursorX, pendingCursorPosition);
            input.setSelectionRange(pos, pos);
          } else {
            // Fallback to start/end of line
            const pos = pendingCursorPosition === 'first' ? 0 : input.value.length;
            input.setSelectionRange(pos, pos);
          }
        } else if (pendingCursorPosition === 'click' && pendingCursorX !== null && pendingClickY !== null) {
          // Position cursor at click location
          const pos = findCursorPositionFromClick(input, pendingCursorX, pendingClickY);
          input.setSelectionRange(pos, pos);
        } else if (typeof pendingCursorPosition === 'number') {
          // Numeric position
          const pos = Math.min(pendingCursorPosition, input.value.length);
          input.setSelectionRange(pos, pos);
        }
        pendingCursorPosition = null;
        pendingCursorX = null;
        pendingClickY = null;

        // Ensure the item is marked as focused
        const itemEl = input.closest('.outline-item');
        if (itemEl) {
          setFocusedItem(itemEl);
        }
      });
    }
  });

  // Capture operations for undo before HTMX sends them
  document.body.addEventListener('htmx:beforeRequest', function(event) {
    const target = event.target;
    const url = event.detail.path || '';

    // Content edit undo
    if (target.classList.contains('item-input') && editStartContent !== null) {
      const newContent = target.value;
      if (newContent !== editStartContent) {
        pushUndo({
          type: 'edit_content',
          itemId: target.dataset.itemId,
          oldContent: editStartContent,
          newContent: newContent
        });
      }
      editStartContent = null;
    }

    // Toggle operations undo
    const toggleMatch = url.match(/\/outlines\/item\/(\d+)\/(toggle-collapse|toggle-heading|toggle-highlight)\//);
    if (toggleMatch) {
      const itemId = toggleMatch[1];
      const toggleType = toggleMatch[2];
      const typeMap = {
        'toggle-collapse': 'toggle_collapse',
        'toggle-heading': 'toggle_heading',
        'toggle-highlight': 'toggle_highlight'
      };
      pushUndo({
        type: typeMap[toggleType],
        itemId: itemId
      });
    }
  });

  // Handle item deletion events
  document.body.addEventListener('itemDeleted', function(event) {
    const itemId = event.detail?.itemId;
    const focusId = event.detail?.focusId;

    // Remove the deleted item from DOM
    if (itemId) {
      const deletedItem = getItemElement(itemId);
      if (deletedItem) {
        deletedItem.remove();
      }
    }

    // Focus the previous item
    if (focusId) {
      const itemEl = getItemElement(focusId);
      if (itemEl) {
        setTimeout(() => setFocusedItem(itemEl), 50);
      }
    }
  });

  // Click on item row to focus/select it
  document.body.addEventListener('click', function(event) {
    // If clicking on an input that's already active, let the browser handle cursor positioning
    if (event.target.classList.contains('item-input')) {
      return;
    }

    const itemRow = event.target.closest('.item-row');
    if (itemRow) {
      const itemEl = itemRow.closest('.outline-item');
      if (itemEl) {
        if (event.shiftKey && focusedItemId) {
          // Extend selection from focused item to clicked item
          event.preventDefault();
          event.stopPropagation();
          selectRange(focusedItemId, itemEl.dataset.itemId);
          setFocusedItem(itemEl, true);
          updateSelectionHighlight();
        } else {
          setFocusedItem(itemEl, false);
          updateSelectionHighlight();
        }
      }
    }
  }, true);  // Use capture phase to run before other handlers

  // Global keyboard navigation
  document.body.addEventListener('keydown', function(event) {
    // Skip if we're in an input field
    if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA') {
      return;
    }

    // Skip if no outline tree on page
    if (!document.getElementById('outline-tree')) {
      return;
    }

    const focusedItem = getFocusedItem();

    switch (event.key) {
      case 'ArrowUp':
        event.preventDefault();
        if (event.metaKey || event.ctrlKey) {
          // Move item up
          if (focusedItem) {
            moveItemUp(focusedItem.dataset.itemId);
          }
        } else if (event.shiftKey) {
          // Multiselect up
          handleShiftArrow('up');
        } else {
          // Navigate up and enter edit mode
          const selectedItems = getSelectedItems();
          if (selectedItems.length >= 2) {
            // Multiple items selected - select item above top selected item
            const items = getVisibleItems();
            const topSelectedIndex = Math.min(...selectedItems.map(el => items.indexOf(el)));
            if (topSelectedIndex > 0) {
              clearSelection();
              const targetItem = items[topSelectedIndex - 1];
              focusItem(targetItem, 'start');
            }
          } else if (focusedItem) {
            const prevItem = getPreviousItem(focusedItem);
            if (prevItem) {
              focusItem(prevItem, 'start');
            }
          } else {
            // Focus first item if none focused
            const items = getVisibleItems();
            if (items.length > 0) {
              focusItem(items[0], 'start');
            }
          }
        }
        break;

      case 'ArrowDown':
        event.preventDefault();
        if (event.metaKey || event.ctrlKey) {
          // Move item down
          if (focusedItem) {
            moveItemDown(focusedItem.dataset.itemId);
          }
        } else if (event.shiftKey) {
          // Multiselect down
          handleShiftArrow('down');
        } else {
          // Navigate down and enter edit mode
          const selectedItems = getSelectedItems();
          if (selectedItems.length >= 2) {
            // Multiple items selected - select item below bottom selected item
            const items = getVisibleItems();
            const bottomSelectedIndex = Math.max(...selectedItems.map(el => items.indexOf(el)));
            if (bottomSelectedIndex < items.length - 1) {
              clearSelection();
              const targetItem = items[bottomSelectedIndex + 1];
              focusItem(targetItem, 'start');
            }
          } else if (focusedItem) {
            const nextItem = getNextItem(focusedItem);
            if (nextItem) {
              focusItem(nextItem, 'start');
            }
          } else {
            // Focus first item if none focused
            const items = getVisibleItems();
            if (items.length > 0) {
              focusItem(items[0], 'start');
            }
          }
        }
        break;

      case 'Enter':
        // Enter edit mode on focused item
        if (focusedItem) {
          event.preventDefault();
          editItem(focusedItem);
        }
        break;

      case 'Tab':
        event.preventDefault();
        const selectedForTab = getSelectedItems();
        if (selectedForTab.length >= 2) {
          // Batch indent/outdent all selected items
          const itemIds = selectedForTab.map(item => parseInt(item.dataset.itemId));
          if (event.shiftKey) {
            batchOutdent(itemIds, focusedItem?.dataset.itemId);
          } else {
            batchIndent(itemIds, focusedItem?.dataset.itemId);
          }
        } else if (focusedItem) {
          if (event.shiftKey) {
            outdentItem(focusedItem.dataset.itemId, true);
          } else {
            indentItem(focusedItem.dataset.itemId, true);
          }
        }
        break;

      case 'Delete':
      case 'Backspace':
        if ((event.metaKey || event.ctrlKey)) {
          event.preventDefault();
          const selected = getSelectedItems();
          if (selected.length > 0) {
            deleteSelectedItems();
          } else if (focusedItem) {
            deleteItem(focusedItem.dataset.itemId);
          }
        }
        break;

      case 'z':
        if ((event.metaKey || event.ctrlKey) && !event.shiftKey) {
          event.preventDefault();
          undo();
        }
        break;

      case 'h':
      case 'H':
        // Ctrl+Shift+H to toggle heading
        if ((event.metaKey || event.ctrlKey) && event.shiftKey && focusedItem) {
          event.preventDefault();
          const itemId = focusedItem.dataset.itemId;
          htmx.ajax('POST', `/outlines/item/${itemId}/toggle-heading/`, {
            target: `#outline-item-${itemId}`,
            swap: 'outerHTML'
          });
        }
        break;

      case ';':
        // Ctrl+; for add source
        if ((event.metaKey || event.ctrlKey) && focusedItem) {
          event.preventDefault();
          const itemId = focusedItem.dataset.itemId;
          htmx.ajax('GET', `/outlines/item/${itemId}/sources/`, {
            target: '#htmx-modal-container'
          }).then(() => {
            const modal = new bootstrap.Modal(document.getElementById('htmx-modal-container'));
            modal.show();
          });
        }
        break;
    }
  });

  // Drag selection: mousedown starts tracking
  document.body.addEventListener('mousedown', function(event) {
    // Only track left mouse button
    if (event.button !== 0) return;

    const itemEl = event.target.closest('.outline-item');
    if (itemEl && document.getElementById('outline-tree')) {
      dragStartItemId = itemEl.dataset.itemId;
      isDragSelecting = false;
    } else {
      dragStartItemId = null;
    }
  });

  // Drag selection: mousemove detects crossing items
  document.body.addEventListener('mousemove', function(event) {
    // Only process if we have a drag start and mouse button is down
    if (!dragStartItemId || event.buttons !== 1) return;

    const currentItemEl = event.target.closest('.outline-item');
    if (!currentItemEl) return;

    const currentItemId = currentItemEl.dataset.itemId;

    // If we've moved to a different item, switch to item selection
    if (currentItemId !== dragStartItemId) {
      if (!isDragSelecting) {
        // First time crossing item boundary - switch to item selection
        isDragSelecting = true;
        // Clear any text selection
        window.getSelection().removeAllRanges();
      }

      // Clear existing selection and select range
      clearSelection();
      selectionAnchorId = dragStartItemId;
      selectRange(dragStartItemId, currentItemId);
      setFocusedItem(currentItemEl, true);
      updateSelectionHighlight();

      // Prevent text selection while drag-selecting items
      event.preventDefault();
    }
  });

  // Drag selection: mouseup ends tracking
  document.body.addEventListener('mouseup', function(event) {
    if (isDragSelecting) {
      // Clear text selection one more time to be safe
      window.getSelection().removeAllRanges();
    }
    dragStartItemId = null;
    isDragSelecting = false;
  });

  // ==========================================================================
  // Search and Replace
  // ==========================================================================

  let searchMatches = [];
  let currentMatchIndex = -1;

  function getSearchBar() {
    return document.getElementById('search-replace-bar');
  }

  function getSearchInput() {
    return document.getElementById('search-input');
  }

  function getReplaceInput() {
    return document.getElementById('replace-input');
  }

  function getSearchCount() {
    return document.getElementById('search-count');
  }

  function isSearchBarVisible() {
    const bar = getSearchBar();
    return bar && bar.classList.contains('visible');
  }

  function showSearchBar() {
    const bar = getSearchBar();
    if (bar) {
      bar.classList.add('visible');
      const input = getSearchInput();
      if (input) {
        input.focus();
        input.select();
      }
    }
    const btn = document.getElementById('search-toggle-btn');
    if (btn) btn.classList.add('active');
  }

  function hideSearchBar() {
    const bar = getSearchBar();
    if (bar) {
      bar.classList.remove('visible');
    }
    const btn = document.getElementById('search-toggle-btn');
    if (btn) btn.classList.remove('active');
    clearSearchHighlights();
    searchMatches = [];
    currentMatchIndex = -1;
    updateSearchCount();
    // Clear inputs
    const searchInput = document.getElementById('search-input');
    const replaceInput = document.getElementById('replace-input');
    if (searchInput) searchInput.value = '';
    if (replaceInput) replaceInput.value = '';
  }

  function clearSearchHighlights() {
    // Remove all search highlights from item content
    document.querySelectorAll('.item-content').forEach(el => {
      // Restore original text (remove mark tags)
      el.innerHTML = el.textContent;
    });
  }

  function highlightSearchMatches(searchTerm) {
    clearSearchHighlights();
    searchMatches = [];
    currentMatchIndex = -1;

    if (!searchTerm) {
      updateSearchCount();
      return;
    }

    const escapedTerm = searchTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(`(${escapedTerm})`, 'gi');

    document.querySelectorAll('.item-content').forEach(el => {
      const text = el.textContent;
      if (regex.test(text)) {
        const itemEl = el.closest('.outline-item');
        const itemId = itemEl?.dataset.itemId;

        // Find all match positions
        let match;
        regex.lastIndex = 0;
        while ((match = regex.exec(text)) !== null) {
          searchMatches.push({
            itemId: itemId,
            element: el,
            index: match.index
          });
        }

        // Highlight matches in the element
        el.innerHTML = text.replace(regex, '<mark class="search-match">$1</mark>');
      }
    });

    if (searchMatches.length > 0) {
      currentMatchIndex = 0;
      highlightCurrentMatch();
    }

    updateSearchCount();
  }

  function highlightCurrentMatch() {
    // Remove current highlight from all
    document.querySelectorAll('.search-match-current').forEach(el => {
      el.classList.remove('search-match-current');
    });

    if (currentMatchIndex >= 0 && currentMatchIndex < searchMatches.length) {
      const match = searchMatches[currentMatchIndex];
      const marks = match.element.querySelectorAll('.search-match');

      // Find which mark corresponds to this match
      let markIndex = 0;
      for (let i = 0; i < currentMatchIndex; i++) {
        if (searchMatches[i].element === match.element) {
          markIndex++;
        } else {
          markIndex = 0;
        }
      }

      // Count how many matches are in this element before current
      let count = 0;
      for (let i = 0; i < currentMatchIndex; i++) {
        if (searchMatches[i].element === match.element) {
          count++;
        }
      }

      if (marks[count]) {
        marks[count].classList.add('search-match-current');
        marks[count].scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }
  }

  function updateSearchCount() {
    const countEl = getSearchCount();
    if (countEl) {
      if (searchMatches.length === 0) {
        countEl.textContent = '';
      } else {
        countEl.textContent = `${currentMatchIndex + 1} of ${searchMatches.length}`;
      }
    }
  }

  function goToNextMatch() {
    if (searchMatches.length === 0) return;
    currentMatchIndex = (currentMatchIndex + 1) % searchMatches.length;
    highlightCurrentMatch();
    updateSearchCount();
  }

  function goToPrevMatch() {
    if (searchMatches.length === 0) return;
    currentMatchIndex = (currentMatchIndex - 1 + searchMatches.length) % searchMatches.length;
    highlightCurrentMatch();
    updateSearchCount();
  }

  function replaceCurrentMatch() {
    if (currentMatchIndex < 0 || currentMatchIndex >= searchMatches.length) return;

    const match = searchMatches[currentMatchIndex];
    const replaceInput = getReplaceInput();
    const searchInput = getSearchInput();
    if (!replaceInput || !searchInput) return;

    const searchTerm = searchInput.value;
    const replaceTerm = replaceInput.value;
    const itemId = match.itemId;

    // Save to server
    fetch(`/outlines/item/${itemId}/replace/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-CSRFToken': getCSRFToken()
      },
      body: `search=${encodeURIComponent(searchTerm)}&replace=${encodeURIComponent(replaceTerm)}&first_only=1`
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        // Update the content element
        const itemEl = getItemElement(itemId);
        if (itemEl) {
          const contentEl = itemEl.querySelector('.item-content');
          if (contentEl) {
            contentEl.textContent = data.content;
          }
        }
        // Re-run search to update highlights
        highlightSearchMatches(searchTerm);
      }
    });
  }

  function replaceAllMatches() {
    const searchInput = getSearchInput();
    const replaceInput = getReplaceInput();
    if (!searchInput || !replaceInput) return;

    const searchTerm = searchInput.value;
    const replaceTerm = replaceInput.value;
    const outlineId = getOutlineId();

    if (!searchTerm || !outlineId) return;

    fetch(`/outlines/${outlineId}/search-replace/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-CSRFToken': getCSRFToken()
      },
      body: `search=${encodeURIComponent(searchTerm)}&replace=${encodeURIComponent(replaceTerm)}`
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        // Refresh the tree
        htmx.trigger(document.getElementById('outline-tree'), 'outlineChanged');
        // Clear search after replace all
        setTimeout(() => {
          highlightSearchMatches(searchTerm);
        }, 300);
      }
    });
  }

  // Initialize search bar event handlers
  function initSearchBar() {
    const searchInput = getSearchInput();
    const replaceInput = getReplaceInput();
    const prevBtn = document.getElementById('search-prev');
    const nextBtn = document.getElementById('search-next');
    const replaceBtn = document.getElementById('replace-one');
    const replaceAllBtn = document.getElementById('replace-all');
    const closeBtn = document.getElementById('search-close');

    if (searchInput) {
      searchInput.addEventListener('input', function() {
        highlightSearchMatches(this.value);
      });

      searchInput.addEventListener('keydown', function(event) {
        if (event.key === 'Enter') {
          event.preventDefault();
          goToNextMatch();
        } else if (event.key === 'Escape') {
          hideSearchBar();
        }
      });
    }

    if (replaceInput) {
      replaceInput.addEventListener('keydown', function(event) {
        if (event.key === 'Enter') {
          event.preventDefault();
          replaceCurrentMatch();
          goToNextMatch();
        } else if (event.key === 'Escape') {
          hideSearchBar();
        }
      });
    }

    if (prevBtn) {
      prevBtn.addEventListener('click', goToPrevMatch);
    }

    if (nextBtn) {
      nextBtn.addEventListener('click', goToNextMatch);
    }

    if (replaceBtn) {
      replaceBtn.addEventListener('click', function() {
        replaceCurrentMatch();
      });
    }

    if (replaceAllBtn) {
      replaceAllBtn.addEventListener('click', replaceAllMatches);
    }

    if (closeBtn) {
      closeBtn.addEventListener('click', hideSearchBar);
    }
  }

  // Initialize on page load
  if (document.getElementById('search-replace-bar')) {
    initSearchBar();
  }

  // Search button click handler
  const searchToggleBtn = document.getElementById('search-toggle-btn');
  if (searchToggleBtn) {
    searchToggleBtn.addEventListener('click', function(event) {
      event.preventDefault();
      if (isSearchBarVisible()) {
        hideSearchBar();
      } else {
        showSearchBar();
      }
    });
  }

  // Global Ctrl+H handler for search/replace
  document.addEventListener('keydown', function(event) {
    if ((event.metaKey || event.ctrlKey) && event.key === 'h') {
      const bar = getSearchBar();
      if (bar) {
        event.preventDefault();
        if (isSearchBarVisible()) {
          hideSearchBar();
        } else {
          showSearchBar();
        }
      }
    }
  });

  // Sources picker: close on Escape
  document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
      const picker = document.querySelector('.sources-picker');
      if (picker) {
        picker.remove();
      }
    }
  });

  // Sources picker: close on click outside
  document.addEventListener('click', function(event) {
    const picker = document.querySelector('.sources-picker');
    if (picker && !picker.contains(event.target) && !event.target.closest('[hx-get*="/sources/"]')) {
      picker.remove();
    }
  });

})();
