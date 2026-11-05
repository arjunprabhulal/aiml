# Configuration file

Since 3.5.0, docuctl reads only `docuctl.toml` in the project root. A `docuctl.yaml`
file is ignored, and `docuctl build` prints `no configuration found`.

Convert an old file with `docuctl migrate`, which writes `docuctl.toml` next to the
old file and leaves `docuctl.yaml` in place. Delete the old file after you check the result.
