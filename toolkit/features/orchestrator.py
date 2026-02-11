"""Orchestration logic for deployments."""

import typer

from toolkit.config.constants import MESSAGES, PATH_STRUCTURES
from toolkit.config.settings import get_settings
from toolkit.core.logging import logger
from toolkit.features import command, filesystem, validation


class DeploymentOrchestrator:
    """Orchestrates complex deployment workflows."""

    def __init__(self, env: str) -> None:
        self.env = env
        self.settings = get_settings(env)

    def setup_environment(self) -> None:
        """Perform initial setup for the environment."""
        logger.info(f"Setting up environment: {self.env}")

        if self.env == "dev":
            self._setup_dev()
        elif self.env == "staging":
            self._setup_staging()
        elif self.env == "prod":
            self._setup_prod()
        else:
            raise ValueError(f"Unknown environment: {self.env}")

    def deploy(self, skip_build: bool = False) -> None:
        """Execute full deployment workflow."""
        with logger.progress(f"Deploying to {self.env}...") as progress:
            task = progress.add_task("Deployment", total=4)

            if not skip_build:
                progress.update(task, description="Building applications...")
                self._build_applications()
                progress.advance(task)

            progress.update(task, description="Deploying infrastructure...")
            self._deploy_infrastructure()
            progress.advance(task)

            progress.update(task, description="Deploying applications...")
            self._deploy_applications()
            progress.advance(task)

            progress.update(task, description="Running health checks...")
            self.run_health_checks()
            progress.advance(task)

    def backup(self) -> None:
        """Perform backup operations."""
        if self.env in ["staging", "prod"]:
            self._run_ansible_playbook("backup.yml")
        else:
            logger.info(MESSAGES.INFO_CREATING_BACKUPS)
            from datetime import datetime

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = (
                self.settings.project_root
                / ".bckp"
                / f"docker_volumes_{self.env}_{timestamp}"
            )
            backup_dir.mkdir(parents=True, exist_ok=True)
            logger.success(f"Backup location created at {backup_dir}")

    def restore(self, backup_id: str) -> None:
        """Perform restore operations."""
        if self.env in ["staging", "prod"]:
            self._run_ansible_playbook(
                "restore.yml", extra_args=["-e", f"backup_id={backup_id}"]
            )
        else:
            logger.warning(MESSAGES.WARNING_RESTORE_NOT_IMPLEMENTED)

    def rollback(self) -> None:
        """Perform rollback operations."""
        if self.env in ["staging", "prod"]:
            self._run_ansible_playbook("rollback.yml")
        else:
            logger.info(MESSAGES.INFO_RESTART_TO_ROLLBACK)

    def check_status(self) -> None:
        """Check deployment status."""
        if self.env == "dev":
            self._check_dev_status()
        elif self.env == "staging":
            self._check_staging_status()
        elif self.env == "prod":
            self._check_prod_status()

    def run_health_checks(self) -> None:
        """Run health checks."""
        if self.env == "dev":
            self._health_checks_dev()
        else:
            self._health_checks_remote()

    # =========================================================================
    # Internal Implementation Details
    # =========================================================================

    def _run_ansible_playbook(
        self,
        playbook: str,
        limit: str | None = None,
        extra_args: list[str] | None = None,
    ) -> None:
        """Execute an Ansible playbook."""
        env_config = self.settings.get_environment(self.env)
        if not env_config.ansible_inventory:
            raise RuntimeError(f"No Ansible inventory configured for {self.env}")

        ansible_dir = self.settings.ansible_dir
        inventory_path = ansible_dir / env_config.ansible_inventory

        if not filesystem.check_file_exists(inventory_path, required=True):
            raise RuntimeError(f"Inventory file not found: {inventory_path}")

        limit_hosts = limit or self.env
        cmd = (
            f"ansible-playbook {ansible_dir}/playbooks/{playbook} "
            f"-i {inventory_path} --limit {limit_hosts} -e env={self.env}"
        )

        if extra_args:
            cmd = f"{cmd} {' '.join(extra_args)}"

        logger.info(f"Running: {cmd}")
        result = command.run(cmd, cwd=ansible_dir)

        if result.returncode != 0:
            raise RuntimeError(f"Playbook {playbook} failed for {self.env}")

    def _setup_dev(self) -> None:
        logger.info(MESSAGES.INFO_DEV_USES_LOCAL)
        validation.validate_dependencies()
        result = command.run(
            f"docker network inspect {self.settings.docker_network}", check=False
        )
        if result.returncode != 0:
            command.run(f"docker network create {self.settings.docker_network}")

    def _setup_staging(self) -> None:
        env_config = self.settings.get_environment("staging")
        if not env_config.ansible_inventory:
            raise typer.Exit(1)

        validation.validate_dependencies()
        try:
            command.run(
                "poetry run toolkit ansible generate staging",
                cwd=self.settings.project_root,
            )
        except Exception as exc:
            raise typer.Exit(1) from exc

        self._run_ansible_playbook("setup.yml", limit="staging")

    def _setup_prod(self) -> None:
        self._run_ansible_playbook("setup.yml")

    def _build_applications(self) -> None:
        applications = ["api", "web", "blog", "wiki"]
        for app in applications:
            try:
                app_dir = self.settings.project_root / PATH_STRUCTURES.APPS_DIR / app
                if not app_dir.exists():
                    continue
                command.run(
                    f"poetry run toolkit apps build {app} --env {self.env}",
                    cwd=self.settings.project_root,
                )
                if self.env != "dev":
                    command.run(
                        f"poetry run toolkit apps docker-build {app} --env {self.env}",
                        cwd=self.settings.project_root,
                    )
            except Exception as e:
                logger.warning(f"Failed to build {app}: {e}")

    def _deploy_infrastructure(self) -> None:
        if self.env in ["staging", "prod"]:
            self._run_ansible_playbook("deploy.yml")

    def _deploy_applications(self) -> None:
        if self.env == "dev":
            applications = ["api", "web", "blog", "wiki"]
            for app in applications:
                command.run(
                    f"poetry run toolkit apps up {app} --env dev",
                    cwd=self.settings.project_root,
                    check=False,
                )
        else:
            self._run_ansible_playbook("deploy-apps.yml")

    def _health_checks_dev(self) -> None:
        result = command.run(
            "docker ps --format 'table {{.Names}}\t{{.Status}}'", check=False
        )
        if result.returncode == 0:
            logger.console.print(result.stdout)

        from toolkit.features.health_check import HealthChecker

        checker = HealthChecker(self.env)
        results = checker.check_health()

        for r in results:
            if r.healthy:
                logger.success(f"✓ {r.service} is healthy ({r.reason})")
            else:
                logger.warning(f"✗ {r.service} is not responding ({r.reason})")

    def _health_checks_remote(self) -> None:
        try:
            self._run_ansible_playbook(
                "health-check.yml", extra_args=["--tags", "health"]
            )
        except RuntimeError:
            logger.warning(MESSAGES.WARNING_HEALTH_CHECKS_FAILED)
            self._run_ansible_playbook("main.yml", extra_args=["--tags", "ping"])

    def _check_dev_status(self) -> None:
        result = command.run("docker ps --format 'table {{.Names}}\t{{.Status}}'")
        logger.console.print(result.stdout)

    def _check_staging_status(self) -> None:
        try:
            self._run_ansible_playbook("deploy.yml", extra_args=["--tags", "verify"])
        except Exception as e:
            logger.warning(f"Status check failed: {e}")

    def _check_prod_status(self) -> None:
        production_services = {
            "api": "https://api.mlorente.dev/health",
            "web": "https://mlorente.dev",
            "blog": "https://blog.mlorente.dev",
            "wiki": "https://wiki.mlorente.dev",
        }
        for _service, url in production_services.items():
            command.run(f"curl -s -o /dev/null {url}", check=False)

        try:
            self._run_ansible_playbook(
                "main.yml", extra_args=["--tags", "verify", "--check"]
            )
        except RuntimeError:
            pass
