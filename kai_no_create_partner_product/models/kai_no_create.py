"""Helpers for blocking partner and product creation outside Inventory and Contacts.

Called from ``_inherit`` model classes. Do not use these as Python base classes:
Odoo 19 cannot reassign ``__bases__`` when a non-Model mixin changes the layout.

Odoo 19 decides the many2one "Create" / "Create and edit" entries from the
field ``options`` (``no_create``, ``no_create_edit``, ``no_quick_create``),
evaluated once when the view is parsed. The field ``context`` is a separate
expression, evaluated in the browser with the Python subset in ``py.js``
(no dict unpacking). These helpers only rewrite ``{...}`` literals so both
sides stay valid.

The server rejects ``create`` only when that context key is present. Flows
that never send it (company and user creation, the mail gateway, imports,
AFIP padrón lookups, portal signup, branch setup, and the Point of Sale
partner dialog) keep working. The POS dialog opens ``res.partner``, which is
one of the screens where creation stays allowed, so its form is not rewritten.
"""

import ast
import logging
import re

from lxml import etree

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

CONTEXT_KEY = 'kai_from_commercial_document'
PARTNER_PRODUCT_MODELS = frozenset({
    'res.partner',
    'product.product',
    'product.template',
})
# Screens where creating a contact or a product is the point of the form,
# plus technical models whose own many2one fields must keep their buttons.
DIRECT_CREATION_MODELS = frozenset({
    'res.partner',
    'product.template',
    'product.product',
    'product.supplierinfo',
    'product.packaging',
    'res.users',
    'res.company',
    'res.config.settings',
})
COMMERCIAL_VIEW_TYPES = frozenset({'form', 'list', 'kanban'})
_NO_CREATE_OPTIONS = ('no_create', 'no_create_edit', 'no_quick_create')
_MODEL_NAME = re.compile(r'^[A-Za-z0-9_.]+$')


def model_allows_direct_creation(model_name):
    """True when this model's own screens must keep Create on partner/product fields."""
    if not model_name:
        return False
    if model_name in DIRECT_CREATION_MODELS:
        return True
    if model_name.startswith('ir.'):
        return True
    if model_name.endswith('.config.settings'):
        return True
    return False


def user_can_create_partner_product(user):
    """True when this user may create contacts and products from any screen."""
    user.ensure_one()
    if user._is_superuser() or user.has_group('base.group_system'):
        return True
    return user.has_group(
        'kai_no_create_partner_product.group_kai_allow_create_partner_product'
    )


def commercial_create_is_blocked(env):
    """True when this create comes from a guarded screen and the user may not."""
    if not env.context.get(CONTEXT_KEY):
        return False
    return not user_can_create_partner_product(env.user)


def check_commercial_create(model, vals_list):
    """Raise if ``vals_list`` would create a partner or product from a guarded screen."""
    if not vals_list or not commercial_create_is_blocked(model.env):
        return
    origin = model.env.context.get(CONTEXT_KEY)
    _logger.info(
        "Blocked %s creation by user %s (id=%s) originating from %s",
        model._name,
        model.env.user.login,
        model.env.uid,
        origin,
    )
    raise UserError(commercial_create_message(model))


def extend_commercial_view_cache_key(model, key):
    """Include the permission. ``get_view`` is cached without the uid.

    Two users with the same permission share the entry. A user who may create
    and a user who may not must not share it, or one of them would see the
    other's buttons. Screens that are not rewritten skip the extra key.
    """
    if model_allows_direct_creation(model._name):
        return key
    return key + (user_can_create_partner_product(model.env.user),)


def guard_commercial_arch(model, arch, view_type):
    """Return ``arch`` with partner/product many2one creation hidden when needed.

    The tree is copied before editing so a shared combined arch is not mutated
    for users who are still allowed to create. Inline subviews of models where
    creation stays allowed (the product form, Contacts, settings) are left as
    they were authored.
    """
    if view_type not in COMMERCIAL_VIEW_TYPES or model_allows_direct_creation(model._name):
        return arch
    if user_can_create_partner_product(model.env.user):
        return arch
    arch = etree.fromstring(etree.tostring(arch))
    restrict_partner_product_m2o(arch, model)
    return arch


def commercial_create_message(model):
    if model._name == 'res.partner':
        return model.env._(
            'No tiene permitido crear contactos desde esta pantalla. '
            'Créelos en Contactos, o pida que le asignen el permiso '
            '«Puede crear productos y contactos en cualquier pantalla».'
        )
    return model.env._(
        'No tiene permitido crear productos desde esta pantalla. '
        'Créelos en Inventario, o pida que le asignen el permiso '
        '«Puede crear productos y contactos en cualquier pantalla».'
    )


def _context_flag(origin):
    if isinstance(origin, str) and _MODEL_NAME.match(origin):
        return "'%s': '%s'" % (CONTEXT_KEY, origin)
    return "'%s': True" % CONTEXT_KEY


def inject_context_key(expr, origin=True):
    """Return ``expr`` with the guarded-screen marker set.

    ``origin`` is stored when it is a model name so the server log can name
    the screen. Non-dict expressions are returned unchanged: a broken context
    would take down the whole form, and the server check only needs the key
    when the many2one actually sends its own context.
    """
    flag = _context_flag(origin)
    expr = (expr or '').strip()
    if not expr:
        return '{%s}' % flag
    if not _is_single_dict_literal(expr) or _dict_literal_has_key(expr, CONTEXT_KEY):
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


def force_no_create(node, origin):
    """Hide Create / Create and edit and mark the context for the server check."""
    merged = merge_no_create_options(node.get('options'))
    if merged is not None:
        node.set('options', merged)
    node.set('context', inject_context_key(node.get('context'), origin))


def restrict_partner_product_m2o(node, model):
    """Walk a view arch, including embedded x2many subviews, and lock those m2o.

    Subviews of models that still allow creation are not rewritten, so a
    product form keeps its supplier and variant lines intact.
    """
    if model_allows_direct_creation(model._name):
        return
    for child in list(node):
        if not isinstance(getattr(child, 'tag', None), str):
            continue
        if child.tag != 'field':
            restrict_partner_product_m2o(child, model)
            continue
        field = model._fields.get(child.get('name') or '')
        if field and field.type == 'many2one' and field.comodel_name in PARTNER_PRODUCT_MODELS:
            force_no_create(child, model._name)
        if field and field.type in ('one2many', 'many2many') and field.comodel_name in model.env:
            if not model_allows_direct_creation(field.comodel_name):
                restrict_partner_product_m2o(child, model.env[field.comodel_name])
            continue
        restrict_partner_product_m2o(child, model)


def _dict_literal_has_key(expr, key):
    try:
        value = ast.literal_eval(expr)
    except (ValueError, SyntaxError, MemoryError, TypeError):
        return ("'%s'" % key) in expr or ('"%s"' % key) in expr
    return isinstance(value, dict) and key in value


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
