"""
Grayscale image loading, standard library only
==============================================
Turns a PNG or a baseline JPEG into one byte per pixel, so a real label
photograph can be fed to :mod:`core.barcode_decode` without a camera and
without a third-party imaging package.

Why this exists
---------------
The decoder is tested against rendered barcodes, which are clean by
construction. A photograph of a thermal label on a cardboard box is not: the
print is worn, the paper is not white, the lighting is uneven and the phone's
JPEG encoder has smeared 8x8 blocks over all of it. Those are the frames the
warehouse actually meets, and until they could be loaded there was no way to
check the decoder against one.

PNG needs only ``zlib``, which is standard library. JPEG needs an actual
baseline decoder -- Huffman, dequantisation, inverse DCT -- which is what most
of this file is. That is a lot of code to avoid a dependency, and it is the same
trade the rest of this project makes: ``core/qrcode.py`` draws QR codes,
``core/barcode.py`` draws barcodes, ``ml/`` implements five classifiers, all
from scratch, because the zero-dependency rule is the point rather than an
inconvenience.

**Only the luma channel is reconstructed.** A barcode is a brightness pattern,
so the chroma components are Huffman-skipped rather than decoded, upsampled and
converted. That is most of the work of a JPEG decoder avoided, for an output
that is exactly what the barcode reader wants anyway.

Progressive JPEG is refused rather than half-read. It is a different scan
structure and a wrong answer would look like a decode failure.
"""

import struct
import zlib


class ImageError(Exception):
    pass


# ---------------------------------------------------------------------------
# PNG
# ---------------------------------------------------------------------------
def _png_gray(data):
    """Grayscale bytes, width, height for a non-interlaced PNG."""
    pos = 8
    idat, palette = [], None
    width = height = depth = colour = interlace = None

    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        kind = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, colour, _c, _f, interlace = struct.unpack(
                ">IIBBBBB", chunk)
        elif kind == b"PLTE":
            palette = chunk
        elif kind == b"IDAT":
            idat.append(chunk)
        elif kind == b"IEND":
            break
        pos += 12 + length

    if width is None:
        raise ImageError("PNG has no header chunk.")
    if interlace:
        raise ImageError("Interlaced PNG is not supported.")
    if colour == 3 and palette is None:
        raise ImageError("Palette PNG with no palette.")

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(colour)
    if channels is None:
        raise ImageError("Unknown PNG colour type %s." % colour)

    raw = zlib.decompress(b"".join(idat))
    bits_per_pixel = depth * channels
    stride = (width * bits_per_pixel + 7) // 8
    step = max(1, bits_per_pixel // 8)

    # Undo the per-scanline filters. Each line is filtered against the one above
    # it, so they have to be reconstructed in order.
    lines = []
    previous = bytearray(stride)
    at = 0
    for _y in range(height):
        if at >= len(raw):
            raise ImageError("PNG data ended early.")
        filter_type = raw[at]
        at += 1
        line = bytearray(raw[at:at + stride])
        at += stride
        if len(line) < stride:
            raise ImageError("PNG scanline is short.")
        if filter_type == 1:                      # Sub
            for i in range(step, stride):
                line[i] = (line[i] + line[i - step]) & 255
        elif filter_type == 2:                    # Up
            for i in range(stride):
                line[i] = (line[i] + previous[i]) & 255
        elif filter_type == 3:                    # Average
            for i in range(stride):
                left = line[i - step] if i >= step else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 255
        elif filter_type == 4:                    # Paeth
            for i in range(stride):
                a = line[i - step] if i >= step else 0
                b = previous[i]
                c = previous[i - step] if i >= step else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if (pa <= pb and pa <= pc)
                                      else (b if pb <= pc else c))) & 255
        lines.append(line)
        previous = line

    grey = bytearray(width * height)
    maximum = (1 << depth) - 1
    for y, line in enumerate(lines):
        row = y * width
        for x in range(width):
            if depth == 8:
                base = x * channels
                if colour in (0, 4):
                    value = line[base]
                elif colour in (2, 6):
                    value = (77 * line[base] + 150 * line[base + 1]
                             + 29 * line[base + 2]) >> 8
                else:
                    i3 = line[base] * 3
                    value = (77 * palette[i3] + 150 * palette[i3 + 1]
                             + 29 * palette[i3 + 2]) >> 8
            elif depth == 16:
                base = x * channels * 2
                if colour in (0, 4):
                    value = line[base]
                else:
                    value = (77 * line[base] + 150 * line[base + 2]
                             + 29 * line[base + 4]) >> 8
            else:                                  # 1, 2 or 4 bits per sample
                per_byte = 8 // depth
                packed = line[x // per_byte]
                shift = 8 - depth * (x % per_byte + 1)
                index = (packed >> shift) & maximum
                if colour == 3:
                    i3 = index * 3
                    value = (77 * palette[i3] + 150 * palette[i3 + 1]
                             + 29 * palette[i3 + 2]) >> 8
                else:
                    value = index * (255 // maximum)
            grey[row + x] = value
    return bytes(grey), width, height


# ---------------------------------------------------------------------------
# Baseline JPEG
# ---------------------------------------------------------------------------
#: The order coefficients are stored in within a block. Undoing it is the first
#: thing that has to happen after Huffman decoding.
ZIGZAG = [
    0,  1,  8, 16,  9,  2,  3, 10, 17, 24, 32, 25, 18, 11,  4,  5,
    12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13,  6,  7, 14, 21, 28,
    35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51,
    58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63,
]


class _Huffman:
    """A JPEG Huffman table, as a code -> value map keyed by (length, code)."""

    def __init__(self, counts, symbols):
        self.lookup = {}
        code = 0
        k = 0
        for length in range(1, 17):
            for _ in range(counts[length - 1]):
                self.lookup[(length, code)] = symbols[k]
                code += 1
                k += 1
            code <<= 1


class _BitReader:
    """Reads entropy-coded JPEG data one bit at a time.

    Byte stuffing is the wrinkle: a literal 0xFF in the data is written as
    ``FF 00``, and any other ``FF xx`` is a marker that ends the run.
    """

    def __init__(self, data, start):
        self.data = data
        self.at = start
        self.bits = 0
        self.count = 0

    def bit(self):
        if self.count == 0:
            if self.at >= len(self.data):
                return 0                      # ran out: pad with zeros
            byte = self.data[self.at]
            self.at += 1
            if byte == 0xFF:
                nxt = self.data[self.at] if self.at < len(self.data) else 0
                if nxt == 0x00:
                    self.at += 1
                else:
                    return 0                  # a marker; the scan is over
            self.bits = byte
            self.count = 8
        self.count -= 1
        return (self.bits >> self.count) & 1

    def receive(self, n):
        value = 0
        for _ in range(n):
            value = (value << 1) | self.bit()
        return value

    def decode(self, table):
        code = 0
        for length in range(1, 17):
            code = (code << 1) | self.bit()
            symbol = table.lookup.get((length, code))
            if symbol is not None:
                return symbol
        raise ImageError("Bad Huffman code in the JPEG scan.")

    def align(self):
        self.count = 0


def _extend(value, n):
    """JPEG stores signed coefficients as magnitude plus an implied sign bit."""
    if n == 0:
        return 0
    return value if value >= (1 << (n - 1)) else value - (1 << n) + 1


def _idct_2d(block):
    """Inverse DCT for one 8x8 block, separable rows then columns.

    Written plainly rather than as one of the fast factorisations. The decoder
    that consumes this is itself pure Python and takes far longer, so clarity
    is worth more here than the constant factor.
    """
    import math

    # Cosine basis, built once and cached on the function.
    table = getattr(_idct_2d, "_cos", None)
    if table is None:
        table = [[math.cos((2 * x + 1) * u * math.pi / 16)
                  * (0.353553390593 if u == 0 else 0.5)
                  for u in range(8)] for x in range(8)]
        _idct_2d._cos = table

    tmp = [0.0] * 64
    for y in range(8):
        row = y * 8
        for x in range(8):
            total = 0.0
            for u in range(8):
                c = block[row + u]
                if c:
                    total += c * table[x][u]
            tmp[row + x] = total
    out = [0] * 64
    for x in range(8):
        for y in range(8):
            total = 0.0
            for v in range(8):
                c = tmp[v * 8 + x]
                if c:
                    total += c * table[y][v]
            value = int(total + 128.5)
            out[y * 8 + x] = 0 if value < 0 else (255 if value > 255 else value)
    return out


def _jpeg_gray(data):
    """Grayscale bytes, width, height for a baseline JPEG.

    Only the luma component is reconstructed; chroma is Huffman-skipped.
    """
    quant = {}
    huff_dc, huff_ac = {}, {}
    frame = None
    restart_interval = 0
    at = 2

    while at < len(data):
        if data[at] != 0xFF:
            at += 1
            continue
        marker = data[at + 1]
        at += 2
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            continue
        if marker == 0xD9:
            break
        (length,) = struct.unpack(">H", data[at:at + 2])
        segment = data[at + 2:at + length]

        if marker == 0xDB:                                     # quant tables
            i = 0
            while i < len(segment):
                precision, table_id = segment[i] >> 4, segment[i] & 15
                i += 1
                if precision:
                    values = list(struct.unpack(">64H", segment[i:i + 128]))
                    i += 128
                else:
                    values = list(segment[i:i + 64])
                    i += 64
                quant[table_id] = values
        elif marker == 0xC4:                                   # huffman tables
            i = 0
            while i < len(segment):
                kind, table_id = segment[i] >> 4, segment[i] & 15
                counts = list(segment[i + 1:i + 17])
                total = sum(counts)
                symbols = list(segment[i + 17:i + 17 + total])
                table = _Huffman(counts, symbols)
                (huff_ac if kind else huff_dc)[table_id] = table
                i += 17 + total
        elif marker == 0xC0 or marker == 0xC1:                 # baseline frame
            precision, height, width, count = struct.unpack(">BHHB", segment[:6])
            components = []
            for c in range(count):
                cid, sampling, qt = segment[6 + c * 3:9 + c * 3]
                components.append({
                    "id": cid, "h": sampling >> 4, "v": sampling & 15, "q": qt,
                })
            frame = {"w": width, "h": height, "components": components}
        elif marker in (0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB,
                        0xCD, 0xCE, 0xCF):
            raise ImageError(
                "This JPEG is progressive or arithmetic-coded, which this "
                "reader does not decode. Re-save it as a baseline JPEG or a PNG.")
        elif marker == 0xDD:                                   # restart interval
            (restart_interval,) = struct.unpack(">H", segment[:2])
        elif marker == 0xDA:                                   # start of scan
            if frame is None:
                raise ImageError("JPEG scan before its frame header.")
            count = segment[0]
            scan = []
            for c in range(count):
                cid, tables = segment[1 + c * 2:3 + c * 2]
                scan.append({"id": cid, "dc": tables >> 4, "ac": tables & 15})
            return _jpeg_scan(data, at + length, frame, scan, quant,
                              huff_dc, huff_ac, restart_interval)
        at += length

    raise ImageError("JPEG has no image scan.")


def _jpeg_scan(data, start, frame, scan, quant, huff_dc, huff_ac, restart):
    width, height = frame["w"], frame["h"]
    components = frame["components"]
    h_max = max(c["h"] for c in components)
    v_max = max(c["v"] for c in components)
    mcu_w, mcu_h = 8 * h_max, 8 * v_max
    across = (width + mcu_w - 1) // mcu_w
    down = (height + mcu_h - 1) // mcu_h

    luma = components[0]
    luma_scan = next((s for s in scan if s["id"] == luma["id"]), scan[0])
    # The luma plane at its own resolution, before upsampling.
    plane_w, plane_h = across * luma["h"] * 8, down * luma["v"] * 8
    plane = bytearray(plane_w * plane_h)

    reader = _BitReader(data, start)
    predictions = {c["id"]: 0 for c in components}
    block = [0] * 64
    units = 0

    for my in range(down):
        for mx in range(across):
            if restart and units and units % restart == 0:
                reader.align()
                # Skip the RSTn marker and reset the DC predictors.
                while (reader.at + 1 < len(data)
                       and not (data[reader.at] == 0xFF
                                and 0xD0 <= data[reader.at + 1] <= 0xD7)):
                    reader.at += 1
                reader.at += 2
                predictions = {c["id"]: 0 for c in components}
            units += 1

            for component in components:
                entry = next((s for s in scan if s["id"] == component["id"]), None)
                if entry is None:
                    continue
                table_q = quant.get(component["q"], [1] * 64)
                dc_table = huff_dc.get(entry["dc"])
                ac_table = huff_ac.get(entry["ac"])
                if dc_table is None or ac_table is None:
                    raise ImageError("JPEG scan names a Huffman table it never defined.")
                is_luma = component["id"] == luma["id"]

                for by in range(component["v"]):
                    for bx in range(component["h"]):
                        for i in range(64):
                            block[i] = 0
                        size = reader.decode(dc_table)
                        diff = _extend(reader.receive(size), size) if size else 0
                        predictions[component["id"]] += diff
                        block[0] = predictions[component["id"]] * table_q[0]

                        k = 1
                        while k < 64:
                            symbol = reader.decode(ac_table)
                            run, size = symbol >> 4, symbol & 15
                            if size == 0:
                                if run == 15:
                                    k += 16
                                    continue
                                break                      # end of block
                            k += run
                            if k > 63:
                                break
                            block[ZIGZAG[k]] = (
                                _extend(reader.receive(size), size) * table_q[k])
                            k += 1

                        if not is_luma:
                            continue                       # chroma: skipped
                        pixels = _idct_2d(block)
                        ox = (mx * component["h"] + bx) * 8
                        oy = (my * component["v"] + by) * 8
                        for row in range(8):
                            target = (oy + row) * plane_w + ox
                            if oy + row >= plane_h:
                                break
                            plane[target:target + 8] = bytes(pixels[row * 8:row * 8 + 8])

    # Upsample the luma plane to the full image size. Nearest-neighbour is
    # enough: the plane is usually already full resolution (4:2:0 subsamples
    # chroma, not luma), so this is normally a straight crop.
    scale_x = luma["h"] / float(h_max)
    scale_y = luma["v"] / float(v_max)
    grey = bytearray(width * height)
    for y in range(height):
        src_row = int(y * scale_y) * plane_w
        target = y * width
        if scale_x == 1.0:
            grey[target:target + width] = plane[src_row:src_row + width]
        else:
            for x in range(width):
                grey[target + x] = plane[src_row + int(x * scale_x)]
    return bytes(grey), width, height


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def load_gray(path):
    """One byte per pixel, row-major, for a PNG or baseline JPEG file.

    Returns ``(pixels, width, height)``.
    """
    with open(path, "rb") as handle:
        data = handle.read()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return _png_gray(data)
    if data[:2] == b"\xff\xd8":
        return _jpeg_gray(data)
    raise ImageError("Not a PNG or JPEG: %s" % path)
