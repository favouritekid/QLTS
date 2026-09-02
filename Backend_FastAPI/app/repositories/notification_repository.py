# app/repositories/notification_repository.py
from typing import List, Optional, Tuple
from sqlalchemy import and_, cast, desc, func, insert, select, String, type_coerce
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from .base import BaseRepository

class NotificationRepository(BaseRepository[models.Notification]):
    """
    Repository for Notification model.
    ✅ PATTERN A COMPLIANT
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, models.Notification)

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        user_id: Optional[int] = None,
        unread_only: bool = False,
        **kwargs
    ) -> Tuple[int, List[models.Notification]]:
        """
        Get paginated notifications with filtering.
        """
        filters = []
        if user_id is not None:
            filters.append(self.model.user_id == user_id)
        if unread_only:
            filters.append(self.model.is_read == False)

        where_clause = and_(*filters) if filters else None
        
        # Count total
        total = await self.count(where_clause)
        
        # Get records
        query = select(self.model).offset(skip).limit(limit).order_by(desc(self.model.created_at))
        if where_clause is not None:
            query = query.where(where_clause)
            
        result = await self.db.execute(query)
        return total, list(result.scalars().all())

    async def get_unread_count(self, user_id: int) -> int:
        """Count unread notifications for a user."""
        return await self.count(
            and_(
                self.model.user_id == user_id,
                self.model.is_read == False
            )
        )

    async def get_total_count(self, user_id: int) -> int:
        """Count total notifications for a user."""
        return await self.count(self.model.user_id == user_id)

    async def get_by_ids(
        self,
        notification_ids: List[int],
        *,
        owner_user_id: Optional[int],
    ) -> List[models.Notification]:
        """Lấy notification theo danh sách ID, có ràng buộc CHỦ QUYỀN.

        ``owner_user_id`` KHÔNG có giá trị mặc định — đây là chủ ý. Trước
        2026-09-02 hàm này chỉ lọc theo ``id``, và đường hydrate inbox
        (``notification_service.get_user_notifications``, nhánh cache HIT)
        lấy danh sách ID từ Redis rồi gọi thẳng vào đây. Nghĩa là Redis
        trở thành nguồn chứng minh chủ quyền: một ID lọt vào
        ``user_inbox:{u1}`` là u1 đọc được hàng của u2, dù endpoint đã
        truyền đúng ``current_user.id`` (OWASP A01). Nhánh cache MISS ngay
        bên dưới thì lại lọc đúng qua ``get_filtered(user_id=...)`` — tức
        lỗ hổng chỉ nằm ở nhánh HIT.

        Bắt buộc nêu tên tham số làm cho một caller mới KHÔNG THỂ quên nó:
        quên là ``TypeError`` lúc gọi, không phải một lỗ hổng im lặng.
        Truyền ``owner_user_id=None`` một cách TƯỜNG MINH khi và chỉ khi
        các ID vừa do chính tiến trình ấy tạo ra trong cùng giao dịch.
        """
        if not notification_ids:
            return []

        dieu_kien = [self.model.id.in_(notification_ids)]
        if owner_user_id is not None:
            dieu_kien.append(self.model.user_id == owner_user_id)

        query = select(self.model).where(and_(*dieu_kien))
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_dedupe_key(self, user_ids: List[int], dedupe_key: str) -> List[int]:
        """
        Find user IDs who already have a notification with the given dedupe_key.
        Uses PostgreSQL JSONB operator ->> for key extraction.
        """
        query = select(self.model.user_id).where(
            and_(
                self.model.user_id.in_(user_ids),
                # PostgreSQL JSONB operator: data->>'dedupe_key' = value
                # type_coerce needed because column is JSON (not JSONB), but
                # PostgreSQL stores both identically; JSONB enables .astext
                type_coerce(self.model.data, JSONB)["dedupe_key"].astext == dedupe_key
            )
        )
        result = await self.db.execute(query)
        return [row[0] for row in result.fetchall()]

    async def bulk_create(self, values: List[dict]) -> List[Tuple[int, int]]:
        """Chèn hàng loạt notification, trả về TỪNG CẶP ``(user_id, id)``.

        Dữ liệu TỰ MÔ TẢ, không phải một danh sách ID trần. Trước
        2026-09-02 hàm này chỉ ``RETURNING id`` và tầng gọi ghép lại bằng
        ``dict(zip(user_ids, ids))`` — tức dựa vào giả định rằng thứ tự
        RETURNING của một lệnh ``INSERT ... VALUES (…),(…)`` trùng thứ tự
        đầu vào. **Giả định đó không có bảo đảm hình thức.** Nếu CSDL trả
        ``[n2, n1]`` cho đầu vào ``[u1, u2]`` thì:

          · ``notification_delivery`` của u1 trỏ vào notification của u2;
          · ``user_inbox:{u1}`` nạp ID không thuộc u1;
          · u1 mất thông báo của chính mình, và sổ delivery sai quan hệ.

        Hàng rào chủ quyền ở đường ĐỌC (``get_by_ids(owner_user_id=…)``)
        chặn được việc đọc chéo, nhưng KHÔNG sửa được dữ liệu đã ghi sai.
        Nên quan hệ chủ quyền phải dựng từ chính dữ liệu CSDL trả về.

        Cố ý KHÔNG dùng ``sort_by_parameter_order``: chưa chứng minh được
        nó áp dụng cho đúng dạng ``insert().values(list)`` đang dùng ở
        đây, và ``RETURNING`` thêm một cột thì đúng bất kể thứ tự.
        """
        if not values:
            return []

        # KHÔNG mở savepoint ở đây. Hàm này được gọi MỘT LẦN MỖI CHUNK
        # (``BULK_INSERT_CHUNK_SIZE = 100``), nên savepoint cấp-chunk cho
        # một bảo đảm SAI: chunk 1 release thành công rồi chunk 2 hỏng thì
        # hàng của chunk 1 vẫn nằm trong giao dịch ngoài và được commit —
        # đúng những hàng ``notification`` mồ côi mà bản vá muốn chặn.
        #
        # Ranh giới đúng là CẤP SỰ KIỆN, bao trọn cả vòng lặp chunk, và nó
        # nằm ở ``notification_dispatcher.dispatch`` — tầng duy nhất biết
        # ranh giới của một sự kiện. Đặt thêm một savepoint ở đây chỉ tạo
        # một lớp không phép kiểm nào canh được.
        result = await self.db.execute(
            insert(self.model)
            .values(values)
            .returning(self.model.user_id, self.model.id)
        )
        return [(row[0], row[1]) for row in result.fetchall()]

    async def get_unread_for_user(self, user_id: int, notification_ids: Optional[List[int]] = None) -> List[models.Notification]:
        """
        Get unread notifications for a specific user.
        Optionally restricted to a list of IDs.

        W7-C.1 fix 2026-05-16: use `is not None` check thay vì truthy.
        `notification_ids=[]` (empty list) is falsy in Python → trước đây
        bypass ID filter → trả ALL unread của user → mark-as-read endpoint
        marked TẤT CẢ inbox unread khi client gửi empty array. Sau fix,
        empty list → ID filter `IN ()` → trả 0 rows (no-op as expected).
        """
        filters = [
            self.model.user_id == user_id,
            self.model.is_read == False
        ]
        if notification_ids is not None:
            filters.append(self.model.id.in_(notification_ids))

        query = select(self.model).where(and_(*filters))
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_for_user_by_id(self, user_id: int, notification_id: int) -> Optional[models.Notification]:
        """Get a specific notification if it belongs to the user."""
        query = select(self.model).where(
            and_(
                self.model.id == notification_id,
                self.model.user_id == user_id
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def bulk_delete_for_user(self, user_id: int, notification_ids: List[int]) -> int:
        """
        Delete multiple notifications for a user.
        Returns count of deleted notifications.
        """
        from sqlalchemy import delete
        
        if not notification_ids:
            return 0
            
        stmt = delete(self.model).where(
            and_(
                self.model.id.in_(notification_ids),
                self.model.user_id == user_id
            )
        )
        result = await self.db.execute(stmt)
        return result.rowcount
