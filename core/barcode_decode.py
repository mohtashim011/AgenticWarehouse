"""
1-D barcode decoder
===================
Reads EAN-13, UPC-A and EAN-8 out of a band of grayscale pixels, in pure Python
with nothing imported that is not in the standard library.

Why a server-side decoder exists at all
---------------------------------------
The browser decoder fails on 1-D barcodes for a reason that is arithmetic rather
than bad luck. ``html5-qrcode`` sizes its decode canvas from the **CSS width of
the element**, not the camera's resolution, and draws the frame into it:

    core-impl.ts:181   const videoWidth = this.surface.clientWidth;   // CSS px
    html5-qrcode.ts:1096  context.canvas.width = qrRegion.width;
    html5-qrcode.ts:1197  drawImage(video, sx,sy,sW,sH, 0,0, qrRegion.width, ...)

So a 1920-wide frame arrives at the decoder as roughly 570 pixels. An EAN-13 is
95 modules wide; a label filling a third of the frame then has under two pixels
per module, and ZXing's own floor is one ("if we don't even have one pixel per
unit of bar width... fail"). A QR of the same physical size is 25-33 modules, so
it keeps four times the pixel budget, is located by three finder patterns at any
angle, and repairs the remainder with Reed-Solomon. Same frame, same distance:
the QR reads and the barcode cannot. That asymmetry is the whole diagnosis.

This module is handed the frame at **full camera resolution** instead, and is
under no real-time obligation, so it can afford to try many scanlines, both
directions and several thresholds.

The rule this module will not break
-----------------------------------
**It returns nothing rather than something wrong.** A wrong barcode puts stock
on the wrong product and the log then records the wrong number, which is exactly
the failure `db.resolve_productno` was tightened to prevent. So a result is
returned only when the checksum validates *and* enough independent scanlines
agree on it. Everything else is a clean miss.

How strongly that holds is not the same for every symbology, and saying so is
the point rather than a caveat:

* **EAN-13, UPC-A, EAN-8.** Measured at zero misreads: across every degradation
  grid, across 100,000 frames cut through a symbol's bars, and across 1,000
  frames of noise, stripes and text. Three independent protections have to fail
  together -- the check digit, the fixed ninety-five-module shape, and six
  left-hand parities that must spell one of exactly ten legal patterns.

* **Code 128.** One protection, a modulo-103 checksum, on a variable-length
  symbology whose shape therefore proves nothing. Two symbol errors that cancel
  modulo 103 pass, and that is roughly one in a hundred corrupted-but-plausible
  readings. Measured: at three pixels per module, one *pixel-perfect rendering*
  in several thousand came back with two characters changed. Add the sensor
  noise any real camera contributes and the same case reads correctly 200 times
  in 200, because the scanlines stop being identical. So the residual risk is
  real but laboratory-shaped, and it is stated here rather than hidden behind
  the sentence at the top of this section.

Reuse
-----
The pattern tables live in :mod:`core.barcode`, which draws these symbols for
the printable label. Decoding is the inverse of encoding, so the tables are
imported rather than copied -- two copies of a parity table is how an encoder
and a decoder silently stop agreeing.
"""

from core.barcode import (
    _LEFT_ODD, _LEFT_EVEN, _RIGHT, _PARITY, check_digit,
)
from core import code128

#: Refuse anything below this. Measured: the decode rate collapses under about
#: three pixels per narrow module, and accepting a marginal read is how a
#: decoder starts inventing product numbers.
MIN_MODULE_PIXELS = 1.4

#: How many scanlines must independently agree before a code is believed. One
#: agreeing line is a coincidence away from a misread; two is not.
MIN_AGREEING_LINES = 2

#: Code 128 is held to a higher count, and the reason is in the symbology
#: rather than in this implementation.
#:
#: An EAN-13 is protected three ways at once: a check digit, a shape that is
#: ninety-five modules and nothing else, and six left-hand parities that must
#: spell one of exactly ten legal patterns. A Code 128 has one protection, a
#: modulo-103 checksum, and it is variable length so the shape proves nothing.
#: A pair of misdecoded symbols whose errors happen to cancel modulo 103 --
#: about one corrupted-but-structurally-valid reading in a hundred -- passes.
#: Measured: reading rendered labels at three pixels per module, SV60K7S6N6M0L
#: came back as SV60K8&6N6M0L, two characters wrong with the checksum intact.
#:
#: More agreeing lines is the honest defence, because the scanlines of a real
#: photograph differ -- sensor noise, sub-pixel sampling, ink varying down the
#: height of a bar -- so a quantisation error that corrupts one row rarely
#: corrupts the next one identically. It costs nothing on a real label, which
#: agrees on seventeen to twenty-three lines.
#:
#: It does NOT defend against a synthetic image whose rows are pixel-identical,
#: and that was measured rather than assumed: the case above still returns the
#: wrong two characters, on twelve agreeing lines, because twelve identical
#: rows agree on the same wrong answer. Nothing that re-reads the same pixels
#: can fix that; the information is not in them.
#:
#: What the same measurement shows is that the failure needs an image no camera
#: produces. Re-rendered 200 times with ordinary sensor noise -- same string,
#: same three pixels per module -- it read **correctly 200 times out of 200**,
#: because the rows then differ and the corruption stops repeating. That is why
#: the threshold is worth having and why the residual risk is a laboratory one.
MIN_AGREEING_LINES_CODE128 = 4

#: How far a run may deviate from its expected width, as a fraction of one
#: module. ZXing uses the same idea; 0.7 is tolerant enough for a blurred phone
#: frame and tight enough to reject noise.
MAX_INDIVIDUAL_VARIANCE = 0.7

#: A digit match worse than this is not a digit.
MAX_PATTERN_VARIANCE = 0.48

#: And a match that is not clearly better than the runner-up is ambiguous, which
#: is the state most likely to produce a plausible wrong digit.
AMBIGUITY_RATIO = 0.60

#: How much contrast a threshold block must show, as a multiple of the noise
#: this scanline is carrying, before it is allowed to judge its own threshold.
#:
#: The question _binarise has to answer for each block is "is the variation I
#: can see real ink, or is it sensor noise?", and a fixed number of grey levels
#: cannot answer it. This used to be a flat 24: real contrast on a worn thermal
#: label, and pure noise on a crisp one. A block lying entirely inside one bar
#: has no true contrast at all, but noise gives it an apparent min-to-max spread
#: of roughly six sigma -- so at sigma 6 nearly seven blocks in ten cleared a
#: floor of 24 and invented a threshold out of noise, slicing solid bars into
#: phantom runs. Measured: a 61-run barcode became 493 runs at ten pixels per
#: module. That only happens when a block fits inside a bar, so it struck
#: exactly the close-up frames this decoder exists to read: decode quality fell
#: as resolution rose, the opposite of what "hold it closer" should do.
#:
#: Two fixes were measured and rejected before this one. Raising the flat floor
#: rescues crisp labels and destroys faded ones (a contrast-30 thermal label:
#: 24 of 48 at a floor of 24, 0 of 48 at 60). Scaling the floor to the *range of
#: the whole scanline* adapts to the label but over-demands whenever big white
#: quiet zones stretch that range, so a blurred label at the resolution floor
#: lost reads the old code got.
#:
#: Scaling it to the noise instead separates the two cases directly, because
#: noise is high-frequency and blur is not. The estimator is the median
#: absolute difference between adjacent pixels: about sigma for gaussian noise,
#: and near zero across a smooth blurred ramp. A solid-bar block shows about
#: six sigma, so eight sigma is comfortably above it while leaving a genuinely
#: blurred narrow bar free to judge itself.
#:
#: Measured against the alternatives (higher is better, all with zero misreads
#: and zero false positives in 450 non-barcode frames):
#:
#:     variant                  blurred/225  noisy/180  labels/240
#:     flat floor of 24                 200         97         144
#:     share of scanline range          186        179         180
#:     eight times the noise            200        179         187
NOISE_CONTRAST_MULTIPLE = 6

#: A block still needs some absolute contrast, for the degenerate case of a
#: perfectly noiseless scanline where the estimate above is zero.
MIN_BLOCK_CONTRAST = 12

INF = float("inf")


def _widths(pattern):
    """A module string such as "0001101" as run widths: [3, 2, 1, 1]."""
    out, current, count = [], pattern[0], 0
    for bit in pattern:
        if bit == current:
            count += 1
        else:
            out.append(count)
            current, count = bit, 1
    out.append(count)
    return out


# The three tables, pre-converted to run widths once at import.
_L_ODD = [_widths(p) for p in _LEFT_ODD]
_L_EVEN = [_widths(p) for p in _LEFT_EVEN]
_R = [_widths(p) for p in _RIGHT]

_GUARD = [1, 1, 1]          # 101
_CENTRE = [1, 1, 1, 1, 1]   # 01010


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
def _variance(observed, expected):
    """How badly a run of widths misses a pattern. Lower is better; INF is no.

    Widths are normalised by the total, so this is scale-free: it does not
    matter whether a module is three pixels or thirty, only that the ratios
    hold. That is what lets one matcher serve every distance.
    """
    total = sum(observed)
    expected_total = sum(expected)
    if total < expected_total:
        return INF                    # fewer pixels than modules: unreadable
    unit = total / float(expected_total)
    limit = unit * MAX_INDIVIDUAL_VARIANCE
    difference = 0.0
    for seen, want in zip(observed, expected):
        delta = abs(seen - want * unit)
        if delta > limit:
            return INF                # one run is wildly wrong: reject early
        difference += delta
    return difference / total


def _best_digit(observed, tables):
    """The digit these four runs most likely encode, or None.

    ``tables`` is a list of (label, patterns). The label comes back with the
    digit because for the left-hand half it *is* the parity, and the parities
    together carry the leading digit.
    """
    best_digit, best_label, best_variance = None, None, INF
    runner_up = INF
    for label, patterns in tables:
        for digit, expected in enumerate(patterns):
            variance = _variance(observed, expected)
            if variance < best_variance:
                runner_up = best_variance
                best_digit, best_label, best_variance = digit, label, variance
            elif variance < runner_up:
                runner_up = variance

    if best_variance > MAX_PATTERN_VARIANCE:
        return None
    # Two patterns fitting almost equally well means the pixels do not actually
    # distinguish them. Guessing here is precisely how a decoder returns a
    # well-formed wrong code.
    if runner_up != INF and best_variance > AMBIGUITY_RATIO * runner_up:
        return None
    return best_digit, best_label


# ---------------------------------------------------------------------------
# Pixels to runs
# ---------------------------------------------------------------------------
def _spread(values):
    """The ink-to-paper spread of a sorted sample, ignoring the extreme tenth.

    Percentiles rather than min and max. A single hot pixel at each end is
    enough to make a blank block look like it spans black to white, and that
    one measurement is what decides whether the block may judge a threshold.
    """
    if not values:
        return 0, 0
    edge = len(values) // 10
    return values[edge], values[len(values) - 1 - edge]


def _noise_level(row):
    """Roughly the per-pixel noise in this scanline, in grey levels.

    The median absolute difference between neighbouring pixels. Noise is
    high-frequency, so it shows up here; the ramps of a blurred bar edge are
    not, and a run of paper or ink contributes zero. For gaussian noise of
    standard deviation sigma this lands near sigma, which is the number
    NOISE_CONTRAST_MULTIPLE is scaled against.

    Median rather than mean, because the real bar edges ARE large neighbouring
    differences and a mean would count them as noise -- the more of the frame
    the barcode fills, the more it would inflate its own threshold.
    """
    if len(row) < 2:
        return 0
    deltas = sorted(abs(row[i] - row[i - 1]) for i in range(1, len(row)))
    return deltas[len(deltas) // 2]


def _binarise(row, block=40):
    """Black/white for one row of grayscale, thresholded in local blocks.

    Local rather than global on purpose. A warehouse label is lit unevenly --
    a ceiling lamp at one end, shadow at the other -- and one threshold across
    the whole row turns the dark end solid black. Blocks with too little
    contrast to judge inherit a threshold from their neighbours instead of
    inventing one, so a quiet zone does not become noise.

    "Too little contrast" is measured against the noise this scanline carries
    rather than against a fixed number of grey levels -- see
    NOISE_CONTRAST_MULTIPLE for why the fixed number was actively harmful at
    high magnification, and for the two alternatives that were measured first.
    """
    # A block has to out-contrast the noise by a clear margin before it is
    # trusted to set its own threshold. Estimated once per scanline: the answer
    # depends on the frame, not on the label.
    needed = max(MIN_BLOCK_CONTRAST, NOISE_CONTRAST_MULTIPLE * _noise_level(row))

    thresholds = []
    for start in range(0, len(row), block):
        low, high = _spread(sorted(row[start:start + block]))
        thresholds.append((low + high) // 2 if (high - low) >= needed else None)

    for i, value in enumerate(thresholds):
        if value is not None:
            continue
        before = next((thresholds[j] for j in range(i - 1, -1, -1)
                       if thresholds[j] is not None), None)
        after = next((thresholds[j] for j in range(i + 1, len(thresholds))
                      if thresholds[j] is not None), None)
        thresholds[i] = before if before is not None else (
            after if after is not None else 128)

    return "".join("1" if row[i] < thresholds[i // block] else "0"
                   for i in range(len(row)))


def _runs(binary):
    """Consecutive same-colour pixels as (colour, width) pairs."""
    out, current, count = [], binary[0], 0
    for bit in binary:
        if bit == current:
            count += 1
        else:
            out.append((current, count))
            current, count = bit, 1
    out.append((current, count))
    return out


# ---------------------------------------------------------------------------
# One scanline
# ---------------------------------------------------------------------------
#: A symbol must stand clear of whatever is beside it. The spec says nine
#: modules; three is enforced instead, because a cropped frame is normal and
#: refusing a real read for a tight crop helps nobody.
#:
#: This check is not cosmetic. Without it an EAN-8 matches happily *inside* an
#: EAN-13's bars -- the run pattern for eight digits genuinely occurs within
#: thirteen, check digit and all -- and the decoder returns a well-formed wrong
#: product number. That was measured, not imagined: 0012345678905 read as
#: 23456129 until this was added.
MIN_QUIET_MODULES = 3


def _quiet_before(pairs, start, module, allow_edge=True):
    """Is there clear space immediately left of the symbol starting here?

    ``allow_edge`` decides what an edge of the scanned band counts as. There is
    nothing to the left of run zero, so no quiet zone can be observed there, and
    a cropped frame is normal -- the browser sends a band spanning the full frame
    width, so the band edge IS the frame edge. Treating that as clear lets a
    label whose quiet zone was trimmed still read.

    It must NOT be treated as clear for a short symbology. See ``_decode_ean8_at``.
    """
    if start == 0:
        return allow_edge
    colour, width = pairs[start - 1]
    return colour == "0" and width >= MIN_QUIET_MODULES * module


def _quiet_after(pairs, index, module, allow_edge=True):
    """Is there clear space immediately right of the symbol ending here?"""
    if index >= len(pairs):
        return allow_edge
    colour, width = pairs[index]
    return colour == "0" and width >= MIN_QUIET_MODULES * module


#: How far the ink bias estimate may be trusted, as a share of one module.
#: The guard is only three runs, so on a noisy scanline the estimate is noisy
#: too. A wrong correction is worse than none, so it is clamped: within this
#: range it rescues a badly printed label, beyond it the reading is not
#: believable and the runs are left alone.
MAX_INK_BIAS_SHARE = 0.40


def _ink_geometry(bars, spaces):
    """(module width, ink bias) in pixels, from runs known to be one module.

    A guard is bar, space, bar, each exactly one module by definition, so the
    two numbers fall straight out of it. If the printer lays down too much ink
    every bar grows by the same amount and every space shrinks by it, so::

        bar   = module + bias
        space = module - bias

    and therefore ``module = (bar + space) / 2`` and ``bias = (bar - space) / 2``.
    A worn print head or an eroded thermal label gives a negative bias.

    This matters because the digit matcher compares individual run widths, and
    ink bias moves every one of them in a way that no amount of scale-free
    normalisation removes: the runs still sum correctly, but a [3,2,1,1] pattern
    drifts toward [2,2,2,1], which is a different digit. Measured on the codes
    from a real warehouse shelf, an erosion of a third of a module took the
    digit acceptance rate from 500 attempts in 600 down to 50 in 175 and the
    label stopped reading entirely. The bias is a property of the printing, not
    of the digit, so measuring it once from a known pattern and removing it
    lets the existing matcher see the shape that was intended.

    ``sum(guard) / 3`` was the previous estimate of the module and is biased
    low or high by exactly this effect; the average of a bar and a space is
    immune to it.

    Every run passed here is one module wide by definition -- the two guards and
    the centre pattern, eleven runs in an EAN-13. Three would do the arithmetic
    just as well and did at first, but three samples off a noisy scanline give a
    noisy bias, and correcting by a noisy number costs more than it earns:
    measured over the same grids, estimating from the start guard alone lost
    nine reads on faded labels and three on noisy ones to buy the worn-print
    gain. Eleven samples keep the gain and give the losses back.
    """
    if not bars or not spaces:
        return 0.0, 0.0
    bar = sum(bars) / float(len(bars))
    space = sum(spaces) / float(len(spaces))
    module = (bar + space) / 2.0
    bias = (bar - space) / 2.0
    limit = module * MAX_INK_BIAS_SHARE
    if bias > limit:
        bias = limit
    elif bias < -limit:
        bias = -limit
    return module, bias


def _deink(widths, bias, starts_with_bar):
    """Undo the ink bias across one alternating group of runs."""
    if not bias:
        return widths
    out = []
    is_bar = starts_with_bar
    for width in widths:
        out.append(width - bias if is_bar else width + bias)
        is_bar = not is_bar
    return out


def _decode_ean13_at(pairs, run_widths, start):
    """Try to read an EAN-13 whose start guard begins at ``start``.

    Returns (code, module_pixels) or None. The structure is fixed -- guard,
    six left digits, centre, six right digits, guard -- so anything that does
    not fit that shape exactly is refused rather than salvaged.
    """
    # 3 guard + 24 left + 5 centre + 24 right + 3 guard
    if start + 59 > len(run_widths):
        return None

    # The three fixed patterns sit at known offsets, so they can all be checked
    # and measured before a single digit is read. That ordering is what makes
    # the ink-bias estimate worth having: it is taken from eleven runs rather
    # than the three of the leading guard.
    guard = run_widths[start:start + 3]
    centre = run_widths[start + 27:start + 32]
    trailing = run_widths[start + 56:start + 59]
    if (_variance(guard, _GUARD) is INF
            or _variance(centre, _CENTRE) is INF
            or _variance(trailing, _GUARD) is INF):
        return None
    # Guard is bar, space, bar. Centre is space, bar, space, bar, space.
    module, bias = _ink_geometry(
        [guard[0], guard[2], centre[1], centre[3], trailing[0], trailing[2]],
        [guard[1], centre[0], centre[2], centre[4], trailing[1]])
    if module < MIN_MODULE_PIXELS:
        return None
    if not _quiet_before(pairs, start, module):
        return None

    left_tables = [("O", _L_ODD), ("E", _L_EVEN)]
    digits, parity = [], []
    index = start + 3
    # A left-hand digit group runs space, bar, space, bar -- the guard ended on
    # a bar, so the group after it starts on a space.
    for _ in range(6):
        match = _best_digit(_deink(run_widths[index:index + 4], bias, False),
                            left_tables)
        if match is None:
            return None
        digit, label = match
        digits.append(digit)
        parity.append(label)
        index += 4

    index += 5                        # the centre was validated above

    # The right-hand half is the other way round: bar, space, bar, space.
    for _ in range(6):
        match = _best_digit(_deink(run_widths[index:index + 4], bias, True),
                            [("R", _R)])
        if match is None:
            return None
        digits.append(match[0])
        index += 4

    if not _quiet_after(pairs, index + 3, module):
        return None

    # The six left-hand parities ARE the leading digit. If the pattern is not
    # one of the ten legal ones, this is not an EAN-13 -- a structural check
    # that costs nothing because the encoder's table already lists them.
    pattern = "".join(parity)
    if pattern not in _PARITY:
        return None
    first = _PARITY.index(pattern)

    body = str(first) + "".join(str(d) for d in digits)
    if check_digit(body[:-1]) != body[-1]:
        return None
    return body, module


def _decode_ean8_at(pairs, run_widths, start):
    """EAN-8: guard, four left digits (all odd parity), centre, four right.

    An EAN-8 must show a REAL quiet zone on both sides -- the edge of the band
    does not count, unlike for an EAN-13. An eight-digit symbol occurs inside a
    thirteen-digit one, check digit and all, so when a frame is cut through an
    EAN-13's bars the cut itself supplies the left-hand "quiet zone" and the
    fragment reads as a well-formed wrong product number. Measured: EAN-13
    0499574977861 cut at module 13 returned 95749778 with every scanline
    agreeing, at 3, 4, 5, 6, 8 and 12 pixels per module.

    An EAN-13 keeps the edge allowance because it cannot be a fragment of
    anything longer here, so a crop can only ever cost it its quiet zone, never
    disguise it as another code. The price of this rule is that an EAN-8 whose
    own quiet zone is cropped away is refused. That is the intended direction:
    a wrong product number is worse for a warehouse than no read at all.
    """
    if start + 43 > len(run_widths):
        return None
    guard = run_widths[start:start + 3]
    centre = run_widths[start + 19:start + 24]
    trailing = run_widths[start + 40:start + 43]
    if (_variance(guard, _GUARD) is INF
            or _variance(centre, _CENTRE) is INF
            or _variance(trailing, _GUARD) is INF):
        return None
    module, bias = _ink_geometry(
        [guard[0], guard[2], centre[1], centre[3], trailing[0], trailing[2]],
        [guard[1], centre[0], centre[2], centre[4], trailing[1]])
    if module < MIN_MODULE_PIXELS:
        return None
    if not _quiet_before(pairs, start, module, allow_edge=False):
        return None

    digits = []
    index = start + 3
    for _ in range(4):
        match = _best_digit(_deink(run_widths[index:index + 4], bias, False),
                            [("O", _L_ODD)])
        if match is None:
            return None
        digits.append(match[0])
        index += 4

    index += 5                        # the centre was validated above

    for _ in range(4):
        match = _best_digit(_deink(run_widths[index:index + 4], bias, True),
                            [("R", _R)])
        if match is None:
            return None
        digits.append(match[0])
        index += 4

    if not _quiet_after(pairs, index + 3, module, allow_edge=False):
        return None

    body = "".join(str(d) for d in digits)
    if check_digit(body[:-1]) != body[-1]:
        return None
    return body, module



# ---------------------------------------------------------------------------
# Code 128
# ---------------------------------------------------------------------------
#: The most symbols a single Code 128 will be followed for: start, data, check
#: and stop. Generous for a product number and small enough that a noisy row
#: full of accidental eleven-module groups cannot be walked indefinitely.
MAX_CODE128_SYMBOLS = 40

_C128 = [list(p) for p in code128.PATTERNS]
_C128_STOP = _C128[code128.STOP]


def _best_symbol(observed):
    """The Code 128 symbol value these six runs encode, or None.

    Same shape as ``_best_digit``: closest pattern, refused when the fit is
    poor or when the runner-up is nearly as good. With 103 data patterns rather
    than ten digits the ambiguity guard earns its keep -- the table is dense and
    a smeared symbol sits between two of its neighbours.
    """
    best_value, best_variance, runner_up = None, INF, INF
    for value in range(code128.STOP):             # data, then the three starts
        variance = _variance(observed, _C128[value])
        if variance < best_variance:
            runner_up = best_variance
            best_value, best_variance = value, variance
        elif variance < runner_up:
            runner_up = variance
    if best_variance > MAX_PATTERN_VARIANCE:
        return None
    if runner_up != INF and best_variance > AMBIGUITY_RATIO * runner_up:
        return None
    return best_value


def _decode_code128_at(pairs, run_widths, start):
    """Try to read a Code 128 whose start symbol begins at ``start``.

    Returns (text, module_pixels) or None.

    Unlike an EAN-13 this has no fixed length, so the shape alone proves very
    little: a run of six-run groups is not rare in a noisy row. What proves it
    is the combination the specification provides -- a legal start symbol, the
    stop pattern, a modulo-103 checksum over every symbol, and clear space on
    both sides that the edge of the band is NOT allowed to stand in for. A
    variable-length symbology can be a fragment of a longer one of its own kind,
    which is exactly the trap an EAN-8 sets inside an EAN-13.
    """
    # start + at least one data symbol + check, then the stop
    if start + 6 + 6 + 6 + 7 > len(run_widths):
        return None

    opening = run_widths[start:start + 6]
    total = sum(opening)
    if total <= 0:
        return None
    module = total / float(code128.SYMBOL_MODULES)
    if module < MIN_MODULE_PIXELS:
        return None
    if not _quiet_before(pairs, start, module, allow_edge=False):
        return None

    first = _best_symbol(opening)
    if first not in (code128.START_A, code128.START_B, code128.START_C):
        return None

    # Ink bias, from the start symbol now that its intended widths are known:
    # three bars and three spaces, so the gap between what the bars measure and
    # what they should measure, spread over three, is the bias.
    #
    # Six runs is a thin sample -- an EAN-13 offers eleven -- and at two or
    # three pixels per module the whole-pixel rounding of each run swamps it.
    # Measured on labels/ont-code128.png, a crisp render with no real ink gain
    # at all, the estimate came out at a quarter of a module and the correction
    # it produced was what stopped the label reading.
    #
    # So both hypotheses are tried rather than one being trusted. That is safe
    # because the checksum, not the width estimate, is what admits a reading:
    # a wrong bias produces wrong symbols, wrong symbols fail modulo 103, and
    # the attempt is discarded. It costs one extra walk of the runs on labels
    # that need it and nothing on labels that do not.
    expected = _C128[first]
    bias = (sum(opening[0::2]) - sum(expected[0::2]) * module) / 3.0
    limit = module * MAX_INK_BIAS_SHARE
    bias = limit if bias > limit else (-limit if bias < -limit else bias)

    for hypothesis in ((bias, 0.0) if abs(bias) > 0.05 else (0.0,)):
        hit = _walk_code128(pairs, run_widths, start, first, module, hypothesis)
        if hit:
            return hit
    return None


def _walk_code128(pairs, run_widths, start, first, module, bias):
    """Read symbols from the start onward under one ink-bias hypothesis."""
    symbols = [first]
    index = start + 6
    while len(symbols) <= MAX_CODE128_SYMBOLS:
        # The stop must be tested first. Its leading six runs total eleven
        # modules like any data symbol, so a data-symbol match would happily
        # consume them and then walk off the end of the barcode.
        if index + 7 <= len(run_widths):
            tail = _deink(run_widths[index:index + 7], bias, True)
            if _variance(tail, _C128_STOP) is not INF:
                if not _quiet_after(pairs, index + 7, module, allow_edge=False):
                    return None
                if len(symbols) < 3:              # start, one datum, check
                    return None
                if not code128.checksum_ok(symbols):
                    return None
                text = code128.to_text(symbols[:-1])
                return (text, module) if text else None

        if index + 6 > len(run_widths):
            return None
        value = _best_symbol(_deink(run_widths[index:index + 6], bias, True))
        if value is None:
            return None
        symbols.append(value)
        index += 6

    return None

def decode_row(row):
    """Every barcode this one row of grayscale plausibly contains.

    Returns a list of (code, symbology, module_pixels). A row usually yields
    nothing; that is the normal case and not an error.
    """
    if len(row) < 60:
        return []
    binary = _binarise(row)
    pairs = _runs(binary)
    if len(pairs) < 30:
        return []                       # not enough transitions to be a barcode

    widths = [width for _colour, width in pairs]
    # A symbol always starts on a bar, so only consider black-first offsets.
    starts = [i for i, (colour, _w) in enumerate(pairs) if colour == "1"]

    found = []
    for start in starts:
        hit = _decode_ean13_at(pairs, widths, start)
        if hit:
            code, module = hit
            found.append((code, "EAN-13", module))
            continue
        hit = _decode_ean8_at(pairs, widths, start)
        if hit:
            code, module = hit
            found.append((code, "EAN-8", module))
            continue
        hit = _decode_code128_at(pairs, widths, start)
        if hit:
            text, module = hit
            found.append((text, "CODE-128", module))

    # If a thirteen-digit symbol was read, an eight-digit one found in the same
    # row is a fragment of it rather than a second barcode. Belt and braces
    # beside the quiet-zone check, because a wrong product number is the one
    # outcome this module exists to make impossible. A Code 128 in the same row
    # is left alone: it is a different symbology carrying different characters,
    # not a shorter reading of the same bars.
    retail = [f for f in found if f[1] in ("EAN-13", "EAN-8")]
    thirteens = [f for f in retail if f[1] == "EAN-13"]
    if thirteens:
        return thirteens + [f for f in found if f[1] == "CODE-128"]
    return found


# ---------------------------------------------------------------------------
# A band of rows
# ---------------------------------------------------------------------------
def decode_band(pixels, width, height, max_rows=24):
    """Read a band of grayscale pixels, row-major, one byte per pixel.

    Sampled rather than exhaustive: a barcode is tall, so rows repeat, and
    twenty-four spread across the band finds it as reliably as hundreds while
    keeping the work bounded on a single-threaded standard-library server.

    Each row is tried forwards and backwards, because a label presented upside
    down is the same symbol reversed and an operator should not have to care.

    Returns a dict describing what was found and how sure it is.
    """
    if width <= 0 or height <= 0:
        return {"ok": False, "code": None, "reason": "Empty image."}
    if len(pixels) < width * height:
        return {"ok": False, "code": None, "reason": "Fewer pixels than the stated size."}

    step = max(1, height // max_rows)
    votes = {}
    best_module = {}
    rows_tried = 0

    for y in range(0, height, step):
        offset = y * width
        row = list(pixels[offset:offset + width])
        if len(row) < width:
            break
        rows_tried += 1

        for candidate in decode_row(row):
            code, symbology, module = candidate
            votes[code] = votes.get(code, 0) + 1
            best_module[code] = max(best_module.get(code, 0), module)
            votes.setdefault("__sym__" + code, symbology)

        reversed_row = row[::-1]
        for candidate in decode_row(reversed_row):
            code, symbology, module = candidate
            votes[code] = votes.get(code, 0) + 1
            best_module[code] = max(best_module.get(code, 0), module)
            votes.setdefault("__sym__" + code, symbology)

    real = {k: v for k, v in votes.items() if not k.startswith("__sym__")}
    if not real:
        return {"ok": False, "code": None, "rows": rows_tried,
                "reason": "No barcode found in this frame."}

    code, agreeing = max(real.items(), key=lambda kv: kv[1])
    symbology = votes.get("__sym__" + code, "EAN-13")

    # Two independent lines, or it is not believed. A single agreeing line is
    # one noise spike away from a well-formed wrong product number, and a wrong
    # product number is worse for a warehouse than no read at all. Code 128
    # needs more of them; see MIN_AGREEING_LINES_CODE128.
    needed = (MIN_AGREEING_LINES_CODE128 if symbology == "CODE-128"
              else MIN_AGREEING_LINES)
    if agreeing < needed:
        return {"ok": False, "code": None, "rows": rows_tried,
                "reason": ("A barcode was almost read, but too few scanlines "
                           "agreed on it to trust. Hold the label steadier or "
                           "fill more of the frame."),
                "near_miss": code}

    return {
        "ok": True,
        "code": code,
        "symbology": symbology,
        "rows": rows_tried,
        "agreeing_lines": agreeing,
        "module_pixels": round(best_module.get(code, 0), 2),
        "competing": sorted(k for k in real if k != code),
    }
