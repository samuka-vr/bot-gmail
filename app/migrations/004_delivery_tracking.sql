ALTER TABLE events ADD COLUMN delivered_at TEXT;
ALTER TABLE events ADD COLUMN delivery_error TEXT;

ALTER TABLE sales ADD COLUMN transcript_message_id INTEGER;
ALTER TABLE sales ADD COLUMN transcript_sent_at TEXT;
ALTER TABLE sales ADD COLUMN ticket_deleted_at TEXT;

CREATE INDEX IF NOT EXISTS ix_events_pending
ON events(delivered_at, created_at);

CREATE INDEX IF NOT EXISTS ix_sales_maintenance
ON sales(cart_notice_delete_at, ticket_delete_at);
