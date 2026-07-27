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
 * Saving is automatic and debounced. Two consequences shape the code below.
 * A save must adopt the server's keys without replacing the field objects,
 * because replacing them changes every x-for key and Alpine rebuilds the whole
 * canvas — which would yank the caret out of whatever input is being typed
 * into. And a document mid-edit is not a valid schema (a question added a
 * second ago has no label), so autosave waits for one rather than flashing an
 * error at someone who is simply still typing.
 */
const AUTOSAVE_MS = 1500;

document.addEventListener('alpine:init', () => {
  Alpine.data('intakeFormBuilder', (config) => ({
    fields: (config.schema || []).map((f) => ({ ...f, _id: newId() })),
    palette: config.palette || [],
    defaults: config.defaults || {},

    selectedId: null,
    preview: false,
    dirty: false,
    saving: false,
    savedAt: '',
    error: '',
    // Why the document can't be saved yet, in words, when that is the reason
    // nothing is happening. Distinct from `error`, which means a save failed.
    blocked: '',
    // Why the open editor would not close, shown inside it.
    problem: '',

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

      // A debounced save can still be pending when the tab goes away.
      const flushNow = () => {
        if (document.visibilityState === 'hidden') this.save({ keepalive: true });
      };
      document.addEventListener('visibilitychange', flushNow);
      window.addEventListener('pagehide', () => this.save({ keepalive: true }));

      // Still worth asking: the last save may be blocked on an unlabelled
      // question, in which case there is nothing autosave can do.
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
      // Recomputed on the edit rather than on the save, so labelling a
      // question clears the notice as it is typed instead of a second later.
      this.blocked = this.notReady();
      this.problem = '';
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

    // What stops this one field from being storable, in words, or '' when
    // nothing does. The server rejects a document whole rather than saving
    // half of one, so these are the states to wait through rather than report.
    fieldProblem(field) {
      if (field.type !== 'text_block' && !String(field.label || '').trim()) {
        return field.type === 'heading'
          ? 'Give this heading some text.'
          : 'Give this question a label.';
      }
      if (Array.isArray(field.options)) {
        const filled = field.options.filter((o) => String(o.label || '').trim());
        if (!filled.length) return 'Add at least one option.';
      }
      return '';
    },

    notReady() {
      for (const field of this.fields) {
        if (this.fieldProblem(field)) {
          return 'Waiting — one question is still incomplete.';
        }
      }
      return '';
    },

    // The editor's own Save: check this field, then collapse it and let the
    // save go now rather than on the debounce. Staying open on a problem is
    // the point — closing an incomplete question would hide the reason the
    // form was not saving.
    doneEditing(field) {
      this.problem = this.fieldProblem(field);
      if (this.problem) return;
      this.selectedId = null;
      this.save();
    },

    // The head's save button doubles as the incomplete marker: it stays
    // visible (and red) on a closed incomplete field, and clicking it there
    // opens the field on its problem instead of trying to close it.
    saveClicked(field) {
      if (this.selectedId !== field._id) {
        this.selectedId = field._id;
        this.problem = this.fieldProblem(field);
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

          const { oldIndex, newIndex } = evt;
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
      this.problem = '';
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
      this.problem = '';
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
     * Position identifies a field: normalize_schema emits exactly one field
     * per field it is given, in order, or rejects the document whole. Options
     * are the exception — it drops the blank row that "add option" leaves
     * behind, so ours are walked past to stay in step.
     */
    adoptKeys(saved) {
      saved.forEach((savedField, index) => {
        const field = this.fields[index];
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

      this.blocked = this.notReady();
      if (this.blocked) return;

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
      try {
        const res = await fetch(config.saveUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken(),
          },
          body: JSON.stringify(this.payload()),
          keepalive: !!options.keepalive,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok) {
          this.error = data.error || 'Could not save this form.';
          return;
        }
        this.quietly(() => this.adoptKeys(data.schema));
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
