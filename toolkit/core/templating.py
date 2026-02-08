"""Jinja2 templating engine for configuration generation."""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, Template
from jinja2.exceptions import TemplateError, UndefinedError

from toolkit.core.logging import logger


class TemplateRenderer:
    """Jinja2 template renderer with strict undefined checking."""

    def __init__(self, template_dir: Path) -> None:
        """Initialize template renderer.

        Args:
            template_dir: Directory containing Jinja2 templates
        """
        self.template_dir = template_dir
        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )

    def render_template(
        self, template_name: str, output_path: Path, context: dict[str, Any]
    ) -> bool:
        """Render a Jinja2 template to an output file.

        Args:
            template_name: Name of the template file (e.g., 'traefik.yml.j2')
            output_path: Path where the rendered output will be written
            context: Dictionary of variables to pass to the template

        Returns:
            True if rendering was successful, False otherwise
        """
        try:
            # Load template
            template = self.env.get_template(template_name)

            # Render template with context
            rendered_content = template.render(**context)

            # Ensure output directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Write rendered content to output file
            output_path.write_text(rendered_content, encoding="utf-8")

            logger.debug(f"Rendered {template_name} -> {output_path}")
            return True

        except UndefinedError as e:
            logger.error(
                f"Template variable error in {template_name}: {e}\n"
                f"Please ensure all required variables are defined in the context."
            )
            return False

        except TemplateError as e:
            logger.error(f"Template error in {template_name}: {e}")
            return False

        except OSError as e:
            logger.error(f"File I/O error for {output_path}: {e}")
            return False

        except Exception as e:
            logger.error(f"Unexpected error rendering {template_name}: {e}")
            return False

    def render_string(
        self, template_string: str, context: dict[str, Any]
    ) -> str | None:
        """Render a template from a string.

        Args:
            template_string: Template content as string
            context: Dictionary of variables to pass to the template

        Returns:
            Rendered string if successful, None otherwise
        """
        try:
            template = Template(
                template_string,
                undefined=StrictUndefined,
                trim_blocks=True,
                lstrip_blocks=True,
            )
            return template.render(**context)

        except UndefinedError as e:
            logger.error(f"Template variable error: {e}")
            return None

        except TemplateError as e:
            logger.error(f"Template error: {e}")
            return None

        except Exception as e:
            logger.error(f"Unexpected error rendering template string: {e}")
            return None


def create_renderer(template_dir: Path) -> TemplateRenderer:
    """Factory function to create a template renderer.

    Args:
        template_dir: Directory containing Jinja2 templates

    Returns:
        Configured TemplateRenderer instance
    """
    if not template_dir.exists():
        logger.error(f"Template directory does not exist: {template_dir}")
        raise FileNotFoundError(f"Template directory not found: {template_dir}")

    if not template_dir.is_dir():
        logger.error(f"Template path is not a directory: {template_dir}")
        raise NotADirectoryError(f"Not a directory: {template_dir}")

    return TemplateRenderer(template_dir)
