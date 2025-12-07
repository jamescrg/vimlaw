/**
 * Outlines App - Keyboard Navigation and Item Operations
 */

(function() {
  'use strict';

  // Track currently focused item and selection
  let focusedItemId = null;
  let selectedItemIds = new Set();
  let selectionAnchorId = null;  // Where shift+arrow selection started

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
  }

  // Deselect a single item
  function deselectItem(itemElement) {
    if (!itemElement) return;
    const itemId = itemElement.dataset.itemId;
    selectedItemIds.delete(itemId);
    itemElement.classList.remove('selected');
  }

  // Clear all selections
  function clearSelection() {
    document.querySelectorAll('.outline-item.selected').forEach(el => {
      el.classList.remove('selected');
    });
    selectedItemIds.clear();
    selectionAnchorId = null;
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
  function focusItem(itemElement) {
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
  function createItemAfter(currentItemId) {
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
      body: `after_id=${currentItemId}&parent_id=${parentId}`
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
          setTimeout(() => focusItem(newItem), 50);
        }
      }
    });
  };

  // Delete item
  function deleteItem(itemId) {
    fetch(`/outlines/item/${itemId}/delete/`, {
      method: 'POST',
      headers: {
        'X-CSRFToken': getCSRFToken()
      }
    })
    .then(response => {
      if (response.ok) {
        const itemEl = getItemElement(itemId);
        const prevItem = getPreviousItem(itemEl);
        itemEl?.remove();
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

  // Indent item (make child of previous sibling)
  function indentItem(itemId, keepSelection = false, enterEditMode = false, cursorPos = null) {
    fetch(`/outlines/item/${itemId}/indent/`, {
      method: 'POST',
      headers: {
        'X-CSRFToken': getCSRFToken()
      }
    })
    .then(response => {
      if (response.ok) {
        refreshTreeAndFocus(itemId, keepSelection, enterEditMode, cursorPos);
      }
    });
  }

  // Outdent item (move to parent's level)
  function outdentItem(itemId, keepSelection = false, enterEditMode = false, cursorPos = null) {
    fetch(`/outlines/item/${itemId}/outdent/`, {
      method: 'POST',
      headers: {
        'X-CSRFToken': getCSRFToken()
      }
    })
    .then(response => {
      if (response.ok) {
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

  // Move item up among siblings
  function moveItemUp(itemId) {
    fetch(`/outlines/item/${itemId}/move-up/`, {
      method: 'POST',
      headers: {
        'X-CSRFToken': getCSRFToken()
      }
    })
    .then(response => {
      if (response.ok) {
        refreshTreeAndFocus(itemId);
      }
    });
  }

  // Move item down among siblings
  function moveItemDown(itemId) {
    fetch(`/outlines/item/${itemId}/move-down/`, {
      method: 'POST',
      headers: {
        'X-CSRFToken': getCSRFToken()
      }
    })
    .then(response => {
      if (response.ok) {
        refreshTreeAndFocus(itemId);
      }
    });
  }

  // Global keydown handler for item inputs
  window.handleItemKeydown = function(event, input) {
    const itemId = input.dataset.itemId;
    const itemEl = getItemElement(itemId);

    switch (event.key) {
      case 'Enter':
        // Create new item (let HTMX handle save first)
        event.preventDefault();
        setTimeout(() => createItemAfter(itemId), 100);
        break;

      case 'Backspace':
        // Delete if empty
        if (input.value === '' && input.selectionStart === 0) {
          event.preventDefault();
          deleteItem(itemId);
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
          // Move item up
          event.preventDefault();
          htmx.trigger(input, 'blur');
          setTimeout(() => moveItemUp(itemId), 100);
        } else if (event.shiftKey) {
          // Multiselect up
          event.preventDefault();
          htmx.trigger(input, 'blur');
          setTimeout(() => handleShiftArrow('up'), 50);
        } else {
          // Navigate up
          event.preventDefault();
          const prevItem = getPreviousItem(itemEl);
          if (prevItem) {
            htmx.trigger(input, 'blur');
            setTimeout(() => focusItem(prevItem), 50);
          }
        }
        break;

      case 'ArrowDown':
        if (event.metaKey || event.ctrlKey) {
          // Move item down
          event.preventDefault();
          htmx.trigger(input, 'blur');
          setTimeout(() => moveItemDown(itemId), 100);
        } else if (event.shiftKey) {
          // Multiselect down
          event.preventDefault();
          htmx.trigger(input, 'blur');
          setTimeout(() => handleShiftArrow('down'), 50);
        } else {
          // Navigate down
          event.preventDefault();
          const nextItem = getNextItem(itemEl);
          if (nextItem) {
            htmx.trigger(input, 'blur');
            setTimeout(() => focusItem(nextItem), 50);
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
    }
  };

  // Auto-focus input when edit mode is triggered
  document.body.addEventListener('htmx:afterSwap', function(event) {
    const input = event.target.querySelector('.item-input');
    if (input) {
      input.focus();
      // Place cursor at end
      input.setSelectionRange(input.value.length, input.value.length);
      // Ensure the item is marked as focused
      const itemEl = input.closest('.outline-item');
      if (itemEl) {
        setFocusedItem(itemEl);
      }
    }
  });

  // Handle item deletion events
  document.body.addEventListener('itemDeleted', function(event) {
    const focusId = event.detail?.focusId;
    if (focusId) {
      const itemEl = getItemElement(focusId);
      if (itemEl) {
        setTimeout(() => focusItem(itemEl), 50);
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
          // Navigate up
          if (focusedItem) {
            const prevItem = getPreviousItem(focusedItem);
            if (prevItem) {
              setFocusedItem(prevItem);
              updateSelectionHighlight();
            }
          } else {
            // Focus first item if none focused
            const items = getVisibleItems();
            if (items.length > 0) {
              setFocusedItem(items[0]);
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
          // Navigate down
          if (focusedItem) {
            const nextItem = getNextItem(focusedItem);
            if (nextItem) {
              setFocusedItem(nextItem);
              updateSelectionHighlight();
            }
          } else {
            // Focus first item if none focused
            const items = getVisibleItems();
            if (items.length > 0) {
              setFocusedItem(items[0]);
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
    }
  });

})();
