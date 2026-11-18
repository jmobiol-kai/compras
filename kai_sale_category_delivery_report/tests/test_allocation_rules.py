"""Coverage planning for the category / delivery-date report.

Run from the repo root:

    python3 kai_sale_category_delivery_report/tests/test_allocation_rules.py
"""
import importlib.util
import unittest
from pathlib import Path


def _load(name, relative):
    path = Path(__file__).resolve().parents[1] / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rules = _load('kai_allocation_rules', Path('wizard') / 'allocation_rules.py')


def _origin(**overrides):
    values = {
        'sale_line_id': 1,
        'sale_order_id': 10,
        'sale_order_name': 'S00010',
        'product_id': 5,
        'qty_demand': 10.0,
        'purchase_ok': True,
        'rounding': 0.01,
        'product_name': 'Pan',
        'default_code': 'PAN',
        'categ_id': 3,
        'categ_complete_name': 'Catering / Pan',
        'product_uom_id': 1,
    }
    values.update(overrides)
    return values


class TestCoveredMap(unittest.TestCase):
    def test_draft_sent_and_purchase_count(self):
        covered = rules.covered_map([
            (1, 2, 'draft'),
            (1, 3, 'sent'),
            (1, 1, 'to approve'),
            (1, 4, 'purchase'),
        ])
        self.assertEqual(covered, {1: 10})

    def test_cancel_and_empty_state_do_not_count(self):
        covered = rules.covered_map([
            (1, 6, 'cancel'),
            (1, 4, False),
            (1, 1, ''),
            (2, 5, 'draft'),
        ])
        self.assertEqual(covered, {2: 5})

    def test_legacy_purchase_without_rows_covers_nothing(self):
        # A historical PO is simply absent from the allocation rows.
        covered = rules.covered_map([])
        plan = rules.plan_purchase([_origin(qty_demand=4)], covered)
        self.assertIsNone(plan['reason'])
        self.assertEqual(plan['purchases'][0]['quantity'], 4)
        self.assertEqual(plan['purchases'][0]['allocations'], [
            {'sale_line_id': 1, 'sale_order_id': 10, 'quantity': 4},
        ])


class TestPlanPurchase(unittest.TestCase):
    def test_partial_coverage_buys_only_the_remainder(self):
        plan = rules.plan_purchase(
            [_origin(qty_demand=10)],
            rules.covered_map([(1, 4, 'draft'), (1, 6, 'cancel')]),
        )
        self.assertEqual(plan['rows'][0]['coverage_state'], 'partial')
        self.assertEqual(plan['rows'][0]['qty_demand'], 10)
        self.assertEqual(plan['rows'][0]['qty_covered'], 4)
        self.assertEqual(plan['rows'][0]['qty_pending'], 6)
        self.assertEqual(plan['purchases'][0]['quantity'], 6)
        self.assertEqual(plan['purchases'][0]['allocations'][0]['quantity'], 6)

    def test_full_draft_coverage_rejects_a_second_purchase(self):
        first = rules.plan_purchase([_origin()], {})
        covered = {
            item['sale_line_id']: item['quantity']
            for item in first['purchases'][0]['allocations']
        }
        second = rules.plan_purchase([_origin()], covered)
        self.assertEqual(second['reason'], 'covered')
        self.assertEqual(second['purchases'], [])
        self.assertEqual(second['rows'][0]['coverage_state'], 'covered')
        self.assertEqual(second['rows'][0]['qty_pending'], 0)

    def test_new_sale_quantity_is_not_blocked_by_the_old_coverage(self):
        plan = rules.plan_purchase([_origin(qty_demand=12)], {1: 10})
        self.assertEqual(plan['purchases'][0]['quantity'], 2)
        self.assertEqual(plan['rows'][0]['coverage_state'], 'partial')

    def test_one_covered_line_does_not_block_its_sibling(self):
        origins = [
            _origin(sale_line_id=1, qty_demand=5),
            _origin(sale_line_id=2, sale_order_id=10, qty_demand=5, sale_order_name='S00010'),
        ]
        plan = rules.plan_purchase(origins, {1: 5})
        self.assertEqual(len(plan['purchases']), 1)
        self.assertEqual(plan['purchases'][0]['quantity'], 5)
        self.assertEqual(
            plan['purchases'][0]['allocations'],
            [{'sale_line_id': 2, 'sale_order_id': 10, 'quantity': 5}],
        )
        states = {item['sale_line_id']: item['coverage_state'] for item in plan['rows'][0]['origins']}
        self.assertEqual(states, {1: 'covered', 2: 'pending'})

    def test_surplus_on_one_line_does_not_cover_another(self):
        origins = [
            _origin(sale_line_id=1, qty_demand=5),
            _origin(sale_line_id=2, qty_demand=5),
        ]
        plan = rules.plan_purchase(origins, {1: 8})
        self.assertEqual(plan['rows'][0]['qty_demand'], 10)
        self.assertEqual(plan['rows'][0]['qty_covered'], 8)
        self.assertEqual(plan['rows'][0]['qty_pending'], 5)
        self.assertEqual(plan['purchases'][0]['allocations'][0]['sale_line_id'], 2)
        self.assertEqual(plan['rows'][0]['origins'][0]['coverage_state'], 'over')

    def test_products_stay_separate_and_not_purchasable_is_skipped(self):
        origins = [
            _origin(product_id=5, product_name='Pan', qty_demand=2),
            _origin(
                sale_line_id=2, sale_order_id=11, product_id=6, product_name='Vino',
                qty_demand=3, purchase_ok=False,
            ),
        ]
        plan = rules.plan_purchase(origins, {})
        self.assertEqual([item['product_id'] for item in plan['purchases']], [5])
        self.assertEqual(plan['purchases'][0]['quantity'], 2)
        self.assertEqual(plan['skipped'], ['Vino'])
        self.assertIsNone(plan['reason'])

    def test_only_not_purchasable_pending_has_its_own_reason(self):
        plan = rules.plan_purchase([_origin(purchase_ok=False)], {})
        self.assertEqual(plan['reason'], 'not_purchasable')
        self.assertEqual(plan['purchases'], [])
        self.assertEqual(plan['rows'][0]['qty_pending'], 10)

    def test_zero_demand_without_coverage_is_empty(self):
        plan = rules.plan_purchase([_origin(qty_demand=0)], {})
        self.assertEqual(plan['reason'], 'empty')

    def test_lowering_sale_demand_does_not_ask_for_another_purchase(self):
        # The purchase is left as it is. Surplus coverage is visible and
        # blocks a new buy of that line; it does not cover a different line.
        plan = rules.plan_purchase([_origin(qty_demand=3)], {1: 10})
        self.assertEqual(plan['reason'], 'covered')
        self.assertEqual(plan['rows'][0]['coverage_state'], 'over')
        self.assertEqual(plan['rows'][0]['qty_pending'], 0)
        self.assertEqual(plan['purchases'], [])

    def test_companies_must_match_the_active_one(self):
        self.assertTrue(rules.same_company([7, 7, False], 7))
        self.assertFalse(rules.same_company([7, 8], 7))
        self.assertTrue(rules.same_company([], 7))


class TestCapAllocations(unittest.TestCase):
    def test_lower_quantity_releases_the_newest_link_first(self):
        self.assertEqual(
            rules.cap_allocation_quantities([6, 4], 7, rounding=1),
            [6, 1],
        )
        self.assertEqual(
            rules.cap_allocation_quantities([6, 4], 6, rounding=1),
            [6, 0],
        )
        self.assertEqual(
            rules.cap_allocation_quantities([6, 4], 3, rounding=1),
            [3, 0],
        )

    def test_higher_quantity_does_not_invent_coverage(self):
        self.assertEqual(
            rules.cap_allocation_quantities([6, 4], 20, rounding=1),
            [6, 4],
        )

    def test_zero_cap_clears_every_link(self):
        self.assertEqual(
            rules.cap_allocation_quantities([6, 4], 0, rounding=1),
            [0, 0],
        )


class TestWizardUsesThePlanner(unittest.TestCase):
    def test_generation_locks_before_planning_and_ignores_the_snapshot_quantity(self):
        wizard = (
            Path(__file__).resolve().parents[1] / 'wizard' / 'sale_category_delivery_wizard.py'
        ).read_text()
        create = wizard.split('def _create_purchase_order', 1)[1]
        self.assertLess(create.find('_advisory_lock'), create.find('lock_sale_lines'))
        self.assertLess(create.find('lock_sale_lines'), create.find('plan_purchase'))
        self.assertLess(create.find('plan_purchase'), create.find('cap_allocation_quantities'))
        self.assertNotIn('line.quantity', create)
        self.assertIn('pg_advisory_xact_lock', wizard)
        self.assertIn('kai.sale.po.allocation', wizard)
        # origin text is still written, and it is not how coverage is decided.
        self.assertIn("'origin':", wizard)
        self.assertNotIn('sudo', wizard)


if __name__ == '__main__':
    unittest.main()
