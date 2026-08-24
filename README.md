# SK Store — Discord Gmail Sales Bot

Bot de vendas assistidas para a SK Store. O cliente envia somente os endereços Gmail e os dados Pix; a equipe valida o acesso manualmente, confirma o pagamento e finaliza a venda no mesmo ticket.

O bot nunca entra no Gmail e nunca solicita senha, código 2FA, cookie, token, código de recuperação ou backup.

## Fluxo

```text
Painel → formulário → ticket/carrinho → Staff assume → pagamento → confirmação → finalização
```

- Painel público com um único botão.
- Carrinho editável antes do pagamento.
- Código temporário de verificação no formato `SK-48321`.
- Claim e ownership de Staff, com override de Admin/Manager.
- Pagamento e verificação sempre manuais.
- Transcript HTML, logs, perfil, fila e configuração dentro do Discord.
- SQLite persistente e Views restauradas depois de reinícios.

## Requisitos

- Python 3.11 ou superior.
- Aplicação e bot criados no [Discord Developer Portal](https://discord.com/developers/applications).
- Dependências de `requirements.txt`.

Versões fixadas no projeto:

```text
discord.py==2.7.1
aiosqlite==0.22.1
python-dotenv==1.2.3
```

## Instalação local

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

No Windows, ative o ambiente com `.venv\Scripts\activate`.

Edite somente o `.env`:

```dotenv
DISCORD_TOKEN=token_do_bot
DATABASE_PATH=data/skstore.db
SYNC_COMMANDS_ON_START=true
LOG_LEVEL=INFO
```

`DEV_GUILD_ID` é opcional. Quando definido, os comandos são sincronizados apenas nesse servidor para testes rápidos. Em produção, remova essa linha para usar comandos globais.

Nunca envie `.env`, tokens ou arquivos `.db` ao Git. O `.gitignore` já bloqueia esses arquivos.

Inicie com:

```bash
python main.py
```

Após a primeira sincronização dos comandos, `SYNC_COMMANDS_ON_START` pode ser definido como `false` para evitar uma chamada de sincronização em cada reinício.

## Intents do Discord

Na página **Bot** da aplicação, ative:

- **Message Content Intent** — obrigatório para o texto completo dos transcripts.

Se a aplicação for verificada ou elegível para verificação, confirme também a aprovação desse intent no Discord.

O código utiliza apenas:

- `guilds`;
- `guild_messages`;
- `message_content`.

`Server Members Intent` e `Presence Intent` não são necessários. Isso reduz cache e consumo de memória.

O código solicita esse intent no Gateway. Se ele não estiver liberado no Developer Portal, o Discord pode recusar a conexão do bot. Em contextos onde o conteúdo não é autorizado, mensagens do histórico também podem chegar com conteúdo, embeds e anexos vazios.

## Convite e permissões

Gere o convite OAuth2 com os escopos:

- `bot`;
- `applications.commands`.

Permissões necessárias para o bot:

- Ver canais;
- Enviar mensagens;
- Inserir links;
- Anexar arquivos;
- Ler histórico de mensagens;
- Gerenciar canais;
- Gerenciar cargos.

`Gerenciar canais` cria, renomeia e remove tickets. `Gerenciar cargos` é exigido pela API do Discord para editar os overwrites privados e bloquear o ticket ao final. Posicione o cargo do bot acima dos cargos que ele precisa administrar.

O comando `/botconfig → Diagnóstico` confirma canais, cargos, permissões, painel, SQLite, Views e intents.

## Primeira configuração

Uma pessoa com `Gerenciar servidor`, `Administrador` ou o cargo Admin/Manager configurado deve executar `/botconfig`.

Ordem recomendada:

1. **Canais** — selecione canal do painel, categoria de tickets, logs e transcripts.
2. **Cargos** — selecione Staff e Admin/Manager.
3. **Preços** — defina preço, mínimo e máximo.
4. **Painel** — revise título, descrição, rodapé, botão e texto do preço.
5. **Aparência** — configure cor, logo, banner e IDs opcionais de emojis customizados.
6. **Mensagem do carrinho** — ajuste texto, destino e auto-delete.
7. **Logs** e **Configurações gerais** — revise toggles, prefixo, limite e auto-close.
8. **Diagnóstico** — corrija qualquer item com `FALHA`.
9. **Publicar / Atualizar painel** — publique somente após o diagnóstico.

Publicar novamente edita a mensagem salva. Se ela tiver sido apagada, o bot cria uma nova e atualiza o ID no SQLite. Se o canal do painel mudar, o novo painel é publicado e a mensagem anterior é removida para não deixar dois painéis ativos.

## Comandos

- `/botconfig` — configuração administrativa efêmera.
- `/perfil` — histórico e totais do próprio cliente.
- `/fila` — fila compacta para Staff.
- `/vender` — abre o mesmo formulário do painel.

Não existem comandos de senha, login ou verificação automática de Gmail.

## Mensagem automática do carrinho

Placeholders disponíveis:

- `{user}` — menção do cliente;
- `{quantidade}` — quantidade de contas;
- `{preco}` — preço por conta;
- `{total}` — total da venda;
- `{codigo}` — código temporário;
- `{ticket}` — menção/link do ticket.

Destinos possíveis: ticket, DM ou ambos. O auto-delete se aplica à mensagem enviada no ticket. O prazo fica persistido e sobrevive a reinícios.

## Verificação manual e segurança

O código `SK-xxxxx` serve para prova manual de acesso. A equipe pode pedir um vídeo ou uma ação dentro da conta exibindo esse código. O cliente não deve mostrar a senha.

Dados armazenados:

- endereços Gmail;
- chave Pix e titular;
- IDs do Discord;
- valores em centavos;
- código temporário;
- estados, timestamps e eventos da venda.

Senhas e segredos de autenticação não têm campo no banco, nos modais ou nos logs.

## Transcripts e logs

O transcript é um HTML com CSS embutido, escrito incrementalmente para não manter o histórico inteiro na RAM. Ele inclui:

- mensagens ainda existentes no ticket;
- autores e timestamps;
- anexos como links;
- embeds;
- metadados e estado final da venda.

O arquivo temporário é removido após o envio. Se o transcript falhar, a venda permanece finalizada e uma falha técnica é registrada.

Logs não exibem senhas ou tokens. Adição/remoção de Gmail é registrada por quantidade; a lista completa permanece na venda e no transcript autorizado.

Restrinja os canais de logs e transcripts à equipe. Se alguém publicar credenciais por conta própria no ticket, remova a mensagem imediatamente; o bot avisa no carrinho que senhas e códigos de acesso não devem ser enviados.

## Banco e migrações

O banco padrão é `data/skstore.db`. As migrações em `app/migrations/` são aplicadas automaticamente e nunca apagam registros de venda.

Para backup seguro:

1. pare o bot;
2. copie `data/skstore.db`;
3. guarde a cópia fora do ZIP e do Git;
4. reinicie o bot.

Com o bot parado, não é necessário copiar arquivos `-wal` ou `-shm`. Não edite o SQLite manualmente enquanto o processo estiver ativo.

## Testes

Com as dependências instaladas:

```bash
python -m compileall -q .
python -m unittest discover -s tests -p "test_*.py" -v
```

A suíte cobre validação, centavos, migrações, duplicidade, idempotência, carrinho, ownership, estados, perfil, fila, deadlines, transcript, embeds, Views, componentes, comandos e arquivos de implantação.

Antes de produção, faça um teste ao vivo em servidor privado com dois usuários de Staff e um cliente. Confirme também DM fechada, permissões removidas e restart durante uma venda ativa.

## Discloud

O `discloud.config` já está na raiz:

```ini
NAME=sk-store-gmail
TYPE=bot
MAIN=main.py
RAM=100
VERSION=latest
AUTORESTART=true
```

Para upload manual, compacte o conteúdo da raiz do projeto. `main.py`, `requirements.txt` e `discloud.config` devem aparecer diretamente na raiz do ZIP, sem uma pasta externa adicional.

Na Discloud, envie também o `.env` de produção diretamente ao ambiente de hospedagem. Não o adicione ao repositório.

O repositório `samuka-vr/bot-gmail` está preparado para Auto Deploy na branch `main`. Faça push na `main` somente depois de todos os testes e revisão final.

## Consumo de RAM

O projeto foi desenhado para o limite de 100 MB:

- sem dashboard web ou servidor HTTP;
- uma conexão `aiosqlite`;
- cache de mensagens limitado a 50;
- sem cache de membros e sem intent de membros;
- consultas SQLite sob demanda;
- recuperação paginada em lotes de 100 vendas;
- um único agendador baseado no próximo prazo;
- transcript escrito em disco de forma incremental;
- apenas três dependências diretas.

O uso real varia com a quantidade de servidores, canais e atividade. O alvo é uma instância pequena/média da SK Store; acompanhe a métrica de RAM da Discloud após o primeiro deploy.

## Limitações intencionais

- Verificação de Gmail e pagamento são manuais.
- Cada venda aceita no máximo 25 contas, limite escolhido para o Select nativo de remoção do Discord.
- Mensagens apagadas antes da finalização não aparecem no transcript.
- Anexos são referenciados por URL; não são baixados nem duplicados.
- DM depende das configurações de privacidade do cliente.
- Auto-close apaga o canal do Discord, mas nunca o registro SQLite.

## Referências oficiais

- [Discord — componentes](https://docs.discord.com/developers/components/reference)
- [Discord — permissões](https://docs.discord.com/developers/topics/permissions)
- [Discord — mensagens e histórico](https://docs.discord.com/developers/resources/message)
- [discord.py — documentação](https://discordpy.readthedocs.io/en/latest/)
- [Discloud — discloud.config](https://docs.discloud.com/configurations/discloud.config)
- [Discloud — hospedagem de bots](https://docs.discloud.com/how-to-host/bots)
