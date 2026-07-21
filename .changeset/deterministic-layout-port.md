---
"static-to-variable": patch
---

Make the static layout port deterministic. When varLib's variable layout merge is unusable and the build falls back to statically porting the default master's GDEF/GSUB/GPOS, the subsetter that prunes the donor's layout to the built glyph set keys its work by object identity, so on some process runs it left a class-def entry for a dropped glyph (an unencoded `ogonek.cap` in Titillium Web's GDEF). That dangling reference slipped past the compile gate and crashed the final font save intermittently. The port now walks every ported Coverage and ClassDef and drops any straggler glyph the built font doesn't have, so the same input always produces the same font and the build never crashes on a leftover reference. Kerning and ligatures are unaffected.
