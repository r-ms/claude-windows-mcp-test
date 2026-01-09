"""Test runner for Claude Code MCP testing."""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .models import Prompt, PromptsConfig, TestResult, TestRun, ToolCall


# Patterns to detect bash-style vs Windows-style commands
BASH_PATTERNS = [
    r'\bls\s+-[la]',
    r'\bls\b(?!\s+\|)',
    r'\bcat\s+',
    r'\bgrep\s+',
    r'\bfind\s+\.\s+-name',
    r'\becho\s+\$',
    r'\bprintenv\b',
    r'\buname\b',
    r'\bdf\s+-h',
    r'\bps\s+aux',
    r'\btop\b',
    r'\bchmod\b',
    r'\btouch\b',
    r'\brm\s+-',
    r'\bcp\s+-',
    r'\bmv\s+',
    r'/proc/',
    r'/etc/',
]

WINDOWS_PATTERNS = [
    r'\bGet-ChildItem\b',
    r'\bGet-Content\b',
    r'\bSet-Content\b',
    r'\bNew-Item\b',
    r'\bGet-Process\b',
    r'\bGet-ComputerInfo\b',
    r'\bGet-PSDrive\b',
    r'\bGet-Volume\b',
    r'\bGet-Command\b',
    r'\b\$env:',
    r'\bdir\s+/s',
    r'\btype\s+',
    r'\bsysteminfo\b',
    r'\bwmic\b',
    r'\btasklist\b',
    r'\bwhere\s+',
    r'%[A-Z]+%',
]


def load_prompts(prompts_file: Path) -> PromptsConfig:
    """Load test prompts from JSON file."""
    with open(prompts_file) as f:
        data = json.load(f)
    return PromptsConfig(**data)


def detect_command_style(text: str) -> tuple[bool, bool]:
    """Detect if text contains bash-style or Windows-style commands."""
    text_lower = text.lower()

    bash_style = any(re.search(pattern, text, re.IGNORECASE) for pattern in BASH_PATTERNS)
    windows_style = any(re.search(pattern, text, re.IGNORECASE) for pattern in WINDOWS_PATTERNS)

    return bash_style, windows_style


def extract_commands_from_response(response_text: str) -> list[str]:
    """Extract command strings from Claude's response."""
    commands = []

    # Look for Bash tool calls in stream-json format
    # The format includes tool_use events with input containing command
    lines = response_text.strip().split('\n')

    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
            if event.get('type') == 'tool_use':
                tool_input = event.get('input', {})
                if 'command' in tool_input:
                    commands.append(tool_input['command'])
        except json.JSONDecodeError:
            continue

    return commands


def extract_tool_calls(response_text: str) -> list[ToolCall]:
    """Extract tool calls from stream-json response."""
    tool_calls = []
    lines = response_text.strip().split('\n')

    current_tool = None

    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
            event_type = event.get('type', '')

            if event_type == 'tool_use':
                current_tool = ToolCall(
                    tool_name=event.get('name', 'unknown'),
                    tool_input=event.get('input', {}),
                )
                tool_calls.append(current_tool)
            elif event_type == 'tool_result' and current_tool:
                current_tool.tool_result = event.get('content', '')
                if event.get('is_error'):
                    current_tool.success = False
                    current_tool.error = event.get('content', '')
        except json.JSONDecodeError:
            continue

    return tool_calls


def extract_errors(response_text: str) -> list[str]:
    """Extract error messages from response."""
    errors = []
    lines = response_text.strip().split('\n')

    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
            if event.get('type') == 'tool_result' and event.get('is_error'):
                errors.append(event.get('content', 'Unknown error'))
            elif event.get('type') == 'error':
                errors.append(event.get('message', 'Unknown error'))
        except json.JSONDecodeError:
            continue

    return errors


def run_single_prompt(prompt: Prompt, work_dir: Path, timeout: int = 120) -> TestResult:
    """Run a single prompt through Claude CLI and collect results."""
    print(f"  Running prompt {prompt.id}: {prompt.category}...")

    result = TestResult(
        prompt_id=prompt.id,
        prompt_text=prompt.text,
        prompt_category=prompt.category,
    )

    try:
        # Build the claude command
        cmd = [
            'claude',
            '-p', prompt.text,
            '--output-format', 'stream-json',
            '--dangerously-skip-permissions',
        ]

        # Run claude CLI
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=work_dir,
        )

        result.raw_response = proc.stdout

        # Extract data from response
        result.commands_used = extract_commands_from_response(proc.stdout)
        result.tool_calls = extract_tool_calls(proc.stdout)
        result.errors = extract_errors(proc.stdout)

        if proc.stderr:
            result.errors.append(f"stderr: {proc.stderr}")

        # Determine success
        result.execution_success = proc.returncode == 0 and len(result.errors) == 0

        # Detect command styles
        all_text = proc.stdout + ' '.join(result.commands_used)
        result.used_bash_style, result.used_windows_style = detect_command_style(all_text)

        # Also check tool inputs
        for tc in result.tool_calls:
            if 'command' in tc.tool_input:
                bash, win = detect_command_style(tc.tool_input['command'])
                result.used_bash_style = result.used_bash_style or bash
                result.used_windows_style = result.used_windows_style or win

        # Build output summary
        result.output = proc.stdout[:2000] if len(proc.stdout) > 2000 else proc.stdout

    except subprocess.TimeoutExpired:
        result.execution_success = False
        result.errors.append(f"Timeout after {timeout} seconds")
    except Exception as e:
        result.execution_success = False
        result.errors.append(str(e))

    status = "OK" if result.execution_success else "FAILED"
    style = []
    if result.used_bash_style:
        style.append("bash")
    if result.used_windows_style:
        style.append("windows")
    style_str = f" ({'/'.join(style)})" if style else ""
    print(f"    [{status}]{style_str}")

    return result


def run_all_prompts(prompts: PromptsConfig, mcp_enabled: bool, mcp_server: str | None = None) -> TestRun:
    """Run all prompts and collect results."""
    # Create a temporary working directory for tests
    work_dir = Path(__file__).parent.parent.parent / 'results' / 'workdir'
    work_dir.mkdir(parents=True, exist_ok=True)

    test_run = TestRun(
        mcp_enabled=mcp_enabled,
        mcp_server=mcp_server,
        total_prompts=len(prompts.prompts),
    )

    print(f"\nRunning {len(prompts.prompts)} prompts (MCP: {'enabled' if mcp_enabled else 'disabled'})...")
    print("=" * 60)

    for prompt in prompts.prompts:
        result = run_single_prompt(prompt, work_dir)
        test_run.results.append(result)

        if result.execution_success:
            test_run.successful_prompts += 1
        else:
            test_run.failed_prompts += 1

        if result.used_bash_style:
            test_run.bash_style_count += 1
        if result.used_windows_style:
            test_run.windows_style_count += 1

    print("=" * 60)
    print(f"Results: {test_run.successful_prompts}/{test_run.total_prompts} successful")
    print(f"Bash-style commands: {test_run.bash_style_count}")
    print(f"Windows-style commands: {test_run.windows_style_count}")

    return test_run


def save_results(test_run: TestRun, output_file: Path) -> None:
    """Save test results to JSON file."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(test_run.model_dump(), f, indent=2)
    print(f"\nResults saved to: {output_file}")


def main_no_mcp() -> None:
    """Entry point for running tests without MCP."""
    main(['--no-mcp'])


def main_with_mcp() -> None:
    """Entry point for running tests with MCP."""
    main(['--with-mcp'])


def main(args: list[str] | None = None) -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Run Claude Code MCP tests on Windows'
    )
    parser.add_argument(
        '--no-mcp',
        action='store_true',
        help='Run tests without MCP enabled',
    )
    parser.add_argument(
        '--with-mcp',
        action='store_true',
        help='Run tests with MCP enabled',
    )
    parser.add_argument(
        '--prompts',
        type=Path,
        default=Path(__file__).parent.parent.parent / 'prompts.json',
        help='Path to prompts.json file',
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=Path(__file__).parent.parent.parent / 'results',
        help='Output directory for results',
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=120,
        help='Timeout per prompt in seconds',
    )

    parsed = parser.parse_args(args)

    if not parsed.no_mcp and not parsed.with_mcp:
        parser.error('Must specify either --no-mcp or --with-mcp')

    if parsed.no_mcp and parsed.with_mcp:
        parser.error('Cannot specify both --no-mcp and --with-mcp')

    # Load prompts
    prompts = load_prompts(parsed.prompts)
    print(f"Loaded {len(prompts.prompts)} test prompts")

    # Determine MCP status
    mcp_enabled = parsed.with_mcp
    mcp_server = 'powershell' if mcp_enabled else None

    # Run tests
    test_run = run_all_prompts(prompts, mcp_enabled, mcp_server)

    # Save results
    output_file = parsed.output_dir / ('with-mcp.json' if mcp_enabled else 'without-mcp.json')
    save_results(test_run, output_file)


if __name__ == '__main__':
    main()
