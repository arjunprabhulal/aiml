"""Inspect exact story-text overlap without fitting or changing any model."""
import json
from pathlib import Path
from baseline import split_stories

HERE = Path(__file__).parent


def overlap_counts(text):
    train, dev, test = split_stories(text)
    training_text = set(train)
    earlier_text = training_text | set(dev)
    return {
        "rows": {"train": len(train), "dev": len(dev), "test": len(test)},
        "dev_rows_matching_training_text": sum(row in training_text for row in dev),
        "test_rows_matching_training_text": sum(row in training_text for row in test),
        "test_rows_matching_train_or_dev_text": sum(row in earlier_text for row in test),
    }


if __name__ == "__main__":
    print(json.dumps(overlap_counts((HERE / "corpus.txt").read_text()), indent=2))
