"""Bounded local checks. Run with the project's Python 3.11 interpreter."""
import ast
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / 'backend').glob('*.py'):
    ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
for command in [
    [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py', '-v'],
    ['node', 'tests/metrics.test.mjs'],
]:
    subprocess.run(command, cwd=ROOT, check=True, timeout=90)
subprocess.run(['node', '--input-type=module', '--check'],
               input=(ROOT / 'frontend/js/main.js').read_text(encoding='utf-8'),
               text=True, cwd=ROOT, check=True, timeout=90)
