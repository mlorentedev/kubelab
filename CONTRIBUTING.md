# Contributing Guidelines

## 🌿 Branch Naming Conventions

- `master`: Stable code for production
- `develop`: Active development and integration
- `feature/*`: Feature branches for new functionality
- `hotfix/*`: Hotfix branches for urgent fixes

### Workflow

1. Create a new branch from `develop` for new features (`feature/name`) or from `master` for hotfixes (`hotfix/name`)

2. Make your changes and commit them

3. Create a Pull Request to merge your branch into `develop`.

4. After code review and approval, merge your branch into `develop`.

### Code conventions

- Frontend: Follow the Astro and HTMX conventions.
- Backend: Follow the Go conventions.
- Commits: Use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).

### 1. Master Branch

- Branch Name: `master`
- Purpose: Main production branch

### 2. Feature Branches

- Format: `feature/[descriptive-name]`
- Rules:
  - Must start with `feature/`
  - Use lowercase letters
  - Separate words with hyphens
- Examples:

  ```git
  feature/add-login-page
  feature/improve-navigation
  feature/user-authentication
  ```

### 3. Hotfix Branches

- Format: `hotfix/[descriptive-name]`
- Rules:
  - Must start with `hotfix/`
  - Use lowercase letters
  - Separate words with hyphens
- Examples:

  ```git
  hotfix/security-vulnerability
  hotfix/fix-login-bug
  hotfix/update-dependencies
  ```

## 📝 Pull Request Title Conventions

### Conventional Commits Format

`<type>(<optional scope>): <description>`

### Allowed Types

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style updates
- `refactor`: Code refactoring
- `test`: Test-related changes
- `chore`: Maintenance tasks

### PR Title Examples

#### Features

- `feat: add user registration`
- `feat(auth): implement login functionality`

#### Bug Fixes

- `fix: resolve pagination issue`
- `fix(api): handle authentication error`

#### Documentation

- `docs: update README with installation instructions`
- `docs(api): improve code comments`

#### Code Style

- `style: format code with prettier`
- `style(css): improve responsive design`

#### Refactoring

- `refactor: simplify user service`
- `refactor(database): optimize query performance`

#### Testing

- `test: add unit tests for user model`
- `test(e2e): implement login flow tests`

#### Maintenance

- `chore: update npm dependencies`
- `chore(ci): improve GitHub Actions workflow`

## 🤝 Contribution Workflow

1. Create a new branch from `master`
2. Follow branch naming conventions
3. Make your changes
4. Write clear, descriptive commit messages
5. Open a Pull Request with a conventional commit title
6. Ensure all CI checks pass
7. Request a code review

## 💡 Best Practices

- Keep branches focused and atomic
- Write clear, concise descriptions
- Break large features into smaller, manageable branches
- Rebase your branch on the latest `master` before creating a PR
- Ensure your code passes all linting and testing checks

## 🚨 What to Avoid

- Don't create branches with unclear or generic names
- Avoid mixing multiple features in a single branch
- Don't ignore linting or testing failures
- Never force-push to `master`

## 📢 Need Help?

If you're unsure about anything, don't hesitate to:

- Ask questions in the PR description
- Request clarification from maintainers
- Refer to these guidelines
