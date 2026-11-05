-- Lesson schema and seed rows. lesson_cluster.py runs this as the owner role, docs_owner.
CREATE SCHEMA docs;

CREATE TABLE docs.editors (
    editor_id text PRIMARY KEY,
    email     text NOT NULL
);

CREATE TABLE docs.pages (
    slug      text PRIMARY KEY,
    editor_id text NOT NULL REFERENCES docs.editors,
    section   text NOT NULL CHECK (section IN ('guides', 'reference', 'changelog')),
    words     integer NOT NULL CHECK (words >= 0)
);

INSERT INTO docs.editors VALUES
    ('e-1', 'ana@example.com'),
    ('e-2', 'bo@example.com');

-- 30 deterministic pages: page-01 ... page-30.
INSERT INTO docs.pages
SELECT format('page-%s', lpad(n::text, 2, '0')),
       CASE WHEN n % 2 = 0 THEN 'e-1' ELSE 'e-2' END,
       (ARRAY['guides', 'reference', 'changelog'])[n % 3 + 1],
       200 + n * 25
FROM generate_series(1, 30) AS n;
