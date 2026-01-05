"""
Seed script for config_subject_group table.
Complete list of Vietnamese admission subject groups.

Run with WSL:
wsl bash -c "cd /mnt/d/QLTS/Backend_FastAPI && source venv/bin/activate && python -m scripts.seeds.seed_subject_groups"
"""
import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Import settings to get DB URL
try:
    from app.core.config import settings
    DB_URL = settings.DATABASE_URL
except:
    print("⚠️  Could not import settings. Using default DB URL.")
    DB_URL = "postgresql+asyncpg://postgres:admin@192.168.88.125:5432/qlts_dev"



# Complete list of Vietnamese subject groups for admission
SUBJECT_GROUPS = [
    # AH - Toán + Tiếng Hàn combinations
    {"code": "AH1", "name": "Toán, Địa lí, Tiếng Hàn"},
    {"code": "AH2", "name": "Toán, Hóa học, Tiếng Hàn"},
    {"code": "AH3", "name": "Toán, Vật lí, Tiếng Hàn"},
    {"code": "AH4", "name": "Toán, Sinh học, Tiếng Hàn"},
    {"code": "AH5", "name": "Toán, Lịch sử, Tiếng Hàn"},
    {"code": "AH6", "name": "Toán, Giáo dục công dân, Tiếng Hàn"},
    {"code": "AH7", "name": "Toán, Khoa học tự nhiên, Tiếng Hàn"},
    {"code": "AH8", "name": "Toán, Khoa học xã hội, Tiếng Hàn"},
    
    # A - Natural Sciences
    {"code": "A00", "name": "Toán, Vật lí, Hóa học"},
    {"code": "A01", "name": "Toán, Vật lí, Tiếng Anh"},
    {"code": "A02", "name": "Toán, Vật lí, Sinh học"},
    {"code": "A03", "name": "Toán, Vật lí, Lịch sử"},
    {"code": "A04", "name": "Toán, Vật lí, Địa lí"},
    {"code": "A05", "name": "Toán, Hóa học, Lịch sử"},
    {"code": "A06", "name": "Toán, Hóa học, Địa lí"},
    {"code": "A07", "name": "Toán, Lịch sử, Địa lí"},
    {"code": "A08", "name": "Toán, Lịch sử, Giáo dục công dân"},
    {"code": "A09", "name": "Toán, Địa lí, Giáo dục công dân"},
    {"code": "A10", "name": "Toán, Vật lí, Giáo dục công dân"},
    {"code": "A11", "name": "Toán, Hoá học, Giáo dục công dân"},
    {"code": "A12", "name": "Toán, Khoa học tự nhiên, Khoa học xã hội"},
    {"code": "A13", "name": "Toán, Khoa học tự nhiên, Lịch sử"},
    {"code": "A14", "name": "Toán, Khoa học tự nhiên, Địa lí"},
    {"code": "A15", "name": "Toán, Khoa học tự nhiên, Giáo dục công dân"},
    {"code": "A16", "name": "Toán, Khoa học tự nhiên, Ngữ văn"},
    {"code": "A17", "name": "Toán, Vật lý, Khoa học xã hội"},
    {"code": "A18", "name": "Toán, Hoá học, Khoa học xã hội"},
    
    # B - Biology focused
    {"code": "B00", "name": "Toán, Hóa học, Sinh học"},
    {"code": "B01", "name": "Toán, Sinh học, Lịch sử"},
    {"code": "B02", "name": "Toán, Sinh học, Địa lí"},
    {"code": "B03", "name": "Toán, Sinh học, Ngữ văn"},
    {"code": "B04", "name": "Toán, Sinh học, Giáo dục công dân"},
    {"code": "B05", "name": "Toán, Sinh học, Khoa học xã hội"},
    {"code": "B08", "name": "Toán, Sinh học, Tiếng Anh"},
    
    # C - Social Sciences / Literature focused
    {"code": "C00", "name": "Ngữ văn, Lịch sử, Địa lí"},
    {"code": "C01", "name": "Ngữ văn, Toán, Vật lí"},
    {"code": "C02", "name": "Ngữ văn, Toán, Hóa học"},
    {"code": "C03", "name": "Ngữ văn, Toán, Lịch sử"},
    {"code": "C04", "name": "Ngữ văn, Toán, Địa lí"},
    {"code": "C05", "name": "Ngữ văn, Vật lí, Hóa học"},
    {"code": "C06", "name": "Ngữ văn, Vật lí, Sinh học"},
    {"code": "C07", "name": "Ngữ văn, Vật lí, Lịch sử"},
    {"code": "C08", "name": "Ngữ văn, Hóa học, Sinh học"},
    {"code": "C09", "name": "Ngữ văn, Vật lí, Địa lí"},
    {"code": "C10", "name": "Ngữ văn, Hóa học, Lịch sử"},
    {"code": "C11", "name": "Ngữ văn, Hóa học, Địa lí"},
    {"code": "C12", "name": "Ngữ văn, Sinh học, Lịch sử"},
    {"code": "C13", "name": "Ngữ văn, Sinh học, Địa lí"},
    {"code": "C14", "name": "Ngữ văn, Toán, Giáo dục công dân"},
    {"code": "C15", "name": "Ngữ văn, Toán, Khoa học xã hội"},
    {"code": "C16", "name": "Ngữ văn, Vật lí, Giáo dục công dân"},
    {"code": "C17", "name": "Ngữ văn, Hóa học, Giáo dục công dân"},
    {"code": "C18", "name": "Ngữ văn, Sinh học, Giáo dục công dân"},
    {"code": "C19", "name": "Ngữ văn, Lịch sử, Giáo dục công dân"},
    {"code": "C20", "name": "Ngữ văn, Địa lí, Giáo dục công dân"},
    {"code": "C21", "name": "Ngữ văn, Khoa học tự nhiên, Khoa học xã hội"},
    {"code": "C22", "name": "Ngữ văn, Địa lí, Khoa học tự nhiên"},
    {"code": "C23", "name": "Ngữ văn, Giáo dục công dân, Khoa học tự nhiên"},
    {"code": "C24", "name": "Ngữ văn, Khoa học xã hội, Vật lí"},
    {"code": "C25", "name": "Ngữ văn, Khoa học xã hội, Hoá học"},
    {"code": "C26", "name": "Ngữ văn, Khoa học xã hội, Sinh học"},
    
    # DD - Special combinations
    {"code": "DD0", "name": "Toán, Khoa học xã hội, Tiếng Nhật"},
    {"code": "DD1", "name": "Toán, Khoa học xã hội, Tiếng Trung"},
    {"code": "DD2", "name": "Ngữ văn, Toán, Tiếng Hàn"},
    
    # DH - Ngữ văn + Tiếng Hàn combinations
    {"code": "DH1", "name": "Ngữ văn, Địa lí, Tiếng Hàn"},
    {"code": "DH2", "name": "Ngữ văn, Hóa học, Tiếng Hàn"},
    {"code": "DH3", "name": "Ngữ văn, Vật lí, Tiếng Hàn"},
    {"code": "DH4", "name": "Ngữ văn, Sinh học, Tiếng Hàn"},
    {"code": "DH5", "name": "Ngữ văn, Lịch sử, Tiếng Hàn"},
    {"code": "DH6", "name": "Ngữ văn, Giáo dục công dân, Tiếng Hàn"},
    {"code": "DH7", "name": "Ngữ văn, Khoa học tự nhiên, Tiếng Hàn"},
    {"code": "DH8", "name": "Ngữ văn, Khoa học xã hội, Tiếng Hàn"},
    
    # D - Foreign language combinations
    {"code": "D01", "name": "Ngữ văn, Toán, Tiếng Anh"},
    {"code": "D02", "name": "Ngữ văn, Toán, Tiếng Nga"},
    {"code": "D03", "name": "Ngữ văn, Toán, Tiếng Pháp"},
    {"code": "D04", "name": "Ngữ văn, Toán, Tiếng Trung"},
    {"code": "D05", "name": "Ngữ văn, Toán, Tiếng Đức"},
    {"code": "D06", "name": "Ngữ văn, Toán, Tiếng Nhật"},
    {"code": "D07", "name": "Toán, Hóa học, Tiếng Anh"},
    {"code": "D08", "name": "Toán, Sinh học, Tiếng Anh"},
    {"code": "D09", "name": "Toán, Lịch sử, Tiếng Anh"},
    {"code": "D10", "name": "Toán, Địa lí, Tiếng Anh"},
    {"code": "D11", "name": "Ngữ văn, Vật lí, Tiếng Anh"},
    {"code": "D12", "name": "Ngữ văn, Hóa học, Tiếng Anh"},
    {"code": "D13", "name": "Ngữ văn, Sinh học, Tiếng Anh"},
    {"code": "D14", "name": "Ngữ văn, Lịch sử, Tiếng Anh"},
    {"code": "D15", "name": "Ngữ văn, Địa lí, Tiếng Anh"},
    {"code": "D16", "name": "Toán, Địa lí, Tiếng Đức"},
    {"code": "D17", "name": "Toán, Địa lí, Tiếng Nga"},
    {"code": "D18", "name": "Toán, Địa lí, Tiếng Nhật"},
    {"code": "D19", "name": "Toán, Địa lí, Tiếng Pháp"},
    {"code": "D20", "name": "Toán, Địa lí, Tiếng Trung"},
    {"code": "D21", "name": "Toán, Hóa học, Tiếng Đức"},
    {"code": "D22", "name": "Toán, Hóa học, Tiếng Nga"},
    {"code": "D23", "name": "Toán, Hóa học, Tiếng Nhật"},
    {"code": "D24", "name": "Toán, Hóa học, Tiếng Pháp"},
    {"code": "D25", "name": "Toán, Hóa học, Tiếng Trung"},
    {"code": "D26", "name": "Toán, Vật lí, Tiếng Đức"},
    {"code": "D27", "name": "Toán, Vật lí, Tiếng Nga"},
    {"code": "D28", "name": "Toán, Vật lí, Tiếng Nhật"},
    {"code": "D29", "name": "Toán, Vật lí, Tiếng Pháp"},
    {"code": "D30", "name": "Toán, Vật lí, Tiếng Trung"},
    {"code": "D31", "name": "Toán, Sinh học, Tiếng Đức"},
    {"code": "D32", "name": "Toán, Sinh học, Tiếng Nga"},
    {"code": "D33", "name": "Toán, Sinh học, Tiếng Nhật"},
    {"code": "D34", "name": "Toán, Sinh học, Tiếng Pháp"},
    {"code": "D35", "name": "Toán, Sinh học, Tiếng Trung"},
    {"code": "D36", "name": "Toán, Lịch sử, Tiếng Đức"},
    {"code": "D37", "name": "Toán, Lịch sử, Tiếng Nga"},
    {"code": "D38", "name": "Toán, Lịch sử, Tiếng Nhật"},
    {"code": "D39", "name": "Toán, Lịch sử, Tiếng Pháp"},
    {"code": "D40", "name": "Toán, Lịch sử, Tiếng Trung"},
    {"code": "D41", "name": "Ngữ văn, Địa lí, Tiếng Đức"},
    {"code": "D42", "name": "Ngữ văn, Địa lí, Tiếng Nga"},
    {"code": "D43", "name": "Ngữ văn, Địa lí, Tiếng Nhật"},
    {"code": "D44", "name": "Ngữ văn, Địa lí, Tiếng Pháp"},
    {"code": "D45", "name": "Ngữ văn, Địa lí, Tiếng Trung"},
    {"code": "D46", "name": "Ngữ văn, Hóa học, Tiếng Đức"},
    {"code": "D47", "name": "Ngữ văn, Hóa học, Tiếng Nga"},
    {"code": "D48", "name": "Ngữ văn, Hóa học, Tiếng Nhật"},
    {"code": "D49", "name": "Ngữ văn, Hóa học, Tiếng Pháp"},
    {"code": "D50", "name": "Ngữ văn, Hóa học, Tiếng Trung"},
    {"code": "D51", "name": "Ngữ văn, Vật lí, Tiếng Đức"},
    {"code": "D52", "name": "Ngữ văn, Vật lí, Tiếng Nga"},
    {"code": "D53", "name": "Ngữ văn, Vật lí, Tiếng Nhật"},
    {"code": "D54", "name": "Ngữ văn, Vật lí, Tiếng Pháp"},
    {"code": "D55", "name": "Ngữ văn, Vật lí, Tiếng Trung"},
    {"code": "D56", "name": "Ngữ văn, Sinh học, Tiếng Đức"},
    {"code": "D57", "name": "Ngữ văn, Sinh học, Tiếng Nga"},
    {"code": "D58", "name": "Ngữ văn, Sinh học, Tiếng Nhật"},
    {"code": "D59", "name": "Ngữ văn, Sinh học, Tiếng Pháp"},
    {"code": "D60", "name": "Ngữ văn, Sinh học, Tiếng Trung"},
    {"code": "D61", "name": "Ngữ văn, Lịch sử, Tiếng Đức"},
    {"code": "D62", "name": "Ngữ văn, Lịch sử, Tiếng Nga"},
    {"code": "D63", "name": "Ngữ văn, Lịch sử, Tiếng Nhật"},
    {"code": "D64", "name": "Ngữ văn, Lịch sử, Tiếng Pháp"},
    {"code": "D65", "name": "Ngữ văn, Lịch sử, Tiếng Trung"},
    {"code": "D66", "name": "Ngữ văn, Giáo dục công dân, Tiếng Anh"},
    {"code": "D67", "name": "Ngữ văn, Giáo dục công dân, Tiếng Đức"},
    {"code": "D68", "name": "Ngữ văn, Giáo dục công dân, Tiếng Nga"},
    {"code": "D69", "name": "Ngữ văn, Giáo dục công dân, Tiếng Nhật"},
    {"code": "D70", "name": "Ngữ văn, Giáo dục công dân, Tiếng Pháp"},
    {"code": "D71", "name": "Ngữ văn, Giáo dục công dân, Tiếng Trung"},
    {"code": "D72", "name": "Ngữ văn, Khoa học tự nhiên, Tiếng Anh"},
    {"code": "D73", "name": "Ngữ văn, Khoa học tự nhiên, Tiếng Đức"},
    {"code": "D74", "name": "Ngữ văn, Khoa học tự nhiên, Tiếng Nga"},
    {"code": "D75", "name": "Ngữ văn, Khoa học tự nhiên, Tiếng Nhật"},
    {"code": "D76", "name": "Ngữ văn, Khoa học tự nhiên, Tiếng Pháp"},
    {"code": "D77", "name": "Ngữ văn, Khoa học tự nhiên, Tiếng Trung"},
    {"code": "D78", "name": "Ngữ văn, Khoa học xã hội, Tiếng Anh"},
    {"code": "D79", "name": "Ngữ văn, Khoa học xã hội, Tiếng Đức"},
    {"code": "D80", "name": "Ngữ văn, Khoa học xã hội, Tiếng Nga"},
    {"code": "D81", "name": "Ngữ văn, Khoa học xã hội, Tiếng Nhật"},
    {"code": "D82", "name": "Ngữ văn, Khoa học xã hội, Tiếng Pháp"},
    {"code": "D83", "name": "Ngữ văn, Khoa học xã hội, Tiếng Trung"},
    {"code": "D84", "name": "Toán, Giáo dục công dân, Tiếng Anh"},
    {"code": "D85", "name": "Toán, Giáo dục công dân, Tiếng Đức"},
    {"code": "D86", "name": "Toán, Giáo dục công dân, Tiếng Nga"},
    {"code": "D87", "name": "Toán, Giáo dục công dân, Tiếng Pháp"},
    {"code": "D88", "name": "Toán, Giáo dục công dân, Tiếng Nhật"},
    {"code": "D89", "name": "Toán, Giáo dục công dân, Tiếng Trung"},
    {"code": "D90", "name": "Toán, Khoa học tự nhiên, Tiếng Anh"},
    {"code": "D91", "name": "Toán, Khoa học tự nhiên, Tiếng Pháp"},
    {"code": "D92", "name": "Toán, Khoa học tự nhiên, Tiếng Đức"},
    {"code": "D93", "name": "Toán, Khoa học tự nhiên, Tiếng Nga"},
    {"code": "D94", "name": "Toán, Khoa học tự nhiên, Tiếng Nhật"},
    {"code": "D95", "name": "Toán, Khoa học tự nhiên, Tiếng Trung"},
    {"code": "D96", "name": "Toán, Khoa học xã hội, Tiếng Anh"},
    {"code": "D97", "name": "Toán, Khoa học xã hội, Tiếng Pháp"},
    {"code": "D98", "name": "Toán, Khoa học xã hội, Tiếng Đức"},
    {"code": "D99", "name": "Toán, Khoa học xã hội, Tiếng Nga"},
    
    # X - Special subjects combinations
    {"code": "X01", "name": "Toán, Ngữ văn, Giáo dục Kinh tế và pháp luật"},
    {"code": "X02", "name": "Toán, Ngữ văn, Tin học"},
    {"code": "X03", "name": "Toán, Ngữ văn, Công nghệ công nghiệp"},
    {"code": "X04", "name": "Toán, Ngữ văn, Công nghệ nông nghiệp"},
    {"code": "X05", "name": "Toán, Vật lí, Giáo dục Kinh tế và pháp luật"},
    {"code": "X06", "name": "Toán, Vật lí, Tin học"},
    {"code": "X07", "name": "Toán, Vật lí, Công nghệ công nghiệp"},
    {"code": "X08", "name": "Toán, Vật lí, Công nghệ nông nghiệp"},
    {"code": "X09", "name": "Toán, Hóa học, Giáo dục Kinh tế và pháp luật"},
    {"code": "X10", "name": "Toán, Hóa học, Tin học"},
    {"code": "X11", "name": "Toán, Hóa học, Công nghệ công nghiệp"},
    {"code": "X12", "name": "Toán, Hóa học, Công nghệ nông nghiệp"},
    {"code": "X13", "name": "Toán, Sinh học, Giáo dục Kinh tế và pháp luật"},
    {"code": "X14", "name": "Toán, Sinh học, Tin học"},
    {"code": "X15", "name": "Toán, Sinh học, Công nghệ công nghiệp"},
    {"code": "X16", "name": "Toán, Sinh học, Công nghệ nông nghiệp"},
    {"code": "X17", "name": "Toán, Lịch sử, Giáo dục Kinh tế và pháp luật"},
    {"code": "X18", "name": "Toán, Lịch sử, Tin học"},
    {"code": "X19", "name": "Toán, Lịch sử, Công nghệ công nghiệp"},
    {"code": "X20", "name": "Toán, Lịch sử, Công nghệ nông nghiệp"},
    {"code": "X21", "name": "Toán, Địa lí, Giáo dục Kinh tế và pháp luật"},
    {"code": "X22", "name": "Toán, Địa lí, Tin học"},
    {"code": "X23", "name": "Toán, Địa lí, Công nghệ công nghiệp"},
    {"code": "X24", "name": "Toán, Địa lí, Công nghệ nông nghiệp"},
    {"code": "X25", "name": "Toán, Giáo dục Kinh tế và pháp luật, Tiếng Anh"},
    {"code": "X26", "name": "Toán, Tin học, Tiếng Anh"},
    {"code": "X27", "name": "Toán, Công nghệ công nghiệp, Tiếng Anh"},
    {"code": "X28", "name": "Toán, Công nghệ nông nghiệp, Tiếng Anh"},
    {"code": "X29", "name": "Toán, Giáo dục Kinh tế và pháp luật, Tiếng Nga"},
    {"code": "X30", "name": "Toán, Tin học, Tiếng Nga"},
    {"code": "X31", "name": "Toán, Công nghệ công nghiệp, Tiếng Nga"},
    {"code": "X32", "name": "Toán, Công nghệ nông nghiệp, Tiếng Nga"},
    {"code": "X33", "name": "Toán, Giáo dục Kinh tế và pháp luật, Tiếng Pháp"},
    {"code": "X34", "name": "Toán, Tin học, Tiếng Pháp"},
    {"code": "X35", "name": "Toán, Công nghệ công nghiệp, Tiếng Pháp"},
    {"code": "X36", "name": "Toán, Công nghệ nông nghiệp, Tiếng Pháp"},
    {"code": "X37", "name": "Toán, Giáo dục Kinh tế và pháp luật, Tiếng Trung"},
    {"code": "X38", "name": "Toán, Tin học, Tiếng Trung"},
    {"code": "X39", "name": "Toán, Công nghệ công nghiệp, Tiếng Trung"},
    {"code": "X40", "name": "Toán, Công nghệ nông nghiệp, Tiếng Trung"},
    {"code": "X41", "name": "Toán, Giáo dục Kinh tế và pháp luật, Tiếng Đức"},
    {"code": "X42", "name": "Toán, Tin học, Tiếng Đức"},
    {"code": "X43", "name": "Toán, Công nghệ công nghiệp, Tiếng Đức"},
    {"code": "X44", "name": "Toán, Công nghệ nông nghiệp, Tiếng Đức"},
    {"code": "X45", "name": "Toán, Giáo dục Kinh tế và pháp luật, Tiếng Nhật"},
    {"code": "X46", "name": "Toán, Tin học, Tiếng Nhật"},
    {"code": "X47", "name": "Toán, Công nghệ công nghiệp, Tiếng Nhật"},
    {"code": "X48", "name": "Toán, Công nghệ nông nghiệp, Tiếng Nhật"},
    {"code": "X49", "name": "Toán, Giáo dục Kinh tế và pháp luật, Tiếng Hàn"},
    {"code": "X50", "name": "Toán, Tin học, Tiếng Hàn"},
    {"code": "X51", "name": "Toán, Công nghệ công nghiệp, Tiếng Hàn"},
    {"code": "X52", "name": "Toán, Công nghệ nông nghiệp, Tiếng Hàn"},
    {"code": "X53", "name": "Toán, Giáo dục Kinh tế và pháp luật, Tin học"},
    {"code": "X54", "name": "Toán, Giáo dục Kinh tế và pháp luật, Công nghệ công nghiệp"},
    {"code": "X55", "name": "Toán, Giáo dục Kinh tế và pháp luật, Công nghệ nông nghiệp"},
    {"code": "X56", "name": "Toán, Tin học, Công nghệ công nghiệp"},
    {"code": "X57", "name": "Toán, Tin học, Công nghệ nông nghiệp"},
    {"code": "X58", "name": "Ngữ văn, Vật lí, Giáo dục Kinh tế và pháp luật"},
    {"code": "X59", "name": "Ngữ văn, Vật lí, Tin học"},
    {"code": "X60", "name": "Ngữ văn, Vật lí, Công nghệ công nghiệp"},
    {"code": "X61", "name": "Ngữ văn, Vật lí, Công nghệ nông nghiệp"},
    {"code": "X62", "name": "Ngữ văn, Hóa học, Giáo dục Kinh tế và pháp luật"},
    {"code": "X63", "name": "Ngữ văn, Hóa học, Tin học"},
    {"code": "X64", "name": "Ngữ văn, Hóa học, Công nghệ công nghiệp"},
    {"code": "X65", "name": "Ngữ văn, Hóa học, Công nghệ nông nghiệp"},
    {"code": "X66", "name": "Ngữ văn, Sinh học, Giáo dục Kinh tế và pháp luật"},
    {"code": "X67", "name": "Ngữ văn, Sinh học, Tin học"},
    {"code": "X68", "name": "Ngữ văn, Sinh học, Công nghệ công nghiệp"},
    {"code": "X69", "name": "Ngữ văn, Sinh học, Công nghệ nông nghiệp"},
    {"code": "X70", "name": "Ngữ văn, Lịch sử, Giáo dục Kinh tế và pháp luật"},
    {"code": "X71", "name": "Ngữ văn, Lịch sử, Tin học"},
    {"code": "X72", "name": "Ngữ văn, Lịch sử, Công nghệ công nghiệp"},
    {"code": "X73", "name": "Ngữ văn, Lịch sử, Công nghệ nông nghiệp"},
    {"code": "X74", "name": "Ngữ văn, Địa lí, Giáo dục Kinh tế và pháp luật"},
    {"code": "X75", "name": "Ngữ văn, Địa lí, Tin học"},
    {"code": "X76", "name": "Ngữ văn, Địa lí, Công nghệ công nghiệp"},
    {"code": "X77", "name": "Ngữ văn, Địa lí, Công nghệ nông nghiệp"},
    {"code": "X78", "name": "Ngữ văn, Giáo dục Kinh tế và pháp luật, Tiếng Anh"},
    {"code": "X79", "name": "Ngữ văn, Tin học, Tiếng Anh"},
    {"code": "X80", "name": "Ngữ văn, Công nghệ công nghiệp, Tiếng Anh"},
    {"code": "X81", "name": "Ngữ văn, Công nghệ nông nghiệp, Tiếng Anh"},
    {"code": "X82", "name": "Ngữ văn, Giáo dục Kinh tế và pháp luật, Tiếng Nga"},
    {"code": "X83", "name": "Ngữ văn, Tin học, Tiếng Nga"},
    {"code": "X84", "name": "Ngữ văn, Công nghệ công nghiệp, Tiếng Nga"},
    {"code": "X85", "name": "Ngữ văn, Công nghệ nông nghiệp, Tiếng Nga"},
    {"code": "X86", "name": "Ngữ văn, Giáo dục Kinh tế và pháp luật, Tiếng Pháp"},
    {"code": "X87", "name": "Ngữ văn, Tin học, Tiếng Pháp"},
    {"code": "X88", "name": "Ngữ văn, Công nghệ công nghiệp, Tiếng Pháp"},
    {"code": "X89", "name": "Ngữ văn, Công nghệ nông nghiệp, Tiếng Pháp"},
    {"code": "X90", "name": "Ngữ văn, Giáo dục Kinh tế và pháp luật, Tiếng Trung"},
    {"code": "X91", "name": "Ngữ văn, Tin học, Tiếng Trung"},
    {"code": "X92", "name": "Ngữ văn, Công nghệ công nghiệp, Tiếng Trung"},
    {"code": "X93", "name": "Ngữ văn, Công nghệ nông nghiệp, Tiếng Trung"},
    {"code": "X94", "name": "Ngữ văn, Giáo dục Kinh tế và pháp luật, Tiếng Đức"},
    {"code": "X95", "name": "Ngữ văn, Tin học, Tiếng Đức"},
    {"code": "X96", "name": "Ngữ văn, Công nghệ công nghiệp, Tiếng Đức"},
    {"code": "X97", "name": "Ngữ văn, Công nghệ nông nghiệp, Tiếng Đức"},
    {"code": "X98", "name": "Ngữ văn, Giáo dục Kinh tế và pháp luật, Tiếng Nhật"},
    {"code": "X99", "name": "Ngữ văn, Tin học, Tiếng Nhật"},
    
    # Y - Extended combinations
    {"code": "Y01", "name": "Ngữ văn, Công nghệ công nghiệp, Tiếng Nhật"},
    {"code": "Y02", "name": "Ngữ văn, Công nghệ nông nghiệp, Tiếng Nhật"},
    {"code": "Y03", "name": "Ngữ văn, Giáo dục Kinh tế và pháp luật, Tiếng Hàn"},
    {"code": "Y04", "name": "Ngữ văn, Tin học, Tiếng Hàn"},
    {"code": "Y05", "name": "Ngữ văn, Công nghệ công nghiệp, Tiếng Hàn"},
    {"code": "Y06", "name": "Ngữ văn, Công nghệ nông nghiệp, Tiếng Hàn"},
    {"code": "Y07", "name": "Ngữ văn, Giáo dục Kinh tế và pháp luật, Tin học"},
    {"code": "Y08", "name": "Ngữ văn, Giáo dục Kinh tế và pháp luật, Công nghệ công nghiệp"},
    {"code": "Y09", "name": "Ngữ văn, Giáo dục Kinh tế và pháp luật, Công nghệ nông nghiệp"},
    {"code": "Y10", "name": "Ngữ văn, Tin học, Công nghệ công nghiệp"},
    {"code": "Y11", "name": "Ngữ văn, Tin học, Công nghệ nông nghiệp"},
]


async def seed_subject_groups():
    """Seed subject groups into database."""
    engine = create_async_engine(DB_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    try:
        async with async_session() as session:
            # Check existing records
            result = await session.execute(
                text("SELECT COUNT(*) FROM config_subject_group")
            )
            count = result.scalar()
            
            if count > 0:
                print(f"⚠️  config_subject_group already has {count} records. Skipping seed.")
                print("   To reseed, run: DELETE FROM config_subject_group;")
                return
            
            # Insert subject groups
            for i, group in enumerate(SUBJECT_GROUPS, 1):
                await session.execute(
                    text("""
                        INSERT INTO config_subject_group (code, name, subjects, display_order, is_active)
                        VALUES (:code, :name, '[]'::jsonb, :display_order, true)
                    """),
                    {
                        "code": group["code"],
                        "name": group["name"],
                        "display_order": i,
                    }
                )
            
            await session.commit()
            print(f"✅ Seeded {len(SUBJECT_GROUPS)} subject groups successfully!")
            
            # Show sample
            result = await session.execute(
                text("SELECT code, name FROM config_subject_group ORDER BY display_order LIMIT 10")
            )
            rows = result.fetchall()
            print("\n📋 Sample Subject Groups:")
            for row in rows:
                print(f"   {row[0]}: {row[1]}")
            print(f"   ... and {len(SUBJECT_GROUPS) - 10} more")
    
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_subject_groups())

