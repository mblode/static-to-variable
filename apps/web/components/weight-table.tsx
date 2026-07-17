"use client";

import {
  CrossSmallIcon,
  MinusSmallIcon,
  PlusSmallIcon,
} from "blode-icons-react";

import { Button } from "@/components/ui/button";
import {
  NumberField,
  NumberFieldDecrement,
  NumberFieldGroup,
  NumberFieldIncrement,
  NumberFieldInput,
} from "@/components/ui/number-field";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { DetectedFont } from "@/lib/build-types";

interface WeightTableProps {
  rows: DetectedFont[];
  onChangeWeight: (i: number, weight: number) => void;
  onRemove: (i: number) => void;
}

const TARGET_DEFAULT = 400;
const MIN_WEIGHT = 1;
const MAX_WEIGHT = 1000;

function nearestDefault(weights: number[]): number {
  let [best] = weights;
  for (const weight of weights) {
    if (Math.abs(weight - TARGET_DEFAULT) < Math.abs(best - TARGET_DEFAULT)) {
      best = weight;
    }
  }
  return best;
}

export function WeightTable({
  rows,
  onChangeWeight,
  onRemove,
}: WeightTableProps) {
  if (rows.length === 0) {
    return null;
  }

  const weights = rows.map((row) => row.weight);
  const distinct = new Set(weights).size === weights.length;
  const enough = rows.length >= 2;
  const valid = enough && distinct;
  const min = Math.min(...weights);
  const max = Math.max(...weights);
  const def = nearestDefault(weights);
  const hasExactDefault = weights.includes(TARGET_DEFAULT);

  return (
    <div className="overflow-hidden rounded-xl bg-card ring-1 ring-foreground/10">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="pl-4">Family</TableHead>
            <TableHead>Style</TableHead>
            <TableHead>Weight</TableHead>
            <TableHead className="pr-4" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, i) => (
            <TableRow className="hover:bg-transparent" key={row.fileName}>
              <TableCell className="pl-4 font-medium text-foreground">
                {row.family}
              </TableCell>
              <TableCell className="text-muted-foreground">
                {row.style}
                {row.italic ? " · italic" : ""}
              </TableCell>
              <TableCell>
                <NumberField
                  className="w-36"
                  max={MAX_WEIGHT}
                  min={MIN_WEIGHT}
                  onValueChange={(value) => onChangeWeight(i, value ?? 0)}
                  value={row.weight}
                >
                  <NumberFieldGroup>
                    <NumberFieldDecrement aria-label="Decrease weight">
                      <MinusSmallIcon />
                    </NumberFieldDecrement>
                    <NumberFieldInput />
                    <NumberFieldIncrement aria-label="Increase weight">
                      <PlusSmallIcon />
                    </NumberFieldIncrement>
                  </NumberFieldGroup>
                </NumberField>
              </TableCell>
              <TableCell className="pr-4 text-right">
                <Button
                  aria-label={`Remove ${row.family} ${row.style}`}
                  onClick={() => onRemove(i)}
                  size="icon-sm"
                  variant="ghost"
                >
                  <CrossSmallIcon />
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <div className="border-t px-4 py-3 text-sm">
        {valid ? (
          <p className="text-muted-foreground">
            Axis{" "}
            <span className="text-foreground tabular-nums">
              Weight {min}–{max}
            </span>
            {" · default "}
            <span className="text-foreground tabular-nums">{def}</span>
            {hasExactDefault ? "" : " (nearest to 400)"}
          </p>
        ) : (
          <p className="text-destructive">
            {enough
              ? "Two files share the same weight — give each a distinct value."
              : "Add at least two weights to build a variable font."}
          </p>
        )}
      </div>
    </div>
  );
}
