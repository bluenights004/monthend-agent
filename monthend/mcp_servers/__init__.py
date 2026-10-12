"""MCP servers that connect Claude to Xero, Microsoft 365, the run datastore and the month-end workflow.

Each server is a stdio process started by Claude Code (.mcp.json) or the Agent SDK.
None of them exposes an approval tool. External writes go through the review gate.
"""
