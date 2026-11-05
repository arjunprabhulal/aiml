# Command reference

- `docuctl build [--jobs N]`: build the site. `--jobs` sets the number of parallel workers (default: CPU count).
- `docuctl preview [--port N]`: serve the built site locally. The default port is 4000.
- `docuctl migrate`: convert `docuctl.yaml` to `docuctl.toml`.
- `docuctl nav init`: write `nav.toml` from the folder layout.
