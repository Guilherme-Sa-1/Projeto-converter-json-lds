import fitz  # PyMuPDF
import json
import re
import os
from collections import defaultdict

# --- MAPAS DE DADOS (APENAS LIVRO DE MÓRMON) ---
SCRIPTURE_MAP = {
    "ニーファイ第一書": {"english": "1 Nephi", "abbr": "1 Ne."},
    "ニーファイ第二書": {"english": "2 Nephi", "abbr": "2 Ne."},
    "ヤコブ書": {"english": "Jacob", "abbr": "Jacob"},
    "エノス書": {"english": "Enos", "abbr": "Enos"},
    "ジェロム書": {"english": "Jarom", "abbr": "Jarom"},
    "オムナイ書": {"english": "Omni", "abbr": "Omni"},
    "モルモンの言葉": {"english": "Words of Mormon", "abbr": "W of M"},
    "モーサヤ書": {"english": "Mosiah", "abbr": "Mosiah"},
    "アルマ書": {"english": "Alma", "abbr": "Alma"},
    "ヒラマン書": {"english": "Helaman", "abbr": "Hel."},
    "第三ニーファイ": {"english": "3 Nephi", "abbr": "3 Ne."},
    "第四ニーファイ": {"english": "4 Nephi", "abbr": "4 Ne."},
    "モルモン書": {"english": "Mormon", "abbr": "Morm."}, 
    "エテル書": {"english": "Ether", "abbr": "Ether"},
    "モロナイ書": {"english": "Moroni", "abbr": "Moro."},
}

FIXED_VOLUME_NAME = "Book of Mormon"

# --- PARTE 1: EXTRAÇÃO DE TEXTO DO PDF (LÓGICA DE HIATO + FILTRO) ---

def extract_vertical_text(pdf_path):
    """
    Extrai texto de um PDF vertical usando uma "lógica de hiato" e
    filtrando cabeçalhos/rodapés (8% superior/inferior).
    """
    print(f"Iniciando extração de texto de '{pdf_path}' (Lógica de Hiato + Filtro)...")
    doc = fitz.open(pdf_path)
    full_text_content = []
    
    VERTICAL_GAP_THRESHOLD = 4.0 # pixels
    TOP_MARGIN_RATIO = 0.08      # Ignora 8% superior da página
    BOTTOM_MARGIN_RATIO = 0.08   # Ignora 8% inferior da página

    for page_num, page in enumerate(doc):
        if (page_num + 1) % 50 == 0:
            print(f"Processando página {page_num + 1} de {len(doc)}...")
        
        page_rect = page.rect
        page_height = page_rect.height
        
        blocks = page.get_text("dict", flags=fitz.TEXT_INHIBIT_SPACES)["blocks"]
        
        vertical_spans = []
        for block in blocks:
            if block['type'] == 0: 
                for line in block['lines']:
                    is_vertical = abs(line['dir'][0]) > abs(line['dir'][1])
                    if not is_vertical:
                        continue
                        
                    for span in line['spans']:
                        # Filtra spans que estão muito acima ou muito abaixo na página
                        if span['bbox'][1] < (page_height * TOP_MARGIN_RATIO) or \
                           span['bbox'][3] > (page_height * (1 - BOTTOM_MARGIN_RATIO)):
                            continue # Ignora este span
                            
                        vertical_spans.append(span)

        columns = defaultdict(list)
        for span in vertical_spans:
            col_key = round(span['bbox'][0]) 
            columns[col_key].append(span)

        sorted_column_keys = sorted(columns.keys(), reverse=True)
        
        page_content = []
        for key in sorted_column_keys:
            spans_in_column = columns[key]
            spans_in_column.sort(key=lambda s: s['bbox'][1]) 
            
            column_lines = []
            current_line_spans = []
            last_span_y1 = -1.0

            for span in spans_in_column:
                span_text = re.sub(r'[\s\u3000\u00AD]+', '', span['text']).strip()
                if not span_text:
                    continue
                    
                span_y0 = span['bbox'][1]

                if last_span_y1 > 0 and (span_y0 - last_span_y1) > VERTICAL_GAP_THRESHOLD:
                    if current_line_spans:
                        column_lines.append("".join(current_line_spans))
                    current_line_spans = [span_text]
                else:
                    current_line_spans.append(span_text)
                
                last_span_y1 = span['bbox'][3]

            if current_line_spans:
                column_lines.append("".join(current_line_spans))

            column_text = "\n".join(column_lines)
            
            if column_text:
                page_content.append(column_text)
        
        full_text_content.append("\n".join(page_content))

    print(f"Extração de texto concluída. Total de páginas: {len(doc)}.")
    return "\n".join(full_text_content)

# --- PARTE 2: ANÁLISE DE TEXTO (LÓGICA ESTRITA + CORREÇÃO DO PONTO `．` + RESUMOS) ---

def parse_text_to_json(raw_text):
    """
    Analisa o texto bruto, procurando por títulos, capítulos, resumos
    e versículos (com o ponto de largura total).
    """
    print("Iniciando análise do texto para estrutura JSON (Com Resumos e Correção de Ponto)...")
    
    # Regex "Estrito": Deve corresponder à linha inteira
    book_titles_pattern = "|".join(re.escape(k) for k in SCRIPTURE_MAP.keys())
    re_book = re.compile(f"^\s*({book_titles_pattern})\s*$", re.MULTILINE)
    
    re_chapter = re.compile(r"^\s*第\s*(\d+)\s*章\s*$", re.MULTILINE)
    
    # --- CORREÇÃO DO REGEX DO VERSÍCULO ---
    # Procura pelo número no início da linha, seguido por um PONTO DE LARGURA TOTAL opcional (．)
    # e então pelo texto que começa com um caractere japonês.
    # \uFF0E é o ponto de largura total. ? o torna opcional.
    re_verse = re.compile(r"^\s*(\d+)\s*．?\s*(.*)", re.MULTILINE)
    # Regex para filtrar linhas de notas de rodapé que são apenas letras (a, b, c...)
    re_footnote = re.compile(r"^\s*[a-z]\s*$")
    
    all_verses = []
    
    current_volume_en = FIXED_VOLUME_NAME
    current_book_en = ""
    current_book_abbr = ""
    current_chapter = 0
    parsing_started = False # Só começa a salvar após encontrar "1 Néfi"
    
    current_verse_text = ""
    current_verse_number = 0
    
    in_summary = False
    current_summary_text = ""

    lines = raw_text.split('\n')
    
    def flush_previous_verse():
        """Função auxiliar para salvar o versículo anterior."""
        nonlocal current_verse_text, current_verse_number, current_summary_text
        
        if parsing_started and current_verse_number > 0 and current_book_en and current_chapter > 0:
            verse_title = f"{current_book_en} {current_chapter}:{current_verse_number}"
            verse_short_title = f"{current_book_abbr} {current_chapter}:{current_verse_number}"
            
            verse_obj = {
                "volume_title": current_volume_en,
                "book_title": current_book_en,
                "book_short_title": current_book_abbr,
                "chapter_number": current_chapter,
                "verse_number": current_verse_number,
                "verse_title": verse_title,
                "verse_short_title": verse_short_title,
                "scripture_text": current_verse_text.strip()
            }
            
            # Adiciona o resumo ao primeiro versículo do capítulo
            if current_summary_text and current_verse_number == 1:
                verse_obj["chapter_summary"] = current_summary_text.strip()
                current_summary_text = "" # Limpa o resumo após usá-lo
                
            all_verses.append(verse_obj)
        
        current_verse_text = ""
        current_verse_number = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Verifica se é um título de LIVRO (correspondência exata/estrita)
        book_match = re_book.match(line)
        if book_match:
            book_name_jp = book_match.group(1)
            
            flush_previous_verse()
            
            if not parsing_started and book_name_jp == "ニーファイ第一書":
                print("\n--- VOLUME: Book of Mormon --- (Detectado)")
                print("Início da análise detectado em '1 Nephi'. Ignorando o prefácio.")
                parsing_started = True
            
            book_info = SCRIPTURE_MAP[book_name_jp]
            current_book_en = book_info["english"]
            current_book_abbr = book_info["abbr"]
            current_chapter = 0
            in_summary = False
            current_summary_text = ""
            
            if parsing_started:
                print(f"--- LIVRO: {current_book_en} ---")
            continue
            
        if not parsing_started:
            continue

        # Verifica se é um número de CAPÍTULO (correspondência exata/estrita)
        chapter_match = re_chapter.match(line)
        if chapter_match:
            flush_previous_verse()
            current_chapter = int(chapter_match.group(1))
            in_summary = True 
            current_summary_text = "" 
            print(f"--- CAPÍTULO: {current_chapter} ---")
            continue
            
        # Verifica se é um número de VERSÍCULO (com o regex corrigido)
        verse_match = re_verse.match(line)
        if verse_match:
            in_summary = False # O primeiro versículo encerra o sumário
            flush_previous_verse() # Salva o versículo anterior
            
            current_verse_number = int(verse_match.group(1))
            current_verse_text = verse_match.group(2).strip()
            continue
            
        # Se for uma linha de nota de rodapé (ex: "a", "b"), ignore
        if re_footnote.match(line):
            continue

        # Se não for um título, capítulo ou versículo:
        # Ou é texto de resumo, ou é continuação de versículo.
        if in_summary:
            current_summary_text += line
        elif current_verse_number > 0:
            current_verse_text += line
    
    # Salva o último versículo do arquivo
    flush_previous_verse()
    
    print(f"Análise concluída. Total de versículos extraídos: {len(all_verses)}")
    return all_verses

# --- BLOCO DE EXECUÇÃO PRINCIPAL ---

if __name__ == "__main__":
    PDF_FILENAME = "book-of-mormon-59012-jpn.pdf"
    TEXT_FILENAME = "book_of_mormon_extracted.txt"
    JSON_FILENAME = "book_of_mormon.json"
    
    # --- Etapa 1: Extrair Texto do PDF ---
    # Forçar a recriação se o arquivo de texto não existir
    if not os.path.exists(TEXT_FILENAME):
        if not os.path.exists(PDF_FILENAME):
            print(f"Erro: Arquivo PDF '{PDF_FILENAME}' não encontrado.")
            exit()
        else:
            raw_text = extract_vertical_text(PDF_FILENAME)
            with open(TEXT_FILENAME, "w", encoding="utf-8") as f:
                f.write(raw_text)
            print(f"Texto bruto extraído e salvo em '{TEXT_FILENAME}'")
    else:
        print(f"Arquivo de texto '{TEXT_FILENAME}' encontrado. Pulando a extração do PDF.")
        print("Analisando o texto existente...")
        
    # --- Etapa 2: Analisar Texto para JSON ---
    if not os.path.exists(TEXT_FILENAME):
        print(f"Erro: Arquivo de texto '{TEXT_FILENAME}' não encontrado para análise.")
    else:
        with open(TEXT_FILENAME, "r", encoding="utf-8") as f:
            full_raw_text = f.read()
            
        structured_data = parse_text_to_json(full_raw_text)
        
        if structured_data:
            with open(JSON_FILENAME, "w", encoding="utf-8") as f:
                json.dump(structured_data, f, ensure_ascii=False, indent=4)
            print(f"\nSucesso! Dados JSON estruturados salvos em '{JSON_FILENAME}'.")
        else:
            print("\nNenhum dado de versículo foi extraído. Verifique o texto extraído.")