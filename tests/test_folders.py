"""Tests for the folder tree, exercised directly rather than through app.py.

No `app_module` fixture, so nothing here runs against the `gi` stub in conftest.py.
"""

from __future__ import annotations

import configparser
import io

from gnome_connection_manager.utils import folders
from gnome_connection_manager.utils.folders import ROOT, Folder, FolderTree
from gnome_connection_manager.utils.hosts import Host


def reread(cp):
    """Serialize and parse back, the way writeConfig and loadConfig actually do it."""
    buf = io.StringIO()
    cp.write(buf)
    out = configparser.RawConfigParser()
    out.read_string(buf.getvalue())
    return out


def host(group, folder=""):
    """A real Host, not a stand-in: a fake with only these two attributes could drift."""
    record = Host(group, "name")
    record.folder = folder
    return record


def tree_of(*records):
    """A tree from (id, name, parent) triples, unrepaired."""
    tree = FolderTree()
    for folder_id, name, parent in records:
        tree.folders[folder_id] = Folder(folder_id, name, parent)
    return tree


def all_paths(tree):
    return sorted(tree.path_for(folder_id) for folder_id in tree.folders)


def test_module_imports_without_gtk():
    assert not hasattr(folders, "Gtk")
    assert not hasattr(folders, "conf")


def test_new_folder_id_is_hex_and_avoids_taken_ids(monkeypatch):
    minted = iter(["aaaaaaaa", "aaaaaaaa", "bbbbbbbb"])
    monkeypatch.setattr(folders.secrets, "token_hex", lambda _n: next(minted))

    assert folders.new_folder_id({"aaaaaaaa"}) == "bbbbbbbb"


def test_ensure_path_creates_each_level_once():
    tree = FolderTree()

    leaf = tree.ensure_path("Work/Servers/Linux")
    again = tree.ensure_path("Work/Servers/Linux")
    sibling = tree.ensure_path("Work/Desktops")

    assert leaf == again
    assert len(tree.folders) == 4
    assert tree.path_for(leaf) == "Work/Servers/Linux"
    assert tree.path_for(sibling) == "Work/Desktops"
    assert tree.folders[sibling].parent == tree.child_named(ROOT, "Work").id


def test_ensure_path_strips_each_segment():
    """configparser strips values on read, so an unstripped name would change on reload."""
    tree = FolderTree()

    leaf = tree.ensure_path("Work / Servers")

    assert tree.path_for(leaf) == "Work/Servers"


def test_ensure_path_keeps_empty_segments_as_the_tree_always_drew_them():
    tree = FolderTree()

    leaf = tree.ensure_path("a//b")

    assert tree.path_for(leaf) == "a//b"
    assert len(tree.folders) == 3


def test_path_for_an_unknown_id_is_empty():
    assert FolderTree().path_for("nope") == ""


def test_bind_resolves_a_host_that_has_no_folder_yet():
    """A record from before ADR-0002: the migration is this fallback."""
    tree = FolderTree()
    record = host("ops/prod")

    tree.bind([record])

    assert record.folder in tree.folders
    assert tree.path_for(record.folder) == "ops/prod"
    assert record.group == "ops/prod"


def test_bind_lets_a_resolving_folder_id_win_over_the_group_string():
    tree = FolderTree()
    prod = tree.ensure_path("ops/prod")
    record = host("stale/path", folder=prod)

    tree.bind([record])

    assert record.folder == prod
    assert record.group == "ops/prod"
    assert tree.child_named(ROOT, "stale") is None


def test_bind_falls_back_to_the_group_when_the_folder_id_names_nothing():
    tree = FolderTree()
    record = host("ops/prod", folder="gone1234")

    tree.bind([record])

    assert record.folder != "gone1234"
    assert tree.path_for(record.folder) == "ops/prod"


def test_bind_follows_a_rename_of_the_folder_record():
    """The point of ADR-0002: renaming is one record, and every host follows it."""
    tree = FolderTree()
    records = [host("ops/prod"), host("ops/prod/db"), host("ops")]
    tree.bind(records)

    tree.child_named(ROOT, "ops").name = "operations"
    tree.bind(records)

    assert [r.group for r in records] == ["operations/prod", "operations/prod/db", "operations"]


def test_bind_on_an_empty_tree_reproduces_every_group_path():
    """Migration must not move anything: the shape of a real config, depth four."""
    paths = ["Home", "Home/PVE", "Home/PVE/Nodes", "Home/PVE/Nodes/Lab", "Work", "Work/DC1"]
    records = [host(path) for path in paths]
    tree = FolderTree()

    tree.bind(records)

    assert [r.group for r in records] == paths
    assert all_paths(tree) == sorted(paths)


def test_prune_removes_folders_with_nothing_kept_below_them():
    tree = FolderTree()
    kept = tree.ensure_path("ops/prod/db")
    tree.ensure_path("ops/staging")
    tree.ensure_path("home")

    removed = tree.prune({kept})

    assert all_paths(tree) == ["ops", "ops/prod", "ops/prod/db"]
    assert len(removed) == 2


def test_prune_keeps_a_folder_that_holds_hosts_and_subfolders():
    tree = FolderTree()
    parent = tree.ensure_path("ops")
    child = tree.ensure_path("ops/prod")

    tree.prune({parent, child})

    assert all_paths(tree) == ["ops", "ops/prod"]


def test_repair_moves_a_folder_with_an_unknown_parent_to_the_top():
    tree = tree_of(("a", "orphan", "missing"))

    assert tree.repair() == ["unknown parent"]
    assert tree.folders["a"].parent == ROOT


def test_repair_breaks_a_folder_that_is_its_own_parent():
    tree = tree_of(("a", "loop", "a"))

    assert tree.repair() == ["cycle"]
    assert tree.folders["a"].parent == ROOT


def test_repair_cuts_a_cycle_where_it_closes_and_nowhere_else():
    """f -> a -> b -> a: only b's edge back to a goes; f keeps its real parent."""
    tree = tree_of(("f", "f", "a"), ("a", "a", "b"), ("b", "b", "a"))

    assert tree.repair() == ["cycle"]
    assert tree.folders["f"].parent == "a"
    assert tree.folders["a"].parent == "b"
    assert tree.folders["b"].parent == ROOT
    assert tree.path_for("f") == "b/a/f"


def test_repair_replaces_a_separator_inside_a_name():
    tree = tree_of(("a", "prod/eu", ROOT))

    assert tree.repair() == ["separator in name"]
    assert tree.folders["a"].name == "prod_eu"


def test_repair_merges_same_named_siblings_and_their_children():
    """Two `ops` at the top, each with a `prod`: one `ops`, one `prod` after."""
    tree = tree_of(
        ("o1", "ops", ROOT),
        ("p1", "prod", "o1"),
        ("o2", "ops", ROOT),
        ("p2", "prod", "o2"),
        ("d2", "db", "p2"),
    )

    fixes = tree.repair()

    assert fixes == ["duplicate sibling", "duplicate sibling"]
    assert set(tree.folders) == {"o1", "p1", "d2"}
    assert tree.path_for("d2") == "ops/prod/db"


def test_repair_leaves_every_path_distinct():
    """What host.group depends on, after the worst a hand edit can do."""
    tree = tree_of(
        ("a", "x/y", ROOT),
        ("b", "x", ROOT),
        ("c", "y", "b"),
        ("d", "x", "missing"),
        ("e", "e", "f"),
        ("f", "f", "e"),
    )

    tree.repair()

    paths = [tree.path_for(folder_id) for folder_id in tree.folders]
    assert len(paths) == len(set(paths))


def test_repair_of_a_healthy_tree_changes_nothing():
    tree = FolderTree()
    tree.ensure_path("ops/prod")
    before = {f.id: (f.name, f.parent) for f in tree.folders.values()}

    assert tree.repair() == []
    assert {f.id: (f.name, f.parent) for f in tree.folders.values()} == before


def test_save_and_load_round_trip():
    tree = FolderTree()
    leaf = tree.ensure_path("ops/prod")
    config = configparser.RawConfigParser()

    tree.save(config)
    loaded, fixes = FolderTree.load(reread(config))

    assert fixes == []
    assert set(loaded.folders) == set(tree.folders)
    assert loaded.path_for(leaf) == "ops/prod"
    assert config.has_section(f"folder {leaf}")


def test_load_ignores_other_sections_and_blank_ids():
    config = configparser.RawConfigParser()
    config.read_string("[host 1]\ngroup = ops\n\n[folder ]\nname = blank\n\n[folder ab12]\n")

    loaded, _fixes = FolderTree.load(config)

    assert set(loaded.folders) == {"ab12"}
    assert loaded.folders["ab12"].name == ""
    assert loaded.folders["ab12"].parent == ROOT


def test_load_repairs_what_it_reads():
    config = configparser.RawConfigParser()
    config.read_string("[folder a]\nname = orphan\nparent = missing\n")

    loaded, fixes = FolderTree.load(config)

    assert fixes == ["unknown parent"]
    assert loaded.folders["a"].parent == ROOT


def test_a_config_with_no_folder_sections_loads_an_empty_tree():
    loaded, fixes = FolderTree.load(configparser.RawConfigParser())

    assert loaded.folders == {}
    assert fixes == []
