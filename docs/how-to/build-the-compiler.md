<!--
SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>

SPDX-License-Identifier: MIT
-->

# Build the compiler

Bootstrapping the compiler, `gcc@15`, takes hours, while the environments of the tests build in
minutes once the compiler is available. The compiler is therefore built once, on a strong machine,
and shared through the seanerstack build cache in the SEANERGYS registry. Test sessions install it
from there. Build it again when `config.yml` changes the compiler, the Spack version or the image,
or when seanerstack pins another `spack-packages` commit.

The machine needs Docker, uv and Git.

1. Log in with an account that may write to the registry:

    ```bash
    docker login registry.seanergys.fz-juelich.de
    ```

2. Build the compiler and push it:

    ```bash
    scripts/build-compiler.sh
    ```

    The script uses the seanerstack checkout next to the seanertest checkout, or clones seanerstack
    when there is none. `SEANERSTACK_SRC` selects another checkout, which must pin the same
    `spack-packages` commit as the seanerstack that test sessions use.

3. Check that a test session installs the compiler instead of building it. Run a test with a new
   cache directory; the build log shows that `gcc` is fetched from the build cache:

    ```bash
    uv run pytest -v -s --target local --cache-dir "$(mktemp -d)" tests/003-spack-package-is-available
    ```

The script runs `python -m seanertest.build --compiler-only`, which runs the build script of a
session without environments. The compiler therefore gets the same hash as in every test session.
