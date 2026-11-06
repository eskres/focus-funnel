"use client";

import { useState, type SyntheticEvent } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { UnauthenticatedError, createApiError, readErrorBody } from "@/lib/api";
import { redirectToLogin } from "@/lib/redirect-to-login";

type Format = "json" | "markdown";

/** Shown when a frame holds text that is not the shared error format. */
export const EXPORT_NOT_STARTED = "The export could not start. Try again.";

/** The text a frame's document shows: its first `pre`, else its body. Null when empty or unreadable. */
function frameText(frame: HTMLIFrameElement): string | null {
  try {
    const doc = frame.contentDocument;
    if (!doc) return null;
    const text = doc.querySelector("pre")?.textContent ?? doc.body?.textContent ?? "";
    return text.trim() === "" ? null : text;
  } catch {
    // A frame whose document cannot be read, such as a download, says nothing.
    return null;
  }
}

/**
 * "Export": download every thought as one JSON or Markdown file. Each press
 * appends a hidden frame that the browser turns into a download, and no frame
 * is removed until the section unmounts, so a second press never cancels the
 * first download. A refusal loads into its frame as JSON, and the card reads
 * it from there.
 */
export function ExportSection() {
  const [frames, setFrames] = useState<{ key: number; src: string }[]>([]);
  const [error, setError] = useState<string | null>(null);

  function download(format: Format) {
    setError(null);
    setFrames((current) => [
      ...current,
      { key: current.length, src: `/api/me/export?format=${format}` },
    ]);
  }

  function onFrameLoad(event: SyntheticEvent<HTMLIFrameElement>) {
    const text = frameText(event.currentTarget);
    if (text === null) return;
    let body: unknown = null;
    try {
      body = JSON.parse(text);
    } catch {
      // Not JSON, such as a JSON viewer's own page: say so below.
    }
    const { code, message } = readErrorBody(body);
    if (!code || !message) {
      setError(EXPORT_NOT_STARTED);
      return;
    }
    // The frame cannot read the status; nothing here uses it.
    const caught = createApiError(code, message, 0);
    if (caught instanceof UnauthenticatedError) {
      redirectToLogin("/settings");
      return;
    }
    setError(caught.message);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Export</h2>
        </CardTitle>
        <CardDescription>
          Download all your thoughts with their dates, status, tags, category, summary, raw text,
          where they came from, and their additions.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => download("json")}>
            Download JSON
          </Button>
          <Button variant="outline" onClick={() => download("markdown")}>
            Download Markdown
          </Button>
        </div>
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {frames.map((frame) => (
          <iframe
            key={frame.key}
            src={frame.src}
            title="Export download"
            hidden
            aria-hidden
            tabIndex={-1}
            onLoad={onFrameLoad}
          />
        ))}
      </CardContent>
    </Card>
  );
}
