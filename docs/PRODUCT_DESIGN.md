# SK Store — UX e arquitetura técnica

Este documento congela as decisões de produto antes da implementação. O bot é um fluxo de venda assistido por Staff, não um gerenciador genérico de tickets.

## Princípios

- Uma ação principal por etapa e ações relacionadas agrupadas em Select Menus.
- Uma única mensagem permanente de fluxo por ticket; o embed e a View são editados no lugar.
- Português brasileiro curto, sem emojis Unicode e sem solicitações de senha ou códigos de acesso.
- Estado, valores e responsáveis persistidos no SQLite; a memória mantém apenas locks transitórios e um agendador leve.
- Valores monetários em centavos inteiros.
- Limite máximo configurável de 25 contas, alinhado ao limite nativo de 25 opções de um Select Menu do Discord.

## Mapa de telas

### Cliente

1. **Painel público** — Embed V1 com logo, banner, título, descrição, informação curta, preço, rodapé e apenas `Vender Gmail`.
2. **Modal de venda** — `Gmails`, `Chave Pix`, `Nome do titular`.
3. **Ticket / carrinho** — embed da venda com status, cliente, código, quantidade, preço, total, Pix, titular e contas. Controles: Select `Editar carrinho` e botão Danger `Cancelar venda`.
4. **Adicionar Gmail** — modal curto; retorna ao mesmo carrinho atualizado.
5. **Remover Gmail** — resposta efêmera com Select de contas ativas; o carrinho original é atualizado.
6. **Editar Pix** — um modal com chave e titular; o carrinho original é atualizado.
7. **Confirmar cancelamento** — confirmação efêmera única e destrutiva.
8. **Pagamento** — o embed principal muda; não existem controles de cliente.
9. **Pago / finalizado / encerrado** — mensagem curta e ticket bloqueado ao terminar.
10. **`/perfil`** — perfil efêmero, totais e últimas cinco vendas.
11. **`/vender`** — abre exatamente o mesmo modal do painel.

### Staff

1. **AGUARDANDO** — botão principal `Assumir`; Select `Ações` com notificar e encerrar.
2. **EM_ANALISE** — botão principal `Continuar para pagamento`; Select `Ações` com notificar e encerrar.
3. **Notificar cliente** — modal `Mensagem`; envia DM com link do ticket e trata DM fechada.
4. **Encerrar venda** — modal `Motivo`; encerra, registra, gera transcript quando habilitado e bloqueia.
5. **PAGAMENTO** — embed dedicado; botão `Confirmar pagamento`; Select `Ações` com voltar, notificar e encerrar.
6. **PAGO** — botão único `Finalizar venda`.
7. **`/fila`** — lista efêmera e compacta das vendas ativas.

### Admin / Manager

1. **`/botconfig`** — embed efêmero de resumo e Select principal com as dez áreas pedidas.
2. **Painel** — dois controles compactos: textos e destaque/preço, respeitando o limite de campos dos modais.
3. **Canais** — quatro Channel Selects: painel, categoria de tickets, logs e transcripts.
4. **Cargos** — dois Role Selects: Staff e Admin/Manager.
5. **Preços** — modal com preço em reais, mínimo e máximo (máximo entre 1 e 25).
6. **Aparência** — controles para cor/URLs e IDs opcionais dos ícones customizados.
7. **Mensagem do carrinho** — texto/delay e Select para ativação, destino (`ticket`, `DM`, `ambos`) e auto-delete; auto-delete vale para a mensagem no ticket.
8. **Logs** — toggles e seletores de canal de logs/transcripts.
9. **Gerais** — prefixo, máximo de vendas ativas, delay e toggles enxutos.
10. **Publicar / Atualizar painel** — atualiza o ID salvo; recria somente se a mensagem sumiu.
11. **Diagnóstico** — checklist de recursos, permissões, SQLite, painel, Views e intents.

## Estados e transições

| Estado | Ações válidas | Próximo estado |
|---|---|---|
| `AGUARDANDO` | editar carrinho, cancelar, assumir, notificar, encerrar | `EM_ANALISE` ou `ENCERRADO` |
| `EM_ANALISE` | editar carrinho, cancelar, continuar, notificar, encerrar | `PAGAMENTO` ou `ENCERRADO` |
| `PAGAMENTO` | voltar, confirmar pagamento, notificar, encerrar | `EM_ANALISE`, `PAGO` ou `ENCERRADO` |
| `PAGO` | finalizar | `FINALIZADO` |
| `FINALIZADO` | nenhuma | terminal |
| `ENCERRADO` | nenhuma | terminal |

Cada transição crítica usa `UPDATE ... WHERE status = estado_esperado`, transação SQLite e `interaction_id` único em eventos. Um clique repetido retorna o estado atual e não repete efeitos.

## Permissões

| Papel | Capacidades |
|---|---|
| Cliente | abrir venda, ver o próprio ticket, editar/cancelar antes de pagamento, consultar perfil |
| Staff | ver tickets, fila, assumir, notificar, encerrar e avançar somente vendas assumidas por si |
| Admin/Manager | todas as ações de Staff, override de responsável, `/botconfig` e diagnóstico |
| Administrador Discord / Manage Guild | acesso administrativo de recuperação, inclusive antes de um cargo Admin ser configurado |
| Bot | criar/editar canais e overwrites, enviar/embutir/anexar arquivos, ler histórico e gerenciar os próprios componentes |

O ticket nega `view_channel` a `@everyone` e permite cliente, Staff, Admin e bot. Ao terminar, envio do cliente e Staff é bloqueado; Admin e bot preservam acesso.

## Persistência e recuperação

- Views estáticas e persistentes, todas com `timeout=None` e `custom_id` explícito e único.
- Callbacks localizam a venda pelo canal, então não carregam todas as vendas em memória.
- `setup_hook` registra painel e Views de todos os estados antes de sincronizar comandos.
- O tópico do canal contém `SKSTORE_SALE_ID=<id>`; se houver reinício entre criar canal e salvar `channel_id`, a recuperação encontra o canal em vez de duplicá-lo.
- Vendas ativas sem mensagem principal têm a interface recriada; mensagens existentes são restauradas/editadas conforme o estado salvo.
- Um único agendador consulta o próximo prazo persistido para auto-delete da mensagem automática ou auto-close do ticket; não há polling frequente.
- A recuperação percorre vendas em lotes de 100 por ID; o histórico inteiro nunca é carregado na RAM.

## Banco de dados

- `schema_migrations`: versão das migrações.
- `users`: identidade por servidor e timestamps.
- `sales`: estado, canal/mensagem, cliente/Staff, centavos, Pix, código, timestamps e prazos.
- `sale_accounts`: endereço original, forma canônica e remoção lógica.
- `settings`: configuração por servidor.
- `events`: auditoria e idempotência por interação.

Índices cobrem fila, perfil, canal, cliente/estado e contas ativas. A conexão única do `aiosqlite` usa WAL, foreign keys e busy timeout.

## Proteções

- Endereço aceito somente em `gmail.com`/`googlemail.com`, sem senha ou dado de autenticação.
- Forma canônica em minúsculas, domínio `gmail.com` e pontos ignorados no nome para detectar aliases duplicados.
- Duplicidade no formulário, na mesma venda e em qualquer venda ativa do mesmo servidor é recusada em transação.
- Locks por venda/cliente e por publicação de painel evitam concorrência local; constraints e updates condicionais garantem correção após restart ou múltiplas instâncias acidentais.
- Canal e mensagem recebem IDs persistidos; criação e finalização são recuperáveis e idempotentes.
- Mensagens e logs usam `AllowedMentions` restrito e não registram tokens ou segredos.

## Intents e limites oficiais adotados

- `guilds` e `guild_messages` para canais, componentes e histórico.
- `message_content` habilitado e documentado como necessário para transcript completo do texto enviado por pessoas.
- `members` e `presences` desabilitados para reduzir cache e RAM.
- Custom IDs permanecem abaixo de 100 caracteres.
- Selects permanecem em no máximo 25 opções; botões em no máximo cinco por linha; textos de modal em no máximo 4.000 caracteres.
- Uma interação recebe uma resposta inicial; mensagens posteriores usam follow-up.

## Arquitetura de módulos

```text
main.py
app/
  bot.py
  config.py
  constants.py
  database.py
  models.py
  cogs/
  views/
  modals/
  services/
  utils/
tests/
docs/
```

Serviços isolam vendas, tickets, painéis, logs, transcripts, diagnóstico e manutenção. Cogs contêm apenas comandos; Views/Modals validam identidade e delegam regras ao serviço.

## Decisões de UX derivadas da pesquisa

- Claim explícito reduz conflito entre atendentes; o banco aplica ownership e Admin pode sobrescrever.
- Formulário inicial tem somente três campos, evitando abandono em mobile.
- Transcript e eventos formam trilha de auditoria; não existe dashboard pesado.
- O painel é idempotente e a configuração é agrupada por Select, seguindo a hierarquia visual de uma ação primária por etapa.
- A interface usa Embeds V1 e componentes clássicos suportados pelo `discord.py`, evitando depender de componentes novos quando não agregam ao fluxo.
