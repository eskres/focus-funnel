"use client";

import { useState } from "react";

import { ThoughtLink } from "@/components/chat/thought-link";
import { Button } from "@/components/ui/button";
import type { Source } from "@/lib/sse";

/** Adds the sources of one more search, keeping each thought once, in the order first seen. */
export function withSources(current: Source[], added: Source[]): Source[] {
  const result = [...current];
  for (const source of added) {
    if (!result.some((kept) => kept.id === source.id)) result.push(source);
  }
  return result;
}

function filedOn(createdAt: string): string {
  return createdAt.slice(0, 10);
}

/**
 * The thoughts an answer was built from. Sorting and the tag filter act on
 * this list only: no new search runs, and the answer does not change.
 */
export function SourcesList({ sources }: { sources: Source[] }) {
  const [newestFirst, setNewestFirst] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  if (sources.length === 0) return null;

  const tags: string[] = [];
  for (const tag of sources.flatMap((source) => source.tags)) {
    if (!tags.includes(tag)) tags.push(tag);
  }
  const shown = sources.filter(
    (source) => picked.length === 0 || source.tags.some((tag) => picked.includes(tag)),
  );
  if (newestFirst) shown.sort((a, b) => b.createdAt.localeCompare(a.createdAt));

  function toggle(tag: string) {
    setPicked((current) =>
      current.includes(tag) ? current.filter((t) => t !== tag) : [...current, tag],
    );
  }

  return (
    <section aria-label="Sources" className="flex w-full max-w-[85%] flex-col gap-2 rounded-lg border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-medium text-muted-foreground">Sources</p>
        <Button
          variant="ghost"
          size="xs"
          aria-pressed={newestFirst}
          onClick={() => setNewestFirst((current) => !current)}
        >
          {newestFirst ? "Newest first" : "Most relevant first"}
        </Button>
      </div>
      {tags.length > 0 && (
        <div role="group" aria-label="Filter by tag" className="flex flex-wrap gap-1">
          {tags.map((tag) => (
            <Button
              key={tag}
              variant={picked.includes(tag) ? "secondary" : "outline"}
              size="xs"
              aria-pressed={picked.includes(tag)}
              onClick={() => toggle(tag)}
            >
              #{tag}
            </Button>
          ))}
          {picked.length > 0 && (
            <Button variant="ghost" size="xs" onClick={() => setPicked([])}>
              Clear
            </Button>
          )}
        </div>
      )}
      <ol className="flex flex-col gap-1">
        {shown.map((source) => (
          <li key={source.id} className="flex flex-wrap items-baseline gap-x-2 text-sm">
            <ThoughtLink id={source.id}>{source.title}</ThoughtLink>
            <span className="text-xs text-muted-foreground">{filedOn(source.createdAt)}</span>
            {source.tags.length > 0 && (
              <span className="text-xs text-muted-foreground">
                {source.tags.map((tag) => `#${tag}`).join(" ")}
              </span>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
