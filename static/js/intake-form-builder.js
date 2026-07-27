/*
 * The custom intake form builder.
 *
 * Holds the whole form as an array of field objects and POSTs it in one go.
 * Two details are load-bearing:
 *
 *  - `key` is the server's, not ours. A new field carries `key: null` and the
 *    server mints one on save; every submission's answers are filed under it,
 *    so after saving we re-hydrate from the server's response rather than
 *    keeping our local copy.
 *  - `_id` is ours, not the server's. Alpine needs a stable identity for
 *    `x-for` before a field has ever been saved, and it is stripped from the
 *    payload on the way out.
 *
 * Saving is automatic, debounced, and never blocked: an unfinished field
 * stores like any other and simply stays off the client's page until it is
 * complete (schema.py is_complete). The one structural constraint is that a
 * save must adopt the server's keys without replacing the field objects —
 * replacing them changes every x-for key and Alpine rebuilds the whole
 * canvas, which would yank the caret out of whatever input is being typed
 * into.
 */
const AUTOSAVE_MS = 1500;

document.addEventListener('alpine:init', () => {
  Alpine.data('intakeFormBuilder', (config) => ({
    fields: (config.schema || []).map((f) => ({ ...f, _id: newId() })),
    palette: config.palette || [],
    defaults: config.defaults || {},

    selectedId: null,
    dirty: false,
    saving: false,
    savedAt: '',
    error: '',

    // Bumped by every edit, so a reply that lands after the next keystroke
    // knows not to declare the form clean.
    rev: 0,
    _timer: null,
    _inFlight: false,
    _queued: false,
    _quiet: false,

    init() {
      this.$watch('fields', () => this.touch(), { deep: true });
      this.mountSortable();
      // The palette groups are x-for children, so they don't exist until
      // Alpine has rendered — mount their drag sources a tick later.
      this.$nextTick(() => this.mountPalette());

      // A debounced save can still be pending when the tab goes away.
      const flushNow = () => {
        if (document.visibilityState === 'hidden') this.save({ keepalive: true });
      };
      document.addEventListener('visibilitychange', flushNow);
      window.addEventListener('pagehide', () => this.save({ keepalive: true }));

      window.addEventListener('beforeunload', (e) => {
        if (!this.dirty) return;
        e.preventDefault();
        e.returnValue = '';
      });
    },

    // Every edit lands here. The debounce is what makes one edit one save:
    // typing a label is a change per keystroke, and each save mints keys and
    // moves the template's version on.
    touch() {
      if (this._quiet) return;
      this.dirty = true;
      this.rev += 1;
      this.error = '';
      clearTimeout(this._timer);
      this._timer = setTimeout(() => this.save(), AUTOSAVE_MS);
    },

    // Run a mutation without waking the watcher. Adopting the server's keys
    // writes to `fields`, which would otherwise schedule the save that would
    // adopt the keys that would schedule the save.
    quietly(mutate) {
      this._quiet = true;
      mutate();
      this.$nextTick(() => { this._quiet = false; });
    },

    // What keeps this one field off the client's page, in words, or '' when
    // nothing does. Informational, never blocking: the field stores either
    // way.
    fieldProblem(field) {
      if (field.type !== 'text_block' && !String(field.label || '').trim()) {
        return field.type === 'heading'
          ? 'Give this heading some text.'
          : 'Give this field a label.';
      }
      if (Array.isArray(field.options)) {
        const filled = field.options.filter((o) => String(o.label || '').trim());
        if (!filled.length) return 'Add at least one option.';
      }
      return '';
    },

    // The editor's own Save: collapse and let the pending save go now rather
    // than on the debounce. Never refuses — an unfinished field stores fine
    // and just stays off the client's page, which the red flag says.
    doneEditing(field) {
      this.selectedId = null;
      this.save();
    },

    // The head's save button doubles as the unfinished marker: it stays
    // visible (and red) on a closed unfinished field, and clicking it there
    // opens the field on its problem instead of closing anything.
    saveClicked(field) {
      if (this.selectedId !== field._id) {
        this.selectedId = field._id;
        return;
      }
      this.doneEditing(field);
    },

    mountSortable() {
      // The node the dragged card sat in front of, captured before Sortable
      // touches anything. Sortable rearranges the DOM directly, which
      // desynchronises Alpine's x-for bookkeeping, so the card is put back
      // exactly where it started and the array is left as the only thing that
      // actually reorders.
      let putBack = null;

      Sortable.create(this.$refs.canvas, {
        handle: '.fb-handle',
        animation: 150,
        ghostClass: 'fb-ghost',
        // The filter matters beyond who is draggable: Sortable's indexes only
        // count children matching it, which is what lets the empty-state well
        // live inside the canvas without shifting every drag index by one.
        draggable: '.fb-field',
        group: { name: 'fb-fields', put: true },
        // A palette item dropped here. Sortable's clone mode works the other
        // way round from its name: the ORIGINAL button is what travels, and
        // the clone is what stays in the palette. The clone is a dead copy —
        // cloneNode carries no Alpine listeners — so the original must go
        // back in its place, or the palette is left holding a button that
        // looks right and does nothing. Then the real field is spliced into
        // the array at the drop position, and Alpine renders the card.
        onAdd: (evt) => {
          const type = evt.item.dataset.type;
          // The Draggable variant, never evt.newIndex: the raw index counts
          // every element child — the empty-state well included — while this
          // one counts only .fb-field matches, which is what the fields
          // array mirrors. The raw pair is how an off-by-one spliced
          // `undefined` into the array and rendered a dead, unopenable card.
          const index = evt.newDraggableIndex;
          evt.clone.replaceWith(evt.item);
          if (!this.defaults[type]) return;
          // Collapsed, not open: the drop already put the card where it
          // belongs, and having it explode into the editor mid-gesture is
          // disorienting. The pencil on the card says what to do next.
          const field = { ...clone(this.defaults[type]), _id: newId() };
          this.fields.splice(index, 0, field);
        },
        onStart: (evt) => {
          putBack = evt.item.nextSibling;
        },
        onEnd: (evt) => {
          // Restore against that saved neighbour rather than an index, which
          // cannot be made to work here for two reasons. The canvas's first
          // child is x-for's own <template>: Sortable's indexes skip template
          // nodes and children[] does not, so every index-based restore is one
          // slot early and dragging the first card lands it ahead of the
          // template, where Alpine will never look for it. And an index only
          // identifies the original neighbour on a downward drag — drag a card
          // upward and children[oldIndex] is a different node than it was.
          // A null neighbour appends, which is right for the last card.
          evt.from.insertBefore(evt.item, putBack);
          putBack = null;

          // Draggable-filtered indexes, for the same reason as onAdd above.
          const oldIndex = evt.oldDraggableIndex;
          const newIndex = evt.newDraggableIndex;
          if (oldIndex === newIndex) return;
          const moved = this.fields.splice(oldIndex, 1)[0];
          if (moved === undefined) return;
          this.fields.splice(newIndex, 0, moved);
        },
      });
    },

    // Each palette group is a drag source: items clone out of it onto the
    // canvas and nothing can be dropped into it. Clicking still adds to the
    // end — Sortable leaves ordinary clicks alone.
    mountPalette() {
      this.$root.querySelectorAll('.fb-palette-group').forEach((el) => {
        Sortable.create(el, {
          group: { name: 'fb-fields', pull: 'clone', put: false },
          sort: false,
          draggable: '.fb-palette-item',
          animation: 150,
          ghostClass: 'fb-ghost',
        });
      });
    },

    // --- Field list ---------------------------------------------------------

    addField(type) {
      const field = { ...clone(this.defaults[type]), _id: newId() };
      this.fields.push(field);
      this.$nextTick(() => {
        const cards = this.$refs.canvas.querySelectorAll('.fb-field');
        const card = cards[cards.length - 1];
        if (card) card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      });
    },

    duplicate(field) {
      // key: null so the copy gets its own — two fields sharing a key would
      // share an answer.
      const copy = { ...clone(field), key: null, _id: newId() };
      this.fields.splice(this.fields.indexOf(field) + 1, 0, copy);
      this.selectedId = copy._id;
    },

    remove(field) {
      this.fields.splice(this.fields.indexOf(field), 1);
    },

    // Keyboard equivalent of dragging the handle. Keeps focus on the handle
    // that moved, so repeated presses walk a question up or down the form.
    moveField(field, delta) {
      const from = this.fields.indexOf(field);
      const to = from + delta;
      if (to < 0 || to >= this.fields.length) return;
      this.fields.splice(from, 1);
      this.fields.splice(to, 0, field);
      this.$nextTick(() => {
        const handles = this.$refs.canvas.querySelectorAll('.fb-handle');
        if (handles[to]) handles[to].focus();
      });
    },

    select(field) {
      this.selectedId = this.selectedId === field._id ? null : field._id;
    },

    // --- Field introspection ------------------------------------------------
    //
    // Which editors a field shows is decided by which keys it has, and those
    // come from the server's FIELD_TYPES. Adding a field type server-side
    // needs no change here.

    has(field, key) {
      return Object.prototype.hasOwnProperty.call(field, key);
    },

    isLayout(field) {
      return field.type === 'heading' || field.type === 'text_block';
    },

    // From the full label map, not the palette — a type hidden from the
    // palette still badges the existing fields that use it.
    typeLabel(type) {
      return (config.labels || {})[type] || type;
    },

    // --- Options ------------------------------------------------------------

    addOption(field) {
      field.options.push({ value: null, label: '' });
    },

    removeOption(field, index) {
      field.options.splice(index, 1);
    },

    moveOption(field, index, delta) {
      const target = index + delta;
      if (target < 0 || target >= field.options.length) return;
      const [moved] = field.options.splice(index, 1);
      field.options.splice(target, 0, moved);
    },

    // --- Saving -------------------------------------------------------------

    questionCount() {
      return this.fields.filter((f) => !this.isLayout(f)).length;
    },

    /*
     * The schema, and only the schema.
     *
     * The name is edited inline against its own endpoint and belongs to the
     * server. Sending it from here too would mean two writers for one field:
     * a rename, then an autosave still carrying the name this page loaded
     * with, which would quietly put the old one back.
     */
    payload() {
      return { schema: this.fields.map(({ _id, ...rest }) => rest) };
    },

    /*
     * Adopt the keys the server just minted — identity only.
     *
     * Never the text. The server trims and truncates labels, and writing its
     * version back over a field someone is still typing into would move their
     * caret. Keys and option values are the only things that must match,
     * because every answer a client gives is filed under them.
     *
     * Position in the SENT array identifies a field: normalize_schema emits
     * exactly one field per field it is given, in order, or rejects the
     * document whole. The sent array is captured by reference at post time,
     * because a drag while the request is in the air reorders this.fields —
     * matching against live indexes would cross keys between fields, and
     * every answer a client gives is filed under those keys. Options are the
     * one in-field exception: normalization drops the blank row "add option"
     * leaves behind, so ours are walked past to stay in step.
     */
    adoptKeys(sent, saved) {
      saved.forEach((savedField, index) => {
        const field = sent[index];
        if (!field) return;
        field.key = savedField.key;
        if (!Array.isArray(field.options) || !Array.isArray(savedField.options)) return;
        let cursor = 0;
        for (const option of field.options) {
          if (!String(option.label || '').trim()) continue;
          if (savedField.options[cursor]) option.value = savedField.options[cursor].value;
          cursor += 1;
        }
      });
    },

    async save(options = {}) {
      clearTimeout(this._timer);
      if (!this.dirty) return;

      // Single-flight: a slow save must not land after a newer one, so the
      // next is queued rather than raced.
      if (this._inFlight) {
        this._queued = true;
        return;
      }
      this._inFlight = true;
      this.saving = true;
      this.error = '';
      const rev = this.rev;
      const sent = this.fields.slice();
      try {
        const res = await fetch(config.saveUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken(),
          },
          body: JSON.stringify({ schema: sent.map(({ _id, ...rest }) => rest) }),
          keepalive: !!options.keepalive,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok) {
          this.error = data.error || 'Could not save this form.';
          return;
        }
        this.quietly(() => this.adoptKeys(sent, data.schema));
        this.savedAt = data.saved_at;
        // Only clean if nothing was typed while the request was in the air.
        if (this.rev === rev) this.$nextTick(() => { this.dirty = false; });
      } catch (e) {
        this.error = 'Could not reach the server. Your changes are still here.';
      } finally {
        this._inFlight = false;
        this.saving = false;
        if (this._queued) {
          this._queued = false;
          this.save();
        }
      }
    },
  }));
});

/*
 * Deep-copy a field object.
 *
 * NOT structuredClone: Alpine wraps everything reachable from x-data in a
 * reactive Proxy, and structuredClone throws DataCloneError on a Proxy — which
 * killed addField() on its first line and made clicking a palette item do
 * nothing at all. A JSON round-trip goes through ordinary property access, so
 * it sees through the proxy, and these are plain JSON field objects anyway.
 */
function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function newId() {
  return (crypto.randomUUID && crypto.randomUUID()) || String(Math.random());
}

function csrfToken() {
  try {
    return JSON.parse(document.body.getAttribute('hx-headers'))['X-CSRFToken'] || '';
  } catch (e) {
    return '';
  }
}
