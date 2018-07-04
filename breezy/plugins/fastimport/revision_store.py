# Copyright (C) 2008, 2009 Canonical Ltd
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
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""An abstraction of a repository providing just the bits importing needs."""

from __future__ import absolute_import

from io import BytesIO

from ... import (
    errors,
    graph as _mod_graph,
    lru_cache,
    osutils,
    revision as _mod_revision,
    trace,
    )
from ...bzr import (
    knit,
    inventory,
    )


class _TreeShim(object):
    """Fake a Tree implementation.

    This implements just enough of the tree api to make commit builder happy.
    """

    def __init__(self, repo, basis_inv, inv_delta, content_provider):
        self._repo = repo
        self._content_provider = content_provider
        self._basis_inv = basis_inv
        self._inv_delta = inv_delta
        self._new_info_by_id = dict([(file_id, (new_path, ie))
                                    for _, new_path, file_id, ie in inv_delta])

    def id2path(self, file_id):
        if file_id in self._new_info_by_id:
            new_path = self._new_info_by_id[file_id][0]
            if new_path is None:
                raise errors.NoSuchId(self, file_id)
            return new_path
        return self._basis_inv.id2path(file_id)

    def path2id(self, path):
        # CommitBuilder currently only requires access to the root id. We don't
        # build a map of renamed files, etc. One possibility if we ever *do*
        # need more than just root, is to defer to basis_inv.path2id() and then
        # check if the file_id is in our _new_info_by_id dict. And in that
        # case, return _new_info_by_id[file_id][0]
        if path != '':
            raise NotImplementedError(_TreeShim.path2id)
        # TODO: Handle root renames?
        return self._basis_inv.root.file_id

    def get_file_with_stat(self, path, file_id=None):
        content = self.get_file_text(path, file_id)
        sio = BytesIO(content)
        return sio, None

    def get_file_text(self, path, file_id=None):
        if file_id is None:
            file_id = self.path2id(path)
        try:
            return self._content_provider(file_id)
        except KeyError:
            # The content wasn't shown as 'new'. Just validate this fact
            assert file_id not in self._new_info_by_id
            old_ie = self._basis_inv.get_entry(file_id)
            old_text_key = (file_id, old_ie.revision)
            stream = self._repo.texts.get_record_stream([old_text_key],
                                                        'unordered', True)
            return next(stream).get_bytes_as('fulltext')

    def get_symlink_target(self, path, file_id=None):
        if file_id is None:
            file_id = self.path2id(path)
        if file_id in self._new_info_by_id:
            ie = self._new_info_by_id[file_id][1]
            return ie.symlink_target
        return self._basis_inv.get_entry(file_id).symlink_target

    def get_reference_revision(self, path, file_id=None):
        raise NotImplementedError(_TreeShim.get_reference_revision)

    def _delta_to_iter_changes(self):
        """Convert the inv_delta into an iter_changes repr."""
        # iter_changes is:
        #   (file_id,
        #    (old_path, new_path),
        #    content_changed,
        #    (old_versioned, new_versioned),
        #    (old_parent_id, new_parent_id),
        #    (old_name, new_name),
        #    (old_kind, new_kind),
        #    (old_exec, new_exec),
        #   )
        basis_inv = self._basis_inv
        for old_path, new_path, file_id, ie in self._inv_delta:
            # Perf: Would this be faster if we did 'if file_id in basis_inv'?
            # Since the *very* common case is that the file already exists, it
            # probably is better to optimize for that
            try:
                old_ie = basis_inv.get_entry(file_id)
            except errors.NoSuchId:
                old_ie = None
                if ie is None:
                    raise AssertionError('How is both old and new None?')
                    change = (file_id,
                        (old_path, new_path),
                        False,
                        (False, False),
                        (None, None),
                        (None, None),
                        (None, None),
                        (None, None),
                        )
                change = (file_id,
                    (old_path, new_path),
                    True,
                    (False, True),
                    (None, ie.parent_id),
                    (None, ie.name),
                    (None, ie.kind),
                    (None, ie.executable),
                    )
            else:
                if ie is None:
                    change = (file_id,
                        (old_path, new_path),
                        True,
                        (True, False),
                        (old_ie.parent_id, None),
                        (old_ie.name, None),
                        (old_ie.kind, None),
                        (old_ie.executable, None),
                        )
                else:
                    content_modified = (ie.text_sha1 != old_ie.text_sha1
                                        or ie.text_size != old_ie.text_size)
                    # TODO: ie.kind != old_ie.kind
                    # TODO: symlinks changing targets, content_modified?
                    change = (file_id,
                        (old_path, new_path),
                        content_modified,
                        (True, True),
                        (old_ie.parent_id, ie.parent_id),
                        (old_ie.name, ie.name),
                        (old_ie.kind, ie.kind),
                        (old_ie.executable, ie.executable),
                        )
            yield change


class RevisionStore(object):

    def __init__(self, repo):
        """An object responsible for loading revisions into a repository.

        NOTE: Repository locking is not managed by this class. Clients
        should take a write lock, call load() multiple times, then release
        the lock.

        :param repository: the target repository
        """
        self.repo = repo
        self._graph = None
        self._use_known_graph = True
        self._supports_chks = getattr(repo._format, 'supports_chks', False)

    def expects_rich_root(self):
        """Does this store expect inventories with rich roots?"""
        return self.repo.supports_rich_root()

    def init_inventory(self, revision_id):
        """Generate an inventory for a parentless revision."""
        if self._supports_chks:
            inv = self._init_chk_inventory(revision_id, inventory.ROOT_ID)
        else:
            inv = inventory.Inventory(revision_id=revision_id)
            if self.expects_rich_root():
                # The very first root needs to have the right revision
                inv.root.revision = revision_id
        return inv

    def _init_chk_inventory(self, revision_id, root_id):
        """Generate a CHKInventory for a parentless revision."""
        from ...bzr import chk_map
        # Get the creation parameters
        chk_store = self.repo.chk_bytes
        serializer = self.repo._format._serializer
        search_key_name = serializer.search_key_name
        maximum_size = serializer.maximum_size

        # Maybe the rest of this ought to be part of the CHKInventory API?
        inv = inventory.CHKInventory(search_key_name)
        inv.revision_id = revision_id
        inv.root_id = root_id
        search_key_func = chk_map.search_key_registry.get(search_key_name)
        inv.id_to_entry = chk_map.CHKMap(chk_store, None, search_key_func)
        inv.id_to_entry._root_node.set_maximum_size(maximum_size)
        inv.parent_id_basename_to_file_id = chk_map.CHKMap(chk_store,
            None, search_key_func)
        inv.parent_id_basename_to_file_id._root_node.set_maximum_size(
            maximum_size)
        inv.parent_id_basename_to_file_id._root_node._key_width = 2
        return inv

    def get_inventory(self, revision_id):
        """Get a stored inventory."""
        return self.repo.get_inventory(revision_id)

    def get_file_text(self, revision_id, file_id):
        """Get the text stored for a file in a given revision."""
        revtree = self.repo.revision_tree(revision_id)
        path = revtree.id2path(file_id)
        return revtree.get_file_text(path, file_id)

    def get_file_lines(self, revision_id, file_id):
        """Get the lines stored for a file in a given revision."""
        revtree = self.repo.revision_tree(revision_id)
        path = revtree.id2path(file_id)
        return osutils.split_lines(revtree.get_file_text(path, file_id))

    def start_new_revision(self, revision, parents, parent_invs):
        """Init the metadata needed for get_parents_and_revision_for_entry().

        :param revision: a Revision object
        """
        self._current_rev_id = revision.revision_id
        self._rev_parents = parents
        self._rev_parent_invs = parent_invs
        # We don't know what the branch will be so there's no real BranchConfig.
        # That means we won't be triggering any hooks and that's a good thing.
        # Without a config though, we must pass in the committer below so that
        # the commit builder doesn't try to look up the config.
        config = None
        # We can't use self.repo.get_commit_builder() here because it starts a
        # new write group. We want one write group around a batch of imports
        # where the default batch size is currently 10000. IGC 20090312
        self._commit_builder = self.repo._commit_builder_class(self.repo,
            parents, config, timestamp=revision.timestamp,
            timezone=revision.timezone, committer=revision.committer,
            revprops=revision.properties, revision_id=revision.revision_id)

    def get_parents_and_revision_for_entry(self, ie):
        """Get the parents and revision for an inventory entry.

        :param ie: the inventory entry
        :return parents, revision_id where
            parents is the tuple of parent revision_ids for the per-file graph
            revision_id is the revision_id to use for this entry
        """
        # Check for correct API usage
        if self._current_rev_id is None:
            raise AssertionError("start_new_revision() must be called"
                " before get_parents_and_revision_for_entry()")
        if ie.revision != self._current_rev_id:
            raise AssertionError("start_new_revision() registered a different"
                " revision (%s) to that in the inventory entry (%s)" %
                (self._current_rev_id, ie.revision))

        # Find the heads. This code is lifted from
        # repository.CommitBuilder.record_entry_contents().
        parent_candidate_entries = ie.parent_candidates(self._rev_parent_invs)
        head_set = self._commit_builder._heads(ie.file_id,
            list(parent_candidate_entries))
        heads = []
        for inv in self._rev_parent_invs:
            try:
                old_rev = inv.get_entry(ie.file_id).revision
            except errors.NoSuchId:
                pass
            else:
                if old_rev in head_set:
                    rev_id = inv.get_entry(ie.file_id).revision
                    heads.append(rev_id)
                    head_set.remove(rev_id)

        # Find the revision to use. If the content has not changed
        # since the parent, record the parent's revision.
        if len(heads) == 0:
            return (), ie.revision
        parent_entry = parent_candidate_entries[heads[0]]
        changed = False
        if len(heads) > 1:
            changed = True
        elif (parent_entry.name != ie.name or parent_entry.kind != ie.kind or
            parent_entry.parent_id != ie.parent_id):
            changed = True
        elif ie.kind == 'file':
            if (parent_entry.text_sha1 != ie.text_sha1 or
                parent_entry.executable != ie.executable):
                changed = True
        elif ie.kind == 'symlink':
            if parent_entry.symlink_target != ie.symlink_target:
                changed = True
        if changed:
            rev_id = ie.revision
        else:
            rev_id = parent_entry.revision
        return tuple(heads), rev_id

    def load_using_delta(self, rev, basis_inv, inv_delta, signature,
        text_provider, parents_provider, inventories_provider=None):
        """Load a revision by applying a delta to a (CHK)Inventory.

        :param rev: the Revision
        :param basis_inv: the basis Inventory or CHKInventory
        :param inv_delta: the inventory delta
        :param signature: signing information
        :param text_provider: a callable expecting a file_id parameter
            that returns the text for that file-id
        :param parents_provider: a callable expecting a file_id parameter
            that return the list of parent-ids for that file-id
        :param inventories_provider: a callable expecting a repository and
            a list of revision-ids, that returns:
              * the list of revision-ids present in the repository
              * the list of inventories for the revision-id's,
                including an empty inventory for the missing revisions
            If None, a default implementation is provided.
        """
        # TODO: set revision_id = rev.revision_id
        builder = self.repo._commit_builder_class(self.repo,
            parents=rev.parent_ids, config=None, timestamp=rev.timestamp,
            timezone=rev.timezone, committer=rev.committer,
            revprops=rev.properties, revision_id=rev.revision_id)
        if self._graph is None and self._use_known_graph:
            if (getattr(_mod_graph, 'GraphThunkIdsToKeys', None) and
                getattr(_mod_graph.GraphThunkIdsToKeys, "add_node", None) and
                getattr(self.repo, "get_known_graph_ancestry", None)):
                self._graph = self.repo.get_known_graph_ancestry(
                    rev.parent_ids)
            else:
                self._use_known_graph = False
        if self._graph is not None:
            orig_heads = builder._heads
            def thunked_heads(file_id, revision_ids):
                # self._graph thinks in terms of keys, not ids, so translate
                # them
                # old_res = orig_heads(file_id, revision_ids)
                if len(revision_ids) < 2:
                    res = set(revision_ids)
                else:
                    res = set(self._graph.heads(revision_ids))
                # if old_res != res:
                #     import pdb; pdb.set_trace()
                return res
            builder._heads = thunked_heads

        if rev.parent_ids:
            basis_rev_id = rev.parent_ids[0]
        else:
            basis_rev_id = _mod_revision.NULL_REVISION
        tree = _TreeShim(self.repo, basis_inv, inv_delta, text_provider)
        changes = tree._delta_to_iter_changes()
        for (file_id, path, fs_hash) in builder.record_iter_changes(
                tree, basis_rev_id, changes):
            # So far, we don't *do* anything with the result
            pass
        builder.finish_inventory()
        # TODO: This is working around a bug in the breezy code base.
        # 'builder.finish_inventory()' ends up doing:
        # self.inv_sha1 = self.repository.add_inventory_by_delta(...)
        # However, add_inventory_by_delta returns (sha1, inv)
        # And we *want* to keep a handle on both of those objects
        if isinstance(builder.inv_sha1, tuple):
            builder.inv_sha1, builder.new_inventory = builder.inv_sha1
        # This is a duplicate of Builder.commit() since we already have the
        # Revision object, and we *don't* want to call commit_write_group()
        rev.inv_sha1 = builder.inv_sha1
        config = builder._config_stack
        builder.repository.add_revision(builder._new_revision_id, rev,
            builder.revision_tree().root_inventory)
        if self._graph is not None:
            # TODO: Use StaticTuple and .intern() for these things
            self._graph.add_node(builder._new_revision_id, rev.parent_ids)

        if signature is not None:
            raise AssertionError('signatures not guaranteed yet')
            self.repo.add_signature_text(rev.revision_id, signature)
        # self._add_revision(rev, inv)
        return builder.revision_tree().root_inventory

    def _non_root_entries_iter(self, inv, revision_id):
        if hasattr(inv, 'iter_non_root_entries'):
            entries = inv.iter_non_root_entries()
        else:
            path_entries = inv.iter_entries()
            # Backwards compatibility hack: skip the root id.
            if not self.repo.supports_rich_root():
                path, root = next(path_entries)
                if root.revision != revision_id:
                    raise errors.IncompatibleRevision(repr(self.repo))
            entries = iter([ie for path, ie in path_entries])
        return entries

    def _add_inventory(self, revision_id, inv, parents, parent_invs):
        """Add the inventory inv to the repository as revision_id.
        
        :param parents: The revision ids of the parents that revision_id
                        is known to have and are in the repository already.
        :param parent_invs: the parent inventories

        :returns: The validator(which is a sha1 digest, though what is sha'd is
            repository format specific) of the serialized inventory.
        """
        return self.repo.add_inventory(revision_id, inv, parents)

    def _add_inventory_by_delta(self, revision_id, basis_inv, inv_delta,
        parents, parent_invs):
        """Add the inventory to the repository as revision_id.
        
        :param basis_inv: the basis Inventory or CHKInventory
        :param inv_delta: the inventory delta
        :param parents: The revision ids of the parents that revision_id
                        is known to have and are in the repository already.
        :param parent_invs: the parent inventories

        :returns: (validator, inv) where validator is the validator
          (which is a sha1 digest, though what is sha'd is repository format
          specific) of the serialized inventory;
          inv is the generated inventory
        """
        if len(parents):
            if self._supports_chks:
                try:
                    validator, new_inv = self.repo.add_inventory_by_delta(parents[0],
                        inv_delta, revision_id, parents, basis_inv=basis_inv,
                        propagate_caches=False)
                except errors.InconsistentDelta:
                    #print "BASIS INV IS\n%s\n" % "\n".join([str(i) for i in basis_inv.iter_entries_by_dir()])
                    trace.mutter("INCONSISTENT DELTA IS:\n%s\n" % "\n".join([str(i) for i in inv_delta]))
                    raise
            else:
                validator, new_inv = self.repo.add_inventory_by_delta(parents[0],
                    inv_delta, revision_id, parents)
        else:
            if isinstance(basis_inv, inventory.CHKInventory):
                new_inv = basis_inv.create_by_apply_delta(inv_delta, revision_id)
            else:
                new_inv = inventory.Inventory(revision_id=revision_id)
                # This is set in the delta so remove it to prevent a duplicate
                new_inv.delete(inventory.ROOT_ID)
                new_inv.apply_delta(inv_delta)
            validator = self.repo.add_inventory(revision_id, new_inv, parents)
        return validator, new_inv

    def _add_revision(self, rev, inv):
        """Add a revision and its inventory to a repository.

        :param rev: the Revision
        :param inv: the inventory
        """
        self.repo.add_revision(rev.revision_id, rev, inv)

    def _default_inventories_provider(self, revision_ids):
        """An inventories provider that queries the repository."""
        present = []
        inventories = []
        for revision_id in revision_ids:
            if self.repo.has_revision(revision_id):
                present.append(revision_id)
                rev_tree = self.repo.revision_tree(revision_id)
            else:
                rev_tree = self.repo.revision_tree(None)
            inventories.append(rev_tree.root_inventory)
        return present, inventories

    def _load_texts(self, revision_id, entries, text_provider, parents_provider):
        """Load texts to a repository for inventory entries.

        This method is provided for subclasses to use or override.

        :param revision_id: the revision identifier
        :param entries: iterator over the inventory entries
        :param text_provider: a callable expecting a file_id parameter
            that returns the text for that file-id
        :param parents_provider: a callable expecting a file_id parameter
            that return the list of parent-ids for that file-id
        """
        text_keys = {}
        for ie in entries:
            text_keys[(ie.file_id, ie.revision)] = ie
        text_parent_map = self.repo.texts.get_parent_map(text_keys)
        missing_texts = set(text_keys) - set(text_parent_map)
        for file_id, revision_id in missing_texts:
            text_key = (file_id, revision_id)
            text_parents = [(file_id, p) for p in parents_provider(file_id)]
            lines = text_provider(file_id)
            #print "adding text for %s\n\tparents:%s" % (text_key,text_parents)
            self.repo.texts.add_lines(text_key, text_parents, lines)

    def get_file_lines(self, revision_id, file_id):
        record = next(self.repo.texts.get_record_stream([(file_id, revision_id)],
            'unordered', True))
        if record.storage_kind == 'absent':
            raise errors.RevisionNotPresent(record.key, self.repo)
        return osutils.split_lines(record.get_bytes_as('fulltext'))

    # This is breaking imports into brisbane-core currently
    #def _add_revision(self, rev, inv):
    #    # There's no need to do everything repo.add_revision does and
    #    # doing so (since bzr.dev 3392) can be pretty slow for long
    #    # delta chains on inventories. Just do the essentials here ...
    #    _mod_revision.check_not_reserved_id(rev.revision_id)
    #    self.repo._add_revision(rev)
