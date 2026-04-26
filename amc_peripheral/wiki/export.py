"""Markdown export for Annie's wiki.

Nightly dump of the wiki DB to a directory of markdown files for
human browsing (Obsidian/VS Code/file explorer). The DB remains the
source of truth; this is a read-only mirror.

Layout (under `output_dir`):

    output_dir/
    ├── index.md              # Table of contents grouped by category
    ├── log.md                # Karpathy-style append-only operations log
    ├── players/
    │   ├── freemanlatif.md
    │   └── ...
    ├── concepts/
    ├── events/
    └── ...

Each page file has YAML front matter (title, slug, category, timestamps,
source_count, tags) followed by the page body (summary, content, inbound
and outbound links).
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
from datetime import datetime
from typing import Optional

from amc_peripheral.settings import WIKI_EXPORT_PATH
from amc_peripheral.wiki.index import WikiIndex
from amc_peripheral.wiki.storage import WikiStorage

log = logging.getLogger(__name__)


class WikiExporter:
    """Exports the wiki DB to a directory of markdown files."""

    # Max number of `wiki_log` entries to include in log.md.
    LOG_MAX_ENTRIES = 500

    def __init__(
        self,
        storage: WikiStorage,
        index: Optional[WikiIndex] = None,
    ):
        self.storage = storage
        self.index = index or WikiIndex(storage)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export_all(self, output_dir: str = WIKI_EXPORT_PATH) -> dict:
        """Export the full wiki to `output_dir` as markdown files.

        Writes to a sibling `.tmp` directory first, then atomically swaps
        it into place. Returns a summary dict.
        """
        output_dir = os.path.abspath(output_dir)
        parent = os.path.dirname(output_dir) or "."
        os.makedirs(parent, exist_ok=True)

        # Use a temp dir as a sibling of the output so os.replace is atomic
        # (same filesystem) and we don't leak a half-written export.
        tmp_dir = tempfile.mkdtemp(
            prefix=os.path.basename(output_dir) + ".",
            suffix=".tmp",
            dir=parent,
        )

        try:
            pages = self.storage.list_pages(limit=100_000)
            for page in pages:
                self._write_page_file(tmp_dir, page)

            self._write_index_file(tmp_dir, pages)
            self._write_log_file(tmp_dir)

            # Atomically swap: remove old, rename new. The small window
            # where output_dir is missing is acceptable for a nightly batch.
            if os.path.isdir(output_dir):
                shutil.rmtree(output_dir)
            elif os.path.exists(output_dir):
                os.remove(output_dir)
            os.rename(tmp_dir, output_dir)
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

        summary = {
            "output_dir": output_dir,
            "pages_exported": len(pages),
            "exported_at": datetime.now().isoformat(),
        }
        log.info(
            f"Wiki exported to {output_dir}: "
            f"{summary['pages_exported']} page(s)"
        )
        self.storage.log_operation(
            operation="export",
            description=f"Exported {summary['pages_exported']} pages to {output_dir}",
            pages_affected=None,
        )
        return summary

    # ------------------------------------------------------------------
    # File writers
    # ------------------------------------------------------------------

    def _write_page_file(self, base_dir: str, page: dict) -> str:
        """Write a single wiki page as markdown. Returns the file path."""
        category = page.get("category") or "misc"
        cat_dir = os.path.join(base_dir, self._sanitize_component(self._category_dir(category)))
        os.makedirs(cat_dir, exist_ok=True)

        filename = self._page_filename(page)
        path = os.path.join(cat_dir, filename)

        body = self._render_page(page)
        # Per-file atomic write
        fd, tmp_path = tempfile.mkstemp(dir=cat_dir, prefix=".tmp.", suffix=".md")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(body)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return path

    def _write_index_file(self, base_dir: str, pages: list[dict]) -> str:
        """Write index.md — TOC of all pages grouped by category."""
        # Use the existing WikiIndex text as a top-level summary, then list
        # every page grouped by category with relative markdown links.
        index_text = self.index.build_index() if pages else ""

        lines: list[str] = []
        lines.append("# Annie's Wiki")
        lines.append("")
        lines.append(f"*Exported: {datetime.now().isoformat(timespec='seconds')}*")
        lines.append(f"*Total pages: {len(pages)}*")
        lines.append("")

        if index_text:
            lines.append("## Summary")
            lines.append("")
            lines.append("```")
            lines.append(index_text)
            lines.append("```")
            lines.append("")

        # Group and render
        by_category: dict[str, list[dict]] = {}
        for p in pages:
            by_category.setdefault(p.get("category") or "misc", []).append(p)

        lines.append("## Pages by Category")
        lines.append("")
        for category in sorted(by_category):
            cat_pages = sorted(by_category[category], key=lambda x: x.get("title", ""))
            cat_dir = self._sanitize_component(self._category_dir(category))
            lines.append(f"### {category} ({len(cat_pages)})")
            lines.append("")
            for p in cat_pages:
                rel = f"{cat_dir}/{self._page_filename(p)}"
                summary = (p.get("summary") or "").strip().replace("\n", " ")
                if summary:
                    lines.append(f"- [{p['title']}]({rel}) — {summary}")
                else:
                    lines.append(f"- [{p['title']}]({rel})")
            lines.append("")

        path = os.path.join(base_dir, "index.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return path

    def _write_log_file(self, base_dir: str) -> str:
        """Write log.md — append-only history of wiki operations.

        Uses Karpathy-style `## [YYYY-MM-DD] operation | description` prefixes
        so each entry can be grep'd with `grep "^## \\[" log.md`.
        """
        entries = self.storage.get_log_entries(limit=self.LOG_MAX_ENTRIES)

        lines: list[str] = []
        lines.append("# Annie's Wiki — Operations Log")
        lines.append("")
        lines.append(
            "*Karpathy-style append-only log. Newest entries first. "
            f"Showing up to the last {self.LOG_MAX_ENTRIES} operations.*"
        )
        lines.append("")
        lines.append(f"*Exported: {datetime.now().isoformat(timespec='seconds')}*")
        lines.append("")

        for entry in entries:
            ts = (entry.get("timestamp") or "")[:10]  # YYYY-MM-DD
            op = entry.get("operation", "unknown")
            desc = (entry.get("description") or "").strip().replace("\n", " ")
            lines.append(f"## [{ts}] {op} | {desc}")
            pages_affected = entry.get("pages_affected")
            if pages_affected:
                lines.append("")
                lines.append(f"Pages affected: {pages_affected}")
            lines.append("")

        path = os.path.join(base_dir, "log.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return path

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    def _render_page(self, page: dict) -> str:
        """Render a wiki page as a markdown document with YAML front matter."""
        page_id = page["id"]
        outbound = self.storage.get_links_from(page_id)
        inbound = self.storage.get_links_to(page_id)

        # Build YAML front matter
        fm_lines = ["---"]
        fm_lines.append(f"title: {self._yaml_string(page.get('title', ''))}")
        fm_lines.append(f"slug: {self._yaml_string(page.get('slug', ''))}")
        fm_lines.append(f"category: {self._yaml_string(page.get('category', ''))}")
        fm_lines.append(f"created_at: {self._yaml_string(page.get('created_at', ''))}")
        fm_lines.append(f"updated_at: {self._yaml_string(page.get('updated_at', ''))}")
        fm_lines.append(f"source_count: {int(page.get('source_count') or 0)}")
        tags = [page.get("category") or "misc"]
        fm_lines.append(f"tags: [{', '.join(self._yaml_string(t) for t in tags)}]")
        if outbound:
            link_titles = [
                self._yaml_string(link.get("to_title", "")) for link in outbound
            ]
            fm_lines.append(f"links_out: [{', '.join(link_titles)}]")
        if inbound:
            link_titles = [
                self._yaml_string(link.get("from_title", "")) for link in inbound
            ]
            fm_lines.append(f"links_in: [{', '.join(link_titles)}]")
        fm_lines.append("---")
        fm_lines.append("")

        # Body
        body_lines: list[str] = []
        body_lines.append(f"# {page.get('title', '(untitled)')}")
        body_lines.append("")

        summary = (page.get("summary") or "").strip()
        if summary:
            body_lines.append("## Summary")
            body_lines.append("")
            body_lines.append(summary)
            body_lines.append("")

        content = (page.get("content") or "").strip()
        if content:
            body_lines.append("## Content")
            body_lines.append("")
            body_lines.append(content)
            body_lines.append("")

        if outbound or inbound:
            body_lines.append("## Links")
            body_lines.append("")
            if outbound:
                body_lines.append("**Outbound:**")
                body_lines.append("")
                for link in outbound:
                    link_path = self._relative_link(page, link, direction="out")
                    body_lines.append(
                        f"- [{link.get('to_title', '')}]({link_path}) "
                        f"— *{link.get('link_type', 'mentions')}*"
                    )
                body_lines.append("")
            if inbound:
                body_lines.append("**Inbound:**")
                body_lines.append("")
                for link in inbound:
                    link_path = self._relative_link(page, link, direction="in")
                    body_lines.append(
                        f"- [{link.get('from_title', '')}]({link_path}) "
                        f"— *{link.get('link_type', 'mentions')}*"
                    )
                body_lines.append("")

        return "\n".join(fm_lines + body_lines)

    def _relative_link(self, page: dict, link_row: dict, direction: str) -> str:
        """Build a relative markdown link path from `page` to the linked page."""
        if direction == "out":
            target_category = link_row.get("to_category") or "misc"
            target_title = link_row.get("to_title") or ""
        else:
            target_category = link_row.get("from_category") or "misc"
            target_title = link_row.get("from_title") or ""

        target_dir = self._sanitize_component(self._category_dir(target_category))
        target_file = self._sanitize_component(
            self._slug_to_filename_stem(target_title)
        ) + ".md"
        # Relative to the page's category directory: go up, then into target
        return f"../{target_dir}/{target_file}"

    def _page_filename(self, page: dict) -> str:
        """Compute filename for a page. Prefers the slug tail; falls back to title."""
        slug = page.get("slug") or ""
        title = page.get("title") or ""
        stem = self._slug_to_filename_stem(slug or title)
        return f"{self._sanitize_component(stem)}.md"

    @staticmethod
    def _slug_to_filename_stem(slug_or_title: str) -> str:
        """Drop `{category}:` prefix if present; return the bare name.

        Accepts either a slug (e.g. `player-freemanlatif`) or a title
        (e.g. `player:freemanlatif`).
        """
        if ":" in slug_or_title:
            return slug_or_title.split(":", 1)[1].strip() or slug_or_title
        # Slugs use hyphens; split on the first hyphen only if it matches a
        # known category prefix to avoid mangling normal titles.
        prefixes = (
            "player-",
            "vehicle-",
            "location-",
            "concept-",
            "event-",
            "relationship-",
            "song-",
            "synthesis-",
            "guide-",
        )
        for p in prefixes:
            if slug_or_title.startswith(p):
                return slug_or_title[len(p):]
        return slug_or_title

    @staticmethod
    def _category_dir(category: str) -> str:
        """Pluralize category for directory name (e.g. player -> players)."""
        category = (category or "").strip().lower()
        if not category:
            return "misc"
        if category.endswith("s"):
            return category
        return f"{category}s"

    @staticmethod
    def _sanitize_component(name: str) -> str:
        """Sanitize a path component: lowercase, drop unsafe chars."""
        name = (name or "").strip().lower()
        # Replace anything that isn't alnum, hyphen, underscore, or dot.
        name = re.sub(r"[^a-z0-9._-]+", "-", name)
        name = re.sub(r"-+", "-", name).strip("-")
        return name or "untitled"

    @staticmethod
    def _yaml_string(value: str) -> str:
        """Quote a string for safe single-line YAML emission."""
        s = "" if value is None else str(value)
        # Double-quoted YAML string with \ and " escaped.
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
