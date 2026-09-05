"""
core/branch_engine.py
Git-style Node Branching Engine for CacheSplit v4.
Provides multi-developer branch isolation, commits, push, pull, restore/rollback,
diffing, and three-way OCC merging on individual nodes or across the cluster.
"""
import time
import uuid
import copy
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

from core.merkle_dag import MerkleDAG, EntityNode
from core.compound_commit import CompoundCommit, EntityMutation, RelationshipEdge

logger = logging.getLogger(__name__)


@dataclass
class BranchCommit:
    commit_id: str
    branch_name: str
    node_id: str
    developer_id: str
    message: str
    parent_commit_id: Optional[str]
    merkle_root: str
    mutations: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    timestamp: float = field(default_factory=time.time)


@dataclass
class NodeBranch:
    branch_name: str
    node_id: str
    head_commit_id: Optional[str]
    merkle_root: str
    developer_id: str
    created_at: float = field(default_factory=time.time)
    parent_branch: str = "main"


class BranchEngine:
    """
    Manages Git-style branching per node.
    Enables concurrent developer workflows with isolated Merkle DAGs,
    pull/push operations, commit histories, rollback/restore, and OCC merging.
    """

    def __init__(self, node_id: str, base_dag: Optional[MerkleDAG] = None):
        self.node_id = node_id
        # Branch name -> MerkleDAG snapshot
        self._dags: Dict[str, MerkleDAG] = {}
        # Branch name -> NodeBranch metadata
        self._branches: Dict[str, NodeBranch] = {}
        # Commit ID -> BranchCommit
        self._commits: Dict[str, BranchCommit] = {}
        # Branch name -> list of commit IDs in order
        self._branch_history: Dict[str, List[str]] = {}

        # Initialize default 'main' branch
        main_dag = copy.deepcopy(base_dag) if base_dag else MerkleDAG()
        genesis_root = main_dag.compute_root_hash() if main_dag.entities else "genesis"


        self._dags["main"] = main_dag
        self._branches["main"] = NodeBranch(
            branch_name="main",
            node_id=self.node_id,
            head_commit_id=None,
            merkle_root=genesis_root,
            developer_id="system",
            parent_branch="main",
        )
        self._branch_history["main"] = []

    # ── Branch Lifecycle ──────────────────────────────────────────────────────

    def create_branch(
        self,
        branch_name: str,
        developer_id: str = "dev",
        from_branch: str = "main",
    ) -> NodeBranch:
        """Create a new isolated branch cloned from `from_branch`."""
        if branch_name in self._branches:
            raise ValueError(f"Branch '{branch_name}' already exists on node '{self.node_id}'")
        if from_branch not in self._branches:
            raise ValueError(f"Source branch '{from_branch}' does not exist on node '{self.node_id}'")

        parent_dag = self._dags[from_branch]
        cloned_dag = copy.deepcopy(parent_dag)

        branch = NodeBranch(
            branch_name=branch_name,
            node_id=self.node_id,
            head_commit_id=self._branches[from_branch].head_commit_id,
            merkle_root=cloned_dag.compute_root_hash(),
            developer_id=developer_id,
            parent_branch=from_branch,
        )

        self._dags[branch_name] = cloned_dag
        self._branches[branch_name] = branch
        self._branch_history[branch_name] = list(self._branch_history.get(from_branch, []))

        logger.info(f"BranchEngine [{self.node_id}]: Created branch '{branch_name}' from '{from_branch}'")
        return branch

    def list_branches(self) -> List[Dict[str, Any]]:
        """List all branches on this node."""
        return [
            {
                "branch_name": b.branch_name,
                "node_id": b.node_id,
                "head_commit_id": b.head_commit_id,
                "merkle_root": b.merkle_root,
                "developer_id": b.developer_id,
                "created_at": b.created_at,
                "parent_branch": b.parent_branch,
                "commit_count": len(self._branch_history.get(b.branch_name, [])),
            }
            for b in self._branches.values()
        ]

    def get_dag(self, branch_name: str = "main") -> MerkleDAG:
        if branch_name not in self._dags:
            raise ValueError(f"Branch '{branch_name}' not found")
        return self._dags[branch_name]

    # ── Git Commit ────────────────────────────────────────────────────────────

    def commit(
        self,
        branch_name: str,
        mutations: List[Dict[str, Any]],
        edges: Optional[List[Dict[str, Any]]] = None,
        developer_id: str = "dev",
        message: str = "Compound commit",
    ) -> BranchCommit:
        """
        Apply mutations to the branch DAG and record a new commit in its history.
        """
        if branch_name not in self._dags:
            raise ValueError(f"Branch '{branch_name}' not found on node '{self.node_id}'")

        dag = self._dags[branch_name]
        parent_commit_id = self._branches[branch_name].head_commit_id

        # Apply mutations to this branch's DAG
        for m in mutations:
            entity_id = m["entity_id"]
            entity_type = m.get("entity_type", "generic")
            data = m.get("data", {})
            existing = dag.get_entity(entity_id)
            if existing:
                existing.data.update(data)
                existing.version += 1
                existing.compute_local_hash()
            else:
                new_node = EntityNode(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    data=data,
                    version=1,
                    region=self.node_id,
                )
                dag.add_entity(new_node)

        # Apply relationship edges
        for e in (edges or []):
            dag.add_edge(e["from_entity_id"], e["to_entity_id"], e.get("relationship_type", "RELATED_TO"))

        # Re-compute Merkle root after mutations
        new_root = dag.compute_root_hash()
        commit_id = f"commit-{uuid.uuid4().hex[:8]}"

        commit_obj = BranchCommit(
            commit_id=commit_id,
            branch_name=branch_name,
            node_id=self.node_id,
            developer_id=developer_id,
            message=message,
            parent_commit_id=parent_commit_id,
            merkle_root=new_root,
            mutations=mutations,
            edges=edges or [],
        )

        self._commits[commit_id] = commit_obj
        self._branches[branch_name].head_commit_id = commit_id
        self._branches[branch_name].merkle_root = new_root
        self._branch_history[branch_name].append(commit_id)

        logger.info(f"BranchEngine [{self.node_id}:{branch_name}]: Commit {commit_id} - '{message}' (Root: {new_root[:10]}...)")
        return commit_obj

    # ── Git Push & Pull ───────────────────────────────────────────────────────

    def push(self, source_branch: str, target_branch: str = "main") -> Dict[str, Any]:
        """
        Fast-forward or merge source branch into target branch.
        """
        if source_branch not in self._branches:
            raise ValueError(f"Source branch '{source_branch}' not found")
        if target_branch not in self._branches:
            raise ValueError(f"Target branch '{target_branch}' not found")

        source_dag = self._dags[source_branch]
        target_dag = self._dags[target_branch]

        # Sync all entities from source into target
        for eid, entity in source_dag.entities.items():
            target_dag.entities[eid] = copy.deepcopy(entity)
        target_dag.edges = copy.deepcopy(source_dag.edges)


        new_root = target_dag.compute_root_hash()
        push_commit_id = f"push-{uuid.uuid4().hex[:8]}"

        push_commit = BranchCommit(
            commit_id=push_commit_id,
            branch_name=target_branch,
            node_id=self.node_id,
            developer_id=self._branches[source_branch].developer_id,
            message=f"Pushed branch '{source_branch}' into '{target_branch}'",
            parent_commit_id=self._branches[target_branch].head_commit_id,
            merkle_root=new_root,
            mutations=[],
            edges=[],
        )

        self._commits[push_commit_id] = push_commit
        self._branches[target_branch].head_commit_id = push_commit_id
        self._branches[target_branch].merkle_root = new_root
        self._branch_history[target_branch].append(push_commit_id)

        return {
            "status": "pushed",
            "source_branch": source_branch,
            "target_branch": target_branch,
            "new_merkle_root": new_root,
            "commit_id": push_commit_id,
        }

    def pull(self, branch_name: str, from_branch: str = "main") -> Dict[str, Any]:
        """
        Pull updates from `from_branch` into `branch_name`.
        """
        if branch_name not in self._branches or from_branch not in self._branches:
            raise ValueError("Invalid branch specified for pull")

        return self.push(source_branch=from_branch, target_branch=branch_name)

    # ── Git Restore / Rollback ────────────────────────────────────────────────

    def restore(self, branch_name: str, commit_id: str) -> Dict[str, Any]:
        """
        Restore/rollback a branch to a specific historical commit state.
        Reconstructs the DAG up to that commit.
        """
        if branch_name not in self._branches:
            raise ValueError(f"Branch '{branch_name}' not found")
        if commit_id not in self._commits:
            raise ValueError(f"Commit '{commit_id}' not found")

        history = self._branch_history.get(branch_name, [])
        if commit_id not in history:
            raise ValueError(f"Commit '{commit_id}' is not in history of branch '{branch_name}'")

        target_idx = history.index(commit_id)
        # Re-play commits from genesis up to target_idx
        rebuilt_dag = MerkleDAG()
        for c_id in history[: target_idx + 1]:
            c = self._commits[c_id]
            for m in c.mutations:
                eid = m["entity_id"]
                data = m.get("data", {})
                ent = rebuilt_dag.get_entity(eid)
                if ent:
                    ent.data.update(data)
                    ent.version += 1
                    ent.compute_local_hash()
                else:
                    rebuilt_dag.add_entity(EntityNode(
                        entity_id=eid, entity_type=m.get("entity_type", "generic"),
                        data=data, version=1, region=self.node_id
                    ))
            for e in c.edges:
                rebuilt_dag.add_edge(e["from_entity_id"], e["to_entity_id"], e.get("relationship_type", "RELATED_TO"))

        self._dags[branch_name] = rebuilt_dag
        new_root = rebuilt_dag.compute_root_hash()
        self._branches[branch_name].head_commit_id = commit_id
        self._branches[branch_name].merkle_root = new_root
        self._branch_history[branch_name] = history[: target_idx + 1]

        logger.info(f"BranchEngine [{self.node_id}:{branch_name}]: Restored to commit {commit_id} (Root: {new_root[:10]}...)")
        return {
            "status": "restored",
            "branch_name": branch_name,
            "commit_id": commit_id,
            "merkle_root": new_root,
        }

    # ── Git Diff & Log ────────────────────────────────────────────────────────

    def diff(self, branch_a: str, branch_b: str) -> Dict[str, Any]:
        """Compare entities between two branches."""
        if branch_a not in self._dags or branch_b not in self._dags:
            raise ValueError("Both branches must exist to perform diff")

        dag_a = self._dags[branch_a]
        dag_b = self._dags[branch_b]

        added = [k for k in dag_b.entities if k not in dag_a.entities]
        removed = [k for k in dag_a.entities if k not in dag_b.entities]
        modified = []

        for k in dag_a.entities:
            if k in dag_b.entities:
                if dag_a.entities[k].local_hash != dag_b.entities[k].local_hash:
                    modified.append({
                        "entity_id": k,
                        "version_a": dag_a.entities[k].version,
                        "version_b": dag_b.entities[k].version,
                        "hash_a": dag_a.entities[k].local_hash,
                        "hash_b": dag_b.entities[k].local_hash,
                    })


        return {
            "branch_a": branch_a,
            "branch_b": branch_b,
            "merkle_root_a": self._branches[branch_a].merkle_root,
            "merkle_root_b": self._branches[branch_b].merkle_root,
            "is_identical": self._branches[branch_a].merkle_root == self._branches[branch_b].merkle_root,
            "added_in_b": added,
            "removed_in_b": removed,
            "modified": modified,
        }

    def log(self, branch_name: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Retrieve commit log for a branch."""
        history = self._branch_history.get(branch_name, [])
        commits = [self._commits[cid] for cid in reversed(history[-limit:]) if cid in self._commits]
        return [
            {
                "commit_id": c.commit_id,
                "branch_name": c.branch_name,
                "developer_id": c.developer_id,
                "message": c.message,
                "merkle_root": c.merkle_root,
                "timestamp": c.timestamp,
                "mutations_count": len(c.mutations),
            }
            for c in commits
        ]
