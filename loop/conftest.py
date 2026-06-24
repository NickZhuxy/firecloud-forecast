"""Put the loop/ project root on sys.path so `import firecloud_ml` resolves when
pytest is run from inside loop/ (as verify.sh does)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
