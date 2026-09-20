"""A parser crash must stop publication and preserve the traceback."""
import os
from pathlib import Path
import subprocess


def test_parser_failure_stops_health_check_and_keeps_stderr(tmp_path):
    workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/parser-daily.yml').read_text()
    step = workflow.split('      - name: Запустить парсер\n', 1)[1].split('\n      - name:', 1)[0]
    script = '\n'.join(line[10:] for line in step.split('        run: |\n', 1)[1].splitlines())
    script = script.replace('${{ github.event.inputs.days || 14 }}', '14')
    python = tmp_path / 'python'
    python.write_text('#!/bin/sh\nif [ "$1" = "-u" ]; then shift; fi\n'
                      'if [ "$1" = "parser.py" ]; then echo "parser failure" >&2; exit 23; fi\n'
                      'touch unexpected-followup\n')
    python.chmod(0o755)
    result = subprocess.run(['bash', '-e', '-c', script], cwd=tmp_path,
                            env={**os.environ, 'PATH': str(tmp_path) + os.pathsep + os.environ['PATH']},
                            capture_output=True, text=True)
    assert result.returncode == 23
    assert 'parser failure' in (tmp_path / 'parser_output.log').read_text()
    assert not (tmp_path / 'unexpected-followup').exists()
