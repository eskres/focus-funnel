"use client";

import { EllipsisIcon, PlusIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

import { useConversations } from "@/components/chat/conversations-context";
import { DeleteDialog } from "@/components/chat/delete-dialog";
import {
  ProposalDialog,
  heldProposalFor,
  type HeldOffer,
} from "@/components/chat/proposal-dialog";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  deleteConversation,
  updateConversation,
  type ConversationSummary,
} from "@/lib/conversations";

/** The conversation list on the left of the chat. */
export function Sidebar() {
  const { lists, loadError, refresh } = useConversations();
  const pathname = usePathname();
  const router = useRouter();
  const [showArchived, setShowArchived] = useState(false);
  const [deleting, setDeleting] = useState<ConversationSummary | null>(null);
  const [offer, setOffer] = useState<HeldOffer | null>(null);
  const activeId = pathname?.startsWith("/app/") ? pathname.slice("/app/".length) : null;

  async function confirmDelete() {
    if (!deleting) return;
    await deleteConversation(deleting.id);
    const wasOpen = deleting.id === activeId;
    setDeleting(null);
    await refresh();
    if (wasOpen) router.push("/app");
  }

  return (
    <nav aria-label="Conversations" className="flex w-64 shrink-0 flex-col gap-2 border-r p-3">
      <Button variant="outline" nativeButton={false} render={<Link href="/app" />}>
        <PlusIcon /> New conversation
      </Button>
      {loadError && <p className="px-2 text-sm text-destructive">{loadError}</p>}
      {lists && lists.conversations.length === 0 && (
        <p className="px-2 text-sm text-muted-foreground">No conversations yet.</p>
      )}
      <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto">
        {lists && (
          <ul aria-label="Recent conversations" className="flex flex-col gap-0.5">
            {lists.conversations.map((conversation) => (
              <ConversationRow
                key={conversation.id}
                conversation={conversation}
                active={conversation.id === activeId}
                onChanged={refresh}
                onOffer={setOffer}
                onDelete={() => setDeleting(conversation)}
              />
            ))}
          </ul>
        )}
        {lists && lists.archived.length > 0 && (
          <div className="mt-3 flex flex-col gap-1">
            <button
              type="button"
              className="px-2 text-left text-xs font-medium text-muted-foreground hover:text-foreground"
              aria-expanded={showArchived}
              onClick={() => setShowArchived((open) => !open)}
            >
              Archived ({lists.archived.length})
            </button>
            {showArchived && (
              <ul aria-label="Archived conversations" className="flex flex-col gap-0.5">
                {lists.archived.map((conversation) => (
                  <ConversationRow
                    key={conversation.id}
                    conversation={conversation}
                    active={conversation.id === activeId}
                    onChanged={refresh}
                    onOffer={setOffer}
                    onDelete={() => setDeleting(conversation)}
                  />
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
      <ProposalDialog offer={offer} onClose={() => setOffer(null)} />
      <DeleteDialog
        open={deleting !== null}
        title={deleting?.title ?? ""}
        onCancel={() => setDeleting(null)}
        onConfirm={confirmDelete}
      />
    </nav>
  );
}

function ConversationRow({
  conversation,
  active,
  onChanged,
  onOffer,
  onDelete,
}: {
  conversation: ConversationSummary;
  active: boolean;
  onChanged: () => Promise<void>;
  /** Shows a held proposal before an action. */
  onOffer: (offer: HeldOffer) => void;
  onDelete: () => void;
}) {
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState(conversation.title);
  const [error, setError] = useState<string | null>(null);

  async function change(update: Parameters<typeof updateConversation>[1]) {
    setError(null);
    try {
      await updateConversation(conversation.id, update);
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not change the conversation.");
    }
  }

  async function archive() {
    // The held proposal is offered before archiving.
    const proposal = await heldProposalFor(conversation.id);
    if (!proposal) {
      await change({ archived: true });
      return;
    }
    onOffer({
      conversationId: conversation.id,
      proposal,
      continueLabel: "Archive now",
      onContinue: () => change({ archived: true }),
    });
  }

  async function saveTitle() {
    setRenaming(false);
    if (title.trim() && title.trim() !== conversation.title) await change({ title: title.trim() });
    else setTitle(conversation.title);
  }

  return (
    <li className="group flex flex-col">
      <div
        className={`flex items-center gap-1 rounded-md pr-1 ${active ? "bg-muted" : "hover:bg-muted/60"}`}
      >
        {renaming ? (
          <Input
            aria-label="Conversation title"
            className="h-7 flex-1"
            autoFocus
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            onBlur={saveTitle}
            onKeyDown={(event) => {
              if (event.key === "Enter") void saveTitle();
              if (event.key === "Escape") {
                setTitle(conversation.title);
                setRenaming(false);
              }
            }}
          />
        ) : (
          <Link
            href={`/app/${conversation.id}`}
            aria-current={active ? "page" : undefined}
            className="flex-1 truncate px-2 py-1.5 text-sm"
          >
            {conversation.title}
          </Link>
        )}
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label={`Options for ${conversation.title}`}
              />
            }
          >
            <EllipsisIcon />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-36">
            <DropdownMenuItem onClick={() => setRenaming(true)}>Rename</DropdownMenuItem>
            {conversation.archived ? (
              <DropdownMenuItem onClick={() => change({ archived: false })}>Restore</DropdownMenuItem>
            ) : (
              <DropdownMenuItem onClick={archive}>Archive</DropdownMenuItem>
            )}
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" onClick={onDelete}>
              Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      {error && <p className="px-2 text-xs text-destructive">{error}</p>}
    </li>
  );
}
