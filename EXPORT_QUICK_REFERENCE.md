# 📋 EXPORT QUICK REFERENCE

Quick reference guide cho việc export và sử dụng codebase exports.

---

## 🚀 QUICK START

### **Export tất cả (Recommended):**
```bash
python export_codebase_to_markdown.py
```

### **Export riêng lẻ:**
```bash
# Frontend only
python export_codebase_to_markdown.py --mode frontend

# Backend only
python export_codebase_to_markdown.py --mode backend

# Combined only
python export_codebase_to_markdown.py --mode combined
```

---

## 📁 OUTPUT FILES

| File | Size | Content |
|------|------|---------|
| `FRONTEND_SOURCE.md` | 164 KB | 60 files, 5,009 lines |
| `BACKEND_SOURCE.md` | 326 KB | 48 files, 8,844 lines |
| `FULL_CODEBASE_EXPORT.md` | 490 KB | 108 files, 13,853 lines |

**Location:** `d:\QLTS\exports\`

---

## 🎯 COMMON USE CASES

### **1. AI Code Review:**
```
Upload: FULL_CODEBASE_EXPORT.md
Prompt: "Review this codebase for security issues and best practices"
```

### **2. Architecture Analysis:**
```
Upload: FULL_CODEBASE_EXPORT.md
Prompt: "Analyze the architecture and suggest improvements"
```

### **3. Bug Detection:**
```
Upload: FULL_CODEBASE_EXPORT.md
Prompt: "Find potential bugs and edge cases"
```

### **4. Documentation:**
```
Upload: FULL_CODEBASE_EXPORT.md
Prompt: "Generate API documentation from this code"
```

---

## 📊 STATISTICS

### **Frontend:**
- **Files:** 60
- **Lines:** 5,009
- **Size:** 164.53 KB
- **Main tech:** Next.js, TypeScript, React

### **Backend:**
- **Files:** 48
- **Lines:** 8,844
- **Size:** 325.90 KB
- **Main tech:** FastAPI, Python, SQLAlchemy

### **Total:**
- **Files:** 108
- **Lines:** 13,853
- **Size:** 490.43 KB

---

## 🔧 CUSTOMIZATION

### **Include .md files:**
Edit `export_codebase_to_markdown.py`:
```python
EXCLUDE_PATTERNS = {
    # '*.md', '*.MD'  # Comment out
}
```

### **Add more extensions:**
```python
FRONTEND_EXTENSIONS = {
    '.ts', '.tsx', '.js', '.jsx',
    '.vue',  # Add Vue files
    '.svelte',  # Add Svelte files
}
```

### **Exclude more directories:**
```python
EXCLUDE_DIRS = {
    'node_modules', 'venv',
    'my_custom_dir',  # Add custom exclusion
}
```

---

## 🐛 TROUBLESHOOTING

### **"Directory not found"**
```bash
# Run from project root
cd d:\QLTS
python export_codebase_to_markdown.py
```

### **"No files found"**
```bash
# Check directories exist
ls frontend/src/
ls Backend_FastAPI/app/
```

### **File too large**
```bash
# Export separately
python export_codebase_to_markdown.py --mode frontend
python export_codebase_to_markdown.py --mode backend
```

---

## 📚 DOCUMENTATION

- **Full guide:** `EXPORT_GUIDE.md`
- **Success summary:** `EXPORT_SUCCESS_SUMMARY.md`
- **This file:** `EXPORT_QUICK_REFERENCE.md`

---

## ✅ CHECKLIST

Before export:
- [ ] Latest code committed
- [ ] No sensitive data in code
- [ ] Enough disk space (~10 MB)

After export:
- [ ] Review output files
- [ ] Backup exports
- [ ] Share with team (if needed)

---

## 🔄 RE-EXPORT

```bash
# When code changes
python export_codebase_to_markdown.py --mode all
```

**Frequency:** After major changes, before deployment, or weekly.

---

## 📞 HELP

```bash
# Show help
python export_codebase_to_markdown.py --help

# Show version
python export_codebase_to_markdown.py --version
```

---

**Last updated:** 2025-11-04  
**Script version:** 1.0.0

