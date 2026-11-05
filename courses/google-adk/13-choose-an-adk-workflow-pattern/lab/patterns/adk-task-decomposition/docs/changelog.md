# Changelog

## 3.6.0
- Add `docuctl preview --port` to choose the preview server port.
- BREAKING: Remove the `--legacy-nav` flag. Navigation now comes only from `nav.toml`.

## 3.5.0
- Build pages in parallel; set the worker count with `--jobs`.
- BREAKING: `docuctl build` no longer reads `docuctl.yaml`; rename it to `docuctl.toml`.
