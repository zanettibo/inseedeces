'use strict';

const TERMINAL = new Set(['completed', 'failed']);
const streams = {};

function applyUpdate(id, data) {
  const row = document.querySelector(`tr[data-import-id="${id}"]`);
  if (!row) return;
  const badge = row.querySelector('.status-badge');
  badge.className = `status-badge badge ${
    data.status === 'completed' ? 'bg-success' :
    data.status === 'failed'    ? 'bg-danger'  :
    data.status === 'processing'? 'bg-primary' : 'bg-secondary'}`;
  badge.textContent = data.status_display;

  if (data.total_records > 0) {
    const pct = (data.records_processed / data.total_records) * 100;
    const bar = row.querySelector('.progress-bar');
    bar.style.width = `${pct}%`;
    bar.classList.toggle('progress-bar-animated', data.status === 'processing');
    bar.classList.toggle('progress-bar-striped', data.status === 'processing');
    const lbl = row.querySelector('.progress').nextElementSibling;
    if (lbl) lbl.textContent = `${Math.round(pct)}%`;
  }

  const errCell = row.querySelector('td:last-child');
  if (data.status === 'completed') {
    const cls = data.pending_errors === 0 ? 'bg-success' : 'bg-danger';
    errCell.innerHTML = `<span class="badge ${cls}">${data.pending_errors}</span>`;
  }
}

function refreshStats() {
  fetch(CONFIG.urls.importStats)
    .then(r => r.json())
    .then(d => {
      const el = document.getElementById('import-stats');
      if (el) el.innerHTML = `${d.total_records_processed} <span style="color:var(--t4);font-size:14px;font-weight:400;">/ ${d.total_records} enregistrements</span>`;
    });
}

function startStream(id) {
  if (streams[id]) return;
  const src = new EventSource(`/import/${id}/stream/`);
  streams[id] = src;
  src.onmessage = e => {
    const d = JSON.parse(e.data);
    if (d.error) { src.close(); delete streams[id]; return; }
    applyUpdate(id, d);
    if (TERMINAL.has(d.status)) { src.close(); delete streams[id]; refreshStats(); }
  };
  src.addEventListener('done', () => { src.close(); delete streams[id]; });
  src.onerror = () => { src.close(); delete streams[id]; };
}

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('tr[data-import-id]').forEach(row => {
    const b = row.querySelector('.status-badge');
    if (!b.classList.contains('bg-success') && !b.classList.contains('bg-danger'))
      startStream(row.dataset.importId);
  });
});

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function fmtSize(b) {
  if (!b) return '';
  return b > 1048576 ? `${(b/1048576).toFixed(1)} Mo` : `${(b/1024).toFixed(0)} Ko`;
}
function fmtDate(s) {
  if (!s) return '';
  return new Date(s).toLocaleDateString('fr-FR');
}

function importDatagouvFile(url, btn) {
  btn.disabled = true;
  btn.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>…';
  const form = new FormData();
  form.append('url', url);
  form.append('csrfmiddlewaretoken', document.querySelector('[name=csrfmiddlewaretoken]').value);
  fetch(CONFIG.urls.importData, {method: 'POST', body: form})
    .then(r => r.json())
    .then(d => {
      if (d.success) window.location.reload();
      else { btn.disabled = false; btn.innerHTML = '<i class="bi bi-cloud-arrow-down me-1"></i>Importer'; alert(d.error); }
    })
    .catch(() => { btn.disabled = false; btn.innerHTML = '<i class="bi bi-cloud-arrow-down me-1"></i>Importer'; });
}

fetch(CONFIG.urls.datagouvAvailableFiles)
  .then(r => r.json())
  .then(d => {
    document.getElementById('datagouv-loading').classList.add('d-none');
    if (d.error) {
      const el = document.getElementById('datagouv-error');
      el.textContent = d.error;
      el.classList.remove('d-none');
      return;
    }
    if (!d.files.length) {
      document.getElementById('datagouv-empty').classList.remove('d-none');
      return;
    }
    const list = document.getElementById('datagouv-list');
    d.files.forEach(f => {
      const div = document.createElement('div');
      div.className = 'd-flex align-items-center justify-content-between mb-2';
      div.style.gap = '8px';
      div.innerHTML = `
        <div>
          <div style="font-family:var(--fm);font-size:13px;color:var(--t1);">${esc(f.title)}</div>
          <div style="font-size:11px;color:var(--t3);">${fmtDate(f.created_at)} · ${fmtSize(f.filesize)}</div>
        </div>
        <button class="btn btn-sm btn-primary dg-import-btn" style="white-space:nowrap;">
          <i class="bi bi-cloud-arrow-down me-1"></i>Importer
        </button>`;
      div.querySelector('.dg-import-btn').addEventListener('click', function() {
        importDatagouvFile(f.url, this);
      });
      list.appendChild(div);
    });
  })
  .catch(() => {
    document.getElementById('datagouv-loading').classList.add('d-none');
    const el = document.getElementById('datagouv-error');
    el.textContent = 'Erreur de chargement';
    el.classList.remove('d-none');
  });

document.getElementById('import-form').addEventListener('submit', function(e) {
  e.preventDefault();
  const errDiv = document.getElementById('import-error');
  const btn = document.getElementById('submit-btn');
  errDiv.classList.add('d-none');
  btn.disabled = true;
  btn.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>En cours…';

  fetch(this.action, {
    method: 'POST', body: new FormData(this),
    headers: { 'X-CSRFToken': this.querySelector('[name=csrfmiddlewaretoken]').value }
  })
  .then(r => r.json())
  .then(d => {
    if (d.success) window.location.reload();
    else { errDiv.classList.remove('d-none'); document.getElementById('import-error-msg').textContent = d.error; }
  })
  .catch(err => { errDiv.classList.remove('d-none'); document.getElementById('import-error-msg').textContent = err.message; })
  .finally(() => { btn.disabled = false; btn.innerHTML = '<i class="bi bi-cloud-upload me-1"></i>Lancer l\'import'; });
});
