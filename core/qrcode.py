"""
QR code encoder
===============
Generates QR codes, in pure Python, with no dependencies.

Two things need one. A phone cannot open the scanner over plain ``http://`` --
browsers only grant camera access on HTTPS or localhost -- so the server prints
a QR of its own HTTPS address for the phone to scan. And a warehouse that reads
QR labels ought to be able to print them: the product-label view encodes
``name,batch,productno``, which is exactly the payload the Scanner Agent parses.

Scope
-----
Byte mode, error-correction level L or M, versions 1-10 (up to 271 bytes at
level L). That covers a LAN URL and a product payload with room to spare, and
stops well short of the version-40 tables that would triple the size of this
file for no benefit here.

The implementation follows ISO/IEC 18004: encode to codewords, append
Reed-Solomon error correction over GF(256), interleave the blocks, lay them into
the matrix along the standard zig-zag, then choose the mask with the lowest
penalty score.
"""

# ---------------------------------------------------------------------------
# Tables (versions 1-10 only)
# ---------------------------------------------------------------------------
#: Total codewords (data + error correction) per version.
TOTAL_CODEWORDS = {
    1: 26, 2: 44, 3: 70, 4: 100, 5: 134,
    6: 172, 7: 196, 8: 242, 9: 292, 10: 346,
}

#: (ec_per_block, [(block_count, data_codewords_per_block), ...]) per (version, level).
BLOCKS = {
    ("L", 1): (7, [(1, 19)]),
    ("L", 2): (10, [(1, 34)]),
    ("L", 3): (15, [(1, 55)]),
    ("L", 4): (20, [(1, 80)]),
    ("L", 5): (26, [(1, 108)]),
    ("L", 6): (18, [(2, 68)]),
    ("L", 7): (20, [(2, 78)]),
    ("L", 8): (24, [(2, 97)]),
    ("L", 9): (30, [(2, 116)]),
    ("L", 10): (18, [(2, 68), (2, 69)]),
    ("M", 1): (10, [(1, 16)]),
    ("M", 2): (16, [(1, 28)]),
    ("M", 3): (26, [(1, 44)]),
    ("M", 4): (18, [(2, 32)]),
    ("M", 5): (24, [(2, 43)]),
    ("M", 6): (16, [(4, 27)]),
    ("M", 7): (18, [(4, 31)]),
    ("M", 8): (22, [(2, 38), (2, 39)]),
    ("M", 9): (22, [(3, 36), (2, 37)]),
    ("M", 10): (26, [(4, 43), (1, 44)]),
}

#: Row/column centres of the alignment patterns, per version.
ALIGNMENT = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30],
    6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}

#: Two-bit code for each error-correction level, as it appears in format info.
EC_BITS = {"L": 0b01, "M": 0b00, "Q": 0b11, "H": 0b10}


class QRError(Exception):
    """Raised when the payload will not fit in a supported version."""


# ---------------------------------------------------------------------------
# GF(256) arithmetic for Reed-Solomon
# ---------------------------------------------------------------------------
_EXP = [0] * 512
_LOG = [0] * 256


def _init_tables():
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        # Multiply by 2 in GF(256) with the QR primitive polynomial 0x11d.
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_init_tables()


def _gf_mul(a, b):
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _generator_poly(degree):
    """The Reed-Solomon generator polynomial of the given degree."""
    poly = [1]
    for i in range(degree):
        # Multiply by (x - alpha^i).
        nxt = [0] * (len(poly) + 1)
        for j, coeff in enumerate(poly):
            nxt[j] ^= _gf_mul(coeff, 1)
            nxt[j + 1] ^= _gf_mul(coeff, _EXP[i])
        poly = nxt
    return poly


def _ec_codewords(data, count):
    """Reed-Solomon remainder for one block."""
    gen = _generator_poly(count)
    remainder = list(data) + [0] * count
    for i in range(len(data)):
        factor = remainder[i]
        if factor == 0:
            continue
        for j, g in enumerate(gen):
            remainder[i + j] ^= _gf_mul(g, factor)
    return remainder[len(data):]


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------
def _capacity(version, level):
    _, groups = BLOCKS[(level, version)]
    return sum(count * size for count, size in groups)


def _choose_version(length, level):
    for version in range(1, 11):
        # 4 bits mode indicator + 8 or 16 bits length + the data itself.
        header = 4 + (8 if version < 10 else 16)
        if header + length * 8 <= _capacity(version, level) * 8:
            return version
    raise QRError(
        "%d bytes is more than this encoder supports (versions 1-10)." % length)


def _encode_data(text, version, level):
    """Payload -> data codewords, padded to the version's capacity."""
    data = text.encode("utf-8")
    bits = []

    def put(value, length):
        for i in range(length - 1, -1, -1):
            bits.append((value >> i) & 1)

    put(0b0100, 4)                                   # byte mode
    put(len(data), 8 if version < 10 else 16)
    for byte in data:
        put(byte, 8)

    capacity_bits = _capacity(version, level) * 8
    if len(bits) > capacity_bits:
        raise QRError("Payload does not fit the chosen version.")

    # Terminator, then pad to a byte boundary.
    put(0, min(4, capacity_bits - len(bits)))
    while len(bits) % 8:
        bits.append(0)

    codewords = [int("".join(str(b) for b in bits[i:i + 8]), 2)
                 for i in range(0, len(bits), 8)]
    # Pad bytes alternate 0xEC / 0x11, as the specification requires.
    pad = [0xEC, 0x11]
    i = 0
    while len(codewords) < _capacity(version, level):
        codewords.append(pad[i % 2])
        i += 1
    return codewords


def _interleave(codewords, version, level):
    """Split into blocks, add error correction, and interleave both."""
    ec_count, groups = BLOCKS[(level, version)]
    blocks = []
    pos = 0
    for count, size in groups:
        for _ in range(count):
            block = codewords[pos:pos + size]
            pos += size
            blocks.append((block, _ec_codewords(block, ec_count)))

    out = []
    longest = max(len(b) for b, _ in blocks)
    for i in range(longest):
        for block, _ in blocks:
            if i < len(block):
                out.append(block[i])
    for i in range(ec_count):
        for _, ec in blocks:
            out.append(ec[i])
    return out


# ---------------------------------------------------------------------------
# Matrix construction
# ---------------------------------------------------------------------------
def _new_matrix(size):
    return [[None] * size for _ in range(size)]


def _place_finder(matrix, row, col):
    for r in range(-1, 8):
        for c in range(-1, 8):
            rr, cc = row + r, col + c
            if not (0 <= rr < len(matrix) and 0 <= cc < len(matrix)):
                continue
            inside = (0 <= r <= 6 and c in (0, 6)) or (0 <= c <= 6 and r in (0, 6)) \
                or (2 <= r <= 4 and 2 <= c <= 4)
            matrix[rr][cc] = 1 if inside else 0


def _place_alignment(matrix, version):
    centres = ALIGNMENT[version]
    size = len(matrix)
    for r in centres:
        for c in centres:
            # Skip the three corners, where the finder patterns already sit.
            if (r, c) in ((6, 6), (6, centres[-1]), (centres[-1], 6)):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    rr, cc = r + dr, c + dc
                    if 0 <= rr < size and 0 <= cc < size:
                        matrix[rr][cc] = 1 if max(abs(dr), abs(dc)) != 1 else 0


def _place_timing(matrix):
    size = len(matrix)
    for i in range(8, size - 8):
        bit = 1 if i % 2 == 0 else 0
        if matrix[6][i] is None:
            matrix[6][i] = bit
        if matrix[i][6] is None:
            matrix[i][6] = bit


def _reserve_format(matrix, version):
    """Mark the format (and version) areas so data never lands on them."""
    size = len(matrix)
    for i in range(9):
        if matrix[8][i] is None:
            matrix[8][i] = 0
        if matrix[i][8] is None:
            matrix[i][8] = 0
    for i in range(8):
        if matrix[8][size - 1 - i] is None:
            matrix[8][size - 1 - i] = 0
        if matrix[size - 1 - i][8] is None:
            matrix[size - 1 - i][8] = 0
    matrix[size - 8][8] = 1                          # the always-dark module
    if version >= 7:
        for i in range(6):
            for j in range(3):
                matrix[size - 11 + j][i] = 0
                matrix[i][size - 11 + j] = 0


def _place_data(matrix, codewords):
    size = len(matrix)
    bits = []
    for cw in codewords:
        for i in range(7, -1, -1):
            bits.append((cw >> i) & 1)

    index = 0
    upward = True
    col = size - 1
    while col > 0:
        if col == 6:                                 # skip the timing column
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for c in (col, col - 1):
                if matrix[row][c] is None:
                    matrix[row][c] = bits[index] if index < len(bits) else 0
                    index += 1
        upward = not upward
        col -= 2


_MASKS = [
    lambda r, c: (r + c) % 2 == 0,
    lambda r, c: r % 2 == 0,
    lambda r, c: c % 3 == 0,
    lambda r, c: (r + c) % 3 == 0,
    lambda r, c: (r // 2 + c // 3) % 2 == 0,
    lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
    lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
    lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0,
]


def _is_function_module(row, col, size, version):
    """True where a module belongs to a pattern rather than to the data."""
    if row < 9 and col < 9:
        return True
    if row < 9 and col >= size - 8:
        return True
    if row >= size - 8 and col < 9:
        return True
    if row == 6 or col == 6:
        return True
    if version >= 7 and ((row < 6 and col >= size - 11) or (col < 6 and row >= size - 11)):
        return True
    centres = ALIGNMENT[version]
    for r in centres:
        for c in centres:
            if (r, c) in ((6, 6), (6, centres[-1] if centres else 6),
                          (centres[-1] if centres else 6, 6)):
                continue
            if abs(row - r) <= 2 and abs(col - c) <= 2:
                return True
    return False


def _apply_mask(matrix, mask, version):
    size = len(matrix)
    out = [row[:] for row in matrix]
    fn = _MASKS[mask]
    for r in range(size):
        for c in range(size):
            if not _is_function_module(r, c, size, version) and fn(r, c):
                out[r][c] ^= 1
    return out


def _penalty(matrix):
    """The four penalty rules from the specification, summed."""
    size = len(matrix)
    score = 0

    # Rule 1: runs of five or more identical modules in a row or column.
    for line in list(matrix) + [list(col) for col in zip(*matrix)]:
        run, prev = 1, line[0]
        for cell in line[1:]:
            if cell == prev:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run, prev = 1, cell
        if run >= 5:
            score += 3 + (run - 5)

    # Rule 2: 2x2 blocks of one colour.
    for r in range(size - 1):
        for c in range(size - 1):
            if matrix[r][c] == matrix[r][c + 1] == matrix[r + 1][c] == matrix[r + 1][c + 1]:
                score += 3

    # Rule 3: the finder-like 1:1:3:1:1 pattern appearing in the data.
    patterns = ([1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0],
                [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1])
    for line in list(matrix) + [list(col) for col in zip(*matrix)]:
        for i in range(size - 10):
            window = line[i:i + 11]
            if window in patterns:
                score += 40

    # Rule 4: overall imbalance between dark and light.
    dark = sum(sum(row) for row in matrix)
    ratio = dark * 100 // (size * size)
    score += 10 * (abs(ratio - 50) // 5)
    return score


def _bch(value, generator):
    """BCH remainder used by the format and version information."""
    shift = generator.bit_length() - 1
    v = value << shift
    while v.bit_length() > shift:
        v ^= generator << (v.bit_length() - generator.bit_length())
    return v


def _format_bits(level, mask):
    data = (EC_BITS[level] << 3) | mask
    return ((data << 10) | _bch(data, 0x537)) ^ 0x5412


def _version_bits(version):
    return (version << 12) | _bch(version, 0x1F25)


def _place_format(matrix, level, mask, version):
    """Write the 15 format bits into both of their copies.

    Bit 0 is the least significant. The two copies are laid out differently --
    one runs down the column beside the top-left finder, the other runs left
    along row 8 from the right-hand edge -- and getting these the wrong way
    round produces a code that looks perfectly correct and decodes in nothing.
    """
    size = len(matrix)
    bits = _format_bits(level, mask)
    for i in range(15):
        bit = (bits >> i) & 1

        # Copy 1: column 8, top-left downwards, then the bottom-left strip.
        if i < 6:
            matrix[i][8] = bit
        elif i < 8:
            matrix[i + 1][8] = bit          # skip the timing row at 6
        else:
            matrix[size - 15 + i][8] = bit

        # Copy 2: row 8, from the right-hand edge leftwards.
        if i < 8:
            matrix[8][size - 1 - i] = bit
        elif i == 8:
            matrix[8][7] = bit              # skip the timing column at 6
        else:
            matrix[8][14 - i] = bit

    matrix[size - 8][8] = 1                 # the always-dark module

    if version >= 7:
        vbits = _version_bits(version)
        for i in range(18):
            bit = (vbits >> i) & 1
            r, c = i // 3, i % 3
            matrix[size - 11 + c][r] = bit
            matrix[r][size - 11 + c] = bit


def encode(text, level="L"):
    """Encode ``text`` and return the QR matrix as a list of rows of 0/1."""
    if level not in ("L", "M"):
        raise QRError("Only error-correction levels L and M are supported.")
    data = text.encode("utf-8")
    version = _choose_version(len(data), level)
    size = 17 + 4 * version

    codewords = _interleave(_encode_data(text, version, level), version, level)

    matrix = _new_matrix(size)
    _place_finder(matrix, 0, 0)
    _place_finder(matrix, 0, size - 7)
    _place_finder(matrix, size - 7, 0)
    _place_alignment(matrix, version)
    _place_timing(matrix)
    _reserve_format(matrix, version)

    _place_data(matrix, codewords)

    best, best_score = None, None
    for mask in range(8):
        candidate = _apply_mask(matrix, mask, version)
        _place_format(candidate, level, mask, version)
        score = _penalty(candidate)
        if best_score is None or score < best_score:
            best, best_score = candidate, score
    return best


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------
def to_svg(text, level="L", module=4, quiet=4, dark="#000000", light="#ffffff"):
    """Render as a standalone SVG string."""
    matrix = encode(text, level)
    size = len(matrix)
    dim = (size + quiet * 2) * module
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
        'viewBox="0 0 %d %d" shape-rendering="crispEdges" role="img" '
        'aria-label="QR code">' % (dim, dim, dim, dim),
        '<rect width="%d" height="%d" fill="%s"/>' % (dim, dim, light),
    ]
    # One path for every dark module beats one <rect> each: the file is a
    # fraction of the size and renders noticeably faster.
    d = []
    for r, row in enumerate(matrix):
        for c, cell in enumerate(row):
            if cell:
                d.append("M%d,%dh%dv%dh-%dz" % (
                    (c + quiet) * module, (r + quiet) * module,
                    module, module, module))
    parts.append('<path d="%s" fill="%s"/>' % ("".join(d), dark))
    parts.append("</svg>")
    return "".join(parts)


def to_terminal(text, level="L", quiet=2, ascii_only=False):
    """Render for printing in a console.

    By default two matrix rows share one character cell using half-block
    characters, so the code comes out roughly square in a terminal whose cells
    are twice as tall as they are wide.

    ``ascii_only`` falls back to two spaces per module. It is wider and uglier
    but survives a console that cannot encode block characters — which is the
    default on Windows, where an unencodable character would otherwise raise
    and take the whole startup banner down with it.
    """
    matrix = encode(text, level)
    if ascii_only:
        pad = "  " * quiet
        blank = "  " * (len(matrix) + quiet * 2)
        lines = [blank] * quiet
        for row in matrix:
            # Dark modules print as spaces on a dark terminal, light as blocks;
            # inverting here keeps the same polarity as the half-block form.
            lines.append(pad + "".join("  " if cell else "##" for cell in row) + pad)
        lines.extend([blank] * quiet)
        return "\n".join(lines)
    size = len(matrix)
    padded = [[0] * (size + quiet * 2) for _ in range(quiet)]
    for row in matrix:
        padded.append([0] * quiet + list(row) + [0] * quiet)
    padded.extend([[0] * (size + quiet * 2) for _ in range(quiet)])
    if len(padded) % 2:
        padded.append([0] * len(padded[0]))

    lines = []
    for i in range(0, len(padded), 2):
        top, bottom = padded[i], padded[i + 1]
        line = []
        for t, b in zip(top, bottom):
            # Dark modules print as empty space so the code reads correctly on
            # the light-on-dark terminals most people use.
            if t and b:
                line.append(" ")
            elif t:
                line.append("▄")
            elif b:
                line.append("▀")
            else:
                line.append("█")
        lines.append("".join(line))
    return "\n".join(lines)
