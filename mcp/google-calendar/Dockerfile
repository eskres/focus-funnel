# A Google Calendar MCP server for docker-compose.mcp.yml (openspec
# mcp-connectors design decision 13). The server speaks MCP over stdio; the
# bridge serves it as Streamable HTTP at /mcp on port 8000, one server
# process per MCP session. See docs/connectors.md#google-calendar.
FROM node:24-alpine
RUN npm install -g --omit=dev @cocal/google-calendar-mcp@2.7.0 supergateway@4.2.0 \
 && npm cache clean --force \
 && mkdir -p /tokens \
 && chown node:node /tokens
# The OAuth client is mounted read-only; the tokens live in a volume the
# server can write, because it refreshes them.
ENV GOOGLE_OAUTH_CREDENTIALS=/config/gcp-oauth.keys.json \
    GOOGLE_CALENDAR_MCP_TOKEN_PATH=/tokens/tokens.json
USER node
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD wget -q -O /dev/null http://127.0.0.1:8000/healthz || exit 1
CMD ["supergateway", "--stdio", "google-calendar-mcp", "--outputTransport", "streamableHttp", \
     "--stateful", "--port", "8000", "--healthEndpoint", "/healthz"]
