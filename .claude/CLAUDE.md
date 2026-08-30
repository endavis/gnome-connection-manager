@../AGENTS.md
@./rules/*.md

# BASIC CLAUDE INSTRUCTIONS

Claude's #1 priority is to use tokens efficiently:
- Keep responses brief and to the point
- Use local tools (Grep, Read, Edit) as a priority over Task tool
- Only use the Task tool when necessary
- Always inform user and ask for consent before starting sub agents

Examples of when to use local tools instead of Task tool:
- Updating types in function declarations
- Creating or updating documentation
- Renaming variables, functions, etc.
- Simple code refactoring

# TODOWRITE USAGE (MANDATORY)

When creating new code (functions, modules, commands, features), Claude MUST use TodoWrite to plan ALL steps:

**Required todo items for any code task:**
1. Implementation file(s)
2. Test file(s) - NEVER skip this
3. Run `doit check` to verify
4. Manual verification/testing

**Why this is mandatory:**
- Removes judgment calls about whether to write tests
- Makes testing systematic, not optional
- Ensures complete implementation (code + tests + validation)
- Provides visibility to user about progress

**Examples of when to use TodoWrite:**
- Creating new Python modules or functions
- Adding CLI commands or API endpoints
- Implementing new features or bug fixes
- Any task involving writing new Python code

**Example todo list for "create new CLI command":**
- [ ] Create src/__PACKAGE_NAME__/cli.py
- [ ] Create tests/test_cli.py with comprehensive tests
- [ ] Update pyproject.toml (if needed)
- [ ] Run doit check to verify all tests pass
- [ ] Test command manually

# DEVELOPMENT WORKFLOW (MANDATORY)

Before making ANY changes, Claude MUST:
1. Read .github/CONTRIBUTING.md and locate the "## Development Workflow" section
2. Verify the workflow: Issue → Branch → Commit → PR → Merge
3. **NEVER commit directly to main**
4. Ensure a GitHub Issue exists for the task
5. Create a branch linked to the issue
6. Work on the branch, then create a PR

# COMMIT WORKFLOW (MANDATORY)

When asked to create a commit or PR, Claude MUST:
1. Read .github/CONTRIBUTING.md and locate the "## Commit Guidelines" section
2. Review the commit message format rules under that section
3. Draft commit message following the exact format specified
4. Commit with `doit commit` when the session is interactive. It wraps commitizen
   and enforces the format. When it is not — a headless or delegated run cannot
   answer its prompts — use `git commit` with a message in the conventional
   format from step 1. Never `git commit` without that format.

NO EXCEPTIONS. If .github/CONTRIBUTING.md has fallen out of context, READ IT FIRST.
