'use strict';

fetch(CONFIG.urls.dashboardStats)
  .then(r => r.json())
  .then(data => {
    document.getElementById('stat-total').textContent = data.total_records.toLocaleString('fr-FR');
    document.getElementById('chart-label').textContent = data.total_records.toLocaleString('fr-FR') + ' enregistrements (1970→)';
    new Chart(document.getElementById('chart-years'), {
      type: 'bar',
      data: {
        labels: data.years,
        datasets: [{ label: 'Décès', data: data.counts,
          backgroundColor: 'rgba(99,102,241,0.55)', borderColor: 'rgba(99,102,241,0.9)',
          borderWidth: 1, borderRadius: 2 }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: {
          backgroundColor: '#27272a', borderColor: '#3f3f46', borderWidth: 1,
          titleColor: '#fafafa', bodyColor: '#a1a1aa',
          callbacks: { label: c => '  ' + c.raw.toLocaleString('fr-FR') + ' décès' }
        }},
        scales: {
          x: { grid: { color: 'rgba(255,255,255,.04)' }, ticks: { color: '#71717a', font: { size: 11 }, maxTicksLimit: 20 } },
          y: { grid: { color: 'rgba(255,255,255,.04)' }, ticks: { color: '#71717a', font: { size: 11 }, callback: v => v >= 1000 ? (v/1000).toFixed(0)+'k' : v } }
        }
      }
    });
  })
  .catch(() => { document.getElementById('chart-label').textContent = 'Erreur de chargement'; });
