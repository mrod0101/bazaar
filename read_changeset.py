#!/usr/bin/env python
"""\
Read in a changeset output, and process it into a Changeset object.
"""

import bzrlib, bzrlib.changeset
import pprint
import common

class BadChangeset(Exception): pass
class MalformedHeader(BadChangeset): pass
class MalformedPatches(BadChangeset): pass
class MalformedFooter(BadChangeset): pass

def _unescape(name):
    """Now we want to find the filename effected.
    Unfortunately the filename is written out as
    repr(filename), which means that it surrounds
    the name with quotes which may be single or double
    (single is preferred unless there is a single quote in
    the filename). And some characters will be escaped.

    TODO:   There has to be some pythonic way of undo-ing the
            representation of a string rather than using eval.
    """
    delimiter = name[0]
    if name[-1] != delimiter:
        raise BadChangeset('Could not properly parse the'
                ' filename: %r' % name)
    # We need to handle escaped hexadecimals too.
    return name[1:-1].replace('\"', '"').replace("\'", "'")

class RevisionInfo(object):
    """Gets filled out for each revision object that is read.
    """
    def __init__(self, rev_id):
        self.rev_id = rev_id
        self.sha1 = None
        self.committer = None
        self.date = None
        self.timestamp = None
        self.timezone = None
        self.inventory_id = None
        self.inventory_sha1 = None

        self.parents = None
        self.message = None

    def __str__(self):
        return pprint.pformat(self.__dict__)

    def as_revision(self):
        from bzrlib.revision import Revision, RevisionReference
        rev = Revision(revision_id=self.rev_id,
            committer=self.committer,
            timestamp=float(self.timestamp),
            timezone=int(self.timezone),
            inventory_id=self.inventory_id,
            inventory_sha1=self.inventory_sha1,
            message='\n'.join(self.message))

        for parent in self.parents:
            rev_id, sha1 = parent.split('\t')
            rev.parents.append(RevisionReference(rev_id, sha1))

        return rev

class ChangesetInfo(object):
    """This is the intermediate class that gets filled out as
    the file is read.
    """
    def __init__(self):
        self.committer = None
        self.date = None
        self.message = None
        self.base = None
        self.base_sha1 = None

        # A list of RevisionInfo objects
        self.revisions = []
        # Tuples of (new_file_id, new_file_path)
        self.new_file_ids = []

        # This is a mapping from file_id to text_id
        self.text_ids = {}

        self.tree_root_id = None
        self.file_ids = None
        self.old_file_ids = None

        self.actions = [] #this is the list of things that happened

    def __str__(self):
        return pprint.pformat(self.__dict__)

    def complete_info(self):
        """This makes sure that all information is properly
        split up, based on the assumptions that can be made
        when information is missing.
        """
        if self.base is None:
            # When we don't have a base, then the real base
            # is the first parent of the last revision listed
            rev = self.revisions[-1]
            self.base = rev.parents[0].revision_id
            self.base_sha1 = rev.parents[0].revision_sha1

        for rev in self.revisions:
            pass

    def create_maps(self):
        """Go through the individual id sections, and generate the 
        id2path and path2id maps.
        """
        # Rather than use an empty path, the changeset code seems 
        # to like to use "./." for the tree root.
        self.id2path[self.tree_root_id] = './.'
        self.path2id['./.'] = self.tree_root_id
        self.id2parent[self.tree_root_id] = bzrlib.changeset.NULL_ID
        self.old_id2path = self.id2path.copy()
        self.old_path2id = self.path2id.copy()
        self.old_id2parent = self.id2parent.copy()

        if self.file_ids:
            for info in self.file_ids:
                path, f_id, parent_id = info.split('\t')
                self.id2path[f_id] = path
                self.path2id[path] = f_id
                self.id2parent[f_id] = parent_id
        if self.old_file_ids:
            for info in self.old_file_ids:
                path, f_id, parent_id = info.split('\t')
                self.old_id2path[f_id] = path
                self.old_path2id[path] = f_id
                self.old_id2parent[f_id] = parent_id

    def get_changeset(self):
        """Create a changeset from the data contained within."""
        from bzrlib.changeset import Changeset, ChangesetEntry, \
            PatchApply, ReplaceContents
        cset = Changeset()
        
        entry = ChangesetEntry(self.tree_root_id, 
                bzrlib.changeset.NULL_ID, './.')
        cset.add_entry(entry)
        for info, lines in self.actions:
            parts = info.split(' ')
            action = parts[0]
            kind = parts[1]
            extra = ' '.join(parts[2:])
            if action == 'renamed':
                old_path, new_path = extra.split(' => ')
                old_path = _unescape(old_path)
                new_path = _unescape(new_path)

                new_id = self.path2id[new_path]
                old_id = self.old_path2id[old_path]
                assert old_id == new_id

                new_parent = self.id2parent[new_id]
                old_parent = self.old_id2parent[old_id]

                entry = ChangesetEntry(old_id, old_parent, old_path)
                entry.new_path = new_path
                entry.new_parent = new_parent
                if lines:
                    entry.contents_change = PatchApply(''.join(lines))
            elif action == 'removed':
                old_path = _unescape(extra)
                old_id = self.old_path2id[old_path]
                old_parent = self.old_id2parent[old_id]
                entry = ChangesetEntry(old_id, old_parent, old_path)
                entry.new_path = None
                entry.new_parent = None
                if lines:
                    # Technically a removed should be a ReplaceContents()
                    # Where you need to have the old contents
                    # But at most we have a remove style patch.
                    #entry.contents_change = ReplaceContents()
                    pass
            elif action == 'added':
                new_path = _unescape(extra)
                new_id = self.path2id[new_path]
                new_parent = self.id2parent[new_id]
                entry = ChangesetEntry(new_id, new_parent, new_path)
                entry.path = None
                entry.parent = None
                if lines:
                    # Technically an added should be a ReplaceContents()
                    # Where you need to have the old contents
                    # But at most we have an add style patch.
                    #entry.contents_change = ReplaceContents()
                    entry.contents_change = PatchApply(''.join(lines))
            elif action == 'modified':
                new_path = _unescape(extra)
                new_id = self.path2id[new_path]
                new_parent = self.id2parent[new_id]
                entry = ChangesetEntry(new_id, new_parent, new_path)
                entry.path = None
                entry.parent = None
                if lines:
                    # Technically an added should be a ReplaceContents()
                    # Where you need to have the old contents
                    # But at most we have an add style patch.
                    #entry.contents_change = ReplaceContents()
                    entry.contents_change = PatchApply(''.join(lines))
            else:
                raise BadChangeset('Unrecognized action: %r' % action)
            cset.add_entry(entry)
        return cset

class ChangesetReader(object):
    """This class reads in a changeset from a file, and returns
    a Changeset object, which can then be applied against a tree.
    """
    def __init__(self, from_file):
        """Read in the changeset from the file.

        :param from_file: A file-like object (must have iterator support).
        """
        object.__init__(self)
        self.from_file = from_file
        self._next_line = None
        
        self.info = ChangesetInfo()
        # We put the actual inventory ids in the footer, so that the patch
        # is easier to read for humans.
        # Unfortunately, that means we need to read everything before we
        # can create a proper changeset.
        self._read_header()
        self._read_patches()
        self._read_footer()

    def _next(self):
        """yield the next line, but secretly
        keep 1 extra line for peeking.
        """
        for line in self.from_file:
            last = self._next_line
            self._next_line = line
            if last is not None:
                yield last

    def get_info(self):
        """Create the actual changeset object.
        """
        self.info.complete_info()
        return self.info

    def _read_header(self):
        """Read the bzr header"""
        header = common.get_header()
        found = False
        for line in self._next():
            if found:
                if (line[:2] != '# ' or line[-1:] != '\n'
                        or line[2:-1] != header[0]):
                    raise MalformedHeader('Found a header, but it'
                        ' was improperly formatted')
                header.pop(0) # We read this line.
                if not header:
                    break # We found everything.
            elif (line[:1] == '#' and line[-1:] == '\n'):
                line = line[1:-1].strip()
                if line[:len(common.header_str)] == common.header_str:
                    if line == header[0]:
                        found = True
                    else:
                        raise MalformedHeader('Found what looks like'
                                ' a header, but did not match')
                    header.pop(0)
        else:
            raise MalformedHeader('Did not find an opening header')

        for line in self._next():
            # The bzr header is terminated with a blank line
            # which does not start with '#'
            if line == '\n':
                break
            self._handle_next(line)

    def _read_next_entry(self, line, indent=1):
        """Read in a key-value pair
        """
        if line[:1] != '#':
            raise MalformedHeader('Bzr header did not start with #')
        line = line[1:-1] # Remove the '#' and '\n'
        if line[:indent] == ' '*indent:
            line = line[indent:]
        if not line:
            return None, None# Ignore blank lines

        loc = line.find(': ')
        if loc != -1:
            key = line[:loc]
            value = line[loc+2:]
            if not value:
                value = self._read_many(indent=indent+3)
        elif line[-1:] == ':':
            key = line[:-1]
            value = self._read_many(indent=indent+3)
        else:
            raise MalformedHeader('While looking for key: value pairs,'
                    ' did not find the colon %r' % (line))

        key = key.replace(' ', '_')
        return key, value

    def _handle_next(self, line):
        key, value = self._read_next_entry(line, indent=1)
        if key is None:
            return

        if key == 'revision':
            self._read_revision(value)
        elif hasattr(self.info, key):
            if getattr(self.info, key) is None:
                setattr(self.info, key, value)
            else:
                raise MalformedHeader('Duplicated Key: %s' % key)
        else:
            # What do we do with a key we don't recognize
            raise MalformedHeader('Unknown Key: %s' % key)
        
    def _read_many(self, indent):
        """If a line ends with no entry, that means that it should be
        followed with multiple lines of values.

        This detects the end of the list, because it will be a line that
        does not start properly indented.
        """
        values = []
        start = '#' + (' '*indent)

        if self._next_line[:len(start)] != start:
            return values

        for line in self._next():
            values.append(line[len(start):-1])
            if self._next_line[:len(start)] != start:
                break
        return values

    def _read_one_patch(self):
        """Read in one patch, return the complete patch, along with
        the next line.

        :return: action, lines, do_continue
        """
        # Peek and see if there are no patches
        if self._next_line[:1] == '#':
            return None, [], False

        line = self._next().next()
        if line[:3] != '***':
            raise MalformedPatches('The first line of all patches'
                ' should be a bzr meta line "***"')
        action = line[4:-1]

        lines = []
        for line in self._next():
            lines.append(line)

            if self._next_line[:3] == '***':
                return action, lines, True
            elif self._next_line[:1] == '#':
                return action, lines, False
        return action, lines, False
            
    def _read_patches(self):
        do_continue = True
        while do_continue:
            action, lines, do_continue = self._read_one_patch()
            if action is not None:
                self.info.actions.append((action, lines))

    def _read_revision(self, rev_id):
        """Revision entries have extra information associated.
        """
        rev_info = RevisionInfo(rev_id)
        start = '#    '
        for line in self._next():
            key,value = self._read_next_entry(line, indent=4)
            #if key is None:
            #    continue
            if hasattr(rev_info, key):
                if getattr(rev_info, key) is None:
                    setattr(rev_info, key, value)
                else:
                    raise MalformedHeader('Duplicated Key: %s' % key)
            else:
                # What do we do with a key we don't recognize
                raise MalformedHeader('Unknown Key: %s' % key)

            if self._next_line[:len(start)] != start:
                break

        self.info.revisions.append(rev_info)

    def _read_footer(self):
        """Read the rest of the meta information.

        :param first_line:  The previous step iterates past what it
                            can handle. That extra line is given here.
        """
        line = self._next().next()
        if line != '# BEGIN BZR FOOTER\n':
            raise MalformedFooter('Footer did not begin with BEGIN BZR FOOTER')

        for line in self._next():
            if line == '# END BZR FOOTER\n':
                return
            self._handle_next(line)

def read_changeset(from_file):
    """Read in a changeset from a filelike object (must have "readline" support), and
    parse it into a Changeset object.
    """
    cr = ChangesetReader(from_file)
    info = cr.get_info()
    return info


class ChangesetTree:
    def __init__(self, base_tree=None):
        self.base_tree = base_tree
        self._renamed = {}
        self._renamed_r = {}
        self._new_id = {}
        self._new_id_r = {}
        self.patches = {}
        self.deleted = []
        self.contents_by_id = True

    def note_rename(self, old_path, new_path):
        assert not self._renamed.has_key(old_path)
        assert not self._renamed_r.has_key(new_path)
        self._renamed[new_path] = old_path
        self._renamed_r[old_path] = new_path

    def note_id(self, new_id, new_path):
        self._new_id[new_path] = new_id
        self._new_id_r[new_id] = new_path

    def note_patch(self, new_path, patch):
        self.patches[new_path] = patch

    def note_deletion(self, old_path):
        self.deleted.append(old_path)

    def old_path(self, new_path):
        import os.path
        old_path = self._renamed.get(new_path)
        if old_path is not None:
            return old_path
        dirname,basename = os.path.split(new_path)
        if dirname is not '':
            old_dir = self.old_path(dirname)
            if old_dir is None:
                old_path = None
            else:
                old_path = os.path.join(old_dir, basename)
        else:
            old_path = new_path
        #If the new path wasn't in renamed, the old one shouldn't be in
        #renamed_r
        if self._renamed_r.has_key(old_path):
            return None
        return old_path 


    def new_path(self, old_path):
        import os.path
        new_path = self._renamed_r.get(old_path)
        if new_path is not None:
            return new_path
        if self._renamed.has_key(new_path):
            return None
        dirname,basename = os.path.split(old_path)
        if dirname is not '':
            new_dir = self.new_path(dirname)
            if new_dir is None:
                new_path = None
            else:
                new_path = os.path.join(new_dir, basename)
        else:
            new_path = old_path
        #If the old path wasn't in renamed, the new one shouldn't be in
        #renamed_r
        if self._renamed.has_key(new_path):
            return None
        return new_path 

    def path2id(self, path):
        file_id = self._new_id.get(path)
        if file_id is not None:
            return file_id
        old_path = self.old_path(path)
        if old_path is None:
            return None
        if old_path in self.deleted:
            return None
        return self.base_tree.path2id(old_path)

    def id2path(self, file_id):
        path = self._new_id_r.get(file_id)
        if path is not None:
            return path
        old_path = self.base_tree.id2path(file_id)
        if old_path is None:
            return None
        if old_path in self.deleted:
            return None
        return self.new_path(old_path)

    def old_contents_id(self, file_id):
        if self.contents_by_id:
            if self.base_tree.has_id(file_id):
                return file_id
            else:
                return None
        new_path = self.id2path(file_id)
        return self.base_tree.path2id(new_path)
        
    def get_file(self, file_id):
        base_id = self.old_contents_id(file_id)
        if base_id is not None:
            patch_original = self.base_tree.get_file(base_id)
        else:
            patch_original = None
        file_patch = self.patches.get(self.id2path(file_id))
        if file_patch is None:
            return patch_original
        return patched_file(file_patch, patch_original)

    def __iter__(self):
        for file_id in self._new_id_r.iterkeys():
            yield file_id
        for file_id in self.base_tree:
            if self.id2path(file_id) is None:
                continue
            yield file_id


def patched_file(file_patch, original):
    from bzrlib.patch import patch
    from tempfile import mkdtemp
    from shutil import rmtree
    from StringIO import StringIO
    from bzrlib.osutils import pumpfile
    import os.path
    temp_dir = mkdtemp()
    try:
        original_path = os.path.join(temp_dir, "originalfile")
        temp_original = file(original_path, "wb")
        if original is not None:
            pumpfile(original, temp_original)
        temp_original.close()
        patched_path = os.path.join(temp_dir, "patchfile")
        assert patch(file_patch, original_path, patched_path) == 0
        result = StringIO()
        temp_patched = file(patched_path, "rb")
        pumpfile(temp_patched, result)
        temp_patched.close()
        result.seek(0,0)

    finally:
        rmtree(temp_dir)

    return result

def test():
    import unittest
    from StringIO import StringIO
    from bzrlib.diff import internal_diff
    class MockTree(object):
        def __init__(self):
            object.__init__(self)
            self.paths = {}
            self.ids = {}
            self.contents = {}

        def __iter__(self):
            return self.paths.iterkeys()

        def add_dir(self, file_id, path):
            self.paths[file_id] = path
            self.ids[path] = file_id
        
        def add_file(self, file_id, path, contents):
            self.add_dir(file_id, path)
            self.contents[file_id] = contents

        def path2id(self, path):
            return self.ids.get(path)

        def id2path(self, file_id):
            return self.paths.get(file_id)

        def has_id(self, file_id):
            return self.id2path(file_id) is not None

        def get_file(self, file_id):
            result = StringIO()
            result.write(self.contents[file_id])
            result.seek(0,0)
            return result

    class CTreeTester(unittest.TestCase):

        def make_tree_1(self):
            mtree = MockTree()
            mtree.add_dir("a", "grandparent")
            mtree.add_dir("b", "grandparent/parent")
            mtree.add_file("c", "grandparent/parent/file", "Hello\n")
            mtree.add_dir("d", "grandparent/alt_parent")
            return ChangesetTree(mtree), mtree
            
        def test_renames(self):
            """Ensure that file renames have the proper effect on children"""
            ctree = self.make_tree_1()[0]
            self.assertEqual(ctree.old_path("grandparent"), "grandparent")
            self.assertEqual(ctree.old_path("grandparent/parent"), "grandparent/parent")
            self.assertEqual(ctree.old_path("grandparent/parent/file"),
                "grandparent/parent/file")

            self.assertEqual(ctree.id2path("a"), "grandparent")
            self.assertEqual(ctree.id2path("b"), "grandparent/parent")
            self.assertEqual(ctree.id2path("c"), "grandparent/parent/file")

            self.assertEqual(ctree.path2id("grandparent"), "a")
            self.assertEqual(ctree.path2id("grandparent/parent"), "b")
            self.assertEqual(ctree.path2id("grandparent/parent/file"), "c")

            self.assertEqual(ctree.path2id("grandparent2"), None)
            self.assertEqual(ctree.path2id("grandparent2/parent"), None)
            self.assertEqual(ctree.path2id("grandparent2/parent/file"), None)

            ctree.note_rename("grandparent", "grandparent2")
            self.assertEqual(ctree.old_path("grandparent"), None)
            self.assertEqual(ctree.old_path("grandparent/parent"), None)
            self.assertEqual(ctree.old_path("grandparent/parent/file"), None)

            self.assertEqual(ctree.id2path("a"), "grandparent2")
            self.assertEqual(ctree.id2path("b"), "grandparent2/parent")
            self.assertEqual(ctree.id2path("c"), "grandparent2/parent/file")

            self.assertEqual(ctree.path2id("grandparent2"), "a")
            self.assertEqual(ctree.path2id("grandparent2/parent"), "b")
            self.assertEqual(ctree.path2id("grandparent2/parent/file"), "c")

            self.assertEqual(ctree.path2id("grandparent"), None)
            self.assertEqual(ctree.path2id("grandparent/parent"), None)
            self.assertEqual(ctree.path2id("grandparent/parent/file"), None)

            ctree.note_rename("grandparent/parent", "grandparent2/parent2")
            self.assertEqual(ctree.id2path("a"), "grandparent2")
            self.assertEqual(ctree.id2path("b"), "grandparent2/parent2")
            self.assertEqual(ctree.id2path("c"), "grandparent2/parent2/file")

            self.assertEqual(ctree.path2id("grandparent2"), "a")
            self.assertEqual(ctree.path2id("grandparent2/parent2"), "b")
            self.assertEqual(ctree.path2id("grandparent2/parent2/file"), "c")

            self.assertEqual(ctree.path2id("grandparent2/parent"), None)
            self.assertEqual(ctree.path2id("grandparent2/parent/file"), None)

            ctree.note_rename("grandparent/parent/file", 
                              "grandparent2/parent2/file2")
            self.assertEqual(ctree.id2path("a"), "grandparent2")
            self.assertEqual(ctree.id2path("b"), "grandparent2/parent2")
            self.assertEqual(ctree.id2path("c"), "grandparent2/parent2/file2")

            self.assertEqual(ctree.path2id("grandparent2"), "a")
            self.assertEqual(ctree.path2id("grandparent2/parent2"), "b")
            self.assertEqual(ctree.path2id("grandparent2/parent2/file2"), "c")

            self.assertEqual(ctree.path2id("grandparent2/parent2/file"), None)

        def test_moves(self):
            """Ensure that file moves have the proper effect on children"""
            ctree = self.make_tree_1()[0]
            ctree.note_rename("grandparent/parent/file", 
                              "grandparent/alt_parent/file")
            self.assertEqual(ctree.id2path("c"), "grandparent/alt_parent/file")
            self.assertEqual(ctree.path2id("grandparent/alt_parent/file"), "c")
            self.assertEqual(ctree.path2id("grandparent/parent/file"), None)

        def unified_diff(self, old, new):
            out = StringIO()
            internal_diff("old", old, "new", new, out)
            out.seek(0,0)
            return out.read()

        def make_tree_2(self):
            ctree = self.make_tree_1()[0]
            ctree.note_rename("grandparent/parent/file", 
                              "grandparent/alt_parent/file")
            self.assertEqual(ctree.id2path("e"), None)
            self.assertEqual(ctree.path2id("grandparent/parent/file"), None)
            ctree.note_id("e", "grandparent/parent/file")
            return ctree

        def test_adds(self):
            """File/inventory adds"""
            ctree = self.make_tree_2()
            add_patch = self.unified_diff([], ["Extra cheese\n"])
            ctree.note_patch("grandparent/parent/file", add_patch)
            self.adds_test(ctree)

        def adds_test(self, ctree):
            self.assertEqual(ctree.id2path("e"), "grandparent/parent/file")
            self.assertEqual(ctree.path2id("grandparent/parent/file"), "e")
            self.assertEqual(ctree.get_file("e").read(), "Extra cheese\n")

        def test_adds2(self):
            """File/inventory adds, with patch-compatibile renames"""
            ctree = self.make_tree_2()
            ctree.contents_by_id = False
            add_patch = self.unified_diff(["Hello\n"], ["Extra cheese\n"])
            ctree.note_patch("grandparent/parent/file", add_patch)
            self.adds_test(ctree)

        def make_tree_3(self):
            ctree, mtree = self.make_tree_1()
            mtree.add_file("e", "grandparent/parent/topping", "Anchovies\n")
            ctree.note_rename("grandparent/parent/file", 
                              "grandparent/alt_parent/file")
            ctree.note_rename("grandparent/parent/topping", 
                              "grandparent/alt_parent/stopping")
            return ctree

        def get_file_test(self, ctree):
            self.assertEqual(ctree.get_file("e").read(), "Lemon\n")
            self.assertEqual(ctree.get_file("c").read(), "Hello\n")

        def test_get_file(self):
            """Get file contents"""
            ctree = self.make_tree_3()
            mod_patch = self.unified_diff(["Anchovies\n"], ["Lemon\n"])
            ctree.note_patch("grandparent/alt_parent/stopping", mod_patch)
            self.get_file_test(ctree)

        def test_get_file2(self):
            """Get file contents, with patch-compatibile renames"""
            ctree = self.make_tree_3()
            ctree.contents_by_id = False
            mod_patch = self.unified_diff([], ["Lemon\n"])
            ctree.note_patch("grandparent/alt_parent/stopping", mod_patch)
            mod_patch = self.unified_diff([], ["Hello\n"])
            ctree.note_patch("grandparent/alt_parent/file", mod_patch)
            self.get_file_test(ctree)

        def test_delete(self):
            "Deletion by changeset"
            ctree = self.make_tree_1()[0]
            self.assertEqual(ctree.get_file("c").read(), "Hello\n")
            ctree.note_deletion("grandparent/parent/file")
            self.assertEqual(ctree.id2path("c"), None)
            self.assertEqual(ctree.path2id("grandparent/parent/file"), None)

        def sorted_ids(self, tree):
            ids = list(tree)
            ids.sort()
            return ids

        def test_iteration(self):
            """Ensure that iteration through ids works properly"""
            ctree = self.make_tree_1()[0]
            self.assertEqual(self.sorted_ids(ctree), ['a', 'b', 'c', 'd'])
            ctree.note_deletion("grandparent/parent/file")
            ctree.note_id("e", "grandparent/alt_parent/fool")
            self.assertEqual(self.sorted_ids(ctree), ['a', 'b', 'd', 'e'])
            

    patchesTestSuite = unittest.makeSuite(CTreeTester,'test_')
    runner = unittest.TextTestRunner()
    runner.run(patchesTestSuite)

