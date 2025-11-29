/**
 * PDF Document Viewer with Highlighting
 * Uses PDF.js for rendering with official viewer CSS
 */

console.log("documents-viewer.js loading...");

// Import PDF.js
let pdfjsLib;
try {
  pdfjsLib = await import(
    "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.min.mjs"
  );
  console.log("PDF.js loaded successfully");
} catch (e) {
  console.error("Failed to load PDF.js:", e);
}

// Set worker
pdfjsLib.GlobalWorkerOptions.workerSrc =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.worker.min.mjs";

class DocumentViewer {
  constructor(config) {
    this.documentId = config.documentId;
    this.documentUrl = config.documentUrl;
    this.csrfToken = config.csrfToken;
    this.highlights = config.existingHighlights || [];
    this.initialPage = config.initialPage || 1;
    this.initialHighlight = config.initialHighlight;

    this.container = document.getElementById("viewer");
    this.pdf = null;
    this.currentPage = 1;
    this.totalPages = 0;
    this.scale = 1.5;
    this.currentSelection = null;
    this.highlightsVisible = true;
    this.pageContainers = [];
    this.pageViewports = [];

    this.init();
  }

  async init() {
    try {
      console.log("Loading PDF from:", this.documentUrl);
      console.log("TextLayer available:", !!pdfjsLib.TextLayer);

      // Load PDF
      this.pdf = await pdfjsLib.getDocument(this.documentUrl).promise;
      console.log("PDF loaded, pages:", this.pdf.numPages);
      this.totalPages = this.pdf.numPages;
      document.getElementById("total-pages").textContent = this.totalPages;
      document.getElementById("page-input").max = this.totalPages;

      // Clear loading indicator
      this.container.innerHTML = "";

      // Render all pages
      await this.renderAllPages();

      this.setupEventListeners();

      // Navigate to initial page or highlight
      if (this.initialHighlight) {
        const highlight = this.highlights.find(
          (h) => h.id === this.initialHighlight
        );
        if (highlight) {
          this.scrollToPage(highlight.page_number);
          this.highlightItem(this.initialHighlight);
        }
      } else if (this.initialPage > 1) {
        this.scrollToPage(this.initialPage);
      }
    } catch (error) {
      console.error("Error loading PDF:", error);
      this.container.innerHTML =
        '<div id="loading-indicator" style="color: red;">Error loading PDF. Please try downloading the file.</div>';
    }
  }

  async renderAllPages() {
    for (let pageNum = 1; pageNum <= this.totalPages; pageNum++) {
      const pageContainer = await this.renderPage(pageNum);
      this.pageContainers.push(pageContainer);
      this.container.appendChild(pageContainer);
    }
  }

  async renderPage(pageNum) {
    const page = await this.pdf.getPage(pageNum);
    const viewport = page.getViewport({ scale: this.scale });
    this.pageViewports[pageNum] = viewport;

    // Create page container
    const pageContainer = document.createElement("div");
    pageContainer.className = "pdf-page-container";
    pageContainer.dataset.pageNumber = pageNum;
    pageContainer.style.position = "relative";
    pageContainer.style.width = `${viewport.width}px`;
    pageContainer.style.height = `${viewport.height}px`;
    pageContainer.style.marginBottom = "20px";

    // Create canvas
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d");
    canvas.height = viewport.height;
    canvas.width = viewport.width;
    canvas.className = "pdf-page";

    pageContainer.appendChild(canvas);

    // Create text layer for selection (use class name expected by pdf_viewer.css)
    const textLayerDiv = document.createElement("div");
    textLayerDiv.className = "textLayer";
    pageContainer.appendChild(textLayerDiv);

    // Create highlight layer
    const highlightLayer = document.createElement("div");
    highlightLayer.className = "highlight-layer";
    highlightLayer.style.position = "absolute";
    highlightLayer.style.left = "0";
    highlightLayer.style.top = "0";
    highlightLayer.style.right = "0";
    highlightLayer.style.bottom = "0";
    highlightLayer.style.pointerEvents = "none";
    pageContainer.appendChild(highlightLayer);

    // Render PDF page
    await page.render({
      canvasContext: context,
      viewport: viewport,
    }).promise;

    // Render text layer using PDF.js textContent
    const textContent = await page.getTextContent();
    await this.renderTextLayer(textContent, textLayerDiv, viewport);

    // Render highlights for this page
    this.renderHighlightsForPage(pageNum, highlightLayer, viewport);

    return pageContainer;
  }

  async renderTextLayer(textContent, container, viewport) {
    // Use PDF.js TextLayer with official viewer CSS
    try {
      if (pdfjsLib.TextLayer) {
        console.log("Using PDF.js TextLayer");
        const textLayer = new pdfjsLib.TextLayer({
          textContentSource: textContent,
          container: container,
          viewport: viewport,
        });
        await textLayer.render();
      } else {
        console.log("TextLayer not available, using fallback");
        // Fallback: render text spans manually
        for (const item of textContent.items) {
          if (!item.str) continue;

          const span = document.createElement("span");
          span.textContent = item.str;

          // Position using viewport transform
          const tx = pdfjsLib.Util.transform(viewport.transform, item.transform);
          const fontHeight = Math.hypot(tx[2], tx[3]);

          span.style.left = `${tx[4]}px`;
          span.style.top = `${tx[5] - fontHeight}px`;
          span.style.fontSize = `${fontHeight}px`;
          span.style.fontFamily = "sans-serif";
          span.style.position = "absolute";
          span.style.color = "transparent";
          span.style.whiteSpace = "pre";

          container.appendChild(span);
        }
      }
    } catch (e) {
      console.error("Text layer render error:", e);
    }
  }

  renderHighlightsForPage(pageNum, highlightLayer, viewport) {
    if (!this.highlightsVisible) return;

    const pageHighlights = this.highlights.filter(
      (h) => h.page_number === pageNum
    );

    pageHighlights.forEach((highlight) => {
      this.renderHighlightOverlay(highlight, highlightLayer);
    });
  }

  renderHighlightOverlay(highlight, highlightLayer) {
    const coords = highlight.coordinates;
    if (coords && coords.rects) {
      coords.rects.forEach((rect) => {
        const div = document.createElement("div");
        div.className = "highlight-overlay";
        div.style.position = "absolute";
        div.style.backgroundColor = highlight.color;
        div.style.opacity = "0.4";
        div.style.left = `${rect.left}px`;
        div.style.top = `${rect.top}px`;
        div.style.width = `${rect.width}px`;
        div.style.height = `${rect.height}px`;
        div.style.pointerEvents = "auto";
        div.style.cursor = "pointer";
        div.style.borderRadius = "2px";
        div.dataset.highlightId = highlight.id;
        div.title = highlight.title;

        div.addEventListener("click", () => {
          this.highlightItem(highlight.id);
        });

        highlightLayer.appendChild(div);
      });
    }
  }

  setupEventListeners() {
    // Page navigation
    document.getElementById("prev-page").addEventListener("click", () => {
      if (this.currentPage > 1) {
        this.scrollToPage(this.currentPage - 1);
      }
    });

    document.getElementById("next-page").addEventListener("click", () => {
      if (this.currentPage < this.totalPages) {
        this.scrollToPage(this.currentPage + 1);
      }
    });

    document.getElementById("page-input").addEventListener("change", (e) => {
      const page = parseInt(e.target.value);
      if (page >= 1 && page <= this.totalPages) {
        this.scrollToPage(page);
      }
    });

    // Track current page on scroll
    document.getElementById("pdf-container").addEventListener("scroll", () => {
      this.updateCurrentPage();
    });

    // Zoom controls
    document.getElementById("zoom-in").addEventListener("click", () => {
      this.scale = Math.min(this.scale + 0.25, 3.0);
      this.updateZoom();
    });

    document.getElementById("zoom-out").addEventListener("click", () => {
      this.scale = Math.max(this.scale - 0.25, 0.5);
      this.updateZoom();
    });

    // Text selection for highlighting
    document.addEventListener("mouseup", (e) => {
      // Only handle selection within the viewer
      if (!this.container.contains(e.target)) return;

      const selection = window.getSelection();
      if (selection.toString().trim()) {
        this.handleTextSelection(selection);
      } else {
        this.currentSelection = null;
        document.getElementById("create-highlight").disabled = true;
      }
    });

    // Toggle highlights visibility
    document.getElementById("toggle-highlights").addEventListener("click", (e) => {
      this.highlightsVisible = !this.highlightsVisible;
      e.currentTarget.classList.toggle("active");
      document.querySelectorAll(".highlight-overlay").forEach((el) => {
        el.style.display = this.highlightsVisible ? "block" : "none";
      });
    });

    // Create highlight button
    document.getElementById("create-highlight").addEventListener("click", () => {
      if (this.currentSelection) {
        this.showHighlightModal();
      }
    });

    // Save highlight
    document.getElementById("save-highlight").addEventListener("click", () => {
      this.saveHighlight();
    });

    // Highlight sidebar navigation
    document.getElementById("highlights-list").addEventListener("click", (e) => {
      const item = e.target.closest(".highlight-item");
      if (item && !e.target.closest(".delete-highlight")) {
        const page = parseInt(item.dataset.page);
        const highlightId = parseInt(item.dataset.highlightId);
        this.scrollToPage(page);
        this.highlightItem(highlightId);
      }

      // Handle delete
      const deleteBtn = e.target.closest(".delete-highlight");
      if (deleteBtn) {
        const highlightId = parseInt(deleteBtn.dataset.highlightId);
        this.deleteHighlight(highlightId);
      }
    });

    // Keyboard navigation
    document.addEventListener("keydown", (e) => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA")
        return;

      if (e.key === "ArrowLeft" || e.key === "PageUp") {
        if (this.currentPage > 1) {
          this.scrollToPage(this.currentPage - 1);
        }
      } else if (e.key === "ArrowRight" || e.key === "PageDown") {
        if (this.currentPage < this.totalPages) {
          this.scrollToPage(this.currentPage + 1);
        }
      }
    });
  }

  scrollToPage(pageNum) {
    const container = document.getElementById("pdf-container");
    const pageContainer = this.pageContainers[pageNum - 1];
    if (pageContainer) {
      container.scrollTo({
        top: pageContainer.offsetTop - 20,
        behavior: "smooth",
      });
      this.currentPage = pageNum;
      document.getElementById("page-input").value = pageNum;
    }
  }

  updateCurrentPage() {
    const container = document.getElementById("pdf-container");
    const scrollTop = container.scrollTop;

    for (let i = 0; i < this.pageContainers.length; i++) {
      const pageContainer = this.pageContainers[i];
      if (
        pageContainer.offsetTop <= scrollTop + 100 &&
        pageContainer.offsetTop + pageContainer.offsetHeight > scrollTop + 100
      ) {
        this.currentPage = i + 1;
        document.getElementById("page-input").value = this.currentPage;
        break;
      }
    }
  }

  async updateZoom() {
    document.getElementById("zoom-level").textContent = `${Math.round(this.scale * 100)}%`;

    // Re-render all pages with new scale
    this.container.innerHTML =
      '<div id="loading-indicator"><i class="bi bi-arrow-repeat spin"></i> Updating zoom...</div>';
    this.pageContainers = [];
    this.pageViewports = [];

    await this.renderAllPages();

    // Restore scroll position
    this.scrollToPage(this.currentPage);
  }

  handleTextSelection(selection) {
    const text = selection.toString().trim();
    if (!text) return;

    // Find which page the selection is on
    const anchorNode = selection.anchorNode;
    const pageContainer = anchorNode.parentElement?.closest(".pdf-page-container");
    if (!pageContainer) return;

    const pageNum = parseInt(pageContainer.dataset.pageNumber);
    const pageRect = pageContainer.getBoundingClientRect();

    // Get selection rects relative to the page container
    const range = selection.getRangeAt(0);
    const rects = range.getClientRects();

    const selectionRects = [];
    for (let i = 0; i < rects.length; i++) {
      const rect = rects[i];
      // Filter out tiny rects
      if (rect.width < 2 || rect.height < 5) continue;

      selectionRects.push({
        left: rect.left - pageRect.left,
        top: rect.top - pageRect.top,
        width: rect.width,
        height: rect.height,
      });
    }

    if (selectionRects.length === 0) return;

    this.currentSelection = {
      text: text,
      page: pageNum,
      rects: selectionRects,
    };

    document.getElementById("create-highlight").disabled = false;
  }

  showHighlightModal() {
    if (!this.currentSelection) return;

    document.getElementById("highlight-page").value = this.currentSelection.page;
    document.getElementById("highlight-coords").value = JSON.stringify({
      rects: this.currentSelection.rects,
    });
    document.getElementById("highlight-text").value = this.currentSelection.text;
    document.getElementById("selected-text-preview").textContent =
      this.currentSelection.text.substring(0, 500) +
      (this.currentSelection.text.length > 500 ? "..." : "");

    // Clear title field
    document.getElementById("highlight-title").value = "";

    const modal = new bootstrap.Modal(
      document.getElementById("highlight-modal")
    );
    modal.show();
  }

  async saveHighlight() {
    const form = document.getElementById("highlight-form");
    const formData = new FormData(form);

    try {
      const response = await fetch(
        `/documents/${this.documentId}/highlights/add/`,
        {
          method: "POST",
          body: formData,
          headers: {
            "X-CSRFToken": this.csrfToken,
          },
        }
      );

      if (response.ok) {
        const highlight = await response.json();
        this.highlights.push(highlight);

        // Close modal
        bootstrap.Modal.getInstance(
          document.getElementById("highlight-modal")
        ).hide();

        // Reset form
        form.reset();
        this.currentSelection = null;
        document.getElementById("create-highlight").disabled = true;

        // Clear selection
        window.getSelection().removeAllRanges();

        // Add highlight to the page
        const pageContainer = this.pageContainers[highlight.page_number - 1];
        if (pageContainer) {
          const highlightLayer = pageContainer.querySelector(".highlight-layer");
          this.renderHighlightOverlay(highlight, highlightLayer);
        }

        // Update sidebar
        this.updateHighlightsSidebar(highlight);
      } else {
        const error = await response.json();
        alert("Error saving highlight: " + (error.error || "Unknown error"));
      }
    } catch (error) {
      console.error("Error saving highlight:", error);
      alert("Error saving highlight");
    }
  }

  updateHighlightsSidebar(highlight) {
    const list = document.getElementById("highlights-list");
    const noHighlights = list.querySelector(".no-highlights");
    if (noHighlights) noHighlights.remove();

    const item = document.createElement("div");
    item.className = "highlight-item";
    item.dataset.highlightId = highlight.id;
    item.dataset.page = highlight.page_number;
    item.style.borderLeft = `4px solid ${highlight.color}`;
    item.innerHTML = `
      <div class="highlight-title">${this.escapeHtml(highlight.title)}</div>
      <div class="highlight-meta">Page ${highlight.page_number}</div>
      <div class="highlight-text">${this.escapeHtml(highlight.text.substring(0, 100))}${highlight.text.length > 100 ? "..." : ""}</div>
      <div class="highlight-actions">
        <button class="btn btn-sm btn-link delete-highlight" data-highlight-id="${highlight.id}" title="Delete">
          <i class="bi bi-trash"></i>
        </button>
      </div>
    `;
    list.appendChild(item);
  }

  highlightItem(highlightId) {
    // Remove active class from all items
    document.querySelectorAll(".highlight-item").forEach((el) => {
      el.classList.remove("active");
    });

    // Add active class to selected item
    const item = document.querySelector(
      `.highlight-item[data-highlight-id="${highlightId}"]`
    );
    if (item) {
      item.classList.add("active");
      item.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  async deleteHighlight(highlightId) {
    if (!confirm("Are you sure you want to delete this highlight?")) return;

    try {
      const response = await fetch(`/documents/highlights/${highlightId}/delete/`, {
        method: "POST",
        headers: {
          "X-CSRFToken": this.csrfToken,
        },
      });

      if (response.ok) {
        // Remove from highlights array
        this.highlights = this.highlights.filter((h) => h.id !== highlightId);

        // Remove overlay from page
        document.querySelectorAll(`.highlight-overlay[data-highlight-id="${highlightId}"]`).forEach((el) => {
          el.remove();
        });

        // Remove from sidebar
        const item = document.querySelector(`.highlight-item[data-highlight-id="${highlightId}"]`);
        if (item) item.remove();

        // Show "no highlights" message if empty
        if (this.highlights.length === 0) {
          document.getElementById("highlights-list").innerHTML =
            '<div class="no-highlights">No highlights yet. Select text in the PDF to create one.</div>';
        }
      } else {
        const error = await response.json();
        alert("Error deleting highlight: " + (error.error || "Unknown error"));
      }
    } catch (error) {
      console.error("Error deleting highlight:", error);
      alert("Error deleting highlight");
    }
  }

  escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }
}

// Initialize viewer (DOM is already ready since module loads after body)
if (window.viewerConfig) {
  console.log("Initializing DocumentViewer...");
  new DocumentViewer(window.viewerConfig);
} else {
  console.error("viewerConfig not found");
}
