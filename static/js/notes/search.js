// Search and replace functionality for the notes editor

import {
  Extension,
  Plugin,
  PluginKey,
  Decoration,
  DecorationSet,
} from "../vendor/tiptap.bundle.js";

import { state, bindClick } from "./state.js";
import { scheduleAutosave } from "./autosave.js";

const searchPluginKey = new PluginKey("search");

const EMPTY_SEARCH_STATE = {
  searchTerm: "",
  decorations: DecorationSet.empty,
  matches: [],
};

export const SearchHighlight = Extension.create({
  name: "searchHighlight",

  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: searchPluginKey,
        state: {
          init() {
            return EMPTY_SEARCH_STATE;
          },
          apply(tr, prev, _oldState, newState) {
            const meta = tr.getMeta(searchPluginKey);

            if (meta !== undefined) {
              if (!meta.searchTerm) return EMPTY_SEARCH_STATE;

              const decorations = [];
              const matches = [];
              const escaped = meta.searchTerm.replace(
                /[.*+?^${}()|[\]\\]/g,
                "\\$&",
              );
              const regex = new RegExp(escaped, "gi");

              newState.doc.descendants((node, pos) => {
                if (!node.isText) return;
                let match;

                while ((match = regex.exec(node.text)) !== null) {
                  const from = pos + match.index;
                  const to = from + match[0].length;
                  matches.push({ from, to });
                  const cls =
                    meta.currentIndex === matches.length - 1
                      ? "search-match search-match-current"
                      : "search-match";
                  decorations.push(Decoration.inline(from, to, { class: cls }));
                }
              });

              return {
                searchTerm: meta.searchTerm,
                decorations: DecorationSet.create(newState.doc, decorations),
                matches,
              };
            }

            return {
              searchTerm: prev.searchTerm,
              decorations: prev.decorations.map(tr.mapping, tr.doc),
              matches: prev.matches.map((m) => ({
                from: tr.mapping.map(m.from),
                to: tr.mapping.map(m.to),
              })),
            };
          },
        },
        props: {
          decorations(st) {
            return this.getState(st).decorations;
          },
        },
      }),
    ];
  },
});

// ─── Search dispatch helper ──────────────────────────────────────────────────

function dispatchSearchMeta(searchTerm, currentIndex) {
  if (!state.editor) return;
  const tr = state.editor.state.tr;

  tr.setMeta(searchPluginKey, { searchTerm, currentIndex });
  state.editor.view.dispatch(tr);
}

// ─── Search bar UI ───────────────────────────────────────────────────────────

export function setupSearchBar() {
  const searchInput = document.getElementById("search-input");
  const replaceInput = document.getElementById("replace-input");

  if (searchInput) {
    let searchTimer;
    searchInput.addEventListener("input", () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => performSearch(searchInput.value), 200);
    });

    searchInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        goToNextMatch();
      } else if (e.key === "Escape") hideSearchBar();
    });
  }

  if (replaceInput) {
    replaceInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        replaceCurrentMatch();
      } else if (e.key === "Escape") hideSearchBar();
    });
  }

  bindClick("search-prev", goToPrevMatch);
  bindClick("search-next", goToNextMatch);
  bindClick("replace-one", replaceCurrentMatch);
  bindClick("replace-all", replaceAllMatches);
  bindClick("search-close", hideSearchBar);
  bindClick("search-toggle-btn", (e) => {
    e.preventDefault();
    toggleSearchBar();
  });
}

export function toggleSearchBar() {
  const bar = document.getElementById("search-replace-bar");
  if (bar && bar.classList.contains("visible")) hideSearchBar();
  else showSearchBar();
}

function showSearchBar() {
  const bar = document.getElementById("search-replace-bar");
  const searchInput = document.getElementById("search-input");
  const toggleBtn = document.getElementById("search-toggle-btn");

  if (bar) bar.classList.add("visible");
  if (toggleBtn) toggleBtn.classList.add("active");

  if (searchInput) {
    searchInput.focus();
    searchInput.select();
  }
}

function hideSearchBar() {
  const bar = document.getElementById("search-replace-bar");
  const toggleBtn = document.getElementById("search-toggle-btn");
  const searchInput = document.getElementById("search-input");
  const replaceInput = document.getElementById("replace-input");

  if (bar) bar.classList.remove("visible");
  if (toggleBtn) toggleBtn.classList.remove("active");

  clearSearchHighlights();
  updateSearchCount();

  if (searchInput) searchInput.value = "";
  if (replaceInput) replaceInput.value = "";
  if (state.editor) state.editor.commands.focus();
}

function performSearch(searchTerm) {
  state.searchMatches = [];
  state.currentMatchIndex = -1;

  if (!searchTerm || !state.editor) {
    dispatchSearchMeta("", -1);
    updateSearchCount();

    return;
  }

  dispatchSearchMeta(searchTerm, 0);

  const pluginState = searchPluginKey.getState(state.editor.state);
  if (pluginState && pluginState.matches) {
    state.searchMatches = pluginState.matches;
  }

  if (state.searchMatches.length > 0) {
    state.currentMatchIndex = 0;
    scrollToCurrentMatch();
  }

  updateSearchCount();
}

function clearSearchHighlights() {
  dispatchSearchMeta("", -1);
  state.searchMatches = [];
  state.currentMatchIndex = -1;
}

function updateSearchDecorations() {
  const searchInput = document.getElementById("search-input");
  dispatchSearchMeta(
    searchInput ? searchInput.value : "",
    state.currentMatchIndex,
  );
}

function scrollToCurrentMatch() {
  if (
    state.currentMatchIndex < 0 ||
    state.currentMatchIndex >= state.searchMatches.length
  )
    return;

  requestAnimationFrame(() => {
    const el = document.querySelector(".search-match-current");
    if (!el) return;

    const notePage = document.querySelector(".note-page");
    if (notePage) {
      const matchRect = el.getBoundingClientRect();
      const containerRect = notePage.getBoundingClientRect();

      const scrollTop =
        notePage.scrollTop +
        (matchRect.top - containerRect.top) -
        notePage.clientHeight / 2;
      notePage.scrollTo({ top: Math.max(0, scrollTop), behavior: "smooth" });
    }
  });
}

function updateSearchCount() {
  const countEl = document.getElementById("search-count");

  if (countEl) {
    countEl.textContent =
      state.searchMatches.length === 0
        ? ""
        : state.currentMatchIndex + 1 + " of " + state.searchMatches.length;
  }
}

function goToNextMatch() {
  if (state.searchMatches.length === 0) return;
  state.currentMatchIndex =
    (state.currentMatchIndex + 1) % state.searchMatches.length;
  updateSearchDecorations();
  scrollToCurrentMatch();
  updateSearchCount();
}

function goToPrevMatch() {
  if (state.searchMatches.length === 0) return;
  state.currentMatchIndex =
    (state.currentMatchIndex - 1 + state.searchMatches.length) %
    state.searchMatches.length;
  updateSearchDecorations();
  scrollToCurrentMatch();
  updateSearchCount();
}

function replaceCurrentMatch() {
  if (
    state.currentMatchIndex < 0 ||
    state.currentMatchIndex >= state.searchMatches.length
  )
    return;

  const searchInput = document.getElementById("search-input");
  const replaceInput = document.getElementById("replace-input");
  if (!searchInput || !state.editor) return;

  const match = state.searchMatches[state.currentMatchIndex];
  if (!match) return;

  state.editor
    .chain()
    .focus()
    .setTextSelection({ from: match.from, to: match.to })
    .deleteSelection()
    .insertContent(replaceInput ? replaceInput.value : "")
    .run();

  performSearch(searchInput.value);
  scheduleAutosave();
}

function replaceAllMatches() {
  const searchInput = document.getElementById("search-input");
  const replaceInput = document.getElementById("replace-input");
  if (!searchInput || !state.editor) return;

  const replaceTerm = replaceInput ? replaceInput.value : "";
  if (!searchInput.value || state.searchMatches.length === 0) return;

  state.editor.chain().focus().run();

  state.searchMatches
    .slice()
    .reverse()
    .forEach((match) => {
      state.editor
        .chain()
        .setTextSelection({ from: match.from, to: match.to })
        .deleteSelection()
        .insertContent(replaceTerm)
        .run();
    });

  clearSearchHighlights();
  updateSearchCount();
  scheduleAutosave();
}
