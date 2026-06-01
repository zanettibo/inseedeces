'use strict';

const NLP_FILTER_KEYS = ['nom','prenoms','sexe','nom_flexible','prenoms_flexible',
  'date_naissance_debut','date_naissance_fin','date_deces_debut','date_deces_fin',
  'lieu_naissance','lieu_naissance_type','lieu_deces','lieu_deces_type'];

(function() {
  const urlParams = new URLSearchParams(window.location.search);
  const activeFilters = NLP_FILTER_KEYS.filter(k => urlParams.get(k));
  if (activeFilters.length > 0) {
    document.getElementById('nlp-input').placeholder = 'Affiner la recherche… ex : "il est mort en 2005"';
    document.getElementById('nlp-hint').innerHTML =
      '<i class="bi bi-funnel-fill me-1" style="color:#a5b4fc;"></i>' +
      '<strong style="color:var(--t2);">' + activeFilters.length + ' filtre' + (activeFilters.length > 1 ? 's' : '') + ' actif' + (activeFilters.length > 1 ? 's' : '') + '</strong>' +
      ' — l\'IA complète les critères existants. ' +
      '<a href="' + CONFIG.urls.search + '" style="color:#a5b4fc;">Réinitialiser</a> pour repartir de zéro.';
  }
})();

document.getElementById('nlp-form').addEventListener('submit', function() {
  const urlParams = new URLSearchParams(window.location.search);
  NLP_FILTER_KEYS.forEach(function(key) {
    const val = urlParams.get(key);
    if (val) {
      const inp = document.createElement('input');
      inp.type = 'hidden';
      inp.name = 'current_' + key;
      inp.value = val;
      document.getElementById('nlp-form').appendChild(inp);
    }
  });
  const btn = document.getElementById('nlp-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Analyse…';
});

function setupFlexibleInput(inputId, flexId) {
  const inp = document.getElementById(inputId);
  const chk = document.getElementById(flexId);
  function sync() { if (!chk.checked && inp.value) inp.value = inp.value.toUpperCase(); }
  inp.addEventListener('input', sync);
  chk.addEventListener('change', sync);
}

document.addEventListener('DOMContentLoaded', function() {
  setupFlexibleInput('nom', 'nom_flexible');
  setupFlexibleInput('prenoms', 'prenoms_flexible');

  function initLieu(selId, typeId) {
    var $s = $('#' + selId);
    $s.select2({
      theme: 'bootstrap-5', placeholder: 'Rechercher un lieu…', allowClear: true,
      minimumInputLength: 2, width: '100%', dropdownParent: $('body'),
      language: { inputTooShort: () => 'Au moins 2 caractères', noResults: () => 'Aucun résultat',
                  searching: () => 'Recherche…', loadingMore: () => 'Chargement…' },
      ajax: {
        url: CONFIG.urls.autocompleteLieu, dataType: 'json', delay: 250,
        data: p => ({ q: p.term, page: p.page }),
        processResults: d => ({ results: d.results, pagination: d.pagination }),
        cache: true
      }
    }).on('select2:select', e => $('#' + typeId).val(e.params.data.type))
      .on('select2:clear',  () => $('#' + typeId).val(''));
  }

  initLieu('lieu_naissance', 'lieu_naissance_type');
  initLieu('lieu_deces', 'lieu_deces_type');

  if (CONFIG.lieuNaissance.value && CONFIG.lieuNaissance.text) {
    $('#lieu_naissance').append(new Option(CONFIG.lieuNaissance.text, CONFIG.lieuNaissance.value, true, true)).trigger('change');
  }
  if (CONFIG.lieuDeces.value && CONFIG.lieuDeces.text) {
    $('#lieu_deces').append(new Option(CONFIG.lieuDeces.text, CONFIG.lieuDeces.value, true, true)).trigger('change');
  }
});
