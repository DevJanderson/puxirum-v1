# Puxirum — Documento de design

> **Status:** rascunho da Fase 0 (v0.1), 2026-11-07. Nenhum código foi escrito ainda.
> Este documento é a referência de todas as fases seguintes. Mudanças de rumo entram aqui antes de entrar no código.

## Sumário

1. [O nome](#1-o-nome)
2. [Objetivo e escopo da v1](#2-objetivo-e-escopo-da-v1)
3. [Princípios de engenharia](#3-princípios-de-engenharia)
4. [O que aprendemos no piloto](#4-o-que-aprendemos-no-piloto)
5. [Arquitetura](#5-arquitetura)
6. [Ciclo de vida de um job](#6-ciclo-de-vida-de-um-job)
7. [Papéis dos agentes](#7-papéis-dos-agentes)
8. [Contrato de arquivos](#8-contrato-de-arquivos)
9. [O gate](#9-o-gate)
10. [Integração com o GitHub](#10-integração-com-o-github)
11. [Integração com o tuios](#11-integração-com-o-tuios)
12. [Custos, tempo e métricas](#12-custos-tempo-e-métricas)
13. [Segurança](#13-segurança)
14. [Configuração](#14-configuração)
15. [Linha de comando](#15-linha-de-comando)
16. [Checklist de paridade](#16-checklist-de-paridade)
17. [Melhorias além da paridade](#17-melhorias-além-da-paridade)
18. [Critérios de sucesso do piloto](#18-critérios-de-sucesso-do-piloto)
19. [Fases, riscos e questões abertas](#19-fases-riscos-e-questões-abertas)

---

## 1. O nome

**Puxirum** é uma palavra da Amazônia, de origem tupi, para o **trabalho coletivo**: a comunidade se reúne e cada pessoa
cumpre uma parte da tarefa até ela ficar pronta. É o mesmo sentido de *mutirão* (do tupi antigo *motirõ*) e de *ajuri*
(nheengatu). O nome descreve a fábrica: vários agentes, cada um no seu papel, entregando juntos um trabalho de qualidade.

> Antes de qualquer publicação, confirmar a grafia e a etimologia com uma fonte de linguística indígena e citar a origem
> na documentação pública.

## 2. Objetivo e escopo da v1

**Objetivo:** transformar issues do GitHub em pull requests mesclados, com qualidade verificável, por meio de uma esteira
fixa de etapas. Scripts fazem o que é determinístico; agentes de IA fazem só o que exige julgamento.

**Escopo da v1:**

| Item | Decisão |
|---|---|
| Linguagem | Python 3.11+ (por causa do `tomllib`), **somente biblioteca padrão** |
| Executor de agentes | Claude Code (`claude`), um processo novo por tarefa |
| Bancada | **Somente tuios**, explorando todo o seu potencial |
| Fila | Issues do GitHub com a label `puxirum` |
| Saída | Um PR por issue, mesclado pelo GitHub |
| Fora da v1 | Outros executores (Codex, Gemini, opencode…), outras bancadas (herdr, tmux, VS Code, apps gráficos), deploy |

**Regra de propriedade intelectual (clean room):** o Puxirum é escrito do zero. Ideias e arquitetura da fábrica de
referência (zazencodes, GPLv3) podem inspirar o design; **nenhum código ou texto de prompt dela é copiado**.

## 3. Princípios de engenharia

1. **Determinismo onde for possível.** Fila, estados, transições, gate, merge, abertura de janelas e medição de custo são
   código Python. IA é chamada só para decidir, especificar, construir e revisar.
2. **Um único escritor de estado.** Só o núcleo grava o estado de um job, com trava e gravação atômica. Toda mudança de
   estado verifica antes a **prova** que a justifica.
3. **O contrato é o arquivo.** Cada agente recebe caminhos, lê arquivos e escreve **um** arquivo com um cabeçalho fixo. O
   núcleo confia no arquivo e no gate, nunca na conversa.
4. **Contexto descartável.** Cada execução de agente começa limpa. Nenhuma sessão acumula histórico entre etapas ou jobs.
5. **Entrada é dado, não instrução.** O texto vindo do GitHub chega aos agentes sempre citado e marcado como dado.
6. **Tudo retomável.** Se qualquer processo morrer, o próximo `puxirum run` continua cada job da etapa em que parou.
7. **Tudo medido.** Custo e tempo por agente, por etapa, por job e por execução, **incluindo** a coordenação.
8. **Falha explícita.** Uma transição ilegal ou uma prova ausente é recusada com o motivo. Nada é contornado em silêncio.
9. **O humano decide o que é dele.** Decisões de produto, dinheiro, acesso e infraestrutura sobem para a pessoa.
10. **Núcleo independente.** O núcleo não conhece detalhes do Claude Code nem do tuios: fala com eles por adaptadores.

## 4. O que aprendemos no piloto

O piloto rodou a fábrica de referência no projeto `todo-factory` em 2026-11-07. Ele é a nossa **linha de base**.

| Medida | Valor |
|---|---|
| Issues | 6 (4 entregues, 1 rejeitada, 1 pediu informação e depois foi entregue) |
| Tempo total | 1h18min (incluindo esperas humanas) |
| Custo total (equivalente à API) | **US$ 8,53** |
| Custo dos agentes | US$ 2,45 (29%) |
| **Custo da coordenação** (sessão de IA orquestradora) | **US$ 6,08 (71%)** |
| Job simples | 4–5 min, ~US$ 0,30–0,40 |
| Job difícil (interface) | 5 rodadas, 28 min, US$ 1,34 |

**Funcionou:** intake como porta de entrada; gate determinístico antes de revisar e antes de mesclar; revisores que
reproduzem problemas no navegador; escalada para humano com decisão de produto; retomada a partir de arquivos;
roteamento de modelos por risco.

**Atritos:** coordenação cara e cumulativa; merges bloqueados pelo modo auto do Claude Code de forma inconsistente;
agentes ignorando instruções secundárias (o builder nunca abriu a janela do tuios); revisor de UX aprovando sem abrir a
página; custo mostrado pela fábrica ignorava a coordenação; specs de interface sem casos de borda (títulos longos).

## 5. Arquitetura

```
                 ┌──────────────────── núcleo (Python) ────────────────────┐
                 │ fila · estados · transições · gate · merge · custos     │
                 └───────┬──────────────────────┬──────────────────┬───────┘
                         │                      │                  │
              Executor (quem faz)      Visibilidade universal    Bancada (onde se vê)
              v1: Claude Code          arquivos · status ·       v1: tuios
              depois: codex, gemini…   notificações              depois: herdr, tmux…
```

- **Núcleo:** decide o que acontece e quando. Não importa nada específico de executor ou bancada.
- **Executor:** sabe montar e rodar um agente (`claude -p …`), com modelo, ferramentas permitidas e prompt; sabe medir o
  custo a partir dos registros da própria ferramenta.
- **Bancada (tuios):** abre e fecha janelas, espera agentes e comandos, mostra status, pergunta à pessoa e avisa.
- **Visibilidade universal:** os arquivos do job, `puxirum status` e as notificações funcionam mesmo sem a bancada.

**Quem abre as janelas é o núcleo, nunca o agente.** O agente não precisa saber que o tuios existe. Isso elimina a classe
de problema em que o agente ignora a instrução de usar a bancada.

**Concorrência:** o núcleo roda como um processo único por repositório (com trava), em laço: lê a fila, avança cada job
um passo, espera eventos ou tempos limite, repete. Jobs diferentes avançam em paralelo até o limite de vagas.

## 6. Ciclo de vida de um job

### Estados

| Estado | Significado | Ocupa vaga? |
|---|---|---|
| `intake` | O agente de entrada avalia a issue | sim |
| `needs-info` | Esperando o autor responder na issue | não |
| `spec` | O agente de especificação escreve a spec | sim |
| `build` | O builder implementa na rodada N | sim |
| `gate` | O núcleo roda as verificações | sim |
| `review` | Os revisores roteados avaliam a rodada N | sim |
| `approve` | O approver decide entre mesclar e escalar | sim |
| `merging` | O núcleo sincroniza, verifica de novo e mescla | sim |
| `needs-human` | Esperando uma decisão da pessoa | não |
| `merged` | Terminado com o PR mesclado | não |
| `rejected` | Terminado sem entrega | não |

### Transições permitidas

```
intake      → spec | needs-info | rejected | needs-human
needs-info  → intake | rejected
spec        → build | needs-human
build       → gate | needs-human
gate        → review | build | needs-human
review      → approve | build | needs-human
approve     → merging | needs-human
merging     → merged | needs-human
needs-human → intake | spec | build | rejected
(qualquer estado não terminal) → merged, quando o PR já foi mesclado no GitHub
```

Cada transição tem uma **prova exigida** (ver a seção 16, itens C14) e **efeitos** no GitHub e no tuios, executados pelo
núcleo dentro da própria transição.

### Rodadas

Uma rodada é `build → gate → review`. O limite padrão é 3 rodadas por job. Ao estourar, o job vai para `needs-human`.
Um retorno da pessoa abre um novo bloco de rodadas.

### Escaladas

Um job vai para `needs-human` com a prova da própria etapa (build `BLOCKED`, última rodada com gate `FAIL` ou `CHANGES`, approver `ESCALATE`) ou com um **motivo explícito do núcleo**, para falhas que nenhum arquivo registra (agente que travou ou insistiu em arquivo malformado, conflito no merge, efeito que falhou). Cada escalada vira `escalation-<k>.md`. O retorno `feedback-<k>.md` devolve o job para onde ele parou: `intake` ou `spec`, se escalou de lá; `build` nos demais casos.

### Efeitos pendentes

`advance` é pura: confere a prova e devolve o novo job mais a lista de efeitos (comentários, labels, worktree, push, PR). O núcleo salva o job com os efeitos em `pending` e só então os executa, um a um, retirando cada um da lista. Cada efeito tem uma chave única (`<job>:<transição>:<n>`), e o comentário no GitHub leva essa chave no marcador. Assim, depois de uma queda, nada é perdido nem repetido. Nenhuma transição nem agente roda enquanto houver efeito pendente.

## 7. Papéis dos agentes

Todos os prompts são escritos do zero, em inglês, neutros quanto à ferramenta. Cada papel lê arquivos e escreve
**exatamente um** arquivo. Modelos padrão = o "meio-termo" validado no piloto.

| Papel | Lê | Escreve | Cabeçalho (1ª linha) | Modelo padrão | Ferramentas |
|---|---|---|---|---|---|
| intake | `issue.md`, código, `AGENTS.md` | `intake.md` | `DECISION: ACCEPT\|NEEDS-INFO\|REJECT` (+ `RISK`, `SURFACES`, `RESCOPED`) | sonnet | leitura + escrita do próprio arquivo, **sem shell** |
| spec | `issue.md`, `intake.md`, código | `spec.md` | `# <título>` (sem cabeçalho) | sonnet | leitura + escrita |
| builder | spec, rodadas anteriores, retornos | código, commits locais, `build.md` | `STATUS: READY\|BLOCKED` | sonnet | completas no worktree |
| revisor de código | spec, build, diff | `round-N/review-code.md` | `VERDICT: PASS\|CHANGES` | haiku (risco baixo) / sonnet | leitura + shell restrito |
| revisor de UX | idem + app rodando | `round-N/review-ux.md` | `VERDICT: …` | sonnet | idem + navegador |
| revisor de UI | idem + app rodando | `round-N/review-ui.md` | `VERDICT: …` | haiku | idem + navegador |
| revisor de segurança | idem | `round-N/review-security.md` | `VERDICT: …` | opus | leitura + shell restrito |
| approver | tudo do job + diff | `decision.md` | `DECISION: APPROVE\|ESCALATE` | sonnet | leitura + shell restrito |

**Mudanças em relação à referência, nascidas do piloto:**

- **O núcleo sobe o servidor de desenvolvimento** (numa janela do tuios) antes de chamar o builder ou os revisores de
  interface, e entrega a URL no prompt. O agente nunca decide se sobe ou não.
- **Revisores de interface são obrigados a anexar evidência** (capturas de tela por largura) para dar `PASS`. Sem
  evidência, o núcleo trata o veredito como inválido.
- **A spec de mudanças com interface tem uma seção obrigatória de casos de borda** (texto longo, vazio, teclado, celular,
  tema escuro).

## 8. Contrato de arquivos

```
<repo>/
  .puxirum/
    config.toml              configuração do projeto (versionada)
    checks.sh                verificações do projeto (versionada, protegida)
    roles/*.md               prompts dos papéis (versionados)
    state/                   estado de execução (ignorado pelo git)
      jobs/<job-id>/
        job.json             estado do job (único escritor: o núcleo)
        events.jsonl         linha do tempo: transições, agentes, custos
        issue.md             a issue citada como dado
        intake.md  intake-<k>.md
        spec.md
        build.md
        round-<N>/checks.md  round-<N>/checks.log  round-<N>/review-<papel>.md
        round-<N>/evidence/  capturas de tela dos revisores
        feedback-<k>.md  decision.md  rejection.md
      runs/<run-id>.json     resumo de cada execução (custos, tempos)
  .worktrees/<job-id>/       worktree do job (ignorado pelo git)
```

**Cabeçalho:** linhas `CHAVE: valor` no topo, até a primeira linha em branco; em seguida `## Summary` com 3 a 5 tópicos.
O núcleo valida o cabeçalho de cada arquivo; um arquivo malformado é um veredito **inválido**, e não um `PASS`.

## 9. O gate

- Roda o `checks.sh` **da cópia principal** dentro do worktree do job, para que um branch não altere os critérios pelos
  quais é julgado.
- Falha se o branch **alterou ou apagou** um arquivo protegido (padrões `fnmatch` na configuração). Criar arquivos é
  permitido.
- Registra veredito, **commit testado**, duração e o final do log. Uma transição só aceita um gate do commit atual.
- Falha sem rodar nada quando o worktree tem mudanças não commitadas, porque o resultado não pertenceria a um commit.
- Tem tempo limite (`gate.timeout_s`). Roda num grupo de processos próprio e, ao terminar ou estourar o tempo, encerra o
  grupo inteiro, para que nenhum servidor ou processo filho fique vivo.
- Lê o diff com `-z --no-renames`: nomes com espaço funcionam, e renomear um arquivo protegido conta como apagá-lo.
- Anota em `## Notes` os arquivos que as próprias verificações deixaram alterados.
- Problemas que não são culpa do branch (script ausente, repositório quebrado) geram erro, não veredito; o núcleo escala
  com motivo.
- Roda depois de cada build e de novo, depois de sincronizar com o `main`, antes de mesclar.
- Revisores só são chamados quando o gate passa.

## 10. Integração com o GitHub

Via `gh` autenticado. A label `puxirum` define a fila; `puxirum:needs-info` e `puxirum:needs-human` marcam esperas.
Comentários do Puxirum levam um marcador invisível com a chave do efeito (`<!-- puxirum:<job>:<transição>:<n> -->`). Um comentário só conta como do Puxirum se tiver o marcador **e** for do operador: o autor da issue não consegue esconder a própria resposta colando o marcador. Somente comentários do autor da issue e do operador entram em
`issue.md`. Branches: `puxirum/<job-id>`. PR aberto como rascunho com `Closes #N`; marcado como pronto ao escalar ou
antes de mesclar; mesclado com o método configurado; branch apagado depois.

O git roda sempre com `LC_ALL=C`, para que mensagens e motivos de escalada sejam iguais em qualquer máquina.

**Merge sem trava:** como o merge é feito pelo núcleo em Python, e não por um agente, ele não depende do modo de
permissões de uma sessão de IA.

## 11. Integração com o tuios

Referência: tuios 0.12.1 (protocolo 1), lido em `tuios --skill all`, `tuios <cmd> --help` e `tuios list-verbs --json`.
O adaptador fala com o tuios por `tuios call <verbo> '<json>'`, que tem contrato estável, erros com código e nenhum
texto para raspar. Ele confere a versão do protocolo ao iniciar.

### 11.1 Regras do adaptador

- **Sempre passar `-s <sessão>`, `-w <id>` e `--cwd`.** Sem `-s`, um comando de fora age na sessão mais recente. Sem `-w`,
  alguns verbos agem no pane focado.
- **Guardar o UUID de cada janela** (`--print-id`), nunca o índice nem o nome, porque o índice muda quando outro pane
  fecha.
- **O tuios é espelho, nunca fonte da verdade.** O estado do job vive em `job.json`. Cards, notas e painel são
  atualizados pelo núcleo e podem ser perdidos sem prejuízo.
- **Sem tuios, o Puxirum funciona igual** (só sem bancada). Se `tuios ls` não responder, o executor roda os agentes como
  subprocessos comuns.

### 11.2 Mapa de recursos

| Necessidade do Puxirum | Recurso do tuios | Decisão v1 |
|---|---|---|
| Ver os agentes trabalhando | Nenhum pane por agente: os agentes rodam como processos do núcleo e gravam `stream-json`; o pane **Agentes** roda `puxirum feed`, que mostra uma linha por passo de todos eles | Uma janela só, de tamanho fixo, por mais agentes que rodem |
| Montar a bancada | `set-workspace-name`, `tml-open` (pane, no workspace do núcleo), `split-window` (lado `down` do painel para o log, lado `right` do log para o feed) e `send-text` para iniciar os dois | O núcleo monta ao iniciar e guarda os ids em `state/workbench.json` |
| Painel ao vivo | `tml-open` com estado vazio e `tml-patch` com os dados | Os dados só chegam por patch JSON: nada vindo de uma issue é lido como TML |
| Status por janela | `set-note` (≤200 bytes) | Ex.: `puxirum · 2 ativos · 1 aguardando · agentes US$ 0.63` |
| Avisar a pessoa | `ask-human` com `wait: false` | Um item no Inbox quando um job passa a esperar por alguém, uma vez por espera; o `[notify]` da pessoa leva ao celular |
| Saber se uma janela ainda existe | `get-window` e `tml-get` | Uma janela fechada pela pessoa é aberta de novo no próximo `refresh` |
| Servidores de desenvolvimento | Nenhum | Rodam em segundo plano, com o log no job; não ocupam pane |
| Quadro de tarefas | `task add/stage/...` | **Não usado na v1**: o painel já mostra os jobs |
| Worktrees | `tuios worktree new` / `fan` | **Não usados**: o Puxirum cria os próprios worktrees com caminho conhecido |
| Commit, push, merge | `ship commit/push/pr/merge` | **Não usados**: o fluxo é `git` + `gh` no núcleo |

### 11.3 Layout

Um workspace, nomeado `puxirum`, com quatro panes:

```
┌──────────────────┬──────────────────┐
│                  │      Painel      │
│   Claude Code    │       (TML)      │
│ (você, /puxirum) ├─────────┬────────┤
│                  │ Puxirum │Agentes │
│                  │(run.log)│ (feed) │
└──────────────────┴─────────┴────────┘
```

- **Claude Code**: a conversa da pessoa com a skill `/puxirum`, que consulta a fábrica e inicia `puxirum run` em
  segundo plano. Pode ser também um shell comum onde a pessoa roda `puxirum run`.
- **Painel**: números do topo (ativos, aguardando, mesclados, custo dos agentes, coordenação US$ 0.00) e as abas
  Jobs, Custos e Atenção.
- **Puxirum**: o log do núcleo, `tail -F` de `state/run.log`. Como o run roda em segundo plano, o log não aparece
  no pane da conversa.
- **Agentes**: o feed ao vivo de todos os agentes ativos.

O layout sai certo quando o workspace tem só o pane da conversa; com outros panes ele funciona, mas o núcleo avisa no
log que a disposição pode variar. Log e feed são abertos sempre juntos, para ficarem lado a lado embaixo do painel.
`puxirum workbench` monta a bancada sem rodar a fila; `puxirum run --no-workbench` a desliga.

### 11.4 Onde o núcleo roda

Em segundo plano, a partir do pane da conversa (a skill usa o `run_in_background` do Claude Code), ou num shell do
tuios. Em ambos os casos o processo herda o pane de quem o iniciou, que é o dono do painel. O pane precisa poder abrir
panes e superfícies (o grant padrão do modo `open`). Fora do tuios, ou com `--no-workbench`, o Puxirum roda igual, só
sem bancada. Um daemon que não fala o protocolo 1 é avisado no log, e a execução segue sem bancada.

**Um run por vez.** `puxirum run` segura `state/run.lock` do início ao fim, e um segundo run recusa. Sem isso, a
limpeza de órfãos do segundo mataria os agentes vivos do primeiro. `puxirum workbench` também recusa enquanto um run
trabalha, para não disputar o painel com ele.

### 11.5 Cuidados conhecidos

- **Uma superfície só aceita patch do pane que a abriu.** Por isso o painel é aberto pelo próprio `puxirum run`; uma
  execução seguinte, num pane novo, reabre o painel.
- **`list-windows` chama o id de `window_id`, e `get-window` chama de `id`.** O adaptador usa o nome de cada verbo.
- **Os testes nunca falam com o tuios real.** A suíte roda dentro de um pane e apaga as variáveis `TUIOS_*` antes de
  começar; num teste antigo, a bancada chegou a abrir painéis na sessão de quem rodava os testes.
- **O sandbox do builder monta marcadores** (`.bashrc`, `.claude/`) na worktree, visíveis só para ele. O prompt manda
  ignorá-los, e no disco sobra no máximo uma pasta vazia, que o git ignora.
- Grants **não são sandbox**: protegem só o uso do tuios. O sistema de arquivos é protegido pelo sandbox do builder,
  pelas ferramentas permitidas a cada papel e pelo gate.
- Uma sessão restaurada depois de reiniciar o daemon volta sem as superfícies. O núcleo reabre o painel a partir dos
  arquivos.

## 12. Custos, tempo e métricas

- **Por agente:** cada execução registra modelo, tokens (entrada, saída, cache) e custo equivalente, lidos dos registros
  do executor, e a duração.
- **Por etapa e por job:** somatórios em `job.json` e `events.jsonl`.
- **Por execução:** `runs/<run-id>.json` com o total, **incluindo** a coordenação (que deve ser ~US$ 0, porque é Python).
- **Relatório:** `puxirum report` mostra a comparação com execuções anteriores e com a linha de base do piloto.
- Os preços por modelo ficam na configuração e o núcleo **não para** quando encontra um modelo sem preço: registra
  "sem preço" e avisa.

## 13. Segurança

- A fila só aceita issues com a label, que exige acesso de triagem ou escrita no repositório.
- Texto do GitHub é sempre citado e marcado como dado. O intake não tem shell.
- Agentes só enviam o próprio branch. Só o núcleo mescla. O Puxirum nunca faz deploy.
- Cada janela de agente recebe **permissões mínimas** do tuios (detalhado na seção 11).
- Segredos não entram em prompts nem em arquivos de estado.
- Os agentes não recebem credenciais: o ambiente perde `SSH_AUTH_SOCK`, tokens do `gh` e auxiliares de credencial do
  git, e `GIT_SSH_COMMAND=false`. Regras de permissão sobre comandos não bastam (um teste real mostrou que
  `env -u GIT_SSH_COMMAND git ls-remote` ainda autenticava com as chaves de `~/.ssh`). Por isso o shell do builder roda
  no **sandbox do sistema operacional do Claude Code** (bubblewrap no Linux), com `failIfUnavailable` e sem saída do
  sandbox: não lê `~/.ssh` e outros segredos, não acessa a rede além de `[agents] network` (padrão: nenhum host) e só
  escreve na worktree e nas partes do `.git` que um commit no próprio branch exige. Nunca em `.git/hooks` ou
  `.git/config`.
- O git do núcleo roda com `core.hooksPath=/dev/null`, para que nada que um agente deixe no repositório seja executado
  fora do sandbox.

## 14. Configuração

`.puxirum/config.toml` (lido com `tomllib`): concorrência, limite de rodadas, branch base, método de merge, labels,
roteamento de revisores e modelos por risco e superfície, caminhos protegidos, portas, preços, comando do servidor de
desenvolvimento e workspace do tuios para os servidores.

Limites de robustez em `[queue]`: `agent_attempts` (padrão 2) é quantas vezes um agente roda antes de o job escalar, e `effect_attempts` (padrão 3) é quantas falhas um efeito aguenta antes de ser abandonado com escalada. Cada job recebe uma faixa de portas `ports.base + ((n - 1) mod 100) × ports.step`: o builder usa a primeira, e cada revisor a seguinte.

O servidor de desenvolvimento vem de `[app]`: `setup` (ex.: `npm ci`), `command` (precisa conter `{port}`) e `ready_timeout_s`. O núcleo o sobe para o builder (em mudanças de interface) e para cada revisor de UX e UI, cada um na sua porta, espera a porta responder (IPv4 ou IPv6), entrega a URL e derruba o grupo de processos no fim. Com `[app]` configurado, um `PASS` de UX ou UI sem captura `ux-*`/`ui-*` em `round-N/evidence/` é recusado e o revisor roda de novo.

Uma execução de agente só conta se ele sair com 0 **e** reescrever o arquivo de saída (o núcleo compara `mtime` e hash antes e depois). Isso impede que um `build.md` `READY` da rodada anterior seja aceito como se fosse novo.

## 15. Linha de comando

| Comando | Faz |
|---|---|
| `puxirum init` | Instala o Puxirum num projeto (pastas, configuração, labels, skill `/puxirum`, verificação) |
| `puxirum run [N]` | Processa a fila inteira, ou só a issue N; retoma o que estiver em andamento |
| `puxirum status` | Mostra os jobs, as etapas e o que espera pela pessoa |
| `puxirum workbench` | Monta a bancada do tuios ao lado do pane atual, sem rodar a fila |
| `puxirum feed` | Segue todos os agentes ativos, uma linha por passo (é o pane Agentes) |
| `puxirum feedback N` | Envia o retorno da pessoa a um job escalado |
| `puxirum reject N` | Rejeita um job em espera, com o motivo |
| `puxirum report` | Custos e tempos por job, por execução e comparados com a linha de base |
| `puxirum doctor` | Verifica pré-requisitos: `gh`, `claude`, tuios, labels, `checks.sh`, skill |

A skill `/puxirum` (`.claude/skills/puxirum/SKILL.md`, instalada pelo `init`) é a forma conversacional de usar esses
comandos: ela consulta, explica e repassa as decisões da pessoa, mas nunca faz o trabalho de um job.

## 16. Checklist de paridade

Cada item é uma capacidade observada na fábrica de referência, descrita com as nossas palavras. A v1 só está pronta
quando todos estão marcados e têm teste.

Legenda: ✅ F1 = coberto por teste na Fase 1; 🟡 = a parte do núcleo está coberta, falta a parte do agente ou da bancada; ⏳ = fica para a fase indicada.

| # | Capacidade | Teste de aceitação | Estado | Coberto por |
|---|---|---|---|---|
| **A** | **Fila e entrada** | | | |
| A1 | Fila = issues abertas com a label | Issue sem label não vira job | ✅ F1 | test_closed_or_unlabeled_issues_are_skipped |
| A2 | Processar a fila toda, uma issue, ou conversar com a fábrica | `run`, `run N`, `feedback`/`reject` funcionam | ✅ F1 | test_run_one_issue, test_cli |
| A3 | Limite de jobs simultâneos; esperas não ocupam vaga | Com limite 1 e um job em `needs-info`, outro job começa | ✅ F1 | test_waiting_jobs_do_not_hold_a_slot |
| A4 | A fila classifica: nova, retomar, aguardar vaga, esperando, ignorar | `status` mostra as cinco situações em cenário montado | ✅ F1 | test_concurrency_one…, test_closed_or_unlabeled… |
| A5 | Detecta resposta do autor após a última pergunta | Comentário do autor move `needs-info` para retomada | ✅ F1 | test_needs_info_waits_then_resumes… |
| A6 | Detecta PR mesclado manualmente e fecha o job | Merge manual leva o job a `merged` | ✅ F1 | test_a_person_merging_the_pr_finishes_the_job |
| A7 | Ignora jobs cuja issue fechou ou perdeu a label | Fechar a issue tira o job da fila | ✅ F1 | test_closed_or_unlabeled_issues_are_skipped |
| **B** | **Segurança da entrada** | | | |
| B8 | Issue citada como dado, com aviso | `issue.md` todo citado e com o aviso | ✅ F1 | test_render_quotes_everything… |
| B9 | Só comentários do autor e do operador | Comentário de terceiro não aparece em `issue.md` | ✅ F1 | test_render_quotes…, test_needs_info… |
| B10 | Comentários do Puxirum marcados | O marcador é reconhecido e não conta como resposta | ✅ F1 | test_replied_since_question (marcador + operador) |
| B11 | Intake sem shell | O executor não concede shell ao intake | ✅ F2 | test_intake_has_no_shell_and_writes_only_its_file; teste real (Bash indisponível, escrita fora do próprio arquivo negada) |
| **C** | **Estados e transições** | | | |
| C12 | Os 11 estados | Enumeração completa no núcleo | ✅ F1 | test_machine |
| C13 | Tabela de transições; movimento ilegal recusado com motivo | Teste para cada transição ilegal | ✅ F1 | test_every_illegal_transition_is_refused |
| C14 | Cada transição confere a prova (decisão do intake, build pronto, árvore limpa, branch enviado, um PR, gate do commit atual, revisões completas e válidas) | Teste para cada prova ausente | ✅ F1 | test_machine (uma prova ausente por teste) |
| C15 | Único escritor, com trava e gravação atômica | Dois processos concorrentes não corrompem o estado | ✅ F1 | test_lock_serialises_writers_across_processes |
| C16 | Id sequencial e legível | `004-editar-titulo` | ✅ F1 | test_create_assigns_sequential_ids |
| C17 | Efeitos no GitHub dentro da transição | Labels e comentários conferidos em teste | ✅ F1 | test_world (efeitos pendentes idempotentes) |
| **D** | **Intake** | | | |
| D18 | Aceitar, pedir informação, rejeitar; reduzir escopo | Três issues de exemplo dão os três resultados | ✅ F1 | test_reject_at_intake, test_needs_info…, test_happy_path |
| D19 | Risco e superfícies | `intake.md` válido contém os campos | ✅ F1 | test_intake_accept |
| D20 | Decisão comentada na issue | Comentário aparece com o marcador | ✅ F1 | test_happy_path |
| D21 | `needs-info` com label; reavaliação arquiva a decisão anterior | `intake-1.md` existe após a resposta | ✅ F1 | test_needs_info_waits_then_resumes… |
| D22 | Rejeitar remove a label e explica | Conferido no GitHub | ✅ F1 | test_reject_at_intake |
| **E** | **Roteamento** | | | |
| E23 | Revisores e modelos por risco e superfície, via configuração | Tabela de casos → conjunto esperado | ✅ F1 | test_route |
| **F** | **Spec** | | | |
| F24 | Spec com contexto, requisitos, critérios verificáveis, fora de escopo, premissas | Validação das seções | ✅ F1/F2 | contrato validado (test_spec); prompt `roles/spec.md` (test_every_example_in_a_prompt_passes_the_contract) |
| F25 | Escopo do intake obrigatório | Prompt e revisão conferem | ✅ F2 | o spec trata o escopo do intake como obrigatório, o revisor só pede mudanças dentro dele e o approver confere (test_role_specifics) |
| **G** | **Build** | | | |
| G26 | Worktree e branch próprios a partir do `main` remoto | Criados na transição para `spec` | ✅ F1 | test_accept_drains_into_a_comment_and_a_worktree |
| G27 | Confere o branch, instala dependências, menor mudança, não toca protegidos | Gate falha se tocar protegido | ✅ F1/F2 | protegidos no gate (F1); setup e menor mudança no prompt do builder (test_role_specifics) |
| G28 | Commits pequenos; o **núcleo** envia o branch e abre o PR rascunho com `Closes #N` (o agente não toca no remoto) | Conferido no GitHub | ✅ F1 | test_push_and_ensure_pr, test_happy_path |
| G29 | `build.md` com evidência por critério e log de rodadas | Validação das seções | ✅ F1/F2 | contrato validado; evidência por critério no prompt (test_every_example_in_a_prompt_passes_the_contract) |
| G30 | `BLOCKED` com motivo | Leva a `needs-human` com o motivo | ✅ F1 | test_blocked_builder_escalates |
| G31 | Rodadas seguintes com contexto do histórico | Builder recebe os arquivos da rodada anterior | ✅ F2 | test_builder_round_two_after_a_gate_failure, test_builder_round_two_after_reviews, test_builder_after_feedback |
| G32 | Verificação antes de o builder terminar | O executor roda o `checks.sh` ao fim do builder | ✅ F2 | hook Stop (test_hook, test_only_the_builder_gets_the_stop_hook); teste real: bloqueou, o builder corrigiu, passou |
| G33 | Portas exclusivas por job | Dois jobs não colidem | ✅ F1 | test_agents_get_their_paths_and_models |
| **H** | **Gate** | | | |
| H34 | `checks.sh` da cópia principal | Branch que altera o `checks.sh` não muda o resultado | ✅ F1 | test_uses_the_main_checkouts_script |
| H35 | Falha com protegido alterado ou apagado | Teste dedicado | ✅ F1 | test_protected_paths, test_renaming… |
| H36 | Registra veredito, commit, duração e log | Conteúdo do `checks.md` | ✅ F1 | test_pass, test_fail_on_exit_code |
| H37 | Revisores só depois de gate PASS | Sem revisores após FAIL | ✅ F1 | test_gate_failure_sends_the_job_back_to_build |
| **I** | **Revisão** | | | |
| I38 | Revisores em paralelo, esperando todos | Transição só com todos os vereditos | ✅ F1 | test_reviewers_run_in_parallel_and_all_must_pass |
| I39 | Quatro olhares: código, UX, UI, segurança | Roteamento chama os corretos | ✅ F1 | test_route, test_reviewers_run_in_parallel… |
| I40 | UX e UI usam o app no navegador, em computador e celular | Evidência anexada obrigatória | ✅ F2 | servidor pelo núcleo, capturas a 1280px e 375px obrigatórias (test_a_pass_without_screenshots_is_not_accepted, test_role_specifics) |
| I41 | A partir da rodada 2, conferem os próprios apontamentos | Prompt recebe a revisão anterior | ✅ F2 | test_reviewer_sees_its_previous_review |
| I42 | PASS/CHANGES, bloqueante separado de observação | Validação do formato | ✅ F1 | test_review (contrato) |
| **J** | **Rodadas e escalada** | | | |
| J43 | Limite de rodadas; escalada com motivo | Estourar leva a `needs-human` | ✅ F1 | test_rounds_run_out_then_feedback_grants_new_ones |
| J44 | Retorno da pessoa registrado e renova o limite | `feedback-1.md` e novo bloco de rodadas | ✅ F1 | test_rounds_run_out_then_feedback_grants_new_ones |
| J45 | Pessoa pode rejeitar job em espera; fecha PR e apaga branch | Conferido no GitHub | ✅ F1 | test_reject_an_escalated_job |
| **K** | **Approver e merge** | | | |
| K46 | Approver confere critérios, gate, revisões; escala casos sensíveis | Casos de exemplo | ✅ F1/F2 | fluxos APPROVE/ESCALATE (F1); critérios e casos sensíveis no prompt `roles/approver.md` (test_role_specifics) |
| K47 | Sincroniza com `main`, gate de novo, envia, mescla pelo `gh`, apaga o branch | Conferido no GitHub | ✅ F1 | test_happy_path |
| K48 | Conflito ou gate falho após sincronizar → `needs-human` | Teste com conflito montado | ✅ F1 | test_conflict_with_main…, test_gate_failure_after_syncing… |
| K49 | Remove o worktree ao terminar | Pasta some em `merged`/`rejected` | ✅ F1 | assertMerged, test_reject_an_escalated_job |
| **L** | **Visibilidade e retomada** | | | |
| L50 | Cada arquivo começa com resumo de 3 a 5 tópicos | Validação do formato | ✅ F1 | test_summary_rules |
| L51 | Painel com cartões, rodadas, risco, custo, tempo e arquivos | Painel no tuios (seção 11) | ✅ F3 | painel TML com jobs, etapa, rodada, custo, tempo, PR, custos por papel e atenção (test_workbench); teste real no tuios |
| L52 | Resumo em tabela no terminal | `puxirum status` | ✅ F1 | test_cli (status) |
| L53 | Custo e tempo por job | `puxirum report` | ✅ F2 | test_report (custo por papel e modelo, tempo ativo e de espera, execuções); custo real lido do `claude -p` |
| L54 | Retomada total após morte do processo | Matar o processo no meio e retomar | ✅ F1 | test_agent_crash_resumes_in_a_new_engine |
| **M** | **Garantias** | | | |
| M55 | Nunca deploy; só o próprio branch; merge só pelo comando oficial; um PR por issue | Revisão de código e testes | ✅ F2 | núcleo faz push/PR/merge, push nunca forçado; agentes sem credenciais e shell do builder no sandbox (test_claude; teste real: `ssh` e `git ls-remote` ao GitHub falham) |

## 17. Melhorias além da paridade

| # | Melhoria | Origem |
|---|---|---|
| M1 | Orquestrador determinístico em Python: coordenação sem custo de IA | 71% do custo do piloto |
| M2 | Contexto descartável: cada agente é um processo novo | Sessão única acumulando histórico |
| M3 | Merge feito pelo núcleo, sem depender do modo de permissões | Merges bloqueados no modo auto |
| M4 | O núcleo sobe e derruba os servidores de desenvolvimento | Builder nunca abriu a janela |
| M5 | Evidência obrigatória para revisores de interface | UX aprovou sem abrir a página |
| M6 | Casos de borda obrigatórios na spec de interface | 5 rodadas na edição de título |
| M7 | Custo total, incluindo coordenação, por execução e comparado | Resumo da referência omitia 71% |
| M8 | Cada agente numa janela própria do tuios, com permissões mínimas | Subagentes invisíveis |
| M9 | Linha do tempo de eventos por job (`events.jsonl`) | Monitor externo improvisado no piloto |
| M10 | Arquivo malformado é inválido, não aprovado | Robustez |
| M11 | `puxirum doctor` para pré-requisitos | Falhas de ambiente no piloto (SSH, `gh`, `agent-browser`) |
| M12 | Fechar a issue rejeitada, se configurado | Issue #2 ficou aberta |
| M13 | Agentes não tocam no remoto: o núcleo faz push, PR e merge | Menos permissões, menos variação |
| M14 | Efeitos pendentes com chave idempotente | Na referência, uma queda entre comentar e salvar duplicava o comentário |
| M15 | Escalada de qualquer etapa ativa, com retomada no ponto da falha | A referência só escalava a partir de build em diante |
| M16 | Revisores e approver não podem mover o HEAD (conferido na transição) | Robustez |

## 18. Critérios de sucesso do piloto

Na Fase 4, o Puxirum roda no `todo-factory` com **issues equivalentes** às do piloto. A v1 é aceita se:

1. **Paridade:** todos os itens da seção 16 têm teste e passam.
2. **Resultado:** as issues têm o mesmo desfecho esperado (entregar, rejeitar, pedir informação, escalar).
3. **Custo:** o total fica **abaixo de US$ 4,27**, a metade da linha de base de US$ 8,53, com a coordenação perto de zero.
4. **Tempo:** um job simples leva no máximo o mesmo que no piloto (~5 min).
5. **Visibilidade:** todo agente aparece no feed da bancada, todo servidor tem log no job, e cada etapa aparece na
   nota e no painel (layout da seção 11.3).
6. **Robustez:** matar o processo no meio de um job e rodar de novo retoma sem perder nada.

## 19. Fases, riscos e questões abertas

| Fase | Entrega |
|---|---|
| 0 | Este documento |
| 1 | Núcleo: fila, estados, transições, gate, merge, GitHub, com agentes falsos e testes |
| 2 | Executor Claude Code e os prompts dos papéis |
| 3 | Bancada tuios completa |
| 4 | Piloto no `todo-factory` e comparação com a linha de base |

**Riscos:**

- O formato dos registros do Claude Code, usado para medir custo, não é uma interface documentada e pode mudar.
- Rodar `claude -p` em modo não interativo exige configurar permissões por papel com cuidado.
- O sandbox depende do bubblewrap e do socat; sem eles, o builder falha de propósito (`failIfUnavailable`) e o
  `doctor` precisa avisar.
- Recursos do tuios evoluem rápido; o adaptador precisa conferir a versão.

**Questões abertas:**

- Num pane com `claude -p` como processo único, os hooks do Claude Code reportam estado ao tuios? (Testar na Fase 3.
  Não é crítico, porque o exit code é a verdade.)
- Formato exato do JSON de `new-window --json` e dos eventos `agent-state`/`attention` (confirmar com `list-verbs` na
  Fase 3).
- Se o núcleo reiniciar, ele consegue continuar atualizando o painel TML que abriu antes? Se não, ele reabre o painel.
- O que acontece com um `new-window --wait` em curso se o daemon do tuios reiniciar? O executor deve tratar como falha
  retomável.
- Painel web somente leitura, além do TML, para quem estiver fora do terminal? (Fora da v1, a menos que seja barato.)
