// TipTap core
export { Editor, Node, Extension, Mark } from '@tiptap/core';

// Extensions
export { default as Document } from '@tiptap/extension-document';
export { default as Paragraph } from '@tiptap/extension-paragraph';
export { default as Text } from '@tiptap/extension-text';
export { default as Bold } from '@tiptap/extension-bold';
export { default as Italic } from '@tiptap/extension-italic';
export { default as Strike } from '@tiptap/extension-strike';
export { default as Heading } from '@tiptap/extension-heading';
export { default as BulletList } from '@tiptap/extension-bullet-list';
export { default as OrderedList } from '@tiptap/extension-ordered-list';
export { default as ListItem } from '@tiptap/extension-list-item';
export { default as Blockquote } from '@tiptap/extension-blockquote';
export { default as HardBreak } from '@tiptap/extension-hard-break';
export { default as History } from '@tiptap/extension-history';
export { default as Dropcursor } from '@tiptap/extension-dropcursor';
export { default as Gapcursor } from '@tiptap/extension-gapcursor';
export { default as Highlight } from '@tiptap/extension-highlight';
export { default as Placeholder } from '@tiptap/extension-placeholder';

// ProseMirror utilities needed for custom plugins
export { Plugin, PluginKey } from '@tiptap/pm/state';
export { Decoration, DecorationSet } from '@tiptap/pm/view';
