# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Agent Instructions

You're working inside the **WAT framework** (Workflows, Agents, Tools). This architecture separates concerns so that probabilistic AI handles reasoning while deterministic code handles execution. That separation is what makes this system reliable.

## The WAT Architecture

**Layer 1: Workflows (The Instructions)**
- Markdown SOPs stored in `workflows/`
- Each workflow defines the objective, required inputs, which tools to use, expected outputs, and how to handle edge cases
- Written in plain language, the same way you'd brief someone on your team

**Layer 2: Agents (The Decision-Maker)**
- This is your role. You're responsible for intelligent coordination.
- Read the relevant workflow, run tools in the correct sequence, handle failures gracefully, and ask clarifying questions when needed
- You connect intent to execution without trying to do everything yourself
- Example: If you need to pull data from a website, don't attempt it directly. Read `workflows/scrape_website.md`, figure out the required inputs, then execute `tools/scrape_single_site.py`

**Layer 3: Tools (The Execution)**
- Python scripts in `tools/` that do the actual work
- API calls, data transformations, file operations, database queries
- Credentials and API keys are stored in `.env`
- These scripts are consistent, testable, and fast

**Why this matters:** When AI tries to handle every step directly, accuracy drops fast. If each step is 90% accurate, you're down to 59% success after just five steps. By offloading execution to deterministic scripts, you stay focused on orchestration and decision-making where you excel.

## Ask First — Hard Rules

These require explicit approval before proceeding:

- **Creating or overwriting a workflow** — workflows are standing instructions; don't draft, replace, or delete them without being asked
- **Running a tool that makes paid API calls or consumes credits** — confirm before each run if the outcome is uncertain
- **Pushing data to cloud services** (Google Sheets, Slides, etc.) when the destination or content wasn't specified

Everything else — reading files, running tools with free/local APIs, fixing scripts, updating `.tmp/` — you can do without asking.

## How to Operate

**1. Look for existing tools first**
Before building anything new, check `tools/` based on what your workflow requires. Only create new scripts when nothing exists for that task.

**2. Learn and adapt when things fail**
When you hit an error:
- Read the full error message and trace
- Fix the script and retest (if it uses paid API calls or credits, check before running again)
- Document what you learned in the workflow (rate limits, timing quirks, unexpected behavior)
- Example: You get rate-limited on an API, so you dig into the docs, discover a batch endpoint, refactor the tool to use it, verify it works, then update the workflow so this never happens again

**3. Keep workflows current**
Workflows should evolve as you learn. When you find better methods, discover constraints, or encounter recurring issues, update the workflow (but see Ask First above).

## The Self-Improvement Loop

Every failure is a chance to make the system stronger:
1. Identify what broke
2. Fix the tool
3. Verify the fix works
4. Update the workflow with the new approach
5. Move on with a more robust system

## File Structure

```
.tmp/           # Temporary files (scraped data, intermediate exports). Regenerated as needed.
tools/          # Python scripts for deterministic execution
workflows/      # Markdown SOPs defining what to do and how
.env            # API keys and environment variables
credentials.json, token.json  # Google OAuth (gitignored)
```

**Core principle:** Local files are just for processing. Anything the user needs to see or use lives in cloud services (Google Sheets, Slides, etc.). Everything in `.tmp/` is disposable.

## Running Tools

Prefer `uv run` over `python` directly — it handles the virtual environment automatically:

```bash
uv run tools/<script_name>.py
# fallback if uv is unavailable:
python tools/<script_name>.py
```

Environment variables are loaded from `.env` via `python-dotenv`. Every tool must call `load_dotenv()` near the top before accessing `os.environ`.

Install missing dependencies:

```bash
pip install -r requirements.txt
# or per-tool:
pip install <package>
```

## Tool Script Conventions

Each tool in `tools/` should follow this pattern:

```python
#!/usr/bin/env python3
from dotenv import load_dotenv
import os, sys

load_dotenv()

def main():
    # single clear responsibility
    # print progress to stdout
    # write outputs to .tmp/ or push to cloud
    # exit(1) with a descriptive message on unrecoverable error
    pass

if __name__ == "__main__":
    main()
```

- One script, one job. No shared state between tools.
- Accept inputs via CLI args or environment variables — never hardcode paths or keys.
- Write intermediate outputs to `.tmp/<descriptive_name>.<ext>`.

## Workflow Execution Pattern

Before running any multi-step task:
1. Check `workflows/` for a relevant SOP
2. Identify the required inputs and tools listed in that workflow
3. Run each tool in sequence, passing outputs as inputs to the next step
4. If no workflow exists for the task, ask before creating one
