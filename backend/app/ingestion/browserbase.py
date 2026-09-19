"""Browserbase + Stagehand adapter.

Bounded, visible browser collection for when a permitted source has no clean
API. Stagehand does navigate -> observe -> extract structured content. We surface
the Browserbase live-view URL via ``on_event`` so the frontend can show the
browser working during the demo.

This is best-effort and heavily guarded: if the SDK or keys are missing, or
anything throws, it returns no items rather than failing the job. Stagehand's
Python API has shifted across versions, so extraction is wrapped defensively.
"""
from __future__ import annotations

import logging

from app.config import settings
from app.ingestion.base import EventCb, SourceAdapter
from app.models import RawItem, ResearchRequest

log = logging.getLogger("voxmarket.ingest.browserbase")


class BrowserbaseAdapter(SourceAdapter):
    name = "browserbase"

    def available(self) -> bool:
        if not settings.browserbase_enabled:
            return False
        try:
            import stagehand  # noqa: F401
        except Exception:  # noqa: BLE001
            return False
        return True

    async def collect(self, request: ResearchRequest, on_event: EventCb = None) -> list[RawItem]:
        if not self.available():
            raise RuntimeError("browserbase not configured (keys or stagehand missing)")

        from stagehand import Stagehand  # type: ignore

        stagehand = Stagehand(
            env="BROWSERBASE",
            api_key=settings.browserbase_api_key,
            project_id=settings.browserbase_project_id,
            model_name=settings.openai_model,
            model_api_key=settings.openai_api_key or None,
        )
        items: list[RawItem] = []
        try:
            await stagehand.init()
            session_id = getattr(stagehand, "session_id", None)
            if session_id and on_event:
                await on_event(
                    "browser_session",
                    {
                        "session_id": session_id,
                        "live_view_url": f"https://www.browserbase.com/sessions/{session_id}",
                    },
                )

            page = stagehand.page
            target = f"https://www.google.com/search?q={request.subject}+customer+reviews+complaints"
            await page.goto(target)
            if on_event:
                await on_event("browser_nav", {"url": target})

            extracted = await self._extract(page, request.subject)
            for i, row in enumerate(extracted):
                text = (row.get("quote") or row.get("text") or "").strip()
                if len(text) < 30:
                    continue
                items.append(
                    RawItem(
                        source="browserbase",
                        source_id=f"bb_{session_id}_{i}",
                        thread_id=f"bb_{row.get('source_title', 'web')[:40]}",
                        thread_title=row.get("source_title", "Web result"),
                        url=row.get("url", target),
                        author=row.get("author", "web"),
                        text=text,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("browserbase collection failed: %s", exc)
            raise
        finally:
            try:
                await stagehand.close()
            except Exception:  # noqa: BLE001
                pass
        return items

    async def _extract(self, page, subject: str) -> list[dict]:
        """Try a couple of Stagehand extract signatures across SDK versions."""
        instruction = (
            f"Extract individual user opinions/complaints/praise about {subject} visible on this "
            "page. For each, return quote (the opinion text), source_title, url, author if any."
        )
        try:
            result = await page.extract(instruction)
            if isinstance(result, dict) and "items" in result:
                return result["items"]
            if isinstance(result, list):
                return result
            data = getattr(result, "data", None) or getattr(result, "extraction", None)
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "items" in data:
                return data["items"]
        except Exception as exc:  # noqa: BLE001
            log.warning("stagehand extract failed: %s", exc)
        return []
