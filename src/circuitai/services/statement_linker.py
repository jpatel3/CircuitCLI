"""Statement linking — auto-match imported transactions to known bills."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from circuitai.core.database import DatabaseConnection


class StatementLinker:
    """Match bank/card transactions against known bills.

    Uses three signals:
    1. Description pattern matching (keyword search)
    2. Amount tolerance (exact or within configurable range)
    3. Date proximity to expected due date

    Learns from manual confirmations by storing new patterns.
    """

    def __init__(
        self,
        db: DatabaseConnection,
        amount_tolerance_cents: int = 500,
        date_window_days: int = 7,
    ) -> None:
        self.db = db
        self.amount_tolerance_cents = amount_tolerance_cents
        self.date_window_days = date_window_days

    def link_transactions(self, account_id: str | None = None) -> dict[str, Any]:
        """Run statement linking on unmatched transactions.

        Returns a summary of what was matched.
        """
        bills = self.db.fetchall(
            "SELECT id, name, match_patterns, amount_cents, due_day "
            "FROM bills WHERE is_active = 1"
        )

        where = "is_matched = 0"
        params: tuple = ()
        if account_id:
            where += " AND account_id = ?"
            params = (account_id,)

        unmatched = self.db.fetchall(
            f"SELECT id, description, amount_cents, transaction_date "
            f"FROM account_transactions WHERE {where}",
            params,
        )

        matches = []
        for txn in unmatched:
            best = self._find_best_match(txn, bills)
            if best:
                bill_id, score = best
                self.db.execute(
                    "UPDATE account_transactions "
                    "SET is_matched = 1, linked_bill_id = ? WHERE id = ?",
                    (bill_id, txn["id"]),
                )
                matches.append({
                    "transaction_id": txn["id"],
                    "bill_id": bill_id,
                    "description": txn["description"],
                    "score": score,
                })

        if matches:
            self.db.commit()

        return {
            "total_unmatched": len(unmatched),
            "matched": len(matches),
            "matches": matches,
        }

    def _find_best_match(
        self, txn: Any, bills: list[Any]
    ) -> tuple[str, float] | None:
        """Find the best matching bill for a transaction.

        Returns (bill_id, score) or None. Score is 0-1.
        """
        best_id = None
        best_score = 0.0

        for bill in bills:
            score = self._score_match(txn, bill)
            if score > best_score and score >= 0.4:
                best_score = score
                best_id = bill["id"]

        if best_id:
            return (best_id, best_score)
        return None

    def _score_match(self, txn: Any, bill: Any) -> float:
        """Score how well a transaction matches a bill (0-1)."""
        score = 0.0

        # 1. Description pattern match (0.5 weight)
        patterns = json.loads(bill["match_patterns"]) if bill["match_patterns"] else []
        desc_upper = txn["description"].upper()
        for pattern in patterns:
            if pattern.upper() in desc_upper:
                score += 0.5
                break

        # 2. Amount match (0.3 weight)
        if bill["amount_cents"] and txn["amount_cents"]:
            diff = abs(abs(txn["amount_cents"]) - bill["amount_cents"])
            if diff == 0:
                score += 0.3
            elif diff <= self.amount_tolerance_cents:
                # Partial credit for close amounts
                score += 0.3 * (1 - diff / self.amount_tolerance_cents)

        # 3. Date proximity (0.2 weight)
        if bill["due_day"] and txn["transaction_date"]:
            score += self._date_proximity_score(
                txn["transaction_date"], bill["due_day"]
            )

        return score

    def _date_proximity_score(self, txn_date_str: str, due_day: int) -> float:
        """Score date proximity (0-0.2) based on closeness to due day."""
        try:
            txn_date = date.fromisoformat(txn_date_str[:10])
            # Calculate expected due date in the same month
            import calendar

            last_day = calendar.monthrange(txn_date.year, txn_date.month)[1]
            expected = txn_date.replace(day=min(due_day, last_day))
            diff_days = abs((txn_date - expected).days)

            if diff_days == 0:
                return 0.2
            elif diff_days <= self.date_window_days:
                return 0.2 * (1 - diff_days / self.date_window_days)
        except (ValueError, TypeError):
            pass
        return 0.0

    def learn_pattern(self, bill_id: str, description: str) -> None:
        """Learn a new pattern from a manual confirmation.

        Extracts keywords from the transaction description and adds
        them to the bill's match_patterns.
        """
        bill = self.db.fetchone(
            "SELECT id, match_patterns FROM bills WHERE id = ?", (bill_id,)
        )
        if not bill:
            return

        patterns = json.loads(bill["match_patterns"]) if bill["match_patterns"] else []

        # Extract the most distinctive part of the description
        # Use the first 2-3 words as a pattern (skip common prefixes)
        words = description.upper().split()
        skip = {"PAYMENT", "TO", "FROM", "FOR", "THE", "ACH", "DEBIT", "CREDIT", "ONLINE"}
        meaningful = [w for w in words if w not in skip]

        if meaningful:
            new_pattern = " ".join(meaningful[:3])
            if new_pattern not in patterns:
                patterns.append(new_pattern)
                self.db.execute(
                    "UPDATE bills SET match_patterns = ? WHERE id = ?",
                    (json.dumps(patterns), bill_id),
                )
                self.db.commit()

    def get_unmatched(self, account_id: str | None = None) -> list[dict[str, Any]]:
        """Get unmatched transactions for review."""
        where = "is_matched = 0"
        params: tuple = ()
        if account_id:
            where += " AND account_id = ?"
            params = (account_id,)

        rows = self.db.fetchall(
            f"SELECT id, account_id, description, amount_cents, transaction_date "
            f"FROM account_transactions WHERE {where} ORDER BY transaction_date DESC",
            params,
        )
        return [dict(r) for r in rows]

    def confirm_match(self, transaction_id: str, bill_id: str) -> None:
        """Manually confirm a match and learn from it."""
        txn = self.db.fetchone(
            "SELECT description FROM account_transactions WHERE id = ?",
            (transaction_id,),
        )
        if txn:
            self.db.execute(
                "UPDATE account_transactions "
                "SET is_matched = 1, linked_bill_id = ? WHERE id = ?",
                (bill_id, transaction_id),
            )
            self.db.commit()
            self.learn_pattern(bill_id, txn["description"])
