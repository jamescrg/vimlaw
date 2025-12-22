//
// utility functions to show and hide elements
//

function show(elementId) {
  const item = document.getElementById(elementId);
  item.style.display = "block";
}

function hide(elementId) {
  const item = document.getElementById(elementId);
  item.style.display = "none";
}

function confirmProceed() {
  const check = confirm("Are you sure you want to delete this record?");
  if (check) {
    return;
  } else {
    event.stopPropagation();
    event.preventDefault();
  }
}

const confirmLinks = document.querySelectorAll(".confirm");
if (confirmLinks) {
  for (const link of confirmLinks) {
    link.addEventListener("click", confirmProceed);
  }
}

// Modal handling is now in alpine-components.js

// Copy link buttons (delegated for HTMX compatibility)
document.addEventListener('click', function(e) {
  const copyBtn = e.target.closest('.copy-btn');
  const highlightCopyBtn = e.target.closest('.highlight-copy-btn');
  const highlightLinkBtn = e.target.closest('.highlight-link-btn');
  const documentLinkBtn = e.target.closest('.document-link-btn');
  const sourceCopyBtn = e.target.closest('.source-copy-btn');

  if (copyBtn) {
    e.preventDefault();
    let data = copyBtn.getAttribute('data-copy');

    // If data-copy-target is specified, get text from target element
    const targetSelector = copyBtn.getAttribute('data-copy-target');
    if (targetSelector) {
      const targetElement = document.querySelector(targetSelector);
      if (targetElement) {
        data = targetElement.textContent.trim();
      }
    }

    copyToClipboard(copyBtn, data);
  } else if (highlightCopyBtn) {
    const data = highlightCopyBtn.getAttribute('data-copy');
    copyToClipboard(highlightCopyBtn, data);
  } else if (highlightLinkBtn) {
    const url = highlightLinkBtn.getAttribute('data-url');
    const fullUrl = window.location.origin + url;
    copyToClipboard(highlightLinkBtn, fullUrl);
  } else if (documentLinkBtn) {
    const url = documentLinkBtn.getAttribute('data-url');
    const fullUrl = window.location.origin + url;
    copyToClipboard(documentLinkBtn, fullUrl);
  } else if (sourceCopyBtn) {
    e.preventDefault();
    const data = sourceCopyBtn.getAttribute('data-copy');
    copyToClipboard(sourceCopyBtn, data);
  }
});

function copyToClipboard(button, data) {
  navigator.clipboard.writeText(data).then(() => {
    const originalHtml = button.innerHTML;
    button.innerHTML = '<i class="icon-check"></i>';
    button.style.color = 'green';
    setTimeout(() => {
      button.innerHTML = originalHtml;
      button.style.color = '';
    }, 2000);
  }).catch(err => {
    console.error('Failed to copy value: ', err);
  });
}

// Copy value logic
document.addEventListener('DOMContentLoaded', function() {
  const copyButtons = document.querySelectorAll('.copy-btn');

  copyButtons.forEach(button => {
    button.addEventListener('click', function() {
      let data = this.getAttribute('data-copy');

      // If data-copy-target is specified, get text from target element
      const targetSelector = this.getAttribute('data-copy-target');
      if (targetSelector) {
        const targetElement = document.querySelector(targetSelector);
        if (targetElement) {
          data = targetElement.textContent.trim();
        }
      }

      navigator.clipboard.writeText(data).then(() => {
        const originalHtml = this.innerHTML;

        this.innerHTML = '<i class="icon-check"></i>';
        this.style.color = 'green';

        setTimeout(() => {
          this.innerHTML = originalHtml;
          this.style.color = '';
        }, 2000);
      }).catch(err => {
        console.error('Failed to copy value: ', err);
      });
    });
  });
});
