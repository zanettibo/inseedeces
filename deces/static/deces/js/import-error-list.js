'use strict';

const chks = () => document.querySelectorAll('.err-chk');
const btnRes   = document.getElementById('btn-res');
const btnRetry = document.getElementById('btn-retry');
const selCount = document.getElementById('sel-count');

function sync() {
  const n = [...chks()].filter(c => c.checked).length;
  selCount.textContent = `${n} sélectionné(s)`;
  btnRes.disabled = btnRetry.disabled = n === 0;
}

document.getElementById('chk-all').addEventListener('change', function() {
  chks().forEach(c => c.checked = this.checked); sync();
});
document.getElementById('btn-all').addEventListener('click', () => {
  chks().forEach(c => c.checked = true);
  document.getElementById('chk-all').checked = true; sync();
});
chks().forEach(c => c.addEventListener('change', sync));
