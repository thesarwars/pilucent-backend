"""Customer hierarchy for the by-customer summary reports.

`Customer.parent` is a self-FK, so sub-customers are a real hierarchy rather
than something inferred from names. Two reports nest on it -- sales by customer
and income by customer -- and they have to agree on the nesting, the display
name and the print order, so the walk lives here rather than in either of them.

The nesting is **arbitrarily deep**. An earlier version of this walk rendered
only roots and their direct children, which silently dropped a sub-sub-customer
from its row *and* from every total above it -- money disappearing from a
financial report with no indication. `Customer.parent` has no depth limit,
cycle guard or self-reference guard at any layer (unlike `ChartOfAccount`,
which rejects self-parenting in its serializer), so this code cannot assume a
shape: it must render whatever the column holds without losing anything.
"""

from weapi.django_rest.helpers.reports.profit_loss_engine import UNASSIGNED_KEY


def customer_tree(company, keys):
    """(parent uid by uid, display name by uid) for the customers in `keys`."""
    from customerio.models import Customer

    real = [key for key in keys if key != UNASSIGNED_KEY]
    if not real:
        return {}, {}

    parents = {}
    names = {}
    rows = Customer.objects.filter(company=company, uid__in=real).values(
        "uid", "parent__uid", "display_name", "first_name", "last_name"
    )
    for row in rows:
        uid = str(row["uid"])
        parents[uid] = str(row["parent__uid"]) if row["parent__uid"] else None
        label = (row["display_name"] or "").strip()
        if not label:
            label = " ".join(
                part
                for part in (
                    (row["first_name"] or "").strip(),
                    (row["last_name"] or "").strip(),
                )
                if part
            )
        names[uid] = label or "(unnamed)"
    return parents, names


def sort_key(key, names):
    """Named customers alphabetically, "Not specified" last."""
    return (key == UNASSIGNED_KEY, (names.get(key) or "").lower(), key)


def _is_rooted(key, parents, keys):
    """Does walking up from `key` terminate, or does it loop?

    A self-parented or cyclic customer has no root, so it cannot be filed as
    anyone's child without vanishing from the render. Such a key is promoted to
    a root instead -- it prints un-nested, which is wrong-looking but keeps its
    figures in the report and in the totals.
    """
    seen = {key}
    current = parents.get(key)
    while current and current in keys:
        if current in seen:
            return False
        seen.add(current)
        current = parents.get(current)
    return True


def group_by_parent(keys, parents):
    """Split `keys` into (roots, children by parent).

    A sub-customer whose parent has no figures of its own still has to appear
    under that parent, so grouping is driven by the parent link rather than by
    who happens to have a total. A parent outside `keys`, or a parent chain
    that loops, leaves the key a root -- otherwise it would never be rendered.
    """
    children = {}
    roots = []
    for key in keys:
        parent = parents.get(key)
        if parent and parent in keys and _is_rooted(key, parents, keys):
            children.setdefault(parent, []).append(key)
        else:
            roots.append(key)
    return roots, children


def tree_rows(keys, parents, names):
    """Yield `(key, depth, subtree)` for the whole forest, in print order.

    `subtree` is `None` on a customer's own row. On a "Total for <customer>"
    row it is the list of keys that total covers -- the customer plus every
    descendant -- and such a row is emitted only for a customer that has
    children, since otherwise it would just restate the row above it.

    Totals nest: a sub-customer with children of its own gets its own total
    inside its parent's.
    """
    roots, children = group_by_parent(keys, parents)

    def ordered(items):
        return sorted(items, key=lambda key: sort_key(key, names))

    def subtree_of(key):
        members = [key]
        for child in ordered(children.get(key, [])):
            members.extend(subtree_of(child))
        return members

    def visit(key, depth):
        yield key, depth, None
        kids = ordered(children.get(key, []))
        for child in kids:
            yield from visit(child, depth + 1)
        if kids:
            yield key, depth, subtree_of(key)

    for root in ordered(roots):
        yield from visit(root, 0)
