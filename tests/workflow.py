"""Helpers that run `run: |` blocks of workflow steps, so the tests cover the shipped shell."""
import os
from pathlib import Path
import subprocess
import textwrap

ROOT = Path(__file__).resolve().parents[1]


def step_script(path, name):
    """Return the dedented `run: |` block of the step called `name` in `path`."""
    lines = (ROOT / path).read_text().splitlines()
    start = lines.index(next(line for line in lines if line.strip() == f'- name: {name}'))
    run = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == 'run: |')
    indent = len(lines[run]) - len(lines[run].lstrip())
    block = []
    for line in lines[run + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        block.append(line)
    return textwrap.dedent('\n'.join(block)).strip() + '\n'


def stub(directory, name, body):
    """Write an executable bash stub `name` into `directory` (prepend it to PATH)."""
    path = Path(directory) / name
    path.write_text('#!/usr/bin/env bash\n' + body)
    path.chmod(0o755)


def run(script, cwd, path_dir=None, **env):
    environment = {**os.environ, **env}
    if path_dir:
        environment['PATH'] = f'{path_dir}:{environment["PATH"]}'
    return subprocess.run(['bash', '-euo', 'pipefail', '-c', script], cwd=cwd, env=environment,
                          text=True, capture_output=True)
