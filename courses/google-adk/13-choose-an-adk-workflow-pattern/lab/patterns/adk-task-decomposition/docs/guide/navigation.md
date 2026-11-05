# Site navigation

The sidebar comes from `nav.toml`. Each `[[section]]` has a `title` and a list of `pages`.

Before 3.6.0, `docuctl build --legacy-nav` built the sidebar from folder names. That flag
is removed in 3.6.0; a build that passes it fails with `unknown flag: --legacy-nav`.
Run `docuctl nav init` once to write a `nav.toml` from the current folder layout.
