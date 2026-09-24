from datetime import date

import pytest
import requests

from powerdesk.config import Feed, OfficialPage
from powerdesk.display import filter_official, is_recent
from powerdesk.official import classify_official, fetch_official, find_date, is_noise, parse_listing
from tests.test_news import RSS, FakeResponse, FakeSession

TODAY = date(2026, 9, 24)

# Shaped like cea.nic.in/whats-new: Sl. No. | Title | Date | Download
CEA_HTML = b"""<html><body><nav><ul><li><a href="/about">Profiles of Chairperson and Members</a></li></ul></nav>
<table><tr><th>Sl. No.</th><th>Title</th><th>Date</th><th>Download</th></tr>
<tr><td>1</td><td>Monthly Installed Capacity Report as on 30.06.2026</td><td>2026-07-15</td>
    <td><a href="https://cea.nic.in/wp-content/uploads/installed/2026/06/Website_June.pdf">file</a> <a href="#">#</a></td></tr>
<tr><td>2</td><td>Draft CEA (Technical Standards for Connectivity to the Grid) Regulations, 2026- Invitation of Public Comments</td>
    <td>2026-08-04</td><td><a href="/wp-content/uploads/notification/2026/08/Draft Grid.pdf">file</a></td></tr>
<tr><td>3</td><td>Notice for Filling up One (01) Vacancy of Despatch Rider on a Deputation Basis</td><td>2026-06-25</td>
    <td><a href="/x.pdf">file</a></td></tr>
<tr><td>4</td><td>Notice &amp; Agenda for 18th NPC Meeting to be held on 18.09.2026 at Rajgir</td><td>2026-09-10</td>
    <td><a href="javascript:void(0)">x</a></td></tr>
<tr><td>5</td><td>All India Electricity Statistics General Review 2025</td><td>2026-01-06</td><td></td></tr>
<tr><td>6</td><td>Report on Roadmap to 100 GW of Hydro Pumped Storage Projects</td><td>2019-01-28</td>
    <td><a href="/old.pdf">file</a></td></tr>
</table></body></html>"""

# Shaped like mnre.gov.in current notices: Title | Description | Start | End | File
MNRE_HTML = b"""<table><tr><td>Updated (05.06.2025) List-I under ALMM order for Solar PV Modules (1.3 mb PDF)</td>
<td>Updated List-I under ALMM order</td><td>18/08/2026</td><td>18/09/2026</td><td><a href="/files/almm.pdf">View (1 MB)</a></td></tr>
<tr><td>Public Notice : Tender for allocation of seabed for Offshore Wind Energy Projects</td><td>desc</td>
<td>12/07/2026</td><td>12/09/2026</td><td><a href="/files/seabed.pdf">View</a></td></tr></table>"""

LIST_HTML = b"""<ul><li><a href="/menu">Some long navigation menu entry</a></li>
<li>Guidelines for BESS fire safety audit, 12 Sep 2026 <a href="/bess.pdf">PDF</a></li></ul>"""


def titles(items):
    return [a.title for a in items]


def test_cea_table():
    items = parse_listing(CEA_HTML, "https://cea.nic.in/whats-new/?lang=en", "CEA")
    t = titles(items)
    assert "Monthly Installed Capacity Report as on 30.06.2026" in t
    cap = items[t.index("Monthly Installed Capacity Report as on 30.06.2026")]
    assert cap.published == date(2026, 7, 15)          # date column wins over the date inside the title
    assert cap.kind == "report" and cap.link.endswith("Website_June.pdf")
    draft = next(a for a in items if a.title.startswith("Draft CEA"))
    assert draft.kind == "regulation"
    assert draft.link == "https://cea.nic.in/wp-content/uploads/notification/2026/08/Draft%20Grid.pdf"  # relative + space
    assert not any("Vacancy" in x for x in t)          # admin noise hidden
    assert not any("NPC Meeting" in x for x in t)      # only a javascript: link, so dropped
    assert not any("General Review" in x for x in t)   # no link at all
    assert not any("Profiles of Chairperson" in x for x in t)  # nav menu ignored when a table exists


def test_mnre_table():
    items = parse_listing(MNRE_HTML, "https://mnre.gov.in/en/past-notices/current-notices/", "MNRE")
    almm, seabed = items
    assert almm.title == "Updated (05.06.2025) List-I under ALMM order for Solar PV Modules"   # size suffix removed
    assert almm.published == date(2026, 8, 18) and almm.kind == "regulation"   # an ALMM order
    assert almm.link == "https://mnre.gov.in/files/almm.pdf"
    assert seabed.kind == "tender"


def test_list_fallback_needs_dates():
    items = parse_listing(LIST_HTML, "https://x.gov.in/", "X")
    assert titles(items) == ["Guidelines for BESS fire safety audit, 12 Sep 2026 PDF"]
    assert items[0].published == date(2026, 9, 12)


@pytest.mark.parametrize("content", [b"", b"<<<>>>", b"\xff\xfe\x00garbage", b"<html><body>No notices</body></html>"])
def test_garbage_pages(content):
    assert parse_listing(content, "https://x.gov.in/", "X") == []


@pytest.mark.parametrize("text,expected", [
    ("2026-07-15", date(2026, 7, 15)),
    ("as on 30.06.2026", date(2026, 6, 30)),
    ("18/08/2026 to 18/09/2026", date(2026, 8, 18)),
    ("held on 12th September 2026", date(2026, 9, 12)),
    ("Sep 21, 2026", date(2026, 9, 21)),
    ("31/02/2026", None),               # impossible date
    ("99-99-9999", None),
    ("version 1.2.3", None),
    (None, None),
])
def test_find_date(text, expected):
    assert find_date(text) == expected


def test_classify_and_noise():
    assert classify_official("Invitation for RFP on GeM portal") == "tender"
    assert classify_official("Minutes of the 20th Meeting of NCT") == "meeting"
    assert classify_official("Advisory on use of Ester Oil in Transformers") == "scheme"
    assert classify_official("Chairperson addresses") == "other"
    assert is_noise("Notice of Result for Canteen Attendant")
    assert not is_noise("Draft Cyber Security Regulations")


def test_fetch_official_isolation_and_filters():
    routes = {
        "https://cea.nic.in/whats-new/": FakeResponse(CEA_HTML),
        "mnre": requests.exceptions.SSLError("bad certificate"),
        "empty": FakeResponse(b"<html>redesigned</html>"),
        "pib": FakeResponse(RSS),
    }
    pages = [OfficialPage("CEA", "https://cea.nic.in/whats-new/"), OfficialPage("MNRE", "mnre"), OfficialPage("New", "empty")]
    items, errors = fetch_official(pages, [Feed("PIB: Ministry of Power", "pib")], session=FakeSession(routes), today=TODAY)
    assert any("MNRE" in e and "SSLError" in e for e in errors)
    assert any("New" in e and "layout" in e for e in errors)
    bodies = {a.body for a in items}
    assert bodies == {"CEA", "PIB: Ministry of Power"}
    assert not any(a.published and a.published.year == 2019 for a in items)  # older than max age
    dated = [a.published for a in items if a.published]
    assert dated == sorted(dated, reverse=True)
    assert filter_official(items, bodies=["CEA"], kinds=["report"])[0].title.startswith("Monthly Installed")
    assert filter_official(items, query="grid")[0].kind == "regulation"


def test_fetch_official_nothing_configured():
    assert fetch_official([], [], today=TODAY) == ([], [])


def test_is_recent():
    assert is_recent(date(2026, 9, 20), today=TODAY)
    assert not is_recent(date(2026, 9, 1), today=TODAY)
    assert not is_recent(None, today=TODAY)
    assert not is_recent(date(2026, 9, 30), today=TODAY)   # future-dated
