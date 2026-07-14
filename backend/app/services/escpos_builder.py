"""Minimal hand-rolled ESC/POS byte builder.

Deliberately not a wrapper around python-escpos: LAN sending is a raw
socket write of a byte string, and this same layout is ported 1:1 to
C# in ResaPrint.Shared/Escpos/EscposBuilder.cs for the Windows Agent.
Keeping both as small hand-written builders is far easier to keep in
sync than wrapping a library built around a live device connection.
"""
from __future__ import annotations

from typing import Literal

ESC = b"\x1b"
GS = b"\x1d"

Align = Literal["left", "center", "right"]

_ALIGN_CODES: dict[Align, bytes] = {
    "left": b"\x00",
    "center": b"\x01",
    "right": b"\x02",
}


def init() -> bytes:
    return ESC + b"@"


def align(mode: Align) -> bytes:
    return ESC + b"a" + _ALIGN_CODES[mode]


def bold(on: bool) -> bytes:
    return ESC + b"E" + (b"\x01" if on else b"\x00")


def text_size(width: int, height: int) -> bytes:
    n = ((width - 1) & 0x07) << 4 | ((height - 1) & 0x07)
    return GS + b"!" + bytes([n])


def cut(partial: bool = True) -> bytes:
    return GS + b"V" + (b"\x01" if partial else b"\x00")


def feed(n: int = 3) -> bytes:
    return b"\n" * n


def encode_line(text: str, codepage: str = "cp437") -> bytes:
    return text.encode(codepage, errors="replace") + b"\n"


class ReceiptBuilder:
    def __init__(self, codepage: str = "cp437") -> None:
        self._codepage = codepage
        self._buf = bytearray(init())

    def align_left(self) -> ReceiptBuilder:
        self._buf += align("left")
        return self

    def align_center(self) -> ReceiptBuilder:
        self._buf += align("center")
        return self

    def align_right(self) -> ReceiptBuilder:
        self._buf += align("right")
        return self

    def bold_line(self, text: str) -> ReceiptBuilder:
        self._buf += bold(True)
        self._buf += encode_line(text, self._codepage)
        self._buf += bold(False)
        return self

    def line(self, text: str = "") -> ReceiptBuilder:
        self._buf += encode_line(text, self._codepage)
        return self

    def kv_line(self, label: str, value: str, width: int = 42) -> ReceiptBuilder:
        gap = max(1, width - len(label) - len(value))
        self._buf += encode_line(f"{label}{' ' * gap}{value}", self._codepage)
        return self

    def divider(self, width: int = 42, char: str = "-") -> ReceiptBuilder:
        self._buf += encode_line(char * width, self._codepage)
        return self

    def feed(self, n: int = 3) -> ReceiptBuilder:
        self._buf += feed(n)
        return self

    def cut(self, partial: bool = True) -> ReceiptBuilder:
        self._buf += cut(partial)
        return self

    def build(self) -> bytes:
        return bytes(self._buf)
