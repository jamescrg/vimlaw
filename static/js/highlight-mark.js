// Highlight mark with real clipboard colors.
//
// TipTap's multicolor Highlight writes the color attribute straight into
// the inline style — but our colors are token names ("mark-green"), so
// copied HTML carried `background-color: mark-green`, which is not a CSS
// color. External paste targets (LibreOffice, Word, Docs) threw the
// highlight away. This override keeps data-color for round-tripping and
// the in-editor CSS, and inlines the real fill so pasted highlights
// survive.

import { Highlight } from "./vendor/tiptap.bundle.js";

// Light-palette fills matching the mark rules in notes-editor.css and
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
  renderHTML({ HTMLAttributes }) {
    const fill = HIGHLIGHT_FILLS[HTMLAttributes["data-color"]] || DEFAULT_FILL;
    return [
      "mark",
      { ...HTMLAttributes, style: "background-color: " + fill },
      0,
    ];
  },
});
