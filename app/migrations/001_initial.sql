CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    customer_id INTEGER NOT NULL,
    channel_id INTEGER UNIQUE,
    workflow_message_id INTEGER,
    cart_notice_message_id INTEGER,
    status TEXT NOT NULL CHECK (status IN (
        'AGUARDANDO', 'EM_ANALISE', 'PAGAMENTO', 'PAGO',
        'FINALIZADO', 'ENCERRADO'
    )),
    responsible_staff_id INTEGER,
    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents > 0),
    pix_key TEXT NOT NULL,
    pix_holder TEXT NOT NULL,
    verification_code TEXT NOT NULL,
    ticket_name TEXT,
    close_reason TEXT,
    closed_by_id INTEGER,
    create_interaction_id INTEGER NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    claimed_at TEXT,
    payment_stage_at TEXT,
    paid_at TEXT,
    completed_at TEXT,
    closed_at TEXT,
    cart_notice_delete_at TEXT,
    ticket_delete_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE (guild_id, verification_code)
);

CREATE TABLE IF NOT EXISTS sale_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE RESTRICT,
    email TEXT NOT NULL,
    canonical_email TEXT NOT NULL,
    created_at TEXT NOT NULL,
    removed_at TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    guild_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by_id INTEGER,
    PRIMARY KEY (guild_id, key)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    sale_id INTEGER REFERENCES sales(id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL,
    actor_id INTEGER,
    payload_json TEXT NOT NULL DEFAULT '{}',
    interaction_id INTEGER UNIQUE,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_sale_active_account
ON sale_accounts(sale_id, canonical_email)
WHERE removed_at IS NULL;
