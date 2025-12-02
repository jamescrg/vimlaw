/**
 * File Upload Form Handler
 *
 * Handles forms with file uploads intelligently:
 * - Uses HTMX for validation when no file is selected
 * - Uses regular form submission when files are present
 * - Supports dropzone for modern file uploads
 */

let documentDropzone = null;
let preservedDropzoneFiles = [];

const initializeDocumentDropzone = () => {
  const dropzoneElement = document.querySelector("#document-dropzone");
  const form = document.querySelector("#file-form");

  if (dropzoneElement && form) {
    // Preserve files from existing dropzone before destroying
    if (documentDropzone && documentDropzone.files) {
      preservedDropzoneFiles = documentDropzone.files.filter(
        (file) => !file.isExistingFile,
      );
    }

    // Clean up any existing dropzone instance
    if (documentDropzone) {
      documentDropzone.destroy();
      documentDropzone = null;
    }

    Dropzone.autoDiscover = false;

    // Remove any existing HTMX attributes to prevent conflicts
    form.removeAttribute("hx-post");
    form.removeAttribute("hx-target");

    documentDropzone = new Dropzone("#document-dropzone", {
      url: "#",
      autoProcessQueue: false,
      uploadMultiple: false,
      maxFiles: 1,
      addRemoveLinks: false,
      dictDefaultMessage: "Drop file here or click to upload",
      dictRemoveFile: '<i class="bi bi-trash"></i>',
      acceptedFiles: ".pdf,.doc,.docx,.txt,.jpg,.jpeg,.png",
      previewTemplate: `
        <div class="dz-preview dz-file-preview">
          <div class="dz-filename-wrapper">
            <span class="dz-filename" data-dz-name></span>
            <span class="dz-size" data-dz-size></span>
          </div>
          <a class="dz-remove" href="javascript:undefined;" data-dz-remove>
            <i class="bi bi-trash"></i>
          </a>
        </div>
      `,

      init: function () {
        const existingFile = dropzoneElement.dataset.existingFile;
        const existingSize = dropzoneElement.dataset.existingSize;

        if (existingFile) {
          const filename = existingFile.split("/").pop() || existingFile;

          const mockFile = {
            name: filename,
            size: parseInt(existingSize) || 0,
            accepted: true,
            status: Dropzone.SUCCESS,
            isExistingFile: true,
          };

          this.files.push(mockFile);
          this.emit("addedfile", mockFile);
          this.emit("complete", mockFile);

          const preview = mockFile.previewElement;
          if (preview) {
            const filenameSpan = preview.querySelector(".dz-filename span");

            if (filenameSpan) {
              filenameSpan.textContent = mockFile.name + " (current file)";
            }

            preview.classList.add("dz-success", "clickable-preview");

            const documentId = form.action.split("/").slice(-2, -1)[0]; // Extract ID from URL
            const downloadUrl = `/files/download/${documentId}/`;

            preview.style.cursor = "pointer";
            preview.title = "Click to download and view current file";

            preview.addEventListener("click", (e) => {
              // Don't trigger download if clicking the remove button
              if (!e.target.closest(".dz-remove")) {
                window.open(downloadUrl, "_blank");
              }
            });
          }
        }

        // Restore preserved files from previous dropzone instance
        if (preservedDropzoneFiles.length > 0) {
          preservedDropzoneFiles.forEach((file) => {
            this.addFile(file);
          });
          preservedDropzoneFiles = []; // Clear after restoring
        }

        // Ensure only one file
        this.on("addedfile", (file) => {
          if (this.files.length > 1) {
            // Remove the oldest file (keep the newest)
            this.removeFile(this.files[0]);
          }
        });

        form.addEventListener("submit", (e) => {
          e.preventDefault();
          e.stopPropagation();

          const submitButton = form.querySelector('button[type="submit"]');
          const originalText = submitButton.innerHTML;

          const formData = new FormData(form);

          // Add file from dropzone to form
          const allFiles = this.files || [];
          const realFiles = allFiles.filter(file => !file.isExistingFile && file instanceof File);
          const hasNewFile = realFiles.length > 0;
          if (hasNewFile) {
            const file = realFiles[0];
            formData.append("file", file);
          }

          // Loading state - show "Uploading..." only if there's a new file
          submitButton.disabled = true;
          submitButton.innerHTML = hasNewFile
            ? '<i class="bi bi-arrow-repeat spin"></i> Uploading...'
            : '<i class="bi bi-arrow-repeat spin"></i> Saving...';

          fetch(form.action, {
            method: "POST",
            body: formData,
          })
            .then((response) => {
              if (response.redirected) {
                // Success - redirect to new URL -- Normal form submission
                preservedDropzoneFiles = []; // Clear preserved files on success
                window.location.href = response.url;
              } else if (response.status === 204) {
                // Close modal and refresh -- HTMX
                preservedDropzoneFiles = []; // Clear preserved files on success
                const modalElement = document.querySelector(
                  "#htmx-modal-container",
                );

                if (modalElement) {
                  const modal =
                    bootstrap.Modal.getInstance(modalElement) ||
                    new bootstrap.Modal(modalElement);

                  modal.hide();
                }

                document.body.dispatchEvent(
                  new CustomEvent("filesChanged"),
                );
              } else {
                // Form validation errors - update content
                return response.text().then((html) => {
                  // Preserve files in the dropzone
                  const preservedFiles = this.files ? [...this.files] : [];

                  document.querySelector("#htmx-modal-container").innerHTML =
                    html;

                  documentDropzone = null;
                  initializeFileUploadForms();

                  // Re-add the preserved files to the dropzone
                  if (preservedFiles.length > 0 && documentDropzone) {
                    preservedFiles.forEach((file) => {
                      if (!file.isExistingFile) {
                        documentDropzone.addFile(file);
                      }
                    });
                  }
                });
              }
            })
            .catch((error) => {
              console.error("Error:", error);
            })
            .finally(() => {
              // Reset dropzone and button loading state
              if (submitButton) {
                submitButton.disabled = false;
                submitButton.innerHTML = originalText;
              }
            });
        });
      },
    });
  }
};

const initializeFileUploadForms = () => {
  // Initialize dropzone for documents
  initializeDocumentDropzone();

  const formsWithFileInputs = document.querySelectorAll(
    'form input[type="file"]',
  );

  formsWithFileInputs.forEach((fileInput) => {
    const form = fileInput.closest("form");

    if (form && !form.dataset.fileUploadInitialized) {
      form.dataset.fileUploadInitialized = "true";

      form.addEventListener("submit", (e) => {
        const hasFile = fileInput.files && fileInput.files.length > 0;

        if (!hasFile) {
          // No file selected, use HTMX for validation
          e.preventDefault();

          const target =
            form.getAttribute("hx-target") ||
            form.getAttribute("data-hx-target") ||
            "#htmx-modal-container";

          // Preserve value from the form
          const formData = new FormData(form);

          fetch(form.action, {
            method: "POST",
            body: formData,
            headers: {
              "X-Requested-With": "XMLHttpRequest",
              "HX-Request": "true",
            },
          })
            .then((response) => response.text())
            .then((html) => {
              document.querySelector(target).innerHTML = html;
              initializeFileUploadForms();
            })
            .catch((error) => console.error("Error:", error));
        } else {
          // File is present, remove HTMX attributes
          form.removeAttribute("hx-post");
          form.removeAttribute("hx-target");
        }
      });
    }
  });
};

// Initialize on DOM load
document.addEventListener("DOMContentLoaded", initializeFileUploadForms);

// Also initialize when HTMX loads new content
document.body.addEventListener("htmx:afterSwap", () => {
  initializeFileUploadForms();
});

// Clear preserved files when modal is closed/hidden
document.body.addEventListener("hidden.bs.modal", () => {
  documentDropzone = null;
  preservedDropzoneFiles = [];
});
