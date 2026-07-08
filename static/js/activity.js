

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


function updateTrustAvailable(){
    /**
     * Show how much trust money remains for the selected matter, so the
     * attorney is aware while billing. Mirrors updateRate(): fires on matter
     * change and on form load.
     */
    var matterElement = document.getElementById("id_matter");
    var row = document.getElementById("trust-available");
    var value = document.getElementById("trust-available-value");
    if (!matterElement || !row || !value) {
        return;
    }

    var matterId = matterElement.options[matterElement.selectedIndex].value;
    if (!matterId) {
        row.style.display = "none";
        return;
    }

    fetch(`/activity/time/trust-available/${matterId}`)
        .then(response => response.json())
        .then(data => {
            value.textContent = data.display;
            value.classList.toggle("is-negative", data.negative);
            row.style.display = "flex";
        })
        .catch(error => {
            console.error('Error fetching trust available:', error);
            row.style.display = "none";
        });
}


// Abbreviation codes cache
let abbreviationCodes = null;

/**
 * Initialize abbreviation preview functionality
 * Fetches abbreviation codes and sets up event listener on the actions textarea
 */
function initAbbreviationPreview() {
    const actionsTextarea = document.getElementById('id_actions');
    const previewContainer = document.getElementById('actions-preview');
    const previewText = document.getElementById('actions-preview-text');

    if (!actionsTextarea || !previewContainer || !previewText) {
        return; // Elements not found, exit early
    }

    // Fetch abbreviation codes if not already cached
    if (!abbreviationCodes) {
        fetch('/activity/time/codes/json/')
            .then(response => response.json())
            .then(codes => {
                abbreviationCodes = codes;
                updatePreview(); // Update preview with initial value
            })
            .catch(error => {
                console.error('Error fetching abbreviation codes:', error);
            });
    }

    // Function to update the preview
    function updatePreview() {
        if (!abbreviationCodes) return;

        const originalText = actionsTextarea.value;

        // abbreviationCodes is an ordered list of [code, expansion] pairs
        // (longest-first), matching the server's save-time order so the preview
        // and the saved text always agree.
        let expandedText = originalText;
        for (const [code, expansion] of abbreviationCodes) {
            expandedText = expandedText.replaceAll(code, expansion);
        }

        // Show the preview (and its checkbox) whenever there's something to
        // expand. The checkbox only controls whether the expansion is applied
        // on save (server-side) — it never hides the preview.
        const hasCodes = originalText.trim() && expandedText !== originalText;
        if (hasCodes) {
            previewText.textContent = expandedText;
            previewContainer.style.display = 'flex';
        } else {
            previewContainer.style.display = 'none';
        }
    }

    // Add event listener for input changes
    actionsTextarea.addEventListener('input', updatePreview);

    // Update preview on initial load (for edit mode)
    updatePreview();
}

// Initialize preview when modal content is loaded
document.body.addEventListener('htmx:afterSettle', function(event) {
    // Check if the time entry form was loaded
    if (document.getElementById('time-entry-form')) {
        initAbbreviationPreview();
        updateTrustAvailable();
    }
});
