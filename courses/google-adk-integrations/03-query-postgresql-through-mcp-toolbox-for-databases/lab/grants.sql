-- The role Toolbox logs in as can read both tables and nothing else.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO toolbox_reader;
GRANT SELECT ON pages, feedback TO toolbox_reader;
