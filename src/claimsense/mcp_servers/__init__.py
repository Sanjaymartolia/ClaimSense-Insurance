"""FastMCP servers: policy-kb, adjudication-calc, tariff, claims-db (Tools & Security, L7)"""

#: Each server's module. A module has `server()` (the FastMCP app, built without opening any data)
#: and `main()` (serve it over stdio): `python -m claimsense.mcp_servers.<module>`.
SERVERS = {
    "policy-kb": "claimsense.mcp_servers.policy_kb",
    "adjudication-calc": "claimsense.mcp_servers.adjudication_calc",
    "tariff": "claimsense.mcp_servers.tariff",
    "claims-db": "claimsense.mcp_servers.claims_db",
}
