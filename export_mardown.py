#!/usr/bin/env python3
"""
Export entire codebase to Markdown format (Windows-Safe Version).

Fixes:
- Replaced rglob with os.walk to strictly exclude directories like 'venv' and 'node_modules'.
- Prevents [WinError 1920] by skipping system/virtual environment files entirely.
- Optimized streaming write for large codebases.
"""

import os
import sys
from pathlib import Path
from typing import List, Set, TextIO
from datetime import datetime

class CodebaseExporter:
    """Export codebase to Markdown format with streaming support."""
    
    # File extensions to include
    FRONTEND_EXTENSIONS = {
        '.ts', '.tsx', '.js', '.jsx', 
        '.css', '.scss', '.sass', '.less',
        '.json', '.html', '.svg'
    }
    
    BACKEND_EXTENSIONS = {
        '.py', '.pyi', '.txt', '.yml', '.yaml',
        '.toml', '.ini', '.cfg', '.conf', '.md'
    }
    
    # Directories to exclude (CASE SENSITIVE)
    EXCLUDE_DIRS = {
        'node_modules', 'venv', '.venv', 'env', '.env',
        'dist', 'build', '.next', '__pycache__', '.pytest_cache',
        '.git', '.github', '.vscode', '.idea',
        'coverage', '.coverage', 'htmlcov',
        'logs', 'tmp', 'temp', 'exports', 'bin', 'obj', 'Include', 'Lib', 'Scripts'
    }
    
    # Files to exclude
    EXCLUDE_FILES = {
        '.env', '.env.local', '.env.production', '.env.development',
        'package-lock.json', 'yarn.lock', 'poetry.lock', 'Pipfile.lock',
        '.DS_Store', 'Thumbs.db', '.gitignore', '.dockerignore',
        'export_codebase_to_markdown.py', 'export_mardown.py'
    }
    
    # Exclude patterns
    EXCLUDE_PATTERNS = {
        # '*.md'
    }
    
    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        self.frontend_dir = self.project_root / 'frontend'
        self.backend_dir = self.project_root / 'Backend_FastAPI'
        self.output_dir = self.project_root / 'exports'
        
        self.stats = {
            'frontend_files': 0,
            'backend_files': 0,
            'frontend_lines': 0,
            'backend_lines': 0,
            'frontend_size': 0,
            'backend_size': 0
        }
    
    def should_exclude_file(self, path: Path) -> bool:
        """Check if file should be excluded based on patterns."""
        if path.name in self.EXCLUDE_FILES:
            return True
            
        for pattern in self.EXCLUDE_PATTERNS:
            if path.match(pattern):
                return True
        return False
    
    def get_language(self, ext: str) -> str:
        language_map = {
            '.ts': 'typescript', '.tsx': 'typescript',
            '.js': 'javascript', '.jsx': 'javascript',
            '.py': 'python', '.pyi': 'python',
            '.json': 'json', '.html': 'html', '.css': 'css',
            '.scss': 'scss', '.yaml': 'yaml', '.yml': 'yaml',
            '.xml': 'xml', '.svg': 'xml', '.sql': 'sql',
            '.sh': 'bash', '.bash': 'bash', '.md': 'markdown',
            '.toml': 'toml', '.ini': 'ini'
        }
        return language_map.get(ext.lower(), 'text')
    
    def collect_files(self, directory: Path, extensions: Set[str]) -> List[Path]:
        """
        Collect files using os.walk to safely prune excluded directories.
        This prevents the script from entering 'venv' or 'node_modules'.
        """
        files = []
        if not directory.exists():
            return files
            
        for root, dirs, filenames in os.walk(directory):
            # 1. Modify dirs list in-place to prevent os.walk from entering excluded directories
            # This is the key fix for WinError 1920
            dirs[:] = [d for d in dirs if d not in self.EXCLUDE_DIRS and not d.startswith('.')]
            
            for filename in filenames:
                if filename in self.EXCLUDE_FILES or filename.startswith('.'):
                    continue
                    
                file_path = Path(root) / filename
                
                # Check extension
                if file_path.suffix not in extensions:
                    continue
                
                # Check other exclusion patterns
                if self.should_exclude_file(file_path):
                    continue
                    
                files.append(file_path)
                
        return sorted(files)

    def stream_file_content(self, source_path: Path, dest_handle: TextIO) -> int:
        """Stream content from source to dest, returning line count."""
        line_count = 0
        try:
            # Try UTF-8 first
            with open(source_path, 'r', encoding='utf-8') as f:
                for line in f:
                    dest_handle.write(line)
                    line_count += 1
        except UnicodeDecodeError:
            # Fallback to latin-1 if binary/weird encoding
            try:
                with open(source_path, 'r', encoding='latin-1') as f:
                    for line in f:
                        dest_handle.write(line)
                        line_count += 1
            except Exception as e:
                dest_handle.write(f"\n[Error reading file: {e}]\n")
        except Exception as e:
            dest_handle.write(f"\n[Error reading file: {e}]\n")
            
        return line_count

    def write_tree_structure(self, directory: Path, file_handle: TextIO, prefix: str = "", is_last: bool = True):
        """Write tree structure directly to file, skipping excluded dirs."""
        if not directory.exists():
            return
        
        try:
            # Only list items that are NOT in EXCLUDE_DIRS/FILES
            items = []
            for item in directory.iterdir():
                if item.is_dir() and (item.name in self.EXCLUDE_DIRS or item.name.startswith('.')):
                    continue
                if item.is_file() and (item.name in self.EXCLUDE_FILES or item.name.startswith('.')):
                    continue
                items.append(item)
            
            items = sorted(items, key=lambda x: (not x.is_dir(), x.name))
        except PermissionError:
            return
        
        count = len(items)
        for i, item in enumerate(items):
            is_last_item = (i == count - 1)
            current_prefix = prefix + ("└── " if is_last else "├── ")
            next_prefix = prefix + ("    " if is_last else "│   ")
            
            if item.is_dir():
                file_handle.write(f"{current_prefix}{item.name}/\n")
                self.write_tree_structure(item, file_handle, next_prefix, is_last_item)
            else:
                file_handle.write(f"{current_prefix}{item.name}\n")

    def export_section_stream(self, files: List[Path], base_dir: Path, section_name: str, dest_handle: TextIO):
        """Export files to the open file handle."""
        print(f"\n📝 Exporting {section_name} ({len(files)} files)...")
        
        dest_handle.write(f"\n# {section_name} Source Code\n\n")
        
        for i, file_path in enumerate(files, 1):
            if i % 50 == 0:
                print(f"   Processed {i}/{len(files)} files...")
                
            try:
                rel_path = file_path.relative_to(self.project_root)
            except ValueError:
                rel_path = file_path.name
            
            try:
                file_size = file_path.stat().st_size
            except OSError:
                file_size = 0
                
            lang = self.get_language(file_path.suffix)
            
            dest_handle.write(f"\n## 📄 `{rel_path}`\n\n")
            dest_handle.write(f"**Size:** {file_size} bytes\n")
            dest_handle.write(f"```{lang}\n")
            
            # Stream content directly to avoid memory issues
            lines = self.stream_file_content(file_path, dest_handle)
            
            dest_handle.write("\n```\n")
            
            # Update stats
            is_frontend = section_name == "Frontend"
            prefix = 'frontend' if is_frontend else 'backend'
            self.stats[f'{prefix}_files'] += 1
            self.stats[f'{prefix}_lines'] += lines
            self.stats[f'{prefix}_size'] += file_size

    def generate_header(self, title: str, file_handle: TextIO):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        file_handle.write(f"# {title}\n\n")
        file_handle.write(f"**Generated:** {now}\n")
        file_handle.write("**Project:** QLTS (Quản Lý Tài Sản)\n")
        file_handle.write("---\n\n")

    def run(self, mode: str):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        print("🔍 Scanning files (skipping 'venv', 'node_modules')...")
        frontend_files = self.collect_files(self.frontend_dir, self.FRONTEND_EXTENSIONS)
        backend_files = self.collect_files(self.backend_dir, self.BACKEND_EXTENSIONS)
        
        # Define export jobs based on mode
        jobs = []
        if mode == 'frontend':
            jobs.append(('FRONTEND_SOURCE.md', [('Frontend', frontend_files, self.frontend_dir)]))
        elif mode == 'backend':
            jobs.append(('BACKEND_SOURCE.md', [('Backend', backend_files, self.backend_dir)]))
        elif mode == 'combined':
            jobs.append(('FULL_CODEBASE.md', [
                ('Frontend', frontend_files, self.frontend_dir),
                ('Backend', backend_files, self.backend_dir)
            ]))
        elif mode == 'all':
            # Create separate files + combined
            jobs.append(('FRONTEND_SOURCE.md', [('Frontend', frontend_files, self.frontend_dir)]))
            jobs.append(('BACKEND_SOURCE.md', [('Backend', backend_files, self.backend_dir)]))
            jobs.append(('FULL_CODEBASE.md', [
                ('Frontend', frontend_files, self.frontend_dir),
                ('Backend', backend_files, self.backend_dir)
            ]))

        print(f"🚀 Starting export in mode: {mode}")

        for filename, sections in jobs:
            output_path = self.output_dir / filename
            print(f"\n📄 Creating {filename}...")
            
            try:
                # Buffer increased to 1MB for speed
                with open(output_path, 'w', encoding='utf-8', buffering=1024*1024) as f:
                    self.generate_header(f"Source Code Export - {filename}", f)
                    
                    # Write Table of Contents
                    f.write("## 📑 Table of Contents\n\n")
                    f.write("1. [Directory Structure](#directory-structure)\n")
                    for sec_name, _, _ in sections:
                        f.write(f"2. [{sec_name} Source Code](#{sec_name.lower().replace(' ', '-')}-source-code)\n")
                    f.write("\n---\n\n")

                    # Write Tree Structure
                    f.write("## 📁 Directory Structure\n\n")
                    f.write("```\n")
                    for sec_name, _, base_dir in sections:
                        if base_dir.exists():
                            f.write(f"{base_dir.name}/\n")
                            self.write_tree_structure(base_dir, f)
                    f.write("```\n\n---\n")

                    # Export file contents
                    for sec_name, files, base_dir in sections:
                        if files:
                            self.export_section_stream(files, base_dir, sec_name, f)
                            
                print(f"✅ Saved: {output_path}")
                
            except IOError as e:
                print(f"❌ Error writing {filename}: {e}")

        print("\n" + "="*60)
        print("📊 EXPORT SUMMARY")
        print(f"Frontend: {self.stats['frontend_files']} files | {self.stats['frontend_lines']:,} lines")
        print(f"Backend:  {self.stats['backend_files']} files | {self.stats['backend_lines']:,} lines")
        print("="*60)

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Stream-based Codebase Exporter (Windows Safe)')
    parser.add_argument('--mode', choices=['frontend', 'backend', 'combined', 'all'], default='all')
    parser.add_argument('--root', type=Path, default=Path.cwd())
    
    args = parser.parse_args()
    exporter = CodebaseExporter(args.root)
    exporter.run(args.mode)

if __name__ == '__main__':
    main()