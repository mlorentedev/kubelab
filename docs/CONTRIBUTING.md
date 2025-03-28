# Development Workflow and Guidelines

## Branch Naming Conventions

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

## Commit Message Conventional Commits

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

## Versioning and Release Management

The project follows Semantic Versioning through commit messages:

- **Major version** increments with breaking changes:
  - Messages containing "BREAKING CHANGE:" or "!:"
  - Example: `feat!: breaking change description`  
- **Minor version** increments with new features:
  - Messages starting with `feat:`  
  - Example: `feat: add new search functionality`  
- **Patch version** increments with fixes/small changes:  
  - Messages starting with `fix:`, `docs:`, `chore:`, `style:`, etc.
  - Example: `fix: correct contact form error`  

You can force a specific increment using `#major`, `#minor`, or `#patch` in the commit message body.

### Pull Request Process

1. Create a feature branch from `develop`
2. Make your changes
3. Write tests for your changes
4. Ensure all tests pass
5. Commit with conventional commit messages
6. Push your branch and open a Pull Request to `develop`
7. Request a code review
8. After approval, merge into `develop`

### What to Avoid

- Vague branch names
- Mixing unrelated changes
- Ignoring failing tests
- Force-pushing to `master`
