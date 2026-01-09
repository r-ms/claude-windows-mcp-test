#!/usr/bin/env python3
"""
Claude Code Windows MCP Test - All-in-One Runner

This script automates the entire test process:
1. Check prerequisites (Claude CLI, PowerShell.MCP module)
2. Run tests WITHOUT MCP enabled
3. Configure PowerShell MCP server
4. Run tests WITH MCP enabled
5. Generate assessment report using Claude CLI

Usage:
    python run_full_test.py              # Full test suite
    python run_full_test.py --no-mcp-only    # Only run without MCP
    python run_full_test.py --with-mcp-only  # Only run with MCP
    python run_full_test.py --skip-assessment # Skip final report generation
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


# Colors for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def print_header(text: str) -> None:
    """Print a formatted header."""
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{text}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}\n")


def print_step(step: int, text: str) -> None:
    """Print a step indicator."""
    print(f"{Colors.CYAN}[Step {step}]{Colors.ENDC} {text}")


def print_success(text: str) -> None:
    """Print success message."""
    print(f"{Colors.GREEN}✓ {text}{Colors.ENDC}")


def print_warning(text: str) -> None:
    """Print warning message."""
    print(f"{Colors.WARNING}⚠ {text}{Colors.ENDC}")


def print_error(text: str) -> None:
    """Print error message."""
    print(f"{Colors.FAIL}✗ {text}{Colors.ENDC}")


def run_command(cmd: list[str], capture: bool = True, timeout: int = 60) -> tuple[int, str, str]:
    """Run a command and return exit code, stdout, stderr."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout or "", result.stderr or ""
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except Exception as e:
        return -1, "", str(e)


def check_claude_cli() -> bool:
    """Check if Claude CLI is installed and accessible."""
    code, stdout, _ = run_command(["claude", "--version"])
    if code == 0:
        print_success(f"Claude CLI found: {stdout.strip()}")
        return True
    print_error("Claude CLI not found. Please install it first.")
    return False


def find_pwsh() -> str | None:
    """Find PowerShell 7+ executable (pwsh.exe)."""
    # Try common locations
    possible_paths = [
        "pwsh.exe",  # If in PATH
        "pwsh",      # Linux/Mac style
        r"C:\Program Files\PowerShell\7\pwsh.exe",
        r"C:\Program Files\PowerShell\7-preview\pwsh.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\PowerShell\pwsh.exe"),
    ]

    for path in possible_paths:
        code, stdout, _ = run_command([path, "-Version"], timeout=10)
        if code == 0:
            return path

    return None


def check_powershell_mcp_module() -> tuple[bool, str | None]:
    """Check if PowerShell.MCP module is installed and get proxy path."""
    # First, find PowerShell 7+
    pwsh = find_pwsh()
    if not pwsh:
        print_warning("PowerShell 7+ (pwsh.exe) not found.")
        print("  PowerShell.MCP requires PowerShell 7.2+")
        print("  Install from: https://github.com/PowerShell/PowerShell/releases")
        return False, None

    print_success(f"PowerShell 7+ found: {pwsh}")

    # Check if module is installed
    cmd = [
        pwsh, "-NoProfile", "-Command",
        "Get-InstalledModule -Name PowerShell.MCP -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Version"
    ]
    code, stdout, _ = run_command(cmd, timeout=30)

    if code != 0 or not stdout.strip():
        print_warning("PowerShell.MCP module not found.")
        print(f"  Install with: {pwsh} -Command \"Install-Module -Name PowerShell.MCP\"")
        return False, None

    version = stdout.strip()
    print_success(f"PowerShell.MCP module found: v{version}")

    # Get proxy path
    cmd = [
        pwsh, "-NoProfile", "-Command",
        "Import-Module PowerShell.MCP; Get-MCPProxyPath"
    ]
    code, stdout, stderr = run_command(cmd, timeout=30)

    if code == 0 and stdout.strip():
        proxy_path = stdout.strip()
        print_success(f"MCP Proxy path: {proxy_path}")
        return True, proxy_path

    print_warning(f"Could not get MCP proxy path: {stderr}")
    return True, None


def check_mcp_configured() -> bool:
    """Check if PowerShell MCP is already configured in Claude Code."""
    code, stdout, _ = run_command(["claude", "mcp", "list"])
    if code == 0 and "powershell" in stdout.lower():
        print_success("PowerShell MCP already configured in Claude Code")
        return True
    return False


def configure_mcp(proxy_path: str) -> bool:
    """Configure PowerShell MCP in Claude Code."""
    print_step(2, "Configuring PowerShell MCP in Claude Code...")

    # Remove existing if present (to ensure clean state)
    run_command(["claude", "mcp", "remove", "powershell"], timeout=10)

    # Add MCP server
    code, stdout, stderr = run_command(
        ["claude", "mcp", "add", "powershell", proxy_path],
        timeout=30
    )

    if code == 0:
        print_success("PowerShell MCP configured successfully")
        return True

    print_error(f"Failed to configure MCP: {stderr}")
    return False


def remove_mcp() -> bool:
    """Remove PowerShell MCP from Claude Code."""
    code, _, _ = run_command(["claude", "mcp", "remove", "powershell"], timeout=10)
    return code == 0


def load_prompts(prompts_file: Path) -> list[dict]:
    """Load test prompts from JSON file."""
    with open(prompts_file) as f:
        data = json.load(f)
    return data.get("prompts", [])


def run_single_test(prompt: dict, work_dir: Path, timeout: int = 120) -> dict:
    """Run a single test prompt and capture results."""
    result = {
        "prompt_id": prompt["id"],
        "category": prompt["category"],
        "prompt_text": prompt["text"],
        "triggers": prompt.get("triggers", ""),
        "success": False,
        "exit_code": -1,
        "stdout": "",
        "stderr": "",
        "errors": [],
        "duration_seconds": 0,
    }

    start_time = datetime.now()

    try:
        proc = subprocess.Popen(
            [
                "claude", "-p", prompt["text"],
                "--output-format", "stream-json",
                "--dangerously-skip-permissions",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=work_dir,
        )

        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            result["exit_code"] = proc.returncode
            result["stdout"] = stdout or ""
            result["stderr"] = stderr or ""
            result["success"] = proc.returncode == 0
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()  # Clean up
            result["errors"].append(f"Timeout after {timeout} seconds")
            result["duration_seconds"] = (datetime.now() - start_time).total_seconds()
            return result

        # Extract errors from stream-json output
        for line in result["stdout"].split('\n'):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                if event.get("type") == "tool_result" and event.get("is_error"):
                    result["errors"].append(event.get("content", "Unknown error")[:200])
            except json.JSONDecodeError:
                pass

        # Check for common error patterns in output
        error_patterns = [
            "command not found",
            "not recognized",
            "No such file",
            "cannot access",
            "extglob",
            "Exit code",
        ]
        for pattern in error_patterns:
            if pattern.lower() in result["stdout"].lower() or pattern.lower() in result["stderr"].lower():
                if not any(pattern.lower() in e.lower() for e in result["errors"]):
                    result["errors"].append(f"Pattern detected: {pattern}")

    except FileNotFoundError:
        result["errors"].append("Claude CLI not found")
    except OSError as e:
        result["errors"].append(f"OS error: {e}")
    except Exception as e:
        result["errors"].append(f"Unexpected error: {type(e).__name__}: {str(e)[:100]}")

    result["duration_seconds"] = (datetime.now() - start_time).total_seconds()

    # Mark as failed if there are errors
    if result["errors"]:
        result["success"] = False

    return result


def run_test_suite(prompts: list[dict], mcp_enabled: bool, results_dir: Path) -> dict:
    """Run all test prompts and save results."""
    mode = "WITH MCP" if mcp_enabled else "WITHOUT MCP"
    print_header(f"Running Tests {mode}")

    # Create work directory for test execution
    work_dir = results_dir / "workdir"
    work_dir.mkdir(parents=True, exist_ok=True)

    test_run = {
        "mcp_enabled": mcp_enabled,
        "timestamp": datetime.now().isoformat(),
        "total_prompts": len(prompts),
        "successful": 0,
        "failed": 0,
        "results": [],
    }

    for i, prompt in enumerate(prompts, 1):
        print(f"  [{i}/{len(prompts)}] {prompt['category']}...", end=" ", flush=True)

        result = run_single_test(prompt, work_dir)
        test_run["results"].append(result)

        if result["success"]:
            test_run["successful"] += 1
            print(f"{Colors.GREEN}OK{Colors.ENDC} ({result['duration_seconds']:.1f}s)")
        else:
            test_run["failed"] += 1
            error_summary = result["errors"][0][:50] if result["errors"] else "Unknown"
            print(f"{Colors.FAIL}FAILED{Colors.ENDC} - {error_summary}")

    # Save results
    output_file = results_dir / ("with-mcp.json" if mcp_enabled else "without-mcp.json")
    with open(output_file, "w") as f:
        json.dump(test_run, f, indent=2)

    print(f"\n{Colors.BOLD}Results:{Colors.ENDC} {test_run['successful']}/{test_run['total_prompts']} successful")
    print(f"Saved to: {output_file}")

    return test_run


def generate_assessment(results_dir: Path) -> bool:
    """Generate assessment report using Claude CLI."""
    print_header("Generating Assessment Report")

    without_mcp_file = results_dir / "without-mcp.json"
    with_mcp_file = results_dir / "with-mcp.json"

    if not without_mcp_file.exists():
        print_error("Missing without-mcp.json results")
        return False

    if not with_mcp_file.exists():
        print_error("Missing with-mcp.json results")
        return False

    # Load results
    with open(without_mcp_file) as f:
        without_mcp = json.load(f)
    with open(with_mcp_file) as f:
        with_mcp = json.load(f)

    # Create summary for Claude
    summary = {
        "without_mcp": {
            "successful": without_mcp["successful"],
            "failed": without_mcp["failed"],
            "total": without_mcp["total_prompts"],
            "failed_categories": [r["category"] for r in without_mcp["results"] if not r["success"]],
            "errors": [{"category": r["category"], "errors": r["errors"][:2]}
                      for r in without_mcp["results"] if r["errors"]],
        },
        "with_mcp": {
            "successful": with_mcp["successful"],
            "failed": with_mcp["failed"],
            "total": with_mcp["total_prompts"],
            "failed_categories": [r["category"] for r in with_mcp["results"] if not r["success"]],
            "errors": [{"category": r["category"], "errors": r["errors"][:2]}
                      for r in with_mcp["results"] if r["errors"]],
        }
    }

    prompt = f'''Analyze these Claude Code Windows test results and create a Markdown report.

## Test Results Summary
```json
{json.dumps(summary, indent=2)}
```

## Context
- Tests ran on Windows with Claude Code (which uses Git Bash internally)
- WITHOUT MCP: Claude uses bash commands that often fail on Windows
- WITH MCP: Claude has PowerShell.MCP providing native Windows commands

## Create a report with:
1. **Executive Summary** (2-3 sentences on the key finding)
2. **Metrics Comparison** (table showing success rates)
3. **Error Analysis** (what types of errors occurred without MCP)
4. **Improvement Analysis** (how MCP helped)
5. **Recommendations** (should Windows users install PowerShell MCP?)
6. **Conclusion**

Format as clean Markdown suitable for a GitHub README.'''

    print("Running Claude CLI for assessment...")

    code, stdout, stderr = run_command(
        ["claude", "-p", prompt, "--dangerously-skip-permissions"],
        timeout=300,
    )

    if code != 0:
        print_warning(f"Assessment returned non-zero: {stderr}")

    # Save report
    report_file = results_dir / "final-report.md"
    with open(report_file, "w") as f:
        f.write(f"# Claude Code Windows MCP Test Report\n\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n\n")
        f.write(stdout)

    print_success(f"Report saved to: {report_file}")

    # Print quick summary
    print(f"\n{Colors.BOLD}Quick Summary:{Colors.ENDC}")
    print(f"  Without MCP: {without_mcp['successful']}/{without_mcp['total_prompts']} passed")
    print(f"  With MCP:    {with_mcp['successful']}/{with_mcp['total_prompts']} passed")

    improvement = with_mcp['successful'] - without_mcp['successful']
    if improvement > 0:
        print(f"  {Colors.GREEN}Improvement: +{improvement} tests passing with MCP{Colors.ENDC}")
    elif improvement < 0:
        print(f"  {Colors.WARNING}Regression: {improvement} fewer tests passing with MCP{Colors.ENDC}")
    else:
        print(f"  No change in success rate")

    return True


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Claude Code Windows MCP Test - All-in-One Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_full_test.py                  # Run complete test suite
  python run_full_test.py --no-mcp-only    # Only test without MCP
  python run_full_test.py --with-mcp-only  # Only test with MCP (must be configured)
  python run_full_test.py --skip-assessment # Skip report generation
        """
    )
    parser.add_argument("--no-mcp-only", action="store_true",
                       help="Only run tests without MCP")
    parser.add_argument("--with-mcp-only", action="store_true",
                       help="Only run tests with MCP")
    parser.add_argument("--skip-assessment", action="store_true",
                       help="Skip generating the assessment report")
    parser.add_argument("--prompts", type=Path, default=Path(__file__).parent / "prompts.json",
                       help="Path to prompts.json file")
    parser.add_argument("--results-dir", type=Path, default=Path(__file__).parent / "results",
                       help="Directory for results output")
    parser.add_argument("--timeout", type=int, default=120,
                       help="Timeout per prompt in seconds")

    args = parser.parse_args()

    print_header("Claude Code Windows MCP Test Suite")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Results directory: {args.results_dir}")

    # Ensure results directory exists
    args.results_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Check prerequisites
    print_step(1, "Checking prerequisites...")

    if not check_claude_cli():
        return 1

    mcp_module_installed, proxy_path = check_powershell_mcp_module()
    mcp_configured = check_mcp_configured()

    # Load prompts
    if not args.prompts.exists():
        print_error(f"Prompts file not found: {args.prompts}")
        return 1

    prompts = load_prompts(args.prompts)
    print_success(f"Loaded {len(prompts)} test prompts")

    # Determine what to run
    run_without_mcp = not args.with_mcp_only
    run_with_mcp = not args.no_mcp_only

    # Run tests WITHOUT MCP
    if run_without_mcp:
        # Temporarily remove MCP if configured
        was_configured = mcp_configured
        if was_configured:
            print("Temporarily removing MCP for baseline test...")
            remove_mcp()

        run_test_suite(prompts, mcp_enabled=False, results_dir=args.results_dir)

        # Restore MCP if it was configured
        if was_configured and proxy_path:
            configure_mcp(proxy_path)

    # Run tests WITH MCP
    if run_with_mcp:
        # Configure MCP if not already configured
        if not mcp_configured:
            if proxy_path:
                if not configure_mcp(proxy_path):
                    print_error("Failed to configure MCP. Skipping MCP tests.")
                    run_with_mcp = False
            else:
                print_warning("Cannot configure MCP - proxy path unknown")
                print("Install PowerShell.MCP and run again, or use --no-mcp-only")
                run_with_mcp = False

        if run_with_mcp:
            run_test_suite(prompts, mcp_enabled=True, results_dir=args.results_dir)

    # Generate assessment
    if not args.skip_assessment and run_without_mcp and run_with_mcp:
        generate_assessment(args.results_dir)
    elif not args.skip_assessment:
        print_warning("Skipping assessment - need both test runs")

    print_header("Test Complete")
    print(f"Results saved to: {args.results_dir}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
