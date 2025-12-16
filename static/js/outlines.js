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
  let pendingSelectionStart = null;  // Start of selection range to apply
  let pendingSelectionEnd = null;  // End of selection range to apply

  // Drag selection state
  let dragStartItemId = null;  // Item where drag started
  let isDragSelecting = false;  // Whether we've switched to item selection mode

  // Undo stack
  const undoStack = [];
  const MAX_UNDO_SIZE = 50;
  let editStartContent = null;  // Content when edit mode started (for undo)

  // Temp ID to real ID resolution
  // Maps temp IDs to {promise, resolve} so operations can wait for real IDs
  const pendingItemIds = new Map();

  // Get the real item ID, waiting if it's a temp ID that hasn't resolved yet
  async function resolveItemId(itemId) {
    if (!itemId || !itemId.startsWith('temp-')) {
      return itemId;
    }
    const pending = pendingItemIds.get(itemId);
    if (pending) {
      return await pending.promise;
    }
    return itemId;
  }

  // ============================================================================
  // Input abstraction helpers (work with both textarea and contenteditable)
  // ============================================================================

  // Get text value from input (textarea or contenteditable)
  function getInputValue(input) {
    if (!input) return '';
    if (input.tagName === 'TEXTAREA') {
      return input.value;
    }
    // Contenteditable - get text without sources
    const clone = input.cloneNode(true);
    const sources = clone.querySelector('.item-sources');
    if (sources) sources.remove();
    return clone.textContent || '';
  }

  // Set text value on input
  function setInputValue(input, value) {
    if (!input) return;
    if (input.tagName === 'TEXTAREA') {
      input.value = value;
    } else {
      // Contenteditable - preserve sources
      const sources = input.querySelector('.item-sources');
      if (sources) {
        // Remove sources temporarily
        sources.remove();
        input.textContent = value;
        input.appendChild(sources);
      } else {
        input.textContent = value;
      }
    }
  }

  // Get cursor/selection start position
  function getSelectionStart(input) {
    if (!input) return 0;
    if (input.tagName === 'TEXTAREA') {
      return input.selectionStart;
    }
    // Contenteditable
    const sel = window.getSelection();
    if (!sel.rangeCount) return 0;
    const range = sel.getRangeAt(0);
    // Only count position within text nodes (not sources)
    const preRange = document.createRange();
    preRange.selectNodeContents(input);
    preRange.setEnd(range.startContainer, range.startOffset);
    // Get text length, excluding sources
    const tempDiv = document.createElement('div');
    tempDiv.appendChild(preRange.cloneContents());
    const sources = tempDiv.querySelector('.item-sources');
    if (sources) sources.remove();
    return tempDiv.textContent.length;
  }

  // Get cursor/selection end position
  function getSelectionEnd(input) {
    if (!input) return 0;
    if (input.tagName === 'TEXTAREA') {
      return input.selectionEnd;
    }
    // Contenteditable
    const sel = window.getSelection();
    if (!sel.rangeCount) return 0;
    const range = sel.getRangeAt(0);
    const preRange = document.createRange();
    preRange.selectNodeContents(input);
    preRange.setEnd(range.endContainer, range.endOffset);
    const tempDiv = document.createElement('div');
    tempDiv.appendChild(preRange.cloneContents());
    const sources = tempDiv.querySelector('.item-sources');
    if (sources) sources.remove();
    return tempDiv.textContent.length;
  }

  // Set selection range on input
  function setInputSelectionRange(input, start, end) {
    if (!input) return;
    if (input.tagName === 'TEXTAREA') {
      input.setSelectionRange(start, end);
      return;
    }
    // Contenteditable - find the text node and set range
    const sel = window.getSelection();
    const range = document.createRange();

    // Walk through text nodes to find position
    let currentPos = 0;
    let startNode = null, startOffset = 0;
    let endNode = null, endOffset = 0;

    function walkNodes(node) {
      if (startNode && endNode) return;
      if (node.nodeType === Node.TEXT_NODE) {
        const len = node.textContent.length;
        if (!startNode && currentPos + len >= start) {
          startNode = node;
          startOffset = start - currentPos;
        }
        if (!endNode && currentPos + len >= end) {
          endNode = node;
          endOffset = end - currentPos;
        }
        currentPos += len;
      } else if (node.nodeType === Node.ELEMENT_NODE && !node.classList.contains('item-sources')) {
        for (const child of node.childNodes) {
          walkNodes(child);
        }
      }
    }

    walkNodes(input);

    if (startNode && endNode) {
      range.setStart(startNode, startOffset);
      range.setEnd(endNode, endOffset);
      sel.removeAllRanges();
      sel.addRange(range);
    }
  }

  // Convert inline markdown to HTML (mirrors Python inline_markdown filter)
  function inlineMarkdown(text) {
    if (!text) return '';
    // Escape HTML first
    let html = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
    // Bold: **text** or __text__
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/__(.+?)__/g, '<strong>$1</strong>');
    // Italic: *text* or _text_
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    html = html.replace(/(?<!\w)_(.+?)_(?!\w)/g, '<em>$1</em>');
    // Colored highlights: g==, r==, p==, o==, c==
    html = html.replace(/g==(.+?)==/g, '<mark class="mark-green">$1</mark>');
    html = html.replace(/r==(.+?)==/g, '<mark class="mark-red">$1</mark>');
    html = html.replace(/p==(.+?)==/g, '<mark class="mark-purple">$1</mark>');
    html = html.replace(/o==(.+?)==/g, '<mark class="mark-orange">$1</mark>');
    html = html.replace(/c==(.+?)==/g, '<mark class="mark-citation">$1</mark>');
    // Default highlight: ==text==
    html = html.replace(/==(.+?)==/g, '<mark>$1</mark>');
    return html;
  }

  // Convert HTML back to markdown (reverse of inlineMarkdown)
  function htmlToMarkdown(html) {
    if (!html) return '';
    // Create a temporary element to parse HTML
    const temp = document.createElement('div');
    temp.innerHTML = html;

    function processNode(node) {
      if (node.nodeType === Node.TEXT_NODE) {
        return node.textContent;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) {
        return '';
      }

      const tag = node.tagName.toLowerCase();
      let content = Array.from(node.childNodes).map(processNode).join('');

      switch (tag) {
        case 'strong':
        case 'b':
          return '**' + content + '**';
        case 'em':
        case 'i':
          return '*' + content + '*';
        case 'mark':
          if (node.classList.contains('mark-green')) return 'g==' + content + '==';
          if (node.classList.contains('mark-red')) return 'r==' + content + '==';
          if (node.classList.contains('mark-purple')) return 'p==' + content + '==';
          if (node.classList.contains('mark-orange')) return 'o==' + content + '==';
          if (node.classList.contains('mark-citation')) return 'c==' + content + '==';
          return '==' + content + '==';
        default:
          return content;
      }
    }

    return Array.from(temp.childNodes).map(processNode).join('');
  }

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
    const contentEl = itemEl.querySelector(':scope > .item-row .item-text');
    const inputEl = itemEl.querySelector(':scope > .item-row .item-input');
    const content = contentEl?.textContent || (inputEl ? getInputValue(inputEl) : '') || '';
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
      case 'split':
        undoSplit(op);
        break;
      case 'join':
        undoJoin(op);
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
          const contentEl = itemEl.querySelector('.item-text');
          if (contentEl) contentEl.textContent = op.oldContent;
          const inputEl = itemEl.querySelector('.item-input');
          if (inputEl) {
            setInputValue(inputEl, op.oldContent);
            if (inputEl.tagName === 'TEXTAREA') {
              autoResizeTextarea(inputEl);
            }
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

  function undoSplit(op) {
    // Undo split: restore original item content and delete the new item
    const fullContent = op.originalContent + op.newItemContent;
    fetch(`/outlines/item/${op.originalItemId}/edit/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-CSRFToken': getCSRFToken()
      },
      body: `content=${encodeURIComponent(fullContent)}`
    }).then(response => {
      if (response.ok) {
        // Delete the new item
        return fetch(`/outlines/item/${op.newItemId}/delete/`, {
          method: 'POST',
          headers: {
            'X-CSRFToken': getCSRFToken()
          }
        });
      }
    }).then(response => {
      if (response && response.ok) {
        refreshTreeAndFocus(op.originalItemId, false, true, op.originalContent.length);
      }
    });
  }

  function undoJoin(op) {
    // Undo join: restore previous item's content and recreate the deleted item
    // First, restore the previous item's original content
    fetch(`/outlines/item/${op.prevItemId}/edit/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-CSRFToken': getCSRFToken()
      },
      body: `content=${encodeURIComponent(op.prevOriginalContent)}`
    }).then(response => {
      if (response.ok) {
        // Recreate the deleted item
        return fetch(`/outlines/${getOutlineId()}/restore-items/`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
          },
          body: JSON.stringify({
            items: [{
              parentId: op.deletedItem.parentId,
              content: op.deletedItem.content,
              order: op.deletedItem.order,
              collapsed: op.deletedItem.collapsed,
              heading: op.deletedItem.heading,
              highlight: op.deletedItem.highlight,
              children: op.deletedItem.children
            }]
          })
        });
      }
    }).then(response => {
      if (response && response.ok) {
        refreshTreeAndFocus(op.prevItemId);
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

    // Check if this would delete all items
    const allItems = document.querySelectorAll('.outline-item');
    if (selected.length >= allItems.length) {
      // Keep the first selected item but clear its content
      const keepItem = selected[0];
      const inputEl = keepItem.querySelector('.item-input');
      const textEl = keepItem.querySelector('.item-text');
      if (inputEl) setInputValue(inputEl, '');
      if (textEl) textEl.textContent = '';
      // Save empty content to server
      fetch(`/outlines/item/${keepItem.dataset.itemId}/update/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          'X-CSRFToken': getCSRFToken()
        },
        body: 'content='
      });
      // Delete the rest
      const toDelete = selected.slice(1);
      if (toDelete.length > 0) {
        const deletedItems = toDelete.map(item => serializeItem(item));
        pushUndo({
          type: 'delete_item',
          deletedItems: deletedItems
        });
        const deletePromises = toDelete.map(item => {
          return fetch(`/outlines/item/${item.dataset.itemId}/delete/`, {
            method: 'POST',
            headers: {
              'X-CSRFToken': getCSRFToken()
            }
          });
        });
        Promise.all(deletePromises).then(() => {
          toDelete.forEach(item => item.remove());
          clearSelection();
          focusItem(keepItem, 'start');
        });
      } else {
        clearSelection();
        focusItem(keepItem, 'start');
      }
      return;
    }

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

  // Copy focused or selected items to clipboard as paragraphs (with formatting for Word)
  function copyItems() {
    const selected = getSelectedItems();
    let items = [];

    if (selected.length >= 2) {
      // Multi-select: use all selected items
      items = selected;
    } else if (focusedItemId) {
      // Single focused item
      const focusedItem = getItemElement(focusedItemId);
      if (focusedItem) {
        items = [focusedItem];
      }
    }

    if (items.length === 0) return;

    // Get text and HTML content from each item
    const results = items.map(item => {
      const contentWrapper = item.querySelector('.item-content-wrapper');
      let text = '';
      let html = '';

      // Check if item is in edit mode - read from input, otherwise from view
      if (contentWrapper?.classList.contains('editing')) {
        const inputEl = item.querySelector('.item-input');
        if (inputEl) {
          // Clone and process for both text and HTML
          const clone = inputEl.cloneNode(true);
          const sources = clone.querySelector('.item-sources');
          if (sources) sources.remove();
          // Unwrap mark elements for HTML (keep bold/italic)
          clone.querySelectorAll('mark').forEach(mark => {
            mark.replaceWith(document.createTextNode(mark.textContent));
          });
          text = clone.textContent?.trim() || '';
          html = clone.innerHTML?.trim() || '';
        }
      } else {
        const textEl = item.querySelector('.item-text');
        if (textEl) {
          const clone = textEl.cloneNode(true);
          // Unwrap mark elements for HTML
          clone.querySelectorAll('mark').forEach(mark => {
            mark.replaceWith(document.createTextNode(mark.textContent));
          });
          text = clone.textContent?.trim() || '';
          html = clone.innerHTML?.trim() || '';
        }
      }

      // Strip any remaining highlight markers from text (safety net)
      text = text.replace(/[grcpo]?==/g, '');

      // Get source citations
      const sources = Array.from(item.querySelectorAll('.source-citation > a[data-bs-toggle="dropdown"]'))
        .map(a => a.textContent?.trim())
        .filter(s => s && s.length > 0);

      if (sources.length > 0) {
        const sourcesStr = ' ' + sources.join('; ');
        return { text: text + sourcesStr, html: html + sourcesStr };
      }
      return { text, html };
    }).filter(r => r.text.length > 0);

    // Join as paragraphs
    let text = results.map(r => r.text).join('\n\n');
    let html = results.map(r => '<p>' + r.html + '</p>').join('');
    // Clean up citation formatting
    text = text.replace(/\); \(/g, '; ');
    html = html.replace(/\); \(/g, '; ');

    // Copy to clipboard with visual feedback (both text and HTML for Word compatibility)
    const button = document.getElementById('copy-btn');
    const textBlob = new Blob([text], { type: 'text/plain' });
    const htmlBlob = new Blob([html], { type: 'text/html' });
    navigator.clipboard.write([
      new ClipboardItem({
        'text/plain': textBlob,
        'text/html': htmlBlob
      })
    ]).then(() => {
      if (button) {
        const originalHtml = button.innerHTML;
        button.innerHTML = '<i class="bi bi-check-lg"></i>';
        button.style.color = 'green';
        setTimeout(() => {
          button.innerHTML = originalHtml;
          button.style.color = '';
        }, 2000);
      }
    }).catch(err => {
      console.error('Failed to copy:', err);
    });
  }

  // Enter edit mode on an item
  function editItem(itemElement) {
    if (!itemElement) return;

    const contentWrapper = itemElement.querySelector('.item-content-wrapper');
    if (!contentWrapper) return;

    const input = contentWrapper.querySelector('.item-input');

    // Add editing class to show the input
    contentWrapper.classList.add('editing');

    if (input) {
      // Render markdown to HTML in input for WYSIWYG editing
      const rawContent = getInputValue(input);
      const sources = input.querySelector('.item-sources');
      // Set HTML content (preserve sources)
      if (sources) {
        input.innerHTML = inlineMarkdown(rawContent);
        input.appendChild(sources);
      } else {
        input.innerHTML = inlineMarkdown(rawContent);
      }

      // Capture initial content for undo (raw markdown)
      editStartContent = rawContent;

      // Focus and position cursor
      requestAnimationFrame(() => {
        input.focus();

        const inputLen = getInputValue(input).length;
        // Apply pending selection range if set
        if (pendingSelectionStart !== null && pendingSelectionEnd !== null) {
          const start = Math.min(pendingSelectionStart, inputLen);
          const end = Math.min(pendingSelectionEnd, inputLen);
          setInputSelectionRange(input, start, end);
          pendingSelectionStart = null;
          pendingSelectionEnd = null;
          pendingCursorPosition = null;
          pendingCursorX = null;
          pendingClickY = null;
        } else if (pendingCursorPosition === 'end') {
          // Position cursor based on pending position
          setInputSelectionRange(input, inputLen, inputLen);
        } else if (pendingCursorPosition === 'start') {
          setInputSelectionRange(input, 0, 0);
        } else if (pendingCursorPosition === 'first' || pendingCursorPosition === 'last') {
          if (pendingCursorX !== null) {
            const pos = findCursorPositionForX(input, pendingCursorX, pendingCursorPosition);
            setInputSelectionRange(input, pos, pos);
          } else {
            const pos = pendingCursorPosition === 'first' ? 0 : inputLen;
            setInputSelectionRange(input, pos, pos);
          }
        } else if (pendingCursorPosition === 'click' && pendingCursorX !== null && pendingClickY !== null) {
          const pos = findCursorPositionFromClick(input, pendingCursorX, pendingClickY);
          setInputSelectionRange(input, pos, pos);
        } else if (typeof pendingCursorPosition === 'number') {
          const pos = Math.min(pendingCursorPosition, inputLen);
          setInputSelectionRange(input, pos, pos);
        }
        pendingCursorPosition = null;
        pendingCursorX = null;
        pendingClickY = null;
      });
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
    if (!currentItem) return;
    const parentId = currentItem.dataset.parentId || '';

    // Optimistic: create temporary item immediately
    const tempId = 'temp-' + Date.now();
    const escapedContent = escapeHtml(content);
    const tempHtml = `
      <div class="outline-item" id="outline-item-${tempId}" data-item-id="${tempId}" data-parent-id="${parentId}">
        <div class="item-row">
          <div class="item-menu dropdown">
            <button class="item-menu-btn" type="button" data-bs-toggle="dropdown" aria-expanded="false">
              <i class="bi bi-three-dots-vertical"></i>
            </button>
            <ul class="dropdown-menu"></ul>
          </div>
          <span class="item-bullet">•</span>
          <div class="item-content-wrapper">
            <div class="item-view"><span class="item-text">${escapedContent}</span></div>
            <div class="item-input" contenteditable="true" data-item-id="${tempId}">${escapedContent}</div>
          </div>
        </div>
      </div>`;
    currentItem.insertAdjacentHTML('afterend', tempHtml);
    const tempItem = currentItem.nextElementSibling;

    // Register pending ID resolution
    let resolvePendingId;
    pendingItemIds.set(tempId, {
      promise: new Promise(resolve => { resolvePendingId = resolve; })
    });

    // Focus the temp item immediately
    if (tempItem) {
      focusItem(tempItem, 'start');
    }

    // Send to server
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
      // Replace temp item with real item, preserving any user changes
      if (tempItem && tempItem.parentElement) {
        // Capture current state before replacing
        const tempInput = tempItem.querySelector('.item-input');
        const currentContent = tempInput ? getInputValue(tempInput) : '';
        const currentParent = tempItem.parentElement;
        const wasFocused = document.activeElement === tempInput;
        const cursorPos = wasFocused ? getSelectionStart(tempInput) : null;

        // Insert server HTML and get new item
        tempItem.insertAdjacentHTML('afterend', html);
        const newItem = tempItem.nextElementSibling;
        tempItem.remove();

        if (newItem) {
          const realId = newItem.dataset.itemId;
          htmx.process(newItem);

          // Restore content if user typed something
          if (currentContent) {
            const newInput = newItem.querySelector('.item-input');
            const newText = newItem.querySelector('.item-text');
            if (newInput) setInputValue(newInput, currentContent);
            if (newText) newText.textContent = currentContent;
          }

          // Move to correct parent if it was indented
          const newItemParent = newItem.parentElement;
          if (currentParent !== newItemParent && currentParent.classList.contains('item-children')) {
            currentParent.appendChild(newItem);
            // Update parent ID
            const parentItem = currentParent.closest('.outline-item');
            if (parentItem) {
              newItem.dataset.parentId = parentItem.dataset.itemId;
              // Sync indent to server
              fetch(`/outlines/item/${realId}/indent/`, {
                method: 'POST',
                headers: { 'X-CSRFToken': getCSRFToken() }
              });
            }
          }

          pushUndo({
            type: 'create_item',
            itemId: realId
          });

          // Restore focus and cursor position
          if (wasFocused) {
            focusItem(newItem, cursorPos !== null ? cursorPos : 'start');
          }

          // Resolve pending ID after focus is restored (with delay for RAF)
          setTimeout(() => {
            resolvePendingId(realId);
            pendingItemIds.delete(tempId);
          }, 50);
        }
      }
    });
  }

  // Helper to escape HTML
  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // Split item: create new sibling and move children to it
  function splitItem(currentItemId, content = '') {
    const currentItem = getItemElement(currentItemId);
    if (!currentItem) return;
    const parentId = currentItem.dataset.parentId || '';

    // Capture original item's current content for undo
    const originalContent = currentItem.querySelector('.item-text')?.textContent || '';

    // Get children from current item (will be moved to new item)
    const childrenContainer = currentItem.querySelector(':scope > .item-children');
    const hadChildren = childrenContainer && childrenContainer.children.length > 0;

    // Optimistic: create temporary item immediately
    const tempId = 'temp-' + Date.now();
    let tempHtml = `
      <div class="outline-item" id="outline-item-${tempId}" data-item-id="${tempId}" data-parent-id="${parentId}">
        <div class="item-row">
          <div class="item-menu dropdown">
            <button class="item-menu-btn" type="button" data-bs-toggle="dropdown" aria-expanded="false">
              <i class="bi bi-three-dots-vertical"></i>
            </button>
            <ul class="dropdown-menu"></ul>
          </div>
          <span class="item-bullet">•</span>
          <div class="item-content-wrapper">
            <div class="item-view"><span class="item-text">${escapeHtml(content)}</span></div>
            <div class="item-input" contenteditable="true" data-item-id="${tempId}">${escapeHtml(content)}</div>
          </div>
        </div>
      </div>`;
    currentItem.insertAdjacentHTML('afterend', tempHtml);
    const tempItem = currentItem.nextElementSibling;

    // Register pending ID resolution
    let resolvePendingId;
    pendingItemIds.set(tempId, {
      promise: new Promise(resolve => { resolvePendingId = resolve; })
    });

    // Move children from current item to new item
    if (childrenContainer) {
      tempItem.appendChild(childrenContainer);
    }

    // Remove collapse toggle from current item if it had one
    const collapseToggle = currentItem.querySelector(':scope > .item-row > .collapse-toggle');
    if (collapseToggle) {
      collapseToggle.remove();
    }

    // Focus the temp item immediately
    if (tempItem) {
      focusItem(tempItem, 'start');
    }

    // Send to server
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
      // Replace temp item with real item, preserving any user changes
      if (tempItem && tempItem.parentElement) {
        // Capture current state before replacing
        const tempInput = tempItem.querySelector('.item-input');
        const currentContent = tempInput ? getInputValue(tempInput) : '';
        const currentParent = tempItem.parentElement;
        const wasFocused = document.activeElement === tempInput;
        const cursorPos = wasFocused ? getSelectionStart(tempInput) : null;

        // Insert server HTML and get new item
        tempItem.insertAdjacentHTML('afterend', html);
        const newItem = tempItem.nextElementSibling;
        tempItem.remove();

        if (newItem) {
          const realId = newItem.dataset.itemId;
          htmx.process(newItem);

          // Restore content if user typed something different
          if (currentContent && currentContent !== content) {
            const newInput = newItem.querySelector('.item-input');
            const newText = newItem.querySelector('.item-text');
            if (newInput) setInputValue(newInput, currentContent);
            if (newText) newText.textContent = currentContent;
          }

          // Move to correct parent if it was indented
          const newItemParent = newItem.parentElement;
          if (currentParent !== newItemParent && currentParent.classList.contains('item-children')) {
            currentParent.appendChild(newItem);
            // Update parent ID
            const parentItem = currentParent.closest('.outline-item');
            if (parentItem) {
              newItem.dataset.parentId = parentItem.dataset.itemId;
              // Sync indent to server
              fetch(`/outlines/item/${realId}/indent/`, {
                method: 'POST',
                headers: { 'X-CSRFToken': getCSRFToken() }
              });
            }
          }

          pushUndo({
            type: 'split',
            originalItemId: currentItemId,
            originalContent: originalContent,
            newItemId: realId,
            newItemContent: content,
            hadChildren: hadChildren
          });

          // Restore focus and cursor position
          if (wasFocused) {
            focusItem(newItem, cursorPos !== null ? cursorPos : 'start');
          }

          // Resolve pending ID after focus is restored (with delay for RAF)
          setTimeout(() => {
            resolvePendingId(realId);
            pendingItemIds.delete(tempId);
          }, 50);
        }
      }
    });
  }

  // Create new item before current (for Enter at position 0)
  function createItemBefore(currentItemId) {
    const outlineId = getOutlineId();
    if (!outlineId) return;

    const currentItem = getItemElement(currentItemId);
    if (!currentItem) return;
    const parentId = currentItem.dataset.parentId || '';

    // Optimistic: create temporary item immediately
    const tempId = 'temp-' + Date.now();
    const tempHtml = `
      <div class="outline-item" id="outline-item-${tempId}" data-item-id="${tempId}" data-parent-id="${parentId}">
        <div class="item-row">
          <div class="item-menu dropdown">
            <button class="item-menu-btn" type="button" data-bs-toggle="dropdown" aria-expanded="false">
              <i class="bi bi-three-dots-vertical"></i>
            </button>
            <ul class="dropdown-menu"></ul>
          </div>
          <span class="item-bullet">•</span>
          <div class="item-content-wrapper">
            <div class="item-view"><span class="item-text"></span></div>
            <div class="item-input" contenteditable="true" data-item-id="${tempId}"></div>
          </div>
        </div>
      </div>`;
    currentItem.insertAdjacentHTML('beforebegin', tempHtml);
    const tempItem = currentItem.previousElementSibling;

    // Register pending ID resolution
    let resolvePendingId;
    pendingItemIds.set(tempId, {
      promise: new Promise(resolve => { resolvePendingId = resolve; })
    });

    // Focus the temp item immediately
    if (tempItem) {
      focusItem(tempItem, 'start');
    }

    // Send to server
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
      // Replace temp item with real item, preserving any user changes
      if (tempItem && tempItem.parentElement) {
        // Capture current state before replacing
        const tempInput = tempItem.querySelector('.item-input');
        const currentContent = tempInput ? getInputValue(tempInput) : '';
        const currentParent = tempItem.parentElement;
        const wasFocused = document.activeElement === tempInput;
        const cursorPos = wasFocused ? getSelectionStart(tempInput) : null;

        // Insert server HTML and get new item
        tempItem.insertAdjacentHTML('afterend', html);
        const newItem = tempItem.nextElementSibling;
        tempItem.remove();

        if (newItem) {
          const realId = newItem.dataset.itemId;
          htmx.process(newItem);

          // Restore content if user typed something
          if (currentContent) {
            const newInput = newItem.querySelector('.item-input');
            const newText = newItem.querySelector('.item-text');
            if (newInput) setInputValue(newInput, currentContent);
            if (newText) newText.textContent = currentContent;
          }

          // Move to correct parent if it was indented
          const newItemParent = newItem.parentElement;
          if (currentParent !== newItemParent && currentParent.classList.contains('item-children')) {
            currentParent.appendChild(newItem);
            // Update parent ID
            const parentItem = currentParent.closest('.outline-item');
            if (parentItem) {
              newItem.dataset.parentId = parentItem.dataset.itemId;
              // Sync indent to server
              fetch(`/outlines/item/${realId}/indent/`, {
                method: 'POST',
                headers: { 'X-CSRFToken': getCSRFToken() }
              });
            }
          }

          pushUndo({
            type: 'create_item',
            itemId: realId
          });

          // Restore focus and cursor position
          if (wasFocused) {
            focusItem(newItem, cursorPos !== null ? cursorPos : 'start');
          }

          // Resolve pending ID after focus is restored (with delay for RAF)
          setTimeout(() => {
            resolvePendingId(realId);
            pendingItemIds.delete(tempId);
          }, 50);
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

    // Only join with previous sibling, not parent
    const prevSibling = itemEl.previousElementSibling;
    if (!prevSibling || !prevSibling.classList.contains('outline-item')) return;

    const prevItemId = prevSibling.dataset.itemId;

    // Get current content from the edit input (we're currently editing this item)
    const curInput = itemEl.querySelector('.item-input');
    const curContent = curInput ? getInputValue(curInput) : '';

    // Get previous sibling's content from view (source of truth)
    const prevContentEl = prevSibling.querySelector('.item-text');
    const prevContent = prevContentEl?.textContent || '';

    // Capture state for undo before making changes
    const deletedItemData = serializeItem(itemEl);
    // Override content with what's in the input (may differ from view)
    deletedItemData.content = curContent;

    const cursorPos = prevContent.length;
    const joinedContent = prevContent + curContent;

    // Move sources from current item to previous sibling
    const curSources = itemEl.querySelector('.item-input .item-sources');
    const prevSources = prevSibling.querySelector('.item-input .item-sources');
    if (curSources && prevSources) {
      while (curSources.firstChild) {
        prevSources.appendChild(curSources.firstChild);
      }
    }

    // Move any children from current item to previous sibling
    const curChildren = itemEl.querySelector(':scope > .item-children');
    if (curChildren && curChildren.children.length > 0) {
      let prevChildren = prevSibling.querySelector(':scope > .item-children');
      if (!prevChildren) {
        prevChildren = document.createElement('div');
        prevChildren.className = 'item-children';
        prevSibling.appendChild(prevChildren);
      }
      while (curChildren.firstChild) {
        prevChildren.appendChild(curChildren.firstChild);
      }
    }

    // Remove current item from DOM
    itemEl.remove();

    // Update previous sibling's view content (source of truth)
    if (prevContentEl) {
      prevContentEl.textContent = joinedContent;
    }

    // Update previous sibling's input content (for edit mode)
    const prevInput = prevSibling.querySelector('.item-input');
    if (prevInput) {
      setInputValue(prevInput, joinedContent);
    }

    // Enter edit mode on previous sibling
    focusItem(prevSibling, cursorPos);

    // Push undo before sending to server
    pushUndo({
      type: 'join',
      deletedItem: deletedItemData,
      prevItemId: prevItemId,
      prevOriginalContent: prevContent
    });

    // Send to server (wait for real ID if temp)
    resolveItemId(itemId).then(realId => {
      fetch(`/outlines/item/${realId}/join-with-previous/`, {
        method: 'POST',
        headers: {
          'X-CSRFToken': getCSRFToken()
        }
      });
    });
  }

  // Delete item
  function deleteItem(itemId) {
    const itemEl = getItemElement(itemId);
    if (!itemEl) return;

    // Check if this is the last item in the outline
    const allItems = document.querySelectorAll('.outline-item');
    if (allItems.length === 1) {
      // Don't delete the last item - clear its content instead
      const inputEl = itemEl.querySelector('.item-input');
      const textEl = itemEl.querySelector('.item-text');
      if (inputEl) setInputValue(inputEl, '');
      if (textEl) textEl.textContent = '';
      // Save empty content to server (wait for real ID if temp)
      resolveItemId(itemId).then(realId => {
        fetch(`/outlines/item/${realId}/update/`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-CSRFToken': getCSRFToken()
          },
          body: 'content='
        });
      });
      focusItem(itemEl, 'start');
      return;
    }

    // Capture item for undo before deletion
    const deletedItem = serializeItem(itemEl);
    pushUndo({
      type: 'delete_item',
      deletedItems: [deletedItem]
    });

    // Prefer next item, fall back to previous
    const nextItem = getNextItem(itemEl);
    const prevItem = getPreviousItem(itemEl);
    const focusTarget = nextItem || prevItem;

    // Wait for real ID if temp, then delete
    resolveItemId(itemId).then(realId => {
      fetch(`/outlines/item/${realId}/delete/`, {
        method: 'POST',
        headers: {
          'X-CSRFToken': getCSRFToken()
        }
      })
      .then(response => {
        if (response.ok) {
          itemEl.remove();
          if (focusTarget) {
            setTimeout(() => focusItem(focusTarget), 50);
          }
        }
      });
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
                    setInputSelectionRange(input, cursorPos, cursorPos);
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
                  setInputSelectionRange(input, cursorPos, cursorPos);
                }
              }, 60);
            }
          }
        }
      });

      // POST indent to server (wait for real ID if temp)
      resolveItemId(itemId).then(realId => {
        fetch(`/outlines/item/${realId}/indent/`, {
          method: 'POST',
          headers: { 'X-CSRFToken': getCSRFToken() }
        });
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
            setInputSelectionRange(input, cursorPos, cursorPos);
          }
        }, 60);
      }
    }

    // POST to server in background (wait for real ID if temp)
    resolveItemId(itemId).then(realId => {
      fetch(`/outlines/item/${realId}/indent/`, {
        method: 'POST',
        headers: {
          'X-CSRFToken': getCSRFToken()
        }
      }).then(response => {
        if (!response.ok) {
          // Revert on error - refresh tree
          refreshTreeAndFocus(realId, keepSelection, enterEditMode, cursorPos);
        }
      });
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
            setInputSelectionRange(input, cursorPos, cursorPos);
          }
        }, 60);
      }
    }

    // POST to server in background (wait for real ID if temp)
    resolveItemId(itemId).then(realId => {
      fetch(`/outlines/item/${realId}/outdent/`, {
        method: 'POST',
        headers: {
          'X-CSRFToken': getCSRFToken()
        }
      }).then(response => {
        if (!response.ok) {
          // Revert on error - refresh tree
          refreshTreeAndFocus(realId, keepSelection, enterEditMode, cursorPos);
        }
      });
    });
  }

  // Batch indent multiple items (optimistic)
  function batchIndent(itemIds, focusItemId) {
    const outlineId = getOutlineId();
    if (!outlineId) return;

    // Get elements in DOM order
    const items = itemIds.map(id => getItemElement(id)).filter(el => el);
    if (items.length === 0) return;

    // Find previous sibling of first item - this will be the new parent
    const firstItem = items[0];
    const prevSibling = firstItem.previousElementSibling;
    if (!prevSibling || !prevSibling.classList.contains('outline-item')) {
      return; // Can't indent - no previous sibling
    }

    // Optimistic DOM update
    let childrenContainer = prevSibling.querySelector(':scope > .item-children');
    if (!childrenContainer) {
      childrenContainer = document.createElement('div');
      childrenContainer.className = 'item-children';
      prevSibling.appendChild(childrenContainer);
    }

    // Move all selected items into the new parent
    items.forEach(item => {
      childrenContainer.appendChild(item);
      item.dataset.parentId = prevSibling.dataset.itemId;
    });

    // Maintain selection state
    clearSelection();
    items.forEach(item => selectItem(item, true));
    if (focusItemId) {
      setFocusedItem(getItemElement(focusItemId), true);
    }

    // Send to server
    fetch(`/outlines/${outlineId}/batch-indent/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCSRFToken()
      },
      body: JSON.stringify({ item_ids: itemIds })
    });
  }

  // Batch outdent multiple items (optimistic)
  function batchOutdent(itemIds, focusItemId) {
    const outlineId = getOutlineId();
    if (!outlineId) return;

    // Get elements in DOM order
    const items = itemIds.map(id => getItemElement(id)).filter(el => el);
    if (items.length === 0) return;

    // Check if first item can be outdented
    const firstItem = items[0];
    const parentChildren = firstItem.parentElement;
    if (!parentChildren || !parentChildren.classList.contains('item-children')) {
      return; // Already at root level
    }
    const parentItem = parentChildren.closest('.outline-item');
    if (!parentItem) return;

    const grandparentContainer = parentItem.parentElement;

    // Optimistic DOM update - insert all items after the parent
    let insertAfter = parentItem;
    items.forEach(item => {
      grandparentContainer.insertBefore(item, insertAfter.nextElementSibling);
      item.dataset.parentId = parentItem.dataset.parentId || '';
      insertAfter = item;
    });

    // Clean up empty children container
    if (parentChildren.children.length === 0) {
      parentChildren.remove();
      const collapseToggle = parentItem.querySelector(':scope > .item-row > .collapse-toggle');
      if (collapseToggle) {
        collapseToggle.remove();
      }
    }

    // Maintain selection state
    clearSelection();
    items.forEach(item => selectItem(item, true));
    if (focusItemId) {
      setFocusedItem(getItemElement(focusItemId), true);
    }

    // Send to server
    fetch(`/outlines/${outlineId}/batch-outdent/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCSRFToken()
      },
      body: JSON.stringify({ item_ids: itemIds })
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
        const inputValue = getInputValue(input);
        const selStart = getSelectionStart(input);
        if (inputValue === '') {
          // Delete empty item and exit
          deleteItem(itemId);
        } else if (selStart === 0) {
          // Cursor at position 0 - create new item ABOVE (Workflowy behavior)
          input.blur();
          setTimeout(() => createItemBefore(itemId), 100);
        } else {
          // Split at cursor: text before stays, text after goes to new item
          const textBefore = inputValue.substring(0, selStart);
          const textAfter = inputValue.substring(selStart);

          // Update current item with text before cursor
          setInputValue(input, textBefore);

          // Trigger save of current item, then split
          input.blur();
          // Always use splitItem for proper undo support (handles children too)
          setTimeout(() => splitItem(itemId, textAfter), 100);
        }
        break;

      case 'Delete':
        if (event.metaKey || event.ctrlKey) {
          // Ctrl+Delete: delete item regardless of content
          event.preventDefault();
          deleteItem(itemId);
        }
        break;

      case 'Backspace':
        if (getInputValue(input) === '') {
          // Delete if empty
          event.preventDefault();
          deleteItem(itemId);
        } else if (getSelectionStart(input) === 0 && getSelectionEnd(input) === 0) {
          // At position 0 with content: join with previous item
          event.preventDefault();
          joinWithPreviousItem(itemId);
        }
        break;

      case 'Tab':
        event.preventDefault();
        const cursorPos = getSelectionStart(input);
        const selectedForTab = getSelectedItems();
        // Save first (if not empty and not a temp item), then indent/outdent
        if (getInputValue(input) !== '' && !itemId.startsWith('temp-')) {
          input.blur();
        }
        // Use resolveItemId to handle temp items that may be replaced
        resolveItemId(itemId).then(realId => {
          if (selectedForTab.length >= 2) {
            // Batch indent/outdent all selected items
            const itemIds = selectedForTab.map(item => parseInt(item.dataset.itemId));
            if (event.shiftKey) {
              batchOutdent(itemIds, realId);
            } else {
              batchIndent(itemIds, realId);
            }
          } else if (event.shiftKey) {
            outdentItem(realId, false, true, cursorPos);
          } else {
            indentItem(realId, false, true, cursorPos);
          }
        });
        break;

      case 'ArrowUp':
        if (event.metaKey || event.ctrlKey) {
          // Move item up (optimistic - instant)
          event.preventDefault();
          const cursorPosUp = getSelectionStart(input);
          input.blur();
          moveItemUp(itemId, false, true, cursorPosUp);
        } else if (event.shiftKey) {
          // Extend selection upward - use same Y-position logic as non-shift
          event.preventDefault();
          const selection = window.getSelection();
          if (selection.rangeCount > 0) {
            const inputRect = input.getBoundingClientRect();

            // Get Y position of selection focus (movable end)
            const range = selection.getRangeAt(0);
            const node = selection.focusNode;
            const offset = selection.focusOffset;
            let yBefore;

            if (node && node.nodeType === Node.TEXT_NODE) {
              let charBeforeY = null, charAfterY = null;

              if (offset > 0) {
                const testRange = document.createRange();
                testRange.setStart(node, offset - 1);
                testRange.setEnd(node, offset);
                charBeforeY = testRange.getBoundingClientRect().top;
              }
              if (offset < node.textContent.length) {
                const testRange = document.createRange();
                testRange.setStart(node, offset);
                testRange.setEnd(node, offset + 1);
                charAfterY = testRange.getBoundingClientRect().top;
              }

              // For UP: prefer charAfter
              if (charAfterY !== null) {
                yBefore = charAfterY;
              } else if (charBeforeY !== null) {
                yBefore = charBeforeY;
              } else {
                yBefore = range.getBoundingClientRect().top;
              }
            } else {
              yBefore = range.getBoundingClientRect().top;
            }

            // Extend selection up
            selection.modify('extend', 'backward', 'line');

            // Get Y position after extend
            const nodeAfter = selection.focusNode;
            const offsetAfter = selection.focusOffset;
            let yAfter;

            if (nodeAfter && nodeAfter.nodeType === Node.TEXT_NODE) {
              let charAfterYAfter = null, charBeforeYAfter = null;

              if (offsetAfter > 0) {
                const testRange = document.createRange();
                testRange.setStart(nodeAfter, offsetAfter - 1);
                testRange.setEnd(nodeAfter, offsetAfter);
                charBeforeYAfter = testRange.getBoundingClientRect().top;
              }
              if (offsetAfter < nodeAfter.textContent.length) {
                const testRange = document.createRange();
                testRange.setStart(nodeAfter, offsetAfter);
                testRange.setEnd(nodeAfter, offsetAfter + 1);
                charAfterYAfter = testRange.getBoundingClientRect().top;
              }

              // After extending UP, prefer charBefore
              if (charBeforeYAfter !== null) {
                yAfter = charBeforeYAfter;
              } else if (charAfterYAfter !== null) {
                yAfter = charAfterYAfter;
              } else {
                yAfter = selection.getRangeAt(0).getBoundingClientRect().top;
              }
            } else {
              yAfter = selection.getRangeAt(0).getBoundingClientRect().top;
            }

            if (yAfter >= yBefore - 3) {
              // Didn't extend up - on first line, transition to multiselect
              input.blur();
              selectItem(itemEl);
              setTimeout(() => handleShiftArrow('up'), 50);
            }
          }
        } else if (getSelectionStart(input) === getSelectionEnd(input)) {
          // No text selection - try to move up, check if it worked
          event.preventDefault();
          const selection = window.getSelection();
          const posBefore = getSelectionStart(input);
          const text = getInputValue(input);
          const inputRect = input.getBoundingClientRect();

          // Get cursor Y by measuring character at cursor position (no DOM changes)
          // At wrap boundaries, use character X positions to determine affinity
          const range = selection.getRangeAt(0);
          const node = range.startContainer;
          const offset = range.startOffset;
          let yBefore, cursorX;

          if (node.nodeType === Node.TEXT_NODE) {
            let charBeforeY = null, charAfterY = null;
            let charBeforeX = null, charAfterX = null;

            if (offset > 0) {
              const testRange = document.createRange();
              testRange.setStart(node, offset - 1);
              testRange.setEnd(node, offset);
              const rect = testRange.getBoundingClientRect();
              charBeforeY = rect.top;
              charBeforeX = rect.right - inputRect.left;
            }
            if (offset < node.textContent.length) {
              const testRange = document.createRange();
              testRange.setStart(node, offset);
              testRange.setEnd(node, offset + 1);
              const rect = testRange.getBoundingClientRect();
              charAfterY = rect.top;
              charAfterX = rect.left - inputRect.left;
            }

            // For UP: prefer charAfter (where we're going from)
            // At wrap boundary, this correctly identifies the lower line
            if (charAfterY !== null) {
              yBefore = charAfterY;
              cursorX = charAfterX;
            } else if (charBeforeY !== null) {
              yBefore = charBeforeY;
              cursorX = charBeforeX;
            } else {
              const rangeRect = range.getBoundingClientRect();
              yBefore = rangeRect.top;
              cursorX = rangeRect.left - inputRect.left;
            }
          } else {
            // Fallback to range rect
            const rangeRect = range.getBoundingClientRect();
            yBefore = rangeRect.top;
            cursorX = rangeRect.left - inputRect.left;
          }

          // Try to move up
          selection.modify('move', 'backward', 'line');
          const posAfter = getSelectionStart(input);

          // Get Y position after move (use same char X-position affinity logic)
          const rangeAfter = selection.getRangeAt(0);
          const nodeAfter = rangeAfter.startContainer;
          const offsetAfter = rangeAfter.startOffset;
          let yAfter;

          if (nodeAfter.nodeType === Node.TEXT_NODE) {
            let charBeforeYAfter = null, charAfterYAfter = null;
            let charAfterXAfter = null;

            if (offsetAfter > 0) {
              const testRange = document.createRange();
              testRange.setStart(nodeAfter, offsetAfter - 1);
              testRange.setEnd(nodeAfter, offsetAfter);
              charBeforeYAfter = testRange.getBoundingClientRect().top;
            }
            if (offsetAfter < nodeAfter.textContent.length) {
              const testRange = document.createRange();
              testRange.setStart(nodeAfter, offsetAfter);
              testRange.setEnd(nodeAfter, offsetAfter + 1);
              const rect = testRange.getBoundingClientRect();
              charAfterYAfter = rect.top;
              charAfterXAfter = rect.left - inputRect.left;
            }

            // After moving UP, prefer charBefore for consistency
            // (we landed at "end" of line above)
            if (charBeforeYAfter !== null) {
              yAfter = charBeforeYAfter;
            } else if (charAfterYAfter !== null) {
              yAfter = charAfterYAfter;
            } else {
              yAfter = rangeAfter.getBoundingClientRect().top;
            }
          } else {
            yAfter = rangeAfter.getBoundingClientRect().top;
          }

          if (yAfter >= yBefore - 3) {
            // Didn't move up - on first line, go to previous item
            const prevItem = getPreviousItem(itemEl);
            if (prevItem) {
              input.blur();
              setTimeout(() => focusItem(prevItem, 'last', cursorX), 50);
            }
          }
          // Otherwise, already moved up within text
        }
        break;

      case 'ArrowDown':
        if (event.metaKey || event.ctrlKey) {
          // Move item down (optimistic - instant)
          event.preventDefault();
          const cursorPosDown = getSelectionStart(input);
          input.blur();
          moveItemDown(itemId, false, true, cursorPosDown);
        } else if (event.shiftKey) {
          // Extend selection downward - use same Y-position logic as non-shift
          event.preventDefault();
          const selection = window.getSelection();
          if (selection.rangeCount > 0) {
            const inputRect = input.getBoundingClientRect();

            // Get Y position of selection focus (end point)
            const range = selection.getRangeAt(0);
            // For extend, we care about the focus, not anchor
            // focusNode/focusOffset give us the movable end of selection
            const node = selection.focusNode;
            const offset = selection.focusOffset;
            let yBefore;

            if (node && node.nodeType === Node.TEXT_NODE) {
              let charBeforeY = null, charAfterY = null;

              if (offset > 0) {
                const testRange = document.createRange();
                testRange.setStart(node, offset - 1);
                testRange.setEnd(node, offset);
                charBeforeY = testRange.getBoundingClientRect().top;
              }
              if (offset < node.textContent.length) {
                const testRange = document.createRange();
                testRange.setStart(node, offset);
                testRange.setEnd(node, offset + 1);
                charAfterY = testRange.getBoundingClientRect().top;
              }

              // For DOWN: prefer charBefore
              if (charBeforeY !== null) {
                yBefore = charBeforeY;
              } else if (charAfterY !== null) {
                yBefore = charAfterY;
              } else {
                yBefore = range.getBoundingClientRect().top;
              }
            } else {
              yBefore = range.getBoundingClientRect().top;
            }

            // Extend selection down - first to end of line, then one character to next line
            selection.modify('extend', 'forward', 'lineboundary');
            selection.modify('extend', 'forward', 'character');

            // Get Y position after extend
            let nodeAfter = selection.focusNode;
            let offsetAfter = selection.focusOffset;
            let yAfter;

            if (nodeAfter && nodeAfter.nodeType === Node.TEXT_NODE) {
              let charAfterYAfter = null, charBeforeYAfter = null;

              if (offsetAfter > 0) {
                const testRange = document.createRange();
                testRange.setStart(nodeAfter, offsetAfter - 1);
                testRange.setEnd(nodeAfter, offsetAfter);
                charBeforeYAfter = testRange.getBoundingClientRect().top;
              }
              if (offsetAfter < nodeAfter.textContent.length) {
                const testRange = document.createRange();
                testRange.setStart(nodeAfter, offsetAfter);
                testRange.setEnd(nodeAfter, offsetAfter + 1);
                charAfterYAfter = testRange.getBoundingClientRect().top;
              }

              // After extending DOWN, prefer charAfter
              if (charAfterYAfter !== null) {
                yAfter = charAfterYAfter;
              } else if (charBeforeYAfter !== null) {
                yAfter = charBeforeYAfter;
              } else {
                yAfter = selection.getRangeAt(0).getBoundingClientRect().top;
              }
            } else {
              yAfter = selection.getRangeAt(0).getBoundingClientRect().top;
            }

            if (yAfter <= yBefore + 3) {
              // Didn't move down - on last line, transition to multiselect
              input.blur();
              selectItem(itemEl);
              setTimeout(() => handleShiftArrow('down'), 50);
            }
          }
        } else if (getSelectionStart(input) === getSelectionEnd(input)) {
          // No text selection - try to move down, check if it worked
          event.preventDefault();
          const selection = window.getSelection();
          const posBefore = getSelectionStart(input);
          const text = getInputValue(input);
          const inputRect = input.getBoundingClientRect();

          // Get cursor Y by measuring character at cursor position (no DOM changes)
          // At wrap boundaries, use character X positions to determine affinity
          const range = selection.getRangeAt(0);
          const node = range.startContainer;
          const offset = range.startOffset;
          let yBefore, cursorX;

          if (node.nodeType === Node.TEXT_NODE) {
            let charBeforeY = null, charAfterY = null;
            let charBeforeX = null, charAfterX = null;

            if (offset > 0) {
              const testRange = document.createRange();
              testRange.setStart(node, offset - 1);
              testRange.setEnd(node, offset);
              const rect = testRange.getBoundingClientRect();
              charBeforeY = rect.top;
              charBeforeX = rect.right - inputRect.left;
            }
            if (offset < node.textContent.length) {
              const testRange = document.createRange();
              testRange.setStart(node, offset);
              testRange.setEnd(node, offset + 1);
              const rect = testRange.getBoundingClientRect();
              charAfterY = rect.top;
              charAfterX = rect.left - inputRect.left;
            }

            // For DOWN: prefer charBefore (end-of-line perspective)
            // At wrap boundary, this correctly identifies the upper line
            if (charBeforeY !== null) {
              yBefore = charBeforeY;
              cursorX = charBeforeX;
            } else if (charAfterY !== null) {
              yBefore = charAfterY;
              cursorX = charAfterX;
            } else {
              const rangeRect = range.getBoundingClientRect();
              yBefore = rangeRect.top;
              cursorX = rangeRect.left - inputRect.left;
            }
          } else {
            // Fallback to range rect
            const rangeRect = range.getBoundingClientRect();
            yBefore = rangeRect.top;
            cursorX = rangeRect.left - inputRect.left;
          }

          // Try to move down
          selection.modify('move', 'forward', 'line');
          const posAfter = getSelectionStart(input);

          // Get Y position after move (use same char X-position affinity logic)
          const rangeAfter = selection.getRangeAt(0);
          const nodeAfter = rangeAfter.startContainer;
          const offsetAfter = rangeAfter.startOffset;
          let yAfter;

          if (nodeAfter.nodeType === Node.TEXT_NODE) {
            let charBeforeYAfter = null, charAfterYAfter = null;
            let charAfterXAfter = null;

            if (offsetAfter > 0) {
              const testRange = document.createRange();
              testRange.setStart(nodeAfter, offsetAfter - 1);
              testRange.setEnd(nodeAfter, offsetAfter);
              charBeforeYAfter = testRange.getBoundingClientRect().top;
            }
            if (offsetAfter < nodeAfter.textContent.length) {
              const testRange = document.createRange();
              testRange.setStart(nodeAfter, offsetAfter);
              testRange.setEnd(nodeAfter, offsetAfter + 1);
              const rect = testRange.getBoundingClientRect();
              charAfterYAfter = rect.top;
              charAfterXAfter = rect.left - inputRect.left;
            }

            // After moving DOWN, prefer charAfter for consistency
            // (we landed at "start" of new position)
            if (charAfterYAfter !== null) {
              yAfter = charAfterYAfter;
            } else if (charBeforeYAfter !== null) {
              yAfter = charBeforeYAfter;
            } else {
              yAfter = rangeAfter.getBoundingClientRect().top;
            }
          } else {
            yAfter = rangeAfter.getBoundingClientRect().top;
          }

          if (yAfter <= yBefore + 3) {
            // Didn't move down - on last line, go to next item
            const nextItem = getNextItem(itemEl);
            if (nextItem) {
              input.blur();
              setTimeout(() => focusItem(nextItem, 'first', cursorX), 50);
            }
          }
          // Otherwise, already moved down within text
        }
        break;

      case 'Escape':
        event.preventDefault();
        if (getInputValue(input) === '') {
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

      case 'Home':
        // Go to start of current visual line (or start of entire text with Ctrl)
        // Shift extends selection, without shift just moves cursor
        event.preventDefault();
        if (event.ctrlKey || event.metaKey) {
          // Ctrl+Home/Ctrl+Shift+Home: go to/select to start of entire item
          if (event.shiftKey) {
            // Extend selection from current position to start
            const cursorPos = getSelectionStart(input);
            setInputSelectionRange(input, 0, cursorPos);
          } else {
            // Just move cursor to start
            setInputSelectionRange(input, 0, 0);
          }
        } else {
          // Home/Shift+Home: go to/select to start of visual line
          window.getSelection().modify(
            event.shiftKey ? 'extend' : 'move',
            'backward',
            'lineboundary'
          );
        }
        break;

      case 'End':
        // Go to end of current visual line (or end of entire text with Ctrl)
        // Shift extends selection, without shift just moves cursor
        event.preventDefault();
        if (event.ctrlKey || event.metaKey) {
          // Ctrl+End/Ctrl+Shift+End: go to/select to end of entire item
          const len = getInputValue(input).length;
          if (event.shiftKey) {
            // Extend selection from current position to end
            const cursorPos = getSelectionEnd(input);
            setInputSelectionRange(input, cursorPos, len);
          } else {
            // Just move cursor to end
            setInputSelectionRange(input, len, len);
          }
        } else {
          // End/Shift+End: go to/select to end of visual line
          window.getSelection().modify(
            event.shiftKey ? 'extend' : 'move',
            'forward',
            'lineboundary'
          );
        }
        break;

      case 'h':
      case 'H':
        // Ctrl+Shift+H to toggle heading
        if ((event.metaKey || event.ctrlKey) && event.shiftKey) {
          event.preventDefault();
          const content = getInputValue(input);
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
        // Ctrl+Z - check if there's a structural undo operation pending
        if ((event.metaKey || event.ctrlKey) && !event.shiftKey) {
          // Check if the last undo operation is structural (delete, create, etc.)
          // If so, handle it here instead of letting browser do text undo
          if (undoStack.length > 0) {
            const lastOp = undoStack[undoStack.length - 1];
            if (lastOp.type === 'delete_item' || lastOp.type === 'create_item' ||
                lastOp.type === 'split' || lastOp.type === 'join') {
              event.preventDefault();
              undo();
            }
          }
        }
        break;

      case 'b':
      case 'B':
        // Ctrl+B - toggle bold on selected text or typing mode
        if ((event.metaKey || event.ctrlKey) && !event.shiftKey) {
          event.preventDefault();
          const selection = window.getSelection();
          if (selection && selection.toString().length > 0) {
            const selectedText = selection.toString();
            const range = selection.getRangeAt(0);
            // Check if selection is inside a strong element
            let parent = range.commonAncestorContainer;
            if (parent.nodeType === Node.TEXT_NODE) parent = parent.parentNode;
            const strongParent = parent.closest('strong');
            if (strongParent && strongParent.textContent === selectedText) {
              // Unwrap: replace strong with its text content
              const textNode = document.createTextNode(selectedText);
              strongParent.replaceWith(textNode);
              // Reselect the text
              const newRange = document.createRange();
              newRange.selectNodeContents(textNode);
              selection.removeAllRanges();
              selection.addRange(newRange);
            } else {
              // Wrap in strong
              const strong = document.createElement('strong');
              strong.textContent = selectedText;
              range.deleteContents();
              range.insertNode(strong);
              // Reselect the text inside strong
              const newRange = document.createRange();
              newRange.selectNodeContents(strong);
              selection.removeAllRanges();
              selection.addRange(newRange);
            }
            input.normalize();
          } else {
            // No selection - toggle bold mode for subsequent typing
            document.execCommand('bold', false, null);
          }
        }
        break;

      case 'i':
      case 'I':
        // Ctrl+I - toggle italic on selected text or typing mode
        if ((event.metaKey || event.ctrlKey) && !event.shiftKey) {
          event.preventDefault();
          const selection = window.getSelection();
          if (selection && selection.toString().length > 0) {
            const selectedText = selection.toString();
            const range = selection.getRangeAt(0);
            // Check if selection is inside an em element
            let parent = range.commonAncestorContainer;
            if (parent.nodeType === Node.TEXT_NODE) parent = parent.parentNode;
            const emParent = parent.closest('em');
            if (emParent && emParent.textContent === selectedText) {
              // Unwrap: replace em with its text content
              const textNode = document.createTextNode(selectedText);
              emParent.replaceWith(textNode);
              // Reselect the text
              const newRange = document.createRange();
              newRange.selectNodeContents(textNode);
              selection.removeAllRanges();
              selection.addRange(newRange);
            } else {
              // Wrap in em
              const em = document.createElement('em');
              em.textContent = selectedText;
              range.deleteContents();
              range.insertNode(em);
              // Reselect the text inside em
              const newRange = document.createRange();
              newRange.selectNodeContents(em);
              selection.removeAllRanges();
              selection.addRange(newRange);
            }
            input.normalize();
          } else {
            // No selection - toggle italic mode for subsequent typing
            document.execCommand('italic', false, null);
          }
        }
        break;

      case 'y':
      case 'g':
      case 'r':
      case 'p':
      case 'o':
        // Alt+Y/G/R/P/O - wrap selected text with <mark> element
        if (event.altKey && !event.ctrlKey && !event.metaKey) {
          const selection = window.getSelection();
          if (selection && selection.toString().length > 0) {
            event.preventDefault();
            const selectedText = selection.toString();
            const range = selection.getRangeAt(0);
            // Create mark element with appropriate class
            const mark = document.createElement('mark');
            if (event.key === 'g') mark.className = 'mark-green';
            else if (event.key === 'r') mark.className = 'mark-red';
            else if (event.key === 'p') mark.className = 'mark-purple';
            else if (event.key === 'o') mark.className = 'mark-orange';
            mark.textContent = selectedText;
            range.deleteContents();
            range.insertNode(mark);
            // Clean up: prevent nested/overlapping marks
            input.normalize(); // Merge adjacent text nodes
            input.querySelectorAll('mark:empty').forEach(m => m.remove());
            input.querySelectorAll('mark mark').forEach(inner => {
              const parent = inner.parentNode;
              while (inner.firstChild) {
                parent.insertBefore(inner.firstChild, inner);
              }
              inner.remove();
            });
            // Collapse selection to end
            selection.collapseToEnd();
          }
        }
        break;

      case 'c':
        // Alt+C - remove highlight (unwrap <mark> elements)
        if (event.altKey && !event.ctrlKey && !event.metaKey) {
          event.preventDefault();
          const selection = window.getSelection();
          if (selection && selection.rangeCount > 0) {
            // If text is selected, replace with plain text (removes any formatting)
            if (selection.toString().length > 0) {
              const text = selection.toString();
              const range = selection.getRangeAt(0);
              range.deleteContents();
              range.insertNode(document.createTextNode(text));
              selection.collapseToEnd();
            } else {
              // No selection - find and unwrap parent mark element
              let node = selection.anchorNode;
              // If we're in a text node, start from its parent
              if (node && node.nodeType === Node.TEXT_NODE) {
                node = node.parentNode;
              }
              while (node && node !== input) {
                if (node.nodeName === 'MARK') {
                  // Unwrap the mark element
                  const parent = node.parentNode;
                  const textNode = document.createTextNode(node.textContent);
                  parent.replaceChild(textNode, node);
                  break;
                }
                node = node.parentNode;
              }
            }
          }
        }
        break;
    }
  };

  // Detect if cursor is on first/last visual line of input (contenteditable)
  // Uses Selection.modify() which correctly handles cursor affinity at wrap boundaries
  function getCursorLine(input) {
    const text = getInputValue(input);
    const selection = window.getSelection();
    if (!selection.rangeCount || !text) {
      return { isFirstLine: true, isLastLine: true, cursorX: 0 };
    }

    // Save current selection
    const savedRange = selection.getRangeAt(0).cloneRange();

    // Get cursor's current screen position for X coordinate
    const cursorRect = savedRange.getBoundingClientRect();
    const inputRect = input.getBoundingClientRect();
    const cursorX = cursorRect.left - inputRect.left;

    // Find line boundaries using Selection.modify (respects cursor affinity)
    selection.modify('move', 'forward', 'lineboundary');
    const lineEndPos = getSelectionStart(input);

    selection.modify('move', 'backward', 'lineboundary');
    const lineStartPos = getSelectionStart(input);

    // Restore original selection
    selection.removeAllRanges();
    selection.addRange(savedRange);

    const isFirstLine = lineStartPos === 0;
    const isLastLine = lineEndPos >= text.length;

    return { isFirstLine, isLastLine, cursorX };
  }

  // Find the best cursor position on a specific line (first or last) to match a target X
  function findCursorPositionForX(input, targetX, targetLine) {
    const text = getInputValue(input);
    if (!text) return 0;

    // Create measurer
    const measurer = document.createElement('div');
    document.body.appendChild(measurer);

    const style = window.getComputedStyle(input);
    // For inline elements, use parent container width for wrapping calculation
    const wrapper = input.closest('.item-content-wrapper');
    let width;
    if (wrapper) {
      const wrapperStyle = window.getComputedStyle(wrapper);
      width = wrapper.getBoundingClientRect().width - parseFloat(wrapperStyle.paddingLeft) - parseFloat(wrapperStyle.paddingRight);
    } else {
      width = input.getBoundingClientRect().width;
    }
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

  // Find cursor position from click coordinates relative to input
  function findCursorPositionFromClick(input, clickX, clickY) {
    const text = getInputValue(input);
    if (!text) return 0;

    // Create measurer
    const measurer = document.createElement('div');
    document.body.appendChild(measurer);

    const style = window.getComputedStyle(input);
    // For inline elements, use parent container width for wrapping calculation
    const wrapper = input.closest('.item-content-wrapper');
    let width;
    if (wrapper) {
      const wrapperStyle = window.getComputedStyle(wrapper);
      width = wrapper.getBoundingClientRect().width - parseFloat(wrapperStyle.paddingLeft) - parseFloat(wrapperStyle.paddingRight);
    } else {
      width = input.getBoundingClientRect().width;
    }
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
      document.body.appendChild(measurer);
    }

    // Copy styles that affect text measurement
    const style = window.getComputedStyle(textarea);
    const wrapper = textarea.closest('.item-content-wrapper');
    const maxWidth = wrapper ? wrapper.clientWidth : parseFloat(style.maxWidth) || 500;

    measurer.style.cssText = 'position:absolute;visibility:hidden;';
    measurer.style.fontSize = style.fontSize;
    measurer.style.fontFamily = style.fontFamily;
    measurer.style.lineHeight = style.lineHeight;
    measurer.style.padding = style.padding;
    measurer.style.boxSizing = style.boxSizing;

    // First measure natural width (no wrapping)
    measurer.style.whiteSpace = 'pre';
    measurer.style.width = 'auto';
    measurer.textContent = textarea.value || ' ';
    let naturalWidth = measurer.offsetWidth + 2; // +2 for cursor

    // Cap width at container width (accounting for sources that may follow)
    const targetWidth = Math.min(naturalWidth, maxWidth);
    textarea.style.width = targetWidth + 'px';

    // Now measure height with wrapping enabled at that width
    measurer.style.whiteSpace = 'pre-wrap';
    measurer.style.wordWrap = 'break-word';
    measurer.style.width = targetWidth + 'px';
    measurer.textContent = textarea.value + '\n';

    // Set textarea height to match measured height
    textarea.style.height = measurer.offsetHeight + 'px';
  }

  // Get text content from contenteditable, excluding sources
  window.getEditableContent = function(el) {
    if (!el) return '';
    // Clone the element to avoid modifying the original
    const clone = el.cloneNode(true);
    // Remove sources from clone
    const sources = clone.querySelector('.item-sources');
    if (sources) sources.remove();
    // Get text content, preserving line breaks
    return clone.textContent || '';
  }

  // Auto-resize contenteditable (no-op since it auto-sizes, but keep for compatibility)
  window.autoResizeInput = function(el) {
    // Contenteditable divs auto-size, nothing needed
  }

  // Capture click position before htmx swap
  document.body.addEventListener('click', function(event) {
    // Don't overwrite if cursor position was already set programmatically
    if (pendingCursorPosition !== null) return;

    const contentWrapper = event.target.closest('.item-content-wrapper');
    if (contentWrapper && !event.target.closest('.item-input')) {
      // Store click position relative to the content wrapper
      const rect = contentWrapper.getBoundingClientRect();
      pendingCursorPosition = 'click';
      pendingCursorX = event.clientX - rect.left;
      pendingClickY = event.clientY - rect.top;
    }
  }, true);  // Use capture phase to run before htmx

  // Copy button in toolbar
  const copyBtn = document.getElementById('copy-btn');
  if (copyBtn) {
    copyBtn.addEventListener('click', function(event) {
      event.preventDefault();
      copyItems();
    });
  }

  // Auto-focus input when a new item is created via HTMX swap
  document.body.addEventListener('htmx:afterSwap', function(event) {
    // Only handle swaps that create new items, not our preloaded edit mode toggle
    const contentWrapper = event.target.closest('.item-content-wrapper');
    if (contentWrapper && contentWrapper.classList.contains('editing')) {
      // Already in edit mode via our toggle - don't interfere
      return;
    }

    const input = event.target.querySelector('.item-input');
    if (input && pendingCursorPosition !== null) {
      // This is likely a new item swap - enter edit mode
      const itemEl = input.closest('.outline-item');
      if (itemEl) {
        editItem(itemEl);
      }
    }
  });

  // Handle focus on contenteditable to update focused item
  document.body.addEventListener('focusin', function(event) {
    if (event.target.classList.contains('item-input')) {
      const itemEl = event.target.closest('.outline-item');
      if (itemEl) {
        setFocusedItem(itemEl);
      }
    }
  });

  // Exit edit mode on blur and save
  document.body.addEventListener('focusout', function(event) {
    const input = event.target;
    if (!input.classList.contains('item-input')) return;

    const itemId = input.dataset.itemId;
    // Get HTML content (excluding sources) and convert to markdown
    const clone = input.cloneNode(true);
    const sourcesInClone = clone.querySelector('.item-sources');
    if (sourcesInClone) sourcesInClone.remove();
    const content = htmlToMarkdown(clone.innerHTML);
    const contentWrapper = input.closest('.item-content-wrapper');

    // Update view mode content and exit edit mode
    if (contentWrapper) {
      const viewContent = contentWrapper.querySelector('.item-text');
      if (viewContent) {
        viewContent.innerHTML = inlineMarkdown(content);
      }
      contentWrapper.classList.remove('editing');

      // Restore raw markdown in input for next edit
      const sources = input.querySelector('.item-sources');
      if (sources) {
        input.textContent = content;
        input.appendChild(sources);
      } else {
        input.textContent = content;
      }
    }

    // Save to server (skip temp items)
    if (itemId && !itemId.startsWith('temp-')) {
      // Push undo if content changed
      if (editStartContent !== null && content !== editStartContent) {
        pushUndo({
          type: 'edit_content',
          itemId: itemId,
          oldContent: editStartContent,
          newContent: content
        });
      }
      editStartContent = null;

      // Save via fetch
      fetch(`/outlines/item/${itemId}/edit/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          'X-CSRFToken': getCSRFToken()
        },
        body: `content=${encodeURIComponent(content)}`
      }).catch(err => console.error('Save failed:', err));
    }
  });

  // Capture operations for undo before HTMX sends them
  document.body.addEventListener('htmx:beforeRequest', function(event) {
    const target = event.target;
    const url = event.detail.path || '';

    // Content edit undo
    if (target.classList.contains('item-input') && editStartContent !== null) {
      const newContent = getInputValue(target);
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
    if (event.target.closest('.item-input')) {
      return;
    }

    // Skip clicks on sources (dropdowns)
    if (event.target.closest('.item-sources')) {
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
          // Check if clicking on content area to enter edit mode
          const contentWrapper = event.target.closest('.item-content-wrapper');
          if (contentWrapper && !contentWrapper.classList.contains('editing')) {
            // Check if user selected text (click and drag)
            const selection = window.getSelection();
            if (selection && selection.toString().length > 0) {
              // User selected text - enter edit mode but preserve selection
              const viewContent = contentWrapper.querySelector('.item-text');
              if (viewContent && viewContent.contains(selection.anchorNode)) {
                // Calculate selection offsets relative to text content
                const range = selection.getRangeAt(0);
                const preSelectionRange = range.cloneRange();
                preSelectionRange.selectNodeContents(viewContent);
                preSelectionRange.setEnd(range.startContainer, range.startOffset);
                const selStart = preSelectionRange.toString().length;
                const selEnd = selStart + selection.toString().length;

                // Set pending selection range for editItem to apply
                pendingSelectionStart = selStart;
                pendingSelectionEnd = selEnd;
                setFocusedItem(itemEl, false);
                editItem(itemEl);
                updateSelectionHighlight();
                return;
              }
            }
            // Capture click position relative to content wrapper for cursor placement
            const rect = contentWrapper.getBoundingClientRect();
            pendingCursorPosition = 'click';
            pendingCursorX = event.clientX - rect.left;
            pendingClickY = event.clientY - rect.top;
            setFocusedItem(itemEl, false);
            editItem(itemEl);
            updateSelectionHighlight();
            return;
          }
          setFocusedItem(itemEl, false);
          updateSelectionHighlight();
        }
      }
    }
  }, true);  // Use capture phase to run before other handlers

  // Global keyboard navigation
  document.body.addEventListener('keydown', function(event) {
    // Skip if we're in an input field or contenteditable
    if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA' || event.target.isContentEditable) {
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

    // Don't interfere with text selection in edit mode
    if (event.target.closest('.item-input')) {
      dragStartItemId = null;
      return;
    }

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
    document.querySelectorAll('.item-text').forEach(el => {
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

    document.querySelectorAll('.item-text').forEach(el => {
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
          const contentEl = itemEl.querySelector('.item-text');
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

  // Handle copy in item inputs - preserve bold/italic for Word compatibility
  document.addEventListener('copy', function(event) {
    const input = event.target.closest('.item-input');
    if (!input) return;

    const selection = window.getSelection();
    if (!selection.rangeCount) return;

    // Get the selected text content
    let text = selection.toString();
    if (!text) return;

    event.preventDefault();

    // Normalize line breaks - collapse multiple newlines to single
    text = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    text = text.replace(/\n{2,}/g, '\n');

    // Get HTML content from selection for rich text paste (Word compatibility)
    const range = selection.getRangeAt(0);
    const fragment = range.cloneContents();
    const tempDiv = document.createElement('div');
    tempDiv.appendChild(fragment);
    // Remove sources from copied content
    tempDiv.querySelectorAll('.item-sources').forEach(s => s.remove());
    // Unwrap mark elements (remove highlighting, keep text)
    tempDiv.querySelectorAll('mark').forEach(mark => {
      mark.replaceWith(document.createTextNode(mark.textContent));
    });
    const html = tempDiv.innerHTML;

    // Set both plain text and HTML to clipboard
    event.clipboardData.setData('text/plain', text);
    event.clipboardData.setData('text/html', html);
  });

  // Handle cut in item inputs - same cleanup as copy
  document.addEventListener('cut', function(event) {
    const input = event.target.closest('.item-input');
    if (!input) return;

    const selection = window.getSelection();
    if (!selection.rangeCount) return;

    let text = selection.toString();
    if (!text) return;

    event.preventDefault();

    // Normalize line breaks
    text = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    text = text.replace(/\n{2,}/g, '\n');

    // Get HTML content from selection for rich text paste (Word compatibility)
    const range = selection.getRangeAt(0);
    const fragment = range.cloneContents();
    const tempDiv = document.createElement('div');
    tempDiv.appendChild(fragment);
    // Remove sources from copied content
    tempDiv.querySelectorAll('.item-sources').forEach(s => s.remove());
    // Unwrap mark elements (remove highlighting, keep text)
    tempDiv.querySelectorAll('mark').forEach(mark => {
      mark.replaceWith(document.createTextNode(mark.textContent));
    });
    const html = tempDiv.innerHTML;

    // Set both plain text and HTML to clipboard
    event.clipboardData.setData('text/plain', text);
    event.clipboardData.setData('text/html', html);

    // Delete the selected content
    selection.deleteFromDocument();
  });

})();
