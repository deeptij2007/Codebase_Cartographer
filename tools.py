"""Tools for the Codebase Cartographer.

Design principle: the agents NEVER get raw `os` / `subprocess` access. Every
filesystem read and every git command goes through one of these tools, which
(a) keep all access inside the target repo, and (b) cap output size so a huge
file can't blow up the context window. The agents are free to write their own
analysis code with safe libraries (ast, collections, networkx, pandas...), but
the door to the outside world is these guarded functions.
"""

from __future__ import annotations

import ast
import shlex
import subprocess
from collections import Counter
from pathlib import Path

import networkx as nx
from smolagents import tool

# --------------------------------------------------------------------------- #
# Repo root + path safety
# --------------------------------------------------------------------------- #

_REPO_ROOT: Path | None = None
_OUTPUT_DIR: Path | None = None

IGNORE_DIRS = {
    ".git", "node_modules", "venv", ".venv", "env", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
    ".idea", ".vscode", ".tox", "target", ".next", "out", "coverage",
    ".gradle", "vendor", ".cache", "site-packages",
}

_MAX_CHARS = 6000  # hard cap on any single tool's textual output


def set_repo_root(path: str | Path) -> None:
    """Point every tool at the repository under analysis (call once at startup).
        INPUT : set_repo_root(".")     
        EFFECT: _REPO_ROOT = /home/claude/codebase-cartographer
    """
    global _REPO_ROOT
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")
    _REPO_ROOT = root


def _root() -> Path:
    """_Hands back the stored repo root, erroring out if it was never set.
        INPUT : _root()
        OUTPUT: /home/claude/codebase-cartographer
    """
    if _REPO_ROOT is None:
        raise RuntimeError("Repo root not set. Call set_repo_root() first.")
    return _REPO_ROOT


def set_output_dir(path: str | Path) -> None:
    """Choose where generated artifacts (e.g. the dependency diagram) are written.

    Keeping artifacts OUT of the analyzed repo means we never pollute the code
    under inspection. Creates the directory if it does not exist.
        INPUT : set_output_dir("nanoGPT")
        EFFECT: _OUTPUT_DIR = /home/anirban/Codebase_Cartographer/nanoGPT
    """
    global _OUTPUT_DIR
    out = Path(path).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    _OUTPUT_DIR = out


def _output_dir() -> Path:
    """Where to write artifacts; falls back to the repo root if never set."""
    return _OUTPUT_DIR if _OUTPUT_DIR is not None else _root()


def _safe(rel: str) -> Path:
    """
        The security gate. Joins a relative path onto the root, cleans up , and refuses anything that escapes the repo
        INPUT : "cartographer/config.py"
        OUTPUT: /home/claude/codebase-cartographer/cartographer/config.py
        INPUT : "../../../etc/passwd"
        OUTPUT: raises ValueError (escapes the repository root)
    """
    target = (_root() / rel).resolve()
    if target != _root() and _root() not in target.parents:
        raise ValueError(f"Path '{rel}' escapes the repository root.")
    return target


def _clip(text: str) -> str:
    """
        Caps long output so a giant file can't flood the AI's memory. Under the limit it returns text unchanged; over it, it trims and appends a note.

        INPUT : _clip("hello")
        OUTPUT: hello
        INPUT : _clip("x" * 6005)        # over the 6000 limit
        OUTPUT: xxxx...xxx ...[truncated, 5 more chars]
    """
    if len(text) > _MAX_CHARS:
        return text[:_MAX_CHARS] + f"\n...[truncated, {len(text) - _MAX_CHARS} more chars]"
    return text


def _iter_files(exts: tuple[str, ...] | None = None):
    """
        Walks every file in the repo, skipping junk folders (.git, node_modules, …), optionally filtered by extension. Hands back files one at a time.
        INPUT : _iter_files((".py",))     # first 3 shown
        OUTPUT: cartographer/main.py, cartographer/config.py, cartographer/__init__.py
    """
    root = _root()
    for p in root.rglob("*"):
        if any(part in IGNORE_DIRS for part in p.relative_to(root).parts):
            continue
        if p.is_file() and (exts is None or p.suffix in exts):
            yield p


# --------------------------------------------------------------------------- #
# Structure tools (for the Mapper)
# --------------------------------------------------------------------------- #

@tool
def list_files(subdir: str = ".", extensions: str = "", max_results: int = 200) -> str:
    """Lists files under a folder, skipping junk, filtered by extension, capped in count.
        INPUT : ("cartographer", ".py")
        OUTPUT: 
            cartographer/__init__.py
            cartographer/agents.py
            cartographer/config.py
            cartographer/main.py
            cartographer/tools.py 

    Args:
        subdir: Directory (relative to the repo root) to list. Use "." for the whole repo.
        extensions: Space-separated suffixes to keep, e.g. ".py .js .ts". Empty = all.
        max_results: Maximum number of paths to return.
    """
    exts = tuple(e if e.startswith(".") else "." + e for e in extensions.split()) or None
    base = _safe(subdir)
    root = _root()
    out = []
    for p in sorted(_iter_files(exts)):
        try:
            p.relative_to(base)
        except ValueError:
            continue
        out.append(str(p.relative_to(root)))
        if len(out) >= max_results:
            out.append(f"...[stopped at {max_results}]")
            break
    return _clip("\n".join(out) or "(no matching files)")


@tool
def read_file(path: str, start_line: int = 1, max_lines: int = 200) -> str:
    """Reads a slice of a text file, with line numbers and a header showing the range.
        INPUT : read_file("cartographer/config.py", 1, 3)
        OUTPUT: # cartographer/config.py  (lines 1-3 of 51)
           

    Args:
        path: File path relative to the repo root.
        start_line: 1-indexed line to start reading from.
        max_lines: Maximum number of lines to return.
    """
    target = _safe(path)
    if not target.is_file():
        return f"Not a file: {path}"
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:  # noqa: BLE001
        return f"Could not read {path}: {exc}"
    chunk = lines[max(0, start_line - 1): start_line - 1 + max_lines]
    numbered = "\n".join(f"{i + start_line:>5}  {ln}" for i, ln in enumerate(chunk))
    header = f"# {path}  (lines {start_line}-{start_line + len(chunk) - 1} of {len(lines)})\n"
    return _clip(header + numbered)


@tool
def file_stats() -> str:
    """Summarizes the repo: file count and total lines per extension.
    INPUT : file_stats()
    OUTPUT: ext        files     loc
        ----------------------------
        .py            5      563
        .txt           1        7
        .md            1       68
        .example       1       19
        ----------------------------
        TOTAL          8      657    
    
    """
    by_ext_files: Counter = Counter()
    by_ext_loc: Counter = Counter()
    for p in _iter_files():
        ext = p.suffix or "(none)"
        by_ext_files[ext] += 1
        try:
            by_ext_loc[ext] += sum(1 for _ in p.open("r", encoding="utf-8", errors="ignore"))
        except Exception:  # noqa: BLE001
            pass
    rows = ["ext        files     loc", "-" * 28]
    for ext, n in by_ext_files.most_common(30):
        rows.append(f"{ext:<10} {n:>5} {by_ext_loc[ext]:>8}")
    rows.append("-" * 28)
    rows.append(f"TOTAL      {sum(by_ext_files.values()):>5} {sum(by_ext_loc.values()):>8}")
    return _clip("\n".join(rows))


@tool
def detect_entrypoints() -> str:
    """Guesses where the program starts — known starter filenames plus any Python file containing __main__. Takes no input.
    INPUT : detect_entrypoints()
    OUTPUT: cartographer/main.py
        cartographer/main.py  (has __main__)
        cartographer/tools.py  (has __main__)
    
    """
    root = _root()
    findings = []
    candidates = [
        "main.py", "app.py", "manage.py", "wsgi.py", "asgi.py", "cli.py",
        "index.js", "server.js", "index.ts", "main.go", "main.rs", "Main.java",
        "package.json", "pyproject.toml", "setup.py", "Cargo.toml", "go.mod",
        "Dockerfile", "docker-compose.yml", "Makefile",
    ]
    for name in candidates:
        for hit in root.rglob(name):
            if any(part in IGNORE_DIRS for part in hit.relative_to(root).parts):
                continue
            findings.append(str(hit.relative_to(root)))
    # Python __main__ blocks are a strong signal.
    for p in _iter_files((".py",)):
        try:
            if '__main__' in p.read_text(encoding="utf-8", errors="ignore"):
                findings.append(str(p.relative_to(root)) + "  (has __main__)")
        except Exception:  # noqa: BLE001
            pass
    return _clip("\n".join(sorted(set(findings))) or "(no obvious entry points found)")


def _module_name(path: Path) -> str:
    """Turns a file path into Python's dotted module name (drops .py, joins folders with dots).
    INPUT : _module_name(".../cartographer/tools.py")
    OUTPUT: cartographer.tools
    """
    return ".".join(path.relative_to(_root()).with_suffix("").parts)


def _resolve_targets(importer: str, node, prefixes: set[str]) -> list[str]:
    """Given one parsed import statement, works out which module name(s) it refers to, correctly handling relative imports like from .config import x. 
    Keeps only the project's own modules..
    INPUT : a parsed `from .config import get_model`, importer="cartographer.agents"
    OUTPUT: ["cartographer.config"]
    INPUT : a parsed `import networkx`     
    OUTPUT: []                             
    """
    out = []
    if isinstance(node, ast.Import):
        out = [a.name for a in node.names]
    elif isinstance(node, ast.ImportFrom):
        if node.level:  # relative import: resolve against the importer's package
            parts = importer.split(".")
            base = parts[: len(parts) - node.level]
            tail = [node.module] if node.module else [a.name for a in node.names]
            out = [".".join(base + [t]) for t in tail]
        elif node.module:
            out = [node.module]
    return [n for n in out if n.split(".")[0] in prefixes]


def _python_import_graph() -> tuple[nx.DiGraph, dict[str, Path]]:
    """Build a DiGraph of internal Python module dependencies."""
    modules = {_module_name(p): p for p in _iter_files((".py",))}
    prefixes = {m.split(".")[0] for m in modules}
    g = nx.DiGraph()
    g.add_nodes_from(modules)
    for mod, path in modules.items():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            for name in _resolve_targets(mod, node, prefixes):
                target = next((m for m in modules if m == name or m.startswith(name + ".")
                               or name.startswith(m + ".")), None)
                if target and target != mod:
                    g.add_edge(mod, target)
    return g, modules


@tool
def build_import_graph(top_n: int = 20) -> str:
    """
        Build a Python import graph and report core modules and import cycles.

        Internal modules with the highest in-degree are the most depended-on (the
        load-bearing code). Cycles flag tangled areas worth refactoring/reading carefully.

        INPUT : build_import_graph()
        OUTPUT: Python modules: 5, internal import edges: 6

            Most depended-on modules (in-degree = how many modules import it):
                3  cartographer.tools
                2  cartographer.agents
                1  cartographer.config

        Args:
            top_n: How many of the most-imported modules to report.
    """
    g, _ = _python_import_graph()
    if g.number_of_nodes() == 0:
        return "(no Python modules found)"

    core = sorted(g.in_degree, key=lambda kv: kv[1], reverse=True)[:top_n]
    lines = [f"Python modules: {g.number_of_nodes()}, internal import edges: {g.number_of_edges()}",
             "", "Most depended-on modules (in-degree = how many modules import it):"]
    lines += [f"  {deg:>3}  {mod}" for mod, deg in core if deg > 0] or ["  (none)"]
    try:
        cycles = list(nx.simple_cycles(g))
        if cycles:
            lines.append("")
            lines.append(f"Import cycles found: {len(cycles)} (showing up to 5)")
            for cyc in cycles[:5]:
                lines.append("  " + " -> ".join(cyc + [cyc[0]]))
    except Exception:  # noqa: BLE001
        pass
    return _clip("\n".join(lines))


@tool
def export_dependency_diagram(top_n: int = 25) -> str:
    """Write a Mermaid dependency diagram of the most-connected Python modules to disk.

    Returns the path to the written file plus the Mermaid source so it can be
    embedded directly in the final report.
    INPUT : export_dependency_diagram(6)
    OUTPUT: Diagram written to .../_cartographer_dependencies.mmd

    ```mermaid
        graph LR
            n0["cartographer.main"]
            n1["cartographer.config"]
            ...
            n0 --> n3
            n0 --> n4
            n3 --> n4
    ```

    Args:
        top_n: Number of highest-degree modules to include in the diagram.
    """
    g, _ = _python_import_graph()
    if g.number_of_edges() == 0:
        return "(no internal Python import edges to diagram)"

    keep = {m for m, _ in sorted(g.degree, key=lambda kv: kv[1], reverse=True)[:top_n]}
    sub = g.subgraph(keep)
    alias = {m: f"n{i}" for i, m in enumerate(sub.nodes)}
    lines = ["```mermaid", "graph LR"]
    for m, a in alias.items():
        lines.append(f'    {a}["{m}"]')
    for u, v in sub.edges:
        lines.append(f"    {alias[u]} --> {alias[v]}")
    lines.append("```")
    mermaid = "\n".join(lines)

    out = _output_dir() / "_cartographer_dependencies.mmd"
    out.write_text(mermaid, encoding="utf-8")
    return f"Diagram written to {out}\n\n{_clip(mermaid)}"


# --------------------------------------------------------------------------- #
# History tools (for the Historian)
# --------------------------------------------------------------------------- #

_GIT_ALLOWED = {
    "log", "shortlog", "ls-files", "ls-tree", "blame", "diff",
    "rev-list", "show", "status", "branch", "tag", "describe",
}


def _git(args: list[str]) -> str:
    """
    Runs a git command inside the repo and returns its output (or a tidy error message if git fails). The other git tools call this.
    INPUT : _git(["log", "--oneline", "-n", "1"])
    OUTPUT: 22ddd1c cli, readme, deps

    
    """
    proc = subprocess.run(
        ["git", "--no-pager", *args],
        cwd=str(_root()), capture_output=True, text=True, timeout=45,
    )
    if proc.returncode != 0:
        return f"[git error] {proc.stderr.strip() or 'non-zero exit'}"
    return proc.stdout


@tool
def run_git(command: str) -> str:
    """Run a read-only git command inside the repository.

    INPUT : run_git("log --oneline -n 3")
    OUTPUT: 22ddd1c cli, readme, deps
        68a7f5f tweak tools again
        ed527f6 tweak tools
    INPUT : run_git("push origin main")
    OUTPUT: Subcommand not allowed. Permitted: blame, branch, describe, diff,
        log, ls-files, ls-tree, rev-list, shortlog, show, status, tag

    Only inspection subcommands are allowed (log, shortlog, blame, diff, show,
    ls-files, rev-list, status, branch, tag, describe). Do NOT include the
    leading word "git".

    Args:
        command: The git command, e.g. 'log --oneline -n 20' or 'shortlog -sne HEAD'.
    """
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        return f"Could not parse command: {exc}"
    if not parts or parts[0] not in _GIT_ALLOWED:
        return f"Subcommand not allowed. Permitted: {', '.join(sorted(_GIT_ALLOWED))}"
    return _clip(_git(parts))


@tool
def git_churn_hotspots(top_n: int = 15, since: str = "2 years ago") -> str:
    """Rank files by churn (number of commits touching them) — a fragility/risk proxy.
    INPUT : git_churn_hotspots(5)
    OUTPUT: commits  file
        ----------------------------------------
              3  cartographer/tools.py
              1  .env.example
              1  README.md
              1  cartographer/main.py
              1  requirements.txt

    Files that change constantly are often where bugs and complexity concentrate.

    Args:
        top_n: How many hotspot files to return.
        since: A git date expression bounding the history window (e.g. '1 year ago').
    """
    raw = _git(["log", f"--since={since}", "--name-only", "--format="])
    if raw.startswith("[git error]"):
        return raw
    counts = Counter(line.strip() for line in raw.splitlines() if line.strip())
    if not counts:
        return "(no commit history in the given window)"
    rows = ["commits  file", "-" * 40]
    rows += [f"{n:>7}  {f}" for f, n in counts.most_common(top_n)]
    return _clip("\n".join(rows))


@tool
def git_authorship(path: str = "") -> str:
    """Show contributor distribution (bus-factor signal) for the repo or one file.
    INPUT : git_authorship()
    OUTPUT: Top contributors (commits, name <email>):
             3  John Doe <jd@example.com>
             2  Jack Smith<js@example.com>
    INPUT : git_authorship("cartographer/tools.py")
    OUTPUT: Authorship of cartographer/tools.py:
        commits  author
        ------------------------------
              2  John Doe
              1  Jack Smith

    A file or repo dominated by a single author is a knowledge-concentration risk.

    Args:
        path: Optional file (relative to repo root). Empty = whole repository.
    """
    if path:
        _safe(path)  # validate it's inside the repo
        raw = _git(["log", "--format=%an", "--", path])
        if raw.startswith("[git error]"):
            return raw
        counts = Counter(a.strip() for a in raw.splitlines() if a.strip())
        rows = [f"Authorship of {path}:", "commits  author", "-" * 30]
        rows += [f"{n:>7}  {a}" for a, n in counts.most_common(15)]
        return _clip("\n".join(rows))
    return _clip("Top contributors (commits, name <email>):\n" + _git(["shortlog", "-sne", "HEAD"]))


# Convenient groupings for wiring up agents.
STRUCTURE_TOOLS = [
    list_files, read_file, file_stats, detect_entrypoints,
    build_import_graph, export_dependency_diagram,
]
HISTORY_TOOLS = [run_git, git_churn_hotspots, git_authorship]
