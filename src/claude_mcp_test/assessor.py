"""Assessment script to analyze test results using Claude CLI."""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .models import TestRun


ASSESSMENT_PROMPT = '''You are analyzing test results from a Claude Code Windows MCP experiment.

The experiment tested Claude Code's behavior on Windows in two scenarios:
1. WITHOUT PowerShell MCP - Claude uses its default bash tool
2. WITH PowerShell MCP - Claude has access to native PowerShell commands

## Test Data

### Results WITHOUT MCP:
```json
{without_mcp_json}
```

### Results WITH MCP:
```json
{with_mcp_json}
```

## Your Task

Analyze these results and produce a comprehensive report in Markdown format. Include:

1. **Executive Summary** (2-3 sentences)

2. **Key Metrics**
   - Success rate comparison (without vs with MCP)
   - Bash-style vs Windows-style command usage
   - Error reduction

3. **Detailed Analysis**
   - Which prompts failed without MCP and why
   - How MCP improved command generation
   - Specific examples of bash-to-Windows command translation

4. **Error Analysis**
   - List specific errors that occurred without MCP
   - Explain why these errors happen (bash commands on Windows)

5. **Recommendations**
   - Should users install PowerShell MCP for Windows?
   - Any limitations or caveats

6. **Conclusion**

Format your response as a complete Markdown document suitable for a README or report.
'''


def load_test_run(filepath: Path) -> TestRun | None:
    """Load a test run from JSON file."""
    if not filepath.exists():
        return None
    with open(filepath) as f:
        data = json.load(f)
    return TestRun(**data)


def summarize_test_run(test_run: TestRun) -> dict:
    """Create a summarized version of test run for the prompt."""
    summary = {
        'mcp_enabled': test_run.mcp_enabled,
        'timestamp': test_run.timestamp,
        'total_prompts': test_run.total_prompts,
        'successful_prompts': test_run.successful_prompts,
        'failed_prompts': test_run.failed_prompts,
        'bash_style_count': test_run.bash_style_count,
        'windows_style_count': test_run.windows_style_count,
        'results': []
    }

    for r in test_run.results:
        result_summary = {
            'id': r.prompt_id,
            'category': r.prompt_category,
            'prompt': r.prompt_text[:100],
            'success': r.execution_success,
            'bash_style': r.used_bash_style,
            'windows_style': r.used_windows_style,
            'commands': r.commands_used[:5],  # Limit to first 5 commands
            'errors': r.errors[:3],  # Limit to first 3 errors
        }
        summary['results'].append(result_summary)

    return summary


def run_assessment(without_mcp: TestRun, with_mcp: TestRun, output_file: Path) -> str:
    """Run Claude CLI to assess the test results."""
    # Create summarized versions to fit in context
    without_summary = summarize_test_run(without_mcp)
    with_summary = summarize_test_run(with_mcp)

    # Build the prompt
    prompt = ASSESSMENT_PROMPT.format(
        without_mcp_json=json.dumps(without_summary, indent=2),
        with_mcp_json=json.dumps(with_summary, indent=2),
    )

    print("Running Claude CLI for assessment...")
    print("=" * 60)

    try:
        # Run claude CLI
        cmd = [
            'claude',
            '-p', prompt,
            '--dangerously-skip-permissions',
        ]

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout for assessment
        )

        if proc.returncode != 0:
            print(f"Warning: Claude CLI returned non-zero exit code: {proc.returncode}")
            if proc.stderr:
                print(f"stderr: {proc.stderr}")

        report = proc.stdout

        # Save the report
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w') as f:
            f.write(f"# Claude Code Windows MCP Test Report\n\n")
            f.write(f"Generated: {datetime.now().isoformat()}\n\n")
            f.write(report)

        print(f"\nReport saved to: {output_file}")
        return report

    except subprocess.TimeoutExpired:
        print("Error: Assessment timed out after 5 minutes")
        return ""
    except Exception as e:
        print(f"Error running assessment: {e}")
        return ""


def generate_quick_summary(without_mcp: TestRun, with_mcp: TestRun) -> str:
    """Generate a quick summary without using Claude CLI."""
    lines = [
        "# Quick Test Summary",
        "",
        "## Without MCP",
        f"- Success rate: {without_mcp.successful_prompts}/{without_mcp.total_prompts} ({100*without_mcp.successful_prompts/without_mcp.total_prompts:.1f}%)",
        f"- Bash-style commands: {without_mcp.bash_style_count}",
        f"- Windows-style commands: {without_mcp.windows_style_count}",
        "",
        "## With MCP",
        f"- Success rate: {with_mcp.successful_prompts}/{with_mcp.total_prompts} ({100*with_mcp.successful_prompts/with_mcp.total_prompts:.1f}%)",
        f"- Bash-style commands: {with_mcp.bash_style_count}",
        f"- Windows-style commands: {with_mcp.windows_style_count}",
        "",
        "## Comparison",
    ]

    success_diff = with_mcp.successful_prompts - without_mcp.successful_prompts
    if success_diff > 0:
        lines.append(f"- MCP improved success by {success_diff} prompts")
    elif success_diff < 0:
        lines.append(f"- MCP decreased success by {-success_diff} prompts")
    else:
        lines.append("- No change in success rate")

    bash_diff = without_mcp.bash_style_count - with_mcp.bash_style_count
    if bash_diff > 0:
        lines.append(f"- Bash-style usage reduced by {bash_diff}")

    win_diff = with_mcp.windows_style_count - without_mcp.windows_style_count
    if win_diff > 0:
        lines.append(f"- Windows-style usage increased by {win_diff}")

    lines.append("")
    lines.append("## Failed Prompts (Without MCP)")
    for r in without_mcp.results:
        if not r.execution_success:
            lines.append(f"- [{r.prompt_category}] {r.prompt_text[:50]}...")
            if r.errors:
                lines.append(f"  - Error: {r.errors[0][:100]}")

    lines.append("")
    lines.append("## Failed Prompts (With MCP)")
    for r in with_mcp.results:
        if not r.execution_success:
            lines.append(f"- [{r.prompt_category}] {r.prompt_text[:50]}...")
            if r.errors:
                lines.append(f"  - Error: {r.errors[0][:100]}")

    return '\n'.join(lines)


def main(args: list[str] | None = None) -> None:
    """Main entry point for assessment."""
    parser = argparse.ArgumentParser(
        description='Assess Claude Code MCP test results'
    )
    parser.add_argument(
        '--results-dir',
        type=Path,
        default=Path(__file__).parent.parent.parent / 'results',
        help='Directory containing test results',
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=None,
        help='Output file for the report (default: results/final-report.md)',
    )
    parser.add_argument(
        '--quick',
        action='store_true',
        help='Generate quick summary without using Claude CLI',
    )

    parsed = parser.parse_args(args)

    results_dir = parsed.results_dir
    output_file = parsed.output or (results_dir / 'final-report.md')

    # Load both test runs
    without_mcp_file = results_dir / 'without-mcp.json'
    with_mcp_file = results_dir / 'with-mcp.json'

    without_mcp = load_test_run(without_mcp_file)
    with_mcp = load_test_run(with_mcp_file)

    if not without_mcp:
        print(f"Error: Could not load {without_mcp_file}")
        print("Run tests without MCP first: uv run python -m claude_mcp_test.runner --no-mcp")
        sys.exit(1)

    if not with_mcp:
        print(f"Error: Could not load {with_mcp_file}")
        print("Run tests with MCP first: uv run python -m claude_mcp_test.runner --with-mcp")
        sys.exit(1)

    print(f"Loaded results from {without_mcp_file} and {with_mcp_file}")

    if parsed.quick:
        # Generate quick summary
        report = generate_quick_summary(without_mcp, with_mcp)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w') as f:
            f.write(report)
        print(f"\nQuick summary saved to: {output_file}")
        print("\n" + report)
    else:
        # Run full Claude CLI assessment
        run_assessment(without_mcp, with_mcp, output_file)


if __name__ == '__main__':
    main()
