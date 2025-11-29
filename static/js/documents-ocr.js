/**
 * OCR Status Polling
 * Polls for OCR status updates on documents that are processing
 */

const OCRStatusPoller = {
  pollInterval: 5000, // 5 seconds
  activePolls: new Map(),

  startPolling(documentId) {
    if (this.activePolls.has(documentId)) return;

    const poll = setInterval(() => {
      this.checkStatus(documentId);
    }, this.pollInterval);

    this.activePolls.set(documentId, poll);
  },

  stopPolling(documentId) {
    const poll = this.activePolls.get(documentId);
    if (poll) {
      clearInterval(poll);
      this.activePolls.delete(documentId);
    }
  },

  async checkStatus(documentId) {
    try {
      const response = await fetch(`/documents/ocr-status/${documentId}/`);
      const data = await response.json();

      if (data.status === "completed" || data.status === "failed") {
        this.stopPolling(documentId);
        // Trigger refresh of the documents list
        document.body.dispatchEvent(new CustomEvent("documentsChanged"));
      }
    } catch (error) {
      console.error("Error checking OCR status:", error);
    }
  },

  // Check all visible documents for processing status
  checkVisibleDocuments() {
    const processingBadges = document.querySelectorAll(
      ".ocr-status .badge.bg-info"
    );
    processingBadges.forEach((badge) => {
      const row = badge.closest("tr");
      const documentId = row ? row.dataset.documentId : null;
      if (documentId) {
        this.startPolling(parseInt(documentId));
      }
    });
  },

  // Stop all active polls
  stopAll() {
    this.activePolls.forEach((poll, documentId) => {
      clearInterval(poll);
    });
    this.activePolls.clear();
  },
};

// Initialize on page load and after HTMX swaps
function initOCRPoller() {
  OCRStatusPoller.checkVisibleDocuments();
}

document.addEventListener("DOMContentLoaded", initOCRPoller);
document.body.addEventListener("htmx:afterSwap", initOCRPoller);
document.body.addEventListener("htmx:afterSettle", initOCRPoller);
