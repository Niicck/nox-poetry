"""Poetry interface."""
import sys
from enum import Enum
from pathlib import Path
from typing import Any
from typing import Iterable
from typing import Iterator
from typing import List
from typing import Optional

import tomlkit
from nox.sessions import Session
from packaging.version import Version


if sys.version_info >= (3, 8):
    from importlib import metadata
else:
    import importlib_metadata as metadata


class IncompatiblePoetryVersionError(Exception):
    """Installed poetry version does not meet requirements."""


class CommandSkippedError(Exception):
    """The command was not executed by Nox."""


class DistributionFormat(str, Enum):
    """Type of distribution archive for a Python package."""

    WHEEL = "wheel"
    SDIST = "sdist"


class Config:
    """Poetry configuration."""

    """Minimum version of poetry that can support group dependencies"""
    MINIMUM_VERSION_SUPPORTING_GROUP_DEPS = Version("1.2.0")

    def __init__(self, project: Path) -> None:
        """Initialize."""
        path = project / "pyproject.toml"
        text = path.read_text(encoding="utf-8")
        data: Any = tomlkit.parse(text)
        self._config = data["tool"]["poetry"]

    @property
    def name(self) -> str:
        """Return the package name."""
        name = self._config["name"]
        assert isinstance(name, str)  # noqa: S101
        return name

    @property
    def extras(self) -> List[str]:
        """Return the package extras."""
        extras = self._config.get("extras", {})
        assert isinstance(extras, dict) and all(  # noqa: S101
            isinstance(extra, str) for extra in extras
        )
        return list(extras)

    @classmethod
    def version(cls) -> Version:
        """Current installed version of poetry."""
        return Version(metadata.version("poetry"))

    @classmethod
    def is_compatible_with_group_deps(cls) -> bool:
        """Test that installed version of poetry can support group dependencies."""
        return cls.version() >= cls.MINIMUM_VERSION_SUPPORTING_GROUP_DEPS


class Poetry:
    """Helper class for invoking Poetry inside a Nox session.

    Attributes:
        session: The Session object.
    """

    def __init__(self, session: Session) -> None:
        """Initialize."""
        self.session = session
        self._config: Optional[Config] = None

    @property
    def config(self) -> Config:
        """Return the package configuration."""
        if self._config is None:
            self._config = Config(Path.cwd())
        return self._config

    def export(
        self,
        groups: Optional[List[str]] = None,
    ) -> str:
        """Export the lock file to requirements format.

        Args:
            groups: optional list of poetry depedency groups to --only install.

        Returns:
            The generated requirements as text.

        Raises:
            CommandSkippedError: The command `poetry export` was not executed.
        """
        args = [
            "poetry",
            "export",
            "--format=requirements.txt",
            *[f"--extras={extra}" for extra in self.config.extras],
            "--without-hashes",
        ]

        if groups:
            args.extend(f"--only={group}" for group in groups)
        elif self.config.is_compatible_with_group_deps():
            args.append("--with=dev")
        else:
            args.append("--dev")

        output = self.session.run_always(
            *args,
            external=True,
            silent=True,
            stderr=None,
        )

        if output is None:
            raise CommandSkippedError(
                "The command `poetry export` was not executed"
                " (a possible cause is specifying `--no-install`)"
            )

        assert isinstance(output, str)  # noqa: S101

        def _stripwarnings(lines: Iterable[str]) -> Iterator[str]:
            for line in lines:
                if line.startswith("Warning:"):
                    print(line, file=sys.stderr)
                    continue
                yield line

        return "".join(_stripwarnings(output.splitlines(keepends=True)))

    def build(self, *, format: str) -> str:
        """Build the package.

        The filename of the archive is extracted from the output Poetry writes
        to standard output, which currently looks like this::

           Building foobar (0.1.0)
            - Building wheel
            - Built foobar-0.1.0-py3-none-any.whl

        This is brittle, but it has the advantage that it does not rely on
        assumptions such as having a clean ``dist`` directory, or
        reconstructing the filename from the package metadata. (Poetry does not
        use PEP 440 for version numbers, so this is non-trivial.)

        Args:
            format: The distribution format, either wheel or sdist.

        Returns:
            The basename of the wheel built by Poetry.

        Raises:
            CommandSkippedError: The command `poetry build` was not executed.
        """
        if not isinstance(format, DistributionFormat):
            format = DistributionFormat(format)

        output = self.session.run_always(
            "poetry",
            "build",
            f"--format={format.value}",
            "--no-ansi",
            external=True,
            silent=True,
            stderr=None,
        )

        if output is None:
            raise CommandSkippedError(
                "The command `poetry build` was not executed"
                " (a possible cause is specifying `--no-install`)"
            )

        assert isinstance(output, str)  # noqa: S101
        return output.split()[-1]
