#!/usr/bin/env python3

from __future__ import annotations

from fontTools.ttLib import TTFont


DESIGNER = "Matthew Blode"
MANUFACTURER = "Matthew Blode"
VENDOR_ID = "MBLD"

WEIGHT_NAMES: dict[int, str] = {
    400: "Regular",
    500: "Medium",
    700: "Bold",
    900: "Black",
}


def set_name_record(font: TTFont, name_id: int, value: str) -> None:
    name_table = font["name"]
    name_table.removeNames(nameID=name_id)
    for platform_id, plat_enc_id, lang_id in ((3, 1, 0x409), (1, 0, 0)):
        name_table.setName(value, name_id, platform_id, plat_enc_id, lang_id)


def patch_metadata(
    font: TTFont,
    *,
    family_name: str,
    style_name: str,
    weight: int,
    italic: bool,
    version_string: str,
    designer: str = DESIGNER,
    manufacturer: str = MANUFACTURER,
    vendor_id: str = VENDOR_ID,
    italic_angle: float = -12.0,
) -> None:
    full_name = f"{family_name} {style_name}"
    postscript_name = f"{family_name.replace(' ', '')}-{style_name.replace(' ', '')}"
    unique_id = f"{version_string};{vendor_id[:4]};{postscript_name}"

    set_name_record(font, 1, family_name)
    set_name_record(font, 2, style_name)
    set_name_record(font, 3, unique_id)
    set_name_record(font, 4, full_name)
    set_name_record(font, 5, version_string)
    set_name_record(font, 6, postscript_name)
    set_name_record(font, 8, manufacturer)
    set_name_record(font, 9, designer)
    set_name_record(font, 16, family_name)
    set_name_record(font, 17, style_name)

    head = font["head"]
    os2 = font["OS/2"]
    post = font["post"]

    head.macStyle &= ~0x03
    os2.fsSelection &= ~0x61
    os2.usWeightClass = weight
    os2.fsType = 0
    os2.achVendID = vendor_id[:4]
    post.italicAngle = italic_angle if italic else 0.0

    if italic:
        head.macStyle |= 0x02
        os2.fsSelection |= 0x01
    elif weight == 400:
        os2.fsSelection |= 0x40

    if weight >= 700:
        head.macStyle |= 0x01
        os2.fsSelection |= 0x20
