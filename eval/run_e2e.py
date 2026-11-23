#!/usr/bin/env python3
"""Run four real-model RAG cases and write the evidence report."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'demo'))
from run_demo import main  # noqa: E402

if __name__ == '__main__':
    sys.argv.extend(['--eval', '--report', str(ROOT / 'eval' / 'report.md')])
    raise SystemExit(main())
