from __future__ import annotations

import html
import json
import webbrowser
from pathlib import Path

from .domain import RunRecord
from .state import StateStore
from .util import atomic_write_json, atomic_write_text


class ReportGenerator:
    """Generate portable, English-only JSON and standalone HTML run reports."""

    def __init__(self, state: StateStore, *, language: str = "en") -> None:
        self.state = state
        self.language = language

    def generate(self, record: RunRecord) -> tuple[Path, Path]:
        directory = self.state.artifact_dir(record.run_id, "report")
        json_path = directory / "report.json"
        html_path = directory / "report.html"
        payload = self._payload(record)
        atomic_write_json(json_path, payload)
        atomic_write_text(html_path, self._html(payload))
        return json_path, html_path

    def open(self, path: Path) -> None:
        webbrowser.open(path.resolve().as_uri())

    def _payload(self, record: RunRecord) -> dict[str, object]:
        return {
            "run": record.to_dict(),
            "summary": {
                "status": record.status.value,
                "tasks_total": len(record.tasks),
                "tasks_accepted": sum(1 for task in record.tasks if task.status.value == "accepted"),
                "tasks_blocked": sum(1 for task in record.tasks if task.status.value in {"blocked", "failed"}),
                "estimated_credits": record.estimated_credits,
                "actual_credits": record.actual_credits,
                "budget_credits": record.budget_credits,
                "total_tokens": record.usage.total_tokens,
                "reasoning_output_tokens": record.usage.reasoning_output_tokens,
                "current_commit": record.current_commit,
            },
        }

    def _html(self, payload: dict[str, object]) -> str:
        run = payload["run"]
        assert isinstance(run, dict)
        summary = payload["summary"]
        assert isinstance(summary, dict)
        title = "Codex Armada Report"
        tasks = run.get("tasks", [])
        rows = ""
        if isinstance(tasks, list):
            for item in tasks:
                if not isinstance(item, dict):
                    continue
                plan = item.get("plan", {}) if isinstance(item.get("plan"), dict) else {}
                route = item.get("route", {}) if isinstance(item.get("route"), dict) else {}
                source = _route_source(route)
                rows += f"""
                <tr>
                  <td><code>{_e(plan.get('id'))}</code><div class="muted">{_e(plan.get('title'))}</div></td>
                  <td><span class="badge">{_e(plan.get('risk'))}</span></td>
                  <td>{_e(route.get('worker_alias'))}<div class="muted">{_e(route.get('worker_effort'))} · {_e(route.get('worker_protocol') or 'standard')}</div></td>
                  <td><code>{_e(source)}</code></td>
                  <td>{_e(item.get('status'))}</td>
                  <td>{float(item.get('credits', 0.0)):.4f}</td>
                  <td><code>{_e(item.get('applied_commit_sha') or item.get('source_commit_sha') or '—')}</code></td>
                </tr>"""
        budget = summary.get("budget_credits")
        budget_value = "∞" if budget is None else f"{float(budget):.2f}"
        data_json = html.escape(json.dumps(payload, ensure_ascii=False, indent=2))
        return f"""<!doctype html>
<html lang="en" dir="ltr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
:root{{--bg:#07111f;--panel:#0d1b2d;--panel2:#12243a;--text:#eff6ff;--muted:#9fb2ca;--line:#243a55;--accent:#63e6be;--warn:#ffd166}}
*{{box-sizing:border-box}} body{{margin:0;background:linear-gradient(145deg,#06101d,#0b1b30 60%,#10243b);color:var(--text);font-family:Inter,Segoe UI,Tahoma,Arial,sans-serif;line-height:1.55}}
.container{{max-width:1260px;margin:auto;padding:32px 18px 72px}} h1{{font-size:clamp(30px,5vw,58px);margin:0 0 8px;letter-spacing:-1px}} h2{{margin-top:34px}} .sub{{color:var(--muted);font-size:17px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(185px,1fr));gap:14px;margin:26px 0}} .card{{background:rgba(13,27,45,.9);border:1px solid var(--line);border-radius:18px;padding:18px;box-shadow:0 18px 50px rgba(0,0,0,.22)}}
.k{{color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:.08em}} .v{{font-size:25px;font-weight:750;margin-top:5px;word-break:break-word}} table{{width:100%;border-collapse:collapse;background:rgba(13,27,45,.9);border:1px solid var(--line);border-radius:18px;overflow:hidden;display:block;overflow-x:auto}} th,td{{padding:14px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}} th{{color:var(--muted);font-size:13px}} tr:last-child td{{border-bottom:0}}
.badge{{display:inline-block;padding:3px 9px;border:1px solid #315071;border-radius:999px;background:#122a45}} code{{font-family:Cascadia Code,Consolas,monospace;font-size:12px}} .muted{{color:var(--muted);font-size:12px;margin-top:3px}} details{{margin-top:28px}} pre{{direction:ltr;text-align:left;white-space:pre-wrap;background:#040a12;border:1px solid var(--line);padding:16px;border-radius:14px;overflow:auto}}
</style>
</head>
<body><main class="container">
<div class="sub">Codex Armada · {_e(run.get('run_id'))}</div>
<h1>{title}</h1>
<div class="sub">{_e(run.get('goal'))}</div>
<section class="grid">
<div class="card"><div class="k">Status</div><div class="v">{_e(summary.get('status'))}</div></div>
<div class="card"><div class="k">Tasks</div><div class="v">{summary.get('tasks_accepted')}/{summary.get('tasks_total')}</div></div>
<div class="card"><div class="k">Credits</div><div class="v">{float(summary.get('actual_credits',0.0)):.3f}</div><div class="muted">Budget {budget_value}</div></div>
<div class="card"><div class="k">Tokens</div><div class="v">{int(summary.get('total_tokens',0)):,}</div><div class="muted">Reasoning {int(summary.get('reasoning_output_tokens',0)):,}</div></div>
<div class="card"><div class="k">Commit</div><div class="v"><code>{_e(summary.get('current_commit') or '—')}</code></div></div>
</section>
<h2>Tasks</h2>
<table><thead><tr><th>Task</th><th>Risk</th><th>Worker</th><th>Worker source</th><th>Status</th><th>Credits</th><th>Commit</th></tr></thead><tbody>{rows}</tbody></table>
<details><summary>Raw data</summary><pre>{data_json}</pre></details>
</main></body></html>"""


def _route_source(route: dict[str, object]) -> str:
    commit = str(route.get("worker_skill_commit") or "")
    repository = str(route.get("worker_skill_repository") or "")
    if commit:
        return f"{repository}@{commit[:12]}" if repository else commit[:12]
    return "built-in"


def _e(value: object) -> str:
    return html.escape(str(value if value is not None else ""))
