# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

"""Run the build phase on its own, for example to fill a shared OCI cache.

    python -m seanertest.build --push oci://REGISTRY/PATH tests/*/fixture.yaml
    python -m seanertest.build --push oci://REGISTRY/PATH --compiler-only

It builds exactly what a test session would build, with the same image,
Spack, recipes, compiler and target, so that test sessions find matching
binaries in the cache.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from seanerstack.pins import BUILTIN_REPO_COMMIT

from seanertest.build.phase import BuildError, build_compiler, run_build_phase
from seanertest.config import ConfigError, find_config, load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m seanertest.build", description=__doc__.split("\n\n")[0])
    parser.add_argument("fixtures", nargs="*", type=Path, help="fixture.yaml files whose software is built")
    parser.add_argument(
        "--compiler-only",
        action="store_true",
        help="build only the compiler of config.yml, which takes the longest, and no environments",
    )
    parser.add_argument("--config", type=Path, help="config.yml (default: found upward from the first fixture)")
    parser.add_argument("--architecture", default="x86_64")
    parser.add_argument("--push", metavar="OCI_URL", help="push to this oci:// cache instead of the local cache")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path.home() / ".cache" / "seanertest",
        help="keeps downloaded sources, lock files and the local cache (default: %(default)s)",
    )
    parser.add_argument("--seanerstack-src", type=Path, help="seanerstack checkout to install in the build container")
    args = parser.parse_args(argv)

    if args.push is not None and not args.push.startswith("oci://"):
        parser.error("--push needs an oci:// URL")
    if args.compiler_only == bool(args.fixtures):
        parser.error("give either fixture files or --compiler-only")
    common = {
        "cache_dir": args.cache_dir.expanduser().resolve(),
        "cache_type": "oci" if args.push else "http",
        "oci_url": args.push,
        "seanerstack_src": args.seanerstack_src,
    }
    if args.compiler_only:
        try:
            config = load_config(args.config or find_config(Path.cwd()))
            build_compiler(
                config=config,
                architecture=config.architecture(args.architecture),
                spack_packages_commit=BUILTIN_REPO_COMMIT,
                upstream=config.upstream_caches,
                **common,
            )
        except (BuildError, ConfigError) as error:
            print(f"seanertest: {error}", file=sys.stderr)
            return 1
        print(f"seanertest: {config.compiler} is in the cache")
        return 0

    # The fixture parser imports seanerops, which only environment builds need.
    from seanertest.fixture import FixtureError, load_fixture

    try:
        config = load_config(args.config or find_config(args.fixtures[0].parent))
        architecture = config.architecture(args.architecture)
        environments = {
            fixture.software for fixture in map(load_fixture, args.fixtures) if fixture.software is not None
        }
        if not environments:
            print("seanertest: the fixtures contain no Spack environments", file=sys.stderr)
            return 0
        built = run_build_phase(
            environments,
            config=config,
            architecture=architecture,
            spack_packages_commit=BUILTIN_REPO_COMMIT,
            upstream=config.upstream_caches,
            **common,
        )
    except (BuildError, ConfigError, FixtureError) as error:
        print(f"seanertest: {error}", file=sys.stderr)
        return 1
    for environment in sorted(built.values(), key=lambda item: str(item.environment.source)):
        print(f"{environment.key}  {environment.environment.source}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
