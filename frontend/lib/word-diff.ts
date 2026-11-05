// A word-level diff for the addition card (thought-appending design decision
// 12): which words of the thought's current summary the proposed summary
// removes, and which it adds. A longest common subsequence over words, with
// the common start and end trimmed first, is fast enough for summaries up to
// 4,000 characters and needs no dependency.

/** A run of text that both summaries share, or that only one of them has. */
export type DiffPart = { kind: "same" | "removed" | "added"; text: string };

type Word = { word: string; text: string };

/**
 * The text as words, each with the spaces after it, so the parts join back
 * into the original text. Spaces before the first word go with it.
 */
function words(text: string): Word[] {
  const found = text.match(/\s*\S+\s*/g) ?? [];
  return found.map((text) => ({ word: text.trim(), text }));
}

function push(parts: DiffPart[], kind: DiffPart["kind"], text: string) {
  const last = parts.at(-1);
  if (last?.kind === kind) last.text += text;
  else parts.push({ kind, text });
}

/**
 * The parts of `before` and `after` in reading order: shared words once,
 * removed words where `before` had them, added words where `after` has them.
 * Words are compared without their spaces; a moved word is removed in one
 * place and added in the other. Shared text keeps `after`'s spacing.
 */
export function wordDiff(before: string, after: string): DiffPart[] {
  const a = words(before);
  const b = words(after);
  const parts: DiffPart[] = [];

  let start = 0;
  while (start < a.length && start < b.length && a[start].word === b[start].word) start += 1;
  let endA = a.length;
  let endB = b.length;
  while (endA > start && endB > start && a[endA - 1].word === b[endB - 1].word) {
    endA -= 1;
    endB -= 1;
  }

  for (let i = 0; i < start; i += 1) push(parts, "same", b[i].text);

  // lengths[i][j]: the longest common run of a[start+i..endA) and b[start+j..endB).
  const n = endA - start;
  const m = endB - start;
  const width = m + 1;
  const lengths = new Uint32Array((n + 1) * width);
  for (let i = n - 1; i >= 0; i -= 1) {
    const word = a[start + i].word;
    for (let j = m - 1; j >= 0; j -= 1) {
      lengths[i * width + j] =
        word === b[start + j].word
          ? lengths[(i + 1) * width + j + 1] + 1
          : Math.max(lengths[(i + 1) * width + j], lengths[i * width + j + 1]);
    }
  }

  let i = 0;
  let j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && a[start + i].word === b[start + j].word) {
      push(parts, "same", b[start + j].text);
      i += 1;
      j += 1;
    } else if (j < m && (i === n || lengths[i * width + j + 1] >= lengths[(i + 1) * width + j])) {
      push(parts, "added", b[start + j].text);
      j += 1;
    } else {
      push(parts, "removed", a[start + i].text);
      i += 1;
    }
  }

  for (let k = endB; k < b.length; k += 1) push(parts, "same", b[k].text);
  return parts;
}

/** Only the parts `before` shows: shared and removed. */
export function beforeParts(parts: DiffPart[]): DiffPart[] {
  return parts.filter((part) => part.kind !== "added");
}

/** Only the parts `after` shows: shared and added. */
export function afterParts(parts: DiffPart[]): DiffPart[] {
  return parts.filter((part) => part.kind !== "removed");
}
