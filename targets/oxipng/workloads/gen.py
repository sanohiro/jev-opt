#!/usr/bin/env python3
"""Deterministic PNG workloads for the oxipng Stage 0 (SPEC.ja.md 6.1, 11).

Python standard library only, no network, fixed seeds. Training and holdout
differ only in the seed, so the holdout is the same measurement on data the
PGO profile has never seen (SPEC.ja.md 10).

Three kinds, chosen to put different amounts of work in oxipng's *own* Rust
code versus the statically linked libdeflate C compressor:

  photo    RGB8, gradient plus low-amplitude noise. Nearly incompressible, so
           libdeflate dominates and the row filters run over a large image.
  alpha    RGBA8, a repeated tile plus an alpha ramp. Compresses well, and
           exercises the alpha/colour-type reduction paths in Rust.
  palette  colour type 3 (indexed) with a 256-entry palette. Exercises
           src/reduction/palette.rs, which is pure Rust and hash-map heavy.

Sizes are chosen so that `oxipng -o 2` takes at least one second per file on
the reference machine (SPEC.ja.md 10: startup must be noise).

Usage:  python3 targets/oxipng/workloads/gen.py
"""

import hashlib
import os
import random
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))

# name -> (kind, width, height, seed)
SPECS = [
    ("train-photo.png",   "photo",   2048, 2048, 20260921201),
    ("train-alpha.png",   "alpha",   3072, 3072, 20260921202),
    ("train-palette.png", "palette", 3072, 3072, 20260921203),
    ("hold-photo.png",    "photo",   2048, 2048, 20260921301),
    ("hold-alpha.png",    "alpha",   3072, 3072, 20260921302),
    ("hold-palette.png",  "palette", 3072, 3072, 20260921303),
]


def chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def xor_noise(body, rnd, mask_byte):
    """XOR every byte with `mask_byte & random`, as one big-integer operation.

    XOR rather than addition so there are no carries between bytes, and one
    big-int operation rather than a Python loop so a 12 MiB image generates in
    well under a second. `body` must NOT contain the per-row filter bytes: a
    noised filter byte can name a filter type that does not exist (5-7), which
    makes the PNG invalid.
    """
    n = len(body)
    noise = int.from_bytes(rnd.randbytes(n), "big")
    mask = int.from_bytes(bytes([mask_byte]) * n, "big")
    return (int.from_bytes(body, "big") ^ (noise & mask)).to_bytes(n, "big")


def add_filter_bytes(body, stride):
    """Prefix every `stride`-byte row with filter byte 0 (None)."""
    out = bytearray()
    for off in range(0, len(body), stride):
        out += b"\x00" + body[off:off + stride]
    return bytes(out)


def build_photo(w, h, seed):
    """RGB8 gradient + noise. Filter byte 0 (None) on every row."""
    rnd = random.Random(seed)
    rpat = bytes((x * 255 // w) & 0xFF for x in range(w))
    bpat = bytes(((x + y) * 255 // (w + h)) & 0xFF for y in (0,) for x in range(w))
    out = bytearray()
    row = bytearray(w * 3)
    for y in range(h):
        row[0::3] = rpat
        row[1::3] = bytes([(y * 255 // h) & 0xFF]) * w
        # B shifts by one step per row, which a row filter can exploit.
        shift = y % w
        row[2::3] = bpat[shift:] + bpat[:shift]
        out += row
    raw = add_filter_bytes(xor_noise(bytes(out), rnd, 0x07), w * 3)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return ihdr, raw, None


def build_alpha(w, h, seed):
    """RGBA8: a 64x64 repeated tile, plus an alpha ramp with flat regions."""
    rnd = random.Random(seed)
    tile = bytes(rnd.randrange(256) for _ in range(64 * 64 * 3))
    out = bytearray()
    for y in range(h):
        ty = y % 64
        base = tile[ty * 64 * 3:(ty + 1) * 64 * 3]
        rgb = (base * ((w // 64) + 1))[:w * 3]
        row = bytearray(w * 4)
        row[0::4] = rgb[0::3]
        row[1::4] = rgb[1::3]
        row[2::4] = rgb[2::3]
        # Alpha: fully opaque for the top half, a horizontal ramp below.
        if y < h // 2:
            row[3::4] = b"\xff" * w
        else:
            row[3::4] = bytes((x * 255 // w) & 0xFF for x in range(w))
        out += b"\x00" + bytes(row)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return ihdr, bytes(out), None


def build_palette(w, h, seed):
    """Colour type 3, 8 bits, 256-entry palette, structured index content."""
    rnd = random.Random(seed)
    plte = bytes(rnd.randrange(256) for _ in range(256 * 3))
    idxpat = bytes((x * 7 + (x // 13)) & 0xFF for x in range(w))
    out = bytearray()
    for y in range(h):
        shift = (y * 3) % w
        out += idxpat[shift:] + idxpat[:shift]
    # A little index noise so the image is not perfectly periodic.
    raw = add_filter_bytes(xor_noise(bytes(out), rnd, 0x03), w)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0)
    return ihdr, raw, plte


BUILDERS = {"photo": build_photo, "alpha": build_alpha, "palette": build_palette}


def main():
    for name, kind, w, h, seed in SPECS:
        ihdr, raw, plte = BUILDERS[kind](w, h, seed)
        data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
        if plte is not None:
            data += chunk(b"PLTE", plte)
        # zlib level 6 so oxipng always finds an improvement and therefore
        # always writes an output file.
        data += chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
        path = os.path.join(HERE, name)
        with open(path, "wb") as f:
            f.write(data)
        print("%s  %9d  %-18s %dx%d seed=%d"
              % (hashlib.sha256(data).hexdigest(), len(data), name, w, h, seed))


if __name__ == "__main__":
    sys.exit(main())
