"use client";

// The fields of a thought as the user edits them, shared by a proposal card
// and the thought sheet, so both check and send the same values.
import { useCategories } from "@/components/chat/categories-context";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

/** The text in the fields: tags as one comma-separated line, "" for no category. */
export type FieldText = {
  title: string;
  summary: string;
  tags: string;
  category: string;
};

export function parseTags(text: string): string[] {
  return text
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
}

/** Whether a field the server requires is empty, so the save button stays off. */
export function hasEmptyField(text: FieldText): boolean {
  return !text.title.trim() || !text.summary.trim();
}

/**
 * The category choices after "None": the user's categories, then any of
 * `kept` the user has since removed, so a field shows what the thought holds.
 */
export function categoryChoices(categories: string[], ...kept: (string | null | undefined)[]): string[] {
  const choices = [...categories];
  for (const name of kept) {
    if (name && !choices.includes(name)) choices.push(name);
  }
  return choices;
}

/**
 * Title, summary, tags, and category as fields. `keep` is a category that
 * stays a choice even when the user picks another, such as the one a stored
 * thought has.
 */
export function ThoughtFields({
  value,
  onChange,
  keep,
}: {
  value: FieldText;
  onChange: (next: FieldText) => void;
  keep?: string | null;
}) {
  const categories = useCategories();
  const choices = categoryChoices(categories, value.category, keep);
  const set = (field: keyof FieldText) => (next: string) => onChange({ ...value, [field]: next });

  return (
    <>
      <Label className="flex flex-col items-start gap-1 text-xs">
        Title
        <Input value={value.title} onChange={(event) => set("title")(event.target.value)} />
      </Label>
      <Label className="flex flex-col items-start gap-1 text-xs">
        Summary
        <Textarea value={value.summary} onChange={(event) => set("summary")(event.target.value)} />
      </Label>
      <Label className="flex flex-col items-start gap-1 text-xs">
        Tags, separated by commas
        <Input value={value.tags} onChange={(event) => set("tags")(event.target.value)} />
      </Label>
      <Label className="flex flex-col items-start gap-1 text-xs">
        Category
        <select
          className="rounded-md border bg-background px-2 py-1 text-sm"
          value={value.category}
          onChange={(event) => set("category")(event.target.value)}
        >
          <option value="">None</option>
          {choices.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </Label>
    </>
  );
}
