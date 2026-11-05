"""Choose the passage that answers the recorded writing question."""
import sys

def feedback(source_id):
    if source_id == 'path-write':
        return True, 'Good: Path.write_text writes the file and accepts encoding="utf-8".'
    if source_id == 'path-read':
        return False, 'Try again: Path.read_text reads a file. Find the passage about writing one.'
    return False, 'Try again: json.dumps creates a string; it does not write a file.'

if __name__ == '__main__':
    ok, message = feedback(sys.argv[1] if len(sys.argv)>1 else '')
    print(message)
    raise SystemExit(0 if ok else 1)
