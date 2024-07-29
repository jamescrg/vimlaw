

function updateRate(){
    /**
     * Update the rate on the time entry form.
     *
     * Changes the value of the "id_firm_rate" input
     * Should be triggered when the "Matter" select input changes.
     */
    var matterElement = document.getElementById("id_matter");
    var matterId = matterElement.options[matterElement.selectedIndex].value;
    document.getElementById("id_rate").value = firm_rates[matterId];

}
