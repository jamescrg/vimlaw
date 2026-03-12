function showEditFolderForm() {
  // get the folder list item
  const parentElement = event.target.parentElement.parentElement.parentElement;

  // hide the folder
  let child = parentElement.querySelector(".show-folder");
  child.style.display = "none";

  // display the folder edit form and delete icon
  child = parentElement.querySelector(".edit-folder");
  child.style.display = "flex";

  // focus on the edit folder input
  const input = child.querySelector(".edit-folder-input");
  input.focus();

  // move the cursor to the end
  const currentValue = input.value; //store the value of the element
  input.value = ""; //clear the value of the element
  input.value = currentValue;
}

function hideEditFolderForm() {
  // get the folder list item
  const parentElement =
    event.target.parentElement.parentElement.parentElement.parentElement;

  // hide the folder
  let child = parentElement.querySelector(".show-folder");
  child.style.display = "inline";

  // display the folder edit form and delete icon
  child = parentElement.querySelector(".edit-folder");
  child.style.display = "none";
}

function showAddFolderForm() {
  let addFolderItem = document.querySelector("#add-folder-item");
  addFolderItem.style.display = "flex";
  addFolderItem.querySelector(".edit-folder").style.display = "flex";
  addFolderItem.querySelector("#add-folder-input").focus();
}

function hideAddFolderForm() {
  setTimeout(function () {
    const elementId = "add-folder-item";
    hide(elementId);
  }, 0);
}

function moveFocusToEnd(input) {
  const length = input.value.length;

  // Move the caret to the end of the input
  input.setSelectionRange(length, length);

  // Move the focus of the caret to the end of the input
  input.scrollLeft = input.scrollWidth;
}

function getNoteFolderDescendantIds(folderId) {
  const ids = [];
  document
    .querySelectorAll(`[data-parent-id="${folderId}"]`)
    .forEach((child) => {
      const childId = child.dataset.folderId;
      ids.push(childId);
      ids.push(...getNoteFolderDescendantIds(childId));
    });
  return ids;
}

function toggleNoteFolder(folderId, evt) {
  evt.preventDefault();
  evt.stopPropagation();

  const folderEl = document.getElementById(`note-folder-${folderId}`);
  if (!folderEl) return;

  const caret = folderEl.querySelector(".caret-icon");
  if (!caret) return;

  const isExpanded = caret.classList.contains("icon-chevron-down");

  if (isExpanded) {
    caret.classList.replace("icon-chevron-down", "icon-chevron-right");
    getNoteFolderDescendantIds(folderId).forEach((id) => {
      const el = document.getElementById(`note-folder-${id}`);
      if (el) el.classList.add("folder-hidden");
    });
  } else {
    caret.classList.replace("icon-chevron-right", "icon-chevron-down");
    document
      .querySelectorAll(`[data-parent-id="${folderId}"]`)
      .forEach((child) => {
        child.classList.remove("folder-hidden");
      });
  }

  // Persist to session
  const csrfToken = document.body.getAttribute("hx-headers");
  const token = csrfToken ? JSON.parse(csrfToken)["X-CSRFToken"] : "";
  fetch(`/notes/folders/toggle/${folderId}/`, {
    method: "POST",
    headers: { "X-CSRFToken": token },
  });
}

function selectMoveTarget(el, value) {
  const tree = el.closest(".move-tree");
  tree.querySelectorAll(".move-tree-item").forEach((item) => {
    item.classList.remove("move-selected");
  });
  el.classList.add("move-selected");
  tree.closest("form").querySelector("#move-destination").value = value;
}

function getMoveDescendantIds(folderId) {
  const ids = [];
  document
    .querySelectorAll(`[data-move-parent-id="${folderId}"]`)
    .forEach((child) => {
      const childId = child.dataset.moveFolderId;
      ids.push(childId);
      ids.push(...getMoveDescendantIds(childId));
    });
  return ids;
}

function toggleMoveFolder(folderId, evt) {
  evt.preventDefault();
  evt.stopPropagation();

  const folderEl = document.querySelector(
    `[data-move-folder-id="${folderId}"]`
  );
  if (!folderEl) return;

  const caret = folderEl.querySelector(".caret-icon");
  if (!caret) return;

  const isExpanded = caret.classList.contains("icon-chevron-down");

  if (isExpanded) {
    caret.classList.replace("icon-chevron-down", "icon-chevron-right");
    getMoveDescendantIds(folderId).forEach((id) => {
      const el = document.querySelector(`[data-move-folder-id="${id}"]`);
      if (el) el.classList.add("folder-hidden");
    });
  } else {
    caret.classList.replace("icon-chevron-right", "icon-chevron-down");
    document
      .querySelectorAll(`[data-move-parent-id="${folderId}"]`)
      .forEach((child) => {
        child.classList.remove("folder-hidden");
      });
  }
}
