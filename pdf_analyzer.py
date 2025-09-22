#!/usr/bin/env python3

import argparse
import json
import logging
import os
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Optional

import PyPDF2
import pytesseract
from pdf2image import convert_from_path
from tqdm import tqdm

# Company name patterns discovered from actual filenames
COMPANY_PATTERNS = {
    # Multi-word companies that need special handling
    "pc_themes": "pc themes",
    "pc": "pc themes",  # Fallback for any missed cases

    # Single word companies
    "bizgram": "bizgram",
    "dynacore": "dynacore",
    "fuwell": "fuwell",
    "infinity": "infinity",
    "laser": "laser",
    "techdeals": "techdeals",
    "tradepac": "tradepac",
}

# Known multi-word patterns that should be extracted as company names
KNOWN_MULTI_WORD_PATTERNS = {
    "bizgram_asia": "bizgram",
    "dynacore_tech": "dynacore",
    "fuwell_international": "fuwell",
    "infinity_computer": "infinity",
    "laser_distributor": "laser",
    "tradepac_distribution": "tradepac",
    "techdeals_pte": "techdeals",
    "pc_themes_technology": "pc themes",
}


def extract_company_robust(filename: str) -> str:
    """
    Extract company name with fail-fast validation.
    Raises ValueError for unknown patterns to prevent silent failures.
    """
    if not filename or not filename.strip():
        raise ValueError(f"Invalid filename: '{filename}'")

    stem = Path(filename).stem
    if not stem:
        raise ValueError(f"Empty stem from filename: '{filename}'")

    if "_" not in stem:
        # No underscore - treat as single company name
        company_key = stem.lower().strip()
        if company_key in COMPANY_PATTERNS:
            return COMPANY_PATTERNS[company_key]
        raise ValueError(f"Unknown single-word company: '{company_key}' in file '{filename}'")

    # Extract potential company parts
    parts = stem.split("_")
    if not parts[0]:
        raise ValueError(f"Empty first part in filename: '{filename}'")

    # Check for known multi-word patterns first (most specific)
    for num_words in range(min(4, len(parts)), 0, -1):  # Check 4, 3, 2, 1 words
        candidate = "_".join(parts[:num_words])
        if candidate in KNOWN_MULTI_WORD_PATTERNS:
            return KNOWN_MULTI_WORD_PATTERNS[candidate]

    # Fall back to single word check
    first_word = parts[0]
    if first_word in COMPANY_PATTERNS:
        return COMPANY_PATTERNS[first_word]

    # If no pattern matched, this is a NEW company - FAIL FAST
    raise ValueError(f"UNKNOWN COMPANY PATTERN: '{first_word}' from file '{filename}'. "
                    f"Add to COMPANY_PATTERNS mapping!")


def extract_text(pdf_path: str, max_pages: int = 3, dpi: int = 200) -> str:
    # Always try OCR first with better settings for better text extraction
    try:
        pages = convert_from_path(pdf_path, last_page=max_pages, dpi=dpi)
        if not pages:
            return ""

        text_parts = []
        for i, page in enumerate(pages):
            try:
                # Use better OCR configuration
                ocr_config = '--psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789@.-_'
                ocr_text = pytesseract.image_to_string(page, config=ocr_config)
                text_parts.append(ocr_text)
                page.close()
            except Exception as e:
                logging.warning(f"OCR failed for page {i+1} of {pdf_path}: {e}")
                try:
                    # Fallback to basic OCR
                    fallback_text = pytesseract.image_to_string(page)
                    text_parts.append(fallback_text)
                except:
                    pass
                page.close()
                continue

        ocr_result = "\n".join(text_parts)
        if ocr_result.strip():
            return ocr_result
    except MemoryError as e:
        logging.error(f"Out of memory processing {pdf_path}: {e}")
    except Exception as e:
        logging.warning(f"OCR processing failed for {pdf_path}: {e}")

    # Fallback to PyPDF2 extraction
    try:
        with open(pdf_path, "rb") as file:
            reader = PyPDF2.PdfReader(file)
            text_parts = []
            for page in reader.pages[:max_pages]:
                try:
                    text_parts.append(page.extract_text())
                except Exception as e:
                    logging.warning(f"Failed to extract text from page in {pdf_path}: {e}")
                    continue

            text = "".join(text_parts)
            if text.strip():
                return text
    except (PyPDF2.errors.PdfReadError, FileNotFoundError, PermissionError) as e:
        logging.warning(f"PyPDF2 extraction failed for {pdf_path}: {e}")
    except Exception as e:
        logging.error(f"Unexpected error during PDF text extraction for {pdf_path}: {e}")

    return ""


def check_match(text: str, company: str) -> bool:
    if not text or not company:
        return False

    # Normalize text for better matching
    text_clean = re.sub(r'[^\w\s]', ' ', text.lower())
    text_clean = re.sub(r'\s+', ' ', text_clean).strip()

    company_lower = company.lower()

    # Create regex patterns for flexible matching
    patterns = []

    # 1. Direct company name with word boundaries
    patterns.append(rf'\b{re.escape(company_lower)}\b')

    # 2. Company name with common business suffixes
    business_suffixes = [
        r'computer\s+(?:pte\s+)?ltd?',
        r'tech(?:nology)?\s+(?:pte\s+)?ltd?',
        r'asia\s+(?:pte\s+)?ltd?',
        r'international\s+(?:pte\s+)?ltd?',
        r'distributor\s+(?:pte\s+)?ltd?',
        r'(?:pte\s+)?ltd?'
    ]

    for suffix in business_suffixes:
        patterns.append(rf'\b{re.escape(company_lower)}\s+{suffix}\b')

    # 3. For multi-word companies, handle variations
    if " " in company_lower:
        words = company_lower.split()

        # All words present with word boundaries
        word_pattern = r'\b' + r'.*?\b'.join(re.escape(word) for word in words) + r'\b'
        patterns.append(word_pattern)

        # With underscores instead of spaces
        underscore_name = '_'.join(words)
        patterns.append(rf'\b{re.escape(underscore_name)}\b')

        # Each word individually (all must be present)
        if all(re.search(rf'\b{re.escape(word)}\b', text_clean) for word in words):
            return True

    # 4. Handle common variations, abbreviations, and email patterns
    company_variations = {
        'pc themes': [r'\bpc\s+themes?\b', r'\bpc.*themes?\b', r'pcthemes'],
        'tradepac': [r'\btrade\s*pac\b', r'\btradepac\b', r'tradepac'],
        'techdeals': [r'\btech\s*deals?\b', r'\btechdeals?\b', r'techdeals'],
        'bizgram': [r'\bbiz\s*gram\b', r'\bbizgram\b', r'bizgram'],
        'dynacore': [r'\bdyna\s*core\b', r'\bdynacore\b', r'dynacore'],
        'fuwell': [r'\bfu\s*well\b', r'\bfuwell\b', r'fuwell'],
        'infinity': [
            r'\binfinit[yi]\b',
            r'\binfinit[yi]\s+computer\b',
            r'infinitycomputer',  # Email domain
            r'@infinitycomputer\.com',  # Email pattern
            r'infinit[yi].*computer',  # Flexible matching
            r'ate\s+computer',  # OCR mangled "INFINITY" -> "atte"
            r'nfinity',  # Partial OCR
            r'infinit'  # Partial match
        ],
        'laser': [r'\blaser\b', r'\blaser\s+distributor\b', r'laser']
    }

    if company_lower in company_variations:
        patterns.extend(company_variations[company_lower])

    # 5. Add email domain patterns for all companies
    email_patterns = [
        rf'{re.escape(company_lower)}\.com',
        rf'@{re.escape(company_lower)}\.com',
        rf'{re.escape(company_lower.replace(" ", ""))}\.com',
        rf'@{re.escape(company_lower.replace(" ", ""))}\.',
    ]
    patterns.extend(email_patterns)

    # Test all patterns
    for pattern in patterns:
        if re.search(pattern, text_clean, re.IGNORECASE):
            return True

    return False


def extract_company(filename: str) -> Optional[str]:
    """
    Extract company name using robust pattern matching with fail-fast validation.
    Returns None only for actual errors, raises ValueError for unknown patterns.
    """
    if not filename or not filename.strip():
        logging.warning(f"Invalid filename: {filename}")
        return None

    try:
        return extract_company_robust(filename)
    except ValueError as e:
        # FAIL FAST: Unknown company patterns should not be silently ignored
        logging.error(f"UNKNOWN COMPANY PATTERN: {e}")
        raise e  # Re-raise to fail fast
    except Exception as e:
        logging.error(f"Unexpected error extracting company from filename {filename}: {e}")
        return None


def analyze_pdf(pdf_path: Path, max_pages: int = 3, dpi: int = 150) -> Dict[str, any]:
    company = extract_company(pdf_path.name)
    if company is None:
        return {
            "file": str(pdf_path),
            "expected": None,
            "matches": False,
            "text_length": 0,
            "error": "Failed to extract company name"
        }

    text = extract_text(str(pdf_path), max_pages, dpi)
    matches = check_match(text, company)

    return {
        "file": str(pdf_path),
        "expected": company,
        "matches": matches,
        "text_length": len(text)
    }

def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    parser = argparse.ArgumentParser(description="Analyze PDFs for company name matches")
    parser.add_argument("directory", nargs="?", default="downloads", help="Directory to scan for PDFs")
    parser.add_argument("-w", "--workers", type=int, default=min(4, os.cpu_count() or 1), help="Number of parallel workers")
    parser.add_argument("-l", "--limit", type=int, help="Limit number of files to process")
    parser.add_argument("-p", "--pages", type=int, default=3, help="Number of pages to analyze per PDF")
    parser.add_argument("--dpi", type=int, default=150, help="DPI for OCR image conversion")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    pdf_files = list(Path(args.directory).glob("**/*.pdf"))
    if not pdf_files:
        print(f"No PDFs found in {args.directory}")
        return

    if args.limit:
        pdf_files = pdf_files[:args.limit]

    print(f"Processing {len(pdf_files)} PDFs with {args.workers} workers...")

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(analyze_pdf, pdf, args.pages, args.dpi): pdf for pdf in pdf_files}

        for future in tqdm(as_completed(futures), total=len(pdf_files), desc="Analyzing"):
            results.append(future.result())

    problematic = [r for r in results if not r["matches"]]

    print(f"Analyzed {len(results)} PDFs")
    print(f"Problematic: {len(problematic)}")

    if problematic:
        with open("problematic.json", "w") as f:
            json.dump(problematic, f, indent=2)
        print("Saved problematic.json")


if __name__ == "__main__":
    main()