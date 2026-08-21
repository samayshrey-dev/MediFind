/**
 * ScrollStack — Interactive Sticky Stacking Cards (React Bits Vanilla Port)
 * Calculates stack indices and applies progressive scroll stacking.
 */
(function () {
  'use strict';

  function initScrollStack() {
    const containers = document.querySelectorAll('.scroll-stack-container');
    containers.forEach(container => {
      const items = container.querySelectorAll('.scroll-stack-item');
      items.forEach((item, index) => {
        item.style.setProperty('--stack-index', index);
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initScrollStack);
  } else {
    initScrollStack();
  }
})();
