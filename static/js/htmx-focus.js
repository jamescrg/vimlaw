(function() {
  let focusedInputId = null;

  document.body.addEventListener('htmx:beforeSwap', function(evt) {
    const activeElement = document.activeElement;
    if (activeElement && activeElement.tagName === 'INPUT' && activeElement.id) {
      const target = evt.detail.target;
      if (target.contains(activeElement)) {
        focusedInputId = activeElement.id;
      }
    }
  });

  document.body.addEventListener('htmx:afterSwap', function(evt) {
    if (focusedInputId) {
      const input = document.getElementById(focusedInputId);
      if (input) {
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
      }
      focusedInputId = null;
    }
  });
})();
