<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/logo-lockup.gif">
    <source media="(prefers-color-scheme: light)" srcset="docs/images/logo-lockup-light.gif">
    <img src="docs/images/logo-lockup.gif" alt="OpenProgram" width="440">
  </picture>
</p>

<!-- Compatibility anchors for existing incoming links. -->
<a id="1-agentic-function-the-primitive-everything-else-is-built-on"></a>
<a id="2-dag-context-for-native-multi-agent-systems"></a>
<a id="3-agentic-workflow-for-trustworthy-self-evolving-agents"></a>
<a id="4-event-infrastructure-for-proactive-agents"></a>
<a id="integrated-projects"></a>
<a id="why-openprogram"></a>
<a id="1-agentic-function--the-primitive-everything-else-is-built-on"></a>
<a id="2-dag-context--for-native-multi-agent-systems"></a>
<a id="3-agentic-workflow--for-trustworthy--self-evolving-agents"></a>
<a id="4-event-infrastructure--for-proactive-agents"></a>
<a id="also-in-the-product"></a>

<p align="center"><b>Um harness de agentes de código aberto em que agentes são programas Python que melhoram a si mesmos.</b></p>

<p align="center">
  <a href="https://github.com/FuzzyKuji/OpenProgram/blob/main/.github/CHANGELOG.md"><img alt="Versão" src="https://img.shields.io/badge/dynamic/toml?url=https%3A%2F%2Fraw.githubusercontent.com%2FFuzzyKuji%2FOpenProgram%2Fmain%2Fpyproject.toml&query=%24.project.version&label=version&color=blue&style=flat-square"></a>
  <a href="https://github.com/FuzzyKuji/OpenProgram/blob/main/LICENSE"><img alt="License" src="https://img.shields.io/badge/license-AGPL--3.0-green?style=flat-square"></a>
  <a href="https://www.python.org/"><img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square"></a>
  <img alt="Platforms" src="https://img.shields.io/badge/platforms-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey?style=flat-square">
</p>

<p align="center">
  <a href="https://openprogram.io">Site</a> · <a href="#install">Instalação</a> · <a href="https://openprogram.io/docs/">Documentação</a>
</p>

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh.md">简体中文</a> · <a href="README.zh-Hant.md">繁體中文</a> · <a href="README.ja.md">日本語</a> · <a href="README.ko.md">한국어</a> · <a href="README.es.md">Español</a> · <a href="README.fr.md">Français</a> · <a href="README.de.md">Deutsch</a> · <a href="README.pt-BR.md">Português</a> · <a href="README.ru.md">Русский</a>
</p>

- **Agentes são classes Python.** Fluxo de controle, verificações e novas tentativas são código comum; `self(...)` é uma chamada ao modelo.
- **Autoprogramação.** Os agentes escrevem novos métodos na própria classe, e eles viram ferramentas no turno seguinte.
- **Contexto em grafo.** Cada chamada é um nó de um único DAG; subagentes rodam no próprio ramo e devolvem só o resultado.
- **Um só espaço de trabalho.** Chat, arquivos, terminal e um navegador embutido que o agente pode controlar, lado a lado.
- **Qualquer modelo.** Anthropic, OpenAI, Gemini e servidores locais, com várias contas por provedor.

<a id="install"></a>

## Instalação

```bash
curl -fsSL https://openprogram.io/install | sh
```

No Windows (a partir da v1.2.0): `irm https://openprogram.io/install.ps1 | iex`. O App de desktop para macOS é um DMG na [página de versões](https://github.com/FuzzyKuji/OpenProgram/releases); o App para Linux está lá como deb e AppImage, e o App para Windows chega com a v1.1.1. Se openprogram.io não responder: `curl -fsSL https://raw.githubusercontent.com/FuzzyKuji/OpenProgram/main/docs/_static_root/install.sh | sh`. Mais opções no [guia de instalação](https://openprogram.io/docs/install/install.html) (em inglês).

## Início rápido

```bash
openprogram        # assistente de configuração e depois chat no terminal
openprogram web    # espaço de trabalho em http://localhost:18100
```

A seguir: [primeiros passos](docs/start/GETTING_STARTED.html) · [modelos](docs/models/README.html) · [toda a documentação](docs/README.html) (em inglês)

## Uma olhada rápida

```python
from openprogram import Agent

class SupportAgent(Agent):
    def triage(self, ticket: str) -> str:
        """Classify the ticket, then draft a reply."""
        kind = self(ticket, choices=["bug", "question"])
        if kind == "bug":
            logs = search_logs(ticket)  # sua própria função auxiliar
            return self(f"Reply using:\n{logs}")
        return self("Draft a short reply.")
```

O modelo decide; o Python garante que as etapas necessárias rodem. Veja [como escrever agentes](docs/capabilities/agentic-programming/writing-functions/agent.html) (em inglês).

## Recursos

Cada item leva ao seu documento de design (em inglês).

### Framework

| | |
|---|---|
| **[Classes de agentes](https://openprogram.io/docs/reference/design/function/agentic-program.html)** | Um agente é uma classe Python; ramificações, novas tentativas e verificações são código, `self(...)` é uma chamada ao modelo. |
| **[DAG de execução](https://openprogram.io/docs/reference/design/runtime/dag/overview.html)** | Cada turno do usuário, chamada ao modelo e chamada de função é um nó que você pode inspecionar, ramificar e reproduzir. |
| **[Contexto](https://openprogram.io/docs/reference/design/context/overview.html)** | Cada chamada lê uma seleção de nós em vez de um histórico que só cresce, com compactação automática. |
| **[Autoprogramação](https://openprogram.io/docs/reference/design/runtime/workflows/workflow.html)** | Os agentes escrevem novos métodos na própria classe; eles viram ferramentas no turno seguinte. |
| **[Decisões verificadas](https://openprogram.io/docs/reference/design/runtime/execution/next-step-decision.html)** | O modelo escolhe em um menu fixo e o código valida a escolha antes de qualquer execução. |
| **[Subagentes](https://openprogram.io/docs/reference/design/runtime/collaboration/agent-collaboration.html)** | Subagentes rodam no próprio ramo, opcionalmente em um worktree do Git, e devolvem só o resultado. |
| **[Eventos](https://openprogram.io/docs/reference/design/proactive/event-layer.html)** | Um barramento de eventos tipado; plugins observam eventos ou bloqueiam chamadas de ferramentas. |
| **[Agentes sempre ativos](https://openprogram.io/docs/reference/design/runtime/always-on-agents.html)** | Agentes que continuam rodando em segundo plano e reagem a eventos. |
| **[Objetivos e recuperação](https://openprogram.io/docs/reference/design/runtime/reliability/goal-and-recovery.html)** | Objetivos de longa duração sobrevivem a reinícios e continuam de onde pararam. |
| **[Tolerância a falhas](https://openprogram.io/docs/reference/design/providers/reliability/llm-fault-tolerance.html)** | Novas tentativas, tempos limite e classificação de erros em toda chamada ao modelo. |

### Espaço de trabalho

| | |
|---|---|
| **[Desktop e interface web](https://openprogram.io/docs/reference/design/ui/README.html)** | O App no macOS e no Linux e, a partir da v1.2.0, também no Windows; a interface web em qualquer um deles ou em um servidor. |
| **[Painéis divididos](https://openprogram.io/docs/reference/design/ui/workspace/center-tabs-and-split-layout.html)** | Chats, arquivos, terminais e páginas web lado a lado. |
| **[Navegador embutido](https://openprogram.io/docs/reference/design/ui/browser/built-in-browser.html)** | Um navegador que o agente lê e controla enquanto você acompanha. |
| **[Terminal integrado](https://openprogram.io/docs/reference/design/ui/workspace/integrated-terminal.html)** | Terminais no espaço de trabalho, compartilhados com o agente. |
| **[Computer use](https://openprogram.io/docs/reference/design/integrations/computer-and-browser-use.html)** | Controle apps de desktop, páginas do navegador ou uma VM remota. |
| **[CLI e TUI](https://openprogram.io/docs/reference/design/cli/README.html)** | O mesmo agente pelo terminal. |
| **[Acesso remoto](https://openprogram.io/docs/reference/design/ui/remote-web-access.html)** | Acesse sua própria instância de outro dispositivo, só você. |

### Agentes e segurança

| | |
|---|---|
| **[Agentes configuráveis](https://openprogram.io/docs/reference/design/runtime/agent-configuration/agent-configuration-ui.html)** | Salve modelo, instruções, ferramentas e acesso à memória como um Agente reutilizável. |
| **[Memória](https://openprogram.io/docs/reference/design/memory/overview.html)** | Memória com fontes, busca e escrita em segundo plano. |
| **[Permissões e sandbox](https://openprogram.io/docs/reference/design/runtime/security/sandbox-architecture.html)** | Aprove ou negue chamadas de ferramentas com uma nota; os comandos rodam em um sandbox. |
| **[Programs](https://openprogram.io/docs/reference/design/runtime/programs/programs-architecture.html)** | Ferramentas e aplicativos como Programs instaláveis. |

### Modelos e integrações

| | |
|---|---|
| **[Provedores](https://openprogram.io/docs/reference/design/providers/README.html)** | Anthropic, OpenAI, Gemini e outros, com várias contas por provedor. |
| **[Modelos locais](https://openprogram.io/docs/reference/design/providers/local-models.html)** | Servidores de inferência locais, com autenticação opcional. |
| **[MCP](https://openprogram.io/docs/reference/design/integrations/mcp-integration.html)** | Use servidores MCP ou exponha o OpenProgram como um. |
| **[Skills e plugins](https://openprogram.io/docs/reference/design/integrations/skills-and-plugins.html)** | Amplie o que o agente sabe e o que ele pode chamar. |
| **[Canais](https://openprogram.io/docs/reference/design/channels/README.html)** | Converse com seus agentes pelo Telegram, Discord, Slack e WeChat. |
| **[Atualizações automáticas](https://openprogram.io/docs/reference/design/distribution/automatic-updates.html)** | Versões assinadas que se atualizam no lugar. |

## Citação

```bibtex
@inproceedings{qi2026llmascode,
  title     = {LLM-as-Code: Agentic Programming for Agent Harness},
  author    = {Qi, Junjia and Fu, Zichuan and Gao, Jingtong and Zhang, Wenlin and Yan, Hanyu and Wu, Xian and Zhao, Xiangyu},
  booktitle = {KDD 2026 Workshop on Agentic Software Engineering (AgenticSE)},
  year      = {2026},
  url       = {https://arxiv.org/abs/2606.15874},
}
```

## Licença

[AGPL-3.0](LICENSE) © 2026 Fzkuji. Consulte a licença para as obrigações de uso, modificação, distribuição e serviço em rede.

## Agradecimentos

Obrigado a quem contribui com código, relatos, reproduções, testes, documentação e revisões.

<!-- contributors-avatars -->
<p>
<a href="https://github.com/FuzzyKuji"><img src="https://avatars.githubusercontent.com/u/9404270?v=4&amp;s=48" width="24" height="24" alt="Maintainer" /></a>
<a href="https://github.com/Qi202"><img src="https://github.com/Qi202.png?size=48" width="24" height="24" alt="Qi202" /></a>
<a href="https://github.com/GithungDang"><img src="https://github.com/GithungDang.png?size=48" width="24" height="24" alt="GithungDang" /></a>
<a href="https://github.com/basil-k-aji-dev"><img src="https://github.com/basil-k-aji-dev.png?size=48" width="24" height="24" alt="basil-k-aji-dev" /></a>
<a href="https://github.com/binyangzhu000-sudo"><img src="https://github.com/binyangzhu000-sudo.png?size=48" width="24" height="24" alt="binyangzhu000-sudo" /></a>
</p>
<!-- /contributors-avatars -->

[Issues](https://github.com/FuzzyKuji/OpenProgram/issues) · [Pull requests](https://github.com/FuzzyKuji/OpenProgram/pulls)
