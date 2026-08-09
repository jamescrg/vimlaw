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

import { connectFormatToolbar } from "./format-toolbar.js";
import { HighlightMark } from "./highlight-mark.js";

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
      Heading.configure({ levels: [1, 2, 3, 4] }),
      BulletList,
      OrderedList,
      ListItem,
      Blockquote,
      HardBreak,
      History,
      HighlightMark.configure({ multicolor: true }),
      Placeholder.configure({
        placeholder: "Compose your prompt here...",
      }),
    ],
    content: "",
  });

  // Wire the shared formatting toolbar to this editor instance
  connectFormatToolbar(
    document.querySelector(".prompt-editor-toolbar"),
    promptEditor,
  );

  return promptEditor;
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
      case "h4":
        return "#### " + getChildren() + "\n\n";
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
      case "mark": {
        // Same colored-highlight syntax the notes editor round-trips
        const prefixes = {
          "mark-green": "g==",
          "mark-red": "r==",
          "mark-purple": "p==",
          "mark-orange": "o==",
          "mark-gray": "a==",
        };
        const color = node.dataset.color || "";
        return (prefixes[color] || "==") + getChildren() + "==";
      }
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
