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


# ---------------------------------------------------------------------------
# Write / edit tools
# ---------------------------------------------------------------------------

def _get_repo(repo_name: str):
    owner = os.getenv("GITHUB_USERNAME")
    if not owner:
        raise ValueError("GITHUB_USERNAME env var not set.")
    return _github.get_repo(f"{owner}/{repo_name}")


@tool
def read_repo_file(repo_name: str, file_path: str, branch: str = "main") -> str:
    """Read the raw content of any file in one of Wesley's GitHub repos.

    Always call this before write_repo_file so you have the current content
    and the file's SHA (required for updates).

    Args:
        repo_name:  Bare repo name, e.g. "ai-me-assistant"
        file_path:  Path relative to repo root, e.g. "src/tools/github.py"
        branch:     Branch to read from (default: "main")

    Returns the file content plus its SHA on the last line (needed for edits).
    """
    try:
        repo = _get_repo(repo_name)
        item = repo.get_contents(file_path, ref=branch)
        content = item.decoded_content.decode("utf-8", errors="replace")
        total = len(content)
        MAX = 12_000
        truncated = total > MAX
        excerpt = content[:MAX]
        suffix = f"\n\n[Truncated — showing {MAX:,} of {total:,} chars]" if truncated else ""
        return (
            f"📄 {repo_name}/{file_path} (branch: {branch})\n"
            f"SHA: {item.sha}\n\n"
            f"{excerpt}{suffix}"
        )
    except Exception as e:
        return f"❌ Failed to read {repo_name}/{file_path}: {e}"


@tool
def write_repo_file(
    repo_name: str,
    file_path: str,
    content: str,
    commit_message: str,
    branch: str = "main",
    current_sha: str = "",
) -> str:
    """Create or update a file in one of Wesley's GitHub repos.

    To UPDATE an existing file you MUST supply its current SHA (get it by
    calling read_repo_file first — the SHA is on the second line of the output).
    To CREATE a new file, leave current_sha empty.

    Args:
        repo_name:       Bare repo name, e.g. "ai-me-assistant"
        file_path:       Path relative to repo root, e.g. "src/tools/foo.py"
        content:         Full new file content (not a diff — the whole file)
        commit_message:  Git commit message
        branch:          Branch to commit to (default: "main")
        current_sha:     SHA of the file being replaced (required for updates,
                         omit for new files)

    Returns the new commit SHA and URL on success.
    """
    try:
        repo = _get_repo(repo_name)
        kwargs = dict(
            path=file_path,
            message=commit_message,
            content=content.encode("utf-8"),
            branch=branch,
        )
        if current_sha:
            kwargs["sha"] = current_sha
            result = repo.update_file(**kwargs)
            verb = "Updated"
        else:
            result = repo.create_file(**kwargs)
            verb = "Created"
        commit = result["commit"]
        return (
            f"✅ {verb} {repo_name}/{file_path} on branch '{branch}'\n"
            f"Commit: {commit.sha[:8]} — {commit_message}\n"
            f"URL: {commit.html_url}"
        )
    except Exception as e:
        return f"❌ Failed to write {repo_name}/{file_path}: {e}"


@tool
def create_repo_branch(repo_name: str, branch_name: str, from_branch: str = "main") -> str:
    """Create a new branch in one of Wesley's GitHub repos.

    Use this before write_repo_file when you want changes reviewed via PR
    instead of going straight to main.

    Args:
        repo_name:    Bare repo name, e.g. "ai-me-assistant"
        branch_name:  New branch name, e.g. "fix/calendar-bug"
        from_branch:  Source branch to branch off (default: "main")
    """
    try:
        repo = _get_repo(repo_name)
        source = repo.get_branch(from_branch)
        repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=source.commit.sha)
        return f"✅ Branch '{branch_name}' created from '{from_branch}' in {repo_name}."
    except Exception as e:
        return f"❌ Failed to create branch: {e}"


@tool
def create_pull_request(
    repo_name: str,
    title: str,
    body: str,
    head_branch: str,
    base_branch: str = "main",
) -> str:
    """Open a pull request in one of Wesley's GitHub repos.

    Use after write_repo_file on a feature branch when you want to review
    changes before merging to main.

    Args:
        repo_name:    Bare repo name, e.g. "ai-me-assistant"
        title:        PR title
        body:         PR description / summary of changes
        head_branch:  Branch with the changes (e.g. "fix/calendar-bug")
        base_branch:  Target branch to merge into (default: "main")
    """
    try:
        repo = _get_repo(repo_name)
        pr = repo.create_pull(
            title=title,
            body=body,
            head=head_branch,
            base=base_branch,
        )
        return (
            f'✅ PR #{pr.number} opened: "{pr.title}"\n'
            f"URL: {pr.html_url}"
        )
    except Exception as e:
        return f"❌ Failed to create PR: {e}"
