(() => {
  'use strict';
  const button = document.querySelector('[data-action="refresh"]');
  if (!button) return;
  button.addEventListener('click', () => {
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    button.textContent = 'Actualizando…';
    window.location.reload();
  });
})();
