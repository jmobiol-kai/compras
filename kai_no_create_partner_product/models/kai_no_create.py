"""Pure helpers for blocking partner and product creation on commercial documents.

Odoo 19 decides the many2one "Create" / "Create and edit" entries from the
field ``options`` (``no_create``, ``no_create_edit``, ``no_quick_create``),
evaluated once when the view is parsed. The field ``context`` is a separate
expression, evaluated in the browser with the Python subset in ``py.js``
(no dict unpacking). These helpers only rewrite ``{...}`` literals so both
sides stay valid.
"""

import ast

CONTEXT_KEY = 'kai_from_commercial_document'
PARTNER_PRODUCT_MODELS = frozenset({
    'res.partner',
    'product.product',
    'product.template',
})
COMMERCIAL_VIEW_TYPES = frozenset({'form', 'list', 'kanban'})
_NO_CREATE_OPTIONS = ('no_create', 'no_create_edit', 'no_quick_create')


def commercial_create_is_blocked(env):
    """True when this create comes from a guarded document and the user may not."""
    if not env.context.get(CONTEXT_KEY):
        return False
    return not env.user.kai_allow_create_partner_product


def inject_context_key(expr):
    """Return ``expr`` with the commercial-document marker set.

    Non-dict expressions are returned unchanged: a broken context would take
    down the whole form, and the server check only needs the key when the
    many2one actually sends its own context.
    """
    flag = "'%s': True" % CONTEXT_KEY
    expr = (expr or '').strip()
    if not expr:
        return '{%s}' % flag
    if not _is_single_dict_literal(expr):
        return expr
    inner = expr[1:-1].strip()
    if inner.endswith(','):
        inner = inner[:-1].strip()
    if not inner:
        return '{%s}' % flag
    return '{%s, %s}' % (inner, flag)


def merge_no_create_options(raw):
    """Return options text with creation disabled, or None if it is not a dict.

    The original literal is kept and the missing flags are appended. ``py.js``
    and ``ast.literal_eval`` both keep the last value of a repeated key, so an
    existing ``'no_create': False`` is overridden without a full rewrite that
    could change quoting the client already accepts.
    """
    raw = (raw or '').strip()
    if not raw:
        return "{'no_create': True, 'no_create_edit': True, 'no_quick_create': True}"
    if not _is_single_dict_literal(raw):
        return None
    try:
        current = ast.literal_eval(raw)
    except (ValueError, SyntaxError, MemoryError, TypeError):
        current = None
    if isinstance(current, dict):
        missing = [key for key in _NO_CREATE_OPTIONS if not current.get(key)]
        if not missing:
            extra = None
        else:
            extra = ', '.join("'%s': True" % key for key in missing)
    else:
        extra = "'no_create': True, 'no_create_edit': True, 'no_quick_create': True"
    if not extra:
        return raw
    inner = raw[1:-1].strip()
    if inner.endswith(','):
        inner = inner[:-1].strip()
    if not inner:
        return '{%s}' % extra
    return '{%s, %s}' % (inner, extra)


def force_no_create(node):
    """Hide Create / Create and edit and mark the context for the server check."""
    merged = merge_no_create_options(node.get('options'))
    if merged is not None:
        node.set('options', merged)
    node.set('context', inject_context_key(node.get('context')))


def restrict_partner_product_m2o(node, model):
    """Walk a view arch, including embedded x2many subviews, and lock those m2o."""
    for child in list(node):
        if not isinstance(getattr(child, 'tag', None), str):
            continue
        if child.tag != 'field':
            restrict_partner_product_m2o(child, model)
            continue
        field = model._fields.get(child.get('name') or '')
        if field and field.type == 'many2one' and field.comodel_name in PARTNER_PRODUCT_MODELS:
            force_no_create(child)
        if field and field.type in ('one2many', 'many2many') and field.comodel_name in model.env:
            restrict_partner_product_m2o(child, model.env[field.comodel_name])
            continue
        restrict_partner_product_m2o(child, model)


def _is_single_dict_literal(expr):
    if not expr.startswith('{') or not expr.endswith('}'):
        return False
    return _matching_brace_end(expr) == len(expr) - 1


def _matching_brace_end(expr):
    depth = 0
    quote = None
    escape = False
    for index, char in enumerate(expr):
        if quote:
            if escape:
                escape = False
            elif char == '\\':
                escape = True
            elif char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
            continue
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return index
    return -1
