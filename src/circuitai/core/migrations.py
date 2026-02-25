"""Schema versioning and migrations for CircuitAI database."""

from __future__ import annotations

from circuitai.core.database import DatabaseConnection
from circuitai.core.exceptions import DatabaseError

CURRENT_SCHEMA_VERSION = 3

MIGRATIONS: dict[int, str | list[str]] = {
    1: """
    -- Schema version tracking
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER NOT NULL,
        applied_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    -- Bills
    CREATE TABLE IF NOT EXISTS bills (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        provider TEXT NOT NULL DEFAULT '',
        category TEXT NOT NULL DEFAULT 'other',
        amount_cents INTEGER NOT NULL,
        due_day INTEGER,
        frequency TEXT NOT NULL DEFAULT 'monthly',
        account_id TEXT,
        auto_pay INTEGER NOT NULL DEFAULT 0,
        match_patterns TEXT NOT NULL DEFAULT '[]',
        notes TEXT NOT NULL DEFAULT '',
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (account_id) REFERENCES accounts(id)
    );

    -- Bill payments
    CREATE TABLE IF NOT EXISTS bill_payments (
        id TEXT PRIMARY KEY,
        bill_id TEXT NOT NULL,
        amount_cents INTEGER NOT NULL,
        paid_date TEXT NOT NULL,
        payment_method TEXT NOT NULL DEFAULT '',
        confirmation TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (bill_id) REFERENCES bills(id) ON DELETE CASCADE
    );

    -- Bank accounts
    CREATE TABLE IF NOT EXISTS accounts (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        institution TEXT NOT NULL,
        account_type TEXT NOT NULL DEFAULT 'checking',
        last_four TEXT NOT NULL DEFAULT '',
        balance_cents INTEGER NOT NULL DEFAULT 0,
        balance_updated_at TEXT,
        notes TEXT NOT NULL DEFAULT '',
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    -- Account transactions
    CREATE TABLE IF NOT EXISTS account_transactions (
        id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL,
        description TEXT NOT NULL,
        amount_cents INTEGER NOT NULL,
        transaction_date TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT '',
        linked_bill_id TEXT,
        linked_investment_id TEXT,
        is_matched INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
        FOREIGN KEY (linked_bill_id) REFERENCES bills(id),
        FOREIGN KEY (linked_investment_id) REFERENCES investments(id)
    );

    -- Credit cards
    CREATE TABLE IF NOT EXISTS cards (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        institution TEXT NOT NULL,
        last_four TEXT NOT NULL DEFAULT '',
        credit_limit_cents INTEGER NOT NULL DEFAULT 0,
        balance_cents INTEGER NOT NULL DEFAULT 0,
        due_day INTEGER,
        apr_bps INTEGER NOT NULL DEFAULT 0,
        balance_updated_at TEXT,
        notes TEXT NOT NULL DEFAULT '',
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    -- Card transactions
    CREATE TABLE IF NOT EXISTS card_transactions (
        id TEXT PRIMARY KEY,
        card_id TEXT NOT NULL,
        description TEXT NOT NULL,
        amount_cents INTEGER NOT NULL,
        transaction_date TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT '',
        linked_bill_id TEXT,
        is_matched INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (card_id) REFERENCES cards(id) ON DELETE CASCADE,
        FOREIGN KEY (linked_bill_id) REFERENCES bills(id)
    );

    -- Mortgages
    CREATE TABLE IF NOT EXISTS mortgages (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        lender TEXT NOT NULL,
        original_amount_cents INTEGER NOT NULL,
        balance_cents INTEGER NOT NULL,
        interest_rate_bps INTEGER NOT NULL,
        monthly_payment_cents INTEGER NOT NULL,
        escrow_cents INTEGER NOT NULL DEFAULT 0,
        term_months INTEGER NOT NULL DEFAULT 360,
        start_date TEXT NOT NULL,
        due_day INTEGER NOT NULL DEFAULT 1,
        account_id TEXT,
        notes TEXT NOT NULL DEFAULT '',
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (account_id) REFERENCES accounts(id)
    );

    -- Mortgage payments
    CREATE TABLE IF NOT EXISTS mortgage_payments (
        id TEXT PRIMARY KEY,
        mortgage_id TEXT NOT NULL,
        amount_cents INTEGER NOT NULL,
        principal_cents INTEGER NOT NULL DEFAULT 0,
        interest_cents INTEGER NOT NULL DEFAULT 0,
        escrow_cents INTEGER NOT NULL DEFAULT 0,
        paid_date TEXT NOT NULL,
        notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (mortgage_id) REFERENCES mortgages(id) ON DELETE CASCADE
    );

    -- Investments
    CREATE TABLE IF NOT EXISTS investments (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        institution TEXT NOT NULL,
        account_type TEXT NOT NULL DEFAULT 'brokerage',
        current_value_cents INTEGER NOT NULL DEFAULT 0,
        cost_basis_cents INTEGER NOT NULL DEFAULT 0,
        recurring_amount_cents INTEGER NOT NULL DEFAULT 0,
        recurring_frequency TEXT NOT NULL DEFAULT 'monthly',
        source_account_id TEXT,
        beneficiary_child_id TEXT,
        value_updated_at TEXT,
        notes TEXT NOT NULL DEFAULT '',
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (source_account_id) REFERENCES accounts(id),
        FOREIGN KEY (beneficiary_child_id) REFERENCES children(id)
    );

    -- Investment contributions
    CREATE TABLE IF NOT EXISTS investment_contributions (
        id TEXT PRIMARY KEY,
        investment_id TEXT NOT NULL,
        amount_cents INTEGER NOT NULL,
        contribution_date TEXT NOT NULL,
        source_account_id TEXT,
        notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (investment_id) REFERENCES investments(id) ON DELETE CASCADE,
        FOREIGN KEY (source_account_id) REFERENCES accounts(id)
    );

    -- Deadlines
    CREATE TABLE IF NOT EXISTS deadlines (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        due_date TEXT NOT NULL,
        priority TEXT NOT NULL DEFAULT 'medium',
        category TEXT NOT NULL DEFAULT 'general',
        linked_bill_id TEXT,
        is_completed INTEGER NOT NULL DEFAULT 0,
        completed_at TEXT,
        notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (linked_bill_id) REFERENCES bills(id)
    );

    -- Children
    CREATE TABLE IF NOT EXISTS children (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        birth_date TEXT,
        notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    -- Activities
    CREATE TABLE IF NOT EXISTS activities (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        child_id TEXT,
        sport_or_type TEXT NOT NULL DEFAULT '',
        provider TEXT NOT NULL DEFAULT '',
        season TEXT NOT NULL DEFAULT '',
        cost_cents INTEGER NOT NULL DEFAULT 0,
        frequency TEXT NOT NULL DEFAULT '',
        schedule TEXT NOT NULL DEFAULT '',
        location TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '',
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (child_id) REFERENCES children(id)
    );

    -- Activity payments
    CREATE TABLE IF NOT EXISTS activity_payments (
        id TEXT PRIMARY KEY,
        activity_id TEXT NOT NULL,
        amount_cents INTEGER NOT NULL,
        paid_date TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE
    );

    -- Tags (flexible tagging system)
    CREATE TABLE IF NOT EXISTS tags (
        id TEXT PRIMARY KEY,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        tag TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_tags_entity ON tags(entity_type, entity_id);
    CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);

    -- Adapter state (for sync tracking and learned patterns)
    CREATE TABLE IF NOT EXISTS adapter_state (
        id TEXT PRIMARY KEY,
        adapter_name TEXT NOT NULL,
        key TEXT NOT NULL,
        value TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_adapter_state_key ON adapter_state(adapter_name, key);

    -- Calendar sync log
    CREATE TABLE IF NOT EXISTS calendar_sync_log (
        id TEXT PRIMARY KEY,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        calendar_uid TEXT NOT NULL DEFAULT '',
        last_synced_at TEXT NOT NULL DEFAULT (datetime('now')),
        last_etag TEXT NOT NULL DEFAULT '',
        sync_direction TEXT NOT NULL DEFAULT 'push'
    );
    CREATE INDEX IF NOT EXISTS idx_sync_entity ON calendar_sync_log(entity_type, entity_id);

    INSERT INTO schema_version (version) VALUES (1);
    """,
    2: [
        # Plaid account mapping table
        """CREATE TABLE IF NOT EXISTS plaid_account_map (
            id TEXT PRIMARY KEY,
            plaid_account_id TEXT NOT NULL UNIQUE,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            institution TEXT NOT NULL DEFAULT '',
            plaid_name TEXT NOT NULL DEFAULT '',
            plaid_mask TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )""",
        # Add plaid_txn_id to account_transactions
        "ALTER TABLE account_transactions ADD COLUMN plaid_txn_id TEXT",
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_acct_txn_plaid
           ON account_transactions(plaid_txn_id) WHERE plaid_txn_id IS NOT NULL""",
        # Add plaid_txn_id to card_transactions
        "ALTER TABLE card_transactions ADD COLUMN plaid_txn_id TEXT",
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_card_txn_plaid
           ON card_transactions(plaid_txn_id) WHERE plaid_txn_id IS NOT NULL""",
        "INSERT INTO schema_version (version) VALUES (2)",
    ],
    3: [
        # Add fingerprint column for cross-source dedup
        "ALTER TABLE account_transactions ADD COLUMN txn_fingerprint TEXT",
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_acct_txn_fingerprint
           ON account_transactions(txn_fingerprint) WHERE txn_fingerprint IS NOT NULL""",
        "ALTER TABLE card_transactions ADD COLUMN txn_fingerprint TEXT",
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_card_txn_fingerprint
           ON card_transactions(txn_fingerprint) WHERE txn_fingerprint IS NOT NULL""",
        "INSERT INTO schema_version (version) VALUES (3)",
    ],
}


def get_schema_version(db: DatabaseConnection) -> int:
    """Get the current schema version, or 0 if the table doesn't exist."""
    try:
        row = db.fetchone("SELECT MAX(version) as v FROM schema_version")
        return row["v"] if row and row["v"] else 0
    except Exception:
        return 0


def run_migrations(db: DatabaseConnection) -> int:
    """Run all pending migrations and return the final schema version."""
    current = get_schema_version(db)

    for version in sorted(MIGRATIONS.keys()):
        if version > current:
            try:
                migration = MIGRATIONS[version]
                if isinstance(migration, list):
                    for stmt in migration:
                        db.execute(stmt)
                    db.commit()
                else:
                    db.conn.executescript(migration)
                    db.commit()
                current = version
            except Exception as e:
                raise DatabaseError(f"Migration to v{version} failed: {e}") from e

    return current


def initialize_database(db: DatabaseConnection) -> int:
    """Set up the database schema from scratch or run pending migrations."""
    return run_migrations(db)
