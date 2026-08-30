---
name: codex-plan
description: Use when planning work for a GitHub issue in this repository from a Codex session. Drafts an implementation plan, iterates with the user, and posts the approved plan comment with the repo's required header format.
---

# Plan Issue

Create an implementation plan for a GitHub issue in this repository.

## When to use

Use this skill when the user wants a Codex-native equivalent of the repository's planning workflow for an issue.

Expected prompt shape:

- `$codex-plan plan issue 399`
- `$codex-plan create an implementation plan for issue 399`

If the issue number is missing, ask for it before continuing.

## Instructions

1. Validate the issue exists and is open:
   ```bash
   gh issue view <issue-number> --json number,title,state,labels
   ```
   - If the issue does not exist, stop and tell the user.
   - If the issue is closed, stop and ask whether to reopen it or stop.

2. Check for an existing plan comment:
   ```bash
   gh api repos/{owner}/{repo}/issues/<issue-number>/comments --jq '.[].body' | grep -E "^#+ Implementation Plan for"
   ```
   - If one already exists, warn the user that continuing will post a new plan comment.

3. Read the project rules before planning:
   - `AGENTS.md`
   - `.github/ISSUE_TEMPLATE/feature_request.yml` for feature scope expectations
   - `docs/development/ai/architectural-conventions.md`

4. Fetch the full issue details:
   ```bash
   gh issue view <issue-number> --json title,body,labels,assignees
   ```
   - Identify the goal, success criteria, constraints, and whether the issue has `needs-adr`.

5. Explore the relevant repo context:
   - Read only the files needed to understand the affected workflow or feature area.
   - Check for related ADRs in `docs/decisions/`.
   - If multiple valid approaches remain, discuss them with the user before deciding.

6. Draft the plan in this exact structure:
   ```markdown
   ## Implementation Plan for #<number>: <title>

   ### Overview
   Brief description of what will be done.

   ### Files to Create/Modify
   - [ ] `path/to/file` — description

   ### Test Plan
   - [ ] Concrete test case

   ### Documentation
   - [ ] Docs to update
   - [ ] ADR needed: yes/no

   ### Validation
   - [ ] `doit check` passes
   - [ ] Manual verification step

   ### Risks and Considerations
   - Key trade-off or implementation risk
   ```

7. Iterate with the user until they explicitly approve the plan. Do not post anything to GitHub before approval.

8. Post the approved plan as an issue comment with the exact header format above:
   ```bash
   gh issue comment <issue-number> --body "<approved plan markdown>"
   ```

9. Tell the user the plan was posted and that the next Codex workflow step is `$codex-implement`.
