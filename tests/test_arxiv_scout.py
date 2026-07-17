import httpx
import respx

from dissonance.scouts.arxiv import ArxivScout

SAMPLE_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2501.01234v2</id>
    <published>2025-01-02T18:00:00Z</published>
    <updated>2025-01-05T09:00:00Z</updated>
    <title>Few-shot Prompting Improves Accuracy on GSM8K</title>
    <summary>  We show that few-shot   prompting improves accuracy.  </summary>
    <author><name>Jane Doe</name></author>
    <author><name>John Smith</name></author>
    <arxiv:primary_category term="cs.CL"/>
    <category term="cs.CL"/>
    <category term="cs.LG"/>
    <link href="http://arxiv.org/abs/2501.01234v2" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/2501.01234v2" rel="related" type="application/pdf"/>
  </entry>
</feed>
"""


@respx.mock
def test_search_parses_entries_into_papers():
    respx.get("https://export.arxiv.org/api/query").mock(
        return_value=httpx.Response(200, text=SAMPLE_ATOM)
    )

    scout = ArxivScout()
    papers = scout.search("GSM8K", max_results=10)
    scout.close()

    assert len(papers) == 1
    p = papers[0]
    assert p.paper_id == "arxiv:2501.01234"
    assert p.arxiv_id == "2501.01234"
    assert p.title == "Few-shot Prompting Improves Accuracy on GSM8K"
    assert p.abstract == "We show that few-shot prompting improves accuracy."
    assert p.authors == ["Jane Doe", "John Smith"]
    assert p.primary_category == "cs.CL"
    assert "cs.LG" in p.categories
    assert p.pdf_url == "http://arxiv.org/pdf/2501.01234v2"
    assert p.html_url == "https://arxiv.org/html/2501.01234"
    assert p.source == "arxiv"
    assert p.full_text_status == "unknown"
    assert p.published_at.year == 2025


def test_parse_feed_strips_versioned_arxiv_id():
    papers = ArxivScout._parse_feed(SAMPLE_ATOM)
    assert papers[0].arxiv_id == "2501.01234"
