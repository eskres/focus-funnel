import { Chat } from "@/components/chat/chat";

/** A stored conversation, so a reload lands on the same one. */
export default async function ConversationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <Chat key={id} conversationId={id} />;
}
