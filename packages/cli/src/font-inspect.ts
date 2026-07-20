/**
 * Minimal sfnt reader: pulls family/subfamily names, the OS/2 weight class,
 * the italic bit, and designer/vendor metadata out of a .ttf/.otf buffer
 * without any dependency. Mirrors apps/web/lib/font-inspect.ts (keep the two
 * in sync) and what the Python discover step reads from each donor.
 */

export interface FontInfo {
  family: string;
  style: string;
  weight: number;
  italic: boolean;
  /** Name ID 8 (manufacturer), when present. */
  vendor?: string;
  /** Name ID 9 (designer), when present. */
  designer?: string;
  /** Name ID 11 (vendor URL), when present. */
  vendorUrl?: string;
  /** Name ID 12 (designer URL), when present. */
  designerUrl?: string;
}

interface TableEntry {
  offset: number;
  length: number;
}

const OFFSET_TABLE_SIZE = 12;
const TABLE_RECORD_SIZE = 16;
const NAME_RECORD_SIZE = 12;

const SFNT_TRUETYPE = 0x00_01_00_00;

const OS2_WEIGHT_OFFSET = 4;
const OS2_FSSELECTION_OFFSET = 62;

const NAME_FAMILY = 1;
const NAME_SUBFAMILY = 2;
const NAME_VENDOR = 8;
const NAME_DESIGNER = 9;
const NAME_VENDOR_URL = 11;
const NAME_DESIGNER_URL = 12;
const NAME_TYPO_FAMILY = 16;
const NAME_TYPO_SUBFAMILY = 17;

const DEFAULT_WEIGHT = 400;

function readTag(view: DataView, offset: number): string {
  let tag = "";
  for (let i = 0; i < 4; i += 1) {
    tag += String.fromCodePoint(view.getUint8(offset + i));
  }
  return tag;
}

function assertSupported(view: DataView): void {
  const signature = view.getUint32(0);
  const tag = readTag(view, 0);
  if (signature === SFNT_TRUETYPE || tag === "true" || tag === "OTTO") {
    return;
  }
  if (tag === "ttcf") {
    throw new Error(
      "Font collections (.ttc) aren't supported. Extract a single font first."
    );
  }
  if (tag === "wOFF" || tag === "wOF2") {
    throw new Error(
      "WOFF/WOFF2 web fonts aren't supported. Use the original .ttf or .otf."
    );
  }
  throw new Error("Not a valid TrueType or OpenType font.");
}

function readTableDirectory(view: DataView): Map<string, TableEntry> {
  const numTables = view.getUint16(4);
  const tables = new Map<string, TableEntry>();
  for (let i = 0; i < numTables; i += 1) {
    const record = OFFSET_TABLE_SIZE + i * TABLE_RECORD_SIZE;
    tables.set(readTag(view, record), {
      offset: view.getUint32(record + 8),
      length: view.getUint32(record + 12),
    });
  }
  return tables;
}

function readOs2(
  view: DataView,
  table: TableEntry | undefined
): { weight: number; italic: boolean } {
  if (!table) {
    return { weight: DEFAULT_WEIGHT, italic: false };
  }
  const weight = view.getUint16(table.offset + OS2_WEIGHT_OFFSET);
  const fsSelection = view.getUint16(table.offset + OS2_FSSELECTION_OFFSET);
  // fsSelection bit 0 is ITALIC; an odd value has it set, avoiding a bitwise op.
  return {
    weight: weight || DEFAULT_WEIGHT,
    italic: fsSelection % 2 === 1,
  };
}

function platformPriority(platformID: number): number {
  if (platformID === 3) {
    return 3;
  }
  if (platformID === 0) {
    return 2;
  }
  if (platformID === 1) {
    return 1;
  }
  return 0;
}

function decodeName(
  view: DataView,
  start: number,
  length: number,
  platformID: number
): string {
  const bytes = new Uint8Array(view.buffer, view.byteOffset + start, length);
  if (platformID === 3 || platformID === 0) {
    return new TextDecoder("utf-16be").decode(bytes);
  }
  let out = "";
  for (const byte of bytes) {
    out += String.fromCodePoint(byte);
  }
  return out;
}

function readNames(
  view: DataView,
  table: TableEntry | undefined
): Map<number, string> {
  const names = new Map<number, string>();
  if (!table) {
    return names;
  }
  const base = table.offset;
  const count = view.getUint16(base + 2);
  const storage = base + view.getUint16(base + 4);
  const bestPriority = new Map<number, number>();
  for (let i = 0; i < count; i += 1) {
    const record = base + 6 + i * NAME_RECORD_SIZE;
    const platformID = view.getUint16(record);
    const nameID = view.getUint16(record + 6);
    const priority = platformPriority(platformID);
    if ((bestPriority.get(nameID) ?? -1) >= priority) {
      continue;
    }
    const length = view.getUint16(record + 8);
    const offset = view.getUint16(record + 10);
    const value = decodeName(view, storage + offset, length, platformID);
    if (value) {
      names.set(nameID, value);
      bestPriority.set(nameID, priority);
    }
  }
  return names;
}

/** Parse font metadata from raw file bytes. Throws on non-font input. */
export function inspectFont(buffer: Uint8Array): FontInfo {
  if (buffer.byteLength < OFFSET_TABLE_SIZE) {
    throw new Error("File is too small to be a font.");
  }
  const view = new DataView(
    buffer.buffer,
    buffer.byteOffset,
    buffer.byteLength
  );
  assertSupported(view);
  const tables = readTableDirectory(view);
  const { weight, italic } = readOs2(view, tables.get("OS/2"));
  const names = readNames(view, tables.get("name"));
  const family =
    names.get(NAME_TYPO_FAMILY) ?? names.get(NAME_FAMILY) ?? "Unknown";
  const style =
    names.get(NAME_TYPO_SUBFAMILY) ?? names.get(NAME_SUBFAMILY) ?? "Regular";
  return {
    family: family.trim(),
    style: style.trim(),
    weight,
    italic,
    vendor: names.get(NAME_VENDOR)?.trim(),
    designer: names.get(NAME_DESIGNER)?.trim(),
    vendorUrl: names.get(NAME_VENDOR_URL)?.trim(),
    designerUrl: names.get(NAME_DESIGNER_URL)?.trim(),
  };
}
