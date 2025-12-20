# create_db.py
import asyncio

from app.database import engine
from app.models import Base  # Import Base từ __init__.py của models


async def create_tables():
    """
    Hàm bất đồng bộ để kết nối đến DB và tạo tất cả các bảng.
    """
    print("Connecting to the database and creating tables...")
    async with engine.begin() as conn:
        # run_sync sẽ chạy hàm create_all của SQLAlchemy trong môi trường bất đồng bộ
        await conn.run_sync(Base.metadata.create_all)
    print("Tables created successfully.")
    # Đóng engine sau khi hoàn tất để script kết thúc
    await engine.dispose()


if __name__ == "__main__":
    # Chạy hàm create_tables
    asyncio.run(create_tables())
