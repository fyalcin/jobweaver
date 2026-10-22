# Network access is private-network-only with one token per client and user

Status: accepted for the planned MCP overhaul; the current MCP server is stdio-only.

The server will support local stdio on the machine that runs Jobweaver and a network connection for the user's
other machines. The network connection binds only to a private-network address (for example the host's Tailscale
address), never to all interfaces, and has no public access. Membership in the private network is not trust,
because such networks often contain other people's devices, so every request needs a token. Each token maps to one
Agent client and one User; the agent never names the User in a call, so it cannot reach other Users' data, and one
token can be revoked alone. Tokens live in a file outside Git and are never printed.
