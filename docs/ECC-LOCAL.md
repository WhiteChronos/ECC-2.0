# ECC-2.0 — uso local sem API paga

O ECC-2.0 continua separado do REA. O perfil desta entrega fornece chat local, diagnóstico, geração de texto/código e um teste de chamada de ferramenta pelo adaptador Python. Não modifica sua conta ChatGPT nem torna assinaturas de outros produtos gratuitas.

## Abrir neste computador

Abra `ECC-Local.cmd` na raiz do projeto para conversar. Para verificar o fluxo de inferência e salvar evidências, execute `Validar-ECC-Local.cmd` pelo PowerShell normal do usuário, sem administrador. Ambos usam Node diretamente; não dependem de npm.ps1 nem alteram a política do PowerShell.

O iniciador abre uma instância própria do Ollama em uma porta loopback disponível, com `OLLAMA_NO_CLOUD=1`, sem chaves de API herdadas e sem proxy. Ao sair, solicita e aguarda o encerramento dos processos diretos que iniciou. Não declara encerramento de todos os possíveis descendentes no Windows. Não instala serviço, tarefa agendada ou execução automática.

O resultado mais recente fica em `.local-runtime/latest-acceptance.json`, acompanhado do histórico por identificador. Uma tentativa nova começa com `passed:false`; uma falha não mantém um sucesso antigo como resultado atual. Esses arquivos e logs ficam fora do Git. O chat mantém o histórico somente em memória.

## Pré-requisitos e portabilidade

- Node >=24.15 e Python >=3.11 com as dependências deste projeto (`python -m pip install -e .` em ambiente virtual próprio).
- Runtime oficial Ollama 0.40.5, obtido da [distribuição oficial](https://github.com/ollama/ollama/releases/tag/v0.40.5). O ZIP Windows desta preparação tem SHA-256 `5134ce7e3bc8e94d0494721c799ec293b429450d0c52461b0ee3647dd3bb4bb7`.
- Modelo `qwen3:0.6b` baixado para o armazenamento local. É um modelo pequeno para aceitação inicial; qualidade e capacidade não equivalem às de modelos maiores.

Neste layout, o iniciador procura `toolchains/ollama-0.40.5` sob a pasta Codex e Python na `.venv` do projeto ou no ambiente `ecc-validation-py` irmão. Para outro computador, definir `ECC_OLLAMA_DIR` apontando para uma pasta com `runtime/ollama.exe` e `models/`, e `ECC_PYTHON` para o executável do ambiente virtual. Ajustar o caminho do Node nos arquivos .cmd se necessário.

O download inicial de runtime/modelo requer internet e armazenamento; a inferência de pesos locais não requer API paga. Hardware e energia continuam necessários. O iniciador não baixa modelos silenciosamente e não reaproveita uma instância desconhecida do Ollama.

O perfil local usa timeout de comunicação de 180 segundos para acomodar a carga inicial dos pesos. Esse timeout de E/S não é um limite absoluto para a sessão inteira. Chat e aceitação desativam pensamento prolongado pelo parâmetro `think:false`. Um timeout permanece falha explícita; não dispara chamada paga nem repetição automática.

## Garantias e limites do perfil

`ECC_LOCAL_ONLY=1` recusa os provedores externos incorporados no resolver e em seus construtores. Ollama aceita somente HTTP em IP loopback, normaliza localhost sem DNS e não utiliza proxies ou redirecionamentos. Cada geração confere metadados locais e recusa modelo com referência remota. Leituras de resposta têm limite de 8 MiB. Em falha, não existe fallback pago.

Essa política não é um firewall nem sandbox contra código malicioso ou extensões arbitrárias. Aplicativos já abertos e instâncias criadas fora desse perfil não são reconfigurados.

Superfícies do ECC que ainda dependem de hosts próprios: NanoClaw baseado em Claude CLI, resumos LLM de sessão, revisão por Codex, TUI Rust com agentes configuráveis, MCPs de terceiros e integrações de IDE. O iniciador local não as executa. Instalar skills não comprova que todas funcionem com o modelo pequeno, e não há declaração de ECC inteiro 100% offline.

## O que a validação comprova

`--doctor` confere versão, modelo instalado e metadados locais, sem afirmar inferência. `--smoke` exige resposta aritmética real, chamada real de uma ferramenta de soma registrada e geração de uma função Python simples conferida por AST. Código gerado não é executado. Todos os checks precisam passar; falhas e encerramento desconhecido permanecem explícitos.

Os testes automatizados de transporte usam servidor local simulado: comprovam bloqueios e tratamento de erros, não o modelo real. A inferência só fica comprovada pelo resultado do smoke executado com pesos reais.

## Diagnóstico Windows

Esta sessão Codex usa uma identidade diferente do usuário normal. O Ollama iniciou, detectou GPU e baixou pesos, mas a abertura do manifesto retornou `Access is denied` nesta sessão. Não remover ACL, antivírus ou controle de execução. Executar a validação no terminal normal; se continuar falhando, preservar `.local-runtime/ollama.log` e o JSON da tentativa para investigar a causa específica.

## Licenças e fontes

Preservar o LICENSE MIT e a atribuição upstream do ECC. O runtime Ollama e o modelo têm licenças próprias, mantidas na distribuição/armazenamento; o Qwen3:0.6b publicado usa Apache-2.0. Componentes novos desta entrega são extensões do projeto independente, sem transferência de autoria do upstream.

- [Windows e distribuição oficial](https://docs.ollama.com/windows)
- [Desativação de recursos cloud](https://docs.ollama.com/faq#how-do-i-disable-ollamas-cloud-features)
- [Modelo e licença](https://ollama.com/library/qwen3:0.6b)

## Desenvolvimento

`python -m pytest tests/test_local_mode.py` testa o perfil; `node --test tests/local-runtime.test.js` testa o iniciador. Em sandbox Windows, passar `--basetemp` para uma pasta nova e gravável se o TEMP padrão estiver bloqueado. Os testes não exigem chave real nem conexão com fornecedor de IA.
