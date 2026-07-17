export interface DemoFont {
  id: string;
  name: string;
  category: string;
  file: string;
  /** wght axis bounds + default, known from the build. */
  axis: { min: number; def: number; max: number };
  instances: { name: string; wght: number }[];
  /** Static weights the variable font was rebuilt from. */
  builtFrom: string;
  credit: string;
}

const w = (min: number, def: number, max: number) => ({ min, def, max });

/**
 * Variable fonts the pipeline rebuilt from independent static weights, shown as
 * live demos. The eight Google Fonts families are SIL Open Font License; each
 * variable file here is a derivative produced by static-to-variable from those
 * OFL static masters, shown for demonstration.
 */
export const FONTS: DemoFont[] = [
  {
    id: "roboto",
    name: "Roboto",
    category: "sans",
    file: "/fonts/roboto.ttf",
    axis: w(100, 400, 900),
    instances: [
      { name: "Thin", wght: 100 },
      { name: "Regular", wght: 400 },
      { name: "Black", wght: 900 },
    ],
    builtFrom: "Thin 100 · Regular 400 · Black 900",
    credit: "Roboto by Christian Robertson, OFL",
  },
  {
    id: "montserrat",
    name: "Montserrat",
    category: "geometric sans",
    file: "/fonts/montserrat.ttf",
    axis: w(100, 400, 900),
    instances: [
      { name: "Thin", wght: 100 },
      { name: "Regular", wght: 400 },
      { name: "Black", wght: 900 },
    ],
    builtFrom: "Thin 100 · Regular 400 · Black 900",
    credit: "Montserrat by Julieta Ulanovsky, OFL",
  },
  {
    id: "work-sans",
    name: "Work Sans",
    category: "sans",
    file: "/fonts/work-sans.ttf",
    axis: w(100, 400, 900),
    instances: [
      { name: "Thin", wght: 100 },
      { name: "Regular", wght: 400 },
      { name: "Black", wght: 900 },
    ],
    builtFrom: "Thin 100 · Regular 400 · Black 900",
    credit: "Work Sans by Wei Huang, OFL",
  },
  {
    id: "raleway",
    name: "Raleway",
    category: "display sans",
    file: "/fonts/raleway.ttf",
    axis: w(100, 400, 900),
    instances: [
      { name: "Thin", wght: 100 },
      { name: "Regular", wght: 400 },
      { name: "Black", wght: 900 },
    ],
    builtFrom: "Thin 100 · Regular 400 · Black 900",
    credit: "Raleway by Matt McInerney et al., OFL",
  },
  {
    id: "merriweather",
    name: "Merriweather",
    category: "serif",
    file: "/fonts/merriweather.ttf",
    axis: w(300, 400, 900),
    instances: [
      { name: "Light", wght: 300 },
      { name: "Regular", wght: 400 },
      { name: "Black", wght: 900 },
    ],
    builtFrom: "Light 300 · Regular 400 · Black 900",
    credit: "Merriweather by Sorkin Type, OFL",
  },
  {
    id: "lora",
    name: "Lora",
    category: "serif",
    file: "/fonts/lora.ttf",
    axis: w(400, 400, 700),
    instances: [
      { name: "Regular", wght: 400 },
      { name: "Medium", wght: 500 },
      { name: "Bold", wght: 700 },
    ],
    builtFrom: "Regular 400 · Medium 500 · Bold 700",
    credit: "Lora by Cyreal, OFL",
  },
  {
    id: "playfair-display",
    name: "Playfair Display",
    category: "display serif",
    file: "/fonts/playfair-display.ttf",
    axis: w(400, 400, 900),
    instances: [
      { name: "Regular", wght: 400 },
      { name: "Bold", wght: 700 },
      { name: "Black", wght: 900 },
    ],
    builtFrom: "Regular 400 · Bold 700 · Black 900",
    credit: "Playfair Display by Claus Eggers Sørensen, OFL",
  },
  {
    id: "source-code-pro",
    name: "Source Code Pro",
    category: "mono",
    file: "/fonts/source-code-pro.ttf",
    axis: w(300, 400, 900),
    instances: [
      { name: "Light", wght: 300 },
      { name: "Regular", wght: 400 },
      { name: "Black", wght: 900 },
    ],
    builtFrom: "Light 300 · Regular 400 · Black 900",
    credit: "Source Code Pro by Adobe, OFL",
  },
  {
    id: "minimal",
    name: "STV Minimal",
    category: "Inter demo",
    file: "/fonts/minimal.ttf",
    axis: w(100, 400, 900),
    instances: [
      { name: "Thin", wght: 100 },
      { name: "Regular", wght: 400 },
      { name: "Black", wght: 900 },
    ],
    builtFrom: "Thin 100 · Regular 400 · Black 900",
    credit: "Built from Inter (Rasmus Andersson, OFL)",
  },
];
