# generate_hash.py
import sys
# Thêm đường dẫn dự án để import app
sys.path.append('.') 
from app.security import get_password_hash

# Tạo hash thật
plain_password = "ValidPassword123!" 
hashed_password = get_password_hash(plain_password)
print(f"REAL_PASSWORD_HASH_FOR_TESTUSER = \"{hashed_password}\"")

# Tạo dummy hash
dummy_password = "a_very_random_dummy_password_for_timing_attack_$%^&*"
dummy_hash = get_password_hash(dummy_password)
print(f"DUMMY_BCRYPT_HASH = \"{dummy_hash}\"")