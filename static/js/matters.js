
function showStatusForm(){
    /**
     * Show a matter's "edit status" form.
     */

    var parentElement = event.target.parentElement;
    var showStatusButton = parentElement.querySelector('.show-status-form-button');
    var statusForm = parentElement.querySelector('.edit-status');

    showStatusButton.style.display = 'none';
    statusForm.style.display = 'block';
    statusForm.focus();

    var input = statusForm.querySelector('.edit-status-input');
    input.focus();

    // move the cursor to the end
    var currentValue = input.value; //store the value of the element
    input.value = ''; //clear the value of the element
    input.value = currentValue;
}


function hideStatusForm(){
    /**
     * Hide a matter's "edit status" form.
     */

    // get the folder list item
    var parentElement = event.target.parentElement.parentElement;

    setTimeout(function () {

        // show the status link
        var child = parentElement.querySelector('.show-status-form-button');
        child.style.display = 'block';

        // hide the status form
        var child = parentElement.querySelector('.edit-status');
        child.style.display = 'none';

    }, 500);
}

