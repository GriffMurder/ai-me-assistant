import os
from datetime import timezone

from dotenv import load_dotenv
from github import Github
from langchain_core.tools import tool

load_dotenv()

_github = Github(os.getenv("GITHUB_TOKEN"))
_README_CHARS = 2000
_OVERVIEW_LIMIT = 20


@tool
def analyze_repo(repo_name: str, question: str) -> str:
    """Analyze one of Wesley's GitHub repos and return its README, file tree,
    recent commits, and metadata so you can answer a question about it.

    Args:
        repo_name: Bare repo name (e.g. "ai-me-assistant"). Owner is taken
            from the GITHUB_USERNAME env var.
        question: What Wesley wants to know about this repo. Returned in the
            output so you can reason from the repo data and answer it.
    """
    try:
        owner = os.getenv("GITHUB_USERNAME")
        if not owner:
            return "❌ GITHUB_USERNAME env var not set."
        repo = _github.get_repo(f"{owner}/{repo_name}")

        meta = (
            f"**{repo.full_name}**\n"
            f"- Description: {repo.description or '(none)'}\n"
            f"- Language: {repo.language or '(unknown)'}\n"
            f"- Stars: {repo.stargazers_count} | Forks: {repo.forks_count}\n"
            f"- Default branch: {repo.default_branch}"
        )

        try:
            readme_full = repo.get_readme().decoded_content.decode("utf-8", errors="replace")
            readme = readme_full[:_README_CHARS]
            if len(readme_full) > _README_CHARS:
                readme += f"\n\n[Truncated — showing {_README_CHARS:,} of {len(readme_full):,} chars]"
        except Exception:
            readme = "(no README)"

        try:
            tree_items = repo.get_contents("")
            tree = "\n".join(
                f"- {'📁' if item.type == 'dir' else '📄'} {item.path}"
                for item in tree_items
            )
        except Exception as e:
            tree = f"(failed to list files: {e})"

        try:
            commits = "\n".join(
                f"- {c.commit.author.date.strftime('%Y-%m-%d')} — {c.commit.message.splitlines()[0]}"
                for c in list(repo.get_commits()[:5])
            )
        except Exception as e:
            commits = f"(failed to load commits: {e})"

        return (
            f"## Repo analysis\n{meta}\n\n"
            f"### README\n{readme}\n\n"
            f"### Top-level files\n{tree}\n\n"
            f"### Recent commits\n{commits}\n\n"
            f"---\n**Question:** {question}"
        )
    except Exception as e:
        return f"❌ Failed to analyze repo '{repo_name}': {e}"


@tool
def repo_overview() -> str:
    """Give a health summary of all Wesley's GitHub repos — last activity, language, open issues.

    Use this for weekly 'state of my apps' questions. For deep-diving into a
    single repo, use analyze_repo instead.
    """
    try:
        owner = os.getenv("GITHUB_USERNAME")
        if not owner:
            return "❌ GITHUB_USERNAME env var not set."

        user = _github.get_user()  # no arg = authenticated user, includes private repos
        repos = list(user.get_repos(sort="pushed", direction="desc"))[:_OVERVIEW_LIMIT]

        if not repos:
            return "No repositories found."

        lines = ["| Repo | Lang | Last Push | Open Issues | Description |",
                 "|------|------|-----------|-------------|-------------|"]
        for repo in repos:
            pushed = repo.pushed_at.strftime("%b %d, %Y") if repo.pushed_at else "—"
            lang = repo.language or "—"
            desc = (repo.description or "")[:60]
            issues = repo.open_issues_count
            lines.append(f"| {repo.name} | {lang} | {pushed} | {issues} | {desc} |")

        return (
            f"## GitHub Repo Overview ({len(repos)} repos, sorted by recent activity)\n\n"
            + "\n".join(lines)
        )
    except Exception as e:
        return f"❌ Failed to load repo overview: {e}"
