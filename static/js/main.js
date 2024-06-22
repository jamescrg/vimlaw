
//
// utility functions to show and hide elements
//

function show(elementId){
    var item = document.getElementById(elementId);
    item.style.display = 'block';
}

function hide(elementId){
    var item = document.getElementById(elementId);
    item.style.display = 'none';
}

function showHide(elementId){

    var item = document.getElementById(elementId);
    if (item) {
        if (item.style.display == 'none') {
            item.style.display = 'block';
        } else {
            item.style.display = 'none';
        }
    }
}

//
// confirm whether to delete a record
//

function confirmProceed() {
    var check = confirm('Are you sure you want to delete this record?');
    if (check) {
        return
    } else {
        event.stopPropagation();
        event.preventDefault();
    }
}

var confirmLinks = document.querySelectorAll('.confirm');
if (confirmLinks) {
    for (var link of confirmLinks) {
        link.addEventListener('click', confirmProceed);
    }
}


function moveCursorToEnd(id) {

  // move the cursor to the end
  var input = document.getElementById(id);

 //store the value of the element
  var currentValue = input.value;

 //clear the value of the element
  input.value = '';

  input.value = currentValue;

}

function showModal(id) {
    window.onload = () => {
      const myModal = new bootstrap.Modal(id);
      myModal.show();
    }
}


// clear htmx-modal-container after use
// this prevents it from showing up for an instant on subsequent requests
const modal = new bootstrap.Modal(document.getElementById("htmx-modal-container"))

htmx.on("htmx:beforeSwap", (e) => {
  // Empty response targeting #dialog => hide the modal
  if (e.detail.target.id == "htmx-modal-container" && !e.detail.xhr.response) {
    modal.hide()
    e.detail.shouldSwap = false
  }
})

htmx.on("hidden.bs.modal", () => {
  document.getElementById("htmx-modal-container").innerHTML = ""
})


