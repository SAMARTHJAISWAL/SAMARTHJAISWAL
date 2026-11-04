"""Render the profile stats card as light and dark SVGs.

Reads public data from the GitHub GraphQL API with the token in GITHUB_TOKEN
and writes stats.svg and stats-dark.svg to the output directory. Standard
library only, so it runs on a bare Actions runner.

    python scripts/profile_card.py --user SAMARTHJAISWAL --out dist
    python scripts/profile_card.py --sample --out dist   # offline preview
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape

QUERY = """
query($login: String!) {
  user(login: $login) {
    pullRequests { totalCount }
    repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC, first: 100) {
      totalCount
      nodes {
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
    contributionsCollection {
      totalCommitContributions
      contributionCalendar { totalContributions }
    }
  }
}
"""

# Build and tooling files say little about what someone writes.
SKIP_LANGUAGES = {"Makefile", "Dockerfile", "Shell", "PowerShell", "Procfile", "Batchfile"}
# Notebooks are Python as far as a reader is concerned.
MERGE_LANGUAGES = {"Jupyter Notebook": "Python"}
# A merge target may only appear through merged repos, so it needs its own colour.
LANGUAGE_COLORS = {"Python": "#3572A5"}

THEMES = {
    "light": {"bg": "#ffffff", "border": "#d0d7de", "title": "#1f2328", "text": "#59636e", "value": "#1f2328", "track": "#eef1f4"},
    "dark": {"bg": "#0d1117", "border": "#30363d", "title": "#f0f6fc", "text": "#9198a1", "value": "#f0f6fc", "track": "#21262d"},
}

FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"


def fetch(login: str, token: str) -> dict:
    body = json.dumps({"query": QUERY, "variables": {"login": login}}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json", "User-Agent": "profile-card"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if payload.get("errors"):
        raise SystemExit(f"GraphQL errors: {payload['errors']}")
    return payload["data"]["user"]


def summarise(user: dict) -> dict:
    """Totals plus each language's share, with every repo weighted equally."""
    shares: Counter[str] = Counter()
    colors: dict[str, str] = {}
    counted = 0
    for repo in user["repositories"]["nodes"]:
        edges = []
        for e in repo["languages"]["edges"]:
            name = e["node"]["name"]
            if name in SKIP_LANGUAGES:
                continue
            if name in MERGE_LANGUAGES:
                edges.append((MERGE_LANGUAGES[name], e["size"]))
            else:
                edges.append((name, e["size"]))
                colors.setdefault(name, e["node"]["color"] or "#8b949e")
        total = sum(size for _, size in edges)
        if not total:
            continue
        counted += 1
        for name, size in edges:
            shares[name] += size / total
    languages = [
        (name, share / counted, colors.get(name, LANGUAGE_COLORS.get(name, "#8b949e")))
        for name, share in shares.most_common(6)
    ] if counted else []
    contributions = user["contributionsCollection"]
    return {
        "contributions": contributions["contributionCalendar"]["totalContributions"],
        "commits": contributions["totalCommitContributions"],
        "pull_requests": user["pullRequests"]["totalCount"],
        "repos": user["repositories"]["totalCount"],
        "languages": languages,
    }


def render(stats: dict, theme: dict) -> str:
    width, height = 840, 190
    metrics = [
        ("Contributions, last year", stats["contributions"]),
        ("Commits, last year", stats["commits"]),
        ("Pull requests", stats["pull_requests"]),
        ("Public repositories", stats["repos"]),
    ]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="GitHub stats">',
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="10" fill="{theme["bg"]}" stroke="{theme["border"]}"/>',
        f'<g font-family="{FONT}">',
        f'<text x="28" y="40" font-size="16" font-weight="600" fill="{theme["title"]}">Activity</text>',
    ]
    for i, (label, value) in enumerate(metrics):
        x, y = 28 + (i % 2) * 190, 86 + (i // 2) * 62
        parts.append(f'<text x="{x}" y="{y}" font-size="26" font-weight="700" fill="{theme["value"]}">{value:,}</text>')
        parts.append(f'<text x="{x}" y="{y + 20}" font-size="12" fill="{theme["text"]}">{escape(label)}</text>')

    lx, bar_w = 440, 372
    parts.append(f'<line x1="410" y1="28" x2="410" y2="{height - 28}" stroke="{theme["border"]}"/>')
    parts.append(f'<text x="{lx}" y="40" font-size="16" font-weight="600" fill="{theme["title"]}">Languages across my repos</text>')
    parts.append(f'<clipPath id="bar"><rect x="{lx}" y="58" width="{bar_w}" height="10" rx="5"/></clipPath>')
    parts.append(f'<rect x="{lx}" y="58" width="{bar_w}" height="10" rx="5" fill="{theme["track"]}"/>')
    total = sum(share for _, share, _ in stats["languages"]) or 1
    offset = 0.0
    parts.append('<g clip-path="url(#bar)">')
    for name, share, color in stats["languages"]:
        w = bar_w * share / total
        parts.append(f'<rect x="{lx + offset:.2f}" y="58" width="{w:.2f}" height="10" fill="{color}"/>')
        offset += w
    parts.append("</g>")
    for i, (name, share, color) in enumerate(stats["languages"]):
        x, y = lx + (i % 2) * 190, 98 + (i // 2) * 28
        parts.append(f'<circle cx="{x + 5}" cy="{y - 4}" r="5" fill="{color}"/>')
        parts.append(f'<text x="{x + 16}" y="{y}" font-size="13" fill="{theme["value"]}">{escape(name)}'
                     f'<tspan fill="{theme["text"]}"> {share * 100:.0f}%</tspan></text>')
    parts.append("</g></svg>")
    return "\n".join(parts) + "\n"


SAMPLE = {
    "contributions": 200, "commits": 165, "pull_requests": 33, "repos": 32,
    "languages": [("Python", 0.462, "#3572A5"), ("JavaScript", 0.237, "#f1e05a"), ("HTML", 0.102, "#e34c26"),
                  ("TypeScript", 0.069, "#3178c6"), ("CSS", 0.051, "#663399"), ("Java", 0.036, "#b07219")],
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--user", default="SAMARTHJAISWAL")
    parser.add_argument("--out", default="dist")
    parser.add_argument("--sample", action="store_true", help="render built-in sample data without calling the API")
    args = parser.parse_args()

    if args.sample:
        stats = SAMPLE
    else:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise SystemExit("GITHUB_TOKEN is not set")
        stats = summarise(fetch(args.user, token))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "stats.svg").write_text(render(stats, THEMES["light"]), encoding="utf-8")
    (out / "stats-dark.svg").write_text(render(stats, THEMES["dark"]), encoding="utf-8")
    print(json.dumps({k: v for k, v in stats.items() if k != "languages"}), [n for n, _, _ in stats["languages"]])


if __name__ == "__main__":
    main()
