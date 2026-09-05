import asyncio
import time
import random
import logging
from enum import Enum

logger = logging.getLogger(__name__)

class RaftState(Enum):
    FOLLOWER = "FOLLOWER"
    CANDIDATE = "CANDIDATE"
    LEADER = "LEADER"

class RaftNode:
    def __init__(self, node_id: str, peers: list[str]):
        self.node_id = node_id
        self.peers = peers
        self.state = RaftState.FOLLOWER
        self.current_term = 0
        self.voted_for = None
        self.log = []
        self.commit_index = 0
        self.last_applied = 0
        
        self.election_timeout = self._random_timeout()
        self.last_heartbeat = time.time()
        self._running = False
        self._task = None

    def _random_timeout(self):
        return random.uniform(1.5, 3.0)

    def start(self):
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._run_loop())
            logger.info(f"RaftNode {self.node_id} started as {self.state.value}")

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    async def _run_loop(self):
        while self._running:
            now = time.time()
            if self.state in [RaftState.FOLLOWER, RaftState.CANDIDATE]:
                if now - self.last_heartbeat > self.election_timeout:
                    self._start_election()
            elif self.state == RaftState.LEADER:
                self._send_heartbeats()
                
            await asyncio.sleep(0.1)

    def _start_election(self):
        self.state = RaftState.CANDIDATE
        self.current_term += 1
        self.voted_for = self.node_id
        self.election_timeout = self._random_timeout()
        self.last_heartbeat = time.time()
        logger.info(f"RaftNode {self.node_id} starting election for term {self.current_term}")
        # In a real implementation, we would send RequestVote RPCs to peers here.
        # Since this is a basic simulation, we'll assume victory if no peers exist.
        if not self.peers:
            self._become_leader()

    def _become_leader(self):
        self.state = RaftState.LEADER
        logger.info(f"RaftNode {self.node_id} became LEADER for term {self.current_term}")

    def _send_heartbeats(self):
        # In a real implementation, we would send AppendEntries RPCs as heartbeats.
        # Here we just log it periodically to avoid spam.
        pass

    def handle_request_vote(self, term: int, candidate_id: str, last_log_index: int, last_log_term: int) -> dict:
        if term > self.current_term:
            self.current_term = term
            self.state = RaftState.FOLLOWER
            self.voted_for = None
            
        vote_granted = False
        if term == self.current_term and (self.voted_for is None or self.voted_for == candidate_id):
            vote_granted = True
            self.voted_for = candidate_id
            self.last_heartbeat = time.time()
            
        return {"term": self.current_term, "vote_granted": vote_granted}

    def handle_heartbeat(self, term: int, leader_id: str) -> dict:
        if term >= self.current_term:
            self.current_term = term
            self.state = RaftState.FOLLOWER
            self.last_heartbeat = time.time()
            return {"term": self.current_term, "success": True}
        return {"term": self.current_term, "success": False}

# Singleton for the server instance
raft_node = RaftNode("server-node", [])
