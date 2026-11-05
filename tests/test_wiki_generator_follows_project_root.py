"""The wiki generator writes under the project root it holds at generate time (#3078).

`test_every_generator_renders.py` builds each generator, then points
`project_root` at a copy of the repo. The wiki generator had already derived its
output directory from the real root in `__init__`, so every run wrote
`apps/wiki/generated_docs` into the checkout: gitignored, so `git status` never
showed it, and the next run's coverage differed because `apps/` had grown a
directory.
"""

from pathlib import Path

from toolkit.config.constants import PATH_STRUCTURES
from toolkit.features.generator_wiki import WikiGenerator


def test_the_output_directory_follows_a_reassigned_project_root(tmp_path: Path) -> None:
    generator = WikiGenerator()
    generator.project_root = tmp_path
    assert generator.wiki_docs_path == tmp_path / PATH_STRUCTURES.WIKI_DOCS
