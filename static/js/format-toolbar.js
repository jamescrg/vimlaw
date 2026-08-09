// Shared formatting toolbar for TipTap editors.
// Pairs with templates/components/format-toolbar.html (buttons carry
// data-cmd) and the .format-toolbar styles in interface.css. Used by the
// notes editor and the AI compose-prompt modal so both surfaces share one
// formatting UX.

const COMMANDS = {
  bold: {
    run: (e) => e.chain().focus().toggleBold().run(),
    active: (e) => e.isActive("bold"),
  },
  italic: {
    run: (e) => e.chain().focus().toggleItalic().run(),
    active: (e) => e.isActive("italic"),
  },
  strike: {
    run: (e) => e.chain().focus().toggleStrike().run(),
    active: (e) => e.isActive("strike"),
  },
  h1: {
    run: (e) => e.chain().focus().toggleHeading({ level: 1 }).run(),
    active: (e) => e.isActive("heading", { level: 1 }),
  },
  h2: {
    run: (e) => e.chain().focus().toggleHeading({ level: 2 }).run(),
    active: (e) => e.isActive("heading", { level: 2 }),
  },
  h3: {
    run: (e) => e.chain().focus().toggleHeading({ level: 3 }).run(),
    active: (e) => e.isActive("heading", { level: 3 }),
  },
  bullet: {
    run: (e) => e.chain().focus().toggleBulletList().run(),
    active: (e) => e.isActive("bulletList"),
  },
  ordered: {
    run: (e) => e.chain().focus().toggleOrderedList().run(),
    active: (e) => e.isActive("orderedList"),
  },
  quote: {
    run: (e) => e.chain().focus().toggleBlockquote().run(),
    active: (e) => e.isActive("blockquote"),
  },
};

// Wire a .format-toolbar container to a TipTap editor: clicks run the
// command, and .active tracks the selection. Safe to call again with a new
// editor instance (the notes editor rebuilds on every note switch) — onclick
// assignment replaces the stale handler instead of stacking a new listener.
export function connectFormatToolbar(toolbar, editor) {
  if (!toolbar || !editor) return;

  const buttons = Array.from(toolbar.querySelectorAll("[data-cmd]")).filter(
    (btn) => COMMANDS[btn.dataset.cmd],
  );

  const update = () => {
    for (const btn of buttons) {
      btn.classList.toggle("active", COMMANDS[btn.dataset.cmd].active(editor));
    }
  };

  for (const btn of buttons) {
    btn.onclick = () => {
      COMMANDS[btn.dataset.cmd].run(editor);
      update();
    };
  }

  editor.on("selectionUpdate", update);
  editor.on("update", update);
  update();
}
