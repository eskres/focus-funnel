"use client";

import { useState } from "react";

import { formatUsd, type UsageReport } from "@/lib/usage";

type Day = UsageReport["days"][number];

const HEIGHT = 160;
const AXIS_WIDTH = 52;
const LABEL_HEIGHT = 20;
const BAR_MAX = 24;
const GAP = 2;
const RADIUS = 4;

/** Up to four clean ticks from 0 to a round maximum. */
export function niceTicks(max: number): number[] {
  if (max <= 0) return [0];
  const rough = max / 3;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= rough) ?? rough;
  const ticks = [];
  for (let value = 0; value < max + step; value += step) {
    ticks.push(Number(value.toPrecision(12)));
    if (value >= max) break;
  }
  return ticks;
}

/** The fewest decimal places (at least two) that show every tick exactly. */
export function tickDecimals(ticks: number[]): number {
  for (let places = 2; places < 10; places += 1) {
    const scale = 10 ** places;
    if (ticks.every((tick) => Math.abs(Math.round(tick * scale) - tick * scale) < 1e-6)) {
      return places;
    }
  }
  return 10;
}

function shortDate(iso: string): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/** A column with a 4px rounded top, square at the baseline. */
function columnPath(x: number, y: number, width: number, bottom: number): string {
  const r = Math.min(RADIUS, width / 2, bottom - y);
  return [
    `M${x},${bottom}`,
    `V${y + r}`,
    `Q${x},${y} ${x + r},${y}`,
    `H${x + width - r}`,
    `Q${x + width},${y} ${x + width},${y + r}`,
    `V${bottom}`,
    "Z",
  ].join(" ");
}

function describe(day: Day): string {
  const unknown =
    day.unknown_cost_calls > 0
      ? `, ${day.unknown_cost_calls} ${day.unknown_cost_calls === 1 ? "call" : "calls"} with unknown cost`
      : "";
  return `${formatUsd(day.cost_usd)} on ${shortDate(day.date)}, ${day.tokens.toLocaleString("en")} tokens${unknown}`;
}

/**
 * Estimated spend per day, one bar each. A single series, so no legend: the
 * section title names it. Each bar shows its values on hover and focus, and
 * the same values are in the table below the chart.
 */
export function UsageChart({ days }: { days: Day[] }) {
  const [active, setActive] = useState<number | null>(null);
  const width = 600;
  const plotWidth = width - AXIS_WIDTH;
  const bottom = HEIGHT - LABEL_HEIGHT;
  const ticks = niceTicks(Math.max(...days.map((d) => d.cost_usd), 0));
  const top = ticks[ticks.length - 1] || 1;
  const places = tickDecimals(ticks);
  const slot = plotWidth / days.length;
  const barWidth = Math.max(Math.min(BAR_MAX, slot - GAP), 1);
  const y = (value: number) => bottom - (value / top) * (bottom - 8);
  const labelled = new Set([0, Math.floor((days.length - 1) / 2), days.length - 1]);
  const shown = active === null ? null : days[active];

  return (
    <figure className="relative flex flex-col gap-2">
      <svg
        viewBox={`0 0 ${width} ${HEIGHT}`}
        className="w-full overflow-visible"
        role="img"
        aria-label={`Estimated spend per day, ${shortDate(days[0].date)} to ${shortDate(days[days.length - 1].date)}`}
      >
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={AXIS_WIDTH}
              x2={width}
              y1={y(tick)}
              y2={y(tick)}
              className="stroke-border"
              strokeWidth={1}
            />
            <text
              x={AXIS_WIDTH - 6}
              y={y(tick)}
              dy="0.32em"
              textAnchor="end"
              className="fill-muted-foreground text-[10px] tabular-nums"
            >
              {formatUsd(tick, places)}
            </text>
          </g>
        ))}
        {days.map((day, index) => {
          const x = AXIS_WIDTH + index * slot + (slot - barWidth) / 2;
          const barTop = y(day.cost_usd);
          return (
            <g
              key={day.date}
              data-testid="usage-bar"
              tabIndex={0}
              role="img"
              aria-label={describe(day)}
              className="outline-none focus-visible:[&>path]:opacity-70"
              onPointerEnter={() => setActive(index)}
              onPointerLeave={() => setActive(null)}
              onFocus={() => setActive(index)}
              onBlur={() => setActive(null)}
            >
              {/* The hit target is the whole column slot, not only the bar. */}
              <rect x={AXIS_WIDTH + index * slot} y={0} width={slot} height={bottom} fill="transparent" />
              {day.cost_usd > 0 && (
                <path
                  d={columnPath(x, barTop, barWidth, bottom)}
                  className={
                    active === index
                      ? "fill-[#5598e7] dark:fill-[#6da7ec]"
                      : "fill-[#2a78d6] dark:fill-[#3987e5]"
                  }
                />
              )}
              {labelled.has(index) && (
                <text
                  x={x + barWidth / 2}
                  y={HEIGHT - 4}
                  textAnchor="middle"
                  className="fill-muted-foreground text-[10px]"
                >
                  {shortDate(day.date)}
                </text>
              )}
            </g>
          );
        })}
        <line
          x1={AXIS_WIDTH}
          x2={width}
          y1={bottom}
          y2={bottom}
          className="stroke-muted-foreground/40"
          strokeWidth={1}
        />
      </svg>
      {shown && (
        <div
          role="tooltip"
          className="pointer-events-none absolute top-0 rounded-md border bg-popover px-2 py-1 text-xs shadow-sm"
          style={{
            left: `${((AXIS_WIDTH + (active! + 0.5) * slot) / width) * 100}%`,
            transform: "translateX(-50%)",
          }}
        >
          <p className="font-semibold tabular-nums">{formatUsd(shown.cost_usd)}</p>
          <p className="text-muted-foreground">
            {shortDate(shown.date)} · {shown.tokens.toLocaleString("en")} tokens
          </p>
          {shown.unknown_cost_calls > 0 && (
            <p className="text-muted-foreground">
              {shown.unknown_cost_calls} with unknown cost
            </p>
          )}
        </div>
      )}
      <figcaption>
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer">Show as a table</summary>
          <table className="mt-2 w-full text-left tabular-nums">
            <thead>
              <tr>
                <th className="font-medium">Day (UTC)</th>
                <th className="font-medium">Estimated spend</th>
                <th className="font-medium">Tokens</th>
                <th className="font-medium">Unknown cost</th>
              </tr>
            </thead>
            <tbody>
              {days.map((day) => (
                <tr key={day.date}>
                  <td>{shortDate(day.date)}</td>
                  <td>{formatUsd(day.cost_usd)}</td>
                  <td>{day.tokens.toLocaleString("en")}</td>
                  <td>{day.unknown_cost_calls || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      </figcaption>
    </figure>
  );
}
