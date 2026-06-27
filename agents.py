"""The agent hierarchy.

    Synthesizer (manager CodeAgent)
        ├── structure_mapper   — walks the tree, parses ASTs, builds the dep graph
        └── git_historian      — mines git history for hotspots and bus-factor

The two specialists are given `name` + `description`, which is what lets the
manager call them as if they were tools (`managed_agents=[...]`).
"""

from __future__ import annotations

from smolagents import CodeAgent, ToolCallingAgent

from .config import get_model
from .tools import HISTORY_TOOLS, STRUCTURE_TOOLS, read_file

# Analysis libraries the Mapper may import in its own code. Note: no `os`,
# no `subprocess`, no `sys` — filesystem access is only via the guarded tools.
MAPPER_IMPORTS = ["ast", "collections", "json", "re", "math", "itertools", "networkx", "pandas"]


def build_cartographer(model=None, verbosity_level: int = 1) -> CodeAgent:
    """Construct and return the top-level manager agent.
    
    INPUT : build_cartographer(model=<a model object>, verbosity_level=1)

    OUTPUT: a manager agent wired like this ─────────────────────────────

    MANAGER  'cartographer'  (CodeAgent)
    tools             : ['read_file']
    authorized imports: ['json', 'textwrap']
    max_steps         : 12
    manages           : ['structure_mapper', 'git_historian']

    └─ 'structure_mapper'  (CodeAgent)
         tools     : ['list_files', 'read_file', 'file_stats',
                      'detect_entrypoints', 'build_import_graph',
                      'export_dependency_diagram']
         max_steps : 14
         imports   : ['ast', 'collections', 'json', 're', 'math',
                      'itertools', 'networkx', 'pandas']   ← MAPPER_IMPORTS

    └─ 'git_historian'  (ToolCallingAgent)
         tools     : ['run_git', 'git_churn_hotspots', 'git_authorship']
         max_steps : 10
    
    """
    model = model or get_model()

    mapper = CodeAgent(
        tools=STRUCTURE_TOOLS,
        model=model,
        additional_authorized_imports=MAPPER_IMPORTS,
        max_steps=14,
        verbosity_level=verbosity_level,
        name="structure_mapper",
        description=(
            "Maps a codebase's structure. Give it a clear instruction such as "
            "'identify the architecture, core modules, entry points and layers'. "
            "It returns prose plus a Mermaid dependency diagram. It can read files, "
            "list the tree, compute LOC stats, find entry points, and build the "
            "Python import graph."
        ),
    )

    # The Historian's tools are atomic and need no code composition, so a
    # ToolCallingAgent is the cheaper, more reliable fit here.
    historian = ToolCallingAgent(
        tools=HISTORY_TOOLS,
        model=model,
        max_steps=10,
        verbosity_level=verbosity_level,
        name="git_historian",
        description=(
            "Investigates a repo's git history. Ask it for churn hotspots (fragile "
            "files), bus-factor / knowledge-concentration risks, and the recent pace "
            "and shape of changes. Returns a prose risk assessment."
        ),
    )

    manager = CodeAgent(
        tools=[read_file],
        model=model,
        managed_agents=[mapper, historian],
        additional_authorized_imports=["json", "textwrap"],
        max_steps=12,
        verbosity_level=verbosity_level,
        name="cartographer",
        description="Produces a developer onboarding map for an unfamiliar codebase.",
    )
    return manager


ONBOARDING_BRIEF = """\
You are onboarding a new engineer to an UNFAMILIAR codebase located at the repo \
root your tools are pointed at. Produce a single Markdown onboarding document.

Delegate to your team:
  - Ask `structure_mapper` for the architecture, core/load-bearing modules, the \
layering, entry points, and a Mermaid dependency diagram.
  - Ask `git_historian` for churn hotspots, bus-factor risks, and how the code \
has been evolving.

Then synthesize THEIR findings (verify a couple of key files yourself with \
read_file if useful) into a report with exactly these sections:

# <Repo name> — Onboarding Map
## What this system does        (2-4 sentence plain-English summary)
## Architecture at a glance      (the layers/components and how data flows)
## Dependency diagram            (embed the Mermaid block from the mapper)
## Core modules                  (the load-bearing files and why they matter)
## Risk & fragility map          (churn hotspots + bus-factor, from the historian)
## Start here: a reading path    (an ORDERED list of ~6 files to read first, each \
with one line on why)

Be concrete and cite real file paths. If something is uncertain, say so rather \
than inventing it. Return ONLY the Markdown document as your final answer.
"""
