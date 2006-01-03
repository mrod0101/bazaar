# Copyright (C) 2004, 2005 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


import os
import sys
import stat
from cStringIO import StringIO

from bzrlib.errors import (NoSuchFile, FileExists,
                           TransportNotPossible, ConnectionError)
from bzrlib.tests import TestCase, TestCaseInTempDir
from bzrlib.tests.HTTPTestUtil import TestCaseWithWebserver
from bzrlib.transport import memory, urlescape
from bzrlib.osutils import pathjoin


def _append(fn, txt):
    """Append the given text (file-like object) to the supplied filename."""
    f = open(fn, 'ab')
    f.write(txt)
    f.flush()
    f.close()
    del f


if sys.platform != 'win32':
    def check_mode(test, path, mode):
        """Check that a particular path has the correct mode."""
        actual_mode = stat.S_IMODE(os.stat(path).st_mode)
        test.assertEqual(mode, actual_mode,
            'mode of %r incorrect (%o != %o)' % (path, mode, actual_mode))
else:
    def check_mode(test, path, mode):
        """On win32 chmod doesn't have any effect, 
        so don't actually check anything
        """
        return


class TestTransport(TestCase):
    """Test the non transport-concrete class functionality."""

    def test_urlescape(self):
        self.assertEqual('%25', urlescape('%'))


class TestTransportMixIn(object):
    """Subclass this, and it will provide a series of tests for a Transport.
    It assumes that the Transport object is connected to the 
    current working directory.  So that whatever is done 
    through the transport, should show up in the working 
    directory, and vice-versa.

    This also tests to make sure that the functions work with both
    generators and lists (assuming iter(list) is effectively a generator)
    """
    readonly = False
    def get_transport(self):
        """Children should override this to return the Transport object.
        """
        raise NotImplementedError

    def assertListRaises(self, excClass, func, *args, **kwargs):
        """Many transport functions can return generators this makes sure
        to wrap them in a list() call to make sure the whole generator
        is run, and that the proper exception is raised.
        """
        try:
            list(func(*args, **kwargs))
        except excClass:
            return
        else:
            if hasattr(excClass,'__name__'): excName = excClass.__name__
            else: excName = str(excClass)
            raise self.failureException, "%s not raised" % excName

    def test_has(self):
        t = self.get_transport()

        files = ['a', 'b', 'e', 'g', '%']
        self.build_tree(files)
        self.assertEqual(True, t.has('a'))
        self.assertEqual(False, t.has('c'))
        self.assertEqual(True, t.has(urlescape('%')))
        self.assertEqual(list(t.has_multi(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'])),
                [True, True, False, False, True, False, True, False])
        self.assertEqual(True, t.has_any(['a', 'b', 'c']))
        self.assertEqual(False, t.has_any(['c', 'd', 'f', urlescape('%%')]))
        self.assertEqual(list(t.has_multi(iter(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']))),
                [True, True, False, False, True, False, True, False])
        self.assertEqual(False, t.has_any(['c', 'c', 'c']))
        self.assertEqual(True, t.has_any(['b', 'b', 'b']))

    def test_get(self):
        t = self.get_transport()

        files = ['a', 'b', 'e', 'g']
        self.build_tree(files)
        self.assertEqual(open('a', 'rb').read(), t.get('a').read())
        content_f = t.get_multi(files)
        for path,f in zip(files, content_f):
            self.assertEqual(f.read(), open(path, 'rb').read())

        content_f = t.get_multi(iter(files))
        for path,f in zip(files, content_f):
            self.assertEqual(f.read(), open(path, 'rb').read())

        self.assertRaises(NoSuchFile, t.get, 'c')
        self.assertListRaises(NoSuchFile, t.get_multi, ['a', 'b', 'c'])
        self.assertListRaises(NoSuchFile, t.get_multi, iter(['a', 'b', 'c']))

    def test_put(self):
        t = self.get_transport()

        # TODO: jam 20051215 No need to do anything if the test is readonly
        #                    origininally it was thought that it would give
        #                    more of a workout to readonly tests. By now the
        #                    suite is probably thorough enough without testing
        #                    readonly protocols in write sections
        #                    The only thing that needs to be tested is that the
        #                    right error is raised

        if self.readonly:
            self.assertRaises(TransportNotPossible,
                    t.put, 'a', 'some text for a\n')
            open('a', 'wb').write('some text for a\n')
        else:
            t.put('a', 'some text for a\n')
        self.assert_(os.path.exists('a'))
        self.check_file_contents('a', 'some text for a\n')
        self.assertEqual(t.get('a').read(), 'some text for a\n')
        # Make sure 'has' is updated
        self.assertEqual(list(t.has_multi(['a', 'b', 'c', 'd', 'e'])),
                [True, False, False, False, False])
        if self.readonly:
            self.assertRaises(TransportNotPossible,
                    t.put_multi,
                    [('a', 'new\ncontents for\na\n'),
                        ('d', 'contents\nfor d\n')])
            open('a', 'wb').write('new\ncontents for\na\n')
            open('d', 'wb').write('contents\nfor d\n')
        else:
            # Put also replaces contents
            self.assertEqual(t.put_multi([('a', 'new\ncontents for\na\n'),
                                          ('d', 'contents\nfor d\n')]),
                             2)
        self.assertEqual(list(t.has_multi(['a', 'b', 'c', 'd', 'e'])),
                [True, False, False, True, False])
        self.check_file_contents('a', 'new\ncontents for\na\n')
        self.check_file_contents('d', 'contents\nfor d\n')

        if self.readonly:
            self.assertRaises(TransportNotPossible,
                t.put_multi, iter([('a', 'diff\ncontents for\na\n'),
                                  ('d', 'another contents\nfor d\n')]))
            open('a', 'wb').write('diff\ncontents for\na\n')
            open('d', 'wb').write('another contents\nfor d\n')
        else:
            self.assertEqual(
                t.put_multi(iter([('a', 'diff\ncontents for\na\n'),
                                  ('d', 'another contents\nfor d\n')]))
                             , 2)
        self.check_file_contents('a', 'diff\ncontents for\na\n')
        self.check_file_contents('d', 'another contents\nfor d\n')

        if self.readonly:
            self.assertRaises(TransportNotPossible,
                    t.put, 'path/doesnt/exist/c', 'contents')
        else:
            self.assertRaises(NoSuchFile,
                    t.put, 'path/doesnt/exist/c', 'contents')

        if not self.readonly:
            t.put('mode644', 'test text\n', mode=0644)
            check_mode(self, 'mode644', 0644)

            t.put('mode666', 'test text\n', mode=0666)
            check_mode(self, 'mode666', 0666)

            t.put('mode600', 'test text\n', mode=0600)
            check_mode(self, 'mode600', 0600)

            # Yes, you can put a file such that it becomes readonly
            t.put('mode400', 'test text\n', mode=0400)
            check_mode(self, 'mode400', 0400)

            t.put_multi([('mmode644', 'text\n')], mode=0644)
            check_mode(self, 'mmode644', 0644)

        # TODO: jam 20051215 test put_multi with a mode. I didn't bother because
        #                    it seems most people don't like the _multi functions

    def test_put_file(self):
        t = self.get_transport()

        # Test that StringIO can be used as a file-like object with put
        f1 = StringIO('this is a string\nand some more stuff\n')
        if self.readonly:
            open('f1', 'wb').write(f1.read())
        else:
            t.put('f1', f1)

        del f1

        self.check_file_contents('f1', 
                'this is a string\nand some more stuff\n')

        f2 = StringIO('here is some text\nand a bit more\n')
        f3 = StringIO('some text for the\nthird file created\n')

        if self.readonly:
            open('f2', 'wb').write(f2.read())
            open('f3', 'wb').write(f3.read())
        else:
            t.put_multi([('f2', f2), ('f3', f3)])

        del f2, f3

        self.check_file_contents('f2', 'here is some text\nand a bit more\n')
        self.check_file_contents('f3', 'some text for the\nthird file created\n')

        # Test that an actual file object can be used with put
        f4 = open('f1', 'rb')
        if self.readonly:
            open('f4', 'wb').write(f4.read())
        else:
            t.put('f4', f4)

        del f4

        self.check_file_contents('f4', 
                'this is a string\nand some more stuff\n')

        f5 = open('f2', 'rb')
        f6 = open('f3', 'rb')
        if self.readonly:
            open('f5', 'wb').write(f5.read())
            open('f6', 'wb').write(f6.read())
        else:
            t.put_multi([('f5', f5), ('f6', f6)])

        del f5, f6

        self.check_file_contents('f5', 'here is some text\nand a bit more\n')
        self.check_file_contents('f6', 'some text for the\nthird file created\n')

        if not self.readonly:
            sio = StringIO('test text\n')
            t.put('mode644', sio, mode=0644)
            check_mode(self, 'mode644', 0644)

            a = open('mode644', 'rb')
            t.put('mode666', a, mode=0666)
            check_mode(self, 'mode666', 0666)

            a = open('mode644', 'rb')
            t.put('mode600', a, mode=0600)
            check_mode(self, 'mode600', 0600)

            # Yes, you can put a file such that it becomes readonly
            a = open('mode644', 'rb')
            t.put('mode400', a, mode=0400)
            check_mode(self, 'mode400', 0400)

    def test_mkdir(self):
        t = self.get_transport()

        # Test mkdir
        os.mkdir('dir_a')
        self.assertEqual(t.has('dir_a'), True)
        self.assertEqual(t.has('dir_b'), False)

        if self.readonly:
            self.assertRaises(TransportNotPossible,
                    t.mkdir, 'dir_b')
            os.mkdir('dir_b')
        else:
            t.mkdir('dir_b')
        self.assertEqual(t.has('dir_b'), True)
        self.assert_(os.path.isdir('dir_b'))

        if self.readonly:
            self.assertRaises(TransportNotPossible,
                    t.mkdir_multi, ['dir_c', 'dir_d'])
            os.mkdir('dir_c')
            os.mkdir('dir_d')
        else:
            t.mkdir_multi(['dir_c', 'dir_d'])

        if self.readonly:
            self.assertRaises(TransportNotPossible,
                    t.mkdir_multi, iter(['dir_e', 'dir_f']))
            os.mkdir('dir_e')
            os.mkdir('dir_f')
        else:
            t.mkdir_multi(iter(['dir_e', 'dir_f']))
        self.assertEqual(list(t.has_multi(
            ['dir_a', 'dir_b', 'dir_c', 'dir_q',
             'dir_d', 'dir_e', 'dir_f', 'dir_b'])),
            [True, True, True, False,
             True, True, True, True])
        for d in ['dir_a', 'dir_b', 'dir_c', 'dir_d', 'dir_e', 'dir_f']:
            self.assert_(os.path.isdir(d))

        if not self.readonly:
            self.assertRaises(NoSuchFile, t.mkdir, 'path/doesnt/exist')
            self.assertRaises(FileExists, t.mkdir, 'dir_a') # Creating a directory again should fail

        # Make sure the transport recognizes when a
        # directory is created by other means
        # Caching Transports will fail, because dir_e was already seen not
        # to exist. So instead, we will search for a new directory
        #os.mkdir('dir_e')
        #if not self.readonly:
        #    self.assertRaises(FileExists, t.mkdir, 'dir_e')

        os.mkdir('dir_g')
        if not self.readonly:
            self.assertRaises(FileExists, t.mkdir, 'dir_g')

        # Test get/put in sub-directories
        if self.readonly:
            open('dir_a/a', 'wb').write('contents of dir_a/a')
            open('dir_b/b', 'wb').write('contents of dir_b/b')
        else:
            self.assertEqual(
                t.put_multi([('dir_a/a', 'contents of dir_a/a'),
                             ('dir_b/b', 'contents of dir_b/b')])
                          , 2)
        for f in ('dir_a/a', 'dir_b/b'):
            self.assertEqual(t.get(f).read(), open(f, 'rb').read())

        if not self.readonly:
            # Test mkdir with a mode
            t.mkdir('dmode755', mode=0755)
            check_mode(self, 'dmode755', 0755)

            t.mkdir('dmode555', mode=0555)
            check_mode(self, 'dmode555', 0555)

            t.mkdir('dmode777', mode=0777)
            check_mode(self, 'dmode777', 0777)

            t.mkdir('dmode700', mode=0700)
            check_mode(self, 'dmode700', 0700)

            # TODO: jam 20051215 test mkdir_multi with a mode
            t.mkdir_multi(['mdmode755'], mode=0755)
            check_mode(self, 'mdmode755', 0755)


    def test_copy_to(self):
        import tempfile
        from bzrlib.transport.local import LocalTransport

        t = self.get_transport()

        files = ['a', 'b', 'c', 'd']
        self.build_tree(files)

        def get_temp_local():
            dtmp = tempfile.mkdtemp(dir=u'.', prefix='test-transport-')
            dtmp_base = os.path.basename(dtmp)
            return dtmp_base, LocalTransport(dtmp)
        dtmp_base, local_t = get_temp_local()

        t.copy_to(files, local_t)
        for f in files:
            self.assertEquals(open(f, 'rb').read(),
                    open(pathjoin(dtmp_base, f), 'rb').read())

        # Test that copying into a missing directory raises
        # NoSuchFile
        os.mkdir('e')
        open('e/f', 'wb').write('contents of e')
        self.assertRaises(NoSuchFile, t.copy_to, ['e/f'], local_t)

        os.mkdir(pathjoin(dtmp_base, 'e'))
        t.copy_to(['e/f'], local_t)

        del dtmp_base, local_t

        dtmp_base, local_t = get_temp_local()

        files = ['a', 'b', 'c', 'd']
        t.copy_to(iter(files), local_t)
        for f in files:
            self.assertEquals(open(f, 'rb').read(),
                    open(pathjoin(dtmp_base, f), 'rb').read())

        del dtmp_base, local_t

        for mode in (0666, 0644, 0600, 0400):
            dtmp_base, local_t = get_temp_local()
            t.copy_to(files, local_t, mode=mode)
            for f in files:
                check_mode(self, os.path.join(dtmp_base, f), mode)

    def test_append(self):
        t = self.get_transport()

        if self.readonly:
            open('a', 'wb').write('diff\ncontents for\na\n')
            open('b', 'wb').write('contents\nfor b\n')
        else:
            t.put_multi([
                    ('a', 'diff\ncontents for\na\n'),
                    ('b', 'contents\nfor b\n')
                    ])

        if self.readonly:
            self.assertRaises(TransportNotPossible,
                    t.append, 'a', 'add\nsome\nmore\ncontents\n')
            _append('a', 'add\nsome\nmore\ncontents\n')
        else:
            t.append('a', 'add\nsome\nmore\ncontents\n')

        self.check_file_contents('a', 
            'diff\ncontents for\na\nadd\nsome\nmore\ncontents\n')

        if self.readonly:
            self.assertRaises(TransportNotPossible,
                    t.append_multi,
                        [('a', 'and\nthen\nsome\nmore\n'),
                         ('b', 'some\nmore\nfor\nb\n')])
            _append('a', 'and\nthen\nsome\nmore\n')
            _append('b', 'some\nmore\nfor\nb\n')
        else:
            t.append_multi([('a', 'and\nthen\nsome\nmore\n'),
                    ('b', 'some\nmore\nfor\nb\n')])
        self.check_file_contents('a', 
            'diff\ncontents for\na\n'
            'add\nsome\nmore\ncontents\n'
            'and\nthen\nsome\nmore\n')
        self.check_file_contents('b', 
                'contents\nfor b\n'
                'some\nmore\nfor\nb\n')

        if self.readonly:
            _append('a', 'a little bit more\n')
            _append('b', 'from an iterator\n')
        else:
            t.append_multi(iter([('a', 'a little bit more\n'),
                    ('b', 'from an iterator\n')]))
        self.check_file_contents('a', 
            'diff\ncontents for\na\n'
            'add\nsome\nmore\ncontents\n'
            'and\nthen\nsome\nmore\n'
            'a little bit more\n')
        self.check_file_contents('b', 
                'contents\nfor b\n'
                'some\nmore\nfor\nb\n'
                'from an iterator\n')

        if self.readonly:
            _append('c', 'some text\nfor a missing file\n')
            _append('a', 'some text in a\n')
            _append('d', 'missing file r\n')
        else:
            t.append('c', 'some text\nfor a missing file\n')
            t.append_multi([('a', 'some text in a\n'),
                            ('d', 'missing file r\n')])
        self.check_file_contents('a', 
            'diff\ncontents for\na\n'
            'add\nsome\nmore\ncontents\n'
            'and\nthen\nsome\nmore\n'
            'a little bit more\n'
            'some text in a\n')
        self.check_file_contents('c', 'some text\nfor a missing file\n')
        self.check_file_contents('d', 'missing file r\n')

    def test_append_file(self):
        t = self.get_transport()

        contents = [
            ('f1', 'this is a string\nand some more stuff\n'),
            ('f2', 'here is some text\nand a bit more\n'),
            ('f3', 'some text for the\nthird file created\n'),
            ('f4', 'this is a string\nand some more stuff\n'),
            ('f5', 'here is some text\nand a bit more\n'),
            ('f6', 'some text for the\nthird file created\n')
        ]
        
        if self.readonly:
            for f, val in contents:
                open(f, 'wb').write(val)
        else:
            t.put_multi(contents)

        a1 = StringIO('appending to\none\n')
        if self.readonly:
            _append('f1', a1.read())
        else:
            t.append('f1', a1)

        del a1

        self.check_file_contents('f1', 
                'this is a string\nand some more stuff\n'
                'appending to\none\n')

        a2 = StringIO('adding more\ntext to two\n')
        a3 = StringIO('some garbage\nto put in three\n')

        if self.readonly:
            _append('f2', a2.read())
            _append('f3', a3.read())
        else:
            t.append_multi([('f2', a2), ('f3', a3)])

        del a2, a3

        self.check_file_contents('f2',
                'here is some text\nand a bit more\n'
                'adding more\ntext to two\n')
        self.check_file_contents('f3', 
                'some text for the\nthird file created\n'
                'some garbage\nto put in three\n')

        # Test that an actual file object can be used with put
        a4 = open('f1', 'rb')
        if self.readonly:
            _append('f4', a4.read())
        else:
            t.append('f4', a4)

        del a4

        self.check_file_contents('f4', 
                'this is a string\nand some more stuff\n'
                'this is a string\nand some more stuff\n'
                'appending to\none\n')

        a5 = open('f2', 'rb')
        a6 = open('f3', 'rb')
        if self.readonly:
            _append('f5', a5.read())
            _append('f6', a6.read())
        else:
            t.append_multi([('f5', a5), ('f6', a6)])

        del a5, a6

        self.check_file_contents('f5',
                'here is some text\nand a bit more\n'
                'here is some text\nand a bit more\n'
                'adding more\ntext to two\n')
        self.check_file_contents('f6',
                'some text for the\nthird file created\n'
                'some text for the\nthird file created\n'
                'some garbage\nto put in three\n')

        a5 = open('f2', 'rb')
        a6 = open('f2', 'rb')
        a7 = open('f3', 'rb')
        if self.readonly:
            _append('c', a5.read())
            _append('a', a6.read())
            _append('d', a7.read())
        else:
            t.append('c', a5)
            t.append_multi([('a', a6), ('d', a7)])
        del a5, a6, a7
        self.check_file_contents('c', open('f2', 'rb').read())
        self.check_file_contents('d', open('f3', 'rb').read())


    def test_delete(self):
        # TODO: Test Transport.delete
        t = self.get_transport()

        # Not much to do with a readonly transport
        if self.readonly:
            return

        open('a', 'wb').write('a little bit of text\n')
        self.failUnless(t.has('a'))
        self.failUnlessExists('a')
        t.delete('a')
        self.failIf(os.path.lexists('a'))

        self.assertRaises(NoSuchFile, t.delete, 'a')

        open('a', 'wb').write('a text\n')
        open('b', 'wb').write('b text\n')
        open('c', 'wb').write('c text\n')
        self.assertEqual([True, True, True],
                list(t.has_multi(['a', 'b', 'c'])))
        t.delete_multi(['a', 'c'])
        self.assertEqual([False, True, False],
                list(t.has_multi(['a', 'b', 'c'])))
        self.failIf(os.path.lexists('a'))
        self.failUnlessExists('b')
        self.failIf(os.path.lexists('c'))

        self.assertRaises(NoSuchFile,
                t.delete_multi, ['a', 'b', 'c'])

        self.assertRaises(NoSuchFile,
                t.delete_multi, iter(['a', 'b', 'c']))

        open('a', 'wb').write('another a text\n')
        open('c', 'wb').write('another c text\n')
        t.delete_multi(iter(['a', 'b', 'c']))

        # We should have deleted everything
        # SftpServer creates control files in the
        # working directory, so we can just do a
        # plain "listdir".
        # self.assertEqual([], os.listdir('.'))

    def test_move(self):
        t = self.get_transport()

        if self.readonly:
            return

        # TODO: I would like to use os.listdir() to
        # make sure there are no extra files, but SftpServer
        # creates control files in the working directory
        # perhaps all of this could be done in a subdirectory

        open('a', 'wb').write('a first file\n')
        self.assertEquals([True, False], list(t.has_multi(['a', 'b'])))

        t.move('a', 'b')
        self.failUnlessExists('b')
        self.failIf(os.path.lexists('a'))

        self.check_file_contents('b', 'a first file\n')
        self.assertEquals([False, True], list(t.has_multi(['a', 'b'])))

        # Overwrite a file
        open('c', 'wb').write('c this file\n')
        t.move('c', 'b')
        self.failIf(os.path.lexists('c'))
        self.check_file_contents('b', 'c this file\n')

        # TODO: Try to write a test for atomicity
        # TODO: Test moving into a non-existant subdirectory
        # TODO: Test Transport.move_multi

    def test_copy(self):
        t = self.get_transport()

        if self.readonly:
            return

        open('a', 'wb').write('a file\n')
        t.copy('a', 'b')
        self.check_file_contents('b', 'a file\n')

        self.assertRaises(NoSuchFile, t.copy, 'c', 'd')
        os.mkdir('c')
        # What should the assert be if you try to copy a
        # file over a directory?
        #self.assertRaises(Something, t.copy, 'a', 'c')
        open('d', 'wb').write('text in d\n')
        t.copy('d', 'b')
        self.check_file_contents('b', 'text in d\n')

        # TODO: test copy_multi

    def test_connection_error(self):
        """ConnectionError is raised when connection is impossible"""
        if not hasattr(self, "get_bogus_transport"):
            return
        t = self.get_bogus_transport()
        try:
            t.get('.bzr/branch')
        except (ConnectionError, NoSuchFile), e:
            pass
        except (Exception), e:
            self.failIf(True, 'Wrong exception thrown: %s' % e)
        else:
            self.failIf(True, 'Did not get the expected exception.')

    def test_stat(self):
        # TODO: Test stat, just try once, and if it throws, stop testing
        from stat import S_ISDIR, S_ISREG

        t = self.get_transport()

        try:
            st = t.stat('.')
        except TransportNotPossible, e:
            # This transport cannot stat
            return

        paths = ['a', 'b/', 'b/c', 'b/d/', 'b/d/e']
        self.build_tree(paths)

        local_stats = []

        for p in paths:
            st = t.stat(p)
            local_st = os.stat(p)
            if p.endswith('/'):
                self.failUnless(S_ISDIR(st.st_mode))
            else:
                self.failUnless(S_ISREG(st.st_mode))
            self.assertEqual(local_st.st_size, st.st_size)
            self.assertEqual(local_st.st_mode, st.st_mode)
            local_stats.append(local_st)

        remote_stats = list(t.stat_multi(paths))
        remote_iter_stats = list(t.stat_multi(iter(paths)))

        for local, remote, remote_iter in \
            zip(local_stats, remote_stats, remote_iter_stats):
            self.assertEqual(local.st_mode, remote.st_mode)
            self.assertEqual(local.st_mode, remote_iter.st_mode)

            self.assertEqual(local.st_size, remote.st_size)
            self.assertEqual(local.st_size, remote_iter.st_size)
            # Should we test UID/GID?

        self.assertRaises(NoSuchFile, t.stat, 'q')
        self.assertRaises(NoSuchFile, t.stat, 'b/a')

        self.assertListRaises(NoSuchFile, t.stat_multi, ['a', 'c', 'd'])
        self.assertListRaises(NoSuchFile, t.stat_multi, iter(['a', 'c', 'd']))

    def test_list_dir(self):
        # TODO: Test list_dir, just try once, and if it throws, stop testing
        t = self.get_transport()
        
        if not t.listable():
            self.assertRaises(TransportNotPossible, t.list_dir, '.')
            return

        def sorted_list(d):
            l = list(t.list_dir(d))
            l.sort()
            return l

        # SftpServer creates control files in the working directory
        # so lets move down a directory to be safe
        os.mkdir('wd')
        os.chdir('wd')
        t = t.clone('wd')

        self.assertEqual([], sorted_list(u'.'))
        self.build_tree(['a', 'b', 'c/', 'c/d', 'c/e'])

        self.assertEqual([u'a', u'b', u'c'], sorted_list(u'.'))
        self.assertEqual([u'd', u'e'], sorted_list(u'c'))

        os.remove('c/d')
        os.remove('b')
        self.assertEqual([u'a', u'c'], sorted_list('.'))
        self.assertEqual([u'e'], sorted_list(u'c'))

        self.assertListRaises(NoSuchFile, t.list_dir, 'q')
        self.assertListRaises(NoSuchFile, t.list_dir, 'c/f')
        self.assertListRaises(NoSuchFile, t.list_dir, 'a')

    def test_clone(self):
        # TODO: Test that clone moves up and down the filesystem
        t1 = self.get_transport()

        self.build_tree(['a', 'b/', 'b/c'])

        self.failUnless(t1.has('a'))
        self.failUnless(t1.has('b/c'))
        self.failIf(t1.has('c'))

        t2 = t1.clone('b')
        self.failUnless(t2.has('c'))
        self.failIf(t2.has('a'))

        t3 = t2.clone('..')
        self.failUnless(t3.has('a'))
        self.failIf(t3.has('c'))

        self.failIf(t1.has('b/d'))
        self.failIf(t2.has('d'))
        self.failIf(t3.has('b/d'))

        if self.readonly:
            open('b/d', 'wb').write('newfile\n')
        else:
            t2.put('d', 'newfile\n')

        self.failUnless(t1.has('b/d'))
        self.failUnless(t2.has('d'))
        self.failUnless(t3.has('b/d'))

        
class HttpTransportTest(TestCaseWithWebserver, TestTransportMixIn):

    readonly = True

    def get_transport(self):
        from bzrlib.transport.http import HttpTransport
        url = self.get_remote_url(u'.')
        return HttpTransport(url)

    def get_bogus_transport(self):
        from bzrlib.transport.http import HttpTransport
        return HttpTransport('http://jasldkjsalkdjalksjdkljasd')


class MemoryTransportTest(TestCase):
    """Memory transport specific tests."""

    def test_parameters(self):
        import bzrlib.transport.memory as memory
        transport = memory.MemoryTransport()
        self.assertEqual(True, transport.listable())
        self.assertEqual(False, transport.should_cache())
        self.assertEqual(False, transport.is_readonly())
