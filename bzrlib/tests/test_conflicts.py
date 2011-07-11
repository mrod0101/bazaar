# Copyright (C) 2005-2011 Canonical Ltd
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

from bzrlib import (
    bzrdir,
    conflicts,
    errors,
    option,
    osutils,
    tests,
    )
from bzrlib.tests import (
    script,
    scenarios,
    )


load_tests = scenarios.load_tests_apply_scenarios


# TODO: Test commit with some added, and added-but-missing files
# RBC 20060124 is that not tested in test_commit.py ?

# The order of 'path' here is important - do not let it
# be a sorted list.
# u'\xe5' == a with circle
# '\xc3\xae' == u'\xee' == i with hat
# So these are u'path' and 'id' only with a circle and a hat. (shappo?)
example_conflicts = conflicts.ConflictList(
    [conflicts.MissingParent('Not deleting', u'p\xe5thg', '\xc3\xaedg'),
     conflicts.ContentsConflict(u'p\xe5tha', None, '\xc3\xaeda'),
     conflicts.TextConflict(u'p\xe5tha'),
     conflicts.PathConflict(u'p\xe5thb', u'p\xe5thc', '\xc3\xaedb'),
     conflicts.DuplicateID('Unversioned existing file',
                           u'p\xe5thc', u'p\xe5thc2',
                           '\xc3\xaedc', '\xc3\xaedc'),
    conflicts.DuplicateEntry('Moved existing file to',
                             u'p\xe5thdd.moved', u'p\xe5thd',
                             '\xc3\xaedd', None),
    conflicts.ParentLoop('Cancelled move', u'p\xe5the', u'p\xe5th2e',
                         None, '\xc3\xaed2e'),
    conflicts.UnversionedParent('Versioned directory',
                                u'p\xe5thf', '\xc3\xaedf'),
    conflicts.NonDirectoryParent('Created directory',
                                 u'p\xe5thg', '\xc3\xaedg'),
])


def vary_by_conflicts():
    for conflict in example_conflicts:
        yield (conflict.__class__.__name__, {"conflict": conflict})


class TestConflicts(tests.TestCaseWithTransport):

    def test_resolve_conflict_dir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree_contents([('hello', 'hello world4'),
                                  ('hello.THIS', 'hello world2'),
                                  ('hello.BASE', 'hello world1'),
                                  ])
        os.mkdir('hello.OTHER')
        tree.add('hello', 'q')
        l = conflicts.ConflictList([conflicts.TextConflict('hello')])
        l.remove_files(tree)

    def test_select_conflicts(self):
        tree = self.make_branch_and_tree('.')
        clist = conflicts.ConflictList

        def check_select(not_selected, selected, paths, **kwargs):
            self.assertEqual(
                (not_selected, selected),
                tree_conflicts.select_conflicts(tree, paths, **kwargs))

        foo = conflicts.ContentsConflict('foo')
        bar = conflicts.ContentsConflict('bar')
        tree_conflicts = clist([foo, bar])

        check_select(clist([bar]), clist([foo]), ['foo'])
        check_select(clist(), tree_conflicts,
                     [''], ignore_misses=True, recurse=True)

        foobaz  = conflicts.ContentsConflict('foo/baz')
        tree_conflicts = clist([foobaz, bar])

        check_select(clist([bar]), clist([foobaz]),
                     ['foo'], ignore_misses=True, recurse=True)

        qux = conflicts.PathConflict('qux', 'foo/baz')
        tree_conflicts = clist([qux])

        check_select(clist(), tree_conflicts,
                     ['foo'], ignore_misses=True, recurse=True)
        check_select (tree_conflicts, clist(), ['foo'], ignore_misses=True)

    def test_resolve_conflicts_recursive(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['dir/', 'dir/hello'])
        tree.add(['dir', 'dir/hello'])

        dirhello = conflicts.ConflictList([conflicts.TextConflict('dir/hello')])
        tree.set_conflicts(dirhello)

        conflicts.resolve(tree, ['dir'], recursive=False, ignore_misses=True)
        self.assertEqual(dirhello, tree.conflicts())

        conflicts.resolve(tree, ['dir'], recursive=True, ignore_misses=True)
        self.assertEqual(conflicts.ConflictList([]), tree.conflicts())


class TestPerConflict(tests.TestCase):

    scenarios = scenarios.multiply_scenarios(vary_by_conflicts())

    def test_stringification(self):
        text = unicode(self.conflict)
        self.assertContainsString(text, self.conflict.path)
        self.assertContainsString(text.lower(), "conflict")
        self.assertContainsString(repr(self.conflict),
            self.conflict.__class__.__name__)

    def test_stanza_roundtrip(self):
        p = self.conflict
        o = conflicts.Conflict.factory(**p.as_stanza().as_dict())
        self.assertEqual(o, p)

        self.assertIsInstance(o.path, unicode)

        if o.file_id is not None:
            self.assertIsInstance(o.file_id, str)

        conflict_path = getattr(o, 'conflict_path', None)
        if conflict_path is not None:
            self.assertIsInstance(conflict_path, unicode)

        conflict_file_id = getattr(o, 'conflict_file_id', None)
        if conflict_file_id is not None:
            self.assertIsInstance(conflict_file_id, str)

    def test_stanzification(self):
        stanza = self.conflict.as_stanza()
        if 'file_id' in stanza:
            # In Stanza form, the file_id has to be unicode.
            self.assertStartsWith(stanza['file_id'], u'\xeed')
        self.assertStartsWith(stanza['path'], u'p\xe5th')
        if 'conflict_path' in stanza:
            self.assertStartsWith(stanza['conflict_path'], u'p\xe5th')
        if 'conflict_file_id' in stanza:
            self.assertStartsWith(stanza['conflict_file_id'], u'\xeed')


class TestConflictList(tests.TestCase):

    def test_stanzas_roundtrip(self):
        stanzas_iter = example_conflicts.to_stanzas()
        processed = conflicts.ConflictList.from_stanzas(stanzas_iter)
        self.assertEqual(example_conflicts, processed)

    def test_stringification(self):
        for text, o in zip(example_conflicts.to_strings(), example_conflicts):
            self.assertEqual(text, unicode(o))


# FIXME: The shell-like tests should be converted to real whitebox tests... or
# moved to a blackbox module -- vila 20100205

# FIXME: test missing for multiple conflicts

# FIXME: Tests missing for DuplicateID conflict type
class TestResolveConflicts(script.TestCaseWithTransportAndScript):

    preamble = None # The setup script set by daughter classes

    def setUp(self):
        super(TestResolveConflicts, self).setUp()
        self.run_script(self.preamble)


def mirror_scenarios(base_scenarios):
    """Return a list of mirrored scenarios.

    Each scenario in base_scenarios is duplicated switching the roles of 'this'
    and 'other'
    """
    scenarios = []
    for common, (lname, ldict), (rname, rdict) in base_scenarios:
        a = tests.multiply_scenarios([(lname, dict(_this=ldict))],
                                     [(rname, dict(_other=rdict))])
        b = tests.multiply_scenarios([(rname, dict(_this=rdict))],
                                     [(lname, dict(_other=ldict))])
        # Inject the common parameters in all scenarios
        for name, d in a + b:
            d.update(common)
        scenarios.extend(a + b)
    return scenarios


# FIXME: Get rid of parametrized (in the class name) once we delete
# TestResolveConflicts -- vila 20100308
class TestParametrizedResolveConflicts(tests.TestCaseWithTransport):
    """This class provides a base to test single conflict resolution.

    Since all conflict objects are created with specific semantics for their
    attributes, each class should implement the necessary functions and
    attributes described below.

    Each class should define the scenarios that create the expected (single)
    conflict.

    Each scenario describes:
    * how to create 'base' tree (and revision)
    * how to create 'left' tree (and revision, parent rev 'base')
    * how to create 'right' tree (and revision, parent rev 'base')
    * how to check that changes in 'base'->'left' have been taken
    * how to check that changes in 'base'->'right' have been taken

    From each base scenario, we generate two concrete scenarios where:
    * this=left, other=right
    * this=right, other=left

    Then the test case verifies each concrete scenario by:
    * creating a branch containing the 'base', 'this' and 'other' revisions
    * creating a working tree for the 'this' revision
    * performing the merge of 'other' into 'this'
    * verifying the expected conflict was generated
    * resolving with --take-this or --take-other, and running the corresponding
      checks (for either 'base'->'this', or 'base'->'other')

    :cvar _conflict_type: The expected class of the generated conflict.

    :cvar _assert_conflict: A method receiving the working tree and the
        conflict object and checking its attributes.

    :cvar _base_actions: The branchbuilder actions to create the 'base'
        revision.

    :cvar _this: The dict related to 'base' -> 'this'. It contains at least:
      * 'actions': The branchbuilder actions to create the 'this'
          revision.
      * 'check': how to check the changes after resolution with --take-this.

    :cvar _other: The dict related to 'base' -> 'other'. It contains at least:
      * 'actions': The branchbuilder actions to create the 'other'
          revision.
      * 'check': how to check the changes after resolution with --take-other.
    """

    # Set by daughter classes
    _conflict_type = None
    _assert_conflict = None

    # Set by load_tests
    _base_actions = None
    _this = None
    _other = None

    scenarios = []
    """The scenario list for the conflict type defined by the class.

    Each scenario is of the form:
    (common, (left_name, left_dict), (right_name, right_dict))

    * common is a dict

    * left_name and right_name are the scenario names that will be combined

    * left_dict and right_dict are the attributes specific to each half of
      the scenario. They should include at least 'actions' and 'check' and
      will be available as '_this' and '_other' test instance attributes.

    Daughters classes are free to add their specific attributes as they see
    fit in any of the three dicts.

    This is a class method so that load_tests can find it.

    '_base_actions' in the common dict, 'actions' and 'check' in the left
    and right dicts use names that map to methods in the test classes. Some
    prefixes are added to these names to get the correspong methods (see
    _get_actions() and _get_check()). The motivation here is to avoid
    collisions in the class namespace.
    """

    def setUp(self):
        super(TestParametrizedResolveConflicts, self).setUp()
        builder = self.make_branch_builder('trunk')
        builder.start_series()

        # Create an empty trunk
        builder.build_snapshot('start', None, [
                ('add', ('', 'root-id', 'directory', ''))])
        # Add a minimal base content
        base_actions = self._get_actions(self._base_actions)()
        builder.build_snapshot('base', ['start'], base_actions)
        # Modify the base content in branch
        actions_other = self._get_actions(self._other['actions'])()
        builder.build_snapshot('other', ['base'], actions_other)
        # Modify the base content in trunk
        actions_this = self._get_actions(self._this['actions'])()
        builder.build_snapshot('this', ['base'], actions_this)
        # builder.get_branch() tip is now 'this'

        builder.finish_series()
        self.builder = builder

    def _get_actions(self, name):
        return getattr(self, 'do_%s' % name)

    def _get_check(self, name):
        return getattr(self, 'check_%s' % name)

    def _merge_other_into_this(self):
        b = self.builder.get_branch()
        wt = b.bzrdir.sprout('branch').open_workingtree()
        wt.merge_from_branch(b, 'other')
        return wt

    def assertConflict(self, wt):
        confs = wt.conflicts()
        self.assertLength(1, confs)
        c = confs[0]
        self.assertIsInstance(c, self._conflict_type)
        self._assert_conflict(wt, c)

    def _get_resolve_path_arg(self, wt, action):
        raise NotImplementedError(self._get_resolve_path_arg)

    def check_resolved(self, wt, action):
        path = self._get_resolve_path_arg(wt, action)
        conflicts.resolve(wt, [path], action=action)
        # Check that we don't have any conflicts nor unknown left
        self.assertLength(0, wt.conflicts())
        self.assertLength(0, list(wt.unknowns()))

    def test_resolve_taking_this(self):
        wt = self._merge_other_into_this()
        self.assertConflict(wt)
        self.check_resolved(wt, 'take_this')
        check_this = self._get_check(self._this['check'])
        check_this()

    def test_resolve_taking_other(self):
        wt = self._merge_other_into_this()
        self.assertConflict(wt)
        self.check_resolved(wt, 'take_other')
        check_other = self._get_check(self._other['check'])
        check_other()


class TestResolveTextConflicts(TestParametrizedResolveConflicts):

    _conflict_type = conflicts.TextConflict

    # Set by the scenarios
    # path and file-id for the file involved in the conflict
    _path = None
    _file_id = None

    scenarios = mirror_scenarios(
        [
            # File modified on both sides
            (dict(_base_actions='create_file',
                  _path='file', _file_id='file-id'),
             ('filed_modified_A',
              dict(actions='modify_file_A', check='file_has_content_A')),
             ('file_modified_B',
              dict(actions='modify_file_B', check='file_has_content_B')),),
            # File modified on both sides in dir
            (dict(_base_actions='create_file_in_dir',
                  _path='dir/file', _file_id='file-id'),
             ('filed_modified_A_in_dir',
              dict(actions='modify_file_A',
                   check='file_in_dir_has_content_A')),
             ('file_modified_B',
              dict(actions='modify_file_B',
                   check='file_in_dir_has_content_B')),),
            ])

    def do_create_file(self, path='file'):
        return [('add', (path, 'file-id', 'file', 'trunk content\n'))]

    def do_modify_file_A(self):
        return [('modify', ('file-id', 'trunk content\nfeature A\n'))]

    def do_modify_file_B(self):
        return [('modify', ('file-id', 'trunk content\nfeature B\n'))]

    def check_file_has_content_A(self, path='file'):
        self.assertFileEqual('trunk content\nfeature A\n',
                             osutils.pathjoin('branch', path))

    def check_file_has_content_B(self, path='file'):
        self.assertFileEqual('trunk content\nfeature B\n',
                             osutils.pathjoin('branch', path))

    def do_create_file_in_dir(self):
        return [('add', ('dir', 'dir-id', 'directory', '')),
            ] + self.do_create_file('dir/file')

    def check_file_in_dir_has_content_A(self):
        self.check_file_has_content_A('dir/file')

    def check_file_in_dir_has_content_B(self):
        self.check_file_has_content_B('dir/file')

    def _get_resolve_path_arg(self, wt, action):
        return self._path

    def assertTextConflict(self, wt, c):
        self.assertEqual(self._file_id, c.file_id)
        self.assertEqual(self._path, c.path)
    _assert_conflict = assertTextConflict


class TestResolveContentsConflict(TestParametrizedResolveConflicts):

    _conflict_type = conflicts.ContentsConflict

    # Set by the scenarios
    # path and file-id for the file involved in the conflict
    _path = None
    _file_id = None

    scenarios = mirror_scenarios(
        [
            # File modified/deleted
            (dict(_base_actions='create_file',
                  _path='file', _file_id='file-id'),
             ('file_modified',
              dict(actions='modify_file', check='file_has_more_content')),
             ('file_deleted',
              dict(actions='delete_file', check='file_doesnt_exist')),),
            # File renamed-modified/deleted
            (dict(_base_actions='create_file',
                  _path='new-file', _file_id='file-id'),
             ('file_renamed_and_modified',
              dict(actions='modify_and_rename_file',
                   check='file_renamed_and_more_content')),
             ('file_deleted',
              dict(actions='delete_file', check='file_doesnt_exist')),),
            # File modified/deleted in dir
            (dict(_base_actions='create_file_in_dir',
                  _path='dir/file', _file_id='file-id'),
             ('file_modified_in_dir',
              dict(actions='modify_file_in_dir',
                   check='file_in_dir_has_more_content')),
             ('file_deleted_in_dir',
              dict(actions='delete_file',
                   check='file_in_dir_doesnt_exist')),),
            ])

    def do_create_file(self):
        return [('add', ('file', 'file-id', 'file', 'trunk content\n'))]

    def do_modify_file(self):
        return [('modify', ('file-id', 'trunk content\nmore content\n'))]

    def do_modify_and_rename_file(self):
        return [('modify', ('file-id', 'trunk content\nmore content\n')),
                ('rename', ('file', 'new-file'))]

    def check_file_has_more_content(self):
        self.assertFileEqual('trunk content\nmore content\n', 'branch/file')

    def check_file_renamed_and_more_content(self):
        self.assertFileEqual('trunk content\nmore content\n', 'branch/new-file')

    def do_delete_file(self):
        return [('unversion', 'file-id')]

    def check_file_doesnt_exist(self):
        self.assertPathDoesNotExist('branch/file')

    def do_create_file_in_dir(self):
        return [('add', ('dir', 'dir-id', 'directory', '')),
                ('add', ('dir/file', 'file-id', 'file', 'trunk content\n'))]

    def do_modify_file_in_dir(self):
        return [('modify', ('file-id', 'trunk content\nmore content\n'))]

    def check_file_in_dir_has_more_content(self):
        self.assertFileEqual('trunk content\nmore content\n', 'branch/dir/file')

    def check_file_in_dir_doesnt_exist(self):
        self.assertPathDoesNotExist('branch/dir/file')

    def _get_resolve_path_arg(self, wt, action):
        return self._path

    def assertContentsConflict(self, wt, c):
        self.assertEqual(self._file_id, c.file_id)
        self.assertEqual(self._path, c.path)
    _assert_conflict = assertContentsConflict


class TestResolvePathConflict(TestParametrizedResolveConflicts):

    _conflict_type = conflicts.PathConflict

    def do_nothing(self):
        return []

    # Each side dict additionally defines:
    # - path path involved (can be '<deleted>')
    # - file-id involved
    scenarios = mirror_scenarios(
        [
            # File renamed/deleted
            (dict(_base_actions='create_file'),
             ('file_renamed',
              dict(actions='rename_file', check='file_renamed',
                   path='new-file', file_id='file-id')),
             ('file_deleted',
              dict(actions='delete_file', check='file_doesnt_exist',
                   # PathConflicts deletion handling requires a special
                   # hard-coded value
                   path='<deleted>', file_id='file-id')),),
            # File renamed/deleted in dir
            (dict(_base_actions='create_file_in_dir'),
             ('file_renamed_in_dir',
              dict(actions='rename_file_in_dir', check='file_in_dir_renamed',
                   path='dir/new-file', file_id='file-id')),
             ('file_deleted',
              dict(actions='delete_file', check='file_in_dir_doesnt_exist',
                   # PathConflicts deletion handling requires a special
                   # hard-coded value
                   path='<deleted>', file_id='file-id')),),
            # File renamed/renamed differently
            (dict(_base_actions='create_file'),
             ('file_renamed',
              dict(actions='rename_file', check='file_renamed',
                   path='new-file', file_id='file-id')),
             ('file_renamed2',
              dict(actions='rename_file2', check='file_renamed2',
                   path='new-file2', file_id='file-id')),),
            # Dir renamed/deleted
            (dict(_base_actions='create_dir'),
             ('dir_renamed',
              dict(actions='rename_dir', check='dir_renamed',
                   path='new-dir', file_id='dir-id')),
             ('dir_deleted',
              dict(actions='delete_dir', check='dir_doesnt_exist',
                   # PathConflicts deletion handling requires a special
                   # hard-coded value
                   path='<deleted>', file_id='dir-id')),),
            # Dir renamed/renamed differently
            (dict(_base_actions='create_dir'),
             ('dir_renamed',
              dict(actions='rename_dir', check='dir_renamed',
                   path='new-dir', file_id='dir-id')),
             ('dir_renamed2',
              dict(actions='rename_dir2', check='dir_renamed2',
                   path='new-dir2', file_id='dir-id')),),
            ])

    def do_create_file(self):
        return [('add', ('file', 'file-id', 'file', 'trunk content\n'))]

    def do_create_dir(self):
        return [('add', ('dir', 'dir-id', 'directory', ''))]

    def do_rename_file(self):
        return [('rename', ('file', 'new-file'))]

    def check_file_renamed(self):
        self.assertPathDoesNotExist('branch/file')
        self.assertPathExists('branch/new-file')

    def do_rename_file2(self):
        return [('rename', ('file', 'new-file2'))]

    def check_file_renamed2(self):
        self.assertPathDoesNotExist('branch/file')
        self.assertPathExists('branch/new-file2')

    def do_rename_dir(self):
        return [('rename', ('dir', 'new-dir'))]

    def check_dir_renamed(self):
        self.assertPathDoesNotExist('branch/dir')
        self.assertPathExists('branch/new-dir')

    def do_rename_dir2(self):
        return [('rename', ('dir', 'new-dir2'))]

    def check_dir_renamed2(self):
        self.assertPathDoesNotExist('branch/dir')
        self.assertPathExists('branch/new-dir2')

    def do_delete_file(self):
        return [('unversion', 'file-id')]

    def check_file_doesnt_exist(self):
        self.assertPathDoesNotExist('branch/file')

    def do_delete_dir(self):
        return [('unversion', 'dir-id')]

    def check_dir_doesnt_exist(self):
        self.assertPathDoesNotExist('branch/dir')

    def do_create_file_in_dir(self):
        return [('add', ('dir', 'dir-id', 'directory', '')),
                ('add', ('dir/file', 'file-id', 'file', 'trunk content\n'))]

    def do_rename_file_in_dir(self):
        return [('rename', ('dir/file', 'dir/new-file'))]

    def check_file_in_dir_renamed(self):
        self.assertPathDoesNotExist('branch/dir/file')
        self.assertPathExists('branch/dir/new-file')

    def check_file_in_dir_doesnt_exist(self):
        self.assertPathDoesNotExist('branch/dir/file')

    def _get_resolve_path_arg(self, wt, action):
        tpath = self._this['path']
        opath = self._other['path']
        if tpath == '<deleted>':
            path = opath
        else:
            path = tpath
        return path

    def assertPathConflict(self, wt, c):
        tpath = self._this['path']
        tfile_id = self._this['file_id']
        opath = self._other['path']
        ofile_id = self._other['file_id']
        self.assertEqual(tfile_id, ofile_id) # Sanity check
        self.assertEqual(tfile_id, c.file_id)
        self.assertEqual(tpath, c.path)
        self.assertEqual(opath, c.conflict_path)
    _assert_conflict = assertPathConflict


class TestResolvePathConflictBefore531967(TestResolvePathConflict):
    """Same as TestResolvePathConflict but a specific conflict object.
    """

    def assertPathConflict(self, c):
        # We create a conflict object as it was created before the fix and
        # inject it into the working tree, the test will exercise the
        # compatibility code.
        old_c = conflicts.PathConflict('<deleted>', self._item_path,
                                       file_id=None)
        wt.set_conflicts(conflicts.ConflictList([old_c]))


class TestResolveDuplicateEntry(TestParametrizedResolveConflicts):

    _conflict_type = conflicts.DuplicateEntry

    scenarios = mirror_scenarios(
        [
            # File created with different file-ids
            (dict(_base_actions='nothing'),
             ('filea_created',
              dict(actions='create_file_a', check='file_content_a',
                   path='file', file_id='file-a-id')),
             ('fileb_created',
              dict(actions='create_file_b', check='file_content_b',
                   path='file', file_id='file-b-id')),),
            ])

    def do_nothing(self):
        return []

    def do_create_file_a(self):
        return [('add', ('file', 'file-a-id', 'file', 'file a content\n'))]

    def check_file_content_a(self):
        self.assertFileEqual('file a content\n', 'branch/file')

    def do_create_file_b(self):
        return [('add', ('file', 'file-b-id', 'file', 'file b content\n'))]

    def check_file_content_b(self):
        self.assertFileEqual('file b content\n', 'branch/file')

    def _get_resolve_path_arg(self, wt, action):
        return self._this['path']

    def assertDuplicateEntry(self, wt, c):
        tpath = self._this['path']
        tfile_id = self._this['file_id']
        opath = self._other['path']
        ofile_id = self._other['file_id']
        self.assertEqual(tpath, opath) # Sanity check
        self.assertEqual(tfile_id, c.file_id)
        self.assertEqual(tpath + '.moved', c.path)
        self.assertEqual(tpath, c.conflict_path)
    _assert_conflict = assertDuplicateEntry


class TestResolveUnversionedParent(TestResolveConflicts):

    # FIXME: Add the reverse tests: dir deleted in trunk, file added in branch

    # FIXME: While this *creates* UnversionedParent conflicts, this really only
    # tests MissingParent resolution :-/
    preamble = """
$ bzr init trunk
...
$ cd trunk
$ mkdir dir
$ bzr add -q dir
$ bzr commit -m 'Create trunk' -q
$ echo 'trunk content' >dir/file
$ bzr add -q dir/file
$ bzr commit -q -m 'Add dir/file in trunk'
$ bzr branch -q . -r 1 ../branch
$ cd ../branch
$ bzr rm dir -q
$ bzr commit -q -m 'Remove dir in branch'
$ bzr merge ../trunk
2>+N  dir/
2>+N  dir/file
2>Conflict adding files to dir.  Created directory.
2>Conflict because dir is not versioned, but has versioned children.  Versioned directory.
2>2 conflicts encountered.
"""

    def test_take_this(self):
        self.run_script("""
$ bzr rm -q dir  --force
$ bzr resolve dir
2>2 conflict(s) resolved, 0 remaining
$ bzr commit -q --strict -m 'No more conflicts nor unknown files'
""")

    def test_take_other(self):
        self.run_script("""
$ bzr resolve dir
2>2 conflict(s) resolved, 0 remaining
$ bzr commit -q --strict -m 'No more conflicts nor unknown files'
""")


class TestResolveMissingParent(TestResolveConflicts):

    preamble = """
$ bzr init trunk
...
$ cd trunk
$ mkdir dir
$ echo 'trunk content' >dir/file
$ bzr add -q
$ bzr commit -m 'Create trunk' -q
$ echo 'trunk content' >dir/file2
$ bzr add -q dir/file2
$ bzr commit -q -m 'Add dir/file2 in branch'
$ bzr branch -q . -r 1 ../branch
$ cd ../branch
$ bzr rm -q dir/file --force
$ bzr rm -q dir
$ bzr commit -q -m 'Remove dir/file'
$ bzr merge ../trunk
2>+N  dir/
2>+N  dir/file2
2>Conflict adding files to dir.  Created directory.
2>Conflict because dir is not versioned, but has versioned children.  Versioned directory.
2>2 conflicts encountered.
"""

    def test_keep_them_all(self):
        self.run_script("""
$ bzr resolve dir
2>2 conflict(s) resolved, 0 remaining
$ bzr commit -q --strict -m 'No more conflicts nor unknown files'
""")

    def test_adopt_child(self):
        self.run_script("""
$ bzr mv -q dir/file2 file2
$ bzr rm -q dir --force
$ bzr resolve dir
2>2 conflict(s) resolved, 0 remaining
$ bzr commit -q --strict -m 'No more conflicts nor unknown files'
""")

    def test_kill_them_all(self):
        self.run_script("""
$ bzr rm -q dir --force
$ bzr resolve dir
2>2 conflict(s) resolved, 0 remaining
$ bzr commit -q --strict -m 'No more conflicts nor unknown files'
""")

    def test_resolve_taking_this(self):
        self.run_script("""
$ bzr resolve --take-this dir
2>...
$ bzr commit -q --strict -m 'No more conflicts nor unknown files'
""")

    def test_resolve_taking_other(self):
        self.run_script("""
$ bzr resolve --take-other dir
2>...
$ bzr commit -q --strict -m 'No more conflicts nor unknown files'
""")


class TestResolveDeletingParent(TestResolveConflicts):

    preamble = """
$ bzr init trunk
...
$ cd trunk
$ mkdir dir
$ echo 'trunk content' >dir/file
$ bzr add -q
$ bzr commit -m 'Create trunk' -q
$ bzr rm -q dir/file --force
$ bzr rm -q dir --force
$ bzr commit -q -m 'Remove dir/file'
$ bzr branch -q . -r 1 ../branch
$ cd ../branch
$ echo 'branch content' >dir/file2
$ bzr add -q dir/file2
$ bzr commit -q -m 'Add dir/file2 in branch'
$ bzr merge ../trunk
2>-D  dir/file
2>Conflict: can't delete dir because it is not empty.  Not deleting.
2>Conflict because dir is not versioned, but has versioned children.  Versioned directory.
2>2 conflicts encountered.
"""

    def test_keep_them_all(self):
        self.run_script("""
$ bzr resolve dir
2>2 conflict(s) resolved, 0 remaining
$ bzr commit -q --strict -m 'No more conflicts nor unknown files'
""")

    def test_adopt_child(self):
        self.run_script("""
$ bzr mv -q dir/file2 file2
$ bzr rm -q dir --force
$ bzr resolve dir
2>2 conflict(s) resolved, 0 remaining
$ bzr commit -q --strict -m 'No more conflicts nor unknown files'
""")

    def test_kill_them_all(self):
        self.run_script("""
$ bzr rm -q dir --force
$ bzr resolve dir
2>2 conflict(s) resolved, 0 remaining
$ bzr commit -q --strict -m 'No more conflicts nor unknown files'
""")

    def test_resolve_taking_this(self):
        self.run_script("""
$ bzr resolve --take-this dir
2>2 conflict(s) resolved, 0 remaining
$ bzr commit -q --strict -m 'No more conflicts nor unknown files'
""")

    def test_resolve_taking_other(self):
        self.run_script("""
$ bzr resolve --take-other dir
2>deleted dir/file2
2>deleted dir
2>2 conflict(s) resolved, 0 remaining
$ bzr commit -q --strict -m 'No more conflicts nor unknown files'
""")


class TestResolveParentLoop(TestParametrizedResolveConflicts):

    _conflict_type = conflicts.ParentLoop

    _this_args = None
    _other_args = None

    # Each side dict additionally defines:
    # - dir_id: the directory being moved
    # - target_id: The target directory
    # - xfail: whether the test is expected to fail if the action is
    #   involved as 'other'
    scenarios = mirror_scenarios(
        [
            # Dirs moved into each other
            (dict(_base_actions='create_dir1_dir2'),
             ('dir1_into_dir2',
              dict(actions='move_dir1_into_dir2', check='dir1_moved',
                   dir_id='dir1-id', target_id='dir2-id', xfail=False)),
             ('dir2_into_dir1',
              dict(actions='move_dir2_into_dir1', check='dir2_moved',
                   dir_id='dir2-id', target_id='dir1-id', xfail=False))),
            # Subdirs moved into each other
            (dict(_base_actions='create_dir1_4'),
             ('dir1_into_dir4',
              dict(actions='move_dir1_into_dir4', check='dir1_2_moved',
                   dir_id='dir1-id', target_id='dir4-id', xfail=True)),
             ('dir3_into_dir2',
              dict(actions='move_dir3_into_dir2', check='dir3_4_moved',
                   dir_id='dir3-id', target_id='dir2-id', xfail=True))),
            ])

    def do_create_dir1_dir2(self):
        return [('add', ('dir1', 'dir1-id', 'directory', '')),
                ('add', ('dir2', 'dir2-id', 'directory', '')),]

    def do_move_dir1_into_dir2(self):
        return [('rename', ('dir1', 'dir2/dir1'))]

    def check_dir1_moved(self):
        self.assertPathDoesNotExist('branch/dir1')
        self.assertPathExists('branch/dir2/dir1')

    def do_move_dir2_into_dir1(self):
        return [('rename', ('dir2', 'dir1/dir2'))]

    def check_dir2_moved(self):
        self.assertPathDoesNotExist('branch/dir2')
        self.assertPathExists('branch/dir1/dir2')

    def do_create_dir1_4(self):
        return [('add', ('dir1', 'dir1-id', 'directory', '')),
                ('add', ('dir1/dir2', 'dir2-id', 'directory', '')),
                ('add', ('dir3', 'dir3-id', 'directory', '')),
                ('add', ('dir3/dir4', 'dir4-id', 'directory', '')),]

    def do_move_dir1_into_dir4(self):
        return [('rename', ('dir1', 'dir3/dir4/dir1'))]

    def check_dir1_2_moved(self):
        self.assertPathDoesNotExist('branch/dir1')
        self.assertPathExists('branch/dir3/dir4/dir1')
        self.assertPathExists('branch/dir3/dir4/dir1/dir2')

    def do_move_dir3_into_dir2(self):
        return [('rename', ('dir3', 'dir1/dir2/dir3'))]

    def check_dir3_4_moved(self):
        self.assertPathDoesNotExist('branch/dir3')
        self.assertPathExists('branch/dir1/dir2/dir3')
        self.assertPathExists('branch/dir1/dir2/dir3/dir4')

    def _get_resolve_path_arg(self, wt, action):
        # ParentLoop says: moving <conflict_path> into <path>. Cancelled move.
        # But since <path> doesn't exist in the working tree, we need to use
        # <conflict_path> instead, and that, in turn, is given by dir_id. Pfew.
        return wt.id2path(self._other['dir_id'])

    def assertParentLoop(self, wt, c):
        self.assertEqual(self._other['dir_id'], c.file_id)
        self.assertEqual(self._other['target_id'], c.conflict_file_id)
        # The conflict paths are irrelevant (they are deterministic but not
        # worth checking since they don't provide the needed information
        # anyway)
        if self._other['xfail']:
            # It's a bit hackish to raise from here relying on being called for
            # both tests but this avoid overriding test_resolve_taking_other
            raise tests.KnownFailure(
                "ParentLoop doesn't carry enough info to resolve --take-other")
    _assert_conflict = assertParentLoop


class TestResolveNonDirectoryParent(TestResolveConflicts):

    preamble = """
$ bzr init trunk
...
$ cd trunk
$ bzr mkdir foo
...
$ bzr commit -m 'Create trunk' -q
$ echo "Boing" >foo/bar
$ bzr add -q foo/bar
$ bzr commit -q -m 'Add foo/bar'
$ bzr branch -q . -r 1 ../branch
$ cd ../branch
$ rm -r foo
$ echo "Boo!" >foo
$ bzr commit -q -m 'foo is now a file'
$ bzr merge ../trunk
2>+N  foo.new/bar
2>RK  foo => foo.new/
# FIXME: The message is misleading, foo.new *is* a directory when the message
# is displayed -- vila 090916
2>Conflict: foo.new is not a directory, but has files in it.  Created directory.
2>1 conflicts encountered.
"""

    def test_take_this(self):
        self.run_script("""
$ bzr rm -q foo.new --force
# FIXME: Isn't it weird that foo is now unkown even if foo.new has been put
# aside ? -- vila 090916
$ bzr add -q foo
$ bzr resolve foo.new
2>1 conflict(s) resolved, 0 remaining
$ bzr commit -q --strict -m 'No more conflicts nor unknown files'
""")

    def test_take_other(self):
        self.run_script("""
$ bzr rm -q foo --force
$ bzr mv -q foo.new foo
$ bzr resolve foo
2>1 conflict(s) resolved, 0 remaining
$ bzr commit -q --strict -m 'No more conflicts nor unknown files'
""")

    def test_resolve_taking_this(self):
        self.run_script("""
$ bzr resolve --take-this foo.new
2>...
$ bzr commit -q --strict -m 'No more conflicts nor unknown files'
""")

    def test_resolve_taking_other(self):
        self.run_script("""
$ bzr resolve --take-other foo.new
2>...
$ bzr commit -q --strict -m 'No more conflicts nor unknown files'
""")


class TestMalformedTransform(script.TestCaseWithTransportAndScript):

    def test_bug_430129(self):
        # This is nearly like TestResolveNonDirectoryParent but with branch and
        # trunk switched. As such it should certainly produce the same
        # conflict.
        self.run_script("""
$ bzr init trunk
...
$ cd trunk
$ bzr mkdir foo
...
$ bzr commit -m 'Create trunk' -q
$ rm -r foo
$ echo "Boo!" >foo
$ bzr commit -m 'foo is now a file' -q
$ bzr branch -q . -r 1 ../branch -q
$ cd ../branch
$ echo "Boing" >foo/bar
$ bzr add -q foo/bar -q
$ bzr commit -m 'Add foo/bar' -q
$ bzr merge ../trunk
2>bzr: ERROR: Tree transform is malformed [('unversioned executability', 'new-1')]
""")


class TestNoFinalPath(script.TestCaseWithTransportAndScript):

    def test_bug_805809(self):
        self.run_script("""
$ bzr init trunk
Created a standalone tree (format: 2a)
$ cd trunk
$ echo trunk >file
$ bzr add
adding file
$ bzr commit -m 'create file on trunk'
2>Committing to: .../trunk/
2>added file
2>Committed revision 1.
# Create a debian branch based on trunk
$ cd ..
$ bzr branch trunk -r 1 debian
2>Branched 1 revision(s).
$ cd debian
$ mkdir dir
$ bzr add
adding dir
$ bzr mv file dir
file => dir/file
$ bzr commit -m 'rename file to dir/file for debian'
2>Committing to: .../debian/
2>added dir
2>renamed file => dir/file
2>Committed revision 2.
# Create an experimental branch with a new root-id
$ cd ..
$ bzr init experimental
Created a standalone tree (format: 2a)
$ cd experimental
# Work around merging into empty branch not being supported
# (http://pad.lv/308562)
$ echo something >not-empty
$ bzr add
adding not-empty
$ bzr commit -m 'Add some content in experimental'
2>Committing to: .../experimental/
2>added not-empty
2>Committed revision 1.
# merge debian even without a common ancestor
$ bzr merge ../debian -r0..2
2>+N  dir/
2>+N  dir/file
2>All changes applied successfully.
$ bzr commit -m 'merging debian into experimental'
2>Committing to: .../experimental/
2>added dir
2>added dir/file
2>Committed revision 2.
# Create an ubuntu branch with yet another root-id
$ cd ..
$ bzr init ubuntu
Created a standalone tree (format: 2a)
$ cd ubuntu
# Work around merging into empty branch not being supported
# (http://pad.lv/308562)
$ echo something >not-empty-ubuntu
$ bzr add
adding not-empty-ubuntu
$ bzr commit -m 'Add some content in experimental'
2>Committing to: .../ubuntu/
2>added not-empty-ubuntu
2>Committed revision 1.
# Also merge debian
$ bzr merge ../debian -r0..2
2>+N  dir/
2>+N  dir/file
2>All changes applied successfully.
$ bzr commit -m 'merging debian'
2>Committing to: .../ubuntu/
2>added dir
2>added dir/file
2>Committed revision 2.
# Now try to merge experimental
$ bzr merge ../experimental
2>+N  not-empty
2>Path conflict: dir / dir
2>1 conflicts encountered.
""")


class TestResolveActionOption(tests.TestCase):

    def setUp(self):
        super(TestResolveActionOption, self).setUp()
        self.options = [conflicts.ResolveActionOption()]
        self.parser = option.get_optparser(dict((o.name, o)
                                                for o in self.options))

    def parse(self, args):
        return self.parser.parse_args(args)

    def test_unknown_action(self):
        self.assertRaises(errors.BadOptionValue,
                          self.parse, ['--action', 'take-me-to-the-moon'])

    def test_done(self):
        opts, args = self.parse(['--action', 'done'])
        self.assertEqual({'action':'done'}, opts)

    def test_take_this(self):
        opts, args = self.parse(['--action', 'take-this'])
        self.assertEqual({'action': 'take_this'}, opts)
        opts, args = self.parse(['--take-this'])
        self.assertEqual({'action': 'take_this'}, opts)

    def test_take_other(self):
        opts, args = self.parse(['--action', 'take-other'])
        self.assertEqual({'action': 'take_other'}, opts)
        opts, args = self.parse(['--take-other'])
        self.assertEqual({'action': 'take_other'}, opts)
