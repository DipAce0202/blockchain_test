# blockchain_v2.py
# Milestone 2: Account-based blockchain with real Transactions, nonces, fees, miner reward.
# Educational only (no signatures yet, no networking, no persistence).

from __future__ import annotations
import hashlib
import json
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

# =========================
# Utilities
# =========================

def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def canonical_json(obj) -> str:
    # Deterministic encoding for hashing
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))

def stable_hash_obj(obj) -> str:
    return sha256_hex(canonical_json(obj).encode())

def merkle_root(leaves: List[str]) -> str:
    """
    Compute a simple Merkle root from hex strings (tx ids).
    - Hash each leaf once (so different lengths collide less).
    - For odd count, duplicate the last (Bitcoin style).
    - This is didactic; production formats differ.
    """
    if not leaves:
        return sha256_hex(b"")
    level = [sha256_hex(x.encode()) for x in leaves]
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            a = level[i]
            b = level[i + 1] if i + 1 < len(level) else a
            nxt.append(sha256_hex((a + b).encode()))
        level = nxt
    return level[0]

# =========================
# Transactions
# =========================

@dataclass(frozen=True)
class Transaction:
    """
    Simple account-model transaction.
    - from_addr: sender address (string)
    - to_addr: receiver address (string)
    - amount: integer units (toy coin)
    - fee: integer units paid to miner
    - nonce: sender's next integer starting at 0
    - memo: optional short note (no effect on state)
    """
    from_addr: str
    to_addr: str
    amount: int
    fee: int
    nonce: int
    memo: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)

    def tx_id(self) -> str:
        # For v2 (no signatures), tx_id is hash of content
        return stable_hash_obj({
            "from": self.from_addr,
            "to": self.to_addr,
            "amount": self.amount,
            "fee": self.fee,
            "nonce": self.nonce,
            "memo": self.memo,
        })

@dataclass(frozen=True)
class CoinbaseTx:
    """
    Special first transaction in every block that mints new coins and collects fees.
    - miner: address receiving reward + fees
    - amount: block reward (just the inflation, fees added at apply time)
    """
    miner: str
    amount: int  # block reward (fees will be added when applying block)

    def to_dict(self) -> Dict:
        return {"miner": self.miner, "amount": self.amount, "type": "COINBASE"}

    def tx_id(self) -> str:
        return stable_hash_obj(self.to_dict())

# =========================
# Blocks
# =========================

@dataclass
class BlockHeader:
    index: int
    prev_hash: str
    timestamp: int
    merkle_root: str
    difficulty: int
    nonce: int

    def to_dict(self) -> Dict:
        return asdict(self)

    def hash(self) -> str:
        return stable_hash_obj(self.to_dict())

@dataclass
class Block:
    header: BlockHeader
    coinbase: CoinbaseTx
    transactions: List[Transaction]  # user txs only (coinbase separate)

    def to_dict(self) -> Dict:
        return {
            "header": self.header.to_dict(),
            "coinbase": self.coinbase.to_dict(),
            "transactions": [t.to_dict() for t in self.transactions],
        }

    def hash(self) -> str:
        return self.header.hash()

# =========================
# Blockchain (account model)
# =========================

class Blockchain:
    def __init__(
        self,
        difficulty: int = 4,
        block_reward: int = 50,
        genesis_balances: Optional[Dict[str, int]] = None,
        miner_address: str = "miner1",
    ):
        """
        difficulty: PoW zeros required
        block_reward: minted per block (via coinbase)
        genesis_balances: initial balances for demo
        miner_address: where coinbase pays
        """
        self.difficulty = difficulty
        self.block_reward = block_reward
        self.miner_address = miner_address

        # Chain data
        self.chain: List[Block] = []
        self.pending: List[Transaction] = []

        # Global state (account balances and nonces)
        self.balances: Dict[str, int] = {}
        self.nonces: Dict[str, int] = {}

        # Initialize with genesis block/state
        self._create_genesis_block(genesis_balances or {})

    # ---------- State helpers ----------

    def get_balance(self, addr: str) -> int:
        return self.balances.get(addr, 0)

    def get_nonce(self, addr: str) -> int:
        return self.nonces.get(addr, 0)

    def _set_balance(self, addr: str, value: int):
        if value < 0:
            raise ValueError("Negative balance")
        self.balances[addr] = value

    def _bump_nonce(self, addr: str):
        self.nonces[addr] = self.get_nonce(addr) + 1

    # ---------- Genesis ----------

    def _create_genesis_block(self, genesis_balances: Dict[str, int]):
        # Initialize state
        for a, bal in genesis_balances.items():
            if bal < 0:
                raise ValueError("Genesis balance must be non-negative")
            self._set_balance(a, bal)
            self.nonces[a] = 0

        # Empty coinbase (no mint at genesis)
        coinbase = CoinbaseTx(miner="SYSTEM", amount=0)
        user_txs: List[Transaction] = []
        tx_ids = [coinbase.tx_id()] + [t.tx_id() for t in user_txs]
        header = BlockHeader(
            index=0,
            prev_hash="0" * 64,
            timestamp=int(time.time()),
            merkle_root=merkle_root(tx_ids),
            difficulty=self.difficulty,
            nonce=0,
        )
        mined = self._mine_header(header)
        genesis = Block(mined, coinbase, user_txs)
        self.chain.append(genesis)

    # ---------- Mempool rules (Milestone 2) ----------

    def _pending_outgoing_total(self, addr: str) -> int:
        # Sum of amount+fee for pending txs from addr
        total = 0
        for tx in self.pending:
            if tx.from_addr == addr:
                total += (tx.amount + tx.fee)
        return total

    def _expected_nonce_with_pending(self, addr: str) -> int:
        # Nonce must be strictly sequential including pending txs
        base = self.get_nonce(addr)
        pending_count = sum(1 for tx in self.pending if tx.from_addr == addr)
        return base + pending_count

    def add_transaction(self, tx: Transaction):
        # Basic checks
        if tx.amount <= 0:
            raise ValueError("amount must be > 0")
        if tx.fee < 0:
            raise ValueError("fee must be >= 0")
        if not tx.from_addr or not tx.to_addr:
            raise ValueError("addresses must be non-empty")
        if tx.from_addr == tx.to_addr:
            raise ValueError("from_addr cannot equal to_addr")

        # Nonce rule: must match expected (including pending from same sender)
        expected = self._expected_nonce_with_pending(tx.from_addr)
        if tx.nonce != expected:
            raise ValueError(f"bad nonce: got {tx.nonce}, expected {expected}")

        # Balance rule: sender must afford amount + fee considering pending
        available = self.get_balance(tx.from_addr) - self._pending_outgoing_total(tx.from_addr)
        required = tx.amount + tx.fee
        if available < required:
            raise ValueError(f"insufficient balance: available {available}, need {required}")

        # Looks good; accept into mempool
        self.pending.append(tx)

    # ---------- Mining ----------

    def mine_block(self) -> Block:
        """
        Build a block from current pending transactions (all of them),
        prepend a coinbase paying the miner, then PoW mine the header.
        """
        if not self.pending:
            # You can still mine empty block that only pays block reward.
            # We'll allow it for demo.
            selected = []
        else:
            selected = list(self.pending)

        # Coinbase (fees added upon application)
        coinbase = CoinbaseTx(miner=self.miner_address, amount=self.block_reward)

        # Build Merkle root using tx_ids (coinbase first)
        tx_ids = [coinbase.tx_id()] + [tx.tx_id() for tx in selected]
        header = BlockHeader(
            index=len(self.chain),
            prev_hash=self.chain[-1].hash(),
            timestamp=int(time.time()),
            merkle_root=merkle_root(tx_ids),
            difficulty=self.difficulty,
            nonce=0,
        )
        mined_header = self._mine_header(header)
        block = Block(mined_header, coinbase, selected)

        # Validate & apply to state before finalizing
        self._apply_block(block)

        # Append and clear selected pending
        self.chain.append(block)

        # Remove included txs from pending
        included_ids = {t.tx_id() for t in selected}
        self.pending = [t for t in self.pending if t.tx_id() not in included_ids]

        return block

    def _mine_header(self, header: BlockHeader) -> BlockHeader:
        target = "0" * header.difficulty
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
            if candidate.hash().startswith(target):
                return candidate
            nonce += 1

    # ---------- Validation / Application ----------

    def _apply_block(self, block: Block):
        """
        Apply a block to the current state. This re-validates all rules
        using the *pre-block* state snapshot.
        """
        # 1) Header linkage & PoW
        if block.header.prev_hash != self.chain[-1].hash():
            raise ValueError("prev_hash mismatch")
        if not block.hash().startswith("0" * block.header.difficulty):
            raise ValueError("insufficient work")

        # 2) Recompute Merkle root
        tx_ids = [block.coinbase.tx_id()] + [t.tx_id() for t in block.transactions]
        if block.header.merkle_root != merkle_root(tx_ids):
            raise ValueError("merkle root mismatch")

        # Snapshot (copy) current state to validate then apply
        bal = dict(self.balances)
        non = dict(self.nonces)

        # 3) Apply user transactions in order
        total_fees = 0
        for tx in block.transactions:
            # Nonce check
            exp = non.get(tx.from_addr, 0)
            if tx.nonce != exp:
                raise ValueError(f"block tx bad nonce for {tx.from_addr}: {tx.nonce} != {exp}")
            if tx.amount <= 0 or tx.fee < 0:
                raise ValueError("invalid tx amounts/fee")
            if tx.from_addr == tx.to_addr:
                raise ValueError("from_addr equals to_addr")

            # Balance check
            sender_bal = bal.get(tx.from_addr, 0)
            cost = tx.amount + tx.fee
            if sender_bal < cost:
                raise ValueError("insufficient funds in block application")
            # Apply transfer
            bal[tx.from_addr] = sender_bal - cost
            bal[tx.to_addr] = bal.get(tx.to_addr, 0) + tx.amount
            # Bump nonce
            non[tx.from_addr] = exp + 1
            # Accumulate fees
            total_fees += tx.fee

        # 4) Apply coinbase (reward + fees)
        miner = block.coinbase.miner
        coinbase_amount = block.coinbase.amount + total_fees
        if coinbase_amount < 0:
            raise ValueError("invalid coinbase amount")
        bal[miner] = bal.get(miner, 0) + coinbase_amount

        # Commit new state
        self.balances = bal
        self.nonces = non

    def is_valid_chain(self) -> bool:
        """
        Re-validate entire chain from scratch by replaying state.
        """
        try:
            # Start from a clean slate
            balances: Dict[str, int] = {}
            nonces: Dict[str, int] = {}

            # Genesis
            g = self.chain[0]
            # Check genesis header & PoW
            if g.header.index != 0 or g.header.prev_hash != "0"*64:
                return False
            if not g.hash().startswith("0" * g.header.difficulty):
                return False
            # Merkle
            tx_ids = [g.coinbase.tx_id()] + [t.tx_id() for t in g.transactions]
            if g.header.merkle_root != merkle_root(tx_ids):
                return False

            # Apply all blocks after genesis
            for i in range(1, len(self.chain)):
                blk = self.chain[i]

                # Linkage
                if blk.header.prev_hash != self.chain[i-1].hash():
                    return False
                if not blk.hash().startswith("0" * blk.header.difficulty):
                    return False

                # Merkle
                tx_ids = [blk.coinbase.tx_id()] + [t.tx_id() for t in blk.transactions]
                if blk.header.merkle_root != merkle_root(tx_ids):
                    return False

                # Apply to temp state
                # Use local copies per iteration
                bal = dict(balances)
                non = dict(nonces)

                total_fees = 0
                for tx in blk.transactions:
                    exp = non.get(tx.from_addr, 0)
                    if tx.nonce != exp or tx.amount <= 0 or tx.fee < 0 or tx.from_addr == tx.to_addr:
                        return False
                    sb = bal.get(tx.from_addr, 0)
                    cost = tx.amount + tx.fee
                    if sb < cost:
                        return False
                    bal[tx.from_addr] = sb - cost
                    bal[tx.to_addr] = bal.get(tx.to_addr, 0) + tx.amount
                    non[tx.from_addr] = exp + 1
                    total_fees += tx.fee

                miner = blk.coinbase.miner
                reward = blk.coinbase.amount + total_fees
                if reward < 0:
                    return False
                bal[miner] = bal.get(miner, 0) + reward

                # Commit
                balances = bal
                nonces = non

            return True
        except Exception:
            return False

    # ---------- Debug / print helpers ----------

    def print_balances(self, only_nonzero: bool = True):
        print("\n=== Balances ===")
        for addr, bal in sorted(self.balances.items()):
            if only_nonzero and bal == 0:
                continue
            print(f"{addr:>10} : {bal}")

    def print_block(self, blk: Block):
        h = blk.header
        print(f"\n=== Block {h.index} ===")
        print(f"Prev Hash   : {h.prev_hash}")
        print(f"Merkle Root : {h.merkle_root}")
        print(f"Timestamp   : {h.timestamp}")
        print(f"Difficulty  : {h.difficulty}")
        print(f"Nonce       : {h.nonce}")
        print(f"Hash        : {blk.hash()}")
        print(f"Coinbase    : miner={blk.coinbase.miner}, reward={blk.coinbase.amount}")
        print(f"Tx Count    : {len(blk.transactions)}")
        for t in blk.transactions[:5]:
            print(f"  - {t.from_addr}->{t.to_addr} amt={t.amount} fee={t.fee} nonce={t.nonce}")
        if len(blk.transactions) > 5:
            print(f"  ... (+{len(blk.transactions)-5} more)")

# =========================
# Demo / Smoke test
# =========================

if __name__ == "__main__":
    # Start a chain with difficulty=4 and a simple genesis allocation
    chain = Blockchain(
        difficulty=4,
        block_reward=25,
        genesis_balances={"alice": 100, "bob": 50},
        miner_address="miner1"
    )

    # Alice pays Bob with a fee
    chain.add_transaction(Transaction(from_addr="alice", to_addr="bob", amount=10, fee=1, nonce=0, memo="A->B 10"))
    # Alice sends again (nonce must be 1 now)
    chain.add_transaction(Transaction(from_addr="alice", to_addr="carol", amount=5, fee=1, nonce=1, memo="A->C 5"))
    # Bob sends Carol (bob's first tx uses nonce=0)
    chain.add_transaction(Transaction(from_addr="bob", to_addr="carol", amount=7, fee=1, nonce=0, memo="B->C 7"))

    print("\nMining Block 1 ...")
    b1 = chain.mine_block()
    chain.print_block(b1)
    chain.print_balances()

    # Another round: Alice tries two txs back-to-back
    # Nonces must increase: alice's next expected nonce is 2 (she already used 0 and 1)
    chain.add_transaction(Transaction(from_addr="alice", to_addr="bob", amount=8, fee=1, nonce=2, memo="A->B 8"))
    chain.add_transaction(Transaction(from_addr="alice", to_addr="bob", amount=4, fee=1, nonce=3, memo="A->B 4"))

    print("\nMining Block 2 ...")
    b2 = chain.mine_block()
    chain.print_block(b2)
    chain.print_balances()

    print("\nChain valid:", chain.is_valid_chain())

    # Tamper test: uncomment to see validation fail
    # chain.chain[1].transactions[0] = Transaction("alice", "bob", 999, 1, 0, "tamper")
    # print("Chain valid after tamper:", chain.is_valid_chain())