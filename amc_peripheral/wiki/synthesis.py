"""Weekly synthesis generation for Annie's wiki.

Each week, Annie writes a `synthesis:community-week-YYYY-Www` page that
narrates the past week of wiki activity. The narrative is produced by a
single lightweight LLM call (no agentic loop, no tools) following the
same pattern as `_ingest_to_wiki`.

Input: recent `wiki_log` entries + most-updated pages.
Output: a new/updated synthesis page cross-linked to the pages it cites.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from amc_peripheral.wiki.retrieval import WikiRetrieval
from amc_peripheral.wiki.storage import WikiStorage

log = logging.getLogger(__name__)


# Keep the prompt focused and bounded — we don't want to spend thousands
# of tokens compiling the raw sources.
MAX_LOG_ENTRIES_IN_PROMPT = 80
MAX_TOP_PAGES_IN_PROMPT = 10
MAX_CONTENT_SNIPPET_CHARS = 400
DEFAULT_MAX_OUTPUT_CHARS = 8_000


class WikiSynthesizer:
    """Generates weekly community-synthesis wiki pages using an LLM."""

    SYSTEM_PROMPT = (
        "You are DJ Annie, writing a weekly 'State of the Community' synthesis "
        "for your personal wiki. You will be given the wiki's recent operations "
        "log and the top pages that were updated this week. Produce a narrative "
        "synthesis page in markdown describing what happened in the community, "
        "who stood out, which topics or vehicles came up often, and any emerging "
        "trends or running jokes. Be observational and concise. Do NOT invent "
        "facts not supported by the inputs. Cite relevant page titles inline "
        "(e.g. 'see player:freemanlatif') so they can be cross-linked. Keep the "
        "output under 800 words."
    )

    def __init__(
        self,
        storage: WikiStorage,
        retrieval: WikiRetrieval,
        llm_client,
        model: str,
    ):
        """Create a synthesizer.

        Args:
            storage: Wiki storage layer.
            retrieval: Wiki ChromaDB retrieval (used to index the new page).
            llm_client: An `openai.AsyncOpenAI`-compatible client.
            model: Model name to use for the synthesis LLM call.
        """
        self.storage = storage
        self.retrieval = retrieval
        self.llm_client = llm_client
        self.model = model

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_weekly_synthesis(
        self,
        now: Optional[datetime] = None,
    ) -> Optional[dict]:
        """Build and persist a weekly synthesis page.

        Returns the affected page dict, or `None` if nothing notable happened
        this week (and no synthesis was produced).
        """
        now = now or datetime.now()

        log_entries = self._recent_ingest_log(now, days=7)
        top_pages = self._top_updated_pages(now, days=7, limit=MAX_TOP_PAGES_IN_PROMPT)

        if not log_entries and not top_pages:
            log.info("Weekly synthesis skipped: no recent activity")
            return None

        prompt_user = self._build_user_prompt(now, log_entries, top_pages)

        try:
            # pyrefly: ignore [no-matching-overload]
            completion = await self.llm_client.chat.completions.create(
                model=self.model,
                reasoning_effort="low",
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt_user},
                ],
            )
        except Exception as e:
            log.warning(f"Weekly synthesis LLM call failed: {e}")
            return None

        if not completion.choices:
            log.warning("Weekly synthesis LLM returned no choices")
            return None

        body = (completion.choices[0].message.content or "").strip()
        if not body:
            log.info("Weekly synthesis LLM returned empty body; skipping")
            return None

        if len(body) > DEFAULT_MAX_OUTPUT_CHARS:
            body = body[:DEFAULT_MAX_OUTPUT_CHARS] + "\n\n[truncated]"

        page = self._upsert_synthesis_page(now, body, top_pages)
        return page

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _align_tz(t: datetime, reference: datetime) -> datetime:
        """Align `t`'s tz-awareness to match `reference`.

        DB timestamps are written with `datetime.now().isoformat()` — always
        naive. `now` may be passed in as tz-aware (the scheduled task uses
        `datetime.now(ZoneInfo("Asia/Bangkok"))`). Mixing the two in a `<`
        comparison raises TypeError, so we normalize `t` to match `reference`.
        """
        if reference.tzinfo is not None and t.tzinfo is None:
            return t.replace(tzinfo=reference.tzinfo)
        if reference.tzinfo is None and t.tzinfo is not None:
            return t.replace(tzinfo=None)
        return t

    def _recent_ingest_log(self, now: datetime, days: int) -> list[dict]:
        """Pull recent ingest log entries within the past `days`."""
        cutoff = now - timedelta(days=days)
        entries = self.storage.get_log_entries(
            operation="ingest", limit=MAX_LOG_ENTRIES_IN_PROMPT * 2
        )
        recent: list[dict] = []
        for e in entries:
            ts = e.get("timestamp") or ""
            if not ts:
                continue
            try:
                t = datetime.fromisoformat(ts)
            except ValueError:
                continue
            t = self._align_tz(t, cutoff)
            if t < cutoff:
                continue
            if not e.get("pages_affected"):
                continue
            recent.append(e)
            if len(recent) >= MAX_LOG_ENTRIES_IN_PROMPT:
                break
        return recent

    def _top_updated_pages(self, now: datetime, days: int, limit: int) -> list[dict]:
        """List the most-recently-updated pages within the past `days`."""
        cutoff = now - timedelta(days=days)
        pages = self.storage.list_pages(limit=limit * 4)
        recent: list[dict] = []
        for p in pages:
            ts = p.get("updated_at") or ""
            if not ts:
                continue
            try:
                t = datetime.fromisoformat(ts)
            except ValueError:
                continue
            t = self._align_tz(t, cutoff)
            # Skip prior synthesis pages so we don't recursively reference them
            if (p.get("category") or "") == "synthesis":
                continue
            if t < cutoff:
                continue
            recent.append(p)
            if len(recent) >= limit:
                break
        return recent

    def _build_user_prompt(
        self,
        now: datetime,
        log_entries: list[dict],
        top_pages: list[dict],
    ) -> str:
        lines: list[str] = []
        iso_year, iso_week, _ = now.isocalendar()
        lines.append(
            f"Week: {iso_year}-W{iso_week:02d} "
            f"(generated {now.isoformat(timespec='seconds')})"
        )
        lines.append("")

        if top_pages:
            lines.append("## Most-updated pages this week")
            for p in top_pages:
                summary = (p.get("summary") or "").strip().replace("\n", " ")
                snippet = (p.get("content") or "").strip().replace("\n", " ")
                if len(snippet) > MAX_CONTENT_SNIPPET_CHARS:
                    snippet = snippet[:MAX_CONTENT_SNIPPET_CHARS] + "..."
                lines.append(
                    f"- {p.get('title', '(untitled)')} "
                    f"[{p.get('category', '?')}] "
                    f"(updated {p.get('updated_at', '?')})"
                )
                if summary:
                    lines.append(f"    summary: {summary}")
                if snippet:
                    lines.append(f"    content: {snippet}")
            lines.append("")

        if log_entries:
            lines.append("## Recent wiki operations")
            for e in log_entries:
                ts = (e.get("timestamp") or "")[:16]
                desc = (e.get("description") or "").strip().replace("\n", " ")
                lines.append(f"- [{ts}] {desc}")
            lines.append("")

        lines.append(
            "Produce the synthesis page body now. Keep it observational, "
            "specific, and tightly grounded in the inputs above."
        )
        return "\n".join(lines)

    def _upsert_synthesis_page(
        self,
        now: datetime,
        body: str,
        cited_pages: list[dict],
    ) -> dict:
        iso_year, iso_week, _ = now.isocalendar()
        week_tag = f"{iso_year}-W{iso_week:02d}"
        title = f"synthesis:community-week-{week_tag}"
        summary = f"Annie's synthesis for week {week_tag}."

        slug = self.storage._make_slug(title)
        existing = self.storage.get_page_by_slug(slug)

        if existing:
            page_id = existing["id"]
            self.storage.update_page(page_id, content=body, summary=summary)
        else:
            page_id = self.storage.create_page(
                title=title,
                category="synthesis",
                content=body,
                summary=summary,
            )

        self.storage.add_source(
            page_id,
            "synthesis",
            f"weekly_{week_tag}",
        )

        refreshed = self.storage.get_page_by_id(page_id)
        if refreshed:
            try:
                self.retrieval.index_page(
                    page_id=page_id,
                    title=refreshed["title"],
                    content=refreshed["content"],
                    category=refreshed["category"],
                    updated_at=refreshed["updated_at"],
                )
            except Exception as e:
                log.warning(f"Synthesis ChromaDB indexing failed: {e}")

        # Cross-link cited pages (skip self)
        cited_ids: list[int] = []
        for p in cited_pages:
            if p.get("id") and p["id"] != page_id:
                try:
                    self.storage.add_link(page_id, p["id"], "cites")
                    cited_ids.append(p["id"])
                except Exception as e:
                    log.warning(
                        f"Synthesis link {page_id}->{p.get('id')} failed: {e}"
                    )

        affected = [page_id] + cited_ids
        self.storage.log_operation(
            operation="synthesis",
            description=f"Weekly synthesis for {week_tag}",
            pages_affected=affected,
        )
        log.info(
            f"Weekly synthesis page written: {title} "
            f"(cited {len(cited_ids)} pages)"
        )
        return refreshed or {
            "id": page_id,
            "title": title,
            "category": "synthesis",
            "content": body,
            "summary": summary,
        }
