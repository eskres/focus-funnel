import { ThoughtLibrary } from "@/components/library/thought-library";

/** The user's thoughts, newest filed first. A fixed segment, so it wins over /app/[id]. */
export default function LibraryPage() {
  return <ThoughtLibrary />;
}
