# Copyright (C) 2005-2012, 2016 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

import os
import sys

import bzrlib
from bzrlib import (
    controldir,
    errors,
    generate_ids,
    merge_directive,
    osutils,
    )
from bzrlib.conflicts import (
    ContentsConflict,
    TextConflict,
    PathConflict,
    )
from bzrlib.merge import (
    Merge3Merger,
    Diff3Merger,
    WeaveMerger,
    Merger,
    )
from bzrlib.osutils import getcwd, pathjoin
from bzrlib.transform import TreeTransform
from bzrlib.tests import TestCaseWithTransport, TestSkipped
from bzrlib.workingtree import WorkingTree


class MergeBuilder(object):

    def __init__(self, dir=None):
        self.dir = osutils.mkdtemp(prefix="merge-test", dir=dir)
        self.tree_root = generate_ids.gen_root_id()
        def wt(name):
           path = pathjoin(self.dir, name)
           os.mkdir(path)
           wt = controldir.ControlDir.create_standalone_workingtree(path)
           # the tests perform pulls, so need a branch that is writeable.
           wt.lock_write()
           wt.set_root_id(self.tree_root)
           wt.flush()
           tt = TreeTransform(wt)
           return wt, tt
        self.base, self.base_tt = wt('base')
        self.this, self.this_tt = wt('this')
        self.other, self.other_tt = wt('other')

    def get_cset_path(self, parent, name):
        if name is None:
            if parent is not None:
                raise AssertionError()
            return None
        return pathjoin(self.cset.entries[parent].path, name)

    def add_file(self, id, parent, name, contents, executable, this=True,
                 base=True, other=True):
        def new_file(tt):
            parent_id = tt.trans_id_file_id(parent)
            tt.new_file(name, parent_id, contents, id, executable)
        for option, tt in self.selected_transforms(this, base, other):
            if option is True:
                new_file(tt)

    def merge(self, merge_type=Merge3Merger, interesting_ids=None, **kwargs):
        merger = self.make_merger(merge_type, interesting_ids, **kwargs)
        merger.do_merge()
        return merger.cooked_conflicts

    def make_preview_transform(self):
        merger = self.make_merger(Merge3Merger, None, this_revision_tree=True)
        return merger.make_preview_transform()

    def make_merger(self, merge_type, interesting_ids,
            this_revision_tree=False, **kwargs):
        self.base_tt.apply()
        self.base.commit('base commit')
        for tt, wt in ((self.this_tt, self.this), (self.other_tt, self.other)):
            # why does this not do wt.pull() ?
            wt.branch.pull(self.base.branch)
            wt.set_parent_ids([wt.branch.last_revision()])
            wt.flush()
            # We maintain a write lock, so make sure changes are flushed to
            # disk first
            tt.apply()
            wt.commit('branch commit')
            wt.flush()
            if wt.branch.last_revision_info()[0] != 2:
                raise AssertionError()
        self.this.branch.fetch(self.other.branch)
        other_basis = self.other.branch.basis_tree()
        if this_revision_tree:
            self.this.commit('message')
            this_tree = self.this.basis_tree()
        else:
            this_tree = self.this
        merger = merge_type(this_tree, self.this, self.base, other_basis,
                            interesting_ids=interesting_ids, do_merge=False,
                            this_branch=self.this.branch, **kwargs)
        return merger

    def list_transforms(self):
        return [self.this_tt, self.base_tt, self.other_tt]

    def selected_transforms(self, this, base, other):
        pairs = [(this, self.this_tt), (base, self.base_tt),
                 (other, self.other_tt)]
        return [(v, tt) for (v, tt) in pairs if v is not None]

    def add_symlink(self, id, parent, name, contents):
        for tt in self.list_transforms():
            parent_id = tt.trans_id_file_id(parent)
            tt.new_symlink(name, parent_id, contents, id)

    def remove_file(self, file_id, base=False, this=False, other=False):
        for option, tt in self.selected_transforms(this, base, other):
            if option is True:
                trans_id = tt.trans_id_file_id(file_id)
                tt.cancel_creation(trans_id)
                tt.cancel_versioning(trans_id)
                tt.set_executability(None, trans_id)

    def add_dir(self, file_id, parent, name, this=True, base=True, other=True):
        for option, tt in self.selected_transforms(this, base, other):
            if option is True:
                parent_id = tt.trans_id_file_id(parent)
                tt.new_directory(name, parent_id, file_id)

    def change_name(self, id, base=None, this=None, other=None):
        for val, tt in ((base, self.base_tt), (this, self.this_tt),
                        (other, self.other_tt)):
            if val is None:
                continue
            trans_id = tt.trans_id_file_id(id)
            parent_id = tt.final_parent(trans_id)
            tt.adjust_path(val, parent_id, trans_id)

    def change_parent(self, file_id, base=None, this=None, other=None):
        for parent, tt in self.selected_transforms(this, base, other):
            trans_id  = tt.trans_id_file_id(file_id)
            parent_id = tt.trans_id_file_id(parent)
            tt.adjust_path(tt.final_name(trans_id), parent_id, trans_id)

    def change_contents(self, file_id, base=None, this=None, other=None):
        for contents, tt in self.selected_transforms(this, base, other):
            trans_id = tt.trans_id_file_id(file_id)
            tt.cancel_creation(trans_id)
            tt.create_file(contents, trans_id)

    def change_target(self, id, base=None, this=None, other=None):
        for target, tt in self.selected_transforms(this, base, other):
            trans_id = tt.trans_id_file_id(id)
            tt.cancel_creation(trans_id)
            tt.create_symlink(target, trans_id)

    def change_perms(self, id, base=None, this=None, other=None):
        for executability, tt in self.selected_transforms(this, base, other):
            trans_id = tt.trans_id_file_id(id)
            tt.set_executability(None, trans_id)
            tt.set_executability(executability, trans_id)

    def change_perms_tree(self, id, tree, mode):
        os.chmod(tree.full_path(id), mode)

    def apply_inv_change(self, inventory_change, orig_inventory):
        orig_inventory_by_path = {}
        for file_id, path in orig_inventory.iteritems():
            orig_inventory_by_path[path] = file_id

        def parent_id(file_id):
            try:
                parent_dir = os.path.dirname(orig_inventory[file_id])
            except:
                print file_id
                raise
            if parent_dir == "":
                return None
            return orig_inventory_by_path[parent_dir]

        def new_path(file_id):
            if fild_id in inventory_change:
                return inventory_change[file_id]
            else:
                parent = parent_id(file_id)
                if parent is None:
                    return orig_inventory[file_id]
                dirname = new_path(parent)
                return pathjoin(dirname, os.path.basename(orig_inventory[file_id]))

        new_inventory = {}
        for file_id in orig_inventory.iterkeys():
            path = new_path(file_id)
            if path is None:
                continue
            new_inventory[file_id] = path

        for file_id, path in inventory_change.iteritems():
            if file_id in orig_inventory:
                continue
            new_inventory[file_id] = path
        return new_inventory

    def unlock(self):
        self.base.unlock()
        self.this.unlock()
        self.other.unlock()

    def cleanup(self):
        self.unlock()
        osutils.rmtree(self.dir)


class MergeTest(TestCaseWithTransport):

    def test_change_name(self):
        """Test renames"""
        builder = MergeBuilder(getcwd())
        builder.add_file("1", builder.tree_root, "name1", "hello1", True)
        builder.change_name("1", other="name2")
        builder.add_file("2", builder.tree_root, "name3", "hello2", True)
        builder.change_name("2", base="name4")
        builder.add_file("3", builder.tree_root, "name5", "hello3", True)
        builder.change_name("3", this="name6")
        builder.merge()
        builder.cleanup()
        builder = MergeBuilder(getcwd())
        builder.add_file("1", builder.tree_root, "name1", "hello1", False)
        builder.change_name("1", other="name2", this="name3")
        conflicts = builder.merge()
        self.assertEqual(conflicts, [PathConflict('name3', 'name2', '1')])
        builder.cleanup()

    def test_merge_one(self):
        builder = MergeBuilder(getcwd())
        builder.add_file("1", builder.tree_root, "name1", "hello1", True)
        builder.change_contents("1", other="text4")
        builder.add_file("2", builder.tree_root, "name2", "hello1", True)
        builder.change_contents("2", other="text4")
        builder.merge(interesting_ids=["1"])
        self.assertEqual(builder.this.get_file("1").read(), "text4" )
        self.assertEqual(builder.this.get_file("2").read(), "hello1" )
        builder.cleanup()

    def test_file_moves(self):
        """Test moves"""
        builder = MergeBuilder(getcwd())
        builder.add_dir("1", builder.tree_root, "dir1")
        builder.add_dir("2", builder.tree_root, "dir2")
        builder.add_file("3", "1", "file1", "hello1", True)
        builder.add_file("4", "1", "file2", "hello2", True)
        builder.add_file("5", "1", "file3", "hello3", True)
        builder.change_parent("3", other="2")
        builder.change_parent("4", this="2")
        builder.change_parent("5", base="2")
        builder.merge()
        builder.cleanup()

        builder = MergeBuilder(getcwd())
        builder.add_dir("1", builder.tree_root, "dir1")
        builder.add_dir("2", builder.tree_root, "dir2")
        builder.add_dir("3", builder.tree_root, "dir3")
        builder.add_file("4", "1", "file1", "hello1", False)
        builder.change_parent("4", other="2", this="3")
        conflicts = builder.merge()
        path2 = pathjoin('dir2', 'file1')
        path3 = pathjoin('dir3', 'file1')
        self.assertEqual(conflicts, [PathConflict(path3, path2, '4')])
        builder.cleanup()

    def test_contents_merge(self):
        """Test merge3 merging"""
        self.do_contents_test(Merge3Merger)

    def test_contents_merge2(self):
        """Test diff3 merging"""
        if sys.platform == 'win32':
            raise TestSkipped("diff3 does not have --binary flag"
                              " and therefore always fails on win32")
        try:
            self.do_contents_test(Diff3Merger)
        except errors.NoDiff3:
            raise TestSkipped("diff3 not available")

    def test_contents_merge3(self):
        """Test diff3 merging"""
        self.do_contents_test(WeaveMerger)

    def test_reprocess_weave(self):
        # Reprocess works on weaves, and behaves as expected
        builder = MergeBuilder(getcwd())
        builder.add_file('a', builder.tree_root, 'blah', 'a', False)
        builder.change_contents('a', this='b\nc\nd\ne\n', other='z\nc\nd\ny\n')
        builder.merge(WeaveMerger, reprocess=True)
        expected = """<<<<<<< TREE
b
=======
z
>>>>>>> MERGE-SOURCE
c
d
<<<<<<< TREE
e
=======
y
>>>>>>> MERGE-SOURCE
"""
        self.assertEqualDiff(builder.this.get_file("a").read(), expected)
        builder.cleanup()

    def do_contents_test(self, merge_factory):
        """Test merging with specified ContentsChange factory"""
        builder = self.contents_test_success(merge_factory)
        builder.cleanup()
        self.contents_test_conflicts(merge_factory)

    def contents_test_success(self, merge_factory):
        builder = MergeBuilder(getcwd())
        builder.add_file("1", builder.tree_root, "name1", "text1", True)
        builder.change_contents("1", other="text4")
        builder.add_file("2", builder.tree_root, "name3", "text2", False)
        builder.change_contents("2", base="text5")
        builder.add_file("3", builder.tree_root, "name5", "text3", True)
        builder.add_file("4", builder.tree_root, "name6", "text4", True)
        builder.remove_file("4", base=True)
        builder.add_file("5", builder.tree_root, "name7", "a\nb\nc\nd\ne\nf\n",
                         True)
        builder.change_contents("5", other="a\nz\nc\nd\ne\nf\n",
                                     this="a\nb\nc\nd\ne\nz\n")
        conflicts = builder.merge(merge_factory)
        try:
            self.assertEqual([], conflicts)
            self.assertEqual("text4", builder.this.get_file("1").read())
            self.assertEqual("text2", builder.this.get_file("2").read())
            self.assertEqual("a\nz\nc\nd\ne\nz\n",
                             builder.this.get_file("5").read())
            self.assertTrue(builder.this.is_executable("1"))
            self.assertFalse(builder.this.is_executable("2"))
            self.assertTrue(builder.this.is_executable("3"))
        except:
            builder.unlock()
            raise
        return builder

    def contents_test_conflicts(self, merge_factory):
        builder = MergeBuilder(getcwd())
        builder.add_file("1", builder.tree_root, "name1", "text1", True)
        builder.change_contents("1", other="text4", this="text3")
        builder.add_file("2", builder.tree_root, "name2", "text1", True)
        builder.change_contents("2", other="\x00", this="text3")
        builder.add_file("3", builder.tree_root, "name3", "text5", False)
        builder.change_perms("3", this=True)
        builder.change_contents('3', this='moretext')
        builder.remove_file('3', other=True)
        conflicts = builder.merge(merge_factory)
        self.assertEqual(conflicts, [TextConflict('name1', file_id='1'),
                                     ContentsConflict('name2', file_id='2'),
                                     ContentsConflict('name3', file_id='3')])
        self.assertEqual(builder.this.get_file('2').read(), '\x00')
        builder.cleanup()

    def test_symlink_conflicts(self):
        if sys.platform != "win32":
            builder = MergeBuilder(getcwd())
            builder.add_symlink("2", builder.tree_root, "name2", "target1")
            builder.change_target("2", other="target4", base="text3")
            conflicts = builder.merge()
            self.assertEqual(conflicts, [ContentsConflict('name2',
                                                          file_id='2')])
            builder.cleanup()

    def test_symlink_merge(self):
        if sys.platform != "win32":
            builder = MergeBuilder(getcwd())
            builder.add_symlink("1", builder.tree_root, "name1", "target1")
            builder.add_symlink("2", builder.tree_root, "name2", "target1")
            builder.add_symlink("3", builder.tree_root, "name3", "target1")
            builder.change_target("1", this="target2")
            builder.change_target("2", base="target2")
            builder.change_target("3", other="target2")
            builder.merge()
            self.assertEqual(builder.this.get_symlink_target("1"), "target2")
            self.assertEqual(builder.this.get_symlink_target("2"), "target1")
            self.assertEqual(builder.this.get_symlink_target("3"), "target2")
            builder.cleanup()

    def test_no_passive_add(self):
        builder = MergeBuilder(getcwd())
        builder.add_file("1", builder.tree_root, "name1", "text1", True)
        builder.remove_file("1", this=True)
        builder.merge()
        builder.cleanup()

    def test_perms_merge(self):
        builder = MergeBuilder(getcwd())
        builder.add_file("1", builder.tree_root, "name1", "text1", True)
        builder.change_perms("1", other=False)
        builder.add_file("2", builder.tree_root, "name2", "text2", True)
        builder.change_perms("2", base=False)
        builder.add_file("3", builder.tree_root, "name3", "text3", True)
        builder.change_perms("3", this=False)
        builder.add_file('4', builder.tree_root, 'name4', 'text4', False)
        builder.change_perms('4', this=True)
        builder.remove_file('4', base=True)
        builder.merge()
        self.assertIs(builder.this.is_executable("1"), False)
        self.assertIs(builder.this.is_executable("2"), True)
        self.assertIs(builder.this.is_executable("3"), False)
        builder.cleanup();

    def test_new_suffix(self):
        builder = MergeBuilder(getcwd())
        builder.add_file("1", builder.tree_root, "name1", "text1", True)
        builder.change_contents("1", other="text3")
        builder.add_file("2", builder.tree_root, "name1.new", "text2", True)
        builder.merge()
        os.lstat(builder.this.id2abspath("2"))
        builder.cleanup()

    def test_spurious_conflict(self):
        builder = MergeBuilder(getcwd())
        builder.add_file("1", builder.tree_root, "name1", "text1", False)
        builder.remove_file("1", other=True)
        builder.add_file("2", builder.tree_root, "name1", "text1", False,
                         this=False, base=False)
        conflicts = builder.merge()
        self.assertEqual(conflicts, [])
        builder.cleanup()

    def test_merge_one_renamed(self):
        builder = MergeBuilder(getcwd())
        builder.add_file('1', builder.tree_root, 'name1', 'text1a', False)
        builder.change_name('1', this='name2')
        builder.change_contents('1', other='text2')
        builder.merge(interesting_files=['name2'])
        self.assertEqual('text2', builder.this.get_file('1').read())
        builder.cleanup()


class FunctionalMergeTest(TestCaseWithTransport):

    def test_trivial_star_merge(self):
        """Test that merges in a star shape Just Work."""
        # John starts a branch
        self.build_tree(("original/", "original/file1", "original/file2"))
        tree = self.make_branch_and_tree('original')
        branch = tree.branch
        tree.smart_add(["original"])
        tree.commit("start branch.", verbose=False)
        # Mary branches it.
        self.build_tree(("mary/",))
        branch.bzrdir.clone("mary")
        # Now John commits a change
        file = open("original/file1", "wt")
        file.write("John\n")
        file.close()
        tree.commit("change file1")
        # Mary does too
        mary_tree = WorkingTree.open('mary')
        mary_branch = mary_tree.branch
        file = open("mary/file2", "wt")
        file.write("Mary\n")
        file.close()
        mary_tree.commit("change file2")
        # john should be able to merge with no conflicts.
        base = [None, None]
        other = ("mary", -1)
        tree.merge_from_branch(mary_tree.branch)
        self.assertEqual("John\n", open("original/file1", "rt").read())
        self.assertEqual("Mary\n", open("original/file2", "rt").read())

    def test_conflicts(self):
        wta = self.make_branch_and_tree('a')
        self.build_tree_contents([('a/file', 'contents\n')])
        wta.add('file')
        wta.commit('base revision', allow_pointless=False)
        d_b = wta.branch.bzrdir.clone('b')
        self.build_tree_contents([('a/file', 'other contents\n')])
        wta.commit('other revision', allow_pointless=False)
        self.build_tree_contents([('b/file', 'this contents contents\n')])
        wtb = d_b.open_workingtree()
        wtb.commit('this revision', allow_pointless=False)
        self.assertEqual(1, wtb.merge_from_branch(wta.branch))
        self.assertPathExists('b/file.THIS')
        self.assertPathExists('b/file.BASE')
        self.assertPathExists('b/file.OTHER')
        wtb.revert()
        self.assertEqual(1, wtb.merge_from_branch(wta.branch,
                                                  merge_type=WeaveMerger))
        self.assertPathExists('b/file')
        self.assertPathExists('b/file.THIS')
        self.assertPathExists('b/file.BASE')
        self.assertPathExists('b/file.OTHER')

    def test_weave_conflicts_not_in_base(self):
        builder = self.make_branch_builder('source')
        builder.start_series()
        # See bug #494197
        #  A        base revision (before criss-cross)
        #  |\
        #  B C      B does nothing, C adds 'foo'
        #  |X|
        #  D E      D and E modify foo in incompatible ways
        #
        # Merging will conflict, with C as a clean base text. However, the
        # current code uses A as the global base and 'foo' doesn't exist there.
        # It isn't trivial to create foo.BASE because it tries to look up
        # attributes like 'executable' in A.
        builder.build_snapshot('A-id', None, [
            ('add', ('', 'TREE_ROOT', 'directory', None))])
        builder.build_snapshot('B-id', ['A-id'], [])
        builder.build_snapshot('C-id', ['A-id'], [
            ('add', ('foo', 'foo-id', 'file', 'orig\ncontents\n'))])
        builder.build_snapshot('D-id', ['B-id', 'C-id'], [
            ('add', ('foo', 'foo-id', 'file', 'orig\ncontents\nand D\n'))])
        builder.build_snapshot('E-id', ['C-id', 'B-id'], [
            ('modify', ('foo-id', 'orig\ncontents\nand E\n'))])
        builder.finish_series()
        tree = builder.get_branch().create_checkout('tree', lightweight=True)
        self.assertEqual(1, tree.merge_from_branch(tree.branch,
                                                   to_revision='D-id',
                                                   merge_type=WeaveMerger))
        self.assertPathExists('tree/foo.THIS')
        self.assertPathExists('tree/foo.OTHER')
        self.expectFailure('fail to create .BASE in some criss-cross merges',
            self.assertPathExists, 'tree/foo.BASE')
        self.assertPathExists('tree/foo.BASE')

    def test_merge_unrelated(self):
        """Sucessfully merges unrelated branches with no common names"""
        wta = self.make_branch_and_tree('a')
        a = wta.branch
        with file('a/a_file', 'wb') as f: f.write('contents\n')
        wta.add('a_file')
        wta.commit('a_revision', allow_pointless=False)
        wtb = self.make_branch_and_tree('b')
        b = wtb.branch
        with file('b/b_file', 'wb') as f: f.write('contents\n')
        wtb.add('b_file')
        b_rev = wtb.commit('b_revision', allow_pointless=False)
        wta.merge_from_branch(wtb.branch, b_rev, 'null:')
        self.assertTrue(os.path.lexists('a/b_file'))
        self.assertEqual([b_rev], wta.get_parent_ids()[1:])

    def test_merge_unrelated_conflicting(self):
        """Sucessfully merges unrelated branches with common names"""
        wta = self.make_branch_and_tree('a')
        a = wta.branch
        with file('a/file', 'wb') as f: f.write('contents\n')
        wta.add('file')
        wta.commit('a_revision', allow_pointless=False)
        wtb = self.make_branch_and_tree('b')
        b = wtb.branch
        with file('b/file', 'wb') as f: f.write('contents\n')
        wtb.add('file')
        b_rev = wtb.commit('b_revision', allow_pointless=False)
        wta.merge_from_branch(wtb.branch, b_rev, 'null:')
        self.assertTrue(os.path.lexists('a/file'))
        self.assertTrue(os.path.lexists('a/file.moved'))
        self.assertEqual([b_rev], wta.get_parent_ids()[1:])

    def test_merge_deleted_conflicts(self):
        wta = self.make_branch_and_tree('a')
        with file('a/file', 'wb') as f: f.write('contents\n')
        wta.add('file')
        wta.commit('a_revision', allow_pointless=False)
        self.run_bzr('branch a b')
        os.remove('a/file')
        wta.commit('removed file', allow_pointless=False)
        with file('b/file', 'wb') as f: f.write('changed contents\n')
        wtb = WorkingTree.open('b')
        wtb.commit('changed file', allow_pointless=False)
        wtb.merge_from_branch(wta.branch, wta.branch.last_revision(),
                              wta.branch.get_rev_id(1))
        self.assertFalse(os.path.lexists('b/file'))

    def test_merge_metadata_vs_deletion(self):
        """Conflict deletion vs metadata change"""
        a_wt = self.make_branch_and_tree('a')
        with file('a/file', 'wb') as f: f.write('contents\n')
        a_wt.add('file')
        a_wt.commit('r0')
        self.run_bzr('branch a b')
        b_wt = WorkingTree.open('b')
        os.chmod('b/file', 0755)
        os.remove('a/file')
        a_wt.commit('removed a')
        self.assertEqual(a_wt.branch.revno(), 2)
        self.assertFalse(os.path.exists('a/file'))
        b_wt.commit('exec a')
        a_wt.merge_from_branch(b_wt.branch, b_wt.last_revision(), 'null:')
        self.assertTrue(os.path.exists('a/file'))

    def test_merge_swapping_renames(self):
        a_wt = self.make_branch_and_tree('a')
        with file('a/un','wb') as f: f.write('UN')
        with file('a/deux','wb') as f: f.write('DEUX')
        a_wt.add('un', 'un-id')
        a_wt.add('deux', 'deux-id')
        a_wt.commit('r0', rev_id='r0')
        self.run_bzr('branch a b')
        b_wt = WorkingTree.open('b')
        b_wt.rename_one('un','tmp')
        b_wt.rename_one('deux','un')
        b_wt.rename_one('tmp','deux')
        b_wt.commit('r1', rev_id='r1')
        self.assertEqual(0, a_wt.merge_from_branch(b_wt.branch,
            b_wt.branch.last_revision(), b_wt.branch.get_rev_id(1)))
        self.assertPathExists('a/un')
        self.assertTrue('a/deux')
        self.assertFalse(os.path.exists('a/tmp'))
        self.assertEqual(file('a/un').read(),'DEUX')
        self.assertEqual(file('a/deux').read(),'UN')

    def test_merge_delete_and_add_same(self):
        a_wt = self.make_branch_and_tree('a')
        with file('a/file', 'wb') as f: f.write('THIS')
        a_wt.add('file')
        a_wt.commit('r0')
        self.run_bzr('branch a b')
        b_wt = WorkingTree.open('b')
        os.remove('b/file')
        b_wt.commit('r1')
        with file('b/file', 'wb') as f: f.write('THAT')
        b_wt.add('file')
        b_wt.commit('r2')
        a_wt.merge_from_branch(b_wt.branch, b_wt.branch.last_revision(),
                               b_wt.branch.get_rev_id(1))
        self.assertTrue(os.path.exists('a/file'))
        self.assertEqual(file('a/file').read(),'THAT')

    def test_merge_rename_before_create(self):
        """rename before create

        This case requires that you must not do creates
        before move-into-place:

        $ touch foo
        $ bzr add foo
        $ bzr commit
        $ bzr mv foo bar
        $ touch foo
        $ bzr add foo
        $ bzr commit
        """
        a_wt = self.make_branch_and_tree('a')
        with file('a/foo', 'wb') as f: f.write('A/FOO')
        a_wt.add('foo')
        a_wt.commit('added foo')
        self.run_bzr('branch a b')
        b_wt = WorkingTree.open('b')
        b_wt.rename_one('foo', 'bar')
        with file('b/foo', 'wb') as f: f.write('B/FOO')
        b_wt.add('foo')
        b_wt.commit('moved foo to bar, added new foo')
        a_wt.merge_from_branch(b_wt.branch, b_wt.branch.last_revision(),
                               b_wt.branch.get_rev_id(1))

    def test_merge_create_before_rename(self):
        """create before rename, target parents before children

        This case requires that you must not do move-into-place
        before creates, and that you must not do children after
        parents:

        $ touch foo
        $ bzr add foo
        $ bzr commit
        $ bzr mkdir bar
        $ bzr add bar
        $ bzr mv foo bar/foo
        $ bzr commit
        """
        os.mkdir('a')
        a_wt = self.make_branch_and_tree('a')
        with file('a/foo', 'wb') as f: f.write('A/FOO')
        a_wt.add('foo')
        a_wt.commit('added foo')
        self.run_bzr('branch a b')
        b_wt = WorkingTree.open('b')
        os.mkdir('b/bar')
        b_wt.add('bar')
        b_wt.rename_one('foo', 'bar/foo')
        b_wt.commit('created bar dir, moved foo into bar')
        a_wt.merge_from_branch(b_wt.branch, b_wt.branch.last_revision(),
                               b_wt.branch.get_rev_id(1))

    def test_merge_rename_to_temp_before_delete(self):
        """rename to temp before delete, source children before parents

        This case requires that you must not do deletes before
        move-out-of-the-way, and that you must not do children
        after parents:

        $ mkdir foo
        $ touch foo/bar
        $ bzr add foo/bar
        $ bzr commit
        $ bzr mv foo/bar bar
        $ rmdir foo
        $ bzr commit
        """
        a_wt = self.make_branch_and_tree('a')
        os.mkdir('a/foo')
        with file('a/foo/bar', 'wb') as f: f.write('A/FOO/BAR')
        a_wt.add('foo')
        a_wt.add('foo/bar')
        a_wt.commit('added foo/bar')
        self.run_bzr('branch a b')
        b_wt = WorkingTree.open('b')
        b_wt.rename_one('foo/bar', 'bar')
        os.rmdir('b/foo')
        b_wt.remove('foo')
        b_wt.commit('moved foo/bar to bar, deleted foo')
        a_wt.merge_from_branch(b_wt.branch, b_wt.branch.last_revision(),
                               b_wt.branch.get_rev_id(1))

    def test_merge_delete_before_rename_to_temp(self):
        """delete before rename to temp

        This case requires that you must not do
        move-out-of-the-way before deletes:

        $ touch foo
        $ touch bar
        $ bzr add foo bar
        $ bzr commit
        $ rm foo
        $ bzr rm foo
        $ bzr mv bar foo
        $ bzr commit
        """
        a_wt = self.make_branch_and_tree('a')
        with file('a/foo', 'wb') as f: f.write('A/FOO')
        with file('a/bar', 'wb') as f: f.write('A/BAR')
        a_wt.add('foo')
        a_wt.add('bar')
        a_wt.commit('added foo and bar')
        self.run_bzr('branch a b')
        b_wt = WorkingTree.open('b')
        os.unlink('b/foo')
        b_wt.remove('foo')
        b_wt.rename_one('bar', 'foo')
        b_wt.commit('deleted foo, renamed bar to foo')
        a_wt.merge_from_branch(b_wt.branch, b_wt.branch.last_revision(),
                               b_wt.branch.get_rev_id(1))


class TestMerger(TestCaseWithTransport):

    def set_up_trees(self):
        this = self.make_branch_and_tree('this')
        this.commit('rev1', rev_id='rev1')
        other = this.bzrdir.sprout('other').open_workingtree()
        this.commit('rev2a', rev_id='rev2a')
        other.commit('rev2b', rev_id='rev2b')
        return this, other

    def test_from_revision_ids(self):
        this, other = self.set_up_trees()
        self.assertRaises(errors.NoSuchRevision, Merger.from_revision_ids,
                          None, this, 'rev2b')
        this.lock_write()
        self.addCleanup(this.unlock)
        merger = Merger.from_revision_ids(None, this,
            'rev2b', other_branch=other.branch)
        self.assertEqual('rev2b', merger.other_rev_id)
        self.assertEqual('rev1', merger.base_rev_id)
        merger = Merger.from_revision_ids(None, this,
            'rev2b', 'rev2a', other_branch=other.branch)
        self.assertEqual('rev2a', merger.base_rev_id)

    def test_from_uncommitted(self):
        this, other = self.set_up_trees()
        merger = Merger.from_uncommitted(this, other, None)
        self.assertIs(other, merger.other_tree)
        self.assertIs(None, merger.other_rev_id)
        self.assertEqual('rev2b', merger.base_rev_id)

    def prepare_for_merging(self):
        this, other = self.set_up_trees()
        other.commit('rev3', rev_id='rev3')
        this.lock_write()
        self.addCleanup(this.unlock)
        return this, other

    def test_from_mergeable(self):
        this, other = self.prepare_for_merging()
        md = merge_directive.MergeDirective2.from_objects(
            other.branch.repository, 'rev3', 0, 0, 'this')
        other.lock_read()
        self.addCleanup(other.unlock)
        merger, verified = Merger.from_mergeable(this, md,
            None)
        md.patch = None
        merger, verified = Merger.from_mergeable(this, md,
            None)
        self.assertEqual('inapplicable', verified)
        self.assertEqual('rev3', merger.other_rev_id)
        self.assertEqual('rev1', merger.base_rev_id)
        md.base_revision_id = 'rev2b'
        merger, verified = Merger.from_mergeable(this, md,
            None)
        self.assertEqual('rev2b', merger.base_rev_id)

    def test_from_mergeable_old_merge_directive(self):
        this, other = self.prepare_for_merging()
        other.lock_write()
        self.addCleanup(other.unlock)
        md = merge_directive.MergeDirective.from_objects(
            other.branch.repository, 'rev3', 0, 0, 'this')
        merger, verified = Merger.from_mergeable(this, md,
            None)
        self.assertEqual('rev3', merger.other_rev_id)
        self.assertEqual('rev1', merger.base_rev_id)
