// Context menu for the editor's tree panes: folder rows get New subfolder /
// Rename / Delete, matter rows get New folder. One shared floating menu
// (#tree-context-menu, same fixed-position idiom as #highlight-ref-dropdown),
// opened by right-click on a row or its hover kebab. Modals reuse the
// Notes-tab folder forms with ?context=editor; their success responses fire
// noteFoldersChanged, which notes-editor.js turns into a tree refresh.

let menu = null;
let targetLi = null; // the folder/matter row the open menu acts on

export function setupTreeMenu() {
  const container = document.getElementById("file-tree-container");
  menu = document.getElementById("tree-context-menu");
  if (!container || !menu) return;

  container.addEventListener("contextmenu", (e) => {
    const li = e.target.closest(".file-tree-folder, .file-tree-matter");
    if (!li) return;
    e.preventDefault();
    openMenu(li, e.clientX, e.clientY);
  });

  container.addEventListener("click", (e) => {
    const btn = e.target.closest(".file-tree-menu-btn");
    if (!btn) return;
    e.stopPropagation();
    const li = btn.closest(".file-tree-folder, .file-tree-matter");
    const rect = btn.getBoundingClientRect();
    openMenu(li, rect.left, rect.bottom + 4);
  });

  menu.addEventListener("click", (e) => {
    const item = e.target.closest("[data-action]");
    if (!item) return;
    e.preventDefault();
    runAction(item.dataset.action);
    closeMenu();
  });

  document.addEventListener("click", (e) => {
    if (!menu.contains(e.target)) closeMenu();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeMenu();
  });
  document.addEventListener("scroll", closeMenu, true);
}

function openMenu(li, x, y) {
  targetLi = li;
  const isMatter = li.classList.contains("file-tree-matter");
  const atDepthCap = !isMatter && +li.dataset.depth >= 3;

  menu.querySelector("[data-action=new] [data-label]").textContent = isMatter
    ? "New folder"
    : "New subfolder";
  menu.querySelector("[data-action=new]").parentElement.style.display =
    atDepthCap ? "none" : "";
  const folderOnly = isMatter ? "none" : "";
  menu.querySelector("[data-action=rename]").parentElement.style.display =
    folderOnly;
  menu.querySelector("[data-action=delete]").parentElement.style.display =
    folderOnly;

  menu.style.position = "fixed";
  menu.style.left = x + "px";
  menu.style.top = y + "px";
  menu.classList.add("show");
}

function closeMenu() {
  if (menu) menu.classList.remove("show");
  targetLi = null;
}

function runAction(action) {
  if (!targetLi) return;
  const container = document.getElementById("file-tree-container");
  const noteParam = "&note=" + window.NOTE_DATA.id;
  const isMatter = targetLi.classList.contains("file-tree-matter");
  let url;

  if (action === "new") {
    const scope = isMatter
      ? "matter=" + targetLi.dataset.matterId
      : "parent=" + targetLi.dataset.folderId;
    url = container.dataset.folderAddUrl + "?context=editor&" + scope;
  } else if (action === "rename") {
    url = targetLi.dataset.editUrl + "?context=editor" + noteParam;
  } else if (action === "delete") {
    url = targetLi.dataset.deleteUrl + "?context=editor" + noteParam;
  } else {
    return;
  }

  window.htmx.ajax("GET", url, {
    target: "#htmx-modal-container",
    swap: "innerHTML",
  });
}
