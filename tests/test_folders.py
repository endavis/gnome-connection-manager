"""Tests for the folder tree, exercised directly rather than through app.py.

No `app_module` fixture, so nothing here runs against the `gi` stub in conftest.py.
"""

from __future__ import annotations

import configparser
import io

import pytest

from gnome_connection_manager.utils import folders
from gnome_connection_manager.utils.folders import (
    EMPTY_NAME,
    INTO_ITSELF,
    NAME_HAS_SEPARATOR,
    NAME_TAKEN,
    NO_SUCH_FOLDER,
    ROOT,
    Folder,
    FolderError,
    FolderTree,
)
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


def test_a_repeated_folder_id_never_reaches_the_tree():
    """#154 asked repair to reassign a repeated id. It cannot arise: the id is the section
    name, and configparser refuses a repeated section before load() sees either."""
    with pytest.raises(configparser.DuplicateSectionError):
        configparser.RawConfigParser().read_string("[folder a]\nname = x\n\n[folder a]\n")


def test_a_config_with_no_folder_sections_loads_an_empty_tree():
    loaded, fixes = FolderTree.load(configparser.RawConfigParser())

    assert loaded.folders == {}
    assert fixes == []


def test_bind_leaves_a_folder_standing_when_its_last_host_moves_out():
    """Folders are records now, not a side effect of some host's path."""
    tree = FolderTree()
    record = host("ops/old")
    tree.bind([record])

    record.folder = tree.ensure_path("ops/new")
    tree.bind([record])

    assert all_paths(tree) == ["ops", "ops/new", "ops/old"]


def named(order):
    return [child.name for child in order]


def filed(tree, path, *names, positions=()):
    """Hosts called `names` in the folder at `path`, with positions if given."""
    folder_id = tree.ensure_path(path)
    made = []
    for index, name in enumerate(names):
        record = Host(path, name)
        record.folder = folder_id
        record.position = positions[index] if positions else None
        made.append(record)
    return folder_id, made


def test_an_unarranged_folder_is_drawn_as_the_tree_always_drew_it():
    """Subfolders first, then hosts, each by name -- case-sensitively, as before."""
    tree = FolderTree()
    for path in ("ops/zeta", "ops/Beta", "home"):
        tree.ensure_path(path)
    ops, hosts = filed(tree, "ops", "web", "Admin")

    contents = tree.contents(hosts)

    assert named(contents[ops]) == ["Beta", "zeta", "Admin", "web"]
    assert named(contents[ROOT]) == ["home", "ops"]


def test_positions_order_hosts_and_folders_together():
    tree = FolderTree()
    ops, hosts = filed(tree, "ops", "web", "db", positions=(0, 2))
    tree.folders[tree.ensure_path("ops/prod")].position = 1

    assert named(tree.contents(hosts)[ops]) == ["web", "prod", "db"]


def test_anything_without_a_position_follows_the_arranged_ones_in_name_order():
    """A host added to an arranged folder lands at the end, not at its place by name."""
    tree = FolderTree()
    ops, hosts = filed(tree, "ops", "zeta", "web", "alpha", positions=(1, 0, None))
    tree.ensure_path("ops/new")

    assert named(tree.contents(hosts)[ops]) == ["web", "zeta", "new", "alpha"]


def test_contents_changes_no_position():
    tree = FolderTree()
    _ops, hosts = filed(tree, "ops", "b", "a", positions=(7, 9))

    tree.contents(hosts)

    assert [h.position for h in hosts] == [7, 9]


def test_number_keeps_positions_only_for_an_order_names_would_not_give():
    tree = FolderTree()
    _ops, (a, b) = filed(tree, "ops", "a", "b")

    folders.number([b, a])
    assert (a.position, b.position) == (1, 0)

    folders.number([a, b])
    assert (a.position, b.position) == (None, None)


def test_place_beside_a_sibling_reorders():
    tree = FolderTree()
    ops, (a, b, c) = filed(tree, "ops", "a", "b", "c")
    order = tree.contents([a, b, c])[ops]

    folders.place(order, c, a)
    assert named(tree.contents([a, b, c])[ops]) == ["c", "a", "b"]

    folders.place(tree.contents([a, b, c])[ops], c, b, after=True)
    assert named(tree.contents([a, b, c])[ops]) == ["a", "b", "c"]
    assert [h.position for h in (a, b, c)] == [None, None, None]


def test_place_brings_an_item_in_from_elsewhere_beside_a_sibling():
    tree = FolderTree()
    ops, (a, b) = filed(tree, "ops", "a", "b")
    _home, (z,) = filed(tree, "home", "z")
    order = tree.contents([a, b])[ops]

    z.folder = ops
    folders.place(order, z, b)

    assert named(tree.contents([a, b, z])[ops]) == ["a", "z", "b"]


def test_place_without_a_spot_keeps_a_folder_in_name_order():
    """Dropping on a folder is not arranging it."""
    tree = FolderTree()
    ops, (b, c) = filed(tree, "ops", "b", "c")
    _home, (a,) = filed(tree, "home", "a", positions=(4,))
    order = tree.contents([b, c])[ops]

    a.folder = ops
    folders.place(order, a)

    assert a.position is None
    assert named(tree.contents([a, b, c])[ops]) == ["a", "b", "c"]


def test_place_without_a_spot_goes_to_the_end_of_an_arranged_folder():
    tree = FolderTree()
    ops, (c, b) = filed(tree, "ops", "c", "b", positions=(0, 1))
    _home, (a,) = filed(tree, "home", "a")
    order = tree.contents([c, b])[ops]

    a.folder = ops
    folders.place(order, a)

    assert named(tree.contents([a, b, c])[ops]) == ["c", "b", "a"]


def test_move_forgets_a_position_among_old_siblings_and_keeps_one_it_did_not_leave():
    tree = FolderTree()
    prod = tree.ensure_path("ops/prod")
    home = tree.ensure_path("home")
    tree.folders[prod].position = 2

    tree.move(prod, tree.folders[prod].parent)
    assert tree.folders[prod].position == 2

    tree.move(prod, home)
    assert tree.folders[prod].position is None


def test_folder_positions_survive_save_and_load():
    tree = FolderTree()
    arranged_id = tree.ensure_path("ops")
    unarranged_id = tree.ensure_path("home")
    tree.folders[arranged_id].position = 5
    config = configparser.RawConfigParser()

    tree.save(config)
    loaded, _fixes = FolderTree.load(reread(config))

    assert loaded.folders[arranged_id].position == 5
    assert loaded.folders[unarranged_id].position is None
    assert not config.has_option(f"folder {unarranged_id}", "position")


@pytest.mark.parametrize(
    ("text", "position"),
    [("3", 3), (" 4 ", 4), ("0", 0), ("", None), ("x", None), ("2.5", None), (None, None)],
)
def test_parse_position(text, position):
    assert folders.parse_position(text) == position


def test_is_ancestor_and_subtree():
    tree = FolderTree()
    db = tree.ensure_path("ops/prod/db")
    prod = tree.folders[db].parent
    ops = tree.folders[prod].parent
    home = tree.ensure_path("home")

    assert tree.is_ancestor(ops, db)
    assert tree.is_ancestor(db, db)
    assert not tree.is_ancestor(db, ops)
    assert not tree.is_ancestor(home, db)
    assert tree.subtree(prod) == {prod, db}


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("   ", EMPTY_NAME),
        ("a/b", NAME_HAS_SEPARATOR),
        ("prod", NAME_TAKEN),
        (" prod ", NAME_TAKEN),
    ],
)
def test_check_name_refuses(name, reason):
    tree = FolderTree()
    tree.ensure_path("ops/prod")
    ops = tree.child_named(ROOT, "ops").id

    with pytest.raises(FolderError) as refused:
        tree.check_name(ops, name)

    assert refused.value.reason == reason


def test_add_creates_a_stripped_name_under_its_parent():
    tree = FolderTree()
    ops = tree.ensure_path("ops")

    folder = tree.add(ops, "  staging ")

    assert tree.path_for(folder.id) == "ops/staging"


def test_add_refuses_a_parent_that_does_not_exist():
    with pytest.raises(FolderError) as refused:
        FolderTree().add("nope", "x")

    assert refused.value.reason == NO_SUCH_FOLDER


def test_rename_may_keep_its_own_name_but_not_take_a_siblings():
    tree = FolderTree()
    prod = tree.ensure_path("ops/prod")
    tree.ensure_path("ops/staging")

    tree.rename(prod, "prod")
    with pytest.raises(FolderError) as refused:
        tree.rename(prod, "staging")

    assert refused.value.reason == NAME_TAKEN
    tree.rename(prod, "production")
    assert tree.path_for(prod) == "ops/production"


def test_move_refiles_a_folder_with_everything_below_it():
    tree = FolderTree()
    db = tree.ensure_path("ops/prod/db")
    prod = tree.folders[db].parent
    home = tree.ensure_path("home")

    tree.move(prod, home)

    assert tree.path_for(db) == "home/prod/db"


def test_move_to_the_top_level():
    tree = FolderTree()
    prod = tree.ensure_path("ops/prod")

    tree.move(prod, ROOT)

    assert tree.path_for(prod) == "prod"


@pytest.mark.parametrize("into", ["itself", "its child"])
def test_move_refuses_a_folder_into_itself_or_below_itself(into):
    tree = FolderTree()
    db = tree.ensure_path("ops/prod/db")
    prod = tree.folders[db].parent

    with pytest.raises(FolderError) as refused:
        tree.move(prod, prod if into == "itself" else db)

    assert refused.value.reason == INTO_ITSELF
    assert tree.path_for(db) == "ops/prod/db"


def test_move_refuses_a_name_already_taken_at_the_destination():
    tree = FolderTree()
    ops_prod = tree.ensure_path("ops/prod")
    home = tree.ensure_path("home")
    tree.ensure_path("home/prod")

    with pytest.raises(FolderError) as refused:
        tree.move(ops_prod, home)

    assert refused.value.reason == NAME_TAKEN


def test_move_does_not_demand_a_name_from_a_legacy_empty_folder():
    """``a//b`` left an empty-named folder; moving it must not fail on the name."""
    tree = FolderTree()
    b = tree.ensure_path("a//b")
    blank = tree.folders[b].parent
    home = tree.ensure_path("home")

    tree.move(blank, home)

    assert tree.path_for(b) == "home//b"


def test_check_move_changes_nothing():
    tree = FolderTree()
    prod = tree.ensure_path("ops/prod")
    home = tree.ensure_path("home")

    tree.check_move(prod, home)

    assert tree.path_for(prod) == "ops/prod"


def test_remove_takes_the_whole_subtree():
    tree = FolderTree()
    db = tree.ensure_path("ops/prod/db")
    prod = tree.folders[db].parent
    tree.ensure_path("ops/staging")

    removed = tree.remove(prod)

    assert removed == {prod, db}
    assert all_paths(tree) == ["ops", "ops/staging"]


def test_editing_an_unknown_folder_is_a_folder_error_not_a_key_error():
    tree = FolderTree()
    for edit in (
        lambda: tree.rename("nope", "x"),
        lambda: tree.move("nope", ROOT),
        lambda: tree.remove("nope"),
    ):
        with pytest.raises(FolderError):
            edit()
