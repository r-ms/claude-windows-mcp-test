# Claude Code Windows MCP Test

A test project to evaluate Claude Code's behavior on Windows with and without PowerShell MCP installed.

## Background

Claude Code on Windows runs inside Git Bash, which can cause issues when Claude generates bash-style commands (like `ls -la`, `cat`, `find`) that don't work natively on Windows. The [PowerShell.MCP](https://www.powershellgallery.com/packages/PowerShell.MCP) module provides a PowerShell MCP server that gives Claude access to native Windows commands.

This project tests whether installing PowerShell MCP improves Claude Code's reliability on Windows.

## Prerequisites

- Windows 10/11
- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (Python package manager)
- Claude Code CLI installed and authenticated
- PowerShell 7.2+ (for MCP testing)

## Installation

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/claude-windows-mcp-test.git
cd claude-windows-mcp-test

# Install dependencies with uv
uv sync
```

## Installing PowerShell MCP

Before running the "with MCP" tests, install and configure PowerShell MCP:

```powershell
# Install the PowerShell module
Install-Module -Name PowerShell.MCP

# Get the proxy path
Import-Module PowerShell.MCP
Get-MCPProxyPath -Escape
```

Then add it to Claude Code:

```bash
# Replace the path with your actual PowerShell.MCP.Proxy.exe path
claude mcp add powershell "C:\Users\YOUR_USER\...\PowerShell.MCP.Proxy.exe"

# Verify it's added
claude mcp list
```

## Usage

### Run Tests Without MCP

```bash
uv run python -m claude_mcp_test.runner --no-mcp
```

### Configure and Run Tests With MCP

1. Make sure PowerShell MCP is configured (see above)
2. Run the tests:

```bash
uv run python -m claude_mcp_test.runner --with-mcp
```

### Generate Assessment Report

After running both test sets:

```bash
# Full assessment using Claude CLI
uv run python -m claude_mcp_test.assessor

# Or quick summary (no Claude CLI needed)
uv run python -m claude_mcp_test.assessor --quick
```

### Full Test Suite

Run everything in sequence:

```bash
# 1. Run without MCP
uv run python -m claude_mcp_test.runner --no-mcp

# 2. Configure PowerShell MCP (if not already done)
# 3. Run with MCP
uv run python -m claude_mcp_test.runner --with-mcp

# 4. Generate report
uv run python -m claude_mcp_test.assessor
```

## Test Prompts

The test suite includes 10 prompts covering common operations:

| # | Category | Prompt |
|---|----------|--------|
| 1 | File Listing | List all files with sizes |
| 2 | Directory Creation | Create folder and file |
| 3 | System Info | Show OS, CPU, memory details |
| 4 | Environment Vars | Display PATH variable |
| 5 | File Search | Find .json files recursively |
| 6 | Process List | Top 5 processes by memory |
| 7 | Disk Space | Check C: drive space |
| 8 | File Content | Create and read a file |
| 9 | Git Operations | Check git status |
| 10 | Package Check | Verify Python installation |

## Output

Results are saved to the `results/` directory:

- `without-mcp.json` - Raw test results without MCP
- `with-mcp.json` - Raw test results with MCP
- `final-report.md` - Claude-generated analysis comparing both runs

## How It Works

1. **Runner** (`runner.py`): Executes each prompt using `claude -p` with `--output-format stream-json` and `--dangerously-skip-permissions`
2. **Detection**: Analyzes commands for bash-style (`ls`, `cat`, `find`) vs Windows-style (`Get-ChildItem`, `dir`, `Get-Content`) patterns
3. **Assessment** (`assessor.py`): Uses Claude CLI to analyze both result sets and generate a comparative report

## Expected Results

Without PowerShell MCP, Claude Code may:
- Generate bash commands that fail on Windows
- Use Unix paths (`/proc/cpuinfo`) that don't exist
- Miss environment variable syntax (`$PATH` vs `$env:PATH`)

With PowerShell MCP, Claude Code should:
- Use native Windows/PowerShell commands
- Have better success rates
- Produce more reliable output

## License

MIT
