//
// utility functions to show and hide elements
//

function show(elementId) {
  const item = document.getElementById(elementId);
  item.style.display = "block";
}

function hide(elementId) {
  const item = document.getElementById(elementId);
  item.style.display = "none";
}

// Attach confirm handler to .confirm links (delegated for dynamic content)
document.addEventListener('click', async function(e) {
  const confirmLink = e.target.closest('.confirm');
  if (!confirmLink) return;

  e.stopPropagation();
  e.preventDefault();

  // Support custom options via data attributes
  const title = confirmLink.dataset.confirmTitle || 'Confirm';
  const message = confirmLink.dataset.confirmMessage || 'Are you sure you want to proceed?';
  const confirmText = confirmLink.dataset.confirmText || 'Confirm';
  const isDangerous = confirmLink.dataset.confirmDangerous !== 'false';

  const confirmed = await showConfirm({
    title: title,
    message: message,
    confirmText: confirmText,
    isDangerous: isDangerous
  });

  if (confirmed) {
    // Navigate to the link's href or data-href (for buttons)
    const href = confirmLink.getAttribute('href') || confirmLink.dataset.href;
    if (href) {
      window.location.href = href;
    }
  }
});

// Handle buttons with data-href attribute (navigate without confirmation)
document.addEventListener('click', function(e) {
  const btn = e.target.closest('button[data-href]');
  if (!btn || btn.classList.contains('confirm')) return;

  e.preventDefault();
  window.location.href = btn.dataset.href;
});

// Modal handling is now in alpine-components.js

// Copy link buttons (delegated for HTMX compatibility)
document.addEventListener('click', function(e) {
  const copyBtn = e.target.closest('.copy-btn');
  const highlightCopyBtn = e.target.closest('.highlight-copy-btn');
  const highlightLinkBtn = e.target.closest('.highlight-link-btn');
  const documentLinkBtn = e.target.closest('.document-link-btn');
  const sourceCopyBtn = e.target.closest('.source-copy-btn');

  if (copyBtn) {
    e.preventDefault();
    let data = copyBtn.getAttribute('data-copy');

    // If data-copy-target is specified, get text from target element
    const targetSelector = copyBtn.getAttribute('data-copy-target');
    if (targetSelector) {
      const targetElement = document.querySelector(targetSelector);
      if (targetElement) {
        data = targetElement.textContent.trim();
      }
    }

    copyToClipboard(copyBtn, data);
  } else if (highlightCopyBtn) {
    const data = highlightCopyBtn.getAttribute('data-copy');
    copyToClipboard(highlightCopyBtn, data);
  } else if (highlightLinkBtn) {
    const url = highlightLinkBtn.getAttribute('data-url');
    const fullUrl = window.location.origin + url;
    copyToClipboard(highlightLinkBtn, fullUrl);
  } else if (documentLinkBtn) {
    const url = documentLinkBtn.getAttribute('data-url');
    const fullUrl = window.location.origin + url;
    copyToClipboard(documentLinkBtn, fullUrl);
  } else if (sourceCopyBtn) {
    e.preventDefault();
    const data = sourceCopyBtn.getAttribute('data-copy');
    copyToClipboard(sourceCopyBtn, data);
  }
});

function copyToClipboard(button, data) {
  navigator.clipboard.writeText(data).then(() => {
    const originalHtml = button.innerHTML;
    button.innerHTML = '<i class="icon-check"></i>';
    button.style.color = 'green';
    setTimeout(() => {
      button.innerHTML = originalHtml;
      button.style.color = '';
    }, 2000);
  }).catch(err => {
    console.error('Failed to copy value: ', err);
  });
}

// Copy value logic
document.addEventListener('DOMContentLoaded', function() {
  const copyButtons = document.querySelectorAll('.copy-btn');

  copyButtons.forEach(button => {
    button.addEventListener('click', function() {
      let data = this.getAttribute('data-copy');

      // If data-copy-target is specified, get text from target element
      const targetSelector = this.getAttribute('data-copy-target');
      if (targetSelector) {
        const targetElement = document.querySelector(targetSelector);
        if (targetElement) {
          data = targetElement.textContent.trim();
        }
      }

      navigator.clipboard.writeText(data).then(() => {
        const originalHtml = this.innerHTML;

        this.innerHTML = '<i class="icon-check"></i>';
        this.style.color = 'green';

        setTimeout(() => {
          this.innerHTML = originalHtml;
          this.style.color = '';
        }, 2000);
      }).catch(err => {
        console.error('Failed to copy value: ', err);
      });
    });
  });
});

// ==========================================================================
//  Leader Key (Space) — Vim-style two-keystroke shortcuts
//  Press Space, then an action key within 500ms
// ==========================================================================

const leader = {
  pending: false,
  buffer: '',
  timer: null,
  TIMEOUT: 500,

  activate() {
    this.pending = true;
    this.buffer = '';
    clearTimeout(this.timer);
    this.timer = setTimeout(() => { this.reset(); }, this.TIMEOUT);
  },

  feed(key) {
    this.buffer += key;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => { this.reset(); }, this.TIMEOUT);
    return this.buffer;
  },

  consume() {
    this.reset();
  },

  reset() {
    this.pending = false;
    this.buffer = '';
    clearTimeout(this.timer);
  },

  isEditable(el) {
    const tag = el.tagName;
    return tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable;
  }
};

// ==========================================================================
//  Search Tab Switcher
// ==========================================================================

function switchSearchTab(tab) {
  const container = tab.closest('.search-tabs');
  container.querySelectorAll('.search-tab').forEach(t => t.classList.remove('active'));
  tab.classList.add('active');

  const scopeInput = document.getElementById('search-scope');
  scopeInput.value = tab.dataset.scope;

  // Trigger search with new scope
  const searchInput = document.getElementById('search-text');
  if (searchInput && searchInput.value.trim()) {
    htmx.trigger(searchInput, 'search');
  }
}

// ==========================================================================
//  Command Palette — <Space>n quick-create menu
// ==========================================================================

const commandPalette = {
  items: [
    { label: 'Time Entry', icon: 'icon-clock', url: '/activity/time/add', matterUrl: '/activity/time/add/{id}/activity' },
    { label: 'Task', icon: 'icon-square-check', url: '/tasks/add', matterUrl: '/matters/{id}/tasks/add' },
    { label: 'Expense', icon: 'icon-dollar-sign', url: '/activity/expenses/add', matterUrl: '/activity/expenses/add/{id}/activity' },
    { label: 'Event', icon: 'icon-calendar', url: '/events/add', matterUrl: '/events/add/{id}' },
    { label: 'Contact', icon: 'icon-user', url: '/contacts/add' },
    { label: 'Intake', icon: 'icon-inbox', url: '/intakes/add' },
  ],
  activeIndex: 0,
  overlay: null,
  pendingToast: null,

  open() {
    if (this.overlay) return;
    this.activeIndex = 0;
    this.pendingToast = null;

    const overlay = document.createElement('div');
    overlay.className = 'cmd-palette-overlay';
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) this.close();
    });

    const dialog = document.createElement('div');
    dialog.className = 'cmd-palette';

    const title = document.createElement('div');
    title.className = 'cmd-palette-title';
    title.textContent = 'Create New';
    dialog.appendChild(title);

    const list = document.createElement('ul');
    list.className = 'cmd-palette-list';
    this.items.forEach((item, i) => {
      const li = document.createElement('li');
      li.className = 'cmd-palette-item' + (i === 0 ? ' active' : '');
      li.innerHTML = `<i class="${item.icon}"></i><span>${item.label}</span>`;
      li.addEventListener('click', () => this.select(i));
      li.addEventListener('mouseenter', () => this.highlight(i));
      list.appendChild(li);
    });
    dialog.appendChild(list);

    const hint = document.createElement('div');
    hint.className = 'cmd-palette-hint';
    hint.innerHTML = '<span><kbd>j/k</kbd> navigate</span><span><kbd>enter</kbd> select</span><span><kbd>esc</kbd> close</span>';
    dialog.appendChild(hint);

    overlay.appendChild(dialog);
    document.body.appendChild(overlay);
    this.overlay = overlay;
  },

  close() {
    if (!this.overlay) return;
    this.overlay.remove();
    this.overlay = null;
  },

  highlight(index) {
    this.activeIndex = index;
    const items = this.overlay.querySelectorAll('.cmd-palette-item');
    items.forEach((el, i) => el.classList.toggle('active', i === index));
  },

  move(delta) {
    const next = (this.activeIndex + delta + this.items.length) % this.items.length;
    this.highlight(next);
  },

  getMatterId() {
    const match = window.location.pathname.match(/^\/(?:matters|case)\/(\d+)/);
    return match ? match[1] : null;
  },

  select(index) {
    const item = this.items[index ?? this.activeIndex];
    this.pendingToast = item.label;
    this.close();

    const matterId = this.getMatterId();
    let url = item.url;
    if (matterId && item.matterUrl) {
      url = item.matterUrl.replace('{id}', matterId);
    }
    htmx.ajax('GET', url + '?from=palette', { target: '#htmx-modal-container' });
  },

  handleKeydown(event) {
    if (!this.overlay) return false;

    if (event.key === 'Escape') {
      event.preventDefault();
      this.close();
      return true;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      this.select();
      return true;
    }
    // j / k or arrow keys
    if (event.key === 'j' || event.key === 'ArrowDown') {
      event.preventDefault();
      this.move(1);
      return true;
    }
    if (event.key === 'k' || event.key === 'ArrowUp') {
      event.preventDefault();
      this.move(-1);
      return true;
    }
    return false;
  }
};

// ==========================================================================
//  Matter Switcher — <Space>m quick matter jump
// ==========================================================================

const matterSwitcher = {
  overlay: null,
  matters: [],
  filtered: [],
  activeIndex: 0,

  open() {
    if (this.overlay) return;
    this.activeIndex = 0;
    this.matters = [];
    this.filtered = [];

    // Build overlay
    const overlay = document.createElement('div');
    overlay.className = 'cmd-palette-overlay';
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) this.close();
    });

    const dialog = document.createElement('div');
    dialog.className = 'cmd-palette matter-switcher-palette';

    const title = document.createElement('div');
    title.className = 'cmd-palette-title';
    title.textContent = 'Switch Matter';
    dialog.appendChild(title);

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'matter-switcher-input';
    input.placeholder = 'Search matters…';
    input.addEventListener('input', () => this.filter(input.value));
    dialog.appendChild(input);

    const list = document.createElement('ul');
    list.className = 'cmd-palette-list matter-switcher-list';
    dialog.appendChild(list);

    const hint = document.createElement('div');
    hint.className = 'cmd-palette-hint';
    hint.innerHTML = '<span><kbd>&uarr;/&darr;</kbd> navigate</span><span><kbd>enter</kbd> select</span><span><kbd>esc</kbd> close</span>';
    dialog.appendChild(hint);

    overlay.appendChild(dialog);
    document.body.appendChild(overlay);
    this.overlay = overlay;

    input.focus();
    this.fetchMatters();
  },

  close() {
    if (!this.overlay) return;
    this.overlay.remove();
    this.overlay = null;
  },

  fetchMatters() {
    fetch('/matters/api/open/')
      .then(r => r.json())
      .then(data => {
        this.matters = data;
        this.filtered = data;
        this.render();
      });
  },

  filter(query) {
    const q = query.toLowerCase();
    this.filtered = q
      ? this.matters.filter(m => m.name.toLowerCase().includes(q))
      : this.matters;
    this.activeIndex = 0;
    this.render();
  },

  render() {
    const list = this.overlay.querySelector('.matter-switcher-list');
    list.innerHTML = '';
    this.filtered.forEach((m, i) => {
      const li = document.createElement('li');
      li.className = 'cmd-palette-item' + (i === this.activeIndex ? ' active' : '');
      li.innerHTML = `<i class="icon-briefcase-business"></i><span>${m.name}</span>`;
      li.addEventListener('click', () => this.select(i));
      li.addEventListener('mouseenter', () => this.highlight(i));
      list.appendChild(li);
    });
  },

  highlight(index) {
    this.activeIndex = index;
    const items = this.overlay.querySelectorAll('.cmd-palette-item');
    items.forEach((el, i) => el.classList.toggle('active', i === index));
  },

  move(delta) {
    if (!this.filtered.length) return;
    const next = (this.activeIndex + delta + this.filtered.length) % this.filtered.length;
    this.highlight(next);
    // Scroll active item into view
    const items = this.overlay.querySelectorAll('.cmd-palette-item');
    if (items[next]) items[next].scrollIntoView({ block: 'nearest' });
  },

  select(index) {
    const matter = this.filtered[index ?? this.activeIndex];
    if (!matter) return;
    this.close();
    window.location.href = '/matters/' + matter.id;
  },

  handleKeydown(event) {
    if (!this.overlay) return false;

    if (event.key === 'Escape') {
      event.preventDefault();
      this.close();
      return true;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      this.select();
      return true;
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      this.move(1);
      return true;
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      this.move(-1);
      return true;
    }
    return false;
  }
};

// ==========================================================================
//  Nav Switcher — <Space>g quick tab jump (reads from DOM)
// ==========================================================================

const navSwitcher = {
  overlay: null,
  items: [],
  filtered: [],
  activeIndex: 0,

  open() {
    if (this.overlay) return;
    this.activeIndex = 0;
    this.items = this.collectItems();
    this.filtered = this.items;
    if (!this.items.length) return;

    const overlay = document.createElement('div');
    overlay.className = 'cmd-palette-overlay';
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) this.close();
    });

    const dialog = document.createElement('div');
    dialog.className = 'cmd-palette matter-switcher-palette';

    const title = document.createElement('div');
    title.className = 'cmd-palette-title';
    title.textContent = 'Go to';
    dialog.appendChild(title);

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'matter-switcher-input';
    input.placeholder = 'Search tabs…';
    input.addEventListener('input', () => this.filter(input.value));
    dialog.appendChild(input);

    const list = document.createElement('ul');
    list.className = 'cmd-palette-list matter-switcher-list';
    dialog.appendChild(list);

    const hint = document.createElement('div');
    hint.className = 'cmd-palette-hint';
    hint.innerHTML = '<span><kbd>&uarr;/&darr;</kbd> navigate</span><span><kbd>enter</kbd> select</span><span><kbd>esc</kbd> close</span>';
    dialog.appendChild(hint);

    overlay.appendChild(dialog);
    document.body.appendChild(overlay);
    this.overlay = overlay;

    this.render();
    input.focus();
  },

  close() {
    if (!this.overlay) return;
    this.overlay.remove();
    this.overlay = null;
  },

  collectItems() {
    const items = [];
    // Main nav links
    document.querySelectorAll('.sidebar-nav-main a[href]').forEach(a => {
      const label = a.textContent.trim();
      const href = a.getAttribute('href');
      if (label && href && href !== '#') {
        items.push({ label, href, group: 'Nav' });
      }
    });
    // Sub-nav links
    document.querySelectorAll('.subnav a[href]').forEach(a => {
      const label = a.textContent.trim();
      const href = a.getAttribute('hx-push-url') || a.getAttribute('href');
      if (label && href && href !== '#') {
        items.push({ label, href, group: 'Tab' });
      }
    });
    return items;
  },

  filter(query) {
    const q = query.toLowerCase();
    this.filtered = q
      ? this.items.filter(item => item.label.toLowerCase().includes(q))
      : this.items;
    this.activeIndex = 0;
    this.render();
  },

  render() {
    const list = this.overlay.querySelector('.matter-switcher-list');
    list.innerHTML = '';
    this.filtered.forEach((item, i) => {
      const li = document.createElement('li');
      li.className = 'cmd-palette-item' + (i === this.activeIndex ? ' active' : '');
      const icon = item.group === 'Nav' ? 'icon-layout-grid' : 'icon-columns-2';
      li.innerHTML = `<i class="${icon}"></i><span>${item.label}</span><span class="cmd-palette-group">${item.group}</span>`;
      li.addEventListener('click', () => this.select(i));
      li.addEventListener('mouseenter', () => this.highlight(i));
      list.appendChild(li);
    });
  },

  highlight(index) {
    this.activeIndex = index;
    const items = this.overlay.querySelectorAll('.cmd-palette-item');
    items.forEach((el, i) => el.classList.toggle('active', i === index));
  },

  move(delta) {
    if (!this.filtered.length) return;
    const next = (this.activeIndex + delta + this.filtered.length) % this.filtered.length;
    this.highlight(next);
    const items = this.overlay.querySelectorAll('.cmd-palette-item');
    if (items[next]) items[next].scrollIntoView({ block: 'nearest' });
  },

  select(index) {
    const item = this.filtered[index ?? this.activeIndex];
    if (!item) return;
    this.close();
    window.location.href = item.href;
  },

  handleKeydown(event) {
    if (!this.overlay) return false;

    if (event.key === 'Escape') {
      event.preventDefault();
      this.close();
      return true;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      this.select();
      return true;
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      this.move(1);
      return true;
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      this.move(-1);
      return true;
    }
    return false;
  }
};

// ==========================================================================
//  Global keydown — leader key, matter switcher, nav switcher, mode keys
// ==========================================================================

function getMatterId() {
  const match = window.location.pathname.match(/^\/(?:matters|case)\/(\d+)/);
  return match ? match[1] : null;
}

document.addEventListener('keydown', function(event) {
  // Let overlays handle their own keys first
  if (commandPalette.handleKeydown(event)) return;
  if (matterSwitcher.handleKeydown(event)) return;
  if (navSwitcher.handleKeydown(event)) return;

  // Skip all shortcut handling when in editable fields or modals
  if (leader.isEditable(event.target)) return;
  if (document.body.classList.contains('modal-open')) return;

  // Space — activate leader key
  if (event.key === ' ' && !event.ctrlKey && !event.metaKey && !event.altKey) {
    event.preventDefault();
    leader.activate();
    return;
  }

  // Leader actions (must follow a Space press within timeout)
  if (leader.pending) {
    event.preventDefault();
    const seq = leader.feed(event.key);

    const LEADER_ACTIONS = {
      'n': () => commandPalette.open(),
      'm': () => matterSwitcher.open(),
      'g': () => navSwitcher.open(),
      'b': () => document.getElementById('sidebar-toggle').click(),
      'ff': () => htmx.ajax('GET', '/search/?scope=all', { target: '#htmx-modal-container' }),
      'fm': () => htmx.ajax('GET', '/search/?scope=matters', { target: '#htmx-modal-container' }),
      'fp': () => htmx.ajax('GET', '/search/?scope=proceedings', { target: '#htmx-modal-container' }),
      'fc': () => htmx.ajax('GET', '/search/?scope=contacts', { target: '#htmx-modal-container' }),
      'fi': () => htmx.ajax('GET', '/search/?scope=intakes', { target: '#htmx-modal-container' }),
      'fn': () => htmx.ajax('GET', '/search/?scope=notes', { target: '#htmx-modal-container' }),
    };

    const action = LEADER_ACTIONS[seq];
    if (action) {
      leader.consume();
      action();
    } else {
      const isPrefix = Object.keys(LEADER_ACTIONS).some(s => s.startsWith(seq) && s !== seq);
      if (!isPrefix) {
        leader.consume();
      }
    }
    return;
  }

  // Bare keys (no leader prefix) — only on matter/case pages
  const matterId = getMatterId();
  if (!matterId) return;

  if (event.key === 'c') {
    window.location.href = '/case/select-matter/' + matterId + '/';
  } else if (event.key === 'd') {
    window.location.href = '/matters/' + matterId;
  }
});

// Show toast when a command palette modal form is successfully submitted
// (only if the backend didn't already send a custom toast via HX-Toast header)
document.body.addEventListener('htmx:afterRequest', function(e) {
  if (e.detail.xhr.status === 204 && commandPalette.pendingToast) {
    const label = commandPalette.pendingToast;
    commandPalette.pendingToast = null;
    if (!e.detail.xhr.getResponseHeader('HX-Toast')) {
      Toast.success(`${label} created.`);
    }
  }
});

// ==========================================================================
//  Search Modal — keyboard navigation
//  Ctrl+Shift+H/L tabs, Ctrl+Shift+J/K results, Ctrl+Shift+Enter open
// ==========================================================================

const searchNav = {
  getModal() {
    return document.querySelector('#htmx-modal-container .search');
  },

  getCards() {
    const modal = this.getModal();
    return modal ? [...modal.querySelectorAll('.search-card')] : [];
  },

  highlightCard(index) {
    const cards = this.getCards();
    if (!cards.length) return;
    cards.forEach(c => c.classList.remove('active'));
    const i = Math.max(0, Math.min(index, cards.length - 1));
    cards[i].classList.add('active');
    cards[i].scrollIntoView({ block: 'nearest' });
  },

  getActiveCardIndex() {
    const cards = this.getCards();
    return cards.findIndex(c => c.classList.contains('active'));
  },

  moveCard(delta) {
    const cards = this.getCards();
    if (!cards.length) return;
    const current = this.getActiveCardIndex();
    const next = current < 0 ? 0 : (current + delta + cards.length) % cards.length;
    this.highlightCard(next);
  },

  selectCard() {
    const cards = this.getCards();
    const idx = this.getActiveCardIndex();
    if (idx >= 0 && cards[idx]) {
      cards[idx].click();
    }
  },

  getTabs() {
    const modal = this.getModal();
    return modal ? [...modal.querySelectorAll('.search-tab')] : [];
  },

  moveTab(delta) {
    const tabs = this.getTabs();
    if (!tabs.length) return;
    const current = tabs.findIndex(t => t.classList.contains('active'));
    const next = (current + delta + tabs.length) % tabs.length;
    tabs[next].click();
    tabs[next].focus();
    // Clear any highlighted cards when switching tabs
    this.getCards().forEach(c => c.classList.remove('active'));
  },

  handleKeydown(event) {
    if (!this.getModal()) return false;
    const input = this.getModal().querySelector('.search-text');
    const inInput = document.activeElement === input;

    // --- Insert mode (input focused) ---
    if (inInput) {
      // Enter — open first result
      if (event.key === 'Enter') {
        const firstCard = this.getModal().querySelector('.search-card');
        if (firstCard) {
          event.preventDefault();
          firstCard.click();
          return true;
        }
      }
      // Esc or Tab — enter normal mode
      if (event.key === 'Escape' || event.key === 'Tab') {
        event.preventDefault();
        event.stopPropagation(); // prevent modal close
        input.blur();
        const activeTab = this.getModal().querySelector('.search-tab.active');
        if (activeTab) activeTab.focus();
        return true;
      }
      return false;
    }

    // --- Normal mode (input not focused) ---
    // i — back to insert mode
    if (event.key === 'i') {
      event.preventDefault();
      this.getCards().forEach(c => c.classList.remove('active'));
      input.focus();
      return true;
    }
    // j / k — navigate results (first j highlights first item)
    if (event.key === 'j' || event.key === 'ArrowDown') {
      event.preventDefault();
      const current = this.getActiveCardIndex();
      this.moveCard(current < 0 ? 0 : 1);
      return true;
    }
    if (event.key === 'k' || event.key === 'ArrowUp') {
      event.preventDefault();
      const current = this.getActiveCardIndex();
      this.moveCard(current < 0 ? 0 : -1);
      return true;
    }
    // h / l — switch tabs
    if (event.key === 'h' || event.key === 'ArrowLeft') {
      event.preventDefault();
      this.moveTab(-1);
      return true;
    }
    if (event.key === 'l' || event.key === 'ArrowRight') {
      event.preventDefault();
      this.moveTab(1);
      return true;
    }
    // Enter — open highlighted result (or first if none highlighted)
    if (event.key === 'Enter') {
      event.preventDefault();
      if (this.getActiveCardIndex() >= 0) {
        this.selectCard();
      } else {
        const firstCard = this.getModal().querySelector('.search-card');
        if (firstCard) firstCard.click();
      }
      return true;
    }
    // Esc — close modal (second Esc)
    // (falls through to the Alpine modal Escape handler)
    return false;
  }
};

document.addEventListener('keydown', function(event) {
  if (searchNav.handleKeydown(event)) return;
}, true);
