import jieba
from pypinyin import pinyin, Style
from bs4 import BeautifulSoup
import logging
import os
import glob
import time
from collections import defaultdict
import re

# --- NEW: Import from deep-translator ---
try:
    from deep_translator import GoogleTranslator # Using Google via deep-translator
    DEEP_TRANSLATOR_AVAILABLE = True
except ImportError:
    DEEP_TRANSLATOR_AVAILABLE = False
    GoogleTranslator = None # Placeholder if import fails
    logging.error("deep-translator library not found. Please install it: pip install deep-translator")
    # Consider exiting here if translation is critical


# --- Configuration ---
SOURCE_DIRECTORY = "data"
OUTPUT_DIRECTORY = "output"
DELETE_SOURCE_FILES_AFTER_PROCESSING = True

# Configuration for deep_translator (GoogleTranslator in this case)
# No API key needed for GoogleTranslator via deep-translator
# Retries and delays for online translation service
ONLINE_TRANSLATION_MAX_RETRIES = 2
ONLINE_TRANSLATION_BASE_DELAY = 0.3  # Slightly increased from 0.2 for online API
ONLINE_TRANSLATION_RATE_LIMIT_MULTIPLIER = 4
ONLINE_TRANSLATION_TIMEOUT = 15 # deep-translator itself might not have a timeout param, this is for our loop

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s')

# --- Character Names ---
CHARACTER_NAMES = [
    "温水和彦", "温水", "和彦", "阿温",
    "八奈见杏菜", "八奈见", "杏菜",
    "烧盐柠檬", "烧盐", "柠檬",
    "小鞠知花", "小鞠", "知花",
    "白玉璃子", "白玉", "璃子", "小玉",
    "小拔老师", "甘夏", "小甘夏",
    "朝云千早", "朝云", "小千",
    "佳树",
    "橘聪", "橘",
    "光希",
    "河合",
]

# --- Helper Functions (add_custom_dictionary, parse_filename, group_html_files, read_and_concatenate_chapter_text, segment_text_to_paragraphs, get_pinyin_for_segment, get_cedict_definition) ---
# These remain the same as the version using CEDICT for definitions
def add_custom_dictionary(word_list):
    count = 0
    for word in word_list:
        jieba.add_word(word.strip())
        count += 1
    logging.info(f"Added {count} custom words to Jieba dictionary.")

def parse_filename(filename):
    match = re.match(r"volume(\d+)_chapter(\d+)_(\d+)\.html", os.path.basename(filename), re.IGNORECASE)
    if match:
        volume, chapter, page_str = match.group(1), match.group(2), match.group(3)
        try: page_int = int(page_str); return volume, chapter, page_int, page_str
        except ValueError: logging.warning(f"Could not parse page number as int from '{page_str}' in {filename}")
    else: logging.warning(f"Filename '{os.path.basename(filename)}' does not match expected pattern.")
    return None

def group_html_files(source_dir):
    logging.info(f"Scanning for HTML files in: {source_dir}")
    html_files = glob.glob(os.path.join(source_dir, '*.html'))
    logging.info(f"Found {len(html_files)} .html files.")
    chapters_data = defaultdict(list)
    for filepath in html_files:
        parsed_info = parse_filename(filepath)
        if parsed_info:
            volume, chapter, page_int, _ = parsed_info
            chapter_key = f"volume{volume}_chapter{chapter}"
            chapters_data[chapter_key].append({'path': filepath, 'page_num': page_int})
    for chapter_key in chapters_data:
        chapters_data[chapter_key].sort(key=lambda x: x['page_num'])
        logging.debug(f"Chapter {chapter_key}: Found {len(chapters_data[chapter_key])} pages, sorted.")
    return chapters_data

def read_and_concatenate_chapter_text(page_files_data):
    full_chapter_text_list = []
    for page_data in page_files_data:
        filepath = page_data['path']
        logging.debug(f"Reading content from page: {filepath}")
        try:
            with open(filepath, 'r', encoding='utf-8') as f: html_content = f.read()
            soup = BeautifulSoup(html_content, 'html.parser')
            content_div = soup.find('div', id='TextContent')
            if content_div:
                page_text_parts = [p.get_text(strip=True) for p in content_div.find_all('p')]
                page_text = "\n".join(filter(None, page_text_parts))
                if page_text: full_chapter_text_list.append(page_text); logging.debug(f" Extracted ~{len(page_text)} chars.")
            else: logging.warning(f"No 'div#TextContent' found in {filepath}.")
        except Exception as e: logging.error(f"Error reading/parsing {filepath}: {e}")
    return "\n".join(full_chapter_text_list)

def segment_text_to_paragraphs(text):
    return [para.strip() for para in re.split(r'\n+', text) if para.strip() and para.strip() != '◇']

def get_pinyin_for_segment(segment):
    logging.debug(f"Pinyin for: '{segment[:30]}...'")
    try:
        pinyin_list = pinyin(segment, style=Style.TONE, heteronym=False, errors='ignore')
        result = " ".join([item[0] for item in pinyin_list if item])
        return result if result else " " # Use HTML space for empty Pinyin
    except Exception as e:
        logging.warning(f"Pinyin gen failed for '{segment[:30]}...': {e}")
        return "N/A"

# --- REPLACED: CEDICT Definition with Online Translation via deep-translator ---
def get_online_translation(segment, online_translator_obj):
    """Gets English translation using the provided deep-translator instance."""
    if not DEEP_TRANSLATOR_AVAILABLE or not online_translator_obj:
        logging.error("deep-translator not available or translator object not initialized.")
        return "Translator N/A"
        
    logging.debug(f"Online Translation for: '{segment[:30]}...'")
    if not segment or not segment.strip(): return " "
    if len(segment.strip()) <= 1 and not segment.strip().isalnum():
        logging.debug(f"  Skipping translation for short/non-alpha segment: '{segment}'")
        return segment

    is_likely_chinese = any('\u4e00' <= char <= '\u9fff' for char in segment.strip())
    if not is_likely_chinese:
        logging.debug(f"  Skipping translation for likely non-Chinese segment: '{segment}'")
        return segment

    # The deep-translator classes usually take source='auto' or a specific like 'zh-CN'
    # The target is set when the translator object is created.
    for attempt in range(ONLINE_TRANSLATION_MAX_RETRIES + 1):
        try:
            # Ensure the translator's source is appropriate. GoogleTranslator often handles 'auto'.
            # If you chose a different backend that needs explicit source:
            # online_translator_obj.source = 'zh-CN' # Or 'auto' if supported
            translated_text = online_translator_obj.translate(segment)

            if translated_text:
                # Some translators might return the original if no translation found or error.
                # It's a good idea to check if it's different from the source for Chinese.
                if translated_text.strip() == segment.strip() and is_likely_chinese:
                     logging.warning(f"  Translation result identical to source for Chinese segment '{segment}'. API might not have translated or service issue.")
                     # For online translators, this often means a problem, so let's retry or mark as N/A
                     # if attempt < ONLINE_TRANSLATION_MAX_RETRIES:
                     #    # Fall through to exception handling for retry logic
                     #    raise Exception("Translation identical to source, forcing retry or N/A")
                     # else:
                     #    return "Translation Failed (Identical)"
                logging.debug(f"  Translation Success: '{translated_text}'")
                return translated_text
            else:
                logging.warning(f"  Online translator returned empty for '{segment}' on attempt {attempt + 1}")
                if attempt < ONLINE_TRANSLATION_MAX_RETRIES:
                    time.sleep(ONLINE_TRANSLATION_BASE_DELAY * (attempt + 1))
                else:
                    return "Translation Failed (Empty)"
        except Exception as e:
            logging.warning(f"  Online Translation attempt {attempt + 1} for '{segment}' failed: {type(e).__name__} - {e}")
            error_str = str(e).lower()
            if "429" in error_str or "too many requests" in error_str or "rate limit" in error_str:
                if attempt < ONLINE_TRANSLATION_MAX_RETRIES:
                    sleep_duration = ONLINE_TRANSLATION_BASE_DELAY * ONLINE_TRANSLATION_RATE_LIMIT_MULTIPLIER * (attempt + 1)
                    logging.error(f"  RATE LIMIT LIKELY HIT for '{segment}'. Sleeping for {sleep_duration:.1f}s...")
                    time.sleep(sleep_duration)
                else: return "Translation Failed (Rate Limit)"
            elif attempt < ONLINE_TRANSLATION_MAX_RETRIES:
                sleep_duration = ONLINE_TRANSLATION_BASE_DELAY * (attempt + 1)
                logging.debug(f"    General error: Sleeping for {sleep_duration:.1f}s...")
                time.sleep(sleep_duration)
            else: return "Translation Failed (Max Retries)"
    return "Translation Failed (Loop End)"


def generate_chapter_html_output(annotated_chapter_data, chapter_title="Annotated Chapter"):
    # HTML structure remains same, but the third row is now "Translation"
    html_parts = [
        "<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'>",
        f"<title>{chapter_title}</title><style>",
        "body { font-family: Arial, 'Microsoft YaHei', 'SimSun', sans-serif; margin: 20px; line-height: 1.7; background-color: #f8f9fa; color: #212529; }",
        "h1 { text-align: center; color: #343a40; margin-bottom: 30px; font-weight: 300; }",
        ".segment-block { margin-bottom: 20px; padding: 12px; background-color: #ffffff; border: 1px solid #dee2e6; border-radius: .25rem; box-shadow: 0 1px 3px rgba(0,0,0,.05); overflow-x: auto; }",
        ".chapter-table { width: 100%; border-collapse: collapse; table-layout: auto; }",
        ".chapter-table td { padding: 8px 10px; text-align: left; vertical-align: top; word-break: break-word; }",
        ".chinese-row td { font-size: 1.4em; color: #2c3e50; padding-bottom: 5px; }",
        ".pinyin-row td { color: #2980b9; font-size: 0.95em; padding-bottom: 5px; border-bottom: 1px dashed #e0e0e0; }",
        ".translation-row td { color: #495057; font-style: italic; font-size: 0.9em; line-height: 1.4; }", # Changed class to translation-row
        "td:empty::after { content: '\\00a0'; }",
        "</style></head><body>", f"<h1>{chapter_title}</h1>"
    ]
    current_segments_zh, current_segments_py, current_segments_trans = [], [], []

    for item in annotated_chapter_data:
        if item == "PARAGRAPH_BREAK":
            if current_segments_zh:
                html_parts.append("<div class='segment-block'><table class='chapter-table'>")
                html_parts.append("<tr class='chinese-row'>")
                for seg in current_segments_zh: html_parts.append(f"<td>{seg if seg.strip() else ' '}</td>")
                html_parts.append("</tr><tr class='pinyin-row'>")
                for seg in current_segments_py: html_parts.append(f"<td>{seg if seg.strip() else ' '}</td>")
                html_parts.append("</tr><tr class='translation-row'>") # Changed class
                for seg in current_segments_trans: html_parts.append(f"<td>{seg if seg.strip() else ' '}</td>")
                html_parts.append("</tr></table></div>")
                current_segments_zh, current_segments_py, current_segments_trans = [], [], []
        else:
            current_segments_zh.append(item['zh'])
            current_segments_py.append(item['py'])
            current_segments_trans.append(item['trans']) # Changed key to 'trans'

    if current_segments_zh: # Handle last paragraph
        html_parts.append("<div class='segment-block'><table class='chapter-table'>")
        html_parts.append("<tr class='chinese-row'>")
        for seg in current_segments_zh: html_parts.append(f"<td>{seg if seg.strip() else ' '}</td>")
        html_parts.append("</tr><tr class='pinyin-row'>")
        for seg in current_segments_py: html_parts.append(f"<td>{seg if seg.strip() else ' '}</td>")
        html_parts.append("</tr><tr class='translation-row'>") # Changed class
        for seg in current_segments_trans: html_parts.append(f"<td>{seg if seg.strip() else ' '}</td>")
        html_parts.append("</tr></table></div>")

    html_parts.append("</body></html>")
    return "\n".join(html_parts)


def process_chapter(chapter_key, page_files_data, output_dir, online_translator_obj): # Parameter changed
    logging.info(f"--- Processing Chapter: {chapter_key} ---")
    chapter_start_time = time.time()
    output_filename = os.path.join(output_dir, f"{chapter_key}.html")

    if os.path.exists(output_filename):
        logging.info(f"Output file {output_filename} already exists. Skipping.")
        return [data['path'] for data in page_files_data], True

    logging.info(f"Step 1: Concatenating text for {len(page_files_data)} pages in {chapter_key}...")
    full_chapter_text = read_and_concatenate_chapter_text(page_files_data)
    if not full_chapter_text.strip():
        logging.warning(f"No text content extracted for chapter {chapter_key}. Skipping generation.")
        return [], False

    paragraphs = segment_text_to_paragraphs(full_chapter_text)
    logging.info(f"Step 2: Split chapter text into {len(paragraphs)} paragraphs.")
    annotated_chapter_data = []
    total_segments_processed, annotation_errors_occurred = 0, False

    logging.info(f"Step 3: Annotating segments for {chapter_key} using Pinyin and Online Translation...")
    for i, para_text in enumerate(paragraphs):
        if (i + 1) % 10 == 0 or i == 0 or i == len(paragraphs) -1 : # Log progress periodically
            logging.info(f"  Processing paragraph {i+1}/{len(paragraphs)}...")
        if not para_text.strip(): continue
        segments = list(jieba.cut(para_text))
        logging.debug(f"    Para {i+1}: Segmented into {len(segments)} parts.")

        # --- Optional: Batch Translation with deep-translator if beneficial ---
        # If many short segments, batching might be faster for some providers.
        # For now, we do segment by segment.
        # chinese_segments_for_batch = [s.strip() for s in segments if s.strip() and any('\u4e00' <= char <= '\u9fff' for char in s.strip())]
        # translations_batch = {}
        # if online_translator_obj and chinese_segments_for_batch:
        # try:
        # logging.debug(f" Attempting batch translation for {len(chinese_segments_for_batch)} segments...")
        #         translated_texts_batch = online_translator_obj.translate_batch(chinese_segments_for_batch)
        #         translations_batch = dict(zip(chinese_segments_for_batch, translated_texts_batch))
        # logging.debug(" Batch translation successful.")
        # except Exception as batch_e:
        # logging.error(f" Batch translation failed: {batch_e}. Falling back to segment-by-segment.")
        # translations_batch = {} # Ensure it's empty on failure

        for seg_idx, seg in enumerate(segments):
            seg_strip = seg.strip()
            if not seg_strip: continue
            
            pinyin_text = get_pinyin_for_segment(seg_strip)
            
            # Use online translation
            # english_text = translations_batch.get(seg_strip) # Try from batch first
            # if english_text is None: # If not in batch or batch failed
            english_text = get_online_translation(seg_strip, online_translator_obj)

            annotated_chapter_data.append({'zh': seg_strip, 'py': pinyin_text, 'trans': english_text}) # Key is 'trans'
            total_segments_processed += 1
            if pinyin_text == "N/A" or "Failed" in english_text or english_text == "Translator N/A":
                annotation_errors_occurred = True
        annotated_chapter_data.append("PARAGRAPH_BREAK")

    logging.info(f"Step 3: Finished annotation for {chapter_key}. Total segments: {total_segments_processed}. Errors: {annotation_errors_occurred}")
    logging.info(f"Step 4: Generating HTML output for {chapter_key}...")
    html_output_content = generate_chapter_html_output(annotated_chapter_data, chapter_title=chapter_key.replace("_", " ").title())

    logging.info(f"Step 5: Saving HTML output to {output_filename}...")
    try:
        with open(output_filename, 'w', encoding='utf-8') as f: f.write(html_output_content)
        logging.info(f"Successfully saved annotated chapter to: {output_filename}")
        chapter_end_time = time.time()
        logging.info(f"--- Chapter {chapter_key} processing duration: {chapter_end_time - chapter_start_time:.2f}s ---")
        return [data['path'] for data in page_files_data], False
    except Exception as e:
        logging.error(f"Failed to write HTML output for {chapter_key} to {output_filename}: {e}")
        return [], False

def main():
    main_start_time = time.time()
    logging.info(f"Starting CiyuReader batch processing with deep-translator (Google)...")
    os.makedirs(OUTPUT_DIRECTORY, exist_ok=True)
    add_custom_dictionary(CHARACTER_NAMES)

    online_translator = None
    if not DEEP_TRANSLATOR_AVAILABLE:
        logging.error("deep-translator is not installed. Cannot perform online translations. Exiting.")
        return
        
    try:
        logging.info("Initializing deep-translator (GoogleTranslator)...")
        # For GoogleTranslator: source='auto' is often fine. For Chinese, 'zh-CN' or 'zh' is more specific.
        online_translator = GoogleTranslator(source='auto', target='en')
        # Test call
        test_text = online_translator.translate("你好")
        logging.info(f"deep-translator (Google) initialized. Test: 你好 -> {test_text}")
    except Exception as e:
        logging.error(f"Failed to initialize deep-translator (GoogleTranslator): {e}", exc_info=True)
        logging.error("Online translation will not be available.")
        # Decide if script should exit or continue without online translation
        # return

    grouped_chapters = group_html_files(SOURCE_DIRECTORY)
    if not grouped_chapters: logging.info("No chapter groups found."); return

    all_processed_source_files = []
    chapters_processed_count, chapters_skipped_count, chapters_error_count = 0, 0, 0

    for chapter_key, page_files_data in grouped_chapters.items():
        if not page_files_data: continue
        
        if not online_translator: # If translator init failed
            logging.error(f"Online translator not available. Skipping chapter {chapter_key}")
            chapters_error_count += 1
            continue

        try:
            processed_files_for_this_chapter, skipped = process_chapter(
                chapter_key, page_files_data, OUTPUT_DIRECTORY, online_translator
            )
            if skipped: chapters_skipped_count += 1
            elif processed_files_for_this_chapter:
                all_processed_source_files.extend(processed_files_for_this_chapter)
                chapters_processed_count += 1
            else: chapters_error_count +=1
        except KeyboardInterrupt: logging.warning("!!! Keyboard interrupt. Stopping. !!!"); break
        except Exception as e:
             logging.error(f"!!! UNHANDLED EXCEPTION for chapter {chapter_key}: {e} !!!", exc_info=True)
             chapters_error_count += 1

    if DELETE_SOURCE_FILES_AFTER_PROCESSING and all_processed_source_files:
        logging.info(f"Deleting {len(all_processed_source_files)} source HTML files...")
        deleted_count, failed_delete_count = 0, 0
        for filepath in all_processed_source_files:
            try:
                if os.path.exists(filepath): os.remove(filepath); deleted_count += 1
            except Exception as e: logging.error(f"  Failed to delete {filepath}: {e}"); failed_delete_count +=1
        logging.info(f"Deleted {deleted_count} files.")
        if failed_delete_count > 0: logging.error(f"Failed to delete {failed_delete_count} files.")
    # ... (rest of summary logging from previous version) ...
    main_end_time = time.time()
    logging.info("=" * 30 + " Batch Processing Summary " + "=" * 30)
    logging.info(f"Total chapter groups found:      {len(grouped_chapters)}")
    logging.info(f"Chapters processed successfully: {chapters_processed_count}")
    logging.info(f"Chapters skipped (output existed): {chapters_skipped_count}")
    logging.info(f"Chapters with processing errors: {chapters_error_count}")
    logging.info(f"Total execution time:            {main_end_time - main_start_time:.2f} seconds")
    logging.info("=" * (60 + len(" Batch Processing Summary ")))


if __name__ == "__main__":
    logging.info("Initializing Jieba...")
    jieba.initialize()
    logging.info("Jieba initialized.")
    main()
