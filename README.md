# 🎧 AudioBook App

> **Engine Universal de Produção de Audiolivros e Resumos Interpretados** com Memória Persistente de Personagens e Síntese Neural Gratuita.

O **AudioBook App** é uma plataforma desenvolvida para transformar qualquer texto (de romances literários a resumos acadêmicos e livros técnicos) em experiências de áudio imersivas e expressivas, sem custos de API de voz e sem exigir hardware pesado.

---

## 🏛️ Visão Arquitetural

Diferente de conversores de texto simples que geram áudio monótono em bloco único, o AudioBook App opera como um estúdio de rádio-teatro automatizado:

```
[Entrada: PDF / EPUB / TXT]
            │
            ▼
┌─────────────────────────┐
│     Extrator & Chunker  │ ──▶ Limpeza de ruídos e divisão em blocos semânticos
└─────────────────────────┘
            │
            ▼
┌─────────────────────────┐
│   Diretor IA (LLM)      │ ──▶ Identifica cenas, personagens, pontuação e emoções
└─────────────────────────┘      (Consulta e alimenta a Bíblia de Personagens)
            │
            ▼
┌─────────────────────────┐
│ Roteiro JSON Estruturado│ ──▶ Cache persistente de falas, vozes e parâmetros acústicos
└─────────────────────────┘
            │
            ▼
┌─────────────────────────┐
│   Motor de Síntese      │ ──▶ Síntese paralela via Edge-TTS (vozes neurais gratuitas)
│       (Edge-TTS)        │      com controle de concorrência (async semaphore)
└─────────────────────────┘
            │
            ▼
┌─────────────────────────┐
│  Mixer de Áudio & Ritmo │ ──▶ Pydub + FFmpeg: inserção de pausas dramáticas,
│     (Pydub / FFmpeg)    │      masterização e exportação em MP3
└─────────────────────────┘
            │
            ▼
  [Audiolivro Final .mp3]
```

---

## 📂 Estrutura Multi-Projetos (Workspaces Isolados)

O sistema é universal: cada livro, artigo ou resumo possui seu próprio cofre isolado dentro de `data/projects/<slug-do-projeto>/`.

```
audiobook-app/
│
├── data/
│   ├── inputs/                  # Arquivos brutos adicionados pelo usuário (.txt, .pdf, .epub)
│   └── projects/                # Workspaces de projetos individuais
│       └── <slug-do-projeto>/
│           ├── metadata.json    # Metadados da obra, modo e progresso
│           ├── characters.json  # Bíblia de Personagens persistente (DNA Vocal)
│           ├── scripts/         # Roteiros estruturados em JSON por capítulo
│           │   └── cap_01.json
│           └── output/          # Áudios renderizados por capítulo e áudio consolidado
│               ├── cap_01.mp3
│               └── completo.mp3
│
├── src/                         # Código fonte da engine
│   └── __init__.py
│
├── .env.example                 # Exemplo de configuração de variáveis de ambiente
├── .gitignore                   # Blindagem de arquivos de áudio, temporários e chaves
├── requirements.txt             # Dependências do projeto
└── README.md
```

---

## 🎭 DNA Vocal e a Bíblia de Personagens

Para garantir que os personagens mantenham a mesma voz, idade, sotaque e personalidade do primeiro ao último capítulo, o sistema gerencia uma memória persistente (`characters.json`):

1. **Camada Fixa (Identidade Permanente):**
   * **Voz Base & Sotaque:** Mapeamento inteligente de vozes neurais (pt-BR, vozes regionais, pt-PT para portugueses, ou vozes multilíngues para estrangeiros).
   * **Baseline Acústico:** Ajuste base de tom (`pitch`) e velocidade (`rate`) que define idade e porte (ex: idoso ranzinza com tom mais grave e cadência contida).
   * **Mapa de Aliases:** Mapeamento de apelidos e sinônimos contextuais (ex: *"Arthur"*, *"Dr. Arthur"*, *"o jovem cientista"* apontam para o mesmo personagem).

2. **Camada Dinâmica (Modulação por Delta com Travas de Segurança):**
   * A LLM não gera números aleatórios de Hz ou porcentagem. Em cada fala, o Diretor seleciona apenas o **rótulo semântico da emoção** (ex: `panico`, `sussurro`, `raiva`, `ironia`, `neutro`).
   * O código Python consulta uma tabela calibrada de deltas:
     $$\text{Parâmetro Final} = \text{Baseline do Personagem} + \text{Delta da Emoção}$$
   * **Clamping (Travas Acústicas):** O sistema aplica limites estritos (ex: velocidade entre `-15%` e `+15%`, tom entre `-10Hz` e `+10Hz`), garantindo que vozes neurais nunca soem artificiais ou distorcidas.

---

## 🛡️ Validador de Integridade Textual por Lotes

Para prevenir alucinações, omissões de parágrafos ou resumos indesejados da LLM:
* O texto do capítulo é dividido em **blocos semânticos lógicos** (5 a 8 parágrafos).
* Após a IA processar o bloco, o sistema valida a integridade textual comparando as falas extraídas com o texto original do bloco.
* Se for detectada divergência ou texto omitido, o sistema **reprocessa apenas aquele bloco específico**, poupando tempo e tokens de contexto.

---

## 🎯 Modos de Operação

O AudioBook App adapta seu comportamento ao tipo de texto processado:

| Modo | Finalidade | Comportamento do Diretor |
| :--- | :--- | :--- |
| **Ficção / Literatura** | Romances, contos, novelas | Dramatização total, detecção multi-voz, sotaques, idades e modulação emocional de cena. |
| **Não-Ficção / Técnico** | Livros de negócios, ensaios, manuais | Narrador principal sóbrio e didático + Segunda voz de destaque para citações, estudos de caso e definições-chave. |
| **Resumo / Estudo Rápido** | Resumos, artigos, sínteses de aula | Cadência dinâmica, ênfase em tópicos e pausas de memorização. Geração direta otimizada para velocidade. |

---

## 💻 Interface de Linha de Comando (CLI)

O pipeline é desacoplado em etapas independentes, permitindo inspeção e ajuste prévio do elenco antes de gravar:

```bash
# 1. Direção: analisa o texto, alimenta a Bíblia de Personagens e gera os roteiros JSON
python main.py direct --project dom-casmurro --input data/inputs/livro.txt --mode fiction

# (Opcional com Modo Express 100% offline sem gastar API):
python main.py direct --project artigo-estudo --input data/inputs/artigo.pdf --express

# 2. Elenco (Cast): visualiza e customiza as vozes escolhidas para cada personagem
python main.py cast --project dom-casmurro

# Para alterar manualmente a voz de um personagem antes de gravar:
python main.py cast --project dom-casmurro --set-voice arthur edge_antonio

# 3. Renderização: sintetiza as falas e masteriza os áudios via Edge-TTS / FFmpeg
python main.py render --project dom-casmurro

# 4. Atalho Completo: executa direção e renderização de ponta a ponta
python main.py run --project resumo-economia --input data/inputs/artigo.txt --mode summary
```

---

## 🎧 Demonstração Real Gerada

O projeto inclui um áudio demonstrativo completo gerado de ponta a ponta, apresentando narração imersiva, diálogos contrastantes e pausas cênicas:

* **Caminho do arquivo:** `data/projects/demo_audiobook/output/demo_cena_dramatica.mp3`
* **Duração:** 48 segundos | Formato: MP3 24kHz Mono 160 kb/s
* **Elenco presente na cena:**
  * **Narrador:** Voz sóbria e grave (*Antônio*, Edge-TTS) com emoções `misterio` e `solene` (pausa final de 1.2s).
  * **Pierre Laurent:** Personagem com sotaque francês nativo (*Rémy*, Edge-TTS Multilingual) em tom `tenso`.
  * **Arthur Pendelton:** Jovem herói dinâmico (*Alex Blended*, tom acelerado) em tom `animado`.
  * **Aninha:** Menina com voz infantil (*Thalita/Francisca*, pitch elevado +6Hz) em tom `panico`.

---

## 🚀 Instalação e Configuração

### Pré-requisitos
* **Python 3.10+** (recomendado Python 3.11 ou 3.12)
* **FFmpeg** instalado e adicionado ao `PATH` do sistema

### 1. Clonar o repositório
```bash
git clone https://github.com/pietro3353/audiobook-app.git
cd audiobook-app
```

### 2. Criar e ativar o ambiente virtual
```bash
# Windows (PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Instalar dependências
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configurar variáveis de ambiente
Copie o arquivo `.env.example` para `.env` e preencha sua chave da API do Gemini (gratuita):
```bash
cp .env.example .env
```
Obtenha sua chave no [Google AI Studio](https://aistudio.google.com/).
