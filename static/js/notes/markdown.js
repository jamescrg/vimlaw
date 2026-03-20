// Markdown - HTML conversion for the notes editor

import { escapeHtml } from "./state.js";

function formatInline(text) {
  const codePlaceholders = [];
  text = text.replace(/`([^`]+)`/g, (_m, code) => {
    codePlaceholders.push("<code>" + escapeHtml(code) + "</code>");
    return "\x00CODE" + (codePlaceholders.length - 1) + "\x00";
  });

  text = text
    .replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>")
    .replace(/___(.+?)___/g, "<strong><em>$1</em></strong>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/__(.+?)__/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/_(.+?)_/g, "<em>$1</em>")
    .replace(/~~(.+?)~~/g, "<s>$1</s>")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/g==(.+?)==/g, '<mark data-color="mark-green">$1</mark>')
    .replace(/r==(.+?)==/g, '<mark data-color="mark-red">$1</mark>')
    .replace(/p==(.+?)==/g, '<mark data-color="mark-purple">$1</mark>')
    .replace(/o==(.+?)==/g, '<mark data-color="mark-orange">$1</mark>')
    .replace(/c==(.+?)==/g, '<mark data-color="mark-citation">$1</mark>')
    .replace(/a==(.+?)==/g, '<mark data-color="mark-gray">$1</mark>')
    .replace(/==(.+?)==/g, "<mark>$1</mark>");

  return text.replace(
    /\x00CODE(\d+)\x00/g,
    (_m, idx) => codePlaceholders[parseInt(idx)],
  );
}

function buildBlockquote(lines, minDepth) {
  let html = "<blockquote>";
  let j = 0;
  while (j < lines.length) {
    if (lines[j].depth === minDepth) {
      html += "<p>" + lines[j].content + "</p>";
      j++;
    } else if (lines[j].depth > minDepth) {
      const nested = [];
      while (j < lines.length && lines[j].depth > minDepth) {
        nested.push(lines[j]);
        j++;
      }
      html += buildBlockquote(nested, minDepth + 1);
    } else {
      break;
    }
  }
  return html + "</blockquote>";
}

export function markdownToHtml(md) {
  if (!md) return "<p></p>";

  md = md.replace(
    /\[\[doc:(\d+)\|([^\]]+)\]\]/g,
    '<span class="note-ref" data-type="document" data-id="$1">$2</span>',
  );
  md = md.replace(
    /\[\[hl:(\d+)\|([^\]]+)\]\]/g,
    '<span class="note-ref" data-type="highlight" data-id="$1">$2</span>',
  );

  const lines = md.split(/\r?\n/);
  const parsed = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) {
      parsed.push({ type: "blank" });
      continue;
    }

    // Fenced code blocks
    const codeBlockMatch = trimmed.match(/^```(\w*)$/);
    if (codeBlockMatch) {
      const lang = codeBlockMatch[1] || null;
      const codeLines = [];
      i++;

      while (i < lines.length && !lines[i].trim().match(/^```$/)) {
        codeLines.push(lines[i]);
        i++;
      }
      parsed.push({
        type: "codeblock",
        content: escapeHtml(codeLines.join("\n")),
        lang,
      });
      continue;
    }

    // Horizontal rules
    if (/^[-*_]{3,}$/.test(trimmed) && !/^[-*] /.test(trimmed)) {
      parsed.push({ type: "hr" });
      continue;
    }

    // Headers
    const headerMatch = trimmed.match(/^(#{1,5}) (.+)$/);
    if (headerMatch) {
      parsed.push({
        type: "header",
        level: headerMatch[1].length,
        content: formatInline(headerMatch[2]),
      });
      continue;
    }

    // Blockquotes (supports nesting)
    if (trimmed.startsWith("> ") || trimmed === ">") {
      let bqDepth = 0;
      let bqRest = trimmed;
      while (bqRest.startsWith("> ") || bqRest === ">") {
        bqDepth++;
        bqRest = bqRest.startsWith("> ") ? bqRest.substring(2) : "";
      }
      parsed.push({
        type: "blockquote",
        depth: bqDepth,
        content: formatInline(bqRest),
      });
      continue;
    }

    // Unordered list items
    const ulMatch = line.replace(/\r$/, "").match(/^([ \t]*)[-*] (.*)$/);
    if (ulMatch) {
      const depth = Math.floor(ulMatch[1].replace(/\t/g, "  ").length / 2);
      parsed.push({
        type: "li",
        listType: "ul",
        depth,
        content: formatInline(ulMatch[2] || ""),
      });
      continue;
    }

    // Ordered list items
    const olMatch = line.replace(/\r$/, "").match(/^([ \t]*)(\d+)\. (.*)$/);
    if (olMatch) {
      const depth = Math.floor(olMatch[1].replace(/\t/g, "  ").length / 2);
      parsed.push({
        type: "li",
        listType: "ol",
        depth,
        content: formatInline(olMatch[3] || ""),
      });
      continue;
    }

    // Regular paragraph
    parsed.push({ type: "paragraph", content: formatInline(trimmed) });
  }

  // Build HTML
  const result = [];
  let i = 0;

  function buildList(startIndex, minDepth) {
    let idx = startIndex;
    const items = [];

    while (
      idx < parsed.length &&
      parsed[idx].type === "li" &&
      parsed[idx].depth >= minDepth
    ) {
      if (parsed[idx].depth > minDepth) break;

      const item = parsed[idx];
      let liContent = "<li><p>" + item.content + "</p>";
      idx++;

      if (
        idx < parsed.length &&
        parsed[idx].type === "li" &&
        parsed[idx].depth > minDepth
      ) {
        const nested = buildList(idx, parsed[idx].depth);
        liContent += nested.html;
        idx = nested.endIndex;
      }

      liContent += "</li>";
      items.push({ html: liContent, listType: item.listType });
    }

    if (items.length === 0) return { html: "", endIndex: idx };

    const tag = items[0].listType;
    return {
      html:
        "<" +
        tag +
        ">" +
        items.map((it) => it.html).join("") +
        "</" +
        tag +
        ">",
      endIndex: idx,
    };
  }

  while (i < parsed.length) {
    const item = parsed[i];

    if (item.type === "blank") {
      i++;
      continue;
    }

    if (item.type === "header") {
      result.push(
        "<h" + item.level + ">" + item.content + "</h" + item.level + ">",
      );
      i++;
      continue;
    }

    if (item.type === "blockquote") {
      const bqLines = [];
      while (i < parsed.length && parsed[i].type === "blockquote") {
        bqLines.push(parsed[i]);
        i++;
      }
      result.push(buildBlockquote(bqLines, 1));
      continue;
    }

    if (item.type === "codeblock") {
      const langAttr = item.lang ? ' class="language-' + item.lang + '"' : "";
      result.push(
        "<pre><code" + langAttr + ">" + item.content + "</code></pre>",
      );
      i++;
      continue;
    }

    if (item.type === "hr") {
      result.push("<hr>");
      i++;
      continue;
    }

    if (item.type === "paragraph") {
      result.push("<p>" + item.content + "</p>");
      i++;
      continue;
    }

    if (item.type === "li") {
      const listResult = buildList(i, item.depth);
      result.push(listResult.html);
      i = listResult.endIndex;
      continue;
    }

    i++;
  }

  return result.join("") || "<p></p>";
}

const HIGHLIGHT_PREFIXES = {
  "mark-green": "g==",
  "mark-red": "r==",
  "mark-purple": "p==",
  "mark-orange": "o==",
  "mark-citation": "c==",
  "mark-gray": "a==",
};

export function htmlToMarkdown(html) {
  const tempDiv = document.createElement("div");
  tempDiv.innerHTML = html;

  function processNode(node, listDepth, listType, listIndex) {
    if (node.nodeType === Node.TEXT_NODE) return node.textContent;
    if (node.nodeType !== Node.ELEMENT_NODE) return "";

    const tag = node.tagName.toLowerCase();

    function getChildren() {
      return Array.from(node.childNodes)
        .map((child) => processNode(child, listDepth, null, 0))
        .join("");
    }

    // Headings (h1-h5)
    const headingLevel = /^h([1-5])$/.exec(tag);
    if (headingLevel) {
      return (
        "#".repeat(parseInt(headingLevel[1])) + " " + getChildren() + "\n\n"
      );
    }

    switch (tag) {
      case "p":
        return listDepth > 0 ? getChildren() : getChildren() + "\n\n";
      case "strong":
        return "**" + getChildren() + "**";
      case "em":
        return "*" + getChildren() + "*";
      case "s":
        return "~~" + getChildren() + "~~";
      case "mark": {
        const color = node.dataset.color || "";
        for (const [cls, prefix] of Object.entries(HIGHLIGHT_PREFIXES)) {
          if (node.classList.contains(cls) || color === cls) {
            return prefix + getChildren() + "==";
          }
        }
        return "==" + getChildren() + "==";
      }
      case "code":
        if (
          node.parentElement &&
          node.parentElement.tagName.toLowerCase() === "pre"
        ) {
          return node.textContent;
        }
        return "`" + node.textContent + "`";
      case "pre": {
        let lang = "";
        const codeEl = node.querySelector("code");
        if (codeEl) {
          const langClass = Array.from(codeEl.classList).find((c) =>
            c.startsWith("language-"),
          );
          if (langClass) lang = langClass.replace("language-", "");
        }
        return "```" + lang + "\n" + getChildren() + "\n```\n\n";
      }
      case "hr":
        return "---\n\n";
      case "blockquote":
        return (
          getChildren()
            .trim()
            .split("\n")
            .map((line) => "> " + line)
            .join("\n") + "\n\n"
        );
      case "ul":
      case "ol": {
        let result = "";
        let idx = 1;
        Array.from(node.children).forEach((child) => {
          if (child.tagName.toLowerCase() === "li") {
            result += processNode(child, listDepth + 1, tag, idx);
            idx++;
          }
        });
        return listDepth === 0 ? result + "\n" : result;
      }
      case "li": {
        const indent = "  ".repeat(listDepth - 1);
        const prefix = listType === "ol" ? listIndex + ". " : "- ";

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
      }
      case "br":
        return "\n";
      case "span":
        if (
          node.classList.contains("note-ref") ||
          node.getAttribute("data-type")
        ) {
          const refType = node.getAttribute("data-type");
          const refId = node.getAttribute("data-id");
          const label = node.textContent || getChildren();
          if (refType === "document")
            return "[[doc:" + refId + "|" + label + "]]";
          if (refType === "highlight")
            return "[[hl:" + refId + "|" + label + "]]";
        }
        return getChildren();
      default:
        return getChildren();
    }
  }

  return processNode(tempDiv, 0, null, 0)
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
