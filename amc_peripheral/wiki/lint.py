"""Lint orchestrator: scan wiki for issues and propose/auto-apply fixes."""

import logging
from typing import Optional

from amc_peripheral.wiki.storage import WikiStorage
from amc_peripheral.wiki.retrieval import WikiRetrieval

log = logging.getLogger(__name__)


class WikiLint:
    """Scans the wiki for contradictions, orphans, stale pages, and missing links."""

    def __init__(self, storage: WikiStorage, retrieval: WikiRetrieval):
        self.storage = storage
        self.retrieval = retrieval

    def run_lint(self, auto_fix: bool = False) -> dict:
        """Run all lint checks and return a report.

        Args:
            auto_fix: If True, apply low-risk fixes automatically.

        Returns:
            Dict with keys: orphans, stale, missing_links, contradictions, inactive_players, fixes_applied.
        """
        report = {
            "orphans": [],
            "stale": [],
            "missing_links": [],
            "contradictions": [],
            "inactive_players": [],
            "fixes_applied": [],
        }

        # Orphan pages
        orphans = self.storage.get_orphan_pages()
        report["orphans"] = [dict(p) for p in orphans]
        if auto_fix and orphans:
            # Low-risk fix: log orphan detection, but don't auto-delete
            for page in orphans:
                report["fixes_applied"].append(
                    f"Flagged orphan page: {page['title']} (id={page['id']})"
                )

        # Stale pages
        stale = self.storage.get_stale_pages(days=30)
        report["stale"] = [dict(p) for p in stale]

        # Missing cross-references: pages that mention other page titles but have no link
        missing_links = self._find_missing_links()
        report["missing_links"] = missing_links
        if auto_fix and missing_links:
            for item in missing_links:
                self.storage.add_link(item["from_page_id"], item["to_page_id"], "mentions")
                report["fixes_applied"].append(
                    f"Added link: {item['from_title']} -> {item['to_title']}"
                )

        # Inactive players
        inactive_players = self._find_inactive_players(days=14)
        report["inactive_players"] = inactive_players
        if auto_fix and inactive_players:
            for player in inactive_players:
                # Update summary to mark inactive
                new_summary = f"{player['summary']} [Inactive]".strip()
                self.storage.update_page(player["id"], summary=new_summary)
                report["fixes_applied"].append(
                    f"Marked player inactive: {player['title']}"
                )

        # Log the lint operation
        total_issues = (
            len(orphans) + len(stale) + len(missing_links) + len(inactive_players)
        )
        self.storage.log_operation(
            operation="lint",
            description=f"Lint completed: {total_issues} issues found, {len(report['fixes_applied'])} fixes applied",
            pages_affected=None,
        )
        log.info(f"Wiki lint: {total_issues} issues, {len(report['fixes_applied'])} auto-fixed")
        return report

    def _find_missing_links(self) -> list[dict]:
        """Find pages that mention other page titles in their content but have no link."""
        pages = self.storage.list_pages(limit=10000)
        if not pages:
            return []

        # Build a map of title -> page_id for quick lookup
        title_map: dict[str, int] = {}
        for page in pages:
            title_map[page["title"].lower()] = page["id"]
            # Also index by slug without prefix
            simple = page["title"].split(":")[-1].strip().lower()
            if simple and simple != page["title"].lower():
                title_map[simple] = page["id"]

        missing = []
        for page in pages:
            content_lower = page.get("content", "").lower()
            existing_links = {
                link["to_page_id"] for link in self.storage.get_links_from(page["id"])
            }

            for title, target_id in title_map.items():
                if target_id == page["id"]:
                    continue
                if target_id in existing_links:
                    continue
                # Simple substring check for mentions (min 3 chars to avoid noise)
                if len(title) >= 3 and title in content_lower:
                    missing.append({
                        "from_page_id": page["id"],
                        "from_title": page["title"],
                        "to_page_id": target_id,
                        "to_title": self.storage.get_page_by_id(target_id)["title"],
                    })
                    break  # Only flag first missing link per page to avoid noise

        return missing

    def _find_inactive_players(self, days: int = 14) -> list[dict]:
        """Find player pages not updated in the last N days."""
        all_players = self.storage.list_pages(category="player", limit=10000)
        if not all_players:
            return []

        # Single query for all stale pages, then filter by category in-memory
        stale = self.storage.get_stale_pages(days=days)
        stale_ids = {p["id"] for p in stale}

        inactive = []
        for player in all_players:
            # Check if already marked inactive
            summary = player.get("summary", "")
            if "[Inactive]" in summary:
                continue
            if player["id"] in stale_ids:
                inactive.append(dict(player))
        return inactive

    def get_contradiction_candidates(self) -> list[dict]:
        """Find pages that might contradict each other.

        This is a lightweight heuristic: pages in the same category with
        overlapping content keywords but different claims.
        Full contradiction detection requires LLM analysis (Phase 4).
        """
        # Placeholder for Phase 4: return pages that share keywords but have no link
        pages = self.storage.list_pages(limit=1000)
        candidates = []
        for i, page_a in enumerate(pages):
            for page_b in pages[i + 1 :]:
                if page_a["category"] != page_b["category"]:
                    continue
                # Simple keyword overlap heuristic
                words_a = set(page_a.get("content", "").lower().split())
                words_b = set(page_b.get("content", "").lower().split())
                overlap = words_a & words_b
                if len(overlap) > 10:
                    candidates.append({
                        "page_a_id": page_a["id"],
                        "page_a_title": page_a["title"],
                        "page_b_id": page_b["id"],
                        "page_b_title": page_b["title"],
                        "overlap_count": len(overlap),
                    })
        return candidates
