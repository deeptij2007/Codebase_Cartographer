# 🗺️ Codebase Cartographer

An agentic onboarding tool built on [smolagents](https://github.com/huggingface/smolagents). Point it at an unfamiliar git repo and it produces an **onboarding map**: what the system does, how it's structured, a dependency diagram, the load-bearing modules, a risk/fragility map from git history, and an ordered "read these files first" path.

It's a showcase of what `CodeAgent` is good at — instead of canned questions, the agent **writes its own analysis code** (AST parsing, import-graph building, history mining) on the fly, because every codebase is different.

📋 **[Cheat sheet →](https://deeptij2007.github.io/Codebase_Cartographer/)** — a one-page quick reference (CLI flags, backends, agent hierarchy, tools).

## How it works

```
Synthesizer (manager CodeAgent)
    ├── structure_mapper  (CodeAgent)        walks the tree, parses ASTs,
    │                                        builds the import graph + diagram
    └── git_historian     (ToolCallingAgent) churn hotspots & bus-factor risk
```

The agents have **no raw `os`/`subprocess` access**. Every filesystem read and git
command goes through a guarded tool in `tools.py` that (a) stays inside the target
repo and (b) caps output size. The agents get analysis libraries (`ast`,
`networkx`, `pandas`, ...) but the door to the outside world is the tools.

## Quickstart

```bash
pip install -r requirements.txt
cp env.example .env           # then fill in a token for your chosen backend
set -a; source .env; set +a   # export the vars

# Run from the directory that CONTAINS the Codebase_Cartographer/ folder.
python -m Codebase_Cartographer.main /path/to/some/repo
```

The report and dependency diagram are written into a folder named after the
analyzed repo (override the location with `-d/--out-dir`, the report filename
with `-o`).

Switch model backend by editing `CARTOGRAPHER_MODEL_TYPE` in `.env`
(`inference` / `litellm` / `openai` / `transformers`).

## Use it as a library

```python
from Codebase_Cartographer import build_cartographer, set_repo_root, ONBOARDING_BRIEF

set_repo_root("/path/to/repo")
agent = build_cartographer()
print(agent.run(ONBOARDING_BRIEF))
```

## Project layout

| File | Purpose |
|------|---------|
| `Codebase_Cartographer/tools.py`  | Guarded structure + git tools (the only I/O gateway) |
| `Codebase_Cartographer/agents.py` | Mapper, Historian, and the Synthesizer manager |
| `Codebase_Cartographer/config.py` | Model factory driven by env vars |
| `Codebase_Cartographer/main.py`   | CLI entry point |

## Safety notes

- `CodeAgent` executes model-written code. The default executor is **local**.
  For untrusted repos, sandbox it: in `agents.py` add `executor_type="docker"`
  (or `"e2b"`) to the agent constructors.
- The import graph and entry-point detection are **heuristics** — great for
  orientation, not a substitute for reading the code.