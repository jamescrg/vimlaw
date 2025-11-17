

function updateRate(){
    /**
     * Update the rate on the time entry form.
     *
     * Changes the value of the "id_rate" input
     * Should be triggered when the "Matter" select input changes.
     *
     * Makes an AJAX request to fetch the rate for the selected matter.
     */
    var matterElement = document.getElementById("id_matter");
    var matterId = matterElement.options[matterElement.selectedIndex].value;

    if (matterId) {
        fetch(`/activity/time/set-rate/${matterId}`)
            .then(response => response.text())
            .then(rate => {
                document.getElementById("id_rate").value = rate;
            })
            .catch(error => {
                console.error('Error fetching rate:', error);
            });
    }

}
