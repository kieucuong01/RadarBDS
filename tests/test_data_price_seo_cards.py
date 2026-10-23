"""Price-page cards must be sales even when the shared guest feed mixes transactions."""
import os
from urllib.parse import urlsplit
import uuid


def test_price_cards_recheck_sale_type_in_current_rows_without_exposing_private_fields(monkeypatch):
    from db.connection import get_conn
    from services import data_price_seo, market_data
    assert 'test' in urlsplit(os.environ['DATABASE_URL']).path.lower()
    prefix='https://price-card-sale-'+uuid.uuid4().hex+'.test/'
    rows=[]
    try:
        with get_conn() as conn:
            for index,tx in enumerate(('ban','thue',None)):
                cursor=conn.execute("""INSERT INTO listings
                    (source,url,ward,property_type,tx_type,area_m2,price_ty,price_per_m2,is_active)
                    VALUES ('facebook',?,'Phú Lợi','dat_nen',?,100,2,20,1)""",(prefix+str(index),tx))
                rows.append(dict(id=cursor.lastrowid,source='facebook',ward='Phú Lợi',area_m2=100,price_ty=2))
        # This is the real feed's compact projection: it has no tx_type member.
        monkeypatch.setattr(market_data,'load_signals',lambda *args,**kwargs:dict(signals=rows))
        cards=data_price_seo.load_public_cards('phu-loi')
        assert [card['id'] for card in cards]==[rows[0]['id']]
        assert set(cards[0])=={'id','ward','area_m2','price_ty'}
    finally:
        with get_conn() as conn:
            conn.execute('DELETE FROM listings WHERE url LIKE ?',(prefix+'%',))
