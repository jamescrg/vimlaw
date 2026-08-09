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
  h4: {
    run: (e) => e.chain().focus().toggleHeading({ level: 4 }).run(),
    active: (e) => e.isActive("heading", { level: 4 }),
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

// The last-used highlight color, shared across surfaces so the swatch the
// user picked in one editor greets them in the next ("" = default yellow).
const HL_STORAGE_KEY = "format-toolbar-hl-color";

// LibreOffice-style split button: main half toggles the current color on the
// selection, caret opens the color menu, picking a color both remembers and
// applies it. Returns the main button (for active-state tracking) or null
// when the surface has no highlight support.
function wireHighlight(toolbar, editor) {
  const split = toolbar.querySelector(".hl-split");
  if (!split) return null;

  // Surfaces whose editor lacks the Highlight extension lose the button
  if (typeof editor.commands.toggleHighlight !== "function") {
    split.style.display = "none";
    return null;
  }
  split.style.display = "";

  const toggleBtn = split.querySelector("[data-hl-toggle]");
  const swatch = split.querySelector("[data-hl-swatch]");
  const menu = split.querySelector("[data-hl-menu]");

  let current = localStorage.getItem(HL_STORAGE_KEY) || "";
  const paintSwatch = () => {
    swatch.dataset.color = current;
  };

  toggleBtn.onclick = () => {
    menu.hidden = true;
    if (editor.isActive("highlight")) {
      editor.chain().focus().unsetHighlight().run();
    } else if (current) {
      editor.chain().focus().setHighlight({ color: current }).run();
    } else {
      editor.chain().focus().setHighlight().run();
    }
  };

  split.querySelector("[data-hl-caret]").onclick = () => {
    menu.hidden = !menu.hidden;
  };

  for (const btn of menu.querySelectorAll("[data-hl-color]")) {
    btn.onclick = () => {
      const value = btn.dataset.hlColor;
      menu.hidden = true;
      if (value === "none") {
        editor.chain().focus().unsetHighlight().run();
        return;
      }
      current = value;
      localStorage.setItem(HL_STORAGE_KEY, current);
      paintSwatch();
      if (current) {
        editor.chain().focus().setHighlight({ color: current }).run();
      } else {
        editor.chain().focus().setHighlight().run();
      }
    };
  }

  // Close the menu on any outside click (bound once; the toolbar element
  // survives editor rebuilds)
  if (!toolbar.dataset.hlOutsideBound) {
    toolbar.dataset.hlOutsideBound = "true";
    document.addEventListener("click", (e) => {
      if (!split.contains(e.target)) menu.hidden = true;
    });
  }

  paintSwatch();
  return toggleBtn;
}

// Wire a .format-toolbar container to a TipTap editor: clicks run the
// command, and .active tracks the selection. Safe to call again with a new
// editor instance (the notes editor rebuilds on every note switch) — onclick
// assignment replaces the stale handler instead of stacking a new listener.
export function connectFormatToolbar(toolbar, editor) {
  if (!toolbar || !editor) return;

  const buttons = Array.from(toolbar.querySelectorAll("[data-cmd]")).filter(
    (btn) => COMMANDS[btn.dataset.cmd],
  );
  const hlToggleBtn = wireHighlight(toolbar, editor);

  const update = () => {
    for (const btn of buttons) {
      btn.classList.toggle("active", COMMANDS[btn.dataset.cmd].active(editor));
    }
    if (hlToggleBtn) {
      hlToggleBtn.classList.toggle("active", editor.isActive("highlight"));
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
