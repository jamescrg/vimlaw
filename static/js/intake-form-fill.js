/*
 * The public intake form a prospective client fills in.
 *
 * Autosaves as they type. Three details matter:
 *
 *  - Single-flight. A slow save must never land after a newer one, so while a
 *    request is in the air the next one is queued rather than raced.
 *  - A final save on page-hide, via fetch(keepalive) rather than sendBeacon —
 *    beacon cannot set the CSRF header. The server merges per key, so a
 *    keepalive save racing a debounced one cannot clobber anything.
 *  - A 403 means the CSRF cookie aged out under a page left open for hours.
 *    That has to be said out loud; failing silently would quietly discard
 *    everything they typed after it.
 */
document.addEventListener('alpine:init', () => {
  Alpine.data('intakeForm', (config) => ({
    answers: normalize(config.answers),
    errors: {},
    state: 'idle', // idle | saving | saved | error
    savedAt: '',
    message: '',
    sending: false,
    submitted: !!config.submitted,
    editing: !config.submitted,

    _timer: null,
    _inFlight: false,
    _queued: false,

    init() {
      const flushNow = () => {
        if (document.visibilityState === 'hidden') this.flush({ keepalive: true });
      };
      document.addEventListener('visibilitychange', flushNow);
      window.addEventListener('pagehide', () => this.flush({ keepalive: true }));
    },

    // Typing: wait for a pause. Picking an option: save almost at once, since
    // there is no more typing coming.
    touch() {
      this.state = 'idle';
      this.schedule(1200);
    },

    flushSoon() {
      this.state = 'idle';
      this.schedule(150);
    },

    schedule(ms) {
      clearTimeout(this._timer);
      this._timer = setTimeout(() => this.flush(), ms);
    },

    async flush(options = {}) {
      // A preview has nowhere to save to, and shouldn't pretend otherwise.
      if (config.preview) return;
      if (!this.editing) return;
      if (this._inFlight) {
        this._queued = true;
        return;
      }
      this._inFlight = true;
      this.state = 'saving';
      try {
        const res = await post(config.saveUrl, { answers: this.answers }, options);
        if (res.status === 403) {
          this.state = 'error';
          this.message =
            'Your session expired. Please reload this page. Your answers are still on screen.';
          return;
        }
        const data = await res.json().catch(() => ({}));
        if (data.ok) {
          this.state = 'saved';
          this.savedAt = data.saved_at || '';
          this.message = '';
        } else {
          this.state = 'error';
          this.message = data.error || 'We could not save that. Please try again.';
        }
      } catch (e) {
        this.state = 'error';
        this.message = 'We could not reach the server. Your answers are still on screen.';
      } finally {
        this._inFlight = false;
        if (this._queued) {
          this._queued = false;
          this.flush();
        }
      }
    },

    async submit() {
      if (config.preview) {
        this.message = 'This is a preview. Nothing typed here is saved or sent.';
        return;
      }
      if (this.sending) return;
      // Land any pending keystrokes first so the server validates the whole
      // document, not the version from a second ago.
      clearTimeout(this._timer);
      this.sending = true;
      this.errors = {};
      this.message = '';
      try {
        const res = await post(config.submitUrl, { answers: this.answers });
        if (res.status === 403) {
          this.message =
            'Your session expired. Please reload this page. Your answers are still on screen.';
          return;
        }
        const data = await res.json().catch(() => ({}));
        if (data.ok) {
          this.submitted = true;
          this.editing = false;
          this.state = 'idle';
          window.scrollTo({ top: 0, behavior: 'smooth' });
          return;
        }
        if (data.errors) {
          this.errors = data.errors;
          this.message = 'Please check the highlighted questions.';
          this.$nextTick(() => {
            const first = document.querySelector('.cf-field-error');
            if (first) first.scrollIntoView({ block: 'center', behavior: 'smooth' });
          });
          return;
        }
        this.message = data.error || 'We could not submit that. Please try again.';
      } catch (e) {
        this.message = 'We could not reach the server. Please try again.';
      } finally {
        this.sending = false;
      }
    },
  }));
});

/*
 * Alpine's x-model needs the key to exist before it can bind to it, and a
 * checkbox group needs an array rather than undefined. Everything else starts
 * as an empty string.
 */
function normalize(answers) {
  const out = { ...(answers || {}) };
  document.querySelectorAll('input[type="checkbox"][name]').forEach((el) => {
    if (!Array.isArray(out[el.name])) out[el.name] = [];
  });
  return out;
}

function post(url, body, options = {}) {
  return fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfToken(),
    },
    body: JSON.stringify(body),
    keepalive: !!options.keepalive,
  });
}

function csrfToken() {
  try {
    return JSON.parse(document.body.getAttribute('hx-headers'))['X-CSRFToken'] || '';
  } catch (e) {
    return '';
  }
}
