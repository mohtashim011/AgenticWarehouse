"""
QR code decoder
===============
Reads back what :mod:`core.qrcode` draws: byte mode, error-correction level L
or M, versions 1 to 10. Standard library only.

Why this exists
---------------
Until now the QR encoder was checked by asserting its *structure* -- module
dimensions, format bits, the always-dark module -- and CLAUDE.md said so
plainly: the symbols were "not round-tripped through an independent decoder in
the test suite; doing so would need a third-party package and would break the
zero-dependency rule, so it stays a manual check."

That is a gap of exactly the kind golden rule 10 exists to close. Structure
checks confirm a QR-shaped thing was drawn; they cannot confirm it says what it
was asked to say. A mask applied to the wrong modules, a format copy written the
wrong way round, an interleave off by one block -- each produces a symbol that
passes every structural assertion and decodes in nothing. Now the encoder is
read back and compared against the string that went in.

It also means a photographed QR label can be checked from a file, the same way
`scan_image.py` already checks a barcode.

What it does and does not do
----------------------------
It reads a QR that is **square to the frame**. Locating a rotated or perspective
-skewed symbol needs the full three-finder homography that a phone camera
library implements, and this decoder is aimed at a rendered label and a photo
taken square-on, not at a code seen from the side. A tilted symbol is refused
rather than half-read.

Reed-Solomon errors *are* corrected -- syndromes, Berlekamp-Massey, Chien
search, Forney -- because a printed label picks up damage and the whole point of
the error correction is to survive it. The GF(256) arithmetic is imported from
the encoder rather than reimplemented, for the same reason the barcode decoder
imports its parity tables: two copies of a field is how an encoder and a decoder
silently stop agreeing.
"""

from core.qrcode import (
    ALIGNMENT, BLOCKS, EC_BITS, _EXP, _LOG, _MASKS, _bch, _gf_mul,
    _is_function_module,
)


class QRDecodeError(Exception):
    pass


#: Format information is protected by its own BCH code and masked with this.
FORMAT_MASK = 0x5412

#: How far a run may stray from the 1:1:3:1:1 finder ratio, as a share of the
#: unit width. Finders are the only thing anchoring the grid, so this is
#: tolerant enough for a blurred photograph and tight enough that ordinary
#: label text does not present as one.
FINDER_TOLERANCE = 0.55

_LEVEL_FOR_BITS = {bits: level for level, bits in EC_BITS.items()}


# ---------------------------------------------------------------------------
# Reed-Solomon decoding
# ---------------------------------------------------------------------------
def _gf_pow(exponent):
    """alpha to the given power, for any integer exponent."""
    return _EXP[exponent % 255]


def _gf_inverse(a):
    if a == 0:
        raise ZeroDivisionError("no inverse of zero in GF(256)")
    return _EXP[(255 - _LOG[a]) % 255]


def _gf_div(a, b):
    if b == 0:
        raise ZeroDivisionError("division by zero in GF(256)")
    if a == 0:
        return 0
    return _EXP[(_LOG[a] - _LOG[b]) % 255]


def _poly_eval(poly, x):
    """Evaluate a polynomial at x. Coefficients run highest power first."""
    out = 0
    for coeff in poly:
        out = _gf_mul(out, x) ^ coeff
    return out


def _poly_scale(poly, factor):
    return [_gf_mul(c, factor) for c in poly]


def _poly_add(p, q):
    size = max(len(p), len(q))
    out = [0] * size
    for i, c in enumerate(p):
        out[i + size - len(p)] ^= c
    for i, c in enumerate(q):
        out[i + size - len(q)] ^= c
    return out


def _poly_mul(p, q):
    out = [0] * (len(p) + len(q) - 1)
    for i, a in enumerate(p):
        if a == 0:
            continue
        for j, b in enumerate(q):
            out[i + j] ^= _gf_mul(a, b)
    return out


def _syndromes(block, ec_count):
    return [_poly_eval(block, _gf_pow(i)) for i in range(ec_count)]


def _error_locator(syndromes, ec_count):
    """Berlekamp-Massey. Returns the error locator polynomial."""
    locator, previous = [1], [1]
    for i in range(ec_count):
        delta = syndromes[i]
        for j in range(1, len(locator)):
            delta ^= _gf_mul(locator[len(locator) - 1 - j], syndromes[i - j])
        previous = previous + [0]
        if delta != 0:
            if len(previous) > len(locator):
                scaled = _poly_scale(previous, delta)
                previous = _poly_scale(locator, _gf_inverse(delta))
                locator = scaled
            locator = _poly_add(locator, _poly_scale(previous, delta))
    while locator and locator[0] == 0:
        locator.pop(0)
    return locator


def _error_positions(locator, length):
    """Chien search: which codewords the locator says are wrong.

    The locator's roots are the INVERSES of the error locators, so each
    candidate position is tested directly rather than sweeping the exponent
    range and mapping back. Sweeping is where this went wrong first: an error
    at codeword p roots the locator at alpha to the power -(n-1-p), which for
    most p lies far outside range(n), so the search found nothing and every
    correctable block was refused.
    """
    count = len(locator) - 1
    positions = [p for p in range(length)
                 if _poly_eval(locator, _gf_pow(-(length - 1 - p))) == 0]
    if len(positions) != count:
        raise QRDecodeError(
            "QR error locator names %d errors but %d positions were found"
            % (count, len(positions)))
    return positions


def _correct(block, syndromes, positions):
    """Forney: work out the magnitude of each error and subtract it."""
    coefficients = [len(block) - 1 - p for p in positions]
    locator = [1]
    for c in coefficients:
        locator = _poly_mul(locator, _poly_add([1], [_gf_pow(c), 0]))

    # The error evaluator is (S(x) * Lambda(x)) truncated to the locator's
    # length -- one more coefficient than the error count, not one fewer.
    evaluator = _poly_mul(syndromes[::-1], locator)
    evaluator = evaluator[len(evaluator) - len(locator):]

    magnitudes = [0] * len(block)
    roots = [_gf_pow(-(255 - c)) for c in coefficients]
    for i, root in enumerate(roots):
        inverse = _gf_inverse(root)
        derivative = 1
        for j, other in enumerate(roots):
            if j != i:
                derivative = _gf_mul(derivative, 1 ^ _gf_mul(inverse, other))
        if derivative == 0:
            raise QRDecodeError("QR error magnitude is undefined")
        # Forney is e = X * Omega(X^-1) / Lambda'(X^-1), and the formal
        # derivative of prod(1 + X_k x) evaluated at X_i^-1 is itself
        # X_i * prod_{j != i}(1 + X_j X_i^-1) -- every other term carries a
        # factor of (1 + X_i X_i^-1), which is zero. So the X cancels, and
        # what is left is Omega over that product. Multiplying by X as well,
        # which is what the shape of the formula invites, scales every
        # magnitude by X and corrects nothing.
        magnitudes[positions[i]] = _gf_div(
            _poly_eval(evaluator, inverse), derivative)
    return _poly_add(block, magnitudes)


def rs_correct(block, ec_count):
    """Correct up to ``ec_count // 2`` errors in one codeword block.

    Returns the corrected data codewords, or raises if the damage is beyond
    what the error correction can repair. Raising is the right answer there: a
    block that cannot be corrected cannot be trusted either.
    """
    work = list(block)
    syndromes = _syndromes(work, ec_count)
    if not any(syndromes):
        return work[:len(work) - ec_count]

    locator = _error_locator(syndromes, ec_count)
    errors = len(locator) - 1
    if errors == 0 or errors * 2 > ec_count:
        raise QRDecodeError(
            "too many errors in a QR block to correct (%d, limit %d)"
            % (errors, ec_count // 2))
    positions = _error_positions(locator, len(work))
    work = _correct(work, syndromes, positions)

    if any(_syndromes(work, ec_count)):
        raise QRDecodeError("QR block still fails its checksum after correction")
    return work[:len(work) - ec_count]


# ---------------------------------------------------------------------------
# Finding the grid
# ---------------------------------------------------------------------------
def _binarise(pixels, width, height):
    """A 1 for dark, 0 for light, over the whole image.

    Global rather than blockwise, unlike the barcode reader. A QR carries its
    own error correction and is normally printed on one flat surface, so the
    blockwise threshold that rescues a barcode across uneven lighting mostly
    buys noise here. The midpoint between the fifth and ninety-fifth percentile
    ignores a few hot pixels at each end.
    """
    sample = sorted(pixels[::max(1, len(pixels) // 4096)])
    if not sample:
        raise QRDecodeError("empty image")
    low = sample[len(sample) // 20]
    high = sample[-1 - len(sample) // 20]
    if high - low < 20:
        raise QRDecodeError("no contrast in this image")
    threshold = (low + high) // 2
    return [[1 if pixels[y * width + x] < threshold else 0 for x in range(width)]
            for y in range(height)]


def _bounding_box(matrix, width, height):
    """The extent of the symbol, ignoring the quiet zone around it.

    A QR has a finder pattern in three of its four corners, so the outermost
    dark pixel in every direction belongs to the symbol itself: the box is the
    symbol, exactly, with no arithmetic needed.
    """
    min_x, min_y, max_x, max_y = width, height, -1, -1
    for y in range(height):
        row = matrix[y]
        try:
            first = row.index(1)
        except ValueError:
            continue
        last = width - 1 - row[::-1].index(1)
        if first < min_x:
            min_x = first
        if last > max_x:
            max_x = last
        if min_y > y:
            min_y = y
        max_y = y
    if max_x < 0:
        raise QRDecodeError("no dark pixels in this image")
    return min_x, min_y, max_x, max_y


def _module_size(matrix, box):
    """Module width in pixels, measured off the top-left finder.

    The top row of a QR begins with the finder's solid seven-module edge and
    then a one-module separator that is always light, so the first dark run on
    that row is seven modules and nothing else. That is a far steadier anchor
    than clustering finder centres: it needs one run, not three patterns, and it
    does not care where the symbol sits in the frame.

    Only the solid edge is measured. Sampling a fixed depth and taking the
    median was the first attempt and it is wrong for a reason worth recording:
    a module or two below the top the finder becomes its RING, whose first dark
    run is one module rather than seven. At five pixels per module that mixed
    thirty-five-pixel rows with five-pixel rows and the median came out at five,
    so every symbol measured seven times too wide and no version matched. The
    edge is therefore followed only while it stays wide, which also yields the
    module HEIGHT for free -- the edge is exactly one module tall.
    """
    min_x, min_y, max_x, max_y = box
    first_run = 0
    top = None
    for y in range(min_y, min(min_y + 6, max_y + 1)):
        row = matrix[y]
        if row[min_x] != 1:
            continue
        run = 0
        while min_x + run <= max_x and row[min_x + run] == 1:
            run += 1
        if run > first_run:
            first_run, top = run, y
    if not first_run or top is None:
        raise QRDecodeError("no finder edge along the top of the symbol")

    tall = 0
    for y in range(top, max_y + 1):
        row = matrix[y]
        if row[min_x] != 1:
            break
        run = 0
        while min_x + run <= max_x and row[min_x + run] == 1:
            run += 1
        if run < first_run * 0.8:
            break
        tall += 1

    module = first_run / 7.0
    if tall and abs(tall - module) > max(1.5, module * 0.5):
        raise QRDecodeError(
            "the finder edge is %d pixels tall but %.1f wide per module; the "
            "symbol is not square to the frame" % (tall, module))
    return module


def _grid(matrix, width, height):
    """(origin_x, origin_y, module, size) for a symbol square to the frame."""
    box = _bounding_box(matrix, width, height)
    min_x, min_y, max_x, max_y = box
    module = _module_size(matrix, box)
    if module <= 0:
        raise QRDecodeError("could not measure the module size")

    across = (max_x - min_x + 1) / module
    down = (max_y - min_y + 1) / module
    if abs(across - down) > 1.5:
        raise QRDecodeError(
            "the symbol is %.1f modules wide and %.1f tall; it is not square "
            "to the frame" % (across, down))

    size = int(round((across + down) / 2.0))
    version = (size - 17) / 4.0
    if abs(version - round(version)) > 0.25 or not 1 <= round(version) <= 10:
        raise QRDecodeError(
            "measured %d modules across, which is not a supported QR version"
            % size)
    version = int(round(version))
    size = version * 4 + 17
    # Re-derive the module from the settled size rather than keeping the
    # estimate: over a whole symbol the rounding error compounds, and by the
    # far corner it is enough to sample the neighbouring module.
    module_x = (max_x - min_x + 1) / float(size)
    module_y = (max_y - min_y + 1) / float(size)
    return min_x, min_y, module_x, module_y, size


def _sample(matrix, width, height, origin_x, origin_y, module_x, module_y, size):
    """The module grid, sampled at the centre of each cell."""
    grid = []
    for row in range(size):
        line = []
        for col in range(size):
            x = int(round(origin_x + (col + 0.5) * module_x))
            y = int(round(origin_y + (row + 0.5) * module_y))
            x = 0 if x < 0 else (width - 1 if x >= width else x)
            y = 0 if y < 0 else (height - 1 if y >= height else y)
            line.append(matrix[y][x])
        grid.append(line)
    return grid


# ---------------------------------------------------------------------------
# Reading the symbol
# ---------------------------------------------------------------------------
def _format_candidates(grid):
    """Both copies of the format information, as raw 15-bit values.

    There are two, written in different directions, precisely so that damage to
    one corner does not cost the symbol its mask and level. Reading only the
    first was this decoder's own gap: it worked on every clean symbol and threw
    away the redundancy the specification put there for the dirty ones.
    """
    size = len(grid)
    first = 0
    for i in range(15):
        if i < 6:
            bit = grid[i][8]
        elif i < 8:
            bit = grid[i + 1][8]
        else:
            bit = grid[size - 15 + i][8]
        first |= bit << i

    second = 0
    for i in range(15):
        if i < 8:
            bit = grid[8][size - 1 - i]
        elif i == 8:
            bit = grid[8][7]
        else:
            bit = grid[8][14 - i]
        second |= bit << i
    return first, second


def _read_format(grid):
    """(level, mask) from the format information, BCH-corrected.

    Fifteen bits, five of data and ten of BCH. Every legal value is tried and
    the closest taken, which is the correction the specification describes and
    is cheap at thirty-two candidates. Both copies are offered and the better
    fit wins, so one damaged corner is survivable.
    """
    best, best_distance = None, 99
    for raw in (c ^ FORMAT_MASK for c in _format_candidates(grid)):
        for data in range(32):
            candidate = (data << 10) | _bch(data, 0x537)
            distance = bin(candidate ^ raw).count("1")
            if distance < best_distance:
                best, best_distance = data, distance
    if best_distance > 3:
        raise QRDecodeError("format information is unreadable in both copies")
    level = _LEVEL_FOR_BITS.get((best >> 3) & 0b11)
    mask = best & 0b111
    if level not in ("L", "M"):
        raise QRDecodeError(
            "error-correction level %s is outside this decoder's scope" % level)
    return level, mask


def _unmask(grid, mask, version):
    size = len(grid)
    rule = _MASKS[mask]
    for row in range(size):
        for col in range(size):
            if not _is_function_module(row, col, size, version) and rule(row, col):
                grid[row][col] ^= 1
    return grid


def _read_codewords(grid, version):
    """Walk the zig-zag and rebuild the interleaved codeword stream."""
    size = len(grid)
    bits = []
    upward = True
    col = size - 1
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for c in (col, col - 1):
                if not _is_function_module(row, c, size, version):
                    bits.append(grid[row][c])
        upward = not upward
        col -= 2

    codewords = []
    for i in range(0, len(bits) - 7, 8):
        value = 0
        for bit in bits[i:i + 8]:
            value = (value << 1) | bit
        codewords.append(value)
    return codewords


def _deinterleave(stream, version, level):
    """Undo _interleave: recover the per-block data and error codewords."""
    ec_count, groups = BLOCKS[(level, version)]
    sizes = []
    for count, size in groups:
        sizes.extend([size] * count)
    total_data = sum(sizes)
    blocks = [[] for _ in sizes]

    index = 0
    longest = max(sizes)
    for i in range(longest):
        for b, size in enumerate(sizes):
            if i < size:
                if index >= len(stream):
                    raise QRDecodeError("QR data ended early")
                blocks[b].append(stream[index])
                index += 1

    ec_blocks = [[] for _ in sizes]
    for i in range(ec_count):
        for b in range(len(sizes)):
            if index >= len(stream):
                raise QRDecodeError("QR error-correction data ended early")
            ec_blocks[b].append(stream[index])
            index += 1

    return [blocks[b] + ec_blocks[b] for b in range(len(sizes))], ec_count, total_data


def _decode_payload(data, version):
    """Read the mode/length header and pull the text out."""
    bits = []
    for value in data:
        for i in range(7, -1, -1):
            bits.append((value >> i) & 1)

    pos = 0

    def take(n):
        nonlocal pos
        if pos + n > len(bits):
            raise QRDecodeError("QR payload ended mid-field")
        out = 0
        for bit in bits[pos:pos + n]:
            out = (out << 1) | bit
        pos += n
        return out

    out = bytearray()
    while pos + 4 <= len(bits):
        mode = take(4)
        if mode == 0b0000:                      # terminator
            break
        if mode != 0b0100:
            raise QRDecodeError(
                "QR mode %s is outside this decoder's scope (byte mode only)"
                % bin(mode))
        length_bits = 8 if version <= 9 else 16
        length = take(length_bits)
        for _ in range(length):
            out.append(take(8))
        # The encoder writes one segment and then the terminator; anything
        # after this is padding.
        break
    if not out:
        raise QRDecodeError("QR carried no data")
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError:
        return out.decode("latin-1")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def decode(pixels, width, height):
    """Read a QR from a grayscale image. Returns a dict describing what it found.

    Never raises for an ordinary failure -- a photograph with no QR in it is the
    normal case, not an error -- so callers get ``ok: False`` and a reason.
    """
    try:
        matrix = _binarise(pixels, width, height)
        origin_x, origin_y, module_x, module_y, size = _grid(matrix, width, height)
        version = (size - 17) // 4
        grid = _sample(matrix, width, height, origin_x, origin_y,
                       module_x, module_y, size)
        level, mask = _read_format(grid)
        _unmask(grid, mask, version)
        stream = _read_codewords(grid, version)
        blocks, ec_count, total_data = _deinterleave(stream, version, level)
        data = []
        corrected = 0
        for block in blocks:
            before = list(block)
            fixed = rs_correct(block, ec_count)
            corrected += sum(1 for a, b in zip(before, fixed) if a != b)
            data.extend(fixed)
        text = _decode_payload(data[:total_data], version)
        return {
            "ok": True, "text": text, "version": version, "level": level,
            "mask": mask, "module_pixels": round((module_x + module_y) / 2.0, 2),
            "modules": size, "corrected_codewords": corrected,
        }
    except QRDecodeError as err:
        return {"ok": False, "text": None, "reason": str(err)}
    except Exception as err:                     # noqa: BLE001
        # A malformed image should be a miss, not a traceback out of a route.
        return {"ok": False, "text": None,
                "reason": "%s: %s" % (err.__class__.__name__, err)}
