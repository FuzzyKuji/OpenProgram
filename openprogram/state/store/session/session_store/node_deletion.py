"""SessionStore node deletion: remove single DAG nodes, splice, undo.

Deleting a node removes it and splices whatever followed it onto its
predecessor, the way deleting a box in a diagram leaves its neighbours
in place. The pieces a node owns go with it: everything hung off it by
``caller`` (a reply's tool calls, a call's sub-calls, the agent branch a
call spawned). What merely came after it in the conversation stays and
moves up.

Nothing is unlinked at once. The node files move to a trash folder
outside the session repo together with a journal of every edge, HEAD
and branch-name change, so ``restore_deleted_nodes`` can put the graph
back exactly. Trash older than ``TRASH_TTL`` is purged on the next
delete in the same store.
"""
from __future__ import annotations

import os
import shutil

from . import shared

TRASH_DIR = ".deleted-nodes"
TRASH_TTL = 24 * 3600
_ANY = object()


class NodeDeletionError(ValueError):
    """The request names a node that cannot be deleted."""


class NodeDeletionOperations:
    def _trash_root(self, session_id: str) -> shared.Path:
        return self.root_path / TRASH_DIR / session_id

    def _purge_trash(self) -> None:
        root = self.root_path / TRASH_DIR
        if not root.is_dir():
            return
        cutoff = shared.time.time() - TRASH_TTL
        for sess in root.iterdir():
            if not sess.is_dir():
                continue
            for op in sess.iterdir():
                try:
                    if op.stat().st_mtime < cutoff:
                        shutil.rmtree(op, ignore_errors=True)
                except OSError:
                    pass

    def delete_nodes(self, session_id: str, node_ids: list[str]) -> dict:
        """Delete ``node_ids``, splice their successors, return the journal.

        Raises ``NodeDeletionError`` when a node is missing or is
        structure rather than content: the ROOT, a spawn-branch root (its
        caller call owns it), a compaction summary, or merge/attach
        machinery.
        """
        targets = [n for n in dict.fromkeys(node_ids or []) if n]
        if not targets:
            raise NodeDeletionError("no nodes to delete")
        self._purge_trash()
        with self._session_lock(session_id):
            pair = self._open(session_id)
            if pair is None:
                raise NodeDeletionError(f"unknown session {session_id!r}")
            git, idx = pair
            with self._head_file_lock(git):
                return self._delete_locked(session_id, git, idx, targets)

    def _delete_locked(self, session_id, git, idx, targets) -> dict:
        nodes = idx.nodes_by_id
        for nid in targets:
            node = nodes.get(nid)
            if node is None:
                raise NodeDeletionError(f"unknown node {nid!r}")
            md = node.metadata or {}
            if md.get("display") == "root":
                raise NodeDeletionError("the root cannot be deleted")
            if shared._is_spawn_root(md):
                raise NodeDeletionError(
                    f"{nid!r} opens an agent branch; delete the call that spawned it")
            if md.get("covers_ids") is not None:
                raise NodeDeletionError(f"{nid!r} is a compaction summary")
            if md.get("function") in ("attach", "merge"):
                raise NodeDeletionError(f"{nid!r} is {md.get('function')} machinery")

        # Everything a target owns goes with it: its caller subtree, and
        # for each owned node (not the targets themselves) its
        # conversation successors too — an agent branch under a call is
        # that call's work, not the next turn.
        doomed: dict[str, None] = dict.fromkeys(targets)
        stack = list(targets)
        while stack:
            cur = stack.pop()
            kids = list(idx.children_by_caller.get(cur, []))
            if cur not in targets:
                kids += idx.children_by_predecessor.get(cur, [])
            for kid in kids:
                if kid not in doomed and kid in nodes:
                    doomed[kid] = None
                    stack.append(kid)

        def survivor_above(nid):
            """Nearest predecessor of ``nid`` that survives (or None)."""
            seen: set = set()
            cur = nid
            while cur and cur in doomed and cur not in seen:
                seen.add(cur)
                cur = shared._node_conv_predecessor(nodes[cur]) if cur in nodes else None
            return cur if cur not in doomed else None

        reparented = []
        for nid, node in list(nodes.items()):
            if nid in doomed:
                continue
            pred = shared._node_conv_predecessor(node)
            if pred and pred in doomed:
                reparented.append({"id": nid, "old": pred, "new": survivor_above(pred)})

        old_head = idx.head_id
        new_head = survivor_above(old_head) if old_head in doomed else old_head

        branches = dict(idx.meta.get("branches") or {})
        branch_moves = []
        for nid in doomed:
            if nid not in branches:
                continue
            entry = branches.pop(nid)
            to = survivor_above(nid)
            if to is not None and to not in branches:
                branches[to] = entry
            else:
                to = None
            branch_moves.append({"from": nid, "to": to, "entry": entry})

        op_id = shared.uuid.uuid4().hex[:12]
        trash = self._trash_root(session_id) / op_id
        (trash / "history").mkdir(parents=True, exist_ok=True)
        hist = git.path / "history"
        moved = []
        for nid in doomed:
            for fpath in hist.glob(f"*-{nid}.json"):
                os.replace(fpath, trash / "history" / fpath.name)
                moved.append(fpath.name)
        for row in reparented:
            self._rewrite_predecessor(hist, row["id"], row["new"])

        journal = {
            "op_id": op_id,
            "session_id": session_id,
            "created_at": shared.time.time(),
            "targets": targets,
            "deleted": list(doomed),
            "files": moved,
            "reparented": reparented,
            "head": {"old": old_head, "new": new_head},
            "branch_moves": branch_moves,
        }
        shared.atomic_write_text(
            trash / "journal.json",
            shared.json.dumps(journal, ensure_ascii=False, default=str))

        meta = dict(idx.meta)
        meta["branches"] = branches
        meta["head_id"] = new_head
        self._commit_rebuild(git, idx, meta)
        if new_head is None and old_head in doomed:
            tips = self.list_branches(session_id)
            if tips:
                meta = dict(idx.meta)
                meta["head_id"] = tips[0]["head_msg_id"]
                journal["head"]["new"] = meta["head_id"]
                shared.atomic_write_text(
                    trash / "journal.json",
                    shared.json.dumps(journal, ensure_ascii=False, default=str))
                self._commit_rebuild(git, idx, meta)
        return journal

    def restore_deleted_nodes(self, session_id: str, op_id: str) -> dict:
        """Undo ``delete_nodes`` op ``op_id``; returns its journal.

        Edges and HEAD are restored only where nothing has moved them
        since: a successor that was re-pointed again, or a HEAD the user
        moved on from, keeps its newer value.
        """
        if not op_id or "/" in op_id or op_id.startswith("."):
            raise NodeDeletionError(f"unknown delete {op_id!r}")
        trash = self._trash_root(session_id) / op_id
        jpath = trash / "journal.json"
        if not jpath.is_file():
            raise NodeDeletionError(f"unknown delete {op_id!r}")
        journal = shared.json.loads(jpath.read_text(encoding="utf-8"))
        with self._session_lock(session_id):
            pair = self._open(session_id)
            if pair is None:
                raise NodeDeletionError(f"unknown session {session_id!r}")
            git, idx = pair
            with self._head_file_lock(git):
                hist = git.path / "history"
                hist.mkdir(parents=True, exist_ok=True)
                for name in journal.get("files") or []:
                    src = trash / "history" / name
                    if src.is_file() and not (hist / name).exists():
                        os.replace(src, hist / name)
                for row in journal.get("reparented") or []:
                    self._rewrite_predecessor(
                        hist, row["id"], row["old"], only_if=row["new"])
                meta = dict(idx.meta)
                meta["head_id"] = idx.head_id
                head = journal.get("head") or {}
                if meta["head_id"] == head.get("new"):
                    meta["head_id"] = head.get("old")
                branches = dict(meta.get("branches") or {})
                for move in journal.get("branch_moves") or []:
                    to = move.get("to")
                    if to and branches.get(to) == move.get("entry"):
                        branches.pop(to)
                    branches.setdefault(move["from"], move.get("entry"))
                meta["branches"] = branches
                self._commit_rebuild(git, idx, meta)
        shutil.rmtree(trash, ignore_errors=True)
        return journal

    def _rewrite_predecessor(self, hist, node_id, value, *, only_if=_ANY) -> None:
        """Point ``node_id``'s history file at ``value``; with ``only_if``,
        only while it still points where this op left it."""
        for fpath in hist.glob(f"*-{node_id}.json"):
            try:
                payload = shared.json.loads(fpath.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if only_if is not _ANY and payload.get("predecessor") != only_if:
                continue
            payload["predecessor"] = value
            shared.atomic_write_text(
                fpath, shared.json.dumps(payload, ensure_ascii=False, default=str))

    def _commit_rebuild(self, git, idx, meta: dict) -> None:
        """Write ``meta`` and rebuild the index from the history on disk."""
        with idx._persist_lock:
            git.write_meta(meta)
            idx.rebuild_from_paths(
                git.list_history(), meta,
                shared._node_conv_predecessor, shared._node_caller,
            )
            git.mark_synced()

