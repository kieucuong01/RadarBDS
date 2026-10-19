import json
import re

import pytest

from services.public_marketing import PUBLIC_CONTACT, build_public_entities


def test_organization_contact_matches_visible_footer_identity():
    entity = build_public_entities('https://radarbds.vn')['organization']
    assert entity['telephone'] == '+84343216024'
    assert entity['email'] == 'radarbds@gmail.com'
    assert entity['sameAs'] == [PUBLIC_CONTACT['youtube'], PUBLIC_CONTACT['facebook']]
    assert entity['address']['streetAddress'] == '57/19 ĐX126, Phường Phú An'
    assert entity['address']['addressLocality'] == 'TP HCM'
    assert entity['address']['addressCountry'] == 'VN'


@pytest.mark.parametrize('path', ['/', '/tin-tuc', '/dinh-gia-bds', '/bang-gia-dat-tphcm',
                                  '/bao-cao', '/ban-do-thu-dau-mot'])
def test_contact_footer_is_present_once_and_schema_stays_valid(path):
    import app as radar_app
    response = radar_app.app.test_client().get(path)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert html.count('class="seo-footer public-site-footer"') == 1
    for value in ['tel:+84343216024', 'mailto:radarbds@gmail.com', PUBLIC_CONTACT['address'],
                  PUBLIC_CONTACT['facebook'], PUBLIC_CONTACT['youtube'], 'public_footer.css']:
        assert value in html
    nodes = []
    for raw in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        payload = json.loads(raw)
        nodes.extend(payload.get('@graph', [payload]))
    organizations = [node for node in nodes if node.get('@id') == 'https://radarbds.vn/#organization']
    assert len(organizations) == 1
    assert organizations[0]['email'] == PUBLIC_CONTACT['email']
