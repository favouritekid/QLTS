# scripts/seeds/seed_full_subject_groups.py
"""
Migrate 231 Subject Groups from config_subject_group (JSON) to subject_group (Relational).

This script:
1. Adds missing subjects to the Subject table
2. Seeds all 231 official Vietnamese subject groups
3. Creates proper SubjectGroupSubject mappings

Usage:
    python -m scripts.seeds.seed_full_subject_groups
"""

import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.admission_config import Subject, SubjectGroup, SubjectGroupSubject


# =============================================================================
# SUBJECT NAME TO CODE MAPPING (Vietnamese -> Code)
# =============================================================================
SUBJECT_NAME_TO_CODE = {
    # Core subjects
    "Toán": "math",
    "Ngữ văn": "literature",
    "Vật lí": "physics",
    "Vật lý": "physics",
    "Hóa học": "chemistry",
    "Hoá học": "chemistry",
    "Sinh học": "biology",
    "Lịch sử": "history",
    "Địa lí": "geography",
    "Địa lý": "geography",
    "Giáo dục công dân": "civic_education",
    
    # Foreign languages
    "Tiếng Anh": "english",
    "Tiếng Pháp": "french",
    "Tiếng Đức": "german",
    "Tiếng Nga": "russian",
    "Tiếng Trung": "chinese",
    "Tiếng Nhật": "japanese",
    "Tiếng Hàn": "korean",
    
    # Combined subjects (new in 2025 curriculum)
    "Khoa học tự nhiên": "natural_science",
    "Khoa học xã hội": "social_science",
    
    # Technology subjects
    "Tin học": "informatics",
    "Công nghệ": "technology",
    "Công nghệ công nghiệp": "industrial_tech",
    "Công nghệ nông nghiệp": "agricultural_tech",
    "Giáo dục Kinh tế và pháp luật": "economics_law",
}


# =============================================================================
# SUBJECTS DATA (Extended with new subjects)
# =============================================================================
SUBJECTS = [
    # Core subjects
    {"code": "math", "name_vi": "Toán", "display_order": 1},
    {"code": "literature", "name_vi": "Ngữ văn", "display_order": 2},
    {"code": "english", "name_vi": "Tiếng Anh", "display_order": 3},
    {"code": "physics", "name_vi": "Vật lý", "display_order": 4},
    {"code": "chemistry", "name_vi": "Hóa học", "display_order": 5},
    {"code": "biology", "name_vi": "Sinh học", "display_order": 6},
    {"code": "history", "name_vi": "Lịch sử", "display_order": 7},
    {"code": "geography", "name_vi": "Địa lý", "display_order": 8},
    {"code": "civic_education", "name_vi": "Giáo dục công dân", "display_order": 9},
    
    # Foreign languages
    {"code": "french", "name_vi": "Tiếng Pháp", "display_order": 10},
    {"code": "german", "name_vi": "Tiếng Đức", "display_order": 11},
    {"code": "russian", "name_vi": "Tiếng Nga", "display_order": 12},
    {"code": "chinese", "name_vi": "Tiếng Trung", "display_order": 13},
    {"code": "japanese", "name_vi": "Tiếng Nhật", "display_order": 14},
    {"code": "korean", "name_vi": "Tiếng Hàn", "display_order": 15},
    
    # Arts
    {"code": "art", "name_vi": "Mỹ thuật", "display_order": 16},
    {"code": "music", "name_vi": "Âm nhạc", "display_order": 17},
    
    # Technology & Others
    {"code": "informatics", "name_vi": "Tin học", "display_order": 18},
    {"code": "technology", "name_vi": "Công nghệ", "display_order": 19},
    {"code": "physical_education", "name_vi": "Thể dục", "display_order": 20},
    
    # NEW: Combined subjects (2025 curriculum)
    {"code": "natural_science", "name_vi": "Khoa học tự nhiên", "display_order": 21},
    {"code": "social_science", "name_vi": "Khoa học xã hội", "display_order": 22},
    
    # NEW: Specialized technology subjects
    {"code": "industrial_tech", "name_vi": "Công nghệ công nghiệp", "display_order": 23},
    {"code": "agricultural_tech", "name_vi": "Công nghệ nông nghiệp", "display_order": 24},
    {"code": "economics_law", "name_vi": "Giáo dục Kinh tế và pháp luật", "display_order": 25},
]


# =============================================================================
# 231 SUBJECT GROUPS (From seed_subject_groups.py)
# =============================================================================
SUBJECT_GROUPS_RAW = [
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
    
    # D - Foreign language combinations (D01-D99)
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
    
    # X - Special subjects combinations (X01-X99)
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


def parse_subject_names(name: str) -> list[str]:
    """Parse Vietnamese subject names to codes.
    
    Example: "Toán, Vật lí, Hóa học" -> ["math", "physics", "chemistry"]
    """
    subject_names = [s.strip() for s in name.split(",")]
    codes = []
    
    for subject_name in subject_names:
        code = SUBJECT_NAME_TO_CODE.get(subject_name)
        if code:
            codes.append(code)
        else:
            print(f"  ⚠️ Unknown subject: '{subject_name}'")
    
    return codes


async def seed_subjects(db: AsyncSession) -> dict[str, int]:
    """Seed Subject table and return code->id mapping."""
    print("📚 Seeding Subjects...")
    
    code_to_id = {}
    
    for subject_data in SUBJECTS:
        result = await db.execute(
            select(Subject).where(Subject.code == subject_data["code"])
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            code_to_id[existing.code] = existing.id
            print(f"  - {subject_data['code']}: exists (id={existing.id})")
        else:
            subject = Subject(**subject_data, is_active=True)
            db.add(subject)
            await db.flush()
            code_to_id[subject.code] = subject.id
            print(f"  ✅ {subject_data['code']}: created (id={subject.id})")
    
    await db.commit()
    print(f"  Total: {len(code_to_id)} subjects")
    return code_to_id


async def seed_subject_groups(db: AsyncSession, subject_code_to_id: dict[str, int]) -> dict[str, int]:
    """Seed SubjectGroup and SubjectGroupSubject tables with all 231 groups."""
    print("\n📐 Seeding 231 Subject Groups...")
    
    group_code_to_id = {}
    created = 0
    skipped = 0
    
    for idx, group_data in enumerate(SUBJECT_GROUPS_RAW):
        code = group_data["code"]
        name = group_data["name"]
        
        # Parse subject names to codes
        subject_codes = parse_subject_names(name)
        
        if not subject_codes:
            print(f"  ⚠️ {code}: No valid subjects found in '{name}'")
            continue
        
        # Check if group exists
        result = await db.execute(
            select(SubjectGroup).where(SubjectGroup.code == code)
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            group_code_to_id[code] = existing.id
            skipped += 1
            continue
        
        # Create group
        group = SubjectGroup(
            code=code,
            name=name,
            display_order=idx + 1,
            is_active=True
        )
        db.add(group)
        await db.flush()
        group_code_to_id[code] = group.id
        
        # Create subject mappings
        for position, subject_code in enumerate(subject_codes, start=1):
            subject_id = subject_code_to_id.get(subject_code)
            if not subject_id:
                print(f"    ⚠️ Subject {subject_code} not found!")
                continue
            
            mapping = SubjectGroupSubject(
                subject_group_id=group.id,
                subject_id=subject_id,
                position=position
            )
            db.add(mapping)
        
        created += 1
        if created % 50 == 0:
            print(f"  ... created {created} groups")
    
    await db.commit()
    print(f"  ✅ Created: {created} new groups")
    print(f"  ⏭️ Skipped: {skipped} existing groups")
    print(f"  Total: {len(group_code_to_id)} groups")
    return group_code_to_id


async def main():
    """Main seeding function."""
    print("=" * 60)
    print("🌱 SEED 231 OFFICIAL SUBJECT GROUPS (Relational)")
    print("=" * 60)
    
    async with AsyncSessionLocal() as db:
        # 1. Seed Subjects (with new subjects)
        subject_ids = await seed_subjects(db)
        
        # 2. Seed Subject Groups (231 groups with mappings)
        group_ids = await seed_subject_groups(db, subject_ids)
        
        print("\n" + "=" * 60)
        print("✅ SEEDING COMPLETE!")
        print("=" * 60)
        print(f"  📚 Subjects: {len(subject_ids)}")
        print(f"  📐 Subject Groups: {len(group_ids)}")


if __name__ == "__main__":
    asyncio.run(main())
