# Contributing Guidelines

## 🌿 Branch Naming Conventions

`master`: Stable code for production  
`develop`: Active development and integration  
`feature/*`: Feature branches for new functionality  
`hotfix/*`: Hotfix branches for urgent fixes  

**Examples:**

```bash
# Feature branch example
git checkout -b feature/add-user-authentication

# Hotfix branch example
git checkout -b hotfix/fix-login-bug
```

## 🔄 Workflow

1. **Create a branch**:  
   - For new features: branch off `develop` → `feature/[short-descriptive-name]`  
   - For hotfixes: branch off `master` → `hotfix/[short-descriptive-name]`  

2. **Make your changes** and commit them following the commit guidelines (see below).  

3. **Push your branch** and open a Pull Request (PR) to merge into `develop`.  

4. **Review and approval**: Request a code review. Address any feedback and ensure CI checks pass.  

5. **Merge your PR** into `develop` after approval.  

## 📝 Commit Message Format

Follow the [Conventional Commits](https://www.conventionalcommits.org/) standard to keep commit history clear and consistent:

**Format:** `<type>(<optional scope>): <description>`

**Allowed Types:**

- `feat` → New feature  
- `fix` → Bug fix  
- `docs` → Documentation update  
- `style` → Code style changes (formatting, no logic changes)  
- `refactor` → Code restructuring without changing behavior  
- `test` → Adding or improving tests  
- `chore` → Maintenance tasks (e.g., dependency updates)  

**Examples:**

```bash
git commit -m "feat(auth): add user registration feature"
git commit -m "fix(api): resolve pagination issue"
git commit -m "docs: update installation instructions"
git commit -m "refactor: simplify database query logic"
git commit -m "chore: update npm dependencies"
```

## 🚦 Pull Request Guideline

When opening a Pull Request:

- **Title**: Use the same Conventional Commit format for the PR title.  
- **Description**: Clearly explain what the PR does and why it’s needed. Add context, screenshots, or references if helpful.  
- **Link issues**: If applicable, mention related issues (e.g., `Closes #42`).  
- **Ensure tests pass**: All CI checks and tests must pass before merging.  
- **Request a review**: Assign at least one reviewer for feedback. s

## ✅ Best Practices

- **Keep branches focused**: One feature or fix per branch.  
- **Write meaningful commit messages**: Clearly explain the purpose of each change.  
- **Keep PRs small**: Easier to review and less prone to merge conflicts.  
- **Rebase frequently**: Keep your branch up to date with `develop`.  
- **Write tests**: Ensure new functionality has adequate test coverage.

## 🚫 What to Avoid

- **Vague branch names**: Use descriptive and focused names.  
- **Mixing unrelated changes**: Stick to one feature or fix per branch.  
- **Ignoring failing tests**: Fix issues before merging.  
- **Force-pushing to `master`**: Never do this — use PRs for all changes.  

## 📢 Need Help?

If you're unsure about anything, don't hesitate to:

- Ask questions in the PR description
- Request clarification from maintainers
- Refer to these guidelines
