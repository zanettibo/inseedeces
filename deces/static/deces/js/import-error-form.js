'use strict';

document.addEventListener('DOMContentLoaded', function() {
  document.querySelectorAll('form input:not([type=hidden]):not([type=submit]), form select, form textarea').forEach(el => {
    el.classList.add('form-control');
  });
});
