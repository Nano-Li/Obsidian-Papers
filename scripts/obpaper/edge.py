"""Main-PDF primitives copied from AutoPaper edge_download.py."""
from .publisher import publisher_for

async def fetch_main_pdf(engine, ctx, paper, dest):
    """Use only the upstream main-PDF primitives; never enter its PDF+SI loop."""
    page = await ctx.new_page()
    doi, publisher = paper['doi'], publisher_for(paper)
    try:
        if publisher == 'elsevier':
            return await engine.try_elsevier_pdf(page, ctx, doi, dest)
        if publisher == 'wiley':
            return await engine.try_click_pdf(page, ctx, doi, publisher, dest, stage='main_pdf')
        url = engine.direct_pdf_url(doi, publisher)
        if url:
            attempt = await engine.try_direct_pdf(page, ctx, url, dest,
                                                  stage='main_pdf', allow_navigation=True)
            if attempt['state'] != engine.STATUS_FAILED:
                return attempt
        return await engine.try_click_pdf(page, ctx, doi, publisher, dest, stage='main_pdf')
    finally:
        # Each paper owns its pages, including popup viewers.
        for tab in list(ctx.pages):
            try:
                await tab.close()
            except Exception:
                pass
        engine.RUN_CTX['manual_pages'] = []
