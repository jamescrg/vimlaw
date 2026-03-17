function showStatusForm() {
    /**
     * Show a matter's "edit status" form.
     */
    const parentElement = event.target.parentElement;
    const showStatusButton = parentElement.querySelector('.show-status-form-button');
    const statusForm = parentElement.querySelector('.edit-status');

    showStatusButton.style.display = 'none';
    statusForm.style.display = 'block';
    statusForm.focus();

    const input = statusForm.querySelector('.edit-status-input');
    input.focus();

    // move the cursor to the end
    let currentValue = input.value; //store the value of the element
    input.value = ''; //clear the value of the element
    input.value = currentValue;
}


document.addEventListener('keydown', function(event) {
    if (event.key !== 'Enter') return;
    const input = event.target;
    if (!input.classList.contains('toolbar-search')) return;
    event.preventDefault();
    const url = input.getAttribute('data-search-url');
    htmx.ajax('GET', url + '?q=' + encodeURIComponent(input.value) + '&enter=1', {target: '#matter-list-body'});
});


function hideStatusForm() {
    /**
     * Hide a matter's "edit status" form.
     */
    const parentElement = event.target.parentElement.parentElement.parentElement;

    setTimeout(function () {

        // show the status link
        let child = parentElement.querySelector('.show-status-form-button');
        child.style.display = 'block';

        // hide the status form
        child = parentElement.querySelector('.edit-status');
        child.style.display = 'none';

    }, 500);
}
