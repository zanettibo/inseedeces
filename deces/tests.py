from datetime import date
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from deces.models import Deces, Commune, Departement, Region, Pays, ImportHistory
from deces.tasks import parse_insee_date, parse_row, ParseError, _resolve_libelle
from deces.search_index import deces_to_doc

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_region(**kwargs):
    defaults = dict(reg='11', cheflieu='75056', tncc='0', ncc='ILE DE FRANCE',
                    nccenr='Île-de-France', libelle="Île-de-France")
    defaults.update(kwargs)
    return Region.objects.get_or_create(reg=defaults['reg'], defaults=defaults)[0]


def make_departement(region=None, **kwargs):
    if region is None:
        region = make_region()
    defaults = dict(dep='75', reg=region, cheflieu='75056', tncc='0',
                    ncc='PARIS', nccenr='Paris', libelle='Paris')
    defaults.update(kwargs)
    return Departement.objects.get_or_create(dep=defaults['dep'], defaults=defaults)[0]


def make_commune(departement=None, **kwargs):
    if departement is None:
        departement = make_departement()
    defaults = dict(com='75056', typecom='COM', reg=departement.reg, dep=departement,
                    ctcd='75', arr='751', tncc='0', ncc='PARIS',
                    nccenr='Paris', libelle='Paris', can='0000', comparent='')
    defaults.update(kwargs)
    return Commune.objects.get_or_create(com=defaults['com'], defaults=defaults)[0]


def make_pays(**kwargs):
    defaults = dict(cog='99109', actual='1', crpay='', ani='', libcog='ALLEMAGNE',
                    libenr='République fédérale d\'Allemagne',
                    codeiso2='DE', codeiso3='DEU', codenum3='276')
    defaults.update(kwargs)
    return Pays.objects.get_or_create(cog=defaults['cog'], defaults=defaults)[0]


def make_deces(**kwargs):
    defaults = dict(
        nom='DUPONT', prenoms='JEAN', sexe='1',
        date_naissance=date(1950, 1, 1), lieu_naissance='75056',
        lieu_naissance_nom='PARIS', lieu_naissance_libelle='Paris, Paris',
        date_deces=date(2020, 6, 15), lieu_deces='75056',
        lieu_deces_libelle='Paris, Paris', acte_deces='12345',
    )
    defaults.update(kwargs)
    return Deces.objects.create(**defaults)


# ---------------------------------------------------------------------------
# parse_insee_date
# ---------------------------------------------------------------------------

class ParseInseeDateTest(TestCase):

    def test_valid_date(self):
        self.assertEqual(parse_insee_date('19500115'), date(1950, 1, 15))

    def test_day_zero_becomes_one(self):
        self.assertEqual(parse_insee_date('19500100'), date(1950, 1, 1))

    def test_month_zero_becomes_one(self):
        self.assertEqual(parse_insee_date('19500001'), date(1950, 1, 1))

    def test_strips_quotes(self):
        self.assertEqual(parse_insee_date('"19500115"'), date(1950, 1, 15))

    def test_empty_string_returns_none(self):
        self.assertIsNone(parse_insee_date(''))

    def test_none_returns_none(self):
        self.assertIsNone(parse_insee_date(None))

    def test_zeroes_returns_none(self):
        self.assertIsNone(parse_insee_date('00000000'))

    def test_invalid_string_returns_none(self):
        self.assertIsNone(parse_insee_date('abcdefgh'))


# ---------------------------------------------------------------------------
# parse_row
# ---------------------------------------------------------------------------

def _row(nomprenom='DUPONT*JEAN', sexe='1', datenaiss='19500115',
         datedeces='20200615', lieunaiss='75056', commnaiss='PARIS',
         lieudeces='75056', actedeces='12345'):
    return {
        'nomprenom': nomprenom, 'sexe': sexe, 'datenaiss': datenaiss,
        'datedeces': datedeces, 'lieunaiss': lieunaiss, 'commnaiss': commnaiss,
        'lieudeces': lieudeces, 'actedeces': actedeces,
    }


class ParseRowTest(TestCase):

    def test_valid_row(self):
        result = parse_row(_row())
        self.assertEqual(result['nom'], 'DUPONT')
        self.assertEqual(result['prenoms'], 'JEAN')
        self.assertEqual(result['sexe'], '1')
        self.assertEqual(result['date_naissance'], date(1950, 1, 15))
        self.assertEqual(result['date_deces'], date(2020, 6, 15))
        self.assertEqual(result['lieu_naissance'], '75056')
        self.assertEqual(result['lieu_deces'], '75056')
        self.assertEqual(result['acte_deces'], '12345')

    def test_missing_star_raises(self):
        with self.assertRaises(ParseError):
            parse_row(_row(nomprenom='DUPONT JEAN'))

    def test_missing_star_no_error_returns_empty(self):
        result = parse_row(_row(nomprenom='DUPONT JEAN'), no_error=True)
        self.assertIsNone(result['nom'])

    def test_invalid_sexe_raises(self):
        with self.assertRaises(ParseError):
            parse_row(_row(sexe='X'))

    def test_invalid_sexe_no_error(self):
        result = parse_row(_row(sexe='X'), no_error=True)
        self.assertIsNone(result['sexe'])

    def test_zero_date_naissance(self):
        result = parse_row(_row(datenaiss='00000000'))
        self.assertIsNone(result['date_naissance'])

    def test_multiple_prenoms(self):
        result = parse_row(_row(nomprenom='DUPONT*JEAN PIERRE PAUL'))
        self.assertEqual(result['nom'], 'DUPONT')
        self.assertEqual(result['prenoms'], 'JEAN PIERRE PAUL')

    def test_libelle_resolved_when_maps_provided(self):
        commune_info = {'75056': {'libelle': 'Paris, Paris', 'dep': '75', 'reg': '11'}}
        pays_map = {}
        result = parse_row(_row(), commune_info=commune_info, pays_map=pays_map)
        self.assertEqual(result['lieu_naissance_libelle'], 'Paris, Paris')
        self.assertEqual(result['lieu_deces_libelle'], 'Paris, Paris')

    def test_pays_libelle_resolved(self):
        commune_info = {}
        pays_map = {'99109': 'ALLEMAGNE'}
        result = parse_row(_row(lieunaiss='99109', lieudeces='99109'),
                           commune_info=commune_info, pays_map=pays_map)
        self.assertEqual(result['lieu_naissance_libelle'], 'ALLEMAGNE')
        self.assertEqual(result['lieu_deces_libelle'], 'ALLEMAGNE')


# ---------------------------------------------------------------------------
# _resolve_libelle
# ---------------------------------------------------------------------------

class ResolveLibelleTest(TestCase):

    def setUp(self):
        self.commune_info = {'75056': {'libelle': 'Paris, Paris', 'dep': '75', 'reg': '11'}}
        self.pays_map = {'99109': 'ALLEMAGNE'}

    def test_commune(self):
        self.assertEqual(_resolve_libelle('75056', self.commune_info, self.pays_map), 'Paris, Paris')

    def test_pays(self):
        self.assertEqual(_resolve_libelle('99109', self.commune_info, self.pays_map), 'ALLEMAGNE')

    def test_unknown_returns_none(self):
        self.assertIsNone(_resolve_libelle('XXXXX', self.commune_info, self.pays_map))

    def test_none_returns_none(self):
        self.assertIsNone(_resolve_libelle(None, self.commune_info, self.pays_map))


# ---------------------------------------------------------------------------
# deces_to_doc
# ---------------------------------------------------------------------------

class DecesToDocTest(TestCase):

    def setUp(self):
        self.commune_info = {'75056': {'libelle': 'Paris, Paris', 'dep': '75', 'reg': '11'}}
        self.pays_map = {'99109': 'ALLEMAGNE'}

    def _make(self, **kwargs):
        d = MagicMock()
        d.nom = kwargs.get('nom', 'DUPONT')
        d.prenoms = kwargs.get('prenoms', 'JEAN')
        d.sexe = kwargs.get('sexe', '1')
        d.date_naissance = kwargs.get('date_naissance', date(1950, 1, 1))
        d.date_deces = kwargs.get('date_deces', date(2020, 6, 15))
        d.lieu_naissance = kwargs.get('lieu_naissance', '75056')
        d.lieu_deces = kwargs.get('lieu_deces', '75056')
        d.acte_deces = kwargs.get('acte_deces', '12345')
        return d

    def test_id_no_special_chars(self):
        doc = deces_to_doc(self._make(acte_deces='936/430'),
                           commune_info=self.commune_info, pays_libelle=self.pays_map)
        import re
        self.assertRegex(doc['id'], r'^[a-zA-Z0-9_\-]+$')

    def test_pk_fields_preserved(self):
        doc = deces_to_doc(self._make(),
                           commune_info=self.commune_info, pays_libelle=self.pays_map)
        self.assertEqual(doc['pk_acte_deces'], '12345')
        self.assertEqual(doc['pk_lieu_deces'], '75056')

    def test_dep_reg_resolved_for_commune(self):
        doc = deces_to_doc(self._make(),
                           commune_info=self.commune_info, pays_libelle=self.pays_map)
        self.assertEqual(doc['dep_deces'], '75')
        self.assertEqual(doc['reg_deces'], '11')

    def test_pays_code_no_dep(self):
        doc = deces_to_doc(self._make(lieu_deces='99109'),
                           commune_info=self.commune_info, pays_libelle=self.pays_map)
        self.assertIsNone(doc['dep_deces'])
        self.assertIsNone(doc['reg_deces'])

    def test_date_converted_to_timestamp(self):
        doc = deces_to_doc(self._make(), commune_info=self.commune_info, pays_libelle=self.pays_map)
        self.assertIsInstance(doc['date_deces_ts'], int)
        self.assertIsInstance(doc['date_naissance_ts'], int)

    def test_none_date_naissance(self):
        doc = deces_to_doc(self._make(date_naissance=None),
                           commune_info=self.commune_info, pays_libelle=self.pays_map)
        self.assertIsNone(doc['date_naissance_ts'])


# ---------------------------------------------------------------------------
# Search view (DB path)
# ---------------------------------------------------------------------------

class SearchViewTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        commune = make_commune()
        pays = make_pays()
        cls.d1 = make_deces(nom='DUPONT', prenoms='JEAN', sexe='1',
                            date_naissance=date(1950, 1, 1), date_deces=date(2020, 1, 1),
                            lieu_naissance='75056', lieu_deces='75056',
                            lieu_naissance_libelle='Paris, Paris',
                            lieu_deces_libelle='Paris, Paris', acte_deces='00001')
        cls.d2 = make_deces(nom='MARTIN', prenoms='MARIE', sexe='2',
                            date_naissance=date(1960, 6, 15), date_deces=date(2021, 3, 10),
                            lieu_naissance='75056', lieu_deces='75056',
                            lieu_naissance_libelle='Paris, Paris',
                            lieu_deces_libelle='Paris, Paris', acte_deces='00002')
        cls.d3 = make_deces(nom='DUPONT', prenoms='PIERRE', sexe='1',
                            date_naissance=date(1940, 3, 20), date_deces=date(2019, 5, 5),
                            lieu_naissance='99109', lieu_deces='75056',
                            lieu_naissance_libelle='ALLEMAGNE',
                            lieu_deces_libelle='Paris, Paris', acte_deces='00003')

    def setUp(self):
        self.client = Client()

    def _get(self, **params):
        return self.client.get(reverse('deces:search'), params)

    def test_no_criteria_shows_no_results(self):
        r = self._get()
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.context['has_search_criteria'])
        self.assertIsNone(r.context['page_obj'])

    def test_exact_nom_match(self):
        r = self._get(nom='DUPONT')
        self.assertEqual(r.context['page_obj'].paginator.count, 2)

    def test_exact_nom_no_match(self):
        r = self._get(nom='DUPON')
        self.assertEqual(r.context['page_obj'].paginator.count, 0)

    def test_sexe_filter(self):
        r = self._get(nom='DUPONT', sexe='1')
        self.assertEqual(r.context['page_obj'].paginator.count, 2)
        r = self._get(nom='MARTIN', sexe='1')
        self.assertEqual(r.context['page_obj'].paginator.count, 0)

    def test_date_naissance_range(self):
        r = self._get(nom='DUPONT', date_naissance_debut='1945-01-01',
                      date_naissance_fin='1955-01-01')
        self.assertEqual(r.context['page_obj'].paginator.count, 1)

    def test_date_deces_range(self):
        r = self._get(date_deces_debut='2020-01-01', date_deces_fin='2020-12-31')
        self.assertEqual(r.context['page_obj'].paginator.count, 1)

    def test_lieu_naissance_commune(self):
        r = self._get(nom='DUPONT', lieu_naissance='75056', lieu_naissance_type='commune')
        self.assertEqual(r.context['page_obj'].paginator.count, 1)

    def test_lieu_naissance_pays(self):
        r = self._get(nom='DUPONT', lieu_naissance='99109', lieu_naissance_type='pays')
        self.assertEqual(r.context['page_obj'].paginator.count, 1)

    @patch('deces.views.MeiliPage')
    def test_flexible_nom_falls_back_to_db_on_meili_error(self, _mock):
        with patch('deces.search_index._get_client', side_effect=Exception("meili down")):
            r = self._get(nom='dupont', nom_flexible='on')
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(r.context['page_obj'].paginator.count, 2)


# ---------------------------------------------------------------------------
# Export view
# ---------------------------------------------------------------------------

class ExportSearchViewTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        make_commune()
        cls.d1 = make_deces(nom='EXPORT', prenoms='TEST', sexe='1',
                            date_naissance=date(1970, 1, 1), date_deces=date(2020, 1, 1),
                            lieu_naissance='75056', lieu_deces='75056',
                            lieu_naissance_libelle='Paris, Paris',
                            lieu_deces_libelle='Paris, Paris', acte_deces='EXP01')

    def setUp(self):
        self.client = Client()
        user = User.objects.create_user(username='export_test', password='pass', is_staff=True)
        self.client.force_login(user)

    def _get(self, **params):
        return self.client.get(reverse('deces:export_search'), params)

    def test_no_criteria_returns_400(self):
        r = self._get()
        self.assertEqual(r.status_code, 400)

    def test_csv_response_content_type(self):
        r = self._get(nom='EXPORT')
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/csv', r['Content-Type'])

    def test_csv_has_bom(self):
        r = self._get(nom='EXPORT')
        content = b''.join(r.streaming_content)
        self.assertTrue(content.startswith(b'\xef\xbb\xbf'), "Missing UTF-8 BOM")

    def test_csv_has_header_and_data(self):
        r = self._get(nom='EXPORT')
        content = b''.join(r.streaming_content).decode('utf-8-sig')
        lines = [l for l in content.splitlines() if l.strip()]
        self.assertGreaterEqual(len(lines), 2)
        self.assertIn('nom', lines[0])

    def test_csv_sexe_converted(self):
        r = self._get(nom='EXPORT')
        content = b''.join(r.streaming_content).decode('utf-8-sig')
        self.assertIn(';M;', content)

    def test_content_disposition_filename(self):
        r = self._get(nom='EXPORT')
        self.assertIn('deces_export.csv', r['Content-Disposition'])
