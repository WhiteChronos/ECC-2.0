# Cooperação opcional com Token-Economy

ECC continua independente. A ponte não altera o provedor do Codex nem instala um serviço.

No PowerShell normal, sem administrador:

```powershell
& '.\ECC-Economico.cmd' --token-economy-root '..\Token-Economy-2.0' --allow-local-inference
```

São três fixtures próprias, três repetições e dois modos: 18 respostas locais. O contexto completo é o arquivo da fixture; o otimizado é um trecho previamente declarado. Esse baseline não representa automaticamente o comportamento padrão do Codex. As respostas esperadas ficam fora dos prompts.

Ollama expõe contagens reais ou uso desconhecido; ausência não vira zero. Token-Economy gera JSON/HTML privado em .evidence/integration. Qualidade insuficiente ou pares incompletos invalidam a meta. O lote encerra seus processos diretos; descendentes não são afirmados. Dados locais não provam redução da fatura do Codex.

Em 18/10/2026 a identidade sandbox recebeu Access is denied ao ler o manifesto qwen3:0.6b. Executar pelo usuário normal Sandro permite verificar o contexto dele; não remover proteções ou credenciais. A tentativa salva é falha, não aprovação.
