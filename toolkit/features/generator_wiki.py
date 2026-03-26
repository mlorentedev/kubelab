"""Wiki documentation collection and generation."""

import shutil
import subprocess
from pathlib import Path
from typing import Any

from toolkit.config.constants import MESSAGES, PATH_STRUCTURES
from toolkit.core.logging import logger
from toolkit.features.generator_base import BaseGenerator


class WikiGenerator(BaseGenerator):
    """Handles wiki documentation collection and generation with MkDocs."""

    def __init__(self, project_root: Path | None = None, environment: str = "dev"):
        """Initialize wiki generator.

        Args:
            project_root: Optional project root path (uses settings if not provided)
            environment: Environment name (dev, staging, prod)
        """
        super().__init__()
        if project_root:
            self.project_root = project_root
        self.environment = environment
        self.wiki_docs_path = self.project_root / PATH_STRUCTURES.WIKI_DOCS

    def generate(self, env: str) -> dict[str, Any]:
        """Generate wiki configuration and collect documentation.

        Args:
            env: Environment name (dev, staging, prod)

        Returns:
            Dictionary with success status and list of generated files
        """
        try:
            # Step 1: Collect all documentation
            if not self.collect_all_documentation():
                return {"success": False, "error": "Documentation collection failed"}

            # Step 2: Process mkdocs.yml.j2 template
            wiki_path = self.project_root / PATH_STRUCTURES.WIKI
            template_path = wiki_path / "mkdocs.yml.j2"
            output_path = wiki_path / "mkdocs.yml"

            if not template_path.exists():
                logger.warning(f"Wiki template not found (skipping): {template_path}")
                return {"success": True, "files": [], "skipped": True}

            # Process template with environment variables from YAML+SOPS
            if not self.replace_placeholders(template_path, output_path, env):
                return {"success": False, "error": "Placeholder replacement failed"}

            # Step 3: Optionally build wiki
            if env != "dev":  # Only build for staging/prod
                if not self.build_wiki():
                    return {"success": False, "error": "Wiki build failed"}

            logger.success(MESSAGES.SUCCESS_WIKI_GENERATED.format(env))
            return {"success": True, "files": [str(output_path)]}

        except Exception as e:
            logger.error(MESSAGES.ERROR_WIKI_GENERATION_FAILED.format(str(e)))
            return {"success": False, "error": str(e)}

    def collect_all_documentation(self) -> bool:
        """Collect documentation from all sources.

        Returns:
            True if collection succeeds, False otherwise
        """
        try:
            logger.info(MESSAGES.INFO_WIKI_COLLECTING_DOCS)

            # Collect from each source
            self._collect_apps_documentation()
            self._collect_edge_documentation()
            self._collect_infra_documentation()
            self._collect_services_documentation()
            self._collect_guides()
            self._collect_adr_documentation()
            self._collect_scripts_documentation()
            self._copy_assets()

            return True
        except Exception as e:
            logger.error(MESSAGES.ERROR_WIKI_COLLECTION_FAILED.format(str(e)))
            return False

    def build_wiki(self) -> bool:
        """Build wiki using mkdocs.

        Returns:
            True if build succeeds, False otherwise
        """
        try:
            logger.info(MESSAGES.INFO_WIKI_BUILDING)

            wiki_dir = self.project_root / PATH_STRUCTURES.WIKI
            subprocess.run(
                ["mkdocs", "build"],
                cwd=wiki_dir,
                check=True,
                capture_output=True,
                text=True,
            )

            logger.success(MESSAGES.SUCCESS_WIKI_BUILT)
            return True

        except FileNotFoundError:
            logger.error(MESSAGES.ERROR_MKDOCS_NOT_FOUND)
            return False
        except subprocess.CalledProcessError as e:
            logger.error(MESSAGES.ERROR_WIKI_BUILD_FAILED.format(e.stderr))
            return False

    def serve_wiki(self, host: str = "127.0.0.1", port: int = 8000) -> bool:
        """Serve the wiki using MkDocs development server.

        Args:
            host: Host to bind to (default: 127.0.0.1)
            port: Port to bind to (default: 8000)

        Returns:
            True if server starts successfully, False otherwise
        """
        logger.info(f"Starting wiki development server on {host}:{port}...")

        try:
            wiki_dir = self.project_root / PATH_STRUCTURES.WIKI
            subprocess.run(
                ["mkdocs", "serve", "--dev-addr", f"{host}:{port}"],
                cwd=wiki_dir,
                check=True,
            )
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to serve wiki: {e}")
            return False
        except FileNotFoundError:
            logger.error("MkDocs not found. Please install it: pip install mkdocs mkdocs-material")
            return False
        except KeyboardInterrupt:
            logger.info("Wiki server stopped")
            return True

    def _collect_apps_documentation(self) -> None:
        """Collect README files from apps/."""
        apps_dir = self.project_root / "apps"
        target_dir = self.wiki_docs_path / "apps"

        for app_dir in sorted(apps_dir.iterdir()):
            if not app_dir.is_dir() or app_dir.name.startswith("."):
                continue

            readme = app_dir / "README.md"
            if readme.exists():
                app_target = target_dir / app_dir.name
                app_target.mkdir(parents=True, exist_ok=True)
                shutil.copy2(readme, app_target / "index.md")
                logger.info(MESSAGES.INFO_WIKI_COLLECTED_APP.format(app_dir.name))

    def _collect_edge_documentation(self) -> None:
        """Collect README files from edge/ services."""
        edge_dir = self.project_root / "edge"
        target_dir = self.wiki_docs_path / "edge"

        if not edge_dir.exists():
            return

        for service_dir in sorted(edge_dir.iterdir()):
            if not service_dir.is_dir() or service_dir.name.startswith("."):
                continue

            readme = service_dir / "README.md"
            if readme.exists():
                service_target = target_dir / service_dir.name
                service_target.mkdir(parents=True, exist_ok=True)
                shutil.copy2(readme, service_target / "index.md")
                logger.info(MESSAGES.INFO_WIKI_COLLECTED_EDGE.format(service_dir.name))

    def _collect_infra_documentation(self) -> None:
        """Collect README files from infra/."""
        infra_dir = self.project_root / "infra"
        target_dir = self.wiki_docs_path / "infra"

        if not infra_dir.exists():
            return

        for item in sorted(infra_dir.iterdir()):
            if not item.is_dir() or item.name.startswith(".") or item.name == "compose":
                continue

            readme = item / "README.md"
            if readme.exists():
                item_target = target_dir / item.name
                item_target.mkdir(parents=True, exist_ok=True)
                shutil.copy2(readme, item_target / "index.md")
                logger.info(MESSAGES.INFO_WIKI_COLLECTED_INFRA.format(item.name))

    def _collect_services_documentation(self) -> None:
        """Collect README files from infra/stacks/services/."""
        services_dir = self.project_root / PATH_STRUCTURES.INFRA_STACKS_SERVICES
        target_dir = self.wiki_docs_path / "services"

        if not services_dir.exists():
            return

        # Categorize by subdirectory (core, observability, security, etc.)
        for category_dir in sorted(services_dir.iterdir()):
            if not category_dir.is_dir() or category_dir.name.startswith("."):
                continue

            for service_dir in sorted(category_dir.iterdir()):
                if not service_dir.is_dir() or service_dir.name.startswith("."):
                    continue

                readme = service_dir / "README.md"
                if readme.exists():
                    service_target = target_dir / service_dir.name
                    service_target.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(readme, service_target / "index.md")
                    logger.info(MESSAGES.INFO_WIKI_COLLECTED_SERVICE.format(service_dir.name))

    def _collect_guides(self) -> None:
        """Collect guides from docs/."""
        docs_dir = self.project_root / "docs"
        target_dir = self.wiki_docs_path / "guides"

        if not docs_dir.exists():
            return

        for doc_file in sorted(docs_dir.glob("*.md")):
            if doc_file.name == "README.md":
                continue

            # Convert filename to guide name (e.g., CI-CD.md -> CI-CD/)
            guide_name = doc_file.stem
            guide_target = target_dir / guide_name
            guide_target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(doc_file, guide_target / "index.md")
            logger.info(MESSAGES.INFO_WIKI_COLLECTED_GUIDE.format(guide_name))

    def _collect_adr_documentation(self) -> None:
        """Collect Architecture Decision Records."""
        adr_dir = self.project_root / "docs" / "adr"
        target_dir = self.wiki_docs_path / "guides" / "ADR"

        if not adr_dir.exists():
            logger.warning(MESSAGES.WARNING_ADR_DIR_NOT_FOUND)
            return

        target_dir.mkdir(parents=True, exist_ok=True)

        # Copy README.md as index.md
        adr_readme = adr_dir / "README.md"
        if adr_readme.exists():
            shutil.copy2(adr_readme, target_dir / "index.md")

        # Copy all ADR files
        for adr_file in sorted(adr_dir.glob("ADR-*.md")):
            shutil.copy2(adr_file, target_dir / adr_file.name)
            logger.info(MESSAGES.INFO_WIKI_COLLECTED_ADR.format(adr_file.name))

    def _copy_assets(self) -> None:
        """Copy asset files (images, media, etc.)."""
        source_assets = self.project_root / "apps" / "wiki" / "docs" / "assets"
        target_assets = self.wiki_docs_path / "assets"

        if source_assets.exists():
            shutil.copytree(source_assets, target_assets, dirs_exist_ok=True)
            logger.info(MESSAGES.INFO_WIKI_ASSETS_COPIED)

    def _collect_scripts_documentation(self) -> None:
        """Collect scripts documentation."""
        scripts_target = self.wiki_docs_path / "scripts"
        scripts_target.mkdir(parents=True, exist_ok=True)

        # Create index file documenting toolkit functionality
        index_content = """# Scripts Documentation

This section contains documentation for the toolkit's Python utilities that replace the legacy shell scripts.

The toolkit provides the following functionality:

## Credentials Management
- Generate secure passwords
- Update authentication credentials across all services
- Manage basic auth and hashed passwords

## Environment Management
- Backup and restore environment files
- Validate environment file syntax
- Initialize environment files from examples

## Template Processing
- Replace placeholders in configuration templates
- Process multiple templates in directories
- Validate template variables

## Wiki Generation
- Collect documentation from the monorepo
- Generate wiki sites with MkDocs
- Organize documentation by sections

## Configuration Generation
- Generate Ansible configurations
- Generate Traefik configurations
- Generate Terraform configurations

All functionality is implemented in pure Python with no shell script dependencies.
"""

        try:
            with open(scripts_target / "index.md", "w", encoding="utf-8") as f:
                f.write(index_content)
            logger.info(MESSAGES.INFO_WIKI_COLLECTED_SCRIPTS)
        except Exception as e:
            logger.error(f"Failed to create scripts documentation: {e}")


# Global instance
wiki_generator = WikiGenerator()
