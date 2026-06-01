'use strict';

const tog = document.getElementById('mob-toggle');
const sb  = document.getElementById('sidebar');
if (tog) tog.addEventListener('click', () => sb.classList.toggle('open'));
document.addEventListener('click', e => {
  if (window.innerWidth < 769 && !sb.contains(e.target) && !tog.contains(e.target))
    sb.classList.remove('open');
});
