ALTER TABLE sales ADD COLUMN terminal_processed_at TEXT;

CREATE INDEX IF NOT EXISTS ix_sales_terminal_pending
ON sales(status, terminal_processed_at);
