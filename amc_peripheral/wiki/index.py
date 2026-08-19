"""Wiki index generation and caching."""

import logging
from typing import Optional

from amc_peripheral.wiki.storage import WikiStorage

log = logging.getLogger(__name__)


class WikiIndex:
    """Generates and caches a compact index of the wiki for LLM context building."""

    def __init__(self, storage: WikiStorage):
        self.storage = storage

    def build_index(self) -> str:
        """Build a compact index string from all wiki pages.

        Groups pages by category and shows counts + sample titles.
        """
        pages = self.storage.list_pages(limit=10000)
        if not pages:
            return ""

        # Group by category
        categories: dict[str, list[dict]] = {}
        for page in pages:
            cat = page["category"]
            categories.setdefault(cat, []).append(page)

        lines = ["Annie's Wiki Index:"]
        for cat, cat_pages in sorted(categories.items()):
            # Locations are the "where is X" content — show more of them so real
            # place pages (e.g. 'Oji Drilling') aren't hidden behind "(+N more)".
            sample_cap = 20 if cat == "location" else 5
            sample = ", ".join(
                p["title"] for p in sorted(cat_pages, key=lambda x: x["title"])[:sample_cap]
            )
            if len(cat_pages) > sample_cap:
                sample += f", ... (+{len(cat_pages) - sample_cap} more)"
            lines.append(f"- {cat} ({len(cat_pages)}): {sample}")

        index = "\n".join(lines)
        self.storage.set_index_cache(index)
        log.info(f"Wiki index rebuilt: {len(pages)} pages across {len(categories)} categories")
        return index

    def get_index(self, force_rebuild: bool = False) -> str:
        """Get the wiki index, rebuilding if missing or forced."""
        if not force_rebuild:
            cached = self.storage.get_index_cache()
            if cached:
                return cached
        return self.build_index()

    def get_category_summary(self, category: str) -> str:
        """Get a summary of pages in a specific category."""
        pages = self.storage.list_pages(category=category, limit=1000)
        if not pages:
            return f"No pages found in category '{category}'."

        lines = [f"Category: {category} ({len(pages)} pages)"]
        for page in sorted(pages, key=lambda x: x["title"]):
            summary = page.get("summary", "") or page.get("content", "")[:100]
            lines.append(f"- {page['title']}: {summary}")
        return "\n".join(lines)

    def get_page_context(self, page_id: int, include_links: bool = True) -> str:
        """Build a formatted context string for a single wiki page.

        Includes the page content, summary, and optionally linked pages.
        """
        page = self.storage.get_page_by_id(page_id)
        if not page:
            return ""

        lines = [
            f"--- Wiki Page: {page['title']} ---",
            f"Category: {page['category']}",
            f"Summary: {page.get('summary', '')}",
            f"Content:\n{page['content']}",
        ]

        if include_links:
            outbound = self.storage.get_links_from(page_id)
            inbound = self.storage.get_links_to(page_id)
            if outbound:
                links = ", ".join(l["to_title"] for l in outbound)
                lines.append(f"Links to: {links}")
            if inbound:
                links = ", ".join(l["from_title"] for l in inbound)
                lines.append(f"Linked from: {links}")

        return "\n".join(lines)

    def get_multi_page_context(self, page_ids: list[int]) -> str:
        """Build a combined context string for multiple pages."""
        contexts = []
        for pid in page_ids:
            ctx = self.get_page_context(pid, include_links=False)
            if ctx:
                contexts.append(ctx)
        return "\n\n".join(contexts)
