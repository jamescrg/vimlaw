// SortableJS integration for the tasks Kanban board.
// Drag a card between columns to change its status; reorder within a column to
// set priority. Order + status are persisted via POST /tasks/board/move/.
(function () {
  function getCSRFToken() {
    var body = document.querySelector("body");
    var hxHeaders = body && body.getAttribute("hx-headers");
    if (hxHeaders) {
      try {
        return JSON.parse(hxHeaders)["X-CSRFToken"] || "";
      } catch (e) {
        /* ignore */
      }
    }
    return "";
  }

  function updateColumnCounts(board) {
    board.querySelectorAll(".kanban-column").forEach(function (column) {
      var count = column.querySelectorAll(".kanban-card").length;
      var badge = column.querySelector(".kanban-column-count");
      if (badge) badge.textContent = count;
    });
  }

  // Fill the viewport: the board runs from its top edge to the bottom of the
  // window (less a small gutter), so columns are full-height and scroll
  // internally. Measured rather than hard-coded so it survives the dev banner,
  // toolbar height changes, and the collapsible sidebar.
  function sizeBoard() {
    var board = document.getElementById("tasks-board");
    if (!board) return;
    var top = board.getBoundingClientRect().top;
    board.style.height = Math.max(240, window.innerHeight - top - 24) + "px";
  }

  function persistMove(board, item, to) {
    var statusSlug = to.dataset.statusSlug;
    var orderedIds = Array.from(to.querySelectorAll(".kanban-card")).map(function (c) {
      return c.dataset.taskId;
    });

    // Optimistic UI: reflect the new column's state immediately.
    item.classList.toggle("complete", statusSlug === "complete");
    if (statusSlug === "complete") item.classList.remove("past-due");
    updateColumnCounts(board);

    fetch("/tasks/board/move/", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCSRFToken(),
      },
      body: JSON.stringify({
        task_id: item.dataset.taskId,
        status_slug: statusSlug,
        ordered_ids: orderedIds,
      }),
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        if (!data || !data.ok) {
          // Toast is a top-level const in toasts.js — a global binding, not a
          // window property — so reach it by name, not via window.Toast.
          if (data && data.message && typeof Toast !== "undefined") {
            Toast.warning(data.message);
          }
          // Re-render the board from the server's truth to undo the drop.
          htmx.trigger(document.body, "tasksListChanged");
        }
      })
      .catch(function () {
        htmx.trigger(document.body, "tasksListChanged");
      });
  }

  function initTaskBoard() {
    var board = document.getElementById("tasks-board");
    if (!board) return;

    // The whole card is the drag handle (Jira-style). A plain click opens the
    // editor; a drag (past fallbackTolerance) moves the card and is followed by
    // a suppressed click so the drop doesn't also open the editor.
    if (!board.dataset.clickInit) {
      board.dataset.clickInit = "1";
      board.addEventListener("click", function (e) {
        if (board._suppressClick) return;
        // Let the checklist/notes buttons handle their own clicks.
        if (e.target.closest("a, button")) return;
        var card = e.target.closest(".kanban-card");
        if (!card) return;
        var url = card.dataset.editUrl;
        if (url) htmx.ajax("GET", url, { target: "#htmx-modal-container" });
      });
    }

    board.querySelectorAll(".kanban-column-cards").forEach(function (list) {
      if (list.dataset.sortableInit) return;
      list.dataset.sortableInit = "1";
      Sortable.create(list, {
        group: "tasks",
        animation: 150,
        ghostClass: "sortable-ghost",
        dragClass: "sortable-drag",
        draggable: ".kanban-card",
        // Don't start a drag from the interactive controls (priority dropdown,
        // checklist/notes buttons); let their click (and htmx request) through.
        filter: ".kanban-card-btn, .kanban-card-priority",
        preventOnFilter: false,
        // Sortable's own drag impl with a small pixel threshold so a click
        // (under 5px of movement) never registers as a drag.
        forceFallback: true,
        fallbackTolerance: 5,
        // Show the grabbing cursor only once a drag is actually under way,
        // not on hover.
        onStart: function () {
          document.body.classList.add("kanban-dragging");
        },
        onEnd: function (evt) {
          document.body.classList.remove("kanban-dragging");
          board._suppressClick = true;
          setTimeout(function () {
            board._suppressClick = false;
          }, 100);
          persistMove(board, evt.item, evt.to);
        },
      });
    });

    sizeBoard();
  }

  document.addEventListener("DOMContentLoaded", initTaskBoard);
  window.addEventListener("resize", sizeBoard);
  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.target.id === "tasks") {
      initTaskBoard();
    }
  });
})();
