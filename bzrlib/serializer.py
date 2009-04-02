# Copyright (C) 2005, 2006 Canonical Ltd
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

"""Inventory/revision serialization."""

from bzrlib import registry

class Serializer(object):
    """Abstract object serialize/deserialize"""

    def write_inventory(self, inv, f):
        """Write inventory to a file"""
        raise NotImplementedError(self.write_inventory)

    def write_inventory_to_string(self, inv):
        raise NotImplementedError(self.write_inventory_to_string)

    def read_inventory_from_string(self, string, revision_id=None,
                                   entry_cache=None):
        """Read string into an inventory object.

        :param string: The serialized inventory to read.
        :param revision_id: If not-None, the expected revision id of the
            inventory. Some serialisers use this to set the results' root
            revision. This should be supplied for deserialising all
            from-repository inventories so that xml5 inventories that were
            serialised without a revision identifier can be given the right
            revision id (but not for working tree inventories where users can
            edit the data without triggering checksum errors or anything).
        :param entry_cache: An optional cache of InventoryEntry objects. If
            supplied we will look up entries via (file_id, revision_id) which
            should map to a valid InventoryEntry (File/Directory/etc) object.
        """
        raise NotImplementedError(self.read_inventory_from_string)

    def read_inventory(self, f, revision_id=None):
        raise NotImplementedError(self.read_inventory)

    def write_revision(self, rev, f):
        raise NotImplementedError(self.write_revision)

    def write_revision_to_string(self, rev):
        raise NotImplementedError(self.write_revision_to_string)

    def read_revision(self, f):
        raise NotImplementedError(self.read_revision)

    def read_revision_from_string(self, xml_string):
        raise NotImplementedError(self.read_revision_from_string)


class SerializerRegistry(registry.Registry):
    """Registry for serializer objects"""


format_registry = SerializerRegistry()
format_registry.register_lazy('4', 'bzrlib.xml4', 'serializer_v4')
format_registry.register_lazy('5', 'bzrlib.xml5', 'serializer_v5')
format_registry.register_lazy('6', 'bzrlib.xml6', 'serializer_v6')
format_registry.register_lazy('7', 'bzrlib.xml7', 'serializer_v7')
format_registry.register_lazy('8', 'bzrlib.xml8', 'serializer_v8')
