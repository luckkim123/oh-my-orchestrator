#!/usr/bin/env python3
"""Regression test for hooks/pre-bash.py.

Guards the two defects the hook shipped with until 2026-08-26: the command was
read from argv (always empty) and a match exited 1 (non-blocking).

Run: python3 hooks/test_pre_bash.py
"""

import importlib.util
import io
import json
import pathlib
import subprocess
import sys

HOOK = pathlib.Path(__file__).with_name('pre-bash.py')

# Load by path: the filename has a dash, so it is not importable by name.
_spec = importlib.util.spec_from_file_location('pre_bash', HOOK)
assert _spec and _spec.loader, f'cannot load {HOOK}'
pre_bash = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pre_bash)

SAFE = "echo 'rm -rf /tmp/nonexistent-probe-path'"
DANGEROUS = 'rm -rf / --no-preserve-root'


def payload(command):
    """A PreToolUse stdin payload; keys mirror the 10 measured on 2.1.239."""
    return json.dumps({
        'session_id': 'test',
        'transcript_path': '/dev/null',
        'cwd': '/tmp',
        'prompt_id': 'test',
        'permission_mode': 'default',
        'effort': {'level': 'high'},
        'hook_event_name': 'PreToolUse',
        'tool_name': 'Bash',
        'tool_use_id': 'test',
        'tool_input': {'command': command},
    })


def run(stdin_text, argv=()):
    """Run the hook as a subprocess; returns (exit_code, stderr).

    Nothing here reaches a shell -- the dangerous string is only ever data.
    """
    proc = subprocess.run(
        [sys.executable, str(HOOK), *argv],
        input=stdin_text, capture_output=True, text=True,
    )
    return proc.returncode, proc.stderr


def test_reads_command_from_stdin_not_argv():
    assert pre_bash.read_command(io.StringIO(payload(SAFE))) == SAFE


def test_dangerous_blocks_with_exit_2():
    code, stderr = run(payload(DANGEROUS))
    assert code == 2, f'expected 2 (the only blocking code), got {code}'
    assert 'rm -rf /' in stderr, stderr


def test_safe_command_passes():
    code, _ = run(payload(SAFE))
    assert code == 0, code


def test_scoped_delete_is_not_a_root_delete():
    """`rm -rf /tmp/x` is routine; the upstream substring pattern matched it."""
    for routine in ['rm -rf /tmp/scratch', 'rm -rf ~/build', 'rm -rf /var/tmp/x/']:
        code, stderr = run(payload(routine))
        assert code == 0, f'false positive on {routine!r}: {stderr}'


def test_bare_root_delete_still_blocks():
    for lethal in ['rm -rf /', 'rm -rf / --no-preserve-root', 'rm -rf ~']:
        code, _ = run(payload(lethal))
        assert code == 2, f'{lethal!r} must block, got {code}'


def test_argv_is_ignored():
    """The old wiring passed "$CLAUDE_TOOL_INPUT" as argv[1]; it must not decide."""
    code, _ = run(payload(SAFE), argv=[DANGEROUS])
    assert code == 0, 'argv must not drive the decision'


def test_fails_open_on_malformed_payload():
    for bad in ['', 'not json', '{}', '{"tool_input": null}']:
        code, _ = run(bad)
        assert code == 0, f'must fail open on {bad!r}, got {code}'


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for test in tests:
        test()
        print(f'ok  {test.__name__}')
    print(f'{len(tests)} passed')


if __name__ == '__main__':
    main()
