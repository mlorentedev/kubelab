 Toolkit Guide

The toolkit is a local operator tool that runs on your development machine to manage all environments (dev, staging, prod).

```
Your Dev Machine                Remote Servers
            
 tk services up web  SSH/→ Staging
 tk deployment     Ansible    (Docker only)
    deploy       SSH/→ Production   
  Ansible    (Docker only)
                                
```

Key point: Toolkit runs locally, manages servers remotely. Never installed on servers.

---

 Quick Start

 Setup (Once)

```bash
cd ~/Projects/cubelab.cloud
poetry install
echo "alias tk='poetry run toolkit'" >> ~/.bashrc
source ~/.bashrc
```

 Daily Usage

```bash
 Local development
tk services up web
tk services logs web
tk services up grafana

 Deploy to environments (from local machine!)
ENVIRONMENT=staging tk deployment deploy
ENVIRONMENT=prod tk deployment deploy
```

---

 Common Commands

 Applications & Services

```bash
tk services build web            Build app
tk services test api             Run tests
tk services up web               Start app
tk services down web             Stop app
tk services logs web             View logs
tk services logs web --no-follow   Static logs
tk services up grafana           Start service
tk services down grafana         Stop service
tk services logs grafana         View logs
tk services list                 List all services
```

 Deployment

```bash
ENVIRONMENT=staging tk deployment deploy    Deploy to staging
ENVIRONMENT=prod tk deployment deploy       Deploy to production
ENVIRONMENT=prod tk deployment status       Check status
```

 Configuration

```bash
tk config generate                         Generate configs
tk credentials generate user pass          Generate HTTP auth
```

 Terraform

```bash
ENVIRONMENT=staging tk terraform plan      Plan changes
ENVIRONMENT=prod tk terraform apply        Apply changes
```

---

 Modifying the Toolkit

 Making Changes

Changes are immediate - no rebuild needed!

```bash
 . Edit code
vim toolkit/cli/services.py

 . Test immediately
tk services --help
 Your changes show up!

 . Use it
tk services restart web
```

Why? `poetry run toolkit` uses source code directly from `toolkit/`.

 Toolkit Architecture

```
toolkit/
 main.py                     CLI entry point
 cli/                        Command groups
    services.py             App & service management
    deployment.py           Deployment
    config.py               Config generation
    credentials.py          Secret management
    terraform.py            Terraform wrapper
    tools.py                Utilities
 config/                     Settings
 core/                       Logging
 features/                   Business logic
```

 Adding a New Command

Example: Add `toolkit services restart`

```python
 toolkit/cli/services.py

@app.command("restart")
def restart_service(
    service_name: str = typer.Argument(..., help="Name of the service"),
    environment: str = typer.Option("dev", "--env", "-e", help="Environment"),
) -> None:
    """Restart a service."""
    logger.info(f"Restarting {service_name} service")

    compose_dir = settings.project_root / "infra" / "stacks" / "apps" / service_name

    if not compose_dir.exists():
        logger.error(f"Service not found: {service_name}")
        raise typer.Exit()

    _stop_docker_service(compose_dir, environment)
    _start_docker_service(compose_dir, environment)
```

Test immediately:
```bash
tk services restart web   Works!
```

 Adding a New App Type

Example: Support building a Next.js app

```python
 toolkit/cli/services.py - in build_app function

elif app_name == "dashboard":
    _build_nextjs_app(app_dir, environment)

 Add build function
def _build_nextjs_app(app_dir: Path, environment: str) -> None:
    """Build Next.js application."""
    nextjs_dir = app_dir / "nextjs-app"

    result = system.run_command_list(["npm", "ci"], cwd=nextjs_dir)
    if result.returncode != :
        logger.error("npm ci failed")
        raise typer.Exit()

    result = system.run_command_list(["npm", "run", "build"], cwd=nextjs_dir)
    if result.returncode == :
        logger.success("Next.js built successfully")
    else:
        logger.error("Build failed")
        raise typer.Exit()
```

 Type Safety

Always use type hints:

```python
from pathlib import Path

def process_app(app_name: str, environment: str) -> bool:
    compose_dir: Path = _get_compose_dir(app_name)
    return compose_dir.exists()
```

Run type check:
```bash
poetry run mypy toolkit/
```

 Code Formatting

```bash
poetry run black toolkit/
poetry run ruff check --fix toolkit/
```

 Common Patterns

Running Docker Compose:
```python
def _start_docker_service(compose_dir: Path, environment: str) -> None:
    env_file = compose_dir / f".env.{environment}"
    compose_file = compose_dir / f"compose.{environment}.yml"

    if not env_file.exists():
        logger.error(f"Env file not found: {env_file}")
        raise typer.Exit()

    result = system.run_command_list(
        [
            "docker", "compose",
            "--env-file", str(env_file),
            "-f", str(compose_file),
            "up", "-d"
        ],
        cwd=compose_dir,
    )

    if result.returncode == :
        logger.success("Service started")
    else:
        logger.error("Failed to start")
        raise typer.Exit()
```

Interactive Prompts:
```python
import typer

def delete_service(service_name: str) -> None:
    confirm = typer.confirm(
        f"Delete {service_name}?",
        default=False
    )
    if not confirm:
        raise typer.Exit()
     Proceed...
```

Progress Indicators:
```python
from rich.progress import Progress, SpinnerColumn, TextColumn

def deploy_all():
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
    ) as progress:
        task = progress.add_task("Deploying...", total=len(services))
        for service in services:
            progress.update(task, description=f"Deploying {service}...")
            _deploy_service(service)
            progress.advance(task)
```

---

 Troubleshooting

 "toolkit: command not found"

Set the alias:
```bash
alias tk='poetry run toolkit'
```

Or use directly:
```bash
poetry run toolkit services up web
```

 "Service directory not found"

Check configs exist:
```bash
ls infra/stacks/apps/web/
 Should show compose.*.yml, .env.*
```

 "Environment file not found"

Create from template:
```bash
cp infra/stacks/apps/web/.env.dev.example infra/stacks/apps/web/.env.dev
 Edit .env.dev with your values
```

 Changes not taking effect

Ensure using `poetry run`:
```bash
 If you have old global install:
pip uninstall toolkit

 Always use:
poetry run toolkit services up web
```

---

 FAQ

Q: Do I need to run `poetry build`?
A: No, never. That's for distributing packages (not needed).

Q: Does toolkit need to be on servers?
A: No! It runs on your dev machine, manages servers remotely.

Q: How do I deploy to production?
A: From your dev machine: `ENVIRONMENT=prod tk deployment deploy`

Q: What if I break something in toolkit code?
A: Just edit and fix. Changes are instant. No rollback needed.

---

 Quick Reference

| Task | Command |
|------|---------|
| Start app | `tk services up web` |
| Stop app | `tk services down web` |
| View logs | `tk services logs web` |
| Deploy staging | `ENVIRONMENT=staging tk deployment deploy` |
| Deploy production | `ENVIRONMENT=prod tk deployment deploy` |
| List services | `tk services list` |
| Start service | `tk services up grafana` |
| Generate configs | `tk config generate` |
| Terraform plan | `ENVIRONMENT=prod tk terraform plan` |
| Check deployment | `ENVIRONMENT=prod tk deployment status` |
| Help | `tk --help` |

---

 Summary

The toolkit is:
-  Local operator tool (runs on your dev machine)
-  Used via `poetry run toolkit` (or alias `tk`)
-  Manages all environments remotely
-  Changes take effect immediately (no build)

The toolkit is NOT:
-  Installed on remote servers
-  A distributed package
-  Requires `poetry build`

Remember: One tool, one location (your dev machine), manages everything everywhere.
