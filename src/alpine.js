// Alpine.js - attach to window and auto-start on DOMContentLoaded (like CDN version)
import Alpine from 'alpinejs';

window.Alpine = Alpine;

// Auto-start when DOM is ready (matches CDN behavior)
document.addEventListener('DOMContentLoaded', () => Alpine.start());
