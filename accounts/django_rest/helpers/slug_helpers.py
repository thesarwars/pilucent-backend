"""Slug sources for `AutoSlugField(populate_from=...)`.

**The uid segment has to survive truncation, and that is the whole point of the
budget below.**

`AutoSlugField` defaults to `max_length=50` and crops whatever it is given to
fit. `f"{title}-{uid8}"` therefore loses its uid the moment the title runs long
-- "New York State Department of Taxation and Finance" is 49 characters, so the
slug came out as the bare slugified title with the uid cropped off entirely.
Once that happens the slug is a pure function of the title, and two accounts
with the same title collide.

Which matters because **`accounts_chartofaccount_slug_key` is a GLOBAL unique
constraint, not a per-company one.** Titles like that one are not a user's
invention -- they come from `agencies_chart_of_account.py`, so every company
that registers a New York tax agency gets the identical title, and after
cropping, the identical slug.

`AutoSlugField(unique=True)` does try to de-duplicate by querying for the slug
and appending `-2`, `-3`, and in a plain test it does exactly that. It cannot be
relied on here for two reasons:

* `ChartOfAccount` is under forced row-level security, so that uniqueness query
  sees only the current company's rows while the constraint it is protecting
  spans every company. It reports "free" for a slug another tenant already
  holds.
* It is a read-then-write with no lock, so two concurrent creates resolve to the
  same answer regardless of RLS.

Both are unfixable at the de-duplication layer and both disappear if the slug is
unique *by construction*. So the title is budgeted to leave room for the uid
rather than the uid being appended and hoped for.

Cropping the title rather than the uid is the right way round: the title half is
decoration for readability, and the uid half is what makes the value unique.
"""

# AutoSlugField's default max_length. Kept as a named constant because the
# budget below is only correct relative to it -- if the field ever declares its
# own max_length, this has to move with it.
SLUG_MAX_LENGTH = 50

# 8 hex characters of the uuid, plus the separator before it.
UID_SEGMENT_LENGTH = 8
TITLE_BUDGET = SLUG_MAX_LENGTH - UID_SEGMENT_LENGTH - 1  # 41


def _uid_segment(instance):
    """First block of the row's uuid.

    `uid` carries `default=uuid.uuid4`, so it is populated at instantiation and
    is already there when `populate_from` runs on an unsaved row.
    """
    return str(instance.uid).split("-")[0]


def _with_uid(text, instance):
    """`text` cropped so the uid still fits inside `SLUG_MAX_LENGTH`.

    Slugify only ever shortens what it is given -- it collapses whitespace and
    drops punctuation -- so budgeting on the raw length is conservative and the
    result cannot exceed the field.
    """
    head = (text or "").strip()[:TITLE_BUDGET]
    return f"{head}-{_uid_segment(instance)}"


def get_user_slug(instance):
    return _with_uid(instance.name, instance)


def get_chart_of_account_slug(instance):
    return _with_uid(instance.title, instance)


def get_accounting_setting_slug(instance):
    return f"accounting-setting-{_uid_segment(instance)}"
