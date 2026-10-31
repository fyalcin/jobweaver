# The MCP server is a thin layer over the running backend

The MCP server calls the existing backend (`jobweaver/server.py`, listening on `127.0.0.1:8000`) over its web API instead of importing its modules. The backend stays the single owner of the SQLite database and document locks, which assume one process. Refactoring logic into a shared library was rejected for now: more work and more risk, and it can still happen function by function later. The backend's login is built for browser cookies, so the MCP server needs its own credential (ADR-0003).
