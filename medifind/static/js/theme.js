/**
 * MedFinder Theme Handler — Clean Healthcare Theme
 */
(function() {
  'use strict';
  try {
    localStorage.removeItem('medifind-theme');
    document.documentElement.removeAttribute('data-theme');
  } catch (e) {}
})();

