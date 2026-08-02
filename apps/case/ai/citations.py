"""
Citation extraction and verification for AI responses.

Uses eyecite for parsing citations and CourtListener API for case validation.
"""

import difflib
import json
import logging
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests
from django.conf import settings
from eyecite import get_citations
from eyecite.models import CaseCitation, FullLawCitation

from apps.case.courtlistener_throttle import throttled_request

logger = logging.getLogger(__name__)

# Load Georgia Code mapping for accurate Justia URLs
_GA_CODE_MAPPING = {}
_GA_CODE_MAPPING_PATH = Path(__file__).parent / "ga_code_mapping.json"
try:
    if _GA_CODE_MAPPING_PATH.exists():
        with open(_GA_CODE_MAPPING_PATH) as f:
            _GA_CODE_MAPPING = json.load(f)
except Exception as e:
    logger.warning("Failed to load Georgia Code mapping: %s", e)


@dataclass
class VerifiedCitation:
    """Represents a verified or unverified citation."""

    original_text: str
    citation_type: str  # "case", "statute", "unknown"
    normalized: Optional[str] = None
    is_valid: Optional[bool] = None  # None = not checked, True/False = checked
    confidence: Optional[float] = None  # 0.0-1.0 confidence score for case matches
    url: Optional[str] = None
    source: Optional[str] = None  # "CourtListener", "Cornell LII", "Justia"
    case_name: Optional[str] = None
    case_name_ai: Optional[str] = None  # The case name from AI's citation
    error: Optional[str] = None


def normalize_party_name(name: str) -> str:
    """
    Normalize a party name for comparison.

    Removes common legal suffixes, punctuation, and normalizes whitespace.
    """
    if not name:
        return ""

    # Convert to lowercase
    name = name.lower()

    # Remove common legal entity suffixes
    suffixes = [
        r"\b(inc|llc|llp|corp|co|ltd|l\.?l\.?c\.?|l\.?l\.?p\.?|"
        r"corporation|company|incorporated|limited)\.?\b",
        r"\bet\s*al\.?\b",
        r"\bin\s+re\b",
    ]
    for suffix in suffixes:
        name = re.sub(suffix, "", name, flags=re.IGNORECASE)

    # Remove punctuation except spaces
    name = re.sub(r"[^\w\s]", " ", name)

    # Normalize whitespace
    name = " ".join(name.split())

    return name.strip()


def extract_party_names(case_name: str) -> tuple[str, str]:
    """
    Extract plaintiff and defendant names from a case name.

    Returns tuple of (plaintiff, defendant) normalized names.
    Handles "v." and "vs." separators.
    """
    if not case_name:
        return ("", "")

    # Split on v. or vs.
    parts = re.split(
        r"\s+v\.?\s+|\s+vs\.?\s+", case_name, maxsplit=1, flags=re.IGNORECASE
    )

    if len(parts) == 2:
        plaintiff = normalize_party_name(parts[0])
        defendant = normalize_party_name(parts[1])
        return (plaintiff, defendant)
    else:
        # No "v." found - return the whole thing normalized
        return (normalize_party_name(case_name), "")


def calculate_case_name_similarity(ai_name: str, cl_name: str) -> float:
    """
    Calculate similarity between AI's case name and CourtListener's case name.

    Returns a score from 0.0 to 1.0:
    - 1.0 = exact match (high confidence)
    - 0.7+ = likely same case (different abbreviations)
    - 0.3-0.7 = uncertain
    - <0.3 = likely different cases (possible hallucination)
    """
    if not ai_name or not cl_name:
        return 0.0

    ai_plaintiff, ai_defendant = extract_party_names(ai_name)
    cl_plaintiff, cl_defendant = extract_party_names(cl_name)

    logger.debug("Comparing names: AI='%s' vs CL='%s'", ai_name, cl_name)
    logger.debug(
        "  Parsed: AI=(%s, %s) vs CL=(%s, %s)",
        ai_plaintiff,
        ai_defendant,
        cl_plaintiff,
        cl_defendant,
    )

    # Calculate similarity for each party
    # Use SequenceMatcher for fuzzy string matching
    def similarity(a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        return difflib.SequenceMatcher(None, a, b).ratio()

    # Check both orderings (sometimes parties are swapped)
    # Normal order: AI plaintiff vs CL plaintiff, AI defendant vs CL defendant
    normal_score = (
        similarity(ai_plaintiff, cl_plaintiff) + similarity(ai_defendant, cl_defendant)
    ) / 2

    # Swapped order: AI plaintiff vs CL defendant, AI defendant vs CL plaintiff
    swapped_score = (
        similarity(ai_plaintiff, cl_defendant) + similarity(ai_defendant, cl_plaintiff)
    ) / 2

    # Also check if one party name appears in the other's full name
    # This handles cases like "Smith" vs "Smith Industries"
    def partial_match(a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        if a in b or b in a:
            return 0.8
        # Check if any significant word matches
        a_words = set(a.split()) - {"the", "of", "and", "a", "an"}
        b_words = set(b.split()) - {"the", "of", "and", "a", "an"}
        if a_words and b_words and a_words & b_words:
            return 0.6
        return 0.0

    partial_plaintiff = partial_match(ai_plaintiff, cl_plaintiff)
    partial_defendant = partial_match(ai_defendant, cl_defendant)
    partial_score = (partial_plaintiff + partial_defendant) / 2

    final_score = max(normal_score, swapped_score, partial_score)

    logger.debug(
        "  Scores: normal=%.2f, swapped=%.2f, partial=%.2f -> final=%.2f",
        normal_score,
        swapped_score,
        partial_score,
        final_score,
    )

    return final_score


def extract_case_name_from_context(text: str, citation_text: str) -> Optional[str]:
    """
    Extract the case name that appears before a citation in text.

    For example, from "See Roe v. Wade, 410 U.S. 113 (1973)" with
    citation_text="410 U.S. 113", this would extract "Roe v. Wade".

    Handles markdown formatting (italics with * or _).
    """
    if not text or not citation_text:
        return None

    # Find the citation in the text
    citation_pos = text.find(citation_text)
    if citation_pos == -1:
        return None

    # Look at the text before the citation (up to 150 chars back)
    before_text = text[max(0, citation_pos - 150) : citation_pos]

    # Remove markdown formatting (asterisks and underscores for italics/bold)
    before_text_clean = re.sub(r"[*_]", "", before_text)

    # Pattern to match case names, handling various formats:
    # - "Smith v. Jones" (simple)
    # - "A. L. Williams & Assocs. v. Faircloth" (initials, ampersand)
    # - "In re Smith" (special format)
    case_name_pattern = (
        r"([A-Z][A-Za-z\.\s&'\-,]+?)"  # Plaintiff (lazy match)
        r"\s+v\.?\s+"  # "v." or "v"
        r"([A-Z][A-Za-z\.\s&'\-,]+?)"  # Defendant (lazy match)
        r",?\s*$"  # Optional comma, end of string
    )

    match = re.search(case_name_pattern, before_text_clean)
    if match:
        plaintiff = match.group(1).strip().rstrip(",")
        defendant = match.group(2).strip().rstrip(",")

        # Remove common prefixes like "See", "In", "Cf."
        prefix_pattern = r"^(?:See|In|Cf\.?|E\.g\.?,?|Compare)\s+"
        plaintiff = re.sub(prefix_pattern, "", plaintiff, flags=re.IGNORECASE)

        case_name = f"{plaintiff} v. {defendant}"
        return case_name

    return None


def extract_citations_from_text(text: str) -> list:
    """
    Use eyecite to extract all citations from text.

    Returns list of eyecite citation objects.
    """
    try:
        citations = get_citations(text)
        return list(citations)
    except Exception as e:
        logger.exception("Error extracting citations: %s", e)
        return []


def verify_case_citations_batch(text: str, api_token: str) -> list[dict]:
    """
    Call CourtListener API to verify all case citations in text.

    Args:
        text: The full text containing citations
        api_token: CourtListener API token

    Returns:
        List of citation result dicts from CourtListener API
    """
    if not api_token:
        logger.warning("No CourtListener API token configured")
        return []

    # Truncate text if too long (API limit is 64,000 chars)
    if len(text) > 60000:
        text = text[:60000]

    try:
        response = throttled_request(
            "post",
            "https://www.courtlistener.com/api/rest/v4/citation-lookup/",
            headers={"Authorization": f"Token {api_token}"},
            data={"text": text},
            timeout=30,
        )

        if response.status_code == 200:
            result = response.json()
            logger.debug("CourtListener API response: %s", result)
            return result
        else:
            logger.error(
                "CourtListener API error: %s - %s",
                response.status_code,
                response.text[:200],
            )
            return []

    except requests.RequestException as e:
        logger.exception("Error calling CourtListener API: %s", e)
        return []


def check_url_exists(url: str, timeout: float = 3.0) -> bool:
    """
    Check if a URL exists by making a HEAD request.
    Returns True if the URL returns a 200 status code.
    """
    try:
        response = requests.head(url, timeout=timeout, allow_redirects=True)
        return response.status_code == 200
    except requests.RequestException:
        return False


def find_working_url(urls: list[str], timeout: float = 3.0) -> Optional[str]:
    """
    Try multiple URLs and return the first one that works.
    Returns None if none of the URLs work.
    """
    for url in urls:
        logger.debug("Checking URL: %s", url)
        if check_url_exists(url, timeout):
            logger.debug("  -> URL works!")
            return url
        logger.debug("  -> URL failed")
    return None


def generate_usc_url(title: str, section: str) -> Optional[str]:
    """Generate Cornell LII URL for a USC citation, validating it exists."""
    # Clean up the section number (remove subsections for the base URL)
    base_section = section.split("(")[0].strip()

    # Try different URL patterns
    urls = [
        f"https://www.law.cornell.edu/uscode/text/{title}/{base_section}",
        f"https://www.law.cornell.edu/uscode/text/{title}/{section}",
    ]

    return find_working_url(urls)


def generate_georgia_url(title: str, chapter: str, section: str) -> tuple[str, bool]:
    """
    Generate Justia URL for a Georgia (OCGA) citation.

    Returns tuple of (url, is_direct_link).
    - is_direct_link=True means it's a direct URL to the statute
    - is_direct_link=False means it's a search URL (fallback)

    Uses the Georgia Code mapping to determine the correct article
    for chapters that have article subdivisions.
    """
    full_section = f"{title}-{chapter}-{section}"
    chapter_key = f"{title}-{chapter}"

    # Look up the article in the mapping
    chapter_mapping = _GA_CODE_MAPPING.get(chapter_key, {})
    article = chapter_mapping.get(section)

    if article:
        # We have an article mapping - generate direct URL with article
        url = (
            f"https://law.justia.com/codes/georgia/"
            f"title-{title}/chapter-{chapter}/article-{article}/section-{full_section}/"
        )
        logger.debug(
            "Georgia URL for %s: article %s found -> %s", full_section, article, url
        )
        return (url, True)
    elif chapter_key in _GA_CODE_MAPPING:
        # Chapter has articles but section not in mapping - may be new/amended
        # Fall back to search
        logger.debug(
            "Georgia URL for %s: chapter has articles but section not mapped",
            full_section,
        )
        search_query = urllib.parse.quote_plus(f"GA Code § {full_section}")
        return (f"https://law.justia.com/search?q={search_query}", False)
    else:
        # Chapter not in mapping - try direct URL without article
        # (some chapters don't have articles)
        url = (
            f"https://law.justia.com/codes/georgia/"
            f"title-{title}/chapter-{chapter}/section-{full_section}/"
        )
        logger.debug(
            "Georgia URL for %s: no article mapping, trying direct -> %s",
            full_section,
            url,
        )
        return (url, True)


def parse_statute_citation(citation_text: str) -> Optional[dict]:
    """
    Parse a statute citation to extract components.

    Returns dict with 'type', 'title', 'section', etc. or None if not parseable.
    """
    # USC pattern: 42 U.S.C. § 1983, 17 USC § 107, etc.
    usc_pattern = r"(\d+)\s*U\.?S\.?C\.?\s*§?\s*(\d+[a-zA-Z0-9\-]*)"
    usc_match = re.search(usc_pattern, citation_text, re.IGNORECASE)
    if usc_match:
        return {
            "type": "usc",
            "title": usc_match.group(1),
            "section": usc_match.group(2),
        }

    # OCGA pattern: O.C.G.A. § 9-11-56, Ga. Code § 9-11-56, etc.
    ocga_pattern = r"(?:O\.?C\.?G\.?A\.?|Ga\.?\s*Code)\s*§?\s*(\d+)-(\d+)-(\d+)"
    ocga_match = re.search(ocga_pattern, citation_text, re.IGNORECASE)
    if ocga_match:
        return {
            "type": "ocga",
            "title": ocga_match.group(1),
            "chapter": ocga_match.group(2),
            "section": ocga_match.group(3),
        }

    # CFR pattern: 42 C.F.R. § 423.120
    cfr_pattern = r"(\d+)\s*C\.?F\.?R\.?\s*§?\s*([\d\.]+)"
    cfr_match = re.search(cfr_pattern, citation_text, re.IGNORECASE)
    if cfr_match:
        return {
            "type": "cfr",
            "title": cfr_match.group(1),
            "section": cfr_match.group(2),
        }

    return None


def generate_statute_url(citation_text: str) -> Optional[tuple[str, str]]:
    """
    Generate URL for a statute citation.

    Returns tuple of (url, source_name) or None if not parseable.
    Validates URLs exist before returning them.
    """
    parsed = parse_statute_citation(citation_text)
    if not parsed:
        return None

    if parsed["type"] == "usc":
        url = generate_usc_url(parsed["title"], parsed["section"])
        if url:
            return (url, "Cornell LII")
        # Fallback to search
        search_query = urllib.parse.quote(citation_text)
        return (
            f"https://www.law.cornell.edu/uscode/search?search={search_query}",
            "Cornell LII Search",
        )

    elif parsed["type"] == "ocga":
        url, is_direct = generate_georgia_url(
            parsed["title"], parsed["chapter"], parsed["section"]
        )
        if is_direct:
            return (url, "Justia")
        else:
            return (url, "Justia Search")

    elif parsed["type"] == "cfr":
        # Cornell LII also has CFR - try to validate
        base_url = (
            f"https://www.law.cornell.edu/cfr/text/"
            f"{parsed['title']}/{parsed['section']}"
        )
        if check_url_exists(base_url):
            return (base_url, "Cornell LII")
        # Fallback to search
        search_query = urllib.parse.quote(citation_text)
        return (
            f"https://www.law.cornell.edu/cfr/search?search={search_query}",
            "Cornell LII Search",
        )

    return None


def verify_all_citations(text: str) -> list[VerifiedCitation]:
    """
    Extract and verify all citations in the given text.

    Args:
        text: Text containing legal citations (typically AI response)

    Returns:
        List of VerifiedCitation objects
    """
    logger.debug("Starting citation verification for text of length %d", len(text))
    api_token = getattr(settings, "COURTLISTENER_API_TOKEN", "")
    results = []
    seen_citations = set()  # Avoid duplicates

    # Extract citations using eyecite
    eyecite_citations = extract_citations_from_text(text)
    logger.debug("eyecite found %d citations", len(eyecite_citations))
    for ec in eyecite_citations:
        logger.debug("  eyecite: '%s' (%s)", ec.matched_text(), type(ec).__name__)

    # Get CourtListener verification for case citations (batch API call)
    # API returns a list of citation results
    cl_results_list = []
    if api_token:
        cl_results_list = verify_case_citations_batch(text, api_token)
        if isinstance(cl_results_list, list):
            logger.debug("CourtListener returned %d results", len(cl_results_list))
            for cl_item in cl_results_list:
                logger.debug("  CL result: %s", cl_item)
        else:
            logger.warning(
                "Unexpected CourtListener response type: %s", type(cl_results_list)
            )
            cl_results_list = []

    # Process each citation
    for citation in eyecite_citations:
        citation_text = citation.matched_text()

        # Skip duplicates
        if citation_text in seen_citations:
            continue
        seen_citations.add(citation_text)

        if isinstance(citation, CaseCitation):
            # Case citation - check CourtListener results
            verified = VerifiedCitation(
                original_text=citation_text,
                citation_type="case",
            )

            # Try to extract the case name the AI used from context
            ai_case_name = extract_case_name_from_context(text, citation_text)
            if ai_case_name:
                verified.case_name_ai = ai_case_name
                logger.debug("Extracted AI case name: '%s'", ai_case_name)

            # Look for this citation in CourtListener results
            # The API returns a list of citation objects
            found_in_cl = False
            for cl_item in cl_results_list:
                cl_citation = cl_item.get("citation", "")
                if citation_text in cl_citation or cl_citation in citation_text:
                    found_in_cl = True
                    if cl_item.get("status") == 200:
                        verified.source = "CourtListener"
                        # Extract URL and case name from clusters
                        clusters = cl_item.get("clusters", [])
                        if clusters:
                            absolute_url = clusters[0].get("absolute_url")
                            if absolute_url:
                                verified.url = (
                                    f"https://www.courtlistener.com{absolute_url}"
                                )
                            verified.case_name = clusters[0].get("case_name")

                        if cl_item.get("normalized_citations"):
                            verified.normalized = cl_item["normalized_citations"][0]

                        # Calculate confidence based on case name match
                        if ai_case_name and verified.case_name:
                            confidence = calculate_case_name_similarity(
                                ai_case_name, verified.case_name
                            )
                            verified.confidence = round(confidence, 2)

                            # Determine validity based on confidence
                            if confidence >= 0.5:
                                verified.is_valid = True
                            else:
                                verified.is_valid = False
                                verified.error = (
                                    f"Case name mismatch: AI cited "
                                    f"'{ai_case_name}' but citation links to "
                                    f"'{verified.case_name}' "
                                    f"(confidence: {confidence:.0%})"
                                )
                            logger.debug(
                                "Case name match: AI='%s' CL='%s' -> %.2f (%s)",
                                ai_case_name,
                                verified.case_name,
                                confidence,
                                "VALID" if verified.is_valid else "MISMATCH",
                            )
                        else:
                            # Can't extract AI case name - can't verify, mark as unknown
                            verified.is_valid = None
                            verified.confidence = None
                            verified.error = "Could not verify case name"
                    else:
                        verified.is_valid = False
                        verified.error = "Not found in CourtListener database"
                        # Still provide search URL for manual verification
                        search_query = urllib.parse.quote(citation_text)
                        verified.url = (
                            f"https://www.courtlistener.com/?q={search_query}&type=o"
                        )
                        verified.source = "CourtListener Search"
                    break

            if not found_in_cl:
                # Not found in API results - generate a search URL anyway
                # so users can manually verify
                search_query = urllib.parse.quote(citation_text)
                verified.url = f"https://www.courtlistener.com/?q={search_query}&type=o"
                verified.source = "CourtListener Search"
                if api_token:
                    # API was called but citation wasn't recognized
                    verified.is_valid = False
                    verified.error = "Citation not verified"
                else:
                    # No API token - can't verify, but provide search link
                    verified.is_valid = None  # Unknown status

            results.append(verified)

        elif isinstance(citation, FullLawCitation):
            # Statute citation - generate URL
            verified = VerifiedCitation(
                original_text=citation_text,
                citation_type="statute",
            )

            url_result = generate_statute_url(citation_text)
            if url_result:
                verified.url, verified.source = url_result
                # Only mark as verified if URL was actually validated via HTTP
                # Cornell LII links (USC/CFR) are verified, Justia links use mapping
                if verified.source == "Cornell LII":
                    verified.is_valid = True  # URL verified via HTTP check
                else:
                    verified.is_valid = None  # URL generated but not verified

            results.append(verified)

    # Also try to find statute citations that eyecite might have missed
    # (eyecite is primarily designed for case citations)
    statute_patterns = [
        (r"\d+\s*U\.?S\.?C\.?\s*§\s*\d+", "usc"),
        (r"O\.?C\.?G\.?A\.?\s*§\s*\d+-\d+-\d+", "ocga"),
        (r"Ga\.?\s*Code\s*§\s*\d+-\d+-\d+", "ocga"),
        (r"\d+\s*C\.?F\.?R\.?\s*§\s*[\d\.]+", "cfr"),
    ]

    for pattern, _ in statute_patterns:
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        for match in matches:
            citation_text = match.group()
            if citation_text not in seen_citations:
                seen_citations.add(citation_text)

                verified = VerifiedCitation(
                    original_text=citation_text,
                    citation_type="statute",
                )

                url_result = generate_statute_url(citation_text)
                if url_result:
                    verified.url, verified.source = url_result
                    # Only mark as verified if URL was actually validated via HTTP
                    # Cornell LII links (USC/CFR) are verified, Justia links use mapping
                    if verified.source == "Cornell LII":
                        verified.is_valid = True  # URL verified via HTTP check
                    else:
                        verified.is_valid = None  # URL generated but not verified

                results.append(verified)

    logger.debug("Citation verification complete. Total results: %d", len(results))

    return results


def citations_to_dict(citations: list[VerifiedCitation]) -> list[dict]:
    """Convert list of VerifiedCitation to JSON-serializable dicts."""
    return [
        {
            "original_text": c.original_text,
            "citation_type": c.citation_type,
            "normalized": c.normalized,
            "is_valid": c.is_valid,
            "confidence": c.confidence,
            "url": c.url,
            "source": c.source,
            "case_name": c.case_name,
            "case_name_ai": c.case_name_ai,
            "error": c.error,
        }
        for c in citations
    ]


def dict_to_citations(data: list[dict]) -> list[VerifiedCitation]:
    """Convert JSON dicts back to VerifiedCitation objects."""
    return [
        VerifiedCitation(
            original_text=d["original_text"],
            citation_type=d["citation_type"],
            normalized=d.get("normalized"),
            is_valid=d.get("is_valid"),
            confidence=d.get("confidence"),
            url=d.get("url"),
            source=d.get("source"),
            case_name=d.get("case_name"),
            case_name_ai=d.get("case_name_ai"),
            error=d.get("error"),
        )
        for d in data
    ]
