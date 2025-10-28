import fitz
import re
import json
from pathlib import Path

PDF_PATH = "triple-jpn.pdf"
OUT_PATH = "triplice_jpn_parsed.json"

# Regex tolerante para capítulo e verso
chapter_re = re.compile(r"第?\s*([0-9０-９]{1,3})\s*章")
verse_re = re.compile(r"^([0-9０-９]{1,3})\s*(.*)")

# Função para converter números japoneses "１" → "1"
def fw_to_ascii(num_str):
    fw = "０１２３４５６７８９"
    for i, ch in enumerate(fw):
        num_str = num_str.replace(ch, str(i))
    return num_str

# Remove furigana básicos: caracteres hiragana isolados entre kanji
def clean_furigana(text):
    text = re.sub(r"[ぁ-ゖゝゞァ-ヺー]{1}", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

doc = fitz.open(PDF_PATH)
records = []
chapter = None
verse = None
buffer = []

volume_title = "Book of Mormon"
book_title = "Book of Mormon"
book_short_title = "BoM"

# 1️⃣ Ler e juntar blocos por página
for pno in range(doc.page_count):
    text = doc.load_page(pno).get_text("text")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    joined = " ".join(lines)  # junta as linhas soltas
    joined = clean_furigana(joined)

    # 2️⃣ Detecta mudança de volume
    if "教義と聖約" in joined:
        volume_title = book_title = "Doctrine and Covenants"
        book_short_title = "D&C"
    elif "高価な真珠" in joined:
        volume_title = book_title = "Pearl of Great Price"
        book_short_title = "PGP"
    elif "モルモン書" in joined:
        volume_title = book_title = "Book of Mormon"
        book_short_title = "BoM"

    # 3️⃣ Encontrar capítulos e versos dentro do texto unido
    tokens = re.split(r"(\d+\s*章|\d+)", joined)
    for token in tokens:
        t = token.strip()
        if not t:
            continue

        mchap = chapter_re.search(t)
        if mchap:
            # salva verso anterior
            if chapter and verse and buffer:
                records.append({
                    "volume_title": volume_title,
                    "book_title": book_title,
                    "book_short_title": book_short_title,
                    "chapter_number": chapter,
                    "verse_number": verse,
                    "verse_title": f"{book_title} {chapter}:{verse}",
                    "verse_short_title": f"{book_short_title} {chapter}:{verse}",
                    "scripture_text": "".join(buffer).strip()
                })
                buffer = []
            chapter = int(fw_to_ascii(mchap.group(1)))
            verse = None
            continue

        mverse = verse_re.match(t)
        if mverse:
            # salva verso anterior
            if chapter and verse and buffer:
                records.append({
                    "volume_title": volume_title,
                    "book_title": book_title,
                    "book_short_title": book_short_title,
                    "chapter_number": chapter,
                    "verse_number": verse,
                    "verse_title": f"{book_title} {chapter}:{verse}",
                    "verse_short_title": f"{book_short_title} {chapter}:{verse}",
                    "scripture_text": "".join(buffer).strip()
                })
                buffer = []
            verse = int(fw_to_ascii(mverse.group(1)))
            rest = clean_furigana(mverse.group(2))
            if rest:
                buffer.append(rest)
            continue

        if chapter and verse:
            buffer.append(t)

# 4️⃣ flush final
if chapter and verse and buffer:
    records.append({
        "volume_title": volume_title,
        "book_title": book_title,
        "book_short_title": book_short_title,
        "chapter_number": chapter,
        "verse_number": verse,
        "verse_title": f"{book_title} {chapter}:{verse}",
        "verse_short_title": f"{book_short_title} {chapter}:{verse}",
        "scripture_text": "".join(buffer).strip()
    })

# 5️⃣ salva JSON
with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(records, f, ensure_ascii=False, indent=2)

print(f"Versos extraídos: {len(records)}")
print(f"JSON salvo em: {OUT_PATH}")
