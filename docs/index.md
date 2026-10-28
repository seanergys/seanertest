<!--
SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>

SPDX-License-Identifier: MIT
-->

# seanertest

Seanertest runs integration tests for SEANERGYS services on testbeds. It drives the complete run: it
collects the selected tests, builds the required software with seanerstack, obtains nodes from
seanerops, starts the services under test, and runs the tests against them.

The [Design](explanation/design.md) page describes the intended setup and the responsibilities of
seanertest, seanerops and seanerstack. Most of it is not yet implemented; the current implementation
is described in the repository README.
