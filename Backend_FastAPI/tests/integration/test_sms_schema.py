# tests/integration/test_sms_schema.py
"""
Regression test schema SMS Marketing (PR-1) — bảo vệ các invariant DB
(CHECK/FK) khỏi hồi quy ở các lần sửa sau. Codify các runtime probe đã
verify thủ công trong review R1–R3 (consent fail-closed + empty-string,
token triplet, count invariants, FK SET NULL bảo toàn ledger/audit,
click_event bỏ denormalize campaign/contact, three-valued-logic guard).

Tables do autouse fixture `setup_test_database` (root conftest) create_all
trên qlts_test. Mỗi test mở AsyncSessionLocal riêng và rollback → không
để lại dữ liệu.

Heavy/destructive → chạy one-off container (CLAUDE.md):
  docker compose run --rm --no-deps backend \
    python -m pytest tests/integration/test_sms_schema.py -q
"""
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.database import AsyncSessionLocal


@pytest_asyncio.fixture(autouse=True)
async def _schema(setup_test_database):
    """Mọi test phụ thuộc setup_test_database: lần đầu DROP SCHEMA + create_all
    theo model hiện tại (qlts_test), các lần sau truncate."""
    yield


async def _raises(sql: str) -> bool:
    """True nếu INSERT vi phạm INTEGRITY constraint (SQLSTATE 23xxx), rollback sạch.

    CHỈ bắt IntegrityError — KHÔNG bắt DBAPIError chung: syntax/disconnect/lỗi DB
    khác sẽ propagate làm test ĐỎ thay vì false-pass. Assert mã 23xxx (23502
    not-null, 23503 FK, 23505 unique, 23514 check).
    """
    async with AsyncSessionLocal() as s:
        try:
            await s.execute(text(sql))
            await s.rollback()
            return False
        except IntegrityError as e:
            await s.rollback()
            code = getattr(getattr(e, "orig", None), "sqlstate", None)
            assert code and code.startswith("23"), \
                f"không phải integrity violation (23xxx): {code}"
            return True


_C = ("INSERT INTO sms_contact (full_name,phone_normalized,phone_international,"
      "marketing_consent_status")
_E = ("INSERT INTO sms_marketing_consent_event "
      "(phone_normalized_snapshot,event_type,occurred_at")
_B = "INSERT INTO sms_contact_import_batch ("


async def test_contact_granted_requires_nonempty_proof():
    # granted thiếu hẳn proof (all NULL) → reject
    assert await _raises(
        _C + ") VALUES ('X','0911000001','84911000001','granted')")
    # granted proof_ref = '' (empty) → reject (three-valued-logic guard)
    assert await _raises(
        _C + ",marketing_consented_at,marketing_consent_basis,"
        "marketing_consent_proof_ref,consent_disclosure_version) VALUES "
        "('X','0911000002','84911000002','granted',now(),'signed_form','','v1')")
    # granted đủ proof không rỗng → OK
    assert not await _raises(
        _C + ",marketing_consented_at,marketing_consent_basis,"
        "marketing_consent_proof_ref,consent_disclosure_version) VALUES "
        "('X','0911000003','84911000003','granted',now(),'signed_form','ref','v1')")
    # unknown không cần proof → OK
    assert not await _raises(
        _C + ") VALUES ('X','0911000004','84911000004','unknown')")


async def test_consent_event_grant_invariants():
    # grant hợp lệ → OK
    assert not await _raises(
        _E + ",basis,disclosure_version,proof_reference) VALUES "
        "('09','granted',now(),'signed_form','v1','ref')")
    # grant thiếu basis (NULL) → reject
    assert await _raises(
        _E + ",disclosure_version,proof_reference) VALUES "
        "('09','granted',now(),'v1','ref')")
    # grant proof rỗng → reject
    assert await _raises(
        _E + ",basis,disclosure_version,proof_reference) VALUES "
        "('09','granted',now(),'signed_form','v1','')")
    # grant lẫn revoke_source → reject
    assert await _raises(
        _E + ",basis,revoke_source,disclosure_version,proof_reference) VALUES "
        "('09','granted',now(),'signed_form','manual','v1','ref')")


async def test_consent_event_revoke_invariants():
    # revoke hợp lệ (revoke_source ∈ enum, basis NULL) → OK
    assert not await _raises(
        _E + ",revoke_source) VALUES ('09','revoked',now(),'sms_reply')")
    # revoke thiếu revoke_source (NULL) → reject (three-valued-logic guard)
    assert await _raises(_E + ") VALUES ('09','revoked',now())")
    # revoke lẫn basis → reject
    assert await _raises(
        _E + ",basis,revoke_source) VALUES "
        "('09','revoked',now(),'signed_form','manual')")
    # revoke lẫn disclosure_version (grant-data) → reject (R4)
    assert await _raises(
        _E + ",revoke_source,disclosure_version) VALUES "
        "('09','revoked',now(),'sms_reply','grant-v1')")
    # revoke lẫn proof_reference (grant-data) → reject (R4)
    assert await _raises(
        _E + ",revoke_source,proof_reference) VALUES "
        "('09','revoked',now(),'sms_reply','ref')")


async def test_import_batch_count_invariants():
    # all-zero (mặc định) → OK
    assert not await _raises(_B + "row_count) VALUES (0)")
    # row_count=1 nhưng các count khác 0 (vi phạm row=valid+invalid+dup) → reject
    assert await _raises(_B + "row_count,valid_count) VALUES (1,0)")
    # count âm → reject
    assert await _raises(_B + "invalid_count) VALUES (-1)")
    # nhất quán: row=1=valid(1)+0+0; added(1)+existing(0)=valid(1) → OK
    assert not await _raises(
        _B + "row_count,valid_count,added_member_count) VALUES (1,1,1)")


async def test_recipient_token_triplet():
    async with AsyncSessionLocal() as s:
        await s.execute(text(
            "INSERT INTO sms_campaign (name,code,sms_template) "
            "VALUES ('C','c-tok','hi')"))
        cid = (await s.execute(
            text("SELECT id FROM sms_campaign WHERE code='c-tok'"))).scalar()
        base = ("INSERT INTO sms_campaign_recipient (campaign_id,build_revision,"
                "group_ids_snapshot,full_name_snapshot,phone_normalized_snapshot,"
                "phone_international_snapshot,carrier_bucket")
        vals = f"VALUES ({cid},0,'{{1}}','N','0900000001','84900000001','viettel'"
        h64 = "a" * 64  # HMAC-SHA256 hex = đúng 64 ký tự

        async def _bad(tail):
            # savepoint: rollback chỉ insert xấu, giữ campaign cho case sau
            sp = await s.begin_nested()
            raised = False
            try:
                await s.execute(text(base + tail))
            except IntegrityError:
                raised = True
            await sp.rollback()
            assert raised

        # chỉ có hash, thiếu ciphertext/key_version → reject
        await _bad(",token_hash) " + vals + f",'{h64}')")
        # hash sai độ dài (≠ 64) → reject
        await _bad(",token_hash,token_ciphertext,token_key_version) "
                   + vals + ",'h','c','v1')")
        # ciphertext rỗng → reject
        await _bad(",token_hash,token_ciphertext,token_key_version) "
                   + vals + f",'{h64}','','v1')")
        # hash 64 ký tự nhưng KHÔNG hex [0-9a-f] → reject (R5)
        await _bad(",token_hash,token_ciphertext,token_key_version) "
                   + vals + f",'{'z' * 64}','cipher','v1')")
        # đủ bộ ba hợp lệ (hash 64 ký tự hex, ciphertext/keyver non-rỗng) → OK
        await s.execute(text(
            base + ",token_hash,token_ciphertext,token_key_version) "
            + vals + f",'{h64}','cipher','v1')"))
        await s.rollback()


async def test_delete_contact_preserves_consent_ledger():
    """FK SET NULL: xóa contact → ledger sống sót (contact_id=NULL, snapshot còn)."""
    async with AsyncSessionLocal() as s:
        await s.execute(text(
            "INSERT INTO sms_contact (full_name,phone_normalized,"
            "phone_international,marketing_consent_status) VALUES "
            "('X','0922000001','84922000001','unknown')"))
        cid = (await s.execute(text(
            "SELECT id FROM sms_contact WHERE phone_normalized='0922000001'"
        ))).scalar()
        await s.execute(text(
            f"INSERT INTO sms_marketing_consent_event (contact_id,"
            f"phone_normalized_snapshot,event_type,occurred_at,basis,"
            f"disclosure_version,proof_reference) VALUES ({cid},'0922000001',"
            f"'granted',now(),'signed_form','v1','ref')"))
        await s.execute(text(f"DELETE FROM sms_contact WHERE id={cid}"))
        row = (await s.execute(text(
            "SELECT contact_id, phone_normalized_snapshot FROM "
            "sms_marketing_consent_event WHERE phone_normalized_snapshot="
            "'0922000001'"))).first()
        assert row is not None
        assert row[0] is None  # contact_id SET NULL
        assert row[1] == '0922000001'  # bằng chứng còn
        await s.rollback()


async def test_recipient_export_counters_nonneg():
    """build_revision/click-counter non-âm + human_click ≤ raw_click; export non-âm."""
    async with AsyncSessionLocal() as s:
        await s.execute(text(
            "INSERT INTO sms_campaign (name,code,sms_template) "
            "VALUES ('C','c-cnt','hi')"))
        cid = (await s.execute(
            text("SELECT id FROM sms_campaign WHERE code='c-cnt'"))).scalar()

        async def _bad(sql):
            sp = await s.begin_nested()
            raised = False
            try:
                await s.execute(text(sql))
            except IntegrityError:
                raised = True
            await sp.rollback()
            assert raised

        rc = ("campaign_id,build_revision,group_ids_snapshot,full_name_snapshot,"
              "phone_normalized_snapshot,phone_international_snapshot,carrier_bucket")
        rv = f"({cid},0,'{{1}}','N','0900000001','84900000001','viettel'"
        # build_revision âm → reject
        await _bad(f"INSERT INTO sms_campaign_recipient ({rc}) VALUES "
                   f"({cid},-1,'{{1}}','N','0900000001','84900000001','viettel')")
        # raw_click_count âm → reject
        await _bad(f"INSERT INTO sms_campaign_recipient ({rc},raw_click_count) "
                   f"VALUES {rv},-3)")
        # human_click_count > raw_click_count → reject
        await _bad(f"INSERT INTO sms_campaign_recipient "
                   f"({rc},raw_click_count,human_click_count) VALUES {rv},0,7)")
        # hợp lệ (rev=0, raw=5, human=3) → OK
        await s.execute(text(
            f"INSERT INTO sms_campaign_recipient "
            f"({rc},raw_click_count,human_click_count) VALUES {rv},5,3)"))
        # export_batch build_revision âm → reject
        await _bad("INSERT INTO sms_campaign_export_batch "
                   f"(campaign_id,build_revision,carrier_bucket) "
                   f"VALUES ({cid},-1,'viettel')")
        # export_batch file_size_bytes âm → reject
        await _bad("INSERT INTO sms_campaign_export_batch "
                   f"(campaign_id,build_revision,carrier_bucket,file_size_bytes) "
                   f"VALUES ({cid},0,'viettel',-1)")
        await s.rollback()


async def test_click_event_has_no_denormalized_campaign_contact():
    """click_event chỉ giữ recipient_id; campaign/contact derive qua JOIN."""
    async with AsyncSessionLocal() as s:
        cols = (await s.execute(text(
            "SELECT string_agg(column_name, ',') FROM information_schema.columns "
            "WHERE table_name='sms_click_event'"))).scalar()
        assert 'recipient_id' in cols
        assert 'campaign_id' not in cols
        assert 'contact_id' not in cols
