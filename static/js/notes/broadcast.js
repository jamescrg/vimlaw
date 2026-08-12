// Cross-tab messaging for the notes editor (BroadcastChannel).
//
// Navigation state is per-tab (tab-state.js), but the data is shared —
// so structural changes and saves announce themselves to sibling tabs:
//   tree-changed            → other tabs re-fetch the trees (each
//                             re-applies its OWN expansion + scroll)
//   note-saved {noteId, updatedAt}
//                           → a clean tab on the same note silently
//                             reloads; a dirty one enters conflict
//   note-deleted {noteId}   → a tab with that note open bails to launch
// Messages are never delivered to the posting tab (per spec), so
// senders need no echo guard. Handlers are injected by notes-editor.js
// to keep this module dependency-free.

let channel = null;

export function broadcast(msg) {
  if (channel) channel.postMessage(msg);
}

export function setupBroadcast(handlers) {
  if (!("BroadcastChannel" in window)) return;
  channel = new BroadcastChannel("notes-editor");
  channel.addEventListener("message", (e) => {
    const msg = e.data || {};
    const handler = handlers[msg.type];
    if (handler) handler(msg);
  });
}
