"""Calendar window, sale states and shared-vendor rule.

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
        self.assertEqual(rules.sale_states(False), ('sale', 'done'))

    def test_quotes_add_draft_and_sent(self):
        self.assertEqual(
            rules.sale_states(True),
            ('sale', 'done', 'draft', 'sent'),
        )

    def test_shared_preferred_seller(self):
        # Facturas 2026-11-05: the three products share Fernandez (id 69).
        self.assertEqual(rules.shared_preferred_partner_id([69, 69, 69]), 69)
        self.assertIsNone(rules.shared_preferred_partner_id([69, 70, 69]))
        self.assertIsNone(rules.shared_preferred_partner_id([69, None]))
        self.assertIsNone(rules.shared_preferred_partner_id([]))


if __name__ == '__main__':
    unittest.main()
