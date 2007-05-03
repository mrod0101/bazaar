# Copyright (C) 2007 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Helper functions for DirState.

This is the python implementation for DirState functions.
"""

from bzrlib.dirstate import DirState


def _read_dirblocks(state):
    """Read in the dirblocks for the given DirState object.

    This is tightly bound to the DirState internal representation. It should be
    thought of as a member function, which is only separated out so that we can
    re-write it in pyrex.

    :param state: A DirState object.
    :return: None
    """
    cdef int pos
    cdef int entry_size
    cdef int field_count

    state._state_file.seek(state._end_of_header)
    text = state._state_file.read()
    # TODO: check the crc checksums. crc_measured = zlib.crc32(text)

    fields = text.split('\0')
    # Remove the last blank entry
    trailing = fields.pop()
    assert trailing == ''
    # consider turning fields into a tuple.

    # skip the first field which is the trailing null from the header.
    cur = 1
    # Each line now has an extra '\n' field which is not used
    # so we just skip over it
    # entry size:
    #  3 fields for the key
    #  + number of fields per tree_data (5) * tree count
    #  + newline
    num_present_parents = state._num_present_parents()
    tree_count = 1 + num_present_parents
    entry_size = state._fields_per_entry()
    expected_field_count = entry_size * state._num_entries
    field_count = len(fields)
    # this checks our adjustment, and also catches file too short.
    assert field_count - cur == expected_field_count, \
        'field count incorrect %s != %s, entry_size=%s, '\
        'num_entries=%s fields=%r' % (
            field_count - cur, expected_field_count, entry_size,
            state._num_entries, fields)

    if num_present_parents == 1:
        # Bind external functions to local names
        _int = int
        # We access all fields in order, so we can just iterate over
        # them. Grab an straight iterator over the fields. (We use an
        # iterator because we don't want to do a lot of additions, nor
        # do we want to do a lot of slicing)
        next = iter(fields).next
        # Move the iterator to the current position
        for x in xrange(cur):
            next()
        # The two blocks here are deliberate: the root block and the
        # contents-of-root block.
        state._dirblocks = [('', []), ('', [])]
        current_block = state._dirblocks[0][1]
        current_dirname = ''
        append_entry = current_block.append
        for count in xrange(state._num_entries):
            dirname = next()
            name = next()
            file_id = next()
            if dirname != current_dirname:
                # new block - different dirname
                current_block = []
                current_dirname = dirname
                state._dirblocks.append((current_dirname, current_block))
                append_entry = current_block.append
            # we know current_dirname == dirname, so re-use it to avoid
            # creating new strings
            entry = ((current_dirname, name, file_id),
                     [(# Current Tree
                         next(),                # minikind
                         next(),                # fingerprint
                         _int(next()),          # size
                         next() == 'y',         # executable
                         next(),                # packed_stat or revision_id
                     ),
                     ( # Parent 1
                         next(),                # minikind
                         next(),                # fingerprint
                         _int(next()),          # size
                         next() == 'y',         # executable
                         next(),                # packed_stat or revision_id
                     ),
                     ])
            trailing = next()
            assert trailing == '\n'
            # append the entry to the current block
            append_entry(entry)
        state._split_root_dirblock_into_contents()
    else:

        fields_to_entry = state._get_fields_to_entry()
        entries = []
        entries_append = entries.append
        pos = cur
        entry_size = entry_size
        while pos < field_count:
            entries_append(fields_to_entry(fields[pos:pos+entry_size]))
            pos = pos + entry_size
        state._entries_to_current_state(entries)
    # To convert from format 2  => format 3
    # state._dirblocks = sorted(state._dirblocks,
    #                          key=lambda blk:blk[0].split('/'))
    # To convert from format 3 => format 2
    # state._dirblocks = sorted(state._dirblocks)
    state._dirblock_state = DirState.IN_MEMORY_UNMODIFIED
