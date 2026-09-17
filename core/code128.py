"""
Code 128
========
Encodes and decodes Code 128, the symbology on the shelf labels this warehouse
actually receives. Standard library only, like everything else on the running
path.

Why it is here
--------------
EAN-13 carries thirteen digits and nothing else. A warehouse label routinely
carries something like ``SHB011`` or ``WIL001`` -- letters and digits, arbitrary
length -- and that is Code 128's job. Two of the three sample labels in
``labels/`` are Code 128, and until this module existed the server decoder
reported them as "no barcode found", which is a poor answer for a barcode that
is plainly there.

How it differs from EAN-13, and why that changes the rules
----------------------------------------------------------
An EAN-13 is a fixed shape: ninety-five modules, always. Code 128 is variable
length, so a *fragment* of a long Code 128 can present the same shape as a
complete short one. That is the same trap an EAN-8 sets inside an EAN-13's bars,
and it is answered the same way: a Code 128 must show real clear space on both
sides, and the band edge does not count.

Three things make a wrong read unlikely even so, and all three are enforced:

* a valid start symbol (103, 104 or 105),
* a **modulo 103 checksum** over every symbol, weighted by position,
* the stop pattern, which is the only thirteen-module symbol in the set.

Structure of a symbol
---------------------
Every symbol is six runs -- three bars, three spaces -- totalling eleven
modules, except the stop, which is seven runs totalling thirteen. The bars of
every symbol sum to an even number of modules; that is Code 128's own
self-checking property and `verify.py` asserts it over the whole table, because
one mistyped width in a 107-row table is otherwise invisible.
"""

#: Run widths for values 0-106: bar, space, bar, space, bar, space. Value 106
#: is the stop and has a seventh element, a trailing bar.
PATTERNS = [
    (2, 1, 2, 2, 2, 2), (2, 2, 2, 1, 2, 2), (2, 2, 2, 2, 2, 1), (1, 2, 1, 2, 2, 3),
    (1, 2, 1, 3, 2, 2), (1, 3, 1, 2, 2, 2), (1, 2, 2, 2, 1, 3), (1, 2, 2, 3, 1, 2),
    (1, 3, 2, 2, 1, 2), (2, 2, 1, 2, 1, 3), (2, 2, 1, 3, 1, 2), (2, 3, 1, 2, 1, 2),
    (1, 1, 2, 2, 3, 2), (1, 2, 2, 1, 3, 2), (1, 2, 2, 2, 3, 1), (1, 1, 3, 2, 2, 2),
    (1, 2, 3, 1, 2, 2), (1, 2, 3, 2, 2, 1), (2, 2, 3, 2, 1, 1), (2, 2, 1, 1, 3, 2),
    (2, 2, 1, 2, 3, 1), (2, 1, 3, 2, 1, 2), (2, 2, 3, 1, 1, 2), (3, 1, 2, 1, 3, 1),
    (3, 1, 1, 2, 2, 2), (3, 2, 1, 1, 2, 2), (3, 2, 1, 2, 2, 1), (3, 1, 2, 2, 1, 2),
    (3, 2, 2, 1, 1, 2), (3, 2, 2, 2, 1, 1), (2, 1, 2, 1, 2, 3), (2, 1, 2, 3, 2, 1),
    (2, 3, 2, 1, 2, 1), (1, 1, 1, 3, 2, 3), (1, 3, 1, 1, 2, 3), (1, 3, 1, 3, 2, 1),
    (1, 1, 2, 3, 1, 3), (1, 3, 2, 1, 1, 3), (1, 3, 2, 3, 1, 1), (2, 1, 1, 3, 1, 3),
    (2, 3, 1, 1, 1, 3), (2, 3, 1, 3, 1, 1), (1, 1, 2, 1, 3, 3), (1, 1, 2, 3, 3, 1),
    (1, 3, 2, 1, 3, 1), (1, 1, 3, 1, 2, 3), (1, 1, 3, 3, 2, 1), (1, 3, 3, 1, 2, 1),
    (3, 1, 3, 1, 2, 1), (2, 1, 1, 3, 3, 1), (2, 3, 1, 1, 3, 1), (2, 1, 3, 1, 1, 3),
    (2, 1, 3, 3, 1, 1), (2, 1, 3, 1, 3, 1), (3, 1, 1, 1, 2, 3), (3, 1, 1, 3, 2, 1),
    (3, 3, 1, 1, 2, 1), (3, 1, 2, 1, 1, 3), (3, 1, 2, 3, 1, 1), (3, 3, 2, 1, 1, 1),
    (3, 1, 4, 1, 1, 1), (2, 2, 1, 4, 1, 1), (4, 3, 1, 1, 1, 1), (1, 1, 1, 2, 2, 4),
    (1, 1, 1, 4, 2, 2), (1, 2, 1, 1, 2, 4), (1, 2, 1, 4, 2, 1), (1, 4, 1, 1, 2, 2),
    (1, 4, 1, 2, 2, 1), (1, 1, 2, 2, 1, 4), (1, 1, 2, 4, 1, 2), (1, 2, 2, 1, 1, 4),
    (1, 2, 2, 4, 1, 1), (1, 4, 2, 1, 1, 2), (1, 4, 2, 2, 1, 1), (2, 4, 1, 2, 1, 1),
    (2, 2, 1, 1, 1, 4), (4, 1, 3, 1, 1, 1), (2, 4, 1, 1, 1, 2), (1, 3, 4, 1, 1, 1),
    (1, 1, 1, 2, 4, 2), (1, 2, 1, 1, 4, 2), (1, 2, 1, 2, 4, 1), (1, 1, 4, 2, 1, 2),
    (1, 2, 4, 1, 1, 2), (1, 2, 4, 2, 1, 1), (4, 1, 1, 2, 1, 2), (4, 2, 1, 1, 1, 2),
    (4, 2, 1, 2, 1, 1), (2, 1, 2, 1, 4, 1), (2, 1, 4, 1, 2, 1), (4, 1, 2, 1, 2, 1),
    (1, 1, 1, 1, 4, 3), (1, 1, 1, 3, 4, 1), (1, 3, 1, 1, 4, 1), (1, 1, 4, 1, 1, 3),
    (1, 1, 4, 3, 1, 1), (4, 1, 1, 1, 1, 3), (4, 1, 1, 3, 1, 1), (1, 1, 3, 1, 4, 1),
    (1, 1, 4, 1, 3, 1), (3, 1, 1, 1, 4, 1), (4, 1, 1, 1, 3, 1), (2, 1, 1, 4, 1, 2),
    (2, 1, 1, 2, 1, 4), (2, 1, 1, 2, 3, 2), (2, 3, 3, 1, 1, 1, 2),
]

START_A, START_B, START_C, STOP = 103, 104, 105, 106

#: Modules of clear space a Code 128 must show on each side. The specification
#: asks for ten. Three is enforced instead, matching the rest of this package --
#: a tightly cropped photograph is normal and refusing a real read for it helps
#: nobody. The rule that does the safety work here is the checksum.
MIN_QUIET_MODULES = 3

SYMBOL_MODULES = 11
STOP_MODULES = 13


class Code128Error(Exception):
    pass


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------
def _modules_for(value):
    """A symbol value as a module string, starting on a bar."""
    bits = []
    dark = True
    for width in PATTERNS[value]:
        bits.append(("1" if dark else "0") * width)
        dark = not dark
    return "".join(bits)


def can_encode(text):
    """Whether Code 128 subset B can carry this string as it stands."""
    return bool(text) and all(32 <= ord(c) <= 126 for c in text)


def values(text):
    """The symbol values for ``text``, start and checksum included.

    Subset B unless the whole string is an even number of digits, in which case
    subset C halves the width. Mixed-mode switching mid-string is legal and
    would compress further; it is not implemented, because a warehouse product
    number is short and the extra states are extra ways to be wrong.
    """
    if not can_encode(text):
        raise Code128Error(
            "Code 128 here carries printable ASCII only; %r does not qualify."
            % (text,))

    if text.isdigit() and len(text) % 2 == 0 and text.isascii():
        out = [START_C]
        out.extend(int(text[i:i + 2]) for i in range(0, len(text), 2))
    else:
        out = [START_B]
        out.extend(ord(c) - 32 for c in text)

    # The check symbol is the start value plus every data symbol weighted by
    # its one-based position, modulo 103.
    total = out[0]
    for position, value in enumerate(out[1:], start=1):
        total += position * value
    out.append(total % 103)
    out.append(STOP)
    return out


def modules(text, quiet=MIN_QUIET_MODULES):
    """The full module string for ``text``, quiet zones included."""
    body = "".join(_modules_for(v) for v in values(text))
    return "0" * quiet + body + "0" * quiet


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------
#: Subset A maps 0-63 to ASCII 32-95 and 64-95 to the control characters. Only
#: the printable half is reconstructed: a control character in a product number
#: is a scanning error, not a product number.
def _char_a(value):
    if 0 <= value <= 63:
        return chr(value + 32)
    return None


def _char_b(value):
    if 0 <= value <= 94:
        return chr(value + 32)
    return None


def to_text(symbols):
    """Turn decoded symbol values into a string, or None if they do not.

    ``symbols`` is everything between the start symbol and the checksum,
    exclusive of both. The start symbol chooses the initial subset.
    """
    if not symbols:
        return None
    start, body = symbols[0], symbols[1:]
    if start == START_A:
        mode = "A"
    elif start == START_B:
        mode = "B"
    elif start == START_C:
        mode = "C"
    else:
        return None

    out = []
    shifted = None
    for value in body:
        active = shifted or mode
        shifted = None
        if active == "C":
            if 0 <= value <= 99:
                out.append("%02d" % value)
                continue
            if value == 100:
                mode = "B"
                continue
            if value == 101:
                mode = "A"
                continue
            if value == 102:                      # FNC1
                continue
            return None
        # Subsets A and B share their special values except for 100 and 101.
        if value == 98:                           # Shift: one character only
            shifted = "B" if active == "A" else "A"
            continue
        if value == 99:
            mode = "C"
            continue
        if active == "A":
            if value == 100:
                mode = "B"
                continue
            if value == 101:                      # FNC4
                continue
        else:
            if value == 100:                      # FNC4
                continue
            if value == 101:
                mode = "A"
                continue
        if value in (96, 97, 102):                # FNC3, FNC2, FNC1
            continue
        character = _char_a(value) if active == "A" else _char_b(value)
        if character is None:
            return None
        out.append(character)
    return "".join(out) if out else None


def checksum_ok(symbols):
    """``symbols`` is start, data..., check. Modulo 103, weighted by position."""
    if len(symbols) < 2:
        return False
    total = symbols[0]
    for position, value in enumerate(symbols[1:-1], start=1):
        total += position * value
    return total % 103 == symbols[-1]
