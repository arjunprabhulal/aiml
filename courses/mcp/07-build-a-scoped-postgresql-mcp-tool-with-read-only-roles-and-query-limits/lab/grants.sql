-- Privileges for the MCP tool's login role. lesson_cluster.py runs this as the cluster administrator.
-- The reader may connect to this database, see schema docs and read docs.pages. It can still
-- read the system catalogs (pg_catalog), as every role can; it cannot read other tables or write.
REVOKE ALL ON DATABASE docs_lesson FROM PUBLIC;
REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;
REVOKE CONNECT ON DATABASE template1 FROM PUBLIC;
GRANT CONNECT ON DATABASE docs_lesson TO mcp_reader;
GRANT USAGE ON SCHEMA docs TO mcp_reader;
GRANT SELECT ON docs.pages TO mcp_reader;

-- Session defaults for the reader. A session can change these with SET, so the tool also
-- sets them for every transaction; the GRANTs above are the boundary.
ALTER ROLE mcp_reader IN DATABASE docs_lesson SET default_transaction_read_only = on;
ALTER ROLE mcp_reader IN DATABASE docs_lesson SET statement_timeout = '500ms';
