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

const WEIGHT_NAMES: Record<number, string> = {
  100: "Thin",
  200: "ExtraLight",
  300: "Light",
  400: "Regular",
  500: "Medium",
  600: "SemiBold",
  700: "Bold",
  800: "ExtraBold",
  900: "Black",
};

const masters = (...wghts: number[]) =>
  wghts.map((wght) => ({ name: WEIGHT_NAMES[wght], wght }));

const builtFrom = (...wghts: number[]) =>
  wghts.map((wght) => `${WEIGHT_NAMES[wght]} ${wght}`).join(" · ");

/**
 * Families that ship on Google Fonts as static weights only, with no variable
 * version. Each file here is the variable font this pipeline built from those
 * OFL static masters (every upright weight the family ships — see
 * scripts/showcase-fonts.json), shown live and downloadable.
 */
export const FONTS: DemoFont[] = [
  {
    id: "poppins",
    name: "Poppins",
    category: "geometric sans",
    file: "/fonts/poppins.woff2",
    ttf: "/fonts/poppins.ttf",
    axis: w(100, 400, 900),
    instances: masters(100, 200, 300, 400, 500, 600, 700, 800, 900),
    builtFrom: builtFrom(100, 200, 300, 400, 500, 600, 700, 800, 900),
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
    instances: masters(100, 200, 300, 400, 500, 600, 700, 800, 900),
    builtFrom: builtFrom(100, 200, 300, 400, 500, 600, 700, 800, 900),
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
    instances: masters(100, 200, 300, 400, 500, 600, 700, 800, 900),
    builtFrom: builtFrom(100, 200, 300, 400, 500, 600, 700, 800, 900),
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
    instances: masters(100, 200, 300, 400, 500, 600, 700, 800, 900),
    builtFrom: builtFrom(100, 200, 300, 400, 500, 600, 700, 800, 900),
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
    instances: masters(200, 300, 400, 600, 700, 900),
    builtFrom: builtFrom(200, 300, 400, 600, 700, 900),
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
    instances: masters(100, 200, 300, 400, 500, 600, 700, 800, 900),
    builtFrom: builtFrom(100, 200, 300, 400, 500, 600, 700, 800, 900),
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
    instances: masters(300, 400, 500, 600, 700),
    builtFrom: builtFrom(300, 400, 500, 600, 700),
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
    instances: masters(300, 400, 500, 600, 700),
    builtFrom: builtFrom(300, 400, 500, 600, 700),
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
    instances: masters(200, 300, 400, 500, 600, 700, 800),
    builtFrom: builtFrom(200, 300, 400, 500, 600, 700, 800),
    staticStyles: 7,
    credit: "Mukta by Ek Type, OFL",
  },
  {
    id: "zilla-slab",
    name: "Zilla Slab",
    category: "slab serif",
    file: "/fonts/zilla-slab.woff2",
    ttf: "/fonts/zilla-slab.ttf",
    axis: w(300, 400, 700),
    instances: masters(300, 400, 500, 600, 700),
    builtFrom: builtFrom(300, 400, 500, 600, 700),
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
    instances: masters(200, 300, 400, 500, 600, 700, 800),
    builtFrom: builtFrom(200, 300, 400, 500, 600, 700, 800),
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
    instances: masters(400, 600, 700),
    builtFrom: builtFrom(400, 600, 700),
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
    instances: masters(200, 300, 400, 700, 800),
    builtFrom: builtFrom(200, 300, 400, 700, 800),
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
    instances: masters(100, 200, 300, 400, 500, 600, 700, 800, 900),
    builtFrom: builtFrom(100, 200, 300, 400, 500, 600, 700, 800, 900),
    staticStyles: 18,
    credit: "Taviraj by Cadson Demak, OFL",
  },
];
