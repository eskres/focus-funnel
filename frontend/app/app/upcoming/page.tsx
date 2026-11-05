import { UpcomingList } from "@/components/upcoming/upcoming-list";

/** The user's dated thoughts from today on. A fixed segment, so it wins over /app/[id]. */
export default function UpcomingPage() {
  return <UpcomingList />;
}
