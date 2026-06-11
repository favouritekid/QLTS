"""sms marketing seed prefix carrier rules

Revision ID: sms20260611_seed
Revises: sms20260611_create
Create Date: 2026-06-11

Seed idempotent (ON CONFLICT DO NOTHING) bảng sms_prefix_carrier_rule.
⚠ Đầu số chỉ phản ánh MẠNG GỐC (MNP) — chỉ để khớp format file upload nhà
mạng, KHÔNG định tuyến chính xác (xem docstring model + Quyết định #7).
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'sms20260611_seed'
down_revision: Union[str, Sequence[str], None] = 'sms20260611_create'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_PREFIXES = (
    "'032','033','034','035','036','037','038','039','086','096','097','098',"  # Viettel
    "'081','082','083','084','085','088','091','094',"  # VinaPhone
    "'070','076','077','078','079','089','090','093',"  # MobiFone
    "'052','056','058','092',"  # Vietnamobile
    "'059','099'"  # Gmobile (055=Reddi/087=iTel MVNO KHÔNG seed → unknown)
)


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO sms_prefix_carrier_rule (prefix, carrier_code, carrier_name, is_active, created_at, updated_at)
        VALUES
          -- Viettel: 032-039, 086, 096, 097, 098
          ('032','viettel','Viettel',TRUE,NOW(),NOW()),('033','viettel','Viettel',TRUE,NOW(),NOW()),
          ('034','viettel','Viettel',TRUE,NOW(),NOW()),('035','viettel','Viettel',TRUE,NOW(),NOW()),
          ('036','viettel','Viettel',TRUE,NOW(),NOW()),('037','viettel','Viettel',TRUE,NOW(),NOW()),
          ('038','viettel','Viettel',TRUE,NOW(),NOW()),('039','viettel','Viettel',TRUE,NOW(),NOW()),
          ('086','viettel','Viettel',TRUE,NOW(),NOW()),('096','viettel','Viettel',TRUE,NOW(),NOW()),
          ('097','viettel','Viettel',TRUE,NOW(),NOW()),('098','viettel','Viettel',TRUE,NOW(),NOW()),
          -- VinaPhone: 081-085, 088, 091, 094
          ('081','vinaphone','VinaPhone',TRUE,NOW(),NOW()),('082','vinaphone','VinaPhone',TRUE,NOW(),NOW()),
          ('083','vinaphone','VinaPhone',TRUE,NOW(),NOW()),('084','vinaphone','VinaPhone',TRUE,NOW(),NOW()),
          ('085','vinaphone','VinaPhone',TRUE,NOW(),NOW()),('088','vinaphone','VinaPhone',TRUE,NOW(),NOW()),
          ('091','vinaphone','VinaPhone',TRUE,NOW(),NOW()),('094','vinaphone','VinaPhone',TRUE,NOW(),NOW()),
          -- MobiFone: 070, 076, 077, 078, 079, 089, 090, 093
          ('070','mobifone','MobiFone',TRUE,NOW(),NOW()),('076','mobifone','MobiFone',TRUE,NOW(),NOW()),
          ('077','mobifone','MobiFone',TRUE,NOW(),NOW()),('078','mobifone','MobiFone',TRUE,NOW(),NOW()),
          ('079','mobifone','MobiFone',TRUE,NOW(),NOW()),('089','mobifone','MobiFone',TRUE,NOW(),NOW()),
          ('090','mobifone','MobiFone',TRUE,NOW(),NOW()),('093','mobifone','MobiFone',TRUE,NOW(),NOW()),
          -- Vietnamobile: 052, 056, 058, 092
          ('052','vietnamobile','Vietnamobile',TRUE,NOW(),NOW()),('056','vietnamobile','Vietnamobile',TRUE,NOW(),NOW()),
          ('058','vietnamobile','Vietnamobile',TRUE,NOW(),NOW()),('092','vietnamobile','Vietnamobile',TRUE,NOW(),NOW()),
          -- Gmobile: 059, 099. (055=Reddi/Wintel, 087=iTel = MVNO → KHÔNG gộp Gmobile;
          -- để unmatched → bucket 'unknown' xử lý thủ công theo format portal đã duyệt)
          ('059','gmobile','Gmobile',TRUE,NOW(),NOW()),('099','gmobile','Gmobile',TRUE,NOW(),NOW())
        ON CONFLICT (prefix) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        f"DELETE FROM sms_prefix_carrier_rule WHERE prefix IN ({_PREFIXES});"
    )
