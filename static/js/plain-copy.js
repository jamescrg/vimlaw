// Copies leave the editor as clean text.
//
// LibreOffice's HTML import drops the *content* of our highlight spans and
// reference-chip spans, so highlighted words and citations vanished on
// paste. Rather than chase LO's parser, the copied slice is scrubbed at
// the model level: highlight marks are stripped (the words stay, bare) and
// reference chips flatten to their label text. Real formatting — italic,
// bold, strike, headings, lists — survives untouched. Applies to both
// clipboard flavors and to cut as well as copy; pasting back into the
// editor gets the same cleaned content.

import { Extension, Plugin, PluginKey } from "./vendor/tiptap.bundle.js";

function cleaned(fragment) {
  const out = [];
  fragment.forEach((child) => {
    if (child.type.name === "noteRef") {
      if (child.attrs.label) out.push(child.type.schema.text(child.attrs.label));
      return;
    }
    let node = child;
    if (child.isText) {
      const marks = child.marks.filter((m) => m.type.name !== "highlight");
      if (marks.length !== child.marks.length) node = child.mark(marks);
    } else if (child.content.size) {
      node = child.copy(cleaned(child.content));
    }
    out.push(node);
  });
  return fragment.constructor.fromArray(out);
}

export const PlainCopy = Extension.create({
  name: "plainCopy",

  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: new PluginKey("plainCopy"),
        props: {
          transformCopied: (slice) => {
            const SliceCtor = slice.constructor;
            return new SliceCtor(
              cleaned(slice.content),
              slice.openStart,
              slice.openEnd,
            );
          },
        },
      }),
    ];
  },
});
