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

export type AuthKind = Connector["auth_kind"];

/** The add form's fields; `auth_value` is sent only when entered. */
export type ConnectorFields = {
  name: string;
  url: string;
  auth_kind: AuthKind;
  auth_header?: string | null;
  auth_value?: string | null;
};

export type ToolChange = { enabled?: boolean; acts?: boolean; always_allow?: boolean };

const connectorPath = (id: string) => `${BASE}/${encodeURIComponent(id)}`;

/** Store that the user accepted the warning shown before the first connector. */
export function acceptConnectorWarning(): Promise<void> {
  return apiFetch<void>(`${BASE}/warning`, { method: "POST" });
}

export function addConnector(fields: ConnectorFields): Promise<Connector> {
  return apiFetch<Connector>(BASE, { method: "POST", body: JSON.stringify(fields) });
}

/** Change a user connector; an omitted `auth_value` keeps the stored one while the kind stays. */
export function changeConnector(id: string, fields: Partial<ConnectorFields>): Promise<Connector> {
  return apiFetch<Connector>(connectorPath(id), { method: "PATCH", body: JSON.stringify(fields) });
}

export function deleteConnector(id: string): Promise<void> {
  return apiFetch<void>(connectorPath(id), { method: "DELETE" });
}

/** Connect to the server and store its tool list; a failure says why in plain words. */
export function testConnector(id: string): Promise<Connector> {
  return apiFetch<Connector>(`${connectorPath(id)}/test`, { method: "POST" });
}

export function changeTool(id: string, tool: string, change: ToolChange): Promise<Connector> {
  return apiFetch<Connector>(`${connectorPath(id)}/tools/${encodeURIComponent(tool)}`, {
    method: "PATCH",
    body: JSON.stringify(change),
  });
}
