-- The docs analytics database the assistant reads: pages and reader feedback.
CREATE TABLE pages (
    slug        text PRIMARY KEY,
    title       text NOT NULL,
    team        text NOT NULL,
    updated_on  date NOT NULL
);
CREATE TABLE feedback (
    id          serial PRIMARY KEY,
    page_slug   text NOT NULL REFERENCES pages (slug),
    helpful     boolean NOT NULL,
    comment     text,
    created_on  date NOT NULL
);
INSERT INTO pages VALUES
    ('rollback', 'Roll back a release', 'platform-docs', '2026-03-02'),
    ('deploy',   'Deploy a service',    'platform-docs', '2026-09-28'),
    ('tokens',   'Manage API tokens',   'platform-docs', '2026-06-15'),
    ('billing',  'Read your invoice',   'billing-docs',  '2026-08-01');
INSERT INTO feedback (page_slug, helpful, comment, created_on) VALUES
    ('rollback', false, 'Still shows docuctl release revert, which fails on 2.x', '2026-10-02'),
    ('rollback', false, 'Which flag picks the release?',                          '2026-10-05'),
    ('rollback', false, NULL,                                                     '2026-10-11'),
    ('rollback', true,  NULL,                                                     '2026-10-12'),
    ('deploy',   true,  NULL,                                                     '2026-10-03'),
    ('deploy',   false, 'The canary section needs an example',                    '2026-10-09'),
    ('tokens',   true,  NULL,                                                     '2026-10-04'),
    ('billing',  false, 'Invoice export link is broken',                          '2026-10-06');
