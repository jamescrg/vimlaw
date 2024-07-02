function showEditFolderForm() {

    // get the folder list item
    const parentElement = event.target.parentElement.parentElement;

    // hide the folder
    let child = parentElement.querySelector('.show-folder');
    child.style.display = 'none';

    // display the folder edit form and delete icon
    child = parentElement.querySelector('.edit-folder');
    child.style.display = 'flex';

    // focus on the edit folder input
    const input = child.querySelector('.edit-folder-input');
    input.focus();

    // move the cursor to the end
    const currentValue = input.value; //store the value of the element
    input.value = ''; //clear the value of the element
    input.value = currentValue;
}


function hideEditFolderForm() {

    // get the folder list item
    const parentElement = event.target.parentElement.parentElement.parentElement;

    setTimeout(function () {

        // hide the folder
        let child = parentElement.querySelector('.show-folder');
        child.style.display = 'inline';

        // display the folder edit form and delete icon
        child = parentElement.querySelector('.edit-folder');
        child.style.display = 'none';

    }, 500);
}


function showAddFolderForm() {
    let addFolderItem = document.querySelector('#add-folder-item');
    addFolderItem.style.display = 'flex';
    addFolderItem.querySelector('.edit-folder').style.display = 'flex';
    addFolderItem.querySelector('#add-folder-input').focus();
}


function hideAddFolderForm() {

    const parentElement = event.target.parentElement.parentElement.parentElement;

    setTimeout(function () {
        const elementId = 'add-folder-item';
        hide(elementId);
    }, 500);
}
