# Claude Code Windows MCP Test

A test project to evaluate Claude Code's behavior on Windows with and without PowerShell MCP installed.

## The Problem

Claude Code on Windows runs inside Git Bash, which causes issues when Claude generates bash-style commands that don't work natively on Windows. Common failures include:

| Error Type | Example |
|------------|---------|
| PowerShell `$_` escaping | `'extglob.ProcessName' is not recognized` |
| Shell mismatch | `Get-Module: command not found` (in bash) |
| Windows dir flags | `dir: cannot access '/s': No such file` |
| Path escaping | `type: C:\\path\\file: not found` |

The [PowerShell.MCP](https://www.powershellgallery.com/packages/PowerShell.MCP) module provides a PowerShell MCP server that gives Claude access to native Windows commands, potentially fixing these issues.

## Quick Start

```bash
# Clone and install
git clone https://github.com/r-ms/claude-windows-mcp-test.git
cd claude-windows-mcp-test
uv sync  # or: pip install -e .

# Run the full test suite (does everything automatically)
python run_full_test.py
```

That's it! The script will:
1. Check if Claude CLI and PowerShell.MCP are installed
2. Run 10 test prompts WITHOUT MCP
3. Configure PowerShell MCP automatically
4. Run the same 10 prompts WITH MCP
5. Generate an assessment report comparing both runs

## Prerequisites

- **Windows 10/11**
- **Python 3.11+**
- **Claude Code CLI** - installed and authenticated
- **PowerShell 7.2+** (for MCP)

### Installing PowerShell.MCP (Optional - script will guide you)

```powershell
Install-Module -Name PowerShell.MCP
```

## Usage Options

```bash
# Full test suite (recommended)
python run_full_test.py

# Only run without MCP (baseline)
python run_full_test.py --no-mcp-only

# Only run with MCP (assumes already configured)
python run_full_test.py --with-mcp-only

# Skip the Claude-generated report
python run_full_test.py --skip-assessment

# Custom timeout per prompt
python run_full_test.py --timeout 180
```

## Test Prompts

The test suite includes 10 prompts specifically designed to trigger common Windows/bash compatibility issues:

| # | Category | What It Tests |
|---|----------|---------------|
| 1 | PowerShell `$_` escaping | Filter processes → triggers `extglob` error |
| 2 | Shell mismatch | Get-Module → fails in bash shell |
| 3 | Windows paths | Read hosts file → backslash escaping |
| 4 | dir confusion | Recursive file list → `/s` vs find |
| 5 | Env var syntax | USERPROFILE → `$env:` vs `$` vs `%` |
| 6 | PowerShell pipeline | Sort files by size → Sort-Object |
| 7 | Windows services | List services → Get-Service |
| 8 | PATH check | Find Python → where vs which |
| 9 | File creation | Create with date → Set-Content vs echo |
| 10 | Network test | Ping → Test-Connection vs ping |

These prompts are based on **real errors** found in actual Claude Code sessions on Windows.

## Output

Results are saved to the `results/` directory:

```
results/
├── without-mcp.json    # Raw results without MCP
├── with-mcp.json       # Raw results with MCP
├── final-report.md     # Claude-generated analysis
└── workdir/            # Temporary test files
```

## Expected Results

**Without PowerShell MCP**, Claude Code may:
- Generate bash commands that fail on Windows (`ls -la`, `cat`, `find`)
- Use Unix paths (`/proc/cpuinfo`) that don't exist
- Miss environment variable syntax (`$PATH` vs `$env:PATH`)
- Fail PowerShell cmdlet calls due to `$_` escaping issues

**With PowerShell MCP**, Claude Code should:
- Use native Windows/PowerShell commands
- Have higher success rates
- Produce more reliable output

## Project Structure

```
claude-windows-mcp-test/
├── run_full_test.py          # All-in-one test runner
├── prompts.json              # Test prompts configuration
├── pyproject.toml            # Python project config
├── src/claude_mcp_test/      # Library code
│   ├── runner.py             # Individual test runner
│   ├── assessor.py           # Report generator
│   └── models.py             # Data models
└── results/                  # Test output
```

## Contributing

Found more error patterns? Add them to `prompts.json` and submit a PR!

## License

MIT
