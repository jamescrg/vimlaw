//
// utility functions to show and hide elements
//

function show(elementId) {
    const item = document.getElementById(elementId);
    item.style.display = 'block';
}

function hide(elementId) {
    const item = document.getElementById(elementId);
    item.style.display = 'none';
}


function confirmProceed() {
    const check = confirm('Are you sure you want to delete this record?');
    if (check) {
        return
    } else {
        event.stopPropagation();
        event.preventDefault();
    }
}

const confirmLinks = document.querySelectorAll('.confirm');
if (confirmLinks) {
    for (const link of confirmLinks) {
        link.addEventListener('click', confirmProceed);
    }
}


// clear htmx-modal-container after use
// this prevents it from showing up for an instant on subsequent requests
const modal = new bootstrap.Modal(document.getElementById("htmx-modal-container"))

htmx.on("htmx:beforeSwap", (e) => {
    // Empty response targeting #dialog => hide the modal
    if (e.detail.target.id === "htmx-modal-container" && !e.detail.xhr.response) {
        modal.hide()
        e.detail.shouldSwap = false
    }
})

htmx.on("hidden.bs.modal", () => {
    document.getElementById("htmx-modal-container").innerHTML = ""
})
