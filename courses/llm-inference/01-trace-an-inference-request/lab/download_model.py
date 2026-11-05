"""Explicit opt-in download of the pinned, Apache-2.0 text model (about 1 GB)."""

import argparse
from huggingface_hub import snapshot_download

MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct"
REVISION = "7ae557604adf67be50417f59c2c2f167def9a775"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True)
    args = parser.parse_args()
    print(
        snapshot_download(
            MODEL_ID,
            revision=REVISION,
            local_dir=args.destination,
            allow_patterns=["*.json", "*.txt", "*.safetensors", "LICENSE", "README.md"],
        )
    )


if __name__ == "__main__":
    main()
