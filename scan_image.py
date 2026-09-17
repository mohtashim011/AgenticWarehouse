"""
Read barcodes out of label image files, without a camera.
=========================================================
    python scan_image.py label.jpg
    python scan_image.py labels/                 (every image in a folder)
    python scan_image.py labels/ --bands         (also try horizontal slices)

Reads QR, EAN-13, UPC-A, EAN-8 and Code 128 out of PNG or baseline JPEG, so a
photograph taken on a phone can be checked directly. Standard library only, like
everything else on the running path.

Prints three things, because "it did not scan" is not a diagnosis:

  SCAN LOG   what read, as what symbology, at how many pixels per module, on
             how many agreeing scanlines (for QR, how many modules across), and
             how long the decode took.
  MISS LOG   what did not read and the decoder's own reason, plus the pixels
             per module the frame could have offered, so a miss caused by
             resolution is distinguishable from a miss caused by print quality
             and from a symbology this decoder does not speak.
  LATENCY    per image and in total, which is the number that decides whether
             the automatic server read can afford to run.

A miss is not a failure of this tool. The decoder refuses rather than guesses,
and a refusal on a damaged label is the correct outcome -- a wrong product
number is worse for a warehouse than no read at all.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import barcode_decode, image, qrcode_decode   # noqa: E402


IMAGE_TYPES = (".png", ".jpg", ".jpeg")

#: The band the browser actually posts: the middle rows at full width. Scanning
#: the whole image here would flatter the decoder relative to what the scanner
#: does in the app.
BROWSER_BAND_ROWS = 160


def estimate_modules(width):
    """Pixels per module if an EAN-13 filled this width. An upper bound."""
    return width / 95.0


def looks_like_bars(pixels, width, height):
    """Is there a barcode-shaped pattern here at all, whatever symbology?

    "No barcode found" answers two very different questions with one sentence:
    there was nothing to read, or there was a perfectly good barcode of a kind
    this decoder does not speak. Those need opposite responses from whoever is
    holding the label -- reposition, or stop trying -- so it is worth telling
    them apart. A row of a 1-D symbol of any kind is a long alternating run of
    dark and light bars; that is what this counts.
    """
    best = 0
    for index in range(1, 8):
        y = height * index // 8
        row = list(pixels[y * width:(y + 1) * width])
        if len(row) < 60:
            continue
        runs = barcode_decode._runs(barcode_decode._binarise(row))
        # Ignore the long pale runs at each end; the interesting part is the
        # dense middle where bar widths are a small multiple of each other.
        narrow = [w for colour, w in runs if w <= max(2, width // 40)]
        if len(narrow) >= 30:
            best = max(best, len(runs))
    return best


def bands_for(pixels, width, height, extra):
    """The slices to try, most representative first."""
    yield "whole image", pixels, width, height
    if height > BROWSER_BAND_ROWS:
        top = (height - BROWSER_BAND_ROWS) // 2
        yield ("centre %d rows (what the scanner posts)" % BROWSER_BAND_ROWS,
               pixels[top * width:(top + BROWSER_BAND_ROWS) * width],
               width, BROWSER_BAND_ROWS)
    if not extra:
        return
    # A label photographed at an angle often has one readable stripe and several
    # that are not, so it is worth reporting which part of the frame worked.
    for index in range(6):
        a = int(height * index / 6.0)
        b = int(height * (index + 2) / 6.0)
        if b - a >= 8:
            yield ("rows %d-%d" % (a, b), pixels[a * width:b * width], width, b - a)


def scan_file(path, extra=False):
    """Returns (scans, misses, seconds) for one image."""
    started = time.perf_counter()
    try:
        pixels, width, height = image.load_gray(path)
    except Exception as err:                      # noqa: BLE001
        return [], [{"band": "-", "reason": "could not read the file: %s" % err,
                     "px_per_module": None}], time.perf_counter() - started

    scans, misses = [], []

    # QR first, and over the whole image rather than a band: a QR is
    # two-dimensional, so slicing it into scanlines destroys it.
    at = time.perf_counter()
    qr = qrcode_decode.decode(pixels, width, height)
    if qr.get("ok"):
        scans.append({
            "band": "whole image", "code": qr["text"], "symbology": "QR",
            "px_per_module": qr.get("module_pixels"),
            "lines": qr.get("modules"), "rows": qr.get("modules"),
            "ms": (time.perf_counter() - at) * 1000.0,
            "competing": [],
            "detail": "version %s, level %s, %s codeword(s) repaired"
                      % (qr.get("version"), qr.get("level"),
                         qr.get("corrected_codewords")),
        })

    found_qr = bool(scans)
    for name, band, band_w, band_h in bands_for(pixels, width, height, extra):
        at = time.perf_counter()
        result = barcode_decode.decode_band(band, band_w, band_h)
        took = time.perf_counter() - at
        if result.get("code"):
            scans.append({
                "band": name, "code": result["code"],
                "symbology": result.get("symbology"),
                "px_per_module": result.get("module_pixels"),
                "lines": result.get("agreeing_lines"),
                "rows": result.get("rows"), "ms": took * 1000.0,
                "competing": result.get("competing") or [],
            })
        elif not found_qr:
            # A QR already read this file, so the 1-D reader finding no bars in
            # it is the expected outcome, not a miss worth reporting.
            misses.append({
                "band": name,
                "reason": result.get("reason", "no barcode found"),
                "near_miss": result.get("near_miss"),
                "px_per_module": round(estimate_modules(band_w), 1),
                "ms": took * 1000.0,
                "bars": looks_like_bars(band, band_w, band_h),
            })
    return scans, misses, time.perf_counter() - started


def collect(targets):
    files = []
    for target in targets:
        if os.path.isdir(target):
            for name in sorted(os.listdir(target)):
                if name.lower().endswith(IMAGE_TYPES):
                    files.append(os.path.join(target, name))
        elif os.path.isfile(target):
            files.append(target)
        else:
            print("  not found: %s" % target)
    return files


def main(argv):
    extra = "--bands" in argv
    targets = [a for a in argv if not a.startswith("--")]
    if not targets:
        print(__doc__)
        return 2

    files = collect(targets)
    if not files:
        print("No PNG or JPEG files found.")
        return 2

    all_scans, all_misses, total = [], [], 0.0
    per_file = []

    for path in files:
        scans, misses, seconds = scan_file(path, extra)
        total += seconds
        per_file.append((path, scans, misses, seconds))
        for s in scans:
            s["file"] = os.path.basename(path)
        for m in misses:
            m["file"] = os.path.basename(path)
        all_scans.extend(scans)
        all_misses.extend(misses)

    print("=" * 78)
    print("SCAN LOG   (%d read)" % len(all_scans))
    print("=" * 78)
    if not all_scans:
        print("  nothing read")
    else:
        print("  %-24s %-9s %7s %6s %8s   %s" %
              ("file", "symbology", "px/mod", "units", "ms", "decoded"))
        for s in all_scans:
            print("  %-24s %-9s %7s %6s %8.1f   %s" % (
                s["file"][:24], s["symbology"] or "-",
                s["px_per_module"], s["lines"], s["ms"], s["code"]))
            if s.get("detail"):
                print("      %s" % s["detail"])
            if s["competing"]:
                print("      competing readings on other lines: %s"
                      % ", ".join(s["competing"]))

    print()
    print("=" * 78)
    print("MISS LOG   (%d did not read)" % len(all_misses))
    print("=" * 78)
    if not all_misses:
        print("  nothing missed")
    else:
        print("  %-22s %-34s %8s %8s" % ("file", "band", "px/mod", "ms"))
        for m in all_misses:
            print("  %-22s %-34s %8s %8.1f" % (
                m["file"][:22], m["band"][:34],
                m["px_per_module"] if m["px_per_module"] is not None else "-",
                m.get("ms", 0.0)))
            print("      %s" % m["reason"])
            if m.get("near_miss"):
                print("      one scanline read %s but nothing agreed with it."
                      % m["near_miss"])
            elif m.get("bars"):
                runs = m["bars"]
                # An EAN-13 scanline is 59 runs plus a quiet zone each side.
                # Close to that and the symbology is probably right and the
                # print is damaged; far from it and it is probably a symbology
                # this decoder does not read.
                # EAN-13 is 59 runs plus a quiet zone each side. Code 128 is
                # six runs per character plus a seven-run stop, so it lands
                # anywhere from about 25 upward. Neither shape is conclusive,
                # but they narrow it usefully.
                if 55 <= runs <= 65:
                    verdict = ("that is about the right shape for an EAN-13, so "
                               "the symbology is probably right and the print or "
                               "focus is the problem")
                elif runs >= 25 and (runs - 9) % 6 <= 1:
                    verdict = ("that is about the right shape for a Code 128 of "
                               "%d characters, so the print, the focus or the "
                               "quiet zone is the problem"
                               % max(1, (runs - 21) // 6))
                else:
                    verdict = ("that is not the shape of an EAN-13 or a Code 128, "
                               "so it is either a symbology this decoder does not "
                               "read (Code 39, ITF, UPC-E) or the bars are broken "
                               "up by worn print")
                print("      a 1-D barcode IS present -- %d bars and spaces on a "
                      "scanline; %s." % (runs, verdict))

    print()
    print("=" * 78)
    print("LATENCY")
    print("=" * 78)
    for path, scans, misses, seconds in per_file:
        verdict = scans[0]["code"] if scans else "no read"
        print("  %-30s %8.0f ms   %s" % (os.path.basename(path)[:30],
                                         seconds * 1000.0, verdict))
    print("  %-30s %8.0f ms   total, %d file(s)"
          % ("", total * 1000.0, len(files)))
    if all_scans:
        times = sorted(s["ms"] for s in all_scans)
        print("  per successful decode: fastest %.0f ms, median %.0f ms, slowest %.0f ms"
              % (times[0], times[len(times) // 2], times[-1]))

    # A file counts as read if any band read it.
    read = sum(1 for _p, s, _m, _t in per_file if s)
    print()
    print("  %d of %d files read." % (read, len(files)))
    return 0 if read == len(files) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
