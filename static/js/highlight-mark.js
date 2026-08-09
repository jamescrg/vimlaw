// Highlight mark that external apps can digest.
//
// Two departures from TipTap's stock multicolor Highlight:
//
// 1. It renders <span class="note-hl">, not <mark> — LibreOffice's HTML
//    import drops <mark> elements *including their text*, so copied
//    highlights vanished on paste. Spans survive everywhere. Old <mark>
//    HTML (and the markdown loader's output) still parses.
//
// 2. The inline style carries the real hex fill. Our color values are
//    token names ("mark-green"), which stock Highlight wrote verbatim
//    into background-color — not a CSS color, useless outside the app.
//    data-color keeps the token for round-tripping and the editor CSS.

import { Highlight } from "./vendor/tiptap.bundle.js";

// Light-palette fills matching the highlight rules in notes-editor.css and
// ai.css (hex, not oklch — external HTML parsers only speak hex; values
// are the palette's *-100 steps, which marks keep even in dark themes).
const HIGHLIGHT_FILLS = {
  "mark-green": "#ecfccb",
  "mark-red": "#fee2e2",
  "mark-purple": "#f3e8ff",
  "mark-orange": "#ffedd5",
  "mark-citation": "#ededed",
  "mark-gray": "#e6e6e6",
};
const DEFAULT_FILL = "#fef9c3";

export const HighlightMark = Highlight.extend({
  addAttributes() {
    return {
      color: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-color"),
        renderHTML: (attributes) => {
          if (!attributes.color) return {};
          return { "data-color": attributes.color };
        },
      },
    };
  },

  parseHTML() {
    return [{ tag: "mark" }, { tag: "span.note-hl" }];
  },

  renderHTML({ HTMLAttributes }) {
    const fill = HIGHLIGHT_FILLS[HTMLAttributes["data-color"]] || DEFAULT_FILL;
    const cls = HTMLAttributes.class
      ? HTMLAttributes.class + " note-hl"
      : "note-hl";
    return [
      "span",
      { ...HTMLAttributes, class: cls, style: "background-color: " + fill },
      0,
    ];
  },
});
