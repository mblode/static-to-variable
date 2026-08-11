---
"static-to-variable": patch
---

Fix the italic angle on bootstrapped sources. Glyphs measures the italic angle clockwise from vertical and `post` measures it counter-clockwise, and glyphsLib negates again on the way out to UFO, so copying `post.italicAngle` straight across left a forward-leaning italic reporting a positive angle in the built font. Projects with their own `.glyphs` sources were unaffected, since they never bootstrap.
