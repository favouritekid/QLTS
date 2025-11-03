# app/models/base.py
from sqlalchemy.orm import declarative_base

# Tạo một lớp Base dùng chung cho tất cả các model
Base = declarative_base()
