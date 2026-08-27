"""Evidence-backed Conduit scenery for the live Orca fleet.

The fleet model is live truth. This module is deliberately weaker: Conduit's
linked-repository graph is derived, so its output may decorate the floor but must
never decide whether a crewmate is alive, working, stalled, or dead.

    uv run python -m fleet_view.environment

Only read-only CLI surfaces are used. A missing, slow, or malformed dependency is
returned as a structured failure instead of escaping into the snapshot builder.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from collections import defaultdict
from pathlib import Path
from typing import Any


_CONDUIT_FALLBACK = Path.home() / ".local" / "bin" / "conduit"
_ATOM_LIMIT = 256
_COMMAND_TIMEOUT_SECONDS = 45
_SCENERY_WARNING = (
    "Scenery only: Conduit values are derived and must not be used as crewmate "
    "liveness or work-state truth."
)


class _ReadFailure(RuntimeError):
    """A dependency failed without making the environment builder raise."""


def _payload(brain: str, *, ok: bool, warnings: list[str]) -> dict[str, Any]:
    return {
        "ok": ok,
        "source": "conduit",
        "brain": brain,
        "generated_at": int(time.time()),
        "repos": {},
        "edges": [],
        "warnings": warnings,
    }


def _failure(brain: str, reason: str) -> dict[str, Any]:
    return _payload(brain, ok=False, warnings=[reason])


def _find_conduit() -> str | None:
    found = shutil.which("conduit")
    if found:
        return found
    if _CONDUIT_FALLBACK.is_file() and os.access(_CONDUIT_FALLBACK, os.X_OK):
        return str(_CONDUIT_FALLBACK)
    return None


def _run_json(command: list[str], *, surface: str) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise _ReadFailure(
            f"{surface} timed out after {_COMMAND_TIMEOUT_SECONDS} seconds"
        ) from exc
    except OSError as exc:
        raise _ReadFailure(f"{surface} could not start: {exc}") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown error").strip()
        detail = " ".join(detail.split())[-400:]
        raise _ReadFailure(f"{surface} failed: {detail}")
    try:
        value = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise _ReadFailure(f"{surface} returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise _ReadFailure(f"{surface} returned a non-object JSON value")
    return value


def _requested_repos(repos: list[str]) -> tuple[list[str], dict[str, str]]:
    ordered: list[str] = []
    by_folded_name: dict[str, str] = {}
    for value in repos:
        if not isinstance(value, str):
            continue
        name = value.strip()
        folded = name.casefold()
        if not name or folded in by_folded_name:
            continue
        ordered.append(name)
        by_folded_name[folded] = name
    return ordered, by_folded_name


def _topic(atom: dict[str, Any]) -> str | None:
    metadata = atom.get("metadata")
    if not isinstance(metadata, dict):
        return None
    for key in ("repo_signal", "pattern_label", "implementation_pattern"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.strip().replace("_", " ").split())
    return None


def _repo_scenery(
    derivations: dict[str, Any], requested: dict[str, str]
) -> dict[str, dict[str, Any]]:
    nodes = derivations.get("nodes")
    if not isinstance(nodes, dict):
        raise _ReadFailure("conduit atom derivations omitted nodes")
    documents = nodes.get("source_documents")
    atoms = nodes.get("graph_memory_atoms")
    if not isinstance(documents, list) or not isinstance(atoms, list):
        raise _ReadFailure("conduit atom derivations had an unexpected node shape")

    repo_by_document: dict[str, str] = {}
    for document in documents:
        if not isinstance(document, dict):
            continue
        metadata = document.get("metadata")
        if not isinstance(metadata, dict):
            continue
        repo_name = metadata.get("repo_name")
        document_id = document.get("source_document_id")
        if not isinstance(repo_name, str) or not isinstance(document_id, str):
            continue
        requested_name = requested.get(repo_name.casefold())
        if requested_name:
            repo_by_document[document_id] = requested_name

    themes: dict[str, set[str]] = defaultdict(set)
    confidences: dict[str, list[float]] = defaultdict(list)
    evidence_by_theme: dict[str, dict[str, str]] = defaultdict(dict)
    for atom in atoms:
        if not isinstance(atom, dict):
            continue
        if atom.get("atom_type") not in {"linked_repo_signal", "linked_repo_pattern"}:
            continue
        document_id = atom.get("source_document_id")
        if not isinstance(document_id, str) or document_id not in repo_by_document:
            continue
        topic = _topic(atom)
        if topic is None:
            continue
        repo_name = repo_by_document[document_id]
        themes[repo_name].add(topic)
        confidence = atom.get("confidence")
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
            confidences[repo_name].append(max(0.0, min(1.0, float(confidence))))
        evidence_by_theme[repo_name].setdefault(
            topic, f"source-graph://document/{document_id}"
        )

    result: dict[str, dict[str, Any]] = {}
    for repo_name in sorted(themes, key=str.casefold):
        values = confidences[repo_name]
        result[repo_name] = {
            # No current read-only CLI field is a repo-level summary. Null is more
            # truthful than synthesizing one from filenames or topic labels.
            "summary": None,
            "themes": sorted(themes[repo_name], key=str.casefold),
            "confidence": round(sum(values) / len(values), 3) if values else 0.0,
            # One resolvable document per theme is enough to audit the claim;
            # returning every matching file turns a small scenery record into a dump.
            "evidence": list(dict.fromkeys(
                evidence_by_theme[repo_name][theme]
                for theme in sorted(themes[repo_name], key=str.casefold)
            )),
        }
    return result


def build_environment(repos: list[str], brain: str = "fyx") -> dict:
    """Never raises; failures preserve the full schema and explain why."""
    safe_brain = brain.strip() if isinstance(brain, str) else ""
    if not safe_brain:
        return _failure(str(brain), "brain must be a non-empty string")

    try:
        requested_order, requested = _requested_repos(repos)
        conduit = _find_conduit()
        if conduit is None:
            return _failure(safe_brain, "conduit CLI not found on PATH")

        status = _run_json(
            [conduit, "brains", "status", "--brain", safe_brain],
            surface=f"conduit brain {safe_brain!r}",
        )
        source_counts = status.get("source_counts")
        if not isinstance(source_counts, dict):
            raise _ReadFailure("conduit brain status omitted source_counts")

        warnings = [_SCENERY_WARNING]
        environment = _payload(safe_brain, ok=True, warnings=warnings)
        linked_count = source_counts.get("linked_repo:repo_file", 0)
        if not isinstance(linked_count, int) or linked_count <= 0:
            warnings.append("Conduit carries no linked-repo documents for this brain.")
            warnings.append(
                "No repo-to-repo evidence was available; edges are intentionally empty."
            )
            return environment

        derivations = _run_json(
            [
                conduit,
                "brain",
                "atom-derivations",
                safe_brain,
                "--atom-limit",
                str(_ATOM_LIMIT),
                "--max-related",
                "1",
                "--no-review-items",
                "--shape",
                "normalized",
            ],
            surface=f"conduit atom derivations for brain {safe_brain!r}",
        )
        environment["repos"] = _repo_scenery(derivations, requested)
        warnings.append(
            f"Themes use a bounded read of {_ATOM_LIMIT} source-backed atoms and may "
            "not be exhaustive."
        )
        if environment["repos"]:
            warnings.append(
                "Conduit exposes no evidence-backed repo summary on this read surface; "
                "summaries are null."
            )

        missing = [name for name in requested_order if name not in environment["repos"]]
        if missing:
            sample = ", ".join(missing[:8])
            suffix = f" and {len(missing) - 8} more" if len(missing) > 8 else ""
            warnings.append(
                f"No sampled Conduit repo evidence matched: {sample}{suffix}."
            )

        # The current dependable CLI exposes repo -> source containment, not a
        # brain-scoped repo -> repo relationship with pair evidence. Shared themes
        # are not enough to invent adjacency.
        warnings.append(
            "Conduit exposes no brain-scoped repo-to-repo relationship read; "
            "edges are intentionally empty."
        )
        return environment
    except Exception as exc:  # never let derived scenery crash live truth
        return _failure(safe_brain, str(exc) or exc.__class__.__name__)


def _operator_repos() -> tuple[list[str], str | None]:
    orca = shutil.which("orca")
    if orca is None:
        return [], "orca CLI not found on PATH; operator repos are unavailable"
    try:
        payload = _run_json(
            [orca, "worktree", "ps", "--json"], surface="orca worktree list"
        )
        worktrees = ((payload.get("result") or {}).get("worktrees")) or []
        if not isinstance(worktrees, list):
            raise _ReadFailure("orca worktree list had an unexpected shape")
        repos = {
            row["repo"].strip()
            for row in worktrees
            if isinstance(row, dict)
            and isinstance(row.get("repo"), str)
            and row["repo"].strip()
        }
        if not repos:
            return [], "orca reported no repository worktrees"
        return sorted(repos, key=str.casefold), None
    except Exception as exc:
        return [], str(exc) or exc.__class__.__name__


def main() -> int:
    repos, error = _operator_repos()
    if error:
        result = _failure("fyx", error)
    else:
        result = build_environment(repos)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
