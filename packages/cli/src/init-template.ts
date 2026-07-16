/**
 * The starter config written by `static-to-variable init`.
 *
 * Kept as a plain string (not an object) so the scaffold preserves comments-free
 * but hand-formatted JSON. Tests parse the fence and validate it against
 * schemas/stv-config.schema.json, so it can never drift from the schema.
 */
export const INIT_CONFIG_TEMPLATE = `{
  "$schema": "https://github.com/mblode/static-to-variable/schemas/stv-config.schema.json",
  "version": 3,
  "id": "myfamily",
  "family": {
    "name": "My Family",
    "version": "1.000",
    "vendor": "MYCO",
    "designer": "Your Name",
    "designerUrl": "https://example.com",
    "vendorUrl": "https://example.com"
  },
  "axes": [
    {
      "tag": "wght",
      "name": "Weight",
      "minimum": 100,
      "default": 400,
      "maximum": 900,
      "namedInstances": { "100": "Thin", "400": "Regular", "900": "Black" }
    }
  ],
  "styles": {
    "roman": {
      "italic": false,
      "donors": [
        { "id": "roman-thin", "name": "MyFamily-Thin", "path": "donors/MyFamily-Thin.otf", "location": { "wght": 100 } },
        { "id": "roman-regular", "name": "MyFamily-Regular", "path": "donors/MyFamily-Regular.otf", "location": { "wght": 400 } },
        { "id": "roman-black", "name": "MyFamily-Black", "path": "donors/MyFamily-Black.otf", "location": { "wght": 900 } }
      ],
      "source": "sources/myfamily.glyphs",
      "masters": [
        { "name": "Thin", "donorId": "roman-thin", "location": { "wght": 100 } },
        { "name": "Regular", "donorId": "roman-regular", "location": { "wght": 400 }, "default": true },
        { "name": "Black", "donorId": "roman-black", "location": { "wght": 900 } }
      ],
      "output": "build/roman/myfamily-vf.ttf"
    }
  },
  "output": { "dir": "build", "releaseDir": "build/release", "formats": ["ttf", "woff2"] }
}
`;
