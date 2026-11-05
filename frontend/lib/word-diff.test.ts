import { describe, expect, it } from "vitest";

import { afterParts, beforeParts, wordDiff } from "./word-diff";

const join = (parts: { text: string }[]) => parts.map((part) => part.text).join("");

describe("wordDiff", () => {
  it("marks nothing when the texts are the same", () => {
    expect(wordDiff("Buy a lock.", "Buy a lock.")).toEqual([{ kind: "same", text: "Buy a lock." }]);
  });

  it("marks added words where the new text has them", () => {
    expect(wordDiff("Buy a lock.", "Buy a red lock.")).toEqual([
      { kind: "same", text: "Buy a " },
      { kind: "added", text: "red " },
      { kind: "same", text: "lock." },
    ]);
  });

  it("marks removed words where the old text had them", () => {
    expect(wordDiff("Buy a cheap red lock.", "Buy a lock.")).toEqual([
      { kind: "same", text: "Buy a " },
      { kind: "removed", text: "cheap red " },
      { kind: "same", text: "lock." },
    ]);
  });

  it("marks a moved word as removed in one place and added in the other", () => {
    const parts = wordDiff("red lock for the bike", "lock for the red bike");
    expect(parts.filter((part) => part.kind === "removed").map((part) => part.text.trim())).toEqual(["red"]);
    expect(parts.filter((part) => part.kind === "added").map((part) => part.text.trim())).toEqual(["red"]);
    expect(join(afterParts(parts))).toBe("lock for the red bike");
    expect(join(beforeParts(parts))).toBe("red lock for the bike");
  });

  it("handles added and removed words together, and an empty side", () => {
    const parts = wordDiff("Compare U-locks under 50 euros.", "Compare folding locks under 80 euros.");
    expect(parts.filter((part) => part.kind === "removed").map((part) => part.text.trim())).toEqual([
      "U-locks",
      "50",
    ]);
    expect(parts.filter((part) => part.kind === "added").map((part) => part.text.trim())).toEqual([
      "folding locks",
      "80",
    ]);
    expect(wordDiff("", "New text")).toEqual([{ kind: "added", text: "New text" }]);
    expect(wordDiff("Old text", "")).toEqual([{ kind: "removed", text: "Old text" }]);
  });

  it("compares words, not the spaces between them", () => {
    expect(wordDiff("one  two\nthree", "one two three")).toEqual([{ kind: "same", text: "one two three" }]);
  });

  it("diffs two 4,000-character summaries in under 50 ms", () => {
    // Different words at almost every place, so the trimmed start and end do not help.
    const vocabulary = "lock bike chain colour price shop steel folding cable red black grey".split(" ");
    const text = (seed: number) => {
      const out: string[] = [];
      let state = seed;
      while (out.join(" ").length < 4000) {
        state = (state * 1103515245 + 12345) % 2147483648;
        out.push(vocabulary[state % vocabulary.length]);
      }
      return out.join(" ").slice(0, 4000);
    };
    const before = text(1);
    const after = text(2);
    expect(before).toHaveLength(4000);
    wordDiff(before.slice(0, 200), after.slice(0, 200)); // warm up the JIT
    const started = performance.now();
    const parts = wordDiff(before, after);
    const took = performance.now() - started;
    expect(join(afterParts(parts))).toBe(after);
    expect(took).toBeLessThan(50);
  });
});
