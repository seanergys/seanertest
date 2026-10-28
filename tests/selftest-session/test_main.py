# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

from pathlib import Path

import pytest
import seanerops
from seanerops import NodeGroup

from seanertest.fixture import FixtureSpec
from seanertest.plugin import resolve_target
from seanertest.session import CLUSTER_ONLY, group_key, group_request, kubernetes_name, resolve_cache_dir

ROOT = Path(__file__).resolve().parents[2]


def fixture(*groups, mode=None):
    return FixtureSpec(path=Path("f"), groups=tuple(NodeGroup(*g) for g in groups), mode=mode, software=None, services=())


@pytest.fixture
def laptop():
    return seanerops.load_target(ROOT / "targets" / "laptop.yml")


def test_groups_follow_the_effective_mode(laptop):
    assert group_key(laptop, fixture(("compute", 2))) == "shared"
    assert group_key(laptop, fixture(("compute", 2), mode="exclusive")) == "exclusive"
    assert group_key(laptop, fixture()) == CLUSTER_ONLY


def test_group_request_merges_with_the_mode_made_explicit(laptop):
    request = group_request(laptop, [fixture(("login", 1), ("compute", 2)), fixture(("compute", 4), mode="shared")])
    assert request.groups == (NodeGroup("login", 1), NodeGroup("compute", 4))
    assert request.mode == "shared"


def test_kubernetes_names_are_dns_labels():
    assert kubernetes_name("seanergys.flux") == "seanergys-flux"
    assert kubernetes_name("test-if-we-can-submit-2-jobs") == "test-if-we-can-submit-2-jobs"
    assert kubernetes_name("3rd") == "s-3rd"


def test_missing_cache_dir_falls_back_to_a_temporary_directory(monkeypatch):
    monkeypatch.delenv("SEANERTEST_CACHE_DIR", raising=False)
    messages = []
    path, temporary = resolve_cache_dir(None, messages.append)
    assert temporary and path.is_dir()
    assert "will not be reused" in messages[0]
    path.rmdir()


def test_cache_dir_option_is_kept(tmp_path):
    path, temporary = resolve_cache_dir(str(tmp_path / "cache"), print)
    assert path == tmp_path / "cache" and not temporary


def test_targets_resolve_by_name_or_path():
    assert resolve_target("laptop", ROOT / "tests") == ROOT / "targets" / "laptop.yml"
    assert resolve_target(str(ROOT / "targets" / "deep.yml"), ROOT) == ROOT / "targets" / "deep.yml"
    with pytest.raises(pytest.UsageError):
        resolve_target("absent", ROOT)
