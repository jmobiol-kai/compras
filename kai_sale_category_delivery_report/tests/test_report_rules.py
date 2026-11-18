"""Calendar window and sale states.

Run from the repo root:

    python3 kai_sale_category_delivery_report/tests/test_report_rules.py
"""
import importlib.util
import unittest
from datetime import date, datetime
from pathlib import Path


def _load_rules():
    path = Path(__file__).resolve().parents[1] / 'wizard' / 'report_rules.py'
    spec = importlib.util.spec_from_file_location('kai_report_rules', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rules = _load_rules()


class TestReportRules(unittest.TestCase):
    def test_argentina_day_is_utc_minus_3(self):
        # 2026-11-05 in America/Argentina/Buenos_Aires (UTC-3, no DST).
        start, end = rules.commitment_utc_window(
            date(2026, 11, 5), 'America/Argentina/Buenos_Aires',
        )
        self.assertEqual(start, datetime(2026, 11, 5, 3, 0))
        self.assertEqual(end, datetime(2026, 11, 6, 3, 0))

    def test_unknown_timezone_falls_back_to_argentina(self):
        start, end = rules.commitment_utc_window(date(2026, 11, 5), 'Not/AZone')
        fallback_start, fallback_end = rules.commitment_utc_window(
            date(2026, 11, 5), rules.FALLBACK_TZ,
        )
        self.assertEqual((start, end), (fallback_start, fallback_end))

    def test_tz_preference_is_user_then_company_then_argentina(self):
        self.assertEqual(rules.resolve_tz_name('Europe/Madrid', 'UTC'), 'Europe/Madrid')
        self.assertEqual(
            rules.resolve_tz_name(False, 'America/Argentina/Buenos_Aires'),
            'America/Argentina/Buenos_Aires',
        )
        self.assertEqual(rules.resolve_tz_name(None, None), rules.FALLBACK_TZ)

    def test_default_states_are_sale_and_done(self):
        self.assertEqual(rules.sale_states(), ('sale', 'done'))
        self.assertEqual(rules.sale_states(False), ('sale', 'done'))

    def test_quotes_are_never_included(self):
        # A stored wizard flag must not widen the domain.
        confirmed = rules.sale_states(False)
        for include_quotes in (True, 1, 'draft'):
            self.assertEqual(rules.sale_states(include_quotes), confirmed)
        for state in rules.QUOTE_STATES + ('cancel',):
            self.assertNotIn(state, rules.sale_states(True))

    def test_wizard_has_no_include_quotes_flag(self):
        root = Path(__file__).resolve().parents[1]
        view = (root / 'views' / 'sale_category_delivery_wizard_views.xml').read_text()
        wizard = (root / 'wizard' / 'sale_category_delivery_wizard.py').read_text()
        self.assertNotIn('include_draft', view)
        self.assertNotIn('Incluir presupuestos', view)
        self.assertIn('name="categ_ids"', view)
        self.assertIn('name="delivery_date"', view)
        self.assertIn('name="partner_id"', view)
        self.assertNotIn('include_draft', wizard)
        self.assertIn('sale_states()', wizard)

    def test_purchase_form_is_editable_after_report_context_merge(self):
        # The report list is read-only. Odoo 19 copies that context onto the
        # purchase form unless the returned action overrides edit/create/delete.
        report_context = {
            'wizard_id': 9,
            'create': False,
            'edit': False,
            'delete': False,
            'allowed_company_ids': [3],
            'default_partner_id': 4,
            'search_default_purchase_ok': 1,
            'group_by': 'categ_id',
        }
        merged = rules.merged_button_action_context(
            report_context,
            rules.purchase_order_action_context(),
        )
        self.assertTrue(merged['edit'])
        self.assertTrue(merged['create'])
        self.assertTrue(merged['delete'])
        # Company scope stays the user's. Nothing here widens it.
        self.assertEqual(merged['allowed_company_ids'], [3])
        self.assertNotIn('default_partner_id', merged)
        self.assertNotIn('search_default_purchase_ok', merged)
        self.assertNotIn('group_by', merged)
        self.assertEqual(merged['wizard_id'], 9)

    def test_purchase_action_uses_editable_context_and_keeps_list_locked(self):
        wizard = (
            Path(__file__).resolve().parents[1]
            / 'wizard'
            / 'sale_category_delivery_wizard.py'
        ).read_text()
        self.assertIn("'edit': False", wizard)
        self.assertIn('purchase_order_action_context()', wizard)
        self.assertNotIn("sudo", wizard)
        # The generated order is a draft: nothing writes a purchase state.
        self.assertNotIn("'state':", wizard)


if __name__ == '__main__':
    unittest.main()
