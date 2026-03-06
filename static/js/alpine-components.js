/**
 * Alpine.js Components
 * Replacement for Bootstrap JS dropdowns and modals
 */

document.addEventListener('alpine:init', () => {

  /**
   * Dropdown Component
   * Usage: <div class="dropdown" x-data="dropdown()">
   *          <button x-ref="button" @click="toggle()" :aria-expanded="open">
   *          <ul class="dropdown-menu" x-ref="menu" x-show="open" @click="close()">
   * Note: We intentionally omit x-transition to avoid sub-pixel layout shifts
   */
  Alpine.data('dropdown', () => ({
    open: false,

    toggle() {
      if (this.open) {
        this.close();
      } else {
        this.openDropdown();
      }
    },

    openDropdown() {
      // Close any other open dropdowns first
      document.querySelectorAll('.dropdown-menu.show').forEach(menu => {
        menu.classList.remove('show');
      });

      this.open = true;
      this.$nextTick(() => {
        this.position();
        this.$refs.menu?.classList.add('show');
      });
    },

    close() {
      this.open = false;
      this.$refs.menu?.classList.remove('show');
      this.resetPosition();
    },

    position() {
      const menu = this.$refs.menu;
      const button = this.$refs.button;
      if (!menu || !button) return;

      const rect = button.getBoundingClientRect();

      // Use fixed positioning to escape overflow constraints
      menu.style.position = 'fixed';
      menu.style.top = `${rect.bottom + 4}px`;
      menu.style.left = `${rect.left}px`;
      menu.style.right = 'auto';
      menu.style.bottom = 'auto';

      // Check if menu would overflow viewport and adjust
      this.$nextTick(() => {
        const menuRect = menu.getBoundingClientRect();
        const spaceBelow = window.innerHeight - rect.bottom;
        const spaceAbove = rect.top;

        // Only flip up if menu truly doesn't fit below AND there's more room above
        if (menuRect.height > spaceBelow && spaceAbove > spaceBelow) {
          const flippedTop = rect.top - menuRect.height - 4;
          if (flippedTop >= 8) {
            menu.style.top = `${flippedTop}px`;
          } else {
            // Constrain to viewport
            menu.style.top = '8px';
            menu.style.maxHeight = `${rect.top - 16}px`;
            menu.style.overflowY = 'auto';
          }
        } else if (menuRect.bottom > window.innerHeight) {
          // Keep below but constrain height
          menu.style.maxHeight = `${spaceBelow - 16}px`;
          menu.style.overflowY = 'auto';
        }

        // Align to right edge if would overflow right
        if (menuRect.right > window.innerWidth - 8) {
          menu.style.left = 'auto';
          menu.style.right = `${window.innerWidth - rect.right}px`;
        }
      });
    },

    resetPosition() {
      const menu = this.$refs.menu;
      if (!menu) return;
      menu.style.position = '';
      menu.style.top = '';
      menu.style.left = '';
      menu.style.right = '';
      menu.style.bottom = '';
      menu.style.maxHeight = '';
      menu.style.overflowY = '';
    },

    // Close on click outside
    handleClickOutside(event) {
      if (this.open && !this.$el.contains(event.target)) {
        this.close();
      }
    },

    // Close on escape key
    handleEscape(event) {
      if (this.open && event.key === 'Escape') {
        this.close();
        this.$refs.button?.focus();
      }
    },

    // Close when clicking any link or button inside the menu
    handleMenuClick(event) {
      const clickedElement = event.target.closest('a, button');
      if (clickedElement && this.$refs.menu?.contains(clickedElement)) {
        this.close();
      }
    },

    init() {
      // Bind event listeners
      this._clickOutsideHandler = this.handleClickOutside.bind(this);
      this._escapeHandler = this.handleEscape.bind(this);
      this._menuClickHandler = this.handleMenuClick.bind(this);

      document.addEventListener('click', this._clickOutsideHandler);
      document.addEventListener('keydown', this._escapeHandler);
      this.$el.addEventListener('click', this._menuClickHandler);
    },

    destroy() {
      document.removeEventListener('click', this._clickOutsideHandler);
      document.removeEventListener('keydown', this._escapeHandler);
      this.$el.removeEventListener('click', this._menuClickHandler);
    }
  }));


  /**
   * Modal Component
   * Usage: Applied to #htmx-modal-container
   * Listens for custom events: 'open-modal', 'close-modal'
   */
  Alpine.data('modal', () => ({
    isOpen: false,

    open() {
      if (this.isOpen) return;
      this.isOpen = true;

      // Add backdrop
      let backdrop = document.querySelector('.modal-backdrop');
      if (!backdrop) {
        backdrop = document.createElement('div');
        backdrop.className = 'modal-backdrop fade show';
        document.body.appendChild(backdrop);
      }

      this.$el.classList.add('show');
      this.$el.style.display = 'block';
      document.body.style.overflow = 'hidden';
      document.body.classList.add('modal-open');

      // Focus first autofocus element or first focusable
      this.$nextTick(() => {
        const autofocus = this.$el.querySelector('[autofocus]');
        if (autofocus) {
          autofocus.focus();
        }
      });
    },

    close() {
      if (!this.isOpen) return;
      this.isOpen = false;
      this.$el.classList.remove('show');

      // Remove backdrop
      const backdrop = document.querySelector('.modal-backdrop');
      if (backdrop) backdrop.remove();

      // Allow fade transition
      setTimeout(() => {
        this.$el.style.display = 'none';
        document.body.style.overflow = '';
        document.body.classList.remove('modal-open');
        // Clear modal content
        this.$el.innerHTML = '';
      }, 150);
    },

    handleBackdropClick(event) {
      // Clicking outside the modal does not close it
      // Users must explicitly close via button or Escape key
    },

    init() {
      // Listen for custom events
      window.addEventListener('open-modal', () => this.open());
      window.addEventListener('close-modal', () => this.close());

      // Backdrop click
      this.$el.addEventListener('click', (e) => this.handleBackdropClick(e));
    }
  }));


  /**
   * Confirm Modal Component
   * A styled replacement for browser's native confirm() dialog
   * Usage: Applied to #confirm-modal-container
   */
  Alpine.data('confirmModal', () => ({
    isOpen: false,
    title: '',
    message: '',
    confirmText: 'Confirm',
    cancelText: 'Cancel',
    isDangerous: false,
    confirmClass: '',
    onConfirm: null,
    onCancel: null,

    show(options) {
      this.title = options.title || 'Confirm';
      this.message = options.message || 'Are you sure?';
      this.confirmText = options.confirmText || 'Confirm';
      this.cancelText = options.cancelText || 'Cancel';
      this.isDangerous = options.isDangerous !== false;
      this.confirmClass = options.confirmClass || '';
      this.onConfirm = options.onConfirm || null;
      this.onCancel = options.onCancel || null;
      this.isOpen = true;

      // Focus the cancel button by default for safety
      this.$nextTick(() => {
        const cancelBtn = this.$el.querySelector('.confirm-modal-cancel');
        if (cancelBtn) cancelBtn.focus();
      });
    },

    confirm() {
      this.isOpen = false;
      if (this.onConfirm) this.onConfirm();
      this.reset();
    },

    cancel() {
      this.isOpen = false;
      if (this.onCancel) this.onCancel();
      this.reset();
    },

    reset() {
      this.onConfirm = null;
      this.onCancel = null;
    },

    handleKeydown(event) {
      if (!this.isOpen) return;
      if (event.key === 'Escape') {
        this.cancel();
      } else if (event.key === 'Enter') {
        // Only confirm on Enter if the confirm button is focused
        if (document.activeElement?.classList.contains('confirm-modal-confirm')) {
          this.confirm();
        }
      }
    }
  }));

});


/**
 * HTMX Integration for Modal
 * Replaces Bootstrap modal hooks in main.js
 */
document.addEventListener('DOMContentLoaded', () => {

  // Helper to check if target is the modal container
  function isModalTarget(target) {
    if (!target) return false;
    return target.id === 'htmx-modal-container' ||
           target.id === 'htmx-modal-content' ||
           target.closest('#htmx-modal-container');
  }

  // Open modal when HTMX swaps content into modal container
  document.body.addEventListener('htmx:afterSwap', (e) => {
    if (isModalTarget(e.detail.target) && e.detail.xhr.response) {
      // Small delay to ensure Alpine has processed new content
      setTimeout(() => {
        window.dispatchEvent(new CustomEvent('open-modal'));
      }, 10);
    }
  });

  // Close modal on empty response
  document.body.addEventListener('htmx:beforeSwap', (e) => {
    if (isModalTarget(e.detail.target) && !e.detail.xhr.response) {
      window.dispatchEvent(new CustomEvent('close-modal'));
      e.detail.shouldSwap = false;
    }
  });

  // Close modal on 204 status (successful form submission, no content)
  document.body.addEventListener('htmx:afterRequest', (e) => {
    if (e.detail.xhr.status === 204) {
      window.dispatchEvent(new CustomEvent('close-modal'));
    }
  });

  // Intercept hx-confirm to use custom modal instead of browser confirm
  document.body.addEventListener('htmx:confirm', (e) => {
    // Only intercept if there's an hx-confirm attribute (e.detail.question has a value)
    if (!e.detail.question) {
      return;
    }

    const confirmModal = document.getElementById('confirm-modal');
    if (!confirmModal) {
      // Fall back to browser confirm if modal not present
      return;
    }

    e.preventDefault();

    const message = e.detail.question;
    const triggerEl = e.detail.elt;

    // Check for custom confirm options in data attributes
    const title = triggerEl.dataset.confirmTitle || 'Confirm';
    const confirmText = triggerEl.dataset.confirmText || 'Delete';
    const cancelText = triggerEl.dataset.cancelText || 'Cancel';
    const confirmStyle = triggerEl.dataset.confirmStyle || 'danger';

    // Get Alpine component and show modal
    const component = Alpine.$data(confirmModal);
    component.show({
      title: title,
      message: message,
      confirmText: confirmText,
      cancelText: cancelText,
      isDangerous: confirmStyle === 'danger',
      confirmClass: 'btn-' + confirmStyle,
      onConfirm: () => {
        e.detail.issueRequest(true);
      }
    });
  });

});


/**
 * Global showConfirm() function
 * Promise-based replacement for browser's native confirm()
 * Usage: if (await showConfirm({ message: 'Delete this?' })) { ... }
 *
 * Options:
 *   - message: The confirmation message (required)
 *   - title: Modal title (default: 'Confirm')
 *   - confirmText: Confirm button text (default: 'Confirm')
 *   - cancelText: Cancel button text (default: 'Cancel')
 *   - isDangerous: Style as dangerous action (default: true)
 */
window.showConfirm = function(options) {
  return new Promise((resolve) => {
    const confirmModal = document.getElementById('confirm-modal');
    if (!confirmModal) {
      // Fall back to browser confirm if modal not present
      resolve(confirm(options.message || 'Are you sure?'));
      return;
    }

    const component = Alpine.$data(confirmModal);
    component.show({
      title: options.title || 'Confirm',
      message: options.message || 'Are you sure?',
      confirmText: options.confirmText || 'Confirm',
      cancelText: options.cancelText || 'Cancel',
      isDangerous: options.isDangerous !== false,
      onConfirm: () => resolve(true),
      onCancel: () => resolve(false)
    });
  });
};
