export interface DemoFont {
  id: string;
  name: string;
  category: string;
  /** Variable WOFF2: used for the live preview and offered as a download. */
  file: string;
  /** Variable TTF download. */
  ttf: string;
  /** wght axis bounds + default, known from the build. */
  axis: { min: number; def: number; max: number };
  instances: { name: string; wght: number }[];
  /** Static weights the variable font was rebuilt from. */
  builtFrom: string;
  /** Static files the family ships on Google Fonts (it has no variable version). */
  staticStyles?: number;
  credit: string;
}

const w = (min: number, def: number, max: number) => ({ min, def, max });

/**
 * Families that ship on Google Fonts as static weights only, with no variable
 * version. Each file here is the variable font this pipeline built from those
 * OFL static masters, shown live and downloadable.
 */
export const FONTS: DemoFont[] = [
  {
    id: "poppins",
    name: "Poppins",
    category: "geometric sans",
    file: "/fonts/poppins.woff2",
    ttf: "/fonts/poppins.ttf",
    axis: w(100, 400, 900),
    instances: [
      { name: "Thin", wght: 100 },
      { name: "Regular", wght: 400 },
      { name: "Black", wght: 900 },
    ],
    builtFrom: "Thin 100 · Regular 400 · Black 900",
    staticStyles: 18,
    credit: "Poppins by Indian Type Foundry, OFL",
  },
  {
    id: "lato",
    name: "Lato",
    category: "humanist sans",
    file: "/fonts/lato.woff2",
    ttf: "/fonts/lato.ttf",
    axis: w(100, 400, 900),
    instances: [
      { name: "Thin", wght: 100 },
      { name: "Regular", wght: 400 },
      { name: "Black", wght: 900 },
    ],
    builtFrom: "Thin 100 · Regular 400 · Black 900",
    staticStyles: 18,
    credit: "Lato by Łukasz Dziedzic, OFL",
  },
  {
    id: "barlow",
    name: "Barlow",
    category: "grotesque sans",
    file: "/fonts/barlow.woff2",
    ttf: "/fonts/barlow.ttf",
    axis: w(100, 400, 900),
    instances: [
      { name: "Thin", wght: 100 },
      { name: "Regular", wght: 400 },
      { name: "Black", wght: 900 },
    ],
    builtFrom: "Thin 100 · Regular 400 · Black 900",
    staticStyles: 18,
    credit: "Barlow by Jeremy Tribby, OFL",
  },
  {
    id: "kanit",
    name: "Kanit",
    category: "geometric sans",
    file: "/fonts/kanit.woff2",
    ttf: "/fonts/kanit.ttf",
    axis: w(100, 400, 900),
    instances: [
      { name: "Thin", wght: 100 },
      { name: "Regular", wght: 400 },
      { name: "Black", wght: 900 },
    ],
    builtFrom: "Thin 100 · Regular 400 · Black 900",
    staticStyles: 18,
    credit: "Kanit by Cadson Demak, OFL",
  },
  {
    id: "titillium-web",
    name: "Titillium Web",
    category: "humanist sans",
    file: "/fonts/titillium-web.woff2",
    ttf: "/fonts/titillium-web.ttf",
    axis: w(200, 400, 900),
    instances: [
      { name: "ExtraLight", wght: 200 },
      { name: "Regular", wght: 400 },
      { name: "Black", wght: 900 },
    ],
    builtFrom: "ExtraLight 200 · Regular 400 · Black 900",
    staticStyles: 12,
    credit: "Titillium Web by Accademia di Belle Arti di Urbino, OFL",
  },
  {
    id: "barlow-condensed",
    name: "Barlow Condensed",
    category: "condensed sans",
    file: "/fonts/barlow-condensed.woff2",
    ttf: "/fonts/barlow-condensed.ttf",
    axis: w(100, 400, 900),
    instances: [
      { name: "Thin", wght: 100 },
      { name: "Regular", wght: 400 },
      { name: "Black", wght: 900 },
    ],
    builtFrom: "Thin 100 · Regular 400 · Black 900",
    staticStyles: 18,
    credit: "Barlow Condensed by Jeremy Tribby, OFL",
  },
  {
    id: "rajdhani",
    name: "Rajdhani",
    category: "display sans",
    file: "/fonts/rajdhani.woff2",
    ttf: "/fonts/rajdhani.ttf",
    axis: w(300, 400, 700),
    instances: [
      { name: "Light", wght: 300 },
      { name: "Regular", wght: 400 },
      { name: "Bold", wght: 700 },
    ],
    builtFrom: "Light 300 · Regular 400 · Bold 700",
    staticStyles: 5,
    credit: "Rajdhani by Indian Type Foundry, OFL",
  },
  {
    id: "khand",
    name: "Khand",
    category: "condensed display sans",
    file: "/fonts/khand.woff2",
    ttf: "/fonts/khand.ttf",
    axis: w(300, 400, 700),
    instances: [
      { name: "Light", wght: 300 },
      { name: "Regular", wght: 400 },
      { name: "Bold", wght: 700 },
    ],
    builtFrom: "Light 300 · Regular 400 · Bold 700",
    staticStyles: 5,
    credit: "Khand by Indian Type Foundry, OFL",
  },
  {
    id: "mukta",
    name: "Mukta",
    category: "humanist sans",
    file: "/fonts/mukta.woff2",
    ttf: "/fonts/mukta.ttf",
    axis: w(200, 400, 800),
    instances: [
      { name: "ExtraLight", wght: 200 },
      { name: "Regular", wght: 400 },
      { name: "ExtraBold", wght: 800 },
    ],
    builtFrom: "ExtraLight 200 · Regular 400 · ExtraBold 800",
    staticStyles: 7,
    credit: "Mukta by Ek Type, OFL",
  },
  {
    id: "passion-one",
    name: "Passion One",
    category: "display slab",
    file: "/fonts/passion-one.woff2",
    ttf: "/fonts/passion-one.ttf",
    axis: w(400, 400, 900),
    instances: [
      { name: "Regular", wght: 400 },
      { name: "Bold", wght: 700 },
      { name: "Black", wght: 900 },
    ],
    builtFrom: "Regular 400 · Bold 700 · Black 900",
    staticStyles: 3,
    credit: "Passion One by Fontstage, OFL",
  },
  {
    id: "zilla-slab",
    name: "Zilla Slab",
    category: "slab serif",
    file: "/fonts/zilla-slab.woff2",
    ttf: "/fonts/zilla-slab.ttf",
    axis: w(300, 400, 700),
    instances: [
      { name: "Light", wght: 300 },
      { name: "Regular", wght: 400 },
      { name: "Bold", wght: 700 },
    ],
    builtFrom: "Light 300 · Regular 400 · Bold 700",
    staticStyles: 10,
    credit: "Zilla Slab by Typotheque for Mozilla, OFL",
  },
  {
    id: "spectral",
    name: "Spectral",
    category: "contemporary serif",
    file: "/fonts/spectral.woff2",
    ttf: "/fonts/spectral.ttf",
    axis: w(200, 400, 800),
    instances: [
      { name: "ExtraLight", wght: 200 },
      { name: "Regular", wght: 400 },
      { name: "ExtraBold", wght: 800 },
    ],
    builtFrom: "ExtraLight 200 · Regular 400 · ExtraBold 800",
    staticStyles: 14,
    credit: "Spectral by Production Type, OFL",
  },
  {
    id: "crimson-text",
    name: "Crimson Text",
    category: "book serif",
    file: "/fonts/crimson-text.woff2",
    ttf: "/fonts/crimson-text.ttf",
    axis: w(400, 400, 700),
    instances: [
      { name: "Regular", wght: 400 },
      { name: "SemiBold", wght: 600 },
      { name: "Bold", wght: 700 },
    ],
    builtFrom: "Regular 400 · SemiBold 600 · Bold 700",
    staticStyles: 6,
    credit: "Crimson Text by Sebastian Kosch, OFL",
  },
  {
    id: "neuton",
    name: "Neuton",
    category: "old-style serif",
    file: "/fonts/neuton.woff2",
    ttf: "/fonts/neuton.ttf",
    axis: w(200, 400, 800),
    instances: [
      { name: "ExtraLight", wght: 200 },
      { name: "Regular", wght: 400 },
      { name: "ExtraBold", wght: 800 },
    ],
    builtFrom: "ExtraLight 200 · Regular 400 · ExtraBold 800",
    staticStyles: 6,
    credit: "Neuton by Brian Zick, OFL",
  },
  {
    id: "taviraj",
    name: "Taviraj",
    category: "transitional serif",
    file: "/fonts/taviraj.woff2",
    ttf: "/fonts/taviraj.ttf",
    axis: w(100, 400, 900),
    instances: [
      { name: "Thin", wght: 100 },
      { name: "Regular", wght: 400 },
      { name: "Black", wght: 900 },
    ],
    builtFrom: "Thin 100 · Regular 400 · Black 900",
    staticStyles: 18,
    credit: "Taviraj by Cadson Demak, OFL",
  },
];
