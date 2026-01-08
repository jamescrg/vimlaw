/**
 * Prompt Editor - Lightweight TipTap editor for AI prompts
 * A simplified version of notes-editor.js focused on prompt composition
 */

// TipTap imports from local bundle (built with: npm run build)
import {
  Editor,
  Document,
  Paragraph,
  Text,
  Bold,
  Italic,
  Strike,
  Heading,
  BulletList,
  OrderedList,
  ListItem,
  Blockquote,
  HardBreak,
  History,
  Placeholder,
} from "./vendor/tiptap.bundle.js";

let promptEditor = null;

/**
 * Initialize the prompt editor in the given container
 */
export function initPromptEditor(container) {
  if (promptEditor) {
    promptEditor.destroy();
  }

  promptEditor = new Editor({
    element: container,
    extensions: [
      Document,
      Paragraph,
      Text,
      Bold,
      Italic,
      Strike,
      Heading.configure({ levels: [1, 2, 3] }),
      BulletList,
      OrderedList,
      ListItem,
      Blockquote,
      HardBreak,
      History,
      Placeholder.configure({
        placeholder: "Compose your prompt here...",
      }),
    ],
    content: "",
    autofocus: true,
  });

  // Set up toolbar buttons
  setupToolbar();

  return promptEditor;
}

/**
 * Set up toolbar button click handlers
 */
function setupToolbar() {
  if (!promptEditor) return;

  const toolbar = document.querySelector(".prompt-editor-toolbar");
  if (!toolbar) return;

  // Bold
  const btnBold = toolbar.querySelector("#btn-bold");
  if (btnBold) {
    btnBold.addEventListener("click", () => {
      promptEditor.chain().focus().toggleBold().run();
      updateToolbarState();
    });
  }

  // Italic
  const btnItalic = toolbar.querySelector("#btn-italic");
  if (btnItalic) {
    btnItalic.addEventListener("click", () => {
      promptEditor.chain().focus().toggleItalic().run();
      updateToolbarState();
    });
  }

  // Strike
  const btnStrike = toolbar.querySelector("#btn-strike");
  if (btnStrike) {
    btnStrike.addEventListener("click", () => {
      promptEditor.chain().focus().toggleStrike().run();
      updateToolbarState();
    });
  }

  // Headings
  [1, 2, 3].forEach((level) => {
    const btn = toolbar.querySelector(`#btn-h${level}`);
    if (btn) {
      btn.addEventListener("click", () => {
        promptEditor.chain().focus().toggleHeading({ level }).run();
        updateToolbarState();
      });
    }
  });

  // Bullet list
  const btnBullet = toolbar.querySelector("#btn-bullet");
  if (btnBullet) {
    btnBullet.addEventListener("click", () => {
      promptEditor.chain().focus().toggleBulletList().run();
      updateToolbarState();
    });
  }

  // Ordered list
  const btnOrdered = toolbar.querySelector("#btn-ordered");
  if (btnOrdered) {
    btnOrdered.addEventListener("click", () => {
      promptEditor.chain().focus().toggleOrderedList().run();
      updateToolbarState();
    });
  }

  // Blockquote
  const btnQuote = toolbar.querySelector("#btn-quote");
  if (btnQuote) {
    btnQuote.addEventListener("click", () => {
      promptEditor.chain().focus().toggleBlockquote().run();
      updateToolbarState();
    });
  }

  // Update toolbar state on selection change
  promptEditor.on("selectionUpdate", updateToolbarState);
  promptEditor.on("update", updateToolbarState);
}

/**
 * Update toolbar button active states based on current selection
 */
function updateToolbarState() {
  if (!promptEditor) return;

  const toolbar = document.querySelector(".prompt-editor-toolbar");
  if (!toolbar) return;

  // Bold
  const btnBold = toolbar.querySelector("#btn-bold");
  if (btnBold) {
    btnBold.classList.toggle("active", promptEditor.isActive("bold"));
  }

  // Italic
  const btnItalic = toolbar.querySelector("#btn-italic");
  if (btnItalic) {
    btnItalic.classList.toggle("active", promptEditor.isActive("italic"));
  }

  // Strike
  const btnStrike = toolbar.querySelector("#btn-strike");
  if (btnStrike) {
    btnStrike.classList.toggle("active", promptEditor.isActive("strike"));
  }

  // Headings
  [1, 2, 3].forEach((level) => {
    const btn = toolbar.querySelector(`#btn-h${level}`);
    if (btn) {
      btn.classList.toggle("active", promptEditor.isActive("heading", { level }));
    }
  });

  // Bullet list
  const btnBullet = toolbar.querySelector("#btn-bullet");
  if (btnBullet) {
    btnBullet.classList.toggle("active", promptEditor.isActive("bulletList"));
  }

  // Ordered list
  const btnOrdered = toolbar.querySelector("#btn-ordered");
  if (btnOrdered) {
    btnOrdered.classList.toggle("active", promptEditor.isActive("orderedList"));
  }

  // Blockquote
  const btnQuote = toolbar.querySelector("#btn-quote");
  if (btnQuote) {
    btnQuote.classList.toggle("active", promptEditor.isActive("blockquote"));
  }
}

/**
 * Convert HTML content to markdown
 */
function htmlToMarkdown(html) {
  const tempDiv = document.createElement("div");
  tempDiv.innerHTML = html;

  function processNode(node, listDepth, listType, listIndex) {
    if (node.nodeType === Node.TEXT_NODE) {
      return node.textContent;
    }

    if (node.nodeType !== Node.ELEMENT_NODE) return "";

    const tag = node.tagName.toLowerCase();

    function getChildren() {
      return Array.from(node.childNodes)
        .map((child) => processNode(child, listDepth, null, 0))
        .join("");
    }

    switch (tag) {
      case "h1":
        return "# " + getChildren() + "\n\n";
      case "h2":
        return "## " + getChildren() + "\n\n";
      case "h3":
        return "### " + getChildren() + "\n\n";
      case "p":
        if (listDepth > 0) {
          return getChildren();
        }
        return getChildren() + "\n\n";
      case "strong":
        return "**" + getChildren() + "**";
      case "em":
        return "*" + getChildren() + "*";
      case "s":
        return "~~" + getChildren() + "~~";
      case "blockquote":
        return (
          getChildren()
            .trim()
            .split("\n")
            .map((line) => "> " + line)
            .join("\n") + "\n\n"
        );
      case "ul":
      case "ol":
        let result = "";
        let idx = 1;
        Array.from(node.children).forEach((child) => {
          if (child.tagName.toLowerCase() === "li") {
            result += processNode(child, listDepth + 1, tag, idx);
            idx++;
          }
        });
        if (listDepth === 0) {
          result += "\n";
        }
        return result;
      case "li":
        const indent = "  ".repeat(listDepth - 1);
        let prefix;
        if (listType === "ol") {
          prefix = listIndex + ". ";
        } else {
          prefix = "- ";
        }

        let textContent = "";
        let nestedLists = "";

        Array.from(node.childNodes).forEach((child) => {
          if (child.nodeType === Node.ELEMENT_NODE) {
            const childTag = child.tagName.toLowerCase();
            if (childTag === "ul" || childTag === "ol") {
              nestedLists += processNode(child, listDepth, null, 0);
            } else {
              textContent += processNode(child, listDepth, null, 0);
            }
          } else {
            textContent += processNode(child, listDepth, null, 0);
          }
        });

        return indent + prefix + textContent.trim() + "\n" + nestedLists;
      case "br":
        return "\n";
      default:
        return getChildren();
    }
  }

  let markdown = processNode(tempDiv, 0, null, 0);
  markdown = markdown.replace(/\n{3,}/g, "\n\n").trim();
  return markdown;
}

/**
 * Get the current editor content as markdown
 */
export function getMarkdownContent() {
  if (!promptEditor) return "";
  const html = promptEditor.getHTML();
  return htmlToMarkdown(html);
}

/**
 * Get the current editor content as HTML
 */
export function getHtmlContent() {
  if (!promptEditor) return "";
  return promptEditor.getHTML();
}

/**
 * Set the editor content from HTML
 */
export function setHtmlContent(html) {
  if (!promptEditor) return;
  promptEditor.commands.setContent(html);
}

/**
 * Clear all editor content
 */
export function clearContent() {
  if (!promptEditor) return;
  promptEditor.commands.clearContent();
}

/**
 * Destroy the editor instance and clean up
 */
export function destroyPromptEditor() {
  if (promptEditor) {
    promptEditor.destroy();
    promptEditor = null;
  }
}

/**
 * Check if editor has content
 */
export function hasContent() {
  if (!promptEditor) return false;
  return !promptEditor.isEmpty;
}
