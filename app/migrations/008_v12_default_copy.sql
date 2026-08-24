UPDATE settings
SET value = 'Venda contas Gmail para a SK Store',
    updated_at = strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now')
WHERE key = 'panel_title'
  AND value = 'Venda seus G-mails para a SK Store';

UPDATE settings
SET value = 'Venda contas que você não usa mais.

Pagamento via Pix.',
    updated_at = strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now')
WHERE key = 'panel_description'
  AND value = 'Venda G-mails que você não usa mais ou crie novas contas para vender.

Pagamento via Pix.';

UPDATE settings
SET value = '{user}, seu carrinho está pronto. Confira os dados abaixo.',
    updated_at = strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now')
WHERE key = 'cart_message_text'
  AND value = '{user}, seu carrinho foi criado. Confira seus dados abaixo.';
