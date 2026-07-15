from app.services.escpos_builder import ReceiptBuilder, align, bold, cut, feed, font_select, init, text_size


def test_init_bytes():
    assert init() == b"\x1b@"


def test_align_codes():
    assert align("left") == b"\x1ba\x00"
    assert align("center") == b"\x1ba\x01"
    assert align("right") == b"\x1ba\x02"


def test_bold_toggle():
    assert bold(True) == b"\x1bE\x01"
    assert bold(False) == b"\x1bE\x00"


def test_text_size_encodes_width_height_nibbles():
    # width=2, height=3 -> (2-1)<<4 | (3-1) = 0x12
    assert text_size(2, 3) == b"\x1d!\x12"


def test_cut_partial_and_full():
    assert cut(partial=True) == b"\x1dV\x01"
    assert cut(partial=False) == b"\x1dV\x00"


def test_feed_repeats_newline():
    assert feed(3) == b"\n\n\n"


def test_receipt_builder_produces_expected_byte_sequence():
    receipt = (
        ReceiptBuilder()
        .align_center()
        .bold_line("ResaPrint")
        .align_left()
        .kv_line("Guest:", "Jane Doe", width=20)
        .divider(width=10)
        .feed(2)
        .cut()
        .build()
    )

    expected = bytearray()
    expected += init()
    expected += align("center")
    expected += bold(True)
    expected += "ResaPrint\n".encode("cp437")
    expected += bold(False)
    expected += align("left")
    gap = 20 - len("Guest:") - len("Jane Doe")
    expected += f"Guest:{' ' * gap}Jane Doe\n".encode("cp437")
    expected += "----------\n".encode("cp437")
    expected += feed(2)
    expected += cut(True)

    assert receipt == bytes(expected)


def test_kv_line_minimum_one_space_when_overflowing_width():
    line = ReceiptBuilder().kv_line("Very long label", "Very long value", width=5).build()
    assert b"Very long label Very long value\n" in line


def test_non_latin1_chars_are_replaced_not_raising():
    receipt = ReceiptBuilder().line("Renée Müller 中文").build()
    assert receipt.endswith(b"\n")
    assert b"?" in receipt or b"e" in receipt


def test_font_select_codes():
    assert font_select("font_a") == b"\x1bM\x00"
    assert font_select("font_b") == b"\x1bM\x01"


def test_set_font_and_set_text_size_chainable():
    receipt = ReceiptBuilder().set_font("font_b").set_text_size(2, 2).line("Hi").build()
    expected = init() + font_select("font_b") + text_size(2, 2) + "Hi\n".encode("cp437")
    assert receipt == expected


def test_kv_line_bold_labels_wraps_only_label_in_bold():
    receipt = ReceiptBuilder(bold_labels=True).kv_line("Guest:", "Jane Doe", width=20).build()
    gap = 20 - len("Guest:") - len("Jane Doe")
    expected = (
        init()
        + bold(True)
        + "Guest:".encode("cp437")
        + bold(False)
        + f"{' ' * gap}Jane Doe\n".encode("cp437")
    )
    assert receipt == expected


def test_kv_line_default_not_bold():
    receipt = ReceiptBuilder(bold_labels=False).kv_line("Guest:", "Jane Doe", width=20).build()
    assert bold(True) not in receipt
