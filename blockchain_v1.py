# blockchain_v1.py
# Milestone 1: Minimal Blockchain with Proof-of-Work (educational, not production-safe)

from __future__ import annotations
import hashlib
import json
import time
from dataclasses import dataclass, asdict
from typing import List, Optional

# ---------------------------
# Utilities
# ---------------------------

def sha256_bytes(data: bytes) -> str:
    """Compute SHA-256 hex digest."""
    return hashlib.sha256(data).hexdigest()

def stable_json_hash(obj) -> str:
    """Hash a Python object deterministically by JSON-encoding with sorted keys."""
    return sha256_bytes(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode())

def merkle_root(items: List[str]) -> str:
    """
    Compute a simple Merkle root over a list of strings.
    - For an empty list, return hash of empty string.
    - For odd number of items per level, duplicate the last (Bitcoin-style).
    Note: This is a teaching Merkle; production chains include more fields & encodings.
    """
    if not items:
        return sha256_bytes(b"")
    level = [sha256_bytes(i.encode()) for i in items]
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            a = level[i]
            b = level[i + 1] if i + 1 < len(level) else a  # duplicate last if odd
            nxt.append(sha256_bytes((a + b).encode()))
        level = nxt
    return level[0]

# ---------------------------
# Core Data Structures
# ---------------------------

@dataclass
class BlockHeader:
    index: int
    prev_hash: str
    timestamp: int
    merkle_root: str
    difficulty: int
    nonce: int

    def to_dict(self):
        return asdict(self)

    def hash(self) -> str:
        return stable_json_hash(self.to_dict())

@dataclass
class Block:
    header: BlockHeader
    transactions: List[str]  # For Milestone 1, transactions are plain strings

    def to_dict(self):
        return {
            "header": self.header.to_dict(),
            "transactions": list(self.transactions),
        }

    def hash(self) -> str:
        return self.header.hash()

class Blockchain:
    def __init__(self, difficulty: int = 4):
        """
        difficulty: number of leading zeros required in block header hash (toy PoW).
        Start with small numbers (e.g., 3 or 4). Increase to make mining harder.
        """
        self.chain: List[Block] = []
        self.pending_txs: List[str] = []
        self.difficulty = difficulty
        self._create_genesis_block()

    # ---------------------------
    # Block / Chain Management
    # ---------------------------

    def _create_genesis_block(self):
        genesis_txs = ["GENESIS"]
        header = BlockHeader(
            index=0,
            prev_hash="0" * 64,
            timestamp=int(time.time()),
            merkle_root=merkle_root(genesis_txs),
            difficulty=self.difficulty,
            nonce=0,
        )
        # Mine the genesis block (optional, but shows consistency)
        mined_header = self._mine_header(header)
        genesis_block = Block(mined_header, genesis_txs)
        self.chain.append(genesis_block)

    def add_transaction(self, tx: str):
        """
        Milestone 1: tx is just a string like "Alice->Bob:5".
        (We will replace with a Transaction object in Milestone 2.)
        """
        if not isinstance(tx, str) or not tx.strip():
            raise ValueError("Transaction must be a non-empty string.")
        self.pending_txs.append(tx.strip())

    def mine_block(self) -> Block:
        """
        Create a new block from pending transactions and mine it.
        Returns the mined Block and clears the pending pool.
        """
        if not self.pending_txs:
            # Even if empty, some chains allow empty blocks; we’ll require at least 1.
            # Add a coinbase-like message for demonstration.
            self.pending_txs.append("SYSTEM:reward:0")

        index = len(self.chain)
        prev_hash = self.chain[-1].hash()
        txs = list(self.pending_txs)  # snapshot
        mroot = merkle_root(txs)
        header = BlockHeader(
            index=index,
            prev_hash=prev_hash,
            timestamp=int(time.time()),
            merkle_root=mroot,
            difficulty=self.difficulty,
            nonce=0,
        )
        mined_header = self._mine_header(header)
        block = Block(mined_header, txs)
        # Append and clear
        self.chain.append(block)
        self.pending_txs.clear()
        return block

    def _mine_header(self, header: BlockHeader) -> BlockHeader:
        """
        Toy Proof-of-Work: Find a nonce such that hash(header) starts with N zeros.
        """
        target_prefix = "0" * header.difficulty
        # Copy to avoid mutating the caller's header
        nonce = header.nonce
        while True:
            candidate = BlockHeader(
                index=header.index,
                prev_hash=header.prev_hash,
                timestamp=header.timestamp,
                merkle_root=header.merkle_root,
                difficulty=header.difficulty,
                nonce=nonce,
            )
            h = candidate.hash()
            if h.startswith(target_prefix):
                return candidate
            nonce += 1

    # ---------------------------
    # Validation
    # ---------------------------

    def is_valid_chain(self) -> bool:
        """
        Validate:
          - Hash linkage (prev_hash references previous block hash)
          - Header hash meets difficulty
          - Merkle root matches transactions
        """
        if not self.chain:
            return False

        for i, block in enumerate(self.chain):
            # Check PoW
            if not block.hash().startswith("0" * block.header.difficulty):
                return False

            # Check Merkle root
            if block.header.merkle_root != merkle_root(block.transactions):
                return False

            if i == 0:
                # Genesis checks
                if block.header.index != 0:
                    return False
                if block.header.prev_hash != "0" * 64:
                    return False
                continue

            prev = self.chain[i - 1]
            # Check linkage
            if block.header.prev_hash != prev.hash():
                return False
            # Check indexing monotonicity
            if block.header.index != prev.header.index + 1:
                return False
            # (Optional) timestamp monotonicity
            if block.header.timestamp < prev.header.timestamp:
                return False
        return True

    # ---------------------------
    # Introspection helpers (for printing)
    # ---------------------------

    def print_chain(self, max_blocks: Optional[int] = None):
        n = len(self.chain) if max_blocks is None else min(max_blocks, len(self.chain))
        for i in range(n):
            b = self.chain[i]
            print(f"\n=== Block {b.header.index} ===")
            print(f"Prev Hash   : {b.header.prev_hash}")
            print(f"Merkle Root : {b.header.merkle_root}")
            print(f"Timestamp   : {b.header.timestamp}")
            print(f"Difficulty  : {b.header.difficulty}")
            print(f"Nonce       : {b.header.nonce}")
            print(f"Hash        : {b.hash()}")
            print(f"Tx Count    : {len(b.transactions)}")
            for tx in b.transactions[:5]:
                print(f"  - {tx}")
            if len(b.transactions) > 5:
                print(f"  ... (+{len(b.transactions)-5} more)")

# ---------------------------
# Demo / Smoke test
# ---------------------------

if __name__ == "__main__":
    # Create a chain with small difficulty (increase to 5+ to feel the pain!)
    chain = Blockchain(difficulty=4)

    # Add some dummy transactions (strings for now)
    chain.add_transaction("Alice->Bob:5")
    chain.add_transaction("Bob->Carol:2")
    chain.add_transaction("Carol->Dave:1")

    print("\nMining Block 1 ...")
    b1 = chain.mine_block()
    print(f"Mined Block 1 with hash: {b1.hash()}")

    chain.add_transaction("Eve->Frank:3")
    chain.add_transaction("SYSTEM:note:This is just a toy chain")

    print("\nMining Block 2 ...")
    b2 = chain.mine_block()
    print(f"Mined Block 2 with hash: {b2.hash()}")

    # Print the first few blocks
    chain.print_chain(max_blocks=3)

    # Validate the chain
    print("\nChain valid:", chain.is_valid_chain())
