UPDATE settings
SET value = 'true',
    updated_at = strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now')
WHERE key = 'auto_close_enabled'
  AND value = 'false';

UPDATE settings
SET value = '60',
    updated_at = strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now')
WHERE key = 'auto_close_delay'
  AND value = '3600';
