"""Interface de Linha de Comando (CLI) Completa do AudioBook App.

Comandos disponíveis:
  direct : Extrai o documento, executa o Diretor e gera roteiros e elenco.
  render : Sintetiza os roteiros e exporta os MP3s finais masterizados.
  run    : Atalho para executar 'direct' + 'render' de ponta a ponta.
  cast   : Visualiza e edita a Bíblia de Personagens do projeto.
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Optional

from src.director import Director
from src.extractor import detect_chapters, extract_file
from src.mixer import AudioMixer
from src.models import EngineStrategy, ProjectMode
from src.project_manager import ProjectManager
from src.synthesizer import Synthesizer
from src.voices import VOICE_CATALOG, get_voice_by_id


def cmd_direct(args):
    """Comando para extração e direção estruturada de texto."""
    pm = ProjectManager()
    slug = args.project
    arquivo_entrada = Path(args.input)

    if not arquivo_entrada.exists():
        print(f"[Erro] Arquivo de entrada não encontrado: {arquivo_entrada}")
        sys.exit(1)

    print(f"\n=======================================================")
    print(f"DIREÇÃO DE PROJETO: {slug}")
    print(f"Arquivo: {arquivo_entrada.name}")
    print(f"Modo: {args.mode.upper()} | Estratégia: {args.strategy.upper()}")
    print(f"Modo Express (Offline): {'SIM' if args.express else 'NÃO'}")
    print(f"=======================================================\n")

    # 1. Cria ou carrega metadados do projeto
    if not pm.project_exists(slug):
        pm.create_project(
            slug=slug,
            title=args.title or slug,
            mode=args.mode,
            engine_strategy=args.strategy,
        )
    metadata = pm.load_metadata(slug)

    # 2. Extrai e cura o documento
    print("[1/3] Extraindo e curando documento...")
    texto_curado = extract_file(arquivo_entrada)
    print(f"      Texto higienizado: {len(texto_curado)} caracteres.")

    # 3. Detecta capítulos
    print("[2/3] Identificando capítulos...")
    capitulos = detect_chapters(texto_curado)
    print(f"      Total de capítulos detectados: {len(capitulos)}")

    # 4. Executa a direção
    print("[3/3] Direcionando falas e construindo roteiros estruturados...")
    director = Director(project_manager=pm)

    for cap in capitulos:
        num = cap["chapter_number"]
        titulo = cap["title"]
        print(f"      -> Direcionando Capítulo {num}: '{titulo}'...")
        script = director.direct_chapter(
            project_slug=slug,
            chapter_number=num,
            chapter_title=titulo,
            chapter_content=cap["content"],
            force_express=args.express,
        )
        print(f"         Concluído: {len(script.blocks)} falas registradas.")

    # Resumo final do elenco
    bible = pm.load_character_bible(slug)
    print(f"\n✔ Direção concluída com sucesso!")
    print(f"   Roteiros salvos em: data/projects/{slug}/scripts/")
    print(f"   Personagens registrados: {len(bible.characters)}")
    for c in bible.characters.values():
        print(f"   - [{c.id}] {c.name} -> Voz: {c.voice_id} ({c.engine})")


def cmd_render(args):
    """Comando para síntese multi-motor e mixagem em MP3."""
    pm = ProjectManager()
    slug = args.project

    if not pm.project_exists(slug):
        print(f"[Erro] Projeto não encontrado: {slug}. Execute 'direct' primeiro.")
        sys.exit(1)

    print(f"\n=======================================================")
    print(f"RENDERIZAÇÃO E MASTERIZAÇÃO: {slug}")
    print(f"=======================================================\n")

    metadata = pm.load_metadata(slug)
    scripts_dir = pm.get_project_dir(slug) / "scripts"
    output_dir = pm.get_project_dir(slug) / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    arquivos_scripts = sorted(scripts_dir.glob("cap_*.json"))
    if not arquivos_scripts:
        print("[Erro] Nenhum roteiro estruturado encontrado em scripts/. Execute 'direct' primeiro.")
        sys.exit(1)

    # Filtra por capítulo se especificado
    if args.chapter:
        arquivos_scripts = [
            f for f in arquivos_scripts if f.name == f"cap_{args.chapter:02d}.json"
        ]
        if not arquivos_scripts:
            print(f"[Erro] Roteiro do capítulo {args.chapter} não encontrado.")
            sys.exit(1)

    synthesizer = Synthesizer()
    mixer = AudioMixer()
    capitulos_mp3: list[Path] = []

    for arq_script in arquivos_scripts:
        cap_num = int(arq_script.stem.split("_")[1])
        script = pm.load_chapter_script(slug, cap_num)
        if not script:
            continue

        print(f"\n[Capítulo {script.chapter_number}: '{script.title}']")
        print(f"Total de falas: {len(script.blocks)}")

        # 1. Síntese Assíncrona com Barra de Progresso
        def progresso(atual, total):
            pct = int((atual / total) * 100)
            bar = "█" * (pct // 5) + "░" * (20 - (pct // 5))
            sys.stdout.write(f"\r      Sintetizando: [{bar}] {pct}% ({atual}/{total})")
            sys.stdout.flush()

        print("   -> 1. Síntese de falas...")
        raw_chunks = asyncio.run(
            synthesizer.synthesize_chapter(
                script=script,
                project_slug=slug,
                on_progress=progresso,
            )
        )
        print("\n   -> 2. Masterizando áudio e pausas dramáticas via FFmpeg...")

        cap_mp3_path = output_dir / f"cap_{script.chapter_number:02d}.mp3"
        mixer.mix_chapter(
            script=script,
            raw_chunks=raw_chunks,
            output_chapter_mp3=cap_mp3_path,
        )
        capitulos_mp3.append(cap_mp3_path)
        tamanho_mb = cap_mp3_path.stat().st_size / (1024 * 1024)
        print(f"      ✔ Capítulo {script.chapter_number} gerado: {cap_mp3_path.name} ({tamanho_mb:.2f} MB)")

    # Se renderizou todos os capítulos, gera o audiolivro completo unificado
    if len(capitulos_mp3) > 1 and not args.chapter:
        completo_mp3 = output_dir / "completo.mp3"
        print(f"\n   -> Unindo todos os capítulos no audiolivro completo...")
        mixer.merge_all_chapters(capitulos_mp3, completo_mp3)
        tamanho_completo = completo_mp3.stat().st_size / (1024 * 1024)
        print(f"      ✔ Audiolivro completo exportado: {completo_mp3.name} ({tamanho_completo:.2f} MB)")

    print(f"\n🎉 Renderização concluída! Arquivos salvos em:")
    print(f"   {output_dir.resolve()}\n")


def cmd_build(args):
    """Executa o pipeline completo ('direct' + 'render') de ponta a ponta."""
    cmd_direct(args)
    # Reusa argumentos para o render
    render_args = argparse.Namespace(
        project=args.project,
        chapter=None,
    )
    cmd_render(render_args)


def cmd_cast(args):
    """Exibe e gerencia a Bíblia de Personagens do projeto."""
    pm = ProjectManager()
    slug = args.project

    if not pm.project_exists(slug):
        print(f"[Erro] Projeto não encontrado: {slug}")
        sys.exit(1)

    bible = pm.load_character_bible(slug)

    # Troca de voz manual se solicitado
    if args.set_voice:
        char_id, nova_voz = args.set_voice
        char = bible.get(char_id)
        if not char:
            print(f"[Erro] Personagem '{char_id}' não encontrado na Bíblia.")
            sys.exit(1)
        voz_profile = get_voice_by_id(nova_voz)
        if not voz_profile:
            print(f"[Erro] Voz '{nova_voz}' não existe no catálogo de vozes.")
            sys.exit(1)

        char.voice_id = voz_profile.id
        char.engine = voz_profile.engine
        pm.save_character_bible(bible)
        print(f"✔ Voz do personagem '{char.name}' atualizada para '{voz_profile.name}' ({voz_profile.id})!\n")

    print(f"\n=======================================================")
    print(f"BÍBLIA DE PERSONAGENS: {slug}")
    print(f"Total: {len(bible.characters)} personagens cadastrados")
    print(f"=======================================================\n")

    cabecalho = f"{'ID':<18} | {'Nome':<20} | {'Voz':<22} | {'Motor':<8} | {'Idade':<8} | {'Sotaque':<12}"
    print(cabecalho)
    print("-" * len(cabecalho))

    for c in bible.characters.values():
        print(
            f"{c.id:<18} | {c.name[:19]:<20} | {c.voice_id:<22} | {c.engine:<8} | {c.apparent_age:<8} | {c.accent:<12}"
        )

    print("\nPara alterar a voz de um personagem:")
    print(f"  python main.py cast --project {slug} --set-voice <id> <voz_id>\n")


def build_parser() -> argparse.ArgumentParser:
    """Configura o analisador de argumentos de linha de comando."""
    parser = argparse.ArgumentParser(
        prog="audiobook",
        description="AudioBook App - Engine Universal de Produção de Audiolivros Interpretados",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. Comando 'direct'
    p_direct = subparsers.add_parser("direct", help="Direciona o texto em roteiro estruturado")
    p_direct.add_argument("-p", "--project", required=True, help="Slug único do projeto")
    p_direct.add_argument("-i", "--input", required=True, help="Caminho do arquivo de entrada (.txt, .md, .pdf, .epub)")
    p_direct.add_argument("-m", "--mode", choices=["fiction", "non_fiction", "summary"], default="fiction", help="Modo do projeto")
    p_direct.add_argument("-s", "--strategy", choices=["unlimited", "hybrid"], default="unlimited", help="Estratégia de motores")
    p_direct.add_argument("-t", "--title", default="", help="Título legível do projeto")
    p_direct.add_argument("-e", "--express", action="store_true", help="Modo offline determinístico sem LLM")
    p_direct.set_defaults(func=cmd_direct)

    # 2. Comando 'render'
    p_render = subparsers.add_parser("render", help="Sintetiza e mixa os roteiros existentes")
    p_render.add_argument("-p", "--project", required=True, help="Slug único do projeto")
    p_render.add_argument("-c", "--chapter", type=int, default=None, help="Número específico de um capítulo para renderizar")
    p_render.set_defaults(func=cmd_render)

    # 3. Comando 'build' / 'run'
    p_build = subparsers.add_parser("run", aliases=["build"], help="Executa o pipeline completo (direção + renderização)")
    p_build.add_argument("-p", "--project", required=True, help="Slug único do projeto")
    p_build.add_argument("-i", "--input", required=True, help="Caminho do arquivo de entrada")
    p_build.add_argument("-m", "--mode", choices=["fiction", "non_fiction", "summary"], default="fiction", help="Modo do projeto")
    p_build.add_argument("-s", "--strategy", choices=["unlimited", "hybrid"], default="unlimited", help="Estratégia de motores")
    p_build.add_argument("-t", "--title", default="", help="Título legível do projeto")
    p_build.add_argument("-e", "--express", action="store_true", help="Modo offline determinístico sem LLM")
    p_build.set_defaults(func=cmd_build)

    # 4. Comando 'cast'
    p_cast = subparsers.add_parser("cast", help="Exibe e gerencia a Bíblia de Personagens")
    p_cast.add_argument("-p", "--project", required=True, help="Slug único do projeto")
    p_cast.add_argument("--set-voice", nargs=2, metavar=("CHAR_ID", "VOICE_ID"), help="Altera a voz de um personagem")
    p_cast.set_defaults(func=cmd_cast)

    return parser


def main():
    """Ponto de entrada principal da CLI."""
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
