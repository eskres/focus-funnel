// Typed client for the MCP connector settings (`/api/connectors`).
// Every route answers 404 while connectors are off on the server.
import { apiFetch } from "@/lib/api";

export type ConnectorTool = {
  name: string;
  title: string | null;
  description: string;
  read_only_hint: boolean | null;
  /** False when `<connector>__<tool>` is not a valid tool name: never switchable. */
  available: boolean;
  enabled: boolean;
  acts: boolean;
  always_allow: boolean;
  /** Whether the badge may say reads. */
  reads_allowed: boolean;
};

export type Connector = {
  id: string;
  name: string;
  source: "user" | "operator";
  /** User connectors only. */
  url: string | null;
  auth_kind: "none" | "bearer" | "header";
  auth_header: string | null;
  auth_set: boolean;
  /** The stored value's last 4 characters, for user connectors. */
  auth_last4: string | null;
  tools: ConnectorTool[];
  tools_listed_at: string | null;
};

export type CatalogEntry = {
  name: string;
  title: string;
  description: string;
  url: string;
  auth_kind: "none" | "bearer" | "header";
  auth_header: string | null;
  guide: string;
};

export type ConnectorsListing = {
  connectors: Connector[];
  user_connectors_allowed: boolean;
  catalog: CatalogEntry[];
  warning_accepted: boolean;
  /** The most connector tools a conversation may have switched on. */
  max_tools: number;
};

const BASE = "/api/connectors";

export function getConnectors(): Promise<ConnectorsListing> {
  return apiFetch<ConnectorsListing>(BASE);
}

/** The tools a connector offers when it is on: available and switched on. */
export function switchedOnTools(connector: Connector): number {
  return connector.tools.filter((tool) => tool.available && tool.enabled).length;
}
