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
 */
document.addEventListener('alpine:init', () => {
  Alpine.data('intakeFormBuilder', (config) => ({
    name: config.name,
    fields: (config.schema || []).map((f) => ({ ...f, _id: newId() })),
    palette: config.palette || [],
    defaults: config.defaults || {},

    selectedId: null,
    preview: false,
    dirty: false,
    saving: false,
    savedAt: '',
    error: '',

    init() {
      this.$watch('fields', () => { this.dirty = true; }, { deep: true });
      this.$watch('name', () => { this.dirty = true; });
      this.mountSortable();
      window.addEventListener('beforeunload', (e) => {
        if (!this.dirty) return;
        e.preventDefault();
        e.returnValue = '';
      });
    },

    mountSortable() {
      Sortable.create(this.$refs.canvas, {
        handle: '.fb-handle',
        animation: 150,
        ghostClass: 'fb-ghost',
        onEnd: (evt) => {
          // Sortable physically moves the node, which desynchronises Alpine's
          // x-for keying. Put it back, reorder the array, and let Alpine
          // re-render as the single source of truth.
          const { oldIndex, newIndex } = evt;
          evt.from.insertBefore(evt.item, evt.from.children[oldIndex]);
          if (oldIndex === newIndex) return;
          const moved = this.fields.splice(oldIndex, 1)[0];
          this.fields.splice(newIndex, 0, moved);
        },
      });
    },

    // --- Field list ---------------------------------------------------------

    addField(type) {
      const field = { ...clone(this.defaults[type]), _id: newId() };
      this.fields.push(field);
      this.selectedId = field._id;
      this.$nextTick(() => {
        const card = this.$refs.canvas.lastElementChild;
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

    typeLabel(type) {
      for (const group of this.palette) {
        const match = group.types.find((t) => t.type === type);
        if (match) return match.label;
      }
      return type;
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

    payload() {
      return {
        name: this.name,
        schema: this.fields.map(({ _id, ...rest }) => rest),
      };
    },

    async save() {
      if (this.saving) return;
      this.saving = true;
      this.error = '';
      try {
        const res = await fetch(config.saveUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken(),
          },
          body: JSON.stringify(this.payload()),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok) {
          this.error = data.error || 'Could not save this form.';
          return;
        }
        // Re-hydrate: the keys the server just minted are what future answers
        // will be filed under, so our copy has to match.
        this.fields = data.schema.map((f) => ({ ...f, _id: newId() }));
        this.savedAt = data.saved_at;
        this.$nextTick(() => { this.dirty = false; });
      } catch (e) {
        this.error = 'Could not reach the server. Your changes are still here.';
      } finally {
        this.saving = false;
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
