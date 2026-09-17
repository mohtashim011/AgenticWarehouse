"""
SQLite data layer for the Agentic Warehouse MVP.

Pure standard library (sqlite3). Holds four tables:
  - items      : one row per product number, holding the live QUANTITY on hand
  - logs       : an audit trail of every scan and the multi-agent decision behind it
  - catalog    : user-managed product name -> category map (the source of truth)
  - categories : the user-managed list of category names

This mirrors the original AUTOWARE project (name, batchno, productno + product logs)
but adds a quantity-based stock model and stores the full agent trace per scan.

Stock model: scanning a code IN increments its quantity, scanning it OUT
decrements it. A product number is therefore a SKU, not a single serial number,
so the same code can be scanned many times to build up stock.
"""

import json
from datetime import datetime, timedelta, timezone

from core import dbcore

#: The GTIN check digit, borrowed from the encoder rather than reimplemented.
#:
#: There used to be a second copy of this rule further down, anchoring the
#: alternating 3/1 weights from the **left**. That gives the same answer as the
#: real rule for an even-length body and the wrong answer for an odd-length one,
#: so it agreed with the encoder on every 12-digit EAN-13 body and disagreed on
#: four fifths of the 7- and 11-digit bodies that ``_code_variants`` feeds it.
#:
#: That was not cosmetic. It is this module's *only* test of whether a dropped
#: digit was genuinely a check digit, so a wrong answer defeats the strictness
#: the whole of ``_code_variants`` exists for. Measured over 20,000 random codes
#: of barcode length: 4.87% admitted a truncation that was not one -- the
#: 09000019 -> 900001 failure this file already fixed once -- and 4.75% refused
#: a real one. Both test vectors in the self-test happened to be cases where the
#: two rules agree, which is why it survived.
#:
#: Two copies of a check-digit rule is how an encoder and a resolver silently
#: stop agreeing, exactly as two copies of a parity table would be. One copy.
from core.barcode import check_digit as _ean_check_digit
from core.barcode import is_numeric as _is_numeric

# Where the database lives, the write lock and the connection factory all belong
# to core.dbcore, so every module (inventory, users, staff, model metrics) shares
# one file and a test can repoint all of them with dbcore.set_db_path().
_lock = dbcore.lock()
_conn = dbcore.connect
now_iso = dbcore.now_iso


UNCATEGORISED = "Uncategorised"

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    code          TEXT,               -- raw scanned string (QR or barcode)
    name          TEXT NOT NULL,
    batchno       TEXT NOT NULL DEFAULT '',      -- '' when the code carried no batch
    productno     TEXT NOT NULL,
    category      TEXT,
    qty           INTEGER NOT NULL DEFAULT 0,    -- live quantity on hand for THIS batch
    status        TEXT NOT NULL DEFAULT 'in',    -- 'in' when qty > 0, else 'out'
    scanned_in_at  TEXT,
    scanned_out_at TEXT,
    -- One row per batch of a product number, so stock stays traceable to a batch.
    UNIQUE(productno, batchno)
);

CREATE TABLE IF NOT EXISTS logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    code       TEXT,
    name       TEXT,
    productno  TEXT,
    batchno    TEXT NOT NULL DEFAULT '',   -- which batch the action hit
    action     TEXT,                  -- IN | OUT | REJECT | ADJUST | UNDO
    category   TEXT,
    anomaly    INTEGER DEFAULT 0,     -- 1 if an anomaly was flagged
    undone     INTEGER NOT NULL DEFAULT 0, -- 1 once reversed, so it cannot be undone twice
    trace      TEXT                   -- JSON: full multi-agent decision trace
);

CREATE TABLE IF NOT EXISTS catalog (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT UNIQUE,
    category TEXT,
    min_qty  INTEGER NOT NULL DEFAULT 0   -- reorder level; 0 = no alert wanted
);

CREATE TABLE IF NOT EXISTS categories (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);

-- A scanned code that means an existing product but does not equal its product
-- number. Set by the user when the printed barcode differs from the QR payload.
CREATE TABLE IF NOT EXISTS aliases (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    code      TEXT UNIQUE NOT NULL,
    productno TEXT NOT NULL
);
"""

# Seed catalog derived from the real AUTOWARE product set (ONT, IPTV, cables, remotes).
# Categories the shipped classifier is trained on. Three of the six were absent
# from a fresh install, so the model could never suggest them -- and the trace
# recorded "unlike anything the model has been shown" for a prediction it was
# 90% sure of. Seeding them is what makes the shipped accuracy figure reachable.
SEED_CATEGORIES = ("Networking", "Entertainment", "Accessories",
                   "Glassware", "Coffee Mugs", "Plasticware")

SEED_CATALOG = [
    ("ONT", "Networking"),
    ("Optical Fiber Cable", "Networking"),
    ("Ethernet Cable RJ45", "Networking"),
    ("Router", "Networking"),
    ("Network Switch", "Networking"),
    ("IPTV Device", "Entertainment"),
    ("Universal Remote", "Entertainment"),
    ("Set Top Box", "Entertainment"),
    ("HDMI Cable", "Accessories"),
    ("Power Adapter", "Accessories"),
    ("Mounting Bracket", "Accessories"),
]


def _items_keyed_by_productno_only(conn):
    """True for databases still using the pre-batch UNIQUE(productno) key."""
    for idx in conn.execute("PRAGMA index_list(items)"):
        if idx["unique"]:
            cols = [r["name"] for r in conn.execute("PRAGMA index_info(%s)" % idx["name"])]
            if cols == ["productno"]:
                return True
    return False


def _migrate(conn):
    """Bring an older database up to the current schema, preserving its data."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(items)")}
    if "qty" not in cols:
        conn.execute("ALTER TABLE items ADD COLUMN qty INTEGER NOT NULL DEFAULT 0")
        # Old rows tracked one physical unit each via status; carry that across.
        conn.execute("UPDATE items SET qty = CASE WHEN status='in' THEN 1 ELSE 0 END")

    if "min_qty" not in {r["name"] for r in conn.execute("PRAGMA table_info(catalog)")}:
        conn.execute("ALTER TABLE catalog ADD COLUMN min_qty INTEGER NOT NULL DEFAULT 0")

    log_cols = {r["name"] for r in conn.execute("PRAGMA table_info(logs)")}
    if "batchno" not in log_cols:
        conn.execute("ALTER TABLE logs ADD COLUMN batchno TEXT NOT NULL DEFAULT ''")
    # Who performed the action. Left NULL for anything logged before sign-in
    # existed — the audit agent reports those separately rather than pretending
    # they were attributable.
    if "user_id" not in log_cols:
        conn.execute("ALTER TABLE logs ADD COLUMN user_id INTEGER")
    if "username" not in log_cols:
        conn.execute("ALTER TABLE logs ADD COLUMN username TEXT NOT NULL DEFAULT ''")
    if "undone" not in log_cols:
        # Older entries predate undo; mark them as already settled so a stale
        # scan from a previous session cannot be reversed out of nowhere.
        conn.execute("ALTER TABLE logs ADD COLUMN undone INTEGER NOT NULL DEFAULT 0")
        conn.execute("UPDATE logs SET undone = 1")

    # Re-key items by (productno, batchno) so each batch is tracked separately.
    # SQLite cannot drop an inline UNIQUE constraint, so the table is rebuilt.
    if _items_keyed_by_productno_only(conn):
        conn.executescript("""
            CREATE TABLE items_new (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                code          TEXT,
                name          TEXT NOT NULL,
                batchno       TEXT NOT NULL DEFAULT '',
                productno     TEXT NOT NULL,
                category      TEXT,
                qty           INTEGER NOT NULL DEFAULT 0,
                status        TEXT NOT NULL DEFAULT 'in',
                scanned_in_at  TEXT,
                scanned_out_at TEXT,
                UNIQUE(productno, batchno)
            );
            -- COALESCE: a NULL batchno would defeat the UNIQUE key, since SQLite
            -- treats every NULL as distinct.
            INSERT INTO items_new
                (code, name, batchno, productno, category, qty, status,
                 scanned_in_at, scanned_out_at)
            SELECT code, name, COALESCE(batchno, ''), productno, category, qty,
                   status, scanned_in_at, scanned_out_at
              FROM items;
            DROP TABLE items;
            ALTER TABLE items_new RENAME TO items;
        """)


def init_db():
    dbcore.ensure_dir()
    with _lock, _conn() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        # Seed the catalog only once.
        count = conn.execute("SELECT COUNT(*) AS c FROM catalog").fetchone()["c"]
        if count == 0:
            conn.executemany(
                "INSERT OR IGNORE INTO catalog(name, category) VALUES (?, ?)",
                SEED_CATALOG,
            )
        # Seed the category list from the catalog, plus the fallback bucket.
        seeded = {c for _, c in SEED_CATALOG} | set(SEED_CATEGORIES) | {UNCATEGORISED}
        # Any category already referenced by the catalog must exist in the list too.
        for r in conn.execute("SELECT DISTINCT category FROM catalog WHERE category IS NOT NULL"):
            seeded.add(r["category"])
        conn.executemany(
            "INSERT OR IGNORE INTO categories(name) VALUES (?)",
            [(c,) for c in sorted(seeded)],
        )


# ----------------------------------------------------------------------------
# Catalog
# ----------------------------------------------------------------------------
def catalog_rows():
    with _lock, _conn() as conn:
        return [dict(r) for r in conn.execute("SELECT name, category FROM catalog ORDER BY name")]


def catalog_lookup(name):
    """The user-assigned category for a product name, or None if never assigned.

    Matching is case-insensitive so "ont" and "ONT" resolve to the same product.
    """
    with _lock, _conn() as conn:
        row = conn.execute(
            "SELECT category FROM catalog WHERE lower(name) = lower(?)", (name,)
        ).fetchone()
        return row["category"] if row else None


# ----------------------------------------------------------------------------
# Categories (user-managed)
# ----------------------------------------------------------------------------
def categories_list():
    """Every category with how many catalogued products and how many units it holds."""
    with _lock, _conn() as conn:
        rows = conn.execute(
            """SELECT c.name AS name,
                      (SELECT COUNT(*) FROM catalog k WHERE k.category = c.name) AS products,
                      (SELECT COALESCE(SUM(i.qty), 0) FROM items i
                        WHERE i.category = c.name AND i.qty > 0) AS units
                 FROM categories c ORDER BY c.name"""
        ).fetchall()
        return [dict(r) for r in rows]


def category_names():
    with _lock, _conn() as conn:
        return [r["name"] for r in conn.execute("SELECT name FROM categories ORDER BY name")]


def category_add(name):
    name = (name or "").strip()
    if not name:
        return False, "Category name cannot be empty."
    with _lock, _conn() as conn:
        exists = conn.execute(
            "SELECT 1 FROM categories WHERE lower(name) = lower(?)", (name,)
        ).fetchone()
        if exists:
            return False, "Category '%s' already exists." % name
        conn.execute("INSERT INTO categories(name) VALUES (?)", (name,))
    return True, "Category '%s' added." % name


def category_rename(old, new):
    old, new = (old or "").strip(), (new or "").strip()
    if not new:
        return False, "New category name cannot be empty."
    if old == UNCATEGORISED:
        return False, "The '%s' bucket cannot be renamed." % UNCATEGORISED
    with _lock, _conn() as conn:
        if not conn.execute("SELECT 1 FROM categories WHERE name = ?", (old,)).fetchone():
            return False, "Category '%s' not found." % old
        clash = conn.execute(
            "SELECT 1 FROM categories WHERE lower(name) = lower(?) AND name <> ?", (new, old)
        ).fetchone()
        if clash:
            return False, "Category '%s' already exists." % new
        # Rename everywhere it is referenced so nothing is orphaned.
        conn.execute("UPDATE categories SET name = ? WHERE name = ?", (new, old))
        conn.execute("UPDATE catalog SET category = ? WHERE category = ?", (new, old))
        conn.execute("UPDATE items SET category = ? WHERE category = ?", (new, old))
    return True, "Renamed '%s' to '%s'." % (old, new)


def category_delete(name):
    """Delete a category; anything filed under it falls back to Uncategorised."""
    name = (name or "").strip()
    if name == UNCATEGORISED:
        return False, "The '%s' bucket cannot be deleted." % UNCATEGORISED
    with _lock, _conn() as conn:
        if not conn.execute("SELECT 1 FROM categories WHERE name = ?", (name,)).fetchone():
            return False, "Category '%s' not found." % name
        conn.execute("DELETE FROM categories WHERE name = ?", (name,))
        conn.execute("UPDATE catalog SET category = ? WHERE category = ?", (UNCATEGORISED, name))
        conn.execute("UPDATE items SET category = ? WHERE category = ?", (UNCATEGORISED, name))
    return True, "Deleted '%s'; its products moved to %s." % (name, UNCATEGORISED)


def assign_category(product_name, category):
    """Map a product name to a category — the user's decision, remembered for
    every future scan and applied to stock already on hand."""
    product_name = (product_name or "").strip()
    category = (category or "").strip()
    if not product_name:
        return False, "Product name cannot be empty."
    with _lock, _conn() as conn:
        if not conn.execute("SELECT 1 FROM categories WHERE name = ?", (category,)).fetchone():
            return False, "Category '%s' does not exist." % category
        conn.execute(
            """INSERT INTO catalog(name, category) VALUES (?, ?)
               ON CONFLICT(name) DO UPDATE SET category = excluded.category""",
            (product_name, category),
        )
        # Re-file stock already recorded under the old category.
        conn.execute(
            "UPDATE items SET category = ? WHERE lower(name) = lower(?)",
            (category, product_name),
        )
    return True, "'%s' filed under %s." % (product_name, category)


def uncategorised_products():
    """Product names currently in stock with no user-assigned category."""
    with _lock, _conn() as conn:
        rows = conn.execute(
            """SELECT i.name AS name, SUM(i.qty) AS qty
                 FROM items i
                WHERE i.qty > 0
                  AND NOT EXISTS (SELECT 1 FROM catalog k
                                   WHERE lower(k.name) = lower(i.name)
                                     AND k.category <> ?)
             GROUP BY lower(i.name) ORDER BY i.name""",
            (UNCATEGORISED,),
        ).fetchall()
        return [dict(r) for r in rows]


# ----------------------------------------------------------------------------
# Items (the live inventory state machine)
# ----------------------------------------------------------------------------
UNKNOWN_NAME = "Unknown Item"


# The GTIN check digit comes from core.barcode -- see the import at the top of
# this module for why there is no second copy of the rule here.


def _code_variants(code):
    """Other spellings of the same retail barcode.

    A QR payload often carries the product number WITHOUT its check digit
    (789076542345) while the printed EAN-13 carries it (7890765423458). Same
    product, different strings — so an exact lookup misses. EAN-13 is also a
    UPC-A with a leading zero. Only numeric codes of barcode length qualify, so
    ordinary product numbers are never loosely matched.
    """
    c = (code or "").strip()
    # is_numeric, not str.isdigit: the latter is True for superscripts that
    # int() then refuses, and this guard is all that stands between a pasted
    # footnote marker and a ValueError raised from inside a database write.
    if not _is_numeric(c) or len(c) not in (8, 11, 12, 13, 14):
        return []
    out = set()

    # Adding a check digit is safe: it can only ever produce the one code this
    # body legitimately expands to.
    out.add(c + _ean_check_digit(c))

    # Removing one is NOT safe on its own, and this is where stock used to land
    # on the wrong product. Chopping the last digit off any numeric code of
    # barcode length yields a shorter number that may belong to something else
    # entirely -- 09000019 became 900001, a real and unrelated product, and the
    # log then recorded the *resolved* number so nothing looked wrong afterwards.
    # A truncation is only a truncation when the digit removed is genuinely the
    # check digit for what remains.
    if len(c) > 1 and _ean_check_digit(c[:-1]) == c[-1]:
        out.add(c[:-1])

    if c.startswith("0"):
        out.add(c[1:])                   # EAN-13 -> UPC-A, same digits
        if len(c) > 2 and _ean_check_digit(c[1:-1]) == c[-1]:
            out.add(c[1:-1])
    else:
        out.add("0" + c)                 # UPC-A -> EAN-13

    out.discard(c)
    return sorted(out)


def resolve_productno(productno):
    """Map a scanned code to the product number actually held in stock.

    Returns ``(canonical, how)`` or ``(None, None)``. Tried in order: exact,
    a link the user set, then a barcode variant.
    """
    productno = (productno or "").strip()
    if not productno:
        return None, None
    with _lock, _conn() as conn:
        def held(pn):
            return conn.execute(
                "SELECT 1 FROM items WHERE productno = ? AND name <> ?",
                (pn, UNKNOWN_NAME),
            ).fetchone() is not None

        if held(productno):
            return productno, "exact"
        row = conn.execute(
            "SELECT productno FROM aliases WHERE code = ?", (productno,)
        ).fetchone()
        if row and held(row["productno"]):
            return row["productno"], "linked by you"
        for v in _code_variants(productno):
            if held(v):
                return v, "barcode check digit"
    return None, None


def link_code(code, productno, actor=None):
    """Point a scanned code at an existing product number."""
    code = (code or "").strip()
    productno = (productno or "").strip()
    if not code or not productno:
        return False, "Both a code and a product are required."
    if code == productno:
        return False, "That code is already the product number."
    with _lock, _conn() as conn:
        target = conn.execute(
            "SELECT name FROM items WHERE productno = ? AND name <> ? LIMIT 1",
            (productno, UNKNOWN_NAME),
        ).fetchone()
        if target is None:
            return False, "No known product with number %s." % productno
        conn.execute(
            """INSERT INTO aliases(code, productno) VALUES (?, ?)
               ON CONFLICT(code) DO UPDATE SET productno = excluded.productno""",
            (code, productno),
        )
        # Fold any stock this code accumulated while it was unrecognised into
        # the product it actually is, so nothing is stranded under "Unknown".
        stray = conn.execute(
            "SELECT batchno, qty FROM items WHERE productno = ? AND name = ?",
            (code, UNKNOWN_NAME),
        ).fetchall()
        moved = 0
        for s in stray:
            if s["qty"] > 0:
                conn.execute(
                    """INSERT INTO items(code, name, batchno, productno, category, qty,
                                         status, scanned_in_at)
                       SELECT ?, name, ?, ?, category, ?, 'in', ?
                         FROM items WHERE productno = ? AND name <> ? LIMIT 1
                       ON CONFLICT(productno, batchno) DO UPDATE SET
                           qty = items.qty + excluded.qty, status = 'in'""",
                    (code, s["batchno"], productno, s["qty"], now_iso(),
                     productno, UNKNOWN_NAME),
                )
                moved += s["qty"]
        conn.execute(
            "DELETE FROM items WHERE productno = ? AND name = ?", (code, UNKNOWN_NAME)
        )
        note = "Code %s now points to %s (%s)." % (code, target["name"], productno)
        if moved:
            note += " Moved %d unit(s) across." % moved
        conn.execute(
            """INSERT INTO logs(ts, code, name, productno, batchno, action, category,
                                anomaly, undone, trace, user_id, username)
               VALUES (?, ?, ?, ?, '', 'ADJUST', ?, 0, 1, ?, ?, ?)""",
            (now_iso(), code, target["name"], productno, UNCATEGORISED,
             json.dumps([{"agent": "Manual correction", "notes": [note]}]),
             (actor or {}).get("id"), (actor or {}).get("username", "")),
        )
    return True, note


def alias_codes():
    """Every scanned code the user has linked to a product number.

    A product is normally reachable by more than one code — the QR payload, the
    printed EAN-13, and sometimes a supplier's own Code 128 label. All of them
    must resolve to the same stock record, which is what this set is for.
    """
    with _lock, _conn() as conn:
        return {r["code"] for r in conn.execute("SELECT code FROM aliases")}


def aliases_for(productno):
    """The alternative codes registered against one product number."""
    with _lock, _conn() as conn:
        return [r["code"] for r in conn.execute(
            "SELECT code FROM aliases WHERE productno = ? ORDER BY code", (productno,))]


def list_aliases():
    """Every code link, with the product it points at — the code registry view."""
    with _lock, _conn() as conn:
        rows = conn.execute(
            """SELECT a.code, a.productno,
                      (SELECT name FROM items i WHERE i.productno = a.productno
                        AND i.name <> ? LIMIT 1) AS name
                 FROM aliases a ORDER BY a.productno, a.code""",
            (UNKNOWN_NAME,),
        ).fetchall()
        return [dict(r) for r in rows]


def unlink_code(code):
    """Remove a code link. The stock it accumulated stays where it was folded in."""
    code = (code or "").strip()
    with _lock, _conn() as conn:
        cur = conn.execute("DELETE FROM aliases WHERE code = ?", (code,))
        if cur.rowcount == 0:
            return False, "No link registered for code %s." % code
    return True, "Link for code %s removed." % code


def all_product_codes():
    """Product number -> every code that resolves to it, including variants.

    This is what lets the label screen print a QR and a barcode for the same
    product and guarantee that scanning either one lands on the same record.
    """
    out = {}
    with _lock, _conn() as conn:
        for r in conn.execute(
            "SELECT DISTINCT productno, name FROM items WHERE name <> ?", (UNKNOWN_NAME,)
        ):
            pn = r["productno"]
            codes = {pn}
            codes.update(_code_variants(pn))
            out[pn] = {"name": r["name"], "codes": sorted(codes), "linked": []}
        for r in conn.execute("SELECT code, productno FROM aliases"):
            if r["productno"] in out:
                out[r["productno"]]["linked"].append(r["code"])
    return out


def lookup_product(productno):
    """What we already know about a product number, or None if never seen.

    A plain barcode carries only a product number — no name and no batch. This
    is how such a scan is matched to the product it actually is, instead of
    landing in stock as a second, nameless entry.

    Preference: a batch that still holds stock, then the largest, then the most
    recent. Rows only ever recorded as unknown teach us nothing, so they are
    excluded.
    """
    with _lock, _conn() as conn:
        row = conn.execute(
            """SELECT name, category, batchno, qty FROM items
                WHERE productno = ? AND name <> ?
             ORDER BY (qty > 0) DESC, qty DESC, id DESC LIMIT 1""",
            (productno, UNKNOWN_NAME),
        ).fetchone()
        return dict(row) if row else None


def rename_product(productno, new_name, actor=None):
    """Give a real name to a product only ever seen as a bare barcode.

    Once named, every future scan of that barcode matches it by name — so it
    picks up the category and stops being 'unknown'.
    """
    new_name = (new_name or "").strip()
    if not new_name:
        return False, "Product name cannot be empty."
    if new_name == UNKNOWN_NAME:
        return False, "Choose a real product name."
    with _lock, _conn() as conn:
        rows = conn.execute(
            "SELECT id, name FROM items WHERE productno = ?", (productno,)
        ).fetchall()
        if not rows:
            return False, "No stock record for product no. %s." % productno
        old = rows[0]["name"]
        conn.execute("UPDATE items SET name = ? WHERE productno = ?", (new_name, productno))
        note = "Product no. %s named '%s' (was '%s')." % (productno, new_name, old)
        conn.execute(
            """INSERT INTO logs(ts, code, name, productno, batchno, action, category,
                                anomaly, undone, trace, user_id, username)
               VALUES (?, ?, ?, ?, '', 'ADJUST', ?, 0, 1, ?, ?, ?)""",
            (now_iso(), productno, new_name, productno, UNCATEGORISED,
             json.dumps([{"agent": "Manual correction", "notes": [note]}]),
             (actor or {}).get("id"), (actor or {}).get("username", "")),
        )
    return True, note


def get_item(productno):
    with _lock, _conn() as conn:
        row = conn.execute("SELECT * FROM items WHERE productno = ?", (productno,)).fetchone()
        return dict(row) if row else None


def _product_total(conn, productno):
    """Units on hand for a product number, summed across all of its batches."""
    return conn.execute(
        "SELECT COALESCE(SUM(qty), 0) AS c FROM items WHERE productno = ? AND qty > 0",
        (productno,),
    ).fetchone()["c"]


def product_total(productno):
    with _lock, _conn() as conn:
        return _product_total(conn, productno)


def stock_in(name, batchno, productno, category, code):
    """Add one unit to this product number's batch. Returns the updated row,
    with ``total`` covering every batch of the product number.

    Scanning the same code repeatedly builds up quantity instead of being
    rejected as a duplicate.
    """
    batchno = (batchno or "").strip()
    with _lock, _conn() as conn:
        conn.execute(
            """INSERT INTO items(code, name, batchno, productno, category, qty, status, scanned_in_at)
               VALUES (?, ?, ?, ?, ?, 1, 'in', ?)
               ON CONFLICT(productno, batchno) DO UPDATE SET
                   qty = items.qty + 1, status = 'in',
                   -- A nameless scan (plain barcode) must never overwrite a
                   -- product we already know the name of.
                   name = CASE WHEN excluded.name = 'Unknown Item'
                               THEN items.name ELSE excluded.name END,
                   category = CASE WHEN excluded.name = 'Unknown Item'
                                   THEN items.category ELSE excluded.category END,
                   code=excluded.code,
                   scanned_in_at=excluded.scanned_in_at""",
            (code, name, batchno, productno, category, now_iso()),
        )
        row = conn.execute(
            "SELECT * FROM items WHERE productno = ? AND batchno = ?", (productno, batchno)
        ).fetchone()
        out = dict(row)
        out["total"] = _product_total(conn, productno)
        return out


def stock_out(productno, batchno=""):
    """Remove one unit. Returns the updated row (with ``total``), or None if
    there is nothing on hand.

    The scanned batch is used when it has stock. Otherwise the oldest batch of
    that product number still holding stock is drawn down (FIFO) — this is what
    lets a plain barcode, which carries no batch, still check stock out.
    """
    batchno = (batchno or "").strip()
    with _lock, _conn() as conn:
        row = conn.execute(
            "SELECT * FROM items WHERE productno = ? AND batchno = ? AND qty > 0",
            (productno, batchno),
        ).fetchone()
        if row is None:
            row = conn.execute(
                """SELECT * FROM items WHERE productno = ? AND qty > 0
                   ORDER BY scanned_in_at, id LIMIT 1""",
                (productno,),
            ).fetchone()
        if row is None:
            return None
        conn.execute(
            """UPDATE items
                  SET qty = qty - 1,
                      scanned_out_at = ?,
                      status = CASE WHEN qty - 1 > 0 THEN 'in' ELSE 'out' END
                WHERE id = ?""",
            (now_iso(), row["id"]),
        )
        updated = dict(conn.execute("SELECT * FROM items WHERE id = ?", (row["id"],)).fetchone())
        updated["total"] = _product_total(conn, productno)
        return updated


def inventory_summary():
    """Aggregate live stock grouped by product name + category, with the batch
    breakdown and reorder level attached to each product."""
    with _lock, _conn() as conn:
        rows = conn.execute(
            """SELECT i.name AS name, i.category AS category, SUM(i.qty) AS qty,
                      COALESCE(MAX(k.min_qty), 0) AS min_qty
               FROM items i
               LEFT JOIN catalog k ON lower(k.name) = lower(i.name)
               WHERE i.qty > 0
               GROUP BY i.name, i.category ORDER BY qty DESC, i.name"""
        ).fetchall()
        out = []
        for r in rows:
            row = dict(r)
            batches = conn.execute(
                """SELECT batchno, productno, qty FROM items
                   WHERE name = ? AND qty > 0 ORDER BY batchno, productno""",
                (row["name"],),
            ).fetchall()
            row["batches"] = [dict(b) for b in batches]
            row["low"] = row["min_qty"] > 0 and row["qty"] <= row["min_qty"]
            out.append(row)
        total = conn.execute(
            "SELECT COALESCE(SUM(qty), 0) AS c FROM items WHERE qty > 0"
        ).fetchone()["c"]
        return {"total": total, "rows": out}


# ----------------------------------------------------------------------------
# Reorder levels / low stock
# ----------------------------------------------------------------------------
def set_min_qty(product_name, min_qty):
    """Set a product's reorder level. Creates a catalog entry if needed."""
    product_name = (product_name or "").strip()
    if not product_name:
        return False, "Product name cannot be empty."
    try:
        min_qty = int(min_qty)
    except (TypeError, ValueError):
        return False, "Reorder level must be a whole number."
    if min_qty < 0:
        return False, "Reorder level cannot be negative."
    with _lock, _conn() as conn:
        conn.execute(
            """INSERT INTO catalog(name, category, min_qty) VALUES (?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET min_qty = excluded.min_qty""",
            (product_name, UNCATEGORISED, min_qty),
        )
    if min_qty == 0:
        return True, "Reorder alert turned off for '%s'." % product_name
    return True, "'%s' will alert at %d or fewer." % (product_name, min_qty)


def min_qty_for(product_name):
    """The reorder level set for a product name; 0 means no alert."""
    with _lock, _conn() as conn:
        row = conn.execute(
            "SELECT min_qty FROM catalog WHERE lower(name) = lower(?)", (product_name,)
        ).fetchone()
        return row["min_qty"] if row else 0


def low_stock():
    """Products at or below their reorder level. Only products with a level set
    (min_qty > 0) can raise an alert."""
    with _lock, _conn() as conn:
        rows = conn.execute(
            """SELECT k.name AS name, k.category AS category, k.min_qty AS min_qty,
                      COALESCE((SELECT SUM(i.qty) FROM items i
                                 WHERE lower(i.name) = lower(k.name) AND i.qty > 0), 0) AS qty
                 FROM catalog k
                WHERE k.min_qty > 0
             ORDER BY k.name"""
        ).fetchall()
    alerts = []
    for r in rows:
        row = dict(r)
        if row["qty"] > row["min_qty"]:
            continue
        row["status"] = "OUT" if row["qty"] == 0 else "LOW"
        alerts.append(row)
    # Most urgent first: out of stock, then furthest below its level.
    alerts.sort(key=lambda a: (a["qty"] - a["min_qty"], a["qty"]))
    return alerts


# ----------------------------------------------------------------------------
# Logs
# ----------------------------------------------------------------------------
def add_log(code, name, productno, action, category, anomaly, trace, batchno="",
            actor=None):
    """Record one action in the audit trail.

    ``actor`` is the signed-in staff member. Both the id and the username are
    stored: the id links to the account, and the username survives the account
    being deleted, so the trail can still say who did it.
    """
    with _lock, _conn() as conn:
        cur = conn.execute(
            """INSERT INTO logs(ts, code, name, productno, batchno, action, category,
                                anomaly, trace, user_id, username)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (now_iso(), code, name, productno, batchno or "", action, category,
             1 if anomaly else 0, json.dumps(trace),
             (actor or {}).get("id"), (actor or {}).get("username", "")),
        )
        # The id lets the interface undo THIS scan rather than whichever one
        # happens to be newest when the button is pressed.
        return cur.lastrowid


def recent_logs(limit=25):
    with _lock, _conn() as conn:
        rows = conn.execute(
            """SELECT id, ts, code, name, productno, batchno, action, category, anomaly, undone, username
                 FROM logs ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


# ----------------------------------------------------------------------------
# Manual corrections + undo
# ----------------------------------------------------------------------------
def adjust_stock(productno, batchno, new_qty, actor=None):
    """Set a batch's quantity directly, for correcting a miscount.

    Recorded in the audit trail as an ADJUST so a manual override is never
    mistaken for a scan.
    """
    batchno = (batchno or "").strip()
    try:
        new_qty = int(new_qty)
    except (TypeError, ValueError):
        return False, "Quantity must be a whole number.", None
    if new_qty < 0:
        return False, "Quantity cannot be negative.", None

    with _lock, _conn() as conn:
        row = conn.execute(
            "SELECT * FROM items WHERE productno = ? AND batchno = ?", (productno, batchno)
        ).fetchone()
        if row is None:
            return False, "No stock record for %s in that batch." % productno, None
        old = row["qty"]
        if old == new_qty:
            return True, "Quantity of %s is already %d." % (productno, new_qty), dict(row)
        conn.execute(
            "UPDATE items SET qty = ?, status = ? WHERE id = ?",
            (new_qty, "in" if new_qty > 0 else "out", row["id"]),
        )
        label = " (batch %s)" % batchno if batchno else ""
        note = "Manual correction: %s%s changed from %d to %d." % (
            row["name"], label, old, new_qty)
        conn.execute(
            """INSERT INTO logs(ts, code, name, productno, batchno, action, category,
                                anomaly, undone, trace, user_id, username)
               VALUES (?, ?, ?, ?, ?, 'ADJUST', ?, 0, 1, ?, ?, ?)""",
            (now_iso(), row["code"], row["name"], productno, batchno, row["category"],
             json.dumps([{"agent": "Manual correction", "notes": [note],
                          "qty": new_qty}]),
             (actor or {}).get("id"), (actor or {}).get("username", "")),
        )
        updated = dict(conn.execute("SELECT * FROM items WHERE id = ?", (row["id"],)).fetchone())
    return True, note, updated


def last_undoable():
    """The most recent scan that can still be reversed, or None."""
    with _lock, _conn() as conn:
        row = conn.execute(
            """SELECT id, ts, name, productno, batchno, action FROM logs
                WHERE action IN ('IN', 'OUT') AND undone = 0
             ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        return dict(row) if row else None


def undo_last(log_id=None, actor=None):
    """Reverse a scan.

    ``log_id`` names the scan to reverse; without it the most recent reversible
    one is used. Naming it matters: the interface lets someone open an earlier
    scan and press Undo, and reversing whatever happens to be newest instead
    silently corrects the wrong product.

    Only scans are undoable — a manual ADJUST is already a deliberate override,
    and reversing one would just be another correction.
    """
    with _lock, _conn() as conn:
        if log_id is not None:
            log = conn.execute(
                """SELECT * FROM logs
                    WHERE id = ? AND action IN ('IN', 'OUT') AND undone = 0""",
                (log_id,)).fetchone()
            if log is None:
                return False, ("That scan has already been reversed, or is not "
                               "something that can be."), None
        else:
            log = conn.execute(
                """SELECT * FROM logs WHERE action IN ('IN', 'OUT') AND undone = 0
                 ORDER BY id DESC LIMIT 1"""
            ).fetchone()
        if log is None:
            return False, "Nothing to undo.", None

        productno, batchno, action = log["productno"], log["batchno"] or "", log["action"]
        item = conn.execute(
            "SELECT * FROM items WHERE productno = ? AND batchno = ?", (productno, batchno)
        ).fetchone()
        if item is None:
            return False, "The stock record for %s no longer exists." % productno, None

        if action == "IN":
            # Refuse rather than drive the count negative: those units are gone.
            if item["qty"] <= 0:
                return False, (
                    "Cannot undo that IN — %s has none of that batch left, so the "
                    "unit has already been taken out." % log["name"]), None
            new_qty = item["qty"] - 1
        else:
            new_qty = item["qty"] + 1

        conn.execute(
            "UPDATE items SET qty = ?, status = ? WHERE id = ?",
            (new_qty, "in" if new_qty > 0 else "out", item["id"]),
        )
        conn.execute("UPDATE logs SET undone = 1 WHERE id = ?", (log["id"],))

        label = " (batch %s)" % batchno if batchno else ""
        note = "Undid %s of %s%s. Quantity is now %d." % (
            action, log["name"], label, new_qty)
        conn.execute(
            """INSERT INTO logs(ts, code, name, productno, batchno, action, category,
                                anomaly, undone, trace, user_id, username)
               VALUES (?, ?, ?, ?, ?, 'UNDO', ?, 0, 1, ?, ?, ?)""",
            (now_iso(), log["code"], log["name"], productno, batchno, log["category"],
             json.dumps([{"agent": "Undo", "notes": [note]}]),
             (actor or {}).get("id"), (actor or {}).get("username", "")),
        )
    return True, note, {"productno": productno, "batchno": batchno, "qty": new_qty}


# ----------------------------------------------------------------------------
# Chart data
# ----------------------------------------------------------------------------
def category_totals():
    """Units on hand per category — the stock-by-category chart."""
    with _lock, _conn() as conn:
        rows = conn.execute(
            """SELECT COALESCE(NULLIF(category, ''), ?) AS category, SUM(qty) AS qty
                 FROM items WHERE qty > 0
             GROUP BY COALESCE(NULLIF(category, ''), ?)
             ORDER BY qty DESC, category""",
            (UNCATEGORISED, UNCATEGORISED),
        ).fetchall()
        return [dict(r) for r in rows]


def activity_daily(days=7):
    """IN and OUT scan counts per day for the last N days, zero-filled.

    Reversed scans are excluded — the chart should show what actually happened
    to stock, not actions that were taken back.
    """
    with _lock, _conn() as conn:
        rows = conn.execute(
            """SELECT substr(ts, 1, 10) AS day,
                      SUM(CASE WHEN action = 'IN'  THEN 1 ELSE 0 END) AS ins,
                      SUM(CASE WHEN action = 'OUT' THEN 1 ELSE 0 END) AS outs
                 FROM logs
                WHERE action IN ('IN', 'OUT') AND undone = 0
             GROUP BY day""",
        ).fetchall()
    by_day = {r["day"]: r for r in rows}
    today = datetime.now(timezone.utc).date()
    series = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        r = by_day.get(d)
        series.append({"day": d, "in": r["ins"] if r else 0, "out": r["outs"] if r else 0})
    return series


# ----------------------------------------------------------------------------
# Product detail
# ----------------------------------------------------------------------------
def product_detail(productno):
    """Everything known about one product number.

    Gathered in a single call because the detail page needs all of it at once,
    and five round trips would let the page render in an inconsistent state —
    quantities from one moment beside a history from another.
    """
    with _lock, _conn() as conn:
        batches = conn.execute(
            """SELECT id, batchno, qty, status, code, category, name,
                      scanned_in_at, scanned_out_at
                 FROM items WHERE productno = ? ORDER BY batchno""",
            (productno,),
        ).fetchall()
        if not batches:
            return None

        rows = [dict(b) for b in batches]
        # A named row wins: a product scanned once as a bare barcode has an
        # 'Unknown Item' row that must not decide what the product is called.
        named = next((r for r in rows if r["name"] != UNKNOWN_NAME), rows[0])
        name = named["name"]
        category = named["category"]

        total = sum(r["qty"] for r in rows if r["qty"] > 0)

        cat = conn.execute(
            "SELECT category, min_qty FROM catalog WHERE lower(name) = lower(?)", (name,)
        ).fetchone()

        history = [dict(r) for r in conn.execute(
            """SELECT ts, action, batchno, category, anomaly, undone, username, code
                 FROM logs WHERE productno = ? ORDER BY id DESC LIMIT 200""",
            (productno,),
        )]

        movement = [dict(r) for r in conn.execute(
            """SELECT substr(ts, 1, 10) AS day,
                      SUM(CASE WHEN action = 'IN'  THEN 1 ELSE 0 END) AS ins,
                      SUM(CASE WHEN action = 'OUT' THEN 1 ELSE 0 END) AS outs
                 FROM logs
                WHERE productno = ? AND action IN ('IN','OUT') AND undone = 0
             GROUP BY day ORDER BY day""",
            (productno,),
        )]

        aliases = [r["code"] for r in conn.execute(
            "SELECT code FROM aliases WHERE productno = ? ORDER BY code", (productno,))]

        first_seen = conn.execute(
            "SELECT MIN(ts) AS t FROM logs WHERE productno = ?", (productno,)
        ).fetchone()["t"]
        last_seen = conn.execute(
            "SELECT MAX(ts) AS t FROM logs WHERE productno = ?", (productno,)
        ).fetchone()["t"]

        handlers = [dict(r) for r in conn.execute(
            """SELECT username, COUNT(*) AS moves FROM logs
                WHERE productno = ? AND username <> '' AND action IN ('IN','OUT')
             GROUP BY username ORDER BY moves DESC LIMIT 5""",
            (productno,),
        )]

    min_qty = cat["min_qty"] if cat else 0
    return {
        "productno": productno,
        "name": name,
        "category": (cat["category"] if cat else None) or category or UNCATEGORISED,
        "min_qty": min_qty,
        "qty": total,
        "low": min_qty > 0 and total <= min_qty,
        "batches": [
            {"batchno": r["batchno"], "qty": r["qty"], "status": r["status"],
             "scanned_in_at": r["scanned_in_at"], "scanned_out_at": r["scanned_out_at"]}
            for r in rows
        ],
        "codes": sorted({productno} | set(_code_variants(productno))),
        "linked_codes": aliases,
        "history": history,
        "movement": movement,
        "handlers": handlers,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "totals": {
            "in": sum(1 for h in history if h["action"] == "IN" and not h["undone"]),
            "out": sum(1 for h in history if h["action"] == "OUT" and not h["undone"]),
            "adjust": sum(1 for h in history if h["action"] == "ADJUST"),
            "reject": sum(1 for h in history if h["action"] == "REJECT"),
            "anomalies": sum(1 for h in history if h["anomaly"]),
        },
    }


def list_products():
    """Every product number held, with its name and quantity — the index the
    detail pages are reached from."""
    with _lock, _conn() as conn:
        rows = conn.execute(
            """SELECT productno,
                      MIN(CASE WHEN name <> ? THEN name END) AS named,
                      MAX(name) AS any_name,
                      SUM(CASE WHEN qty > 0 THEN qty ELSE 0 END) AS qty,
                      COUNT(*) AS batches
                 FROM items GROUP BY productno ORDER BY qty DESC""",
            (UNKNOWN_NAME,),
        ).fetchall()
    return [{"productno": r["productno"], "name": r["named"] or r["any_name"],
             "qty": r["qty"], "batches": r["batches"]} for r in rows]


# ----------------------------------------------------------------------------
# Manual product management
# ----------------------------------------------------------------------------
def create_product(name, productno, batchno="", qty=0, category=None, min_qty=0, actor=None):
    """Add a product by hand, without scanning it.

    Needed when stock is received before its labels are, and for setting a
    catalogue up in advance. The opening quantity is recorded as an ADJUST, not
    as a scan, so the audit trail never claims something was scanned when it
    was typed.
    """
    name = (name or "").strip()
    productno = (productno or "").strip()
    batchno = (batchno or "").strip()
    if not name:
        return False, "A product name is required.", None
    if name == UNKNOWN_NAME:
        return False, "Choose a real product name.", None
    if not productno:
        return False, "A product number is required.", None
    try:
        qty = int(qty)
        min_qty = int(min_qty)
    except (TypeError, ValueError):
        return False, "Quantity and reorder level must be whole numbers.", None
    if qty < 0 or min_qty < 0:
        return False, "Quantity and reorder level cannot be negative.", None

    category = (category or UNCATEGORISED).strip() or UNCATEGORISED

    with _lock, _conn() as conn:
        clash = conn.execute(
            "SELECT name FROM items WHERE productno = ? AND batchno = ?",
            (productno, batchno),
        ).fetchone()
        if clash:
            return False, ("Product no. %s already exists%s. Edit it instead."
                           % (productno, " in batch " + batchno if batchno else "")), None
        if not conn.execute(
                "SELECT 1 FROM categories WHERE name = ?", (category,)).fetchone():
            return False, "Category '%s' does not exist." % category, None

        conn.execute(
            """INSERT INTO items(code, name, batchno, productno, category, qty, status,
                                 scanned_in_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (productno, name, batchno, productno, category, qty,
             "in" if qty > 0 else "out", now_iso()),
        )
        conn.execute(
            """INSERT INTO catalog(name, category, min_qty) VALUES (?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                   category = CASE WHEN catalog.category = ? THEN excluded.category
                                   ELSE catalog.category END,
                   min_qty = excluded.min_qty""",
            (name, category, min_qty, UNCATEGORISED),
        )
        note = ("Product '%s' (%s) created by hand with an opening quantity of %d."
                % (name, productno, qty))
        conn.execute(
            """INSERT INTO logs(ts, code, name, productno, batchno, action, category,
                                anomaly, undone, trace, user_id, username)
               VALUES (?, ?, ?, ?, ?, 'ADJUST', ?, 0, 1, ?, ?, ?)""",
            (now_iso(), productno, name, productno, batchno, category,
             json.dumps([{"agent": "Manual entry", "notes": [note], "qty": qty}]),
             (actor or {}).get("id"), (actor or {}).get("username", "")),
        )
    return True, note, product_detail(productno)


def update_product(productno, name=None, category=None, min_qty=None, actor=None):
    """Rename a product, refile it, or change its reorder level."""
    with _lock, _conn() as conn:
        row = conn.execute(
            "SELECT name FROM items WHERE productno = ? AND name <> ? LIMIT 1",
            (productno, UNKNOWN_NAME),
        ).fetchone() or conn.execute(
            "SELECT name FROM items WHERE productno = ? LIMIT 1", (productno,)).fetchone()
        if row is None:
            return False, "No product with number %s." % productno
        old_name = row["name"]
        changes = []

        if name is not None:
            name = name.strip()
            if not name or name == UNKNOWN_NAME:
                return False, "Choose a real product name."
            if name != old_name:
                conn.execute("UPDATE items SET name = ? WHERE productno = ?",
                             (name, productno))
                changes.append("renamed '%s' to '%s'" % (old_name, name))
        target_name = name or old_name

        if category is not None:
            category = category.strip()
            if not conn.execute(
                    "SELECT 1 FROM categories WHERE name = ?", (category,)).fetchone():
                return False, "Category '%s' does not exist." % category
            conn.execute("UPDATE items SET category = ? WHERE productno = ?",
                         (category, productno))
            conn.execute(
                """INSERT INTO catalog(name, category) VALUES (?, ?)
                   ON CONFLICT(name) DO UPDATE SET category = excluded.category""",
                (target_name, category))
            changes.append("filed under %s" % category)

        if min_qty is not None:
            try:
                min_qty = int(min_qty)
            except (TypeError, ValueError):
                return False, "The reorder level must be a whole number."
            if min_qty < 0:
                return False, "The reorder level cannot be negative."
            conn.execute(
                """INSERT INTO catalog(name, category, min_qty) VALUES (?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET min_qty = excluded.min_qty""",
                (target_name, UNCATEGORISED, min_qty))
            changes.append("reorder level set to %d" % min_qty)

        if not changes:
            return True, "Nothing changed."
        note = "Product %s: %s." % (productno, ", ".join(changes))
        # Renaming or refiling a product changes no quantity, so this row must
        # not be treated as a new opening balance for anything. It is written
        # against the no-batch key only, which holds no stock of its own.
        conn.execute(
            """INSERT INTO logs(ts, code, name, productno, batchno, action, category,
                                anomaly, undone, trace, user_id, username)
               VALUES (?, ?, ?, ?, '__meta__', 'ADJUST', ?, 0, 1, ?, ?, ?)""",
            (now_iso(), productno, target_name, productno, category or UNCATEGORISED,
             json.dumps([{"agent": "Manual correction", "notes": [note]}]),
             (actor or {}).get("id"), (actor or {}).get("username", "")),
        )
    return True, note


def delete_product(productno, force=False, actor=None):
    """Remove a product's stock records.

    Refused while stock is on hand unless forced: deleting a product that still
    has units is almost always a mistake, and the one time it is not, saying so
    explicitly is cheap. Log entries are never deleted — the trail keeps its
    history whatever happens to the product record.
    """
    with _lock, _conn() as conn:
        rows = conn.execute(
            "SELECT name, SUM(qty) AS qty FROM items WHERE productno = ?", (productno,)
        ).fetchone()
        if rows is None or rows["name"] is None:
            return False, "No product with number %s." % productno
        on_hand = rows["qty"] or 0
        if on_hand > 0 and not force:
            return False, ("%s still has %d unit(s) on hand. Scan them out or adjust "
                           "the quantity to zero first." % (rows["name"], on_hand))
        conn.execute("DELETE FROM items WHERE productno = ?", (productno,))
        conn.execute("DELETE FROM aliases WHERE productno = ?", (productno,))
        note = ("Product '%s' (%s) removed%s. Its audit history is kept."
                % (rows["name"], productno,
                   " with %d unit(s) still recorded" % on_hand if on_hand else ""))
        conn.execute(
            """INSERT INTO logs(ts, code, name, productno, batchno, action, category,
                                anomaly, undone, trace, user_id, username)
               VALUES (?, ?, ?, ?, '', 'ADJUST', ?, 0, 1, ?, ?, ?)""",
            (now_iso(), productno, rows["name"], productno, UNCATEGORISED,
             json.dumps([{"agent": "Manual correction", "notes": [note]}]),
             (actor or {}).get("id"), (actor or {}).get("username", "")),
        )
    return True, note


def add_batch(productno, batchno, qty=0, actor=None):
    """Open a new batch of an existing product."""
    batchno = (batchno or "").strip()
    detail = product_detail(productno)
    if detail is None:
        return False, "No product with number %s." % productno
    if any(b["batchno"] == batchno for b in detail["batches"]):
        return False, "Batch '%s' already exists for this product." % (batchno or "(none)")
    ok, message, _ = create_product(detail["name"], productno, batchno, qty,
                                    detail["category"], detail["min_qty"], actor=actor)
    return ok, message


def delete_batch(productno, batchno, actor=None):
    with _lock, _conn() as conn:
        row = conn.execute(
            "SELECT name, qty FROM items WHERE productno = ? AND batchno = ?",
            (productno, batchno or ""),
        ).fetchone()
        if row is None:
            return False, "No such batch."
        remaining = conn.execute(
            "SELECT COUNT(*) AS c FROM items WHERE productno = ?", (productno,)
        ).fetchone()["c"]
        if remaining <= 1:
            return False, ("This is the product's only batch. Delete the product "
                           "itself instead.")
        if row["qty"] > 0:
            return False, ("Batch %s still holds %d unit(s). Set it to zero first."
                           % (batchno or "(none)", row["qty"]))
        conn.execute("DELETE FROM items WHERE productno = ? AND batchno = ?",
                     (productno, batchno or ""))
        note = "Batch %s of %s removed." % (batchno or "(none)", row["name"])
        conn.execute(
            """INSERT INTO logs(ts, code, name, productno, batchno, action, category,
                                anomaly, undone, trace, user_id, username)
               VALUES (?, ?, ?, ?, ?, 'ADJUST', ?, 0, 1, ?, ?, ?)""",
            (now_iso(), productno, row["name"], productno, batchno or "", UNCATEGORISED,
             json.dumps([{"agent": "Manual correction", "notes": [note]}]),
             (actor or {}).get("id"), (actor or {}).get("username", "")),
        )
    return True, note


# ----------------------------------------------------------------------------
# Daily reporting
# ----------------------------------------------------------------------------
def daily_report(days=30, date_from=None, date_to=None):
    """Movements per day over a window, with the breakdowns a manager asks for.

    Reversed scans are excluded throughout: the report should show what actually
    happened to stock, not actions that were taken back. Days with no movement
    are filled in with zeros, because a gap in a line chart reads as missing
    data rather than as a quiet day.
    """
    today = datetime.now(timezone.utc).date()
    if date_to:
        try:
            end = datetime.fromisoformat(date_to).date()
        except ValueError:
            end = today
    else:
        end = today
    if date_from:
        try:
            start = datetime.fromisoformat(date_from).date()
        except ValueError:
            start = end - timedelta(days=max(int(days), 1) - 1)
    else:
        start = end - timedelta(days=max(int(days), 1) - 1)
    if start > end:
        start, end = end, start

    lo, hi = start.isoformat(), (end + timedelta(days=1)).isoformat()

    with _lock, _conn() as conn:
        by_day = {r["day"]: r for r in conn.execute(
            """SELECT substr(ts, 1, 10) AS day,
                      SUM(CASE WHEN action = 'IN'  THEN 1 ELSE 0 END) AS ins,
                      SUM(CASE WHEN action = 'OUT' THEN 1 ELSE 0 END) AS outs,
                      SUM(CASE WHEN action = 'REJECT' THEN 1 ELSE 0 END) AS rejects,
                      SUM(CASE WHEN action = 'ADJUST' THEN 1 ELSE 0 END) AS adjusts,
                      SUM(anomaly) AS anomalies,
                      COUNT(*) AS total
                 FROM logs
                WHERE ts >= ? AND ts < ? AND undone = 0
             GROUP BY day""",
            (lo, hi),
        )}

        by_product = [dict(r) for r in conn.execute(
            """SELECT name, productno,
                      SUM(CASE WHEN action = 'IN'  THEN 1 ELSE 0 END) AS ins,
                      SUM(CASE WHEN action = 'OUT' THEN 1 ELSE 0 END) AS outs
                 FROM logs
                WHERE ts >= ? AND ts < ? AND undone = 0 AND action IN ('IN','OUT')
             GROUP BY name, productno
             ORDER BY (ins + outs) DESC LIMIT 25""",
            (lo, hi),
        )]

        by_category = [dict(r) for r in conn.execute(
            """SELECT COALESCE(NULLIF(category, ''), ?) AS category,
                      SUM(CASE WHEN action = 'IN'  THEN 1 ELSE 0 END) AS ins,
                      SUM(CASE WHEN action = 'OUT' THEN 1 ELSE 0 END) AS outs
                 FROM logs
                WHERE ts >= ? AND ts < ? AND undone = 0 AND action IN ('IN','OUT')
             GROUP BY 1 ORDER BY (ins + outs) DESC""",
            (UNCATEGORISED, lo, hi),
        )]

        by_staff = [dict(r) for r in conn.execute(
            """SELECT CASE WHEN username = '' THEN 'not recorded' ELSE username END AS staff,
                      SUM(CASE WHEN action = 'IN'  THEN 1 ELSE 0 END) AS ins,
                      SUM(CASE WHEN action = 'OUT' THEN 1 ELSE 0 END) AS outs,
                      SUM(anomaly) AS anomalies,
                      COUNT(*) AS total
                 FROM logs
                WHERE ts >= ? AND ts < ? AND undone = 0
             GROUP BY staff ORDER BY total DESC""",
            (lo, hi),
        )]

        by_hour = [dict(r) for r in conn.execute(
            """SELECT CAST(substr(ts, 12, 2) AS INTEGER) AS hour, COUNT(*) AS total
                 FROM logs
                WHERE ts >= ? AND ts < ? AND undone = 0 AND action IN ('IN','OUT')
             GROUP BY hour ORDER BY hour""",
            (lo, hi),
        )]

    series = []
    day = start
    while day <= end:
        key = day.isoformat()
        r = by_day.get(key)
        series.append({
            "day": key,
            "in": (r["ins"] if r else 0) or 0,
            "out": (r["outs"] if r else 0) or 0,
            "rejects": (r["rejects"] if r else 0) or 0,
            "adjusts": (r["adjusts"] if r else 0) or 0,
            "anomalies": (r["anomalies"] if r else 0) or 0,
            "total": (r["total"] if r else 0) or 0,
            # Net movement is the number a stock controller actually watches.
            "net": ((r["ins"] if r else 0) or 0) - ((r["outs"] if r else 0) or 0),
        })
        day += timedelta(days=1)

    total_in = sum(d["in"] for d in series)
    total_out = sum(d["out"] for d in series)
    active_days = sum(1 for d in series if d["total"])

    hours = {h["hour"]: h["total"] for h in by_hour}
    busiest = max(hours, key=hours.get) if hours else None
    busiest_day = max(series, key=lambda d: d["total"]) if series else None

    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "days": len(series),
        "series": series,
        "by_product": by_product,
        "by_category": by_category,
        "by_staff": by_staff,
        "by_hour": [{"hour": h, "total": hours.get(h, 0)} for h in range(24)],
        "summary": {
            "in": total_in,
            "out": total_out,
            "net": total_in - total_out,
            "rejects": sum(d["rejects"] for d in series),
            "adjusts": sum(d["adjusts"] for d in series),
            "anomalies": sum(d["anomalies"] for d in series),
            "active_days": active_days,
            # Averaged over days with activity, not the whole window: a quiet
            # weekend should not make the weekday average look bad.
            "avg_in_per_active_day": round(total_in / active_days, 2) if active_days else 0,
            "avg_out_per_active_day": round(total_out / active_days, 2) if active_days else 0,
            "busiest_hour": busiest,
            "busiest_day": busiest_day["day"] if busiest_day and busiest_day["total"] else None,
        },
    }


def search_logs(q="", action="", limit=100):
    """Filter the audit trail by free text (name / product no. / batch) and action."""
    q = (q or "").strip()
    action = (action or "").strip().upper()
    sql = ["SELECT id, ts, code, name, productno, batchno, action, category, anomaly, undone, username",
           "FROM logs WHERE 1=1"]
    params = []
    if q:
        sql.append("AND (name LIKE ? OR productno LIKE ? OR batchno LIKE ? "
                   "OR username LIKE ?)")
        like = "%" + q + "%"
        params += [like, like, like, like]
    if action:
        sql.append("AND action = ?")
        params.append(action)
    sql.append("ORDER BY id DESC LIMIT ?")
    params.append(max(1, min(int(limit or 100), 500)))
    with _lock, _conn() as conn:
        return [dict(r) for r in conn.execute(" ".join(sql), params)]


def out_history():
    """All OUT actions with timestamps — feeds the forecast agent."""
    with _lock, _conn() as conn:
        rows = conn.execute(
            "SELECT ts, name FROM logs WHERE action='OUT' ORDER BY ts"
        ).fetchall()
        return [dict(r) for r in rows]


def stats():
    with _lock, _conn() as conn:
        total_in = conn.execute(
            "SELECT COALESCE(SUM(qty), 0) AS c FROM items WHERE qty > 0"
        ).fetchone()["c"]
        total_scans = conn.execute("SELECT COUNT(*) AS c FROM logs").fetchone()["c"]
        anomalies = conn.execute("SELECT COUNT(*) AS c FROM logs WHERE anomaly=1").fetchone()["c"]
        categories = conn.execute("SELECT COUNT(*) AS c FROM categories").fetchone()["c"]
        moves = conn.execute(
            """SELECT SUM(CASE WHEN action = 'IN'  THEN 1 ELSE 0 END) AS ins,
                      SUM(CASE WHEN action = 'OUT' THEN 1 ELSE 0 END) AS outs
                 FROM logs WHERE action IN ('IN', 'OUT') AND undone = 0"""
        ).fetchone()
        return {
            "in_stock": total_in,
            "total_scans": total_scans,
            "anomalies": anomalies,
            "categories": categories,
            "scans_in": moves["ins"] or 0,
            "scans_out": moves["outs"] or 0,
        }
