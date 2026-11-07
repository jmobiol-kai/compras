"""View names must be real fields. Odoo 19 rejects the module otherwise.

The 19.0.1.0.3 install failed because a button used
``invisible="not legacy_purchase_ids"`` while that name existed only in the
action context. This check walks every view the way ``ir.ui.view`` does:
field tags, modifiers, decorations and domain leaves must name a field of
the view model. It does not boot Odoo.

Run from the repo root:

    python3 kai_sale_category_delivery_report/tests/test_view_fields.py
"""
import ast
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Names Odoo ignores inside invisible/readonly/required/decoration expressions.
IGNORED = {
    'True', 'False', 'None', 'self', 'uid', 'context', 'context_today',
    'allowed_company_ids', 'current_company_id', 'time', 'datetime',
    'relativedelta', 'current_date', 'today', 'now', 'abs', 'len', 'bool',
    'float', 'str', 'unicode', 'set', 'id', 'parent', 'true', 'false',
}
MODIFIERS = ('column_invisible', 'invisible', 'readonly', 'required')
# Fields used on models this module only extends. Odoo core defines them.
BASE_FIELDS = {
    'purchase.order': {'state'},
    'purchase.order.line': set(),
    'sale.order': set(),
    'sale.order.line': set(),
}
KNOWN_GROUPS = {
    'sales_team.group_sale_salesman',
    'purchase.group_purchase_user',
}


def _expression_names(expression):
    if not expression or expression.strip().lower() in {'0', '1', 'true', 'false'}:
        return set()
    tree = ast.parse(expression.strip(), mode='eval').body

    def walk(node):
        if isinstance(node, ast.Constant):
            return set()
        if isinstance(node, ast.Name):
            return {node.id}
        if isinstance(node, ast.Attribute):
            roots = walk(node.value)
            if len(roots) == 1:
                return {f'{next(iter(roots))}.{node.attr}'}
            return roots
        if isinstance(node, (ast.List, ast.Tuple)):
            names = set()
            for item in node.elts:
                names |= walk(item)
            return names
        if isinstance(node, ast.UnaryOp):
            return walk(node.operand)
        if isinstance(node, ast.BoolOp):
            names = set()
            for item in node.values:
                names |= walk(item)
            return names
        if isinstance(node, ast.Compare):
            names = walk(node.left)
            for item in node.comparators:
                names |= walk(item)
            return names
        if isinstance(node, ast.BinOp):
            return walk(node.left) | walk(node.right)
        if isinstance(node, ast.Call):
            names = walk(node.func)
            for arg in node.args:
                names |= walk(arg)
            for keyword in node.keywords:
                names |= walk(keyword.value)
            return names
        if isinstance(node, ast.IfExp):
            return walk(node.test) | walk(node.body) | walk(node.orelse)
        if isinstance(node, ast.Subscript):
            return walk(node.value) | walk(node.slice)
        if isinstance(node, ast.Dict):
            names = set()
            for key in node.keys:
                if key is not None:
                    names |= walk(key)
            for value in node.values:
                names |= walk(value)
            return names
        raise AssertionError(f'unsupported expression node {type(node).__name__}: {expression}')

    names = set()
    for name in walk(tree):
        root = name.split('.', 1)[0]
        if root not in IGNORED and root != 'parent':
            names.add(root)
    return names


def _domain_field_names(domain):
    """Left-hand field names of a domain literal. Values are not fields."""
    tree = ast.parse(domain.strip(), mode='eval').body
    names = set()

    def leaf(node):
        if not isinstance(node, (ast.List, ast.Tuple)) or len(node.elts) != 3:
            return
        left = node.elts[0]
        if isinstance(left, ast.Constant) and isinstance(left.value, str):
            names.add(left.value.split('.', 1)[0])

    def walk(node):
        if isinstance(node, (ast.List, ast.Tuple)):
            if node.elts and isinstance(node.elts[0], ast.Constant) and not isinstance(node.elts[0].value, str):
                return
            if len(node.elts) == 3 and not isinstance(node.elts[0], (ast.List, ast.Tuple)):
                leaf(node)
                return
            for item in node.elts:
                walk(item)

    walk(tree)
    return names


def _field_call(node):
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == 'fields':
        return func.attr
    return None


def _const_str(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def parse_models():
    """model -> {field name: comodel or None} and model -> public method names."""
    fields_by_model = {name: set(names) for name, names in BASE_FIELDS.items()}
    comodel = {}
    methods = {name: set() for name in BASE_FIELDS}
    for path in ROOT.rglob('*.py'):
        if 'tests' in path.parts:
            continue
        tree = ast.parse(path.read_text())
        for cls in tree.body:
            if not isinstance(cls, ast.ClassDef):
                continue
            model_name = None
            for stmt in cls.body:
                if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
                    continue
                target = stmt.targets[0]
                if not isinstance(target, ast.Name):
                    continue
                if target.id == '_name':
                    model_name = _const_str(stmt.value)
                elif target.id == '_inherit' and model_name is None:
                    model_name = _const_str(stmt.value)
            if not model_name:
                continue
            fields_by_model.setdefault(model_name, set()).update(BASE_FIELDS.get(model_name, set()))
            methods.setdefault(model_name, set())
            for stmt in cls.body:
                if isinstance(stmt, ast.FunctionDef) and not stmt.name.startswith('_'):
                    methods[model_name].add(stmt.name)
                if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
                    continue
                target = stmt.targets[0]
                if not isinstance(target, ast.Name):
                    continue
                kind = _field_call(stmt.value)
                if not kind:
                    continue
                fields_by_model[model_name].add(target.id)
                if kind in {'Many2one', 'One2many', 'Many2many'} and stmt.value.args:
                    other = _const_str(stmt.value.args[0])
                    if other:
                        comodel[(model_name, target.id)] = other
    return fields_by_model, comodel, methods


def _arch_views():
    views = []
    for path in (ROOT / 'views').glob('*.xml'):
        root = ET.parse(path).getroot()
        for record in root.findall('record'):
            if record.find('field[@name="arch"]') is None:
                continue
            model = record.findtext('field[@name="model"]')
            arch = record.find('field[@name="arch"]')
            views.append((str(path.relative_to(ROOT)), model, list(arch)))
    return views


class TestViewFields(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fields, cls.comodel, cls.methods = parse_models()

    def test_every_view_name_is_a_field_and_every_button_is_a_method(self):
        missing = []
        for path, model, nodes in _arch_views():
            self._walk(path, model, nodes, missing)
        self.assertFalse(missing, '\n'.join(missing))

    def _walk(self, path, model, nodes, missing):
        for node in nodes:
            if not isinstance(node.tag, str):
                continue
            children_model = model
            if node.tag == 'field':
                name = node.get('name')
                if name and name not in self.fields.get(model, set()):
                    missing.append(f'{path}: <field name="{name}"> is not on {model}')
                if list(node):
                    children_model = self.comodel.get((model, name), model)
            if node.tag == 'button' and node.get('type') == 'object':
                action = node.get('name')
                if action not in self.methods.get(model, set()):
                    missing.append(f'{path}: button {action} is not a method of {model}')
            for attr in MODIFIERS:
                expr = node.get(attr)
                for fname in _expression_names(expr or ''):
                    if fname not in self.fields.get(model, set()):
                        missing.append(
                            f'{path}: {attr}="{expr}" uses "{fname}", missing on {model}'
                        )
            for attr, expr in node.attrib.items():
                if not attr.startswith('decoration-'):
                    continue
                for fname in _expression_names(expr):
                    if fname not in self.fields.get(model, set()):
                        missing.append(
                            f'{path}: {attr}="{expr}" uses "{fname}", missing on {model}'
                        )
            if node.tag == 'filter' and node.get('domain'):
                for fname in _domain_field_names(node.get('domain')):
                    if fname not in self.fields.get(model, set()):
                        missing.append(
                            f'{path}: filter {node.get("name")} domain uses "{fname}", missing on {model}'
                        )
            if node.get('groups'):
                for group in node.get('groups').replace('!', '').split(','):
                    group = group.strip()
                    if group and group not in KNOWN_GROUPS:
                        missing.append(f'{path}: unknown group {group}')
            self._walk(path, children_model, list(node), missing)

    def test_access_csv_covers_every_model(self):
        names = set()
        for line in (ROOT / 'security' / 'ir.model.access.csv').read_text().splitlines()[1:]:
            if not line.strip():
                continue
            xmlid = line.split(',')[2]
            self.assertTrue(xmlid.startswith('model_'), xmlid)
            names.add(xmlid[len('model_'):].replace('_', '.'))
        defined = {
            model for model in self.fields
            if model not in BASE_FIELDS or model.startswith('kai.')
        }
        # BASE_FIELDS keys are extended models. Own models are the kai.* ones.
        own = {model for model in self.fields if model.startswith('kai.')}
        self.assertEqual(own, names)
        self.assertTrue(defined)

    def test_security_rule_and_data_files_exist(self):
        rules = (ROOT / 'security' / 'sale_po_allocation_rules.xml').read_text()
        self.assertIn('model_kai_sale_po_allocation', rules)
        self.assertIn("company_ids", rules)
        manifest = (ROOT / '__manifest__.py').read_text()
        self.assertIn("'version': '19.0.1.0.6'", manifest)
        for name in (
            'security/ir.model.access.csv',
            'security/sale_po_allocation_rules.xml',
            'views/sale_category_delivery_line_views.xml',
            'views/sale_category_delivery_wizard_views.xml',
            'views/purchase_order_views.xml',
        ):
            self.assertTrue((ROOT / name).is_file(), name)

    def test_legacy_button_names_a_real_field(self):
        view = (ROOT / 'views' / 'sale_category_delivery_line_views.xml').read_text()
        self.assertIn('invisible="not legacy_purchase_ids"', view)
        self.assertIn('legacy_purchase_ids', self.fields['kai.sale.category.delivery.line'])
        wizard = (ROOT / 'wizard' / 'sale_category_delivery_wizard.py').read_text()
        self.assertIn("'legacy_purchase_ids':", wizard)


if __name__ == '__main__':
    unittest.main()
