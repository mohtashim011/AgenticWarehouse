"""
EAN-13 / UPC-A barcode renderer
===============================
Draws the 1-D barcode that goes on a printed label, beside the QR code.

This exists to close the loop the project keeps making a point of: a product has
one identity reachable by two symbologies. The label carries a QR holding
``name,batch,productno`` and a barcode holding the product number, and scanning
either lands on the same stock record. Printing both from one place is what
makes that checkable rather than merely asserted.

EAN-13 encodes twelve digits plus a check digit. The first digit is not drawn as
bars at all -- it is implied by which parity pattern each of the next six digits
uses, which is why an EAN-13 fits in the same width as a twelve-digit UPC-A.
"""

# Bar patterns. 0 is a space, 1 is a bar. Each digit is seven modules wide.
_LEFT_ODD = ["0001101", "0011001", "0010011", "0111101", "0100011",
             "0110001", "0101111", "0111011", "0110111", "0001011"]
_LEFT_EVEN = ["0100111", "0110011", "0011011", "0100001", "0011101",
              "0111001", "0000101", "0010001", "0001001", "0010111"]
_RIGHT = ["1110010", "1100110", "1101100", "1000010", "1011100",
          "1001110", "1010000", "1000100", "1001000", "1110100"]

#: Which of the first six digits use the even parity table, per first digit.
#: This is how the leading digit is encoded without any bars of its own.
_PARITY = ["OOOOOO", "OOEOEE", "OOEEOE", "OOEEEO", "OEOOEE",
           "OEEOOE", "OEEEOO", "OEOEOE", "OEOEEO", "OEEOEO"]

QUIET = 9        # modules of clear space each side; scanners need it
GUARD = "101"
CENTRE = "01010"


class BarcodeError(Exception):
    pass


def is_numeric(code):
    """Is this a string of plain 0-9 digits, and nothing cleverer?

    ``str.isdigit()`` is not that test and looks exactly like it. It is True for
    superscripts and other numeric forms that ``int()`` then refuses, so
    ``"1234567²".isdigit()`` is True and ``int("²")`` raises. Every guard in
    front of ``check_digit`` used ``isdigit()``, so a product number pasted with
    a footnote marker still in it reached ``int()`` and raised ValueError from
    inside a database write -- the row committed and the request 500'd, after
    which the code registry raised for every product until someone edited the
    database by hand.

    Requiring ASCII as well is deliberate. ``isdecimal()`` alone would admit
    Arabic-Indic and other decimal digits, which ``int()`` accepts happily and
    which would then be concatenated with an ASCII check digit into a product
    number written in two scripts. A retail barcode is 0-9.
    """
    return bool(code) and code.isdigit() and code.isascii()


def check_digit(body):
    """The GTIN check digit for a numeric body.

    Weights alternate 3 and 1 counting **from the right**, because that is how
    the GTIN rule is defined: the digit immediately left of the check digit
    always carries weight 3, whatever the length.

    This used to anchor the weights from the left, which gives the same answer
    for an even-length body -- a 12-digit EAN-13 body, which is all this module
    ever produced -- and the wrong answer for an odd-length one. Nothing called
    it that way until the decoder arrived and needed EAN-8, whose body is seven
    digits, so the bug was real but unreachable.
    """
    if not is_numeric(body):
        raise BarcodeError(
            "A check digit needs plain 0-9 digits; %r is not." % (body,))
    total = sum(int(d) * (3 if (len(body) - i) % 2 == 1 else 1)
                for i, d in enumerate(body))
    return str((10 - total % 10) % 10)


def normalise(code):
    """Coerce a product number to 13 digits, or raise.

    Accepts a 12-digit body (adds the check digit), a UPC-A (pads a leading
    zero) or a complete EAN-13. Anything else is not a retail barcode and
    should not be drawn as one -- an invalid barcode that looks convincing is
    worse than no barcode.
    """
    code = (code or "").strip()
    if not is_numeric(code):
        raise BarcodeError("Only numeric codes can be drawn as EAN-13.")
    if len(code) == 11:                     # UPC-A body, no check digit
        code = "0" + code
        code += check_digit(code)
    elif len(code) == 12:
        # Genuinely ambiguous: twelve digits is either a complete UPC-A, or an
        # EAN-13 body whose check digit has not been written down. Both occur in
        # this warehouse. A complete UPC-A is self-consistent, so test that
        # first and only fall back to appending a check digit when it is not.
        if check_digit(code[:11]) == code[11]:
            code = "0" + code               # UPC-A -> EAN-13
        else:
            code += check_digit(code)
    elif len(code) == 13:
        if check_digit(code[:12]) != code[12]:
            raise BarcodeError(
                "The check digit does not match: %s should end in %s."
                % (code, check_digit(code[:12])))
    else:
        raise BarcodeError(
            "EAN-13 needs 12 or 13 digits; %s has %d." % (code, len(code)))
    return code


def modules(code):
    """The full module string for a code: 95 modules of 0s and 1s."""
    code = normalise(code)
    parity = _PARITY[int(code[0])]
    bits = [GUARD]
    for i, digit in enumerate(code[1:7]):
        table = _LEFT_ODD if parity[i] == "O" else _LEFT_EVEN
        bits.append(table[int(digit)])
    bits.append(CENTRE)
    for digit in code[7:]:
        bits.append(_RIGHT[int(digit)])
    bits.append(GUARD)
    return code, "".join(bits)


def to_svg(code, module=2, height=60, show_text=True, dark="#000000", light="#ffffff"):
    """Render an EAN-13 as a standalone SVG string."""
    code, bits = modules(code)
    text_space = 14 if show_text else 0
    width = (len(bits) + QUIET * 2) * module
    total_height = height + text_space + 4

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
        'viewBox="0 0 %d %d" shape-rendering="crispEdges" role="img" '
        'aria-label="Barcode %s">' % (width, total_height, width, total_height, code),
        '<rect width="%d" height="%d" fill="%s"/>' % (width, total_height, light),
    ]

    # Guard bars run slightly longer than the data bars, which is what gives an
    # EAN-13 its familiar shape and gives the scanner its alignment marks.
    guard_positions = set(range(0, 3)) | set(range(45, 50)) | set(range(92, 95))

    d = []
    for i, bit in enumerate(bits):
        if bit != "1":
            continue
        x = (QUIET + i) * module
        h = height + (text_space // 2 if i in guard_positions and show_text else 0)
        d.append("M%d,0h%dv%dh-%dz" % (x, module, h, module))
    parts.append('<path d="%s" fill="%s"/>' % ("".join(d), dark))

    if show_text:
        y = total_height - 2
        # The leading digit sits outside the bars, in the left quiet zone --
        # that is where it belongs, since it has no bars of its own.
        groups = [
            (code[0], (QUIET - 7) * module),
            (code[1:7], (QUIET + 3) * module + 21 * module),
            (code[7:], (QUIET + 50) * module + 21 * module),
        ]
        for text, x in groups:
            parts.append(
                '<text x="%d" y="%d" font-family="monospace" font-size="%d" '
                'text-anchor="middle" fill="%s" letter-spacing="1">%s</text>'
                % (x, y, module * 6, dark, text))

    parts.append("</svg>")
    return "".join(parts)


def can_render(code):
    """Whether a product number can legitimately be drawn as an EAN-13."""
    try:
        normalise(code)
        return True
    except BarcodeError:
        return False
