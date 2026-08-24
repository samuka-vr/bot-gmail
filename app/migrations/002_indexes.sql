CREATE INDEX IF NOT EXISTS ix_sales_guild_status
ON sales(guild_id, status, created_at);

CREATE INDEX IF NOT EXISTS ix_sales_customer_status
ON sales(guild_id, customer_id, status);

CREATE INDEX IF NOT EXISTS ix_sales_channel
ON sales(channel_id);

CREATE INDEX IF NOT EXISTS ix_accounts_canonical_active
ON sale_accounts(canonical_email, removed_at);

CREATE INDEX IF NOT EXISTS ix_accounts_sale_active
ON sale_accounts(sale_id, removed_at);

CREATE INDEX IF NOT EXISTS ix_events_sale_created
ON events(sale_id, created_at);
