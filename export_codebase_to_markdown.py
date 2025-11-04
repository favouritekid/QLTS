#!/usr/bin/env python3
"""
Export entire codebase to Markdown format.

This script exports all source code files from frontend and backend
into well-formatted Markdown files for documentation or AI analysis.

Features:
- Separate exports for frontend and backend
- Tree structure visualization
- Syntax highlighting
- Progress tracking
- File size estimation
- Configurable exclusions
"""

import os
import sys
from pathlib import Path
from typing import List, Dict, Set, Tuple
from datetime import datetime
import mimetypes


class CodebaseExporter:
    """Export codebase to Markdown format."""
    
    # File extensions to include
    FRONTEND_EXTENSIONS = {
        '.ts', '.tsx', '.js', '.jsx', 
        '.css', '.scss', '.sass', '.less',
        '.json', '.html', '.svg'
    }
    
    BACKEND_EXTENSIONS = {
        '.py', '.pyi', '.txt', '.yml', '.yaml',
        '.toml', '.ini', '.cfg', '.conf'
    }
    
    # Directories to exclude
    EXCLUDE_DIRS = {
        'node_modules', 'venv', '.venv', 'env', '.env',
        'dist', 'build', '.next', '__pycache__', '.pytest_cache',
        '.git', '.github', '.vscode', '.idea',
        'coverage', '.coverage', 'htmlcov',
        'logs', 'tmp', 'temp'
    }
    
    # Files to exclude
    EXCLUDE_FILES = {
        '.env', '.env.local', '.env.production', '.env.development',
        'package-lock.json', 'yarn.lock', 'poetry.lock', 'Pipfile.lock',
        '.DS_Store', 'Thumbs.db', '.gitignore', '.dockerignore'
    }
    
    # Exclude markdown files (documentation)
    EXCLUDE_PATTERNS = {
        '*.md', '*.MD'
    }
    
    def __init__(self, project_root: Path):
        """Initialize exporter with project root directory."""
        self.project_root = project_root
        self.frontend_dir = project_root / 'frontend' / 'src'
        self.backend_dir = project_root / 'Backend_FastAPI' / 'app'
        self.output_dir = project_root / 'exports'
        
        # Statistics
        self.stats = {
            'frontend_files': 0,
            'backend_files': 0,
            'frontend_lines': 0,
            'backend_lines': 0,
            'frontend_size': 0,
            'backend_size': 0
        }
    
    def should_exclude(self, path: Path) -> bool:
        """Check if path should be excluded."""
        # Check if any parent directory is in exclude list
        for parent in path.parents:
            if parent.name in self.EXCLUDE_DIRS:
                return True
        
        # Check if filename is in exclude list
        if path.name in self.EXCLUDE_FILES:
            return True
        
        # Check if matches exclude patterns
        for pattern in self.EXCLUDE_PATTERNS:
            if path.match(pattern):
                return True
        
        return False
    
    def get_language_from_extension(self, ext: str) -> str:
        """Get syntax highlighting language from file extension."""
        language_map = {
            '.ts': 'typescript',
            '.tsx': 'typescript',
            '.js': 'javascript',
            '.jsx': 'javascript',
            '.py': 'python',
            '.pyi': 'python',
            '.json': 'json',
            '.yml': 'yaml',
            '.yaml': 'yaml',
            '.toml': 'toml',
            '.css': 'css',
            '.scss': 'scss',
            '.sass': 'sass',
            '.html': 'html',
            '.svg': 'xml',
            '.ini': 'ini',
            '.cfg': 'ini',
            '.conf': 'conf',
            '.txt': 'text'
        }
        return language_map.get(ext.lower(), 'text')
    
    def generate_tree_structure(self, directory: Path, prefix: str = "", is_last: bool = True) -> List[str]:
        """Generate tree structure visualization."""
        lines = []
        
        if not directory.exists():
            return lines
        
        # Get all items in directory
        try:
            items = sorted(directory.iterdir(), key=lambda x: (not x.is_dir(), x.name))
        except PermissionError:
            return lines
        
        # Filter out excluded items
        items = [item for item in items if not self.should_exclude(item)]
        
        for i, item in enumerate(items):
            is_last_item = i == len(items) - 1
            
            # Create tree characters
            if is_last:
                current_prefix = prefix + "└── "
                next_prefix = prefix + "    "
            else:
                current_prefix = prefix + "├── "
                next_prefix = prefix + "│   "
            
            # Add current item
            if item.is_dir():
                lines.append(f"{current_prefix}{item.name}/")
                # Recursively add subdirectory contents
                lines.extend(self.generate_tree_structure(item, next_prefix, is_last_item))
            else:
                lines.append(f"{current_prefix}{item.name}")
        
        return lines
    
    def collect_files(self, directory: Path, extensions: Set[str]) -> List[Path]:
        """Collect all files with specified extensions from directory."""
        files = []
        
        if not directory.exists():
            print(f"⚠️  Directory not found: {directory}")
            return files
        
        for item in directory.rglob('*'):
            if item.is_file() and not self.should_exclude(item):
                if item.suffix in extensions:
                    files.append(item)
        
        return sorted(files)
    
    def read_file_content(self, file_path: Path) -> Tuple[str, int]:
        """Read file content and return content with line count."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.count('\n') + 1
                return content, lines
        except UnicodeDecodeError:
            # Try with different encoding
            try:
                with open(file_path, 'r', encoding='latin-1') as f:
                    content = f.read()
                    lines = content.count('\n') + 1
                    return content, lines
            except Exception as e:
                return f"[Error reading file: {e}]", 0
        except Exception as e:
            return f"[Error reading file: {e}]", 0
    
    def export_section(self, files: List[Path], base_dir: Path, section_name: str) -> str:
        """Export a section of files to Markdown format."""
        markdown_lines = []
        
        print(f"\n📝 Exporting {section_name}...")
        print(f"   Found {len(files)} files")
        
        for i, file_path in enumerate(files, 1):
            # Progress indicator
            if i % 10 == 0 or i == len(files):
                print(f"   Progress: {i}/{len(files)} files ({i*100//len(files)}%)")
            
            # Get relative path
            try:
                rel_path = file_path.relative_to(base_dir)
            except ValueError:
                rel_path = file_path.relative_to(self.project_root)
            
            # Read file content
            content, line_count = self.read_file_content(file_path)
            
            # Get language for syntax highlighting
            language = self.get_language_from_extension(file_path.suffix)
            
            # Add to markdown
            markdown_lines.append(f"\n## 📄 `{rel_path}`\n")
            markdown_lines.append(f"**Lines:** {line_count} | **Size:** {file_path.stat().st_size} bytes\n")
            markdown_lines.append(f"```{language}")
            markdown_lines.append(content)
            markdown_lines.append("```\n")
            
            # Update statistics
            if section_name == "Frontend":
                self.stats['frontend_files'] += 1
                self.stats['frontend_lines'] += line_count
                self.stats['frontend_size'] += file_path.stat().st_size
            else:
                self.stats['backend_files'] += 1
                self.stats['backend_lines'] += line_count
                self.stats['backend_size'] += file_path.stat().st_size
        
        return '\n'.join(markdown_lines)
    
    def format_size(self, size_bytes: int) -> str:
        """Format file size in human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} TB"
    
    def generate_header(self, title: str, description: str) -> str:
        """Generate Markdown header with metadata."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        header = f"""# {title}

**Generated:** {now}  
**Project:** QLTS (Quản Lý Tài Sản)  
**Description:** {description}

---

"""
        return header
    
    def generate_statistics(self) -> str:
        """Generate statistics section."""
        stats = f"""## 📊 Statistics

### Frontend
- **Files:** {self.stats['frontend_files']}
- **Lines of Code:** {self.stats['frontend_lines']:,}
- **Total Size:** {self.format_size(self.stats['frontend_size'])}

### Backend
- **Files:** {self.stats['backend_files']}
- **Lines of Code:** {self.stats['backend_lines']:,}
- **Total Size:** {self.format_size(self.stats['backend_size'])}

### Total
- **Files:** {self.stats['frontend_files'] + self.stats['backend_files']}
- **Lines of Code:** {self.stats['frontend_lines'] + self.stats['backend_lines']:,}
- **Total Size:** {self.format_size(self.stats['frontend_size'] + self.stats['backend_size'])}

---

"""
        return stats

    def export_frontend(self) -> bool:
        """Export frontend source code to Markdown."""
        print("\n" + "="*60)
        print("🎨 EXPORTING FRONTEND SOURCE CODE")
        print("="*60)

        # Collect files
        files = self.collect_files(self.frontend_dir, self.FRONTEND_EXTENSIONS)

        if not files:
            print("⚠️  No frontend files found!")
            return False

        # Generate tree structure
        print("\n📁 Generating directory tree...")
        tree_lines = self.generate_tree_structure(self.frontend_dir)
        tree_structure = '\n'.join(tree_lines)

        # Generate header
        header = self.generate_header(
            "Frontend Source Code",
            "Complete source code export of the Next.js frontend application"
        )

        # Add tree structure
        tree_section = f"""## 📁 Directory Structure

```
frontend/src/
{tree_structure}
```

---

## 📝 Source Files

"""

        # Export files
        content = self.export_section(files, self.frontend_dir, "Frontend")

        # Combine all sections
        markdown = header + tree_section + content

        # Write to file
        output_file = self.output_dir / 'FRONTEND_SOURCE.md'
        self.output_dir.mkdir(exist_ok=True)

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(markdown)

        print(f"\n✅ Frontend export complete: {output_file}")
        print(f"   Files: {self.stats['frontend_files']}")
        print(f"   Lines: {self.stats['frontend_lines']:,}")
        print(f"   Size: {self.format_size(self.stats['frontend_size'])}")

        return True

    def export_backend(self) -> bool:
        """Export backend source code to Markdown."""
        print("\n" + "="*60)
        print("🔧 EXPORTING BACKEND SOURCE CODE")
        print("="*60)

        # Collect files
        files = self.collect_files(self.backend_dir, self.BACKEND_EXTENSIONS)

        if not files:
            print("⚠️  No backend files found!")
            return False

        # Generate tree structure
        print("\n📁 Generating directory tree...")
        tree_lines = self.generate_tree_structure(self.backend_dir)
        tree_structure = '\n'.join(tree_lines)

        # Generate header
        header = self.generate_header(
            "Backend Source Code",
            "Complete source code export of the FastAPI backend application"
        )

        # Add tree structure
        tree_section = f"""## 📁 Directory Structure

```
Backend_FastAPI/app/
{tree_structure}
```

---

## 📝 Source Files

"""

        # Export files
        content = self.export_section(files, self.backend_dir, "Backend")

        # Combine all sections
        markdown = header + tree_section + content

        # Write to file
        output_file = self.output_dir / 'BACKEND_SOURCE.md'
        self.output_dir.mkdir(exist_ok=True)

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(markdown)

        print(f"\n✅ Backend export complete: {output_file}")
        print(f"   Files: {self.stats['backend_files']}")
        print(f"   Lines: {self.stats['backend_lines']:,}")
        print(f"   Size: {self.format_size(self.stats['backend_size'])}")

        return True

    def export_combined(self) -> bool:
        """Export combined frontend + backend to single Markdown file."""
        print("\n" + "="*60)
        print("📦 EXPORTING COMBINED SOURCE CODE")
        print("="*60)

        # Collect files
        frontend_files = self.collect_files(self.frontend_dir, self.FRONTEND_EXTENSIONS)
        backend_files = self.collect_files(self.backend_dir, self.BACKEND_EXTENSIONS)

        if not frontend_files and not backend_files:
            print("⚠️  No files found!")
            return False

        # Generate header
        header = self.generate_header(
            "Complete Project Source Code",
            "Full source code export of QLTS project (Frontend + Backend)"
        )

        # Table of contents
        toc = """## 📑 Table of Contents

1. [Frontend Source Code](#frontend-source-code)
2. [Backend Source Code](#backend-source-code)
3. [Statistics](#statistics)

---

"""

        # Frontend section
        frontend_section = ""
        if frontend_files:
            print("\n📁 Generating frontend tree...")
            tree_lines = self.generate_tree_structure(self.frontend_dir)
            tree_structure = '\n'.join(tree_lines)

            frontend_section = f"""# Frontend Source Code

## 📁 Directory Structure

```
frontend/src/
{tree_structure}
```

---

## 📝 Source Files

"""
            frontend_section += self.export_section(frontend_files, self.frontend_dir, "Frontend")

        # Backend section
        backend_section = ""
        if backend_files:
            print("\n📁 Generating backend tree...")
            tree_lines = self.generate_tree_structure(self.backend_dir)
            tree_structure = '\n'.join(tree_lines)

            backend_section = f"""

---

# Backend Source Code

## 📁 Directory Structure

```
Backend_FastAPI/app/
{tree_structure}
```

---

## 📝 Source Files

"""
            backend_section += self.export_section(backend_files, self.backend_dir, "Backend")

        # Statistics
        stats_section = self.generate_statistics()

        # Combine all sections
        markdown = header + toc + stats_section + frontend_section + backend_section

        # Write to file
        output_file = self.output_dir / 'FULL_CODEBASE_EXPORT.md'
        self.output_dir.mkdir(exist_ok=True)

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(markdown)

        print(f"\n✅ Combined export complete: {output_file}")
        print(f"   Total files: {self.stats['frontend_files'] + self.stats['backend_files']}")
        print(f"   Total lines: {self.stats['frontend_lines'] + self.stats['backend_lines']:,}")
        print(f"   Total size: {self.format_size(self.stats['frontend_size'] + self.stats['backend_size'])}")

        return True

    def run(self, mode: str = 'all'):
        """Run the export process."""
        print("\n" + "="*60)
        print("🚀 CODEBASE EXPORTER")
        print("="*60)
        print(f"Project Root: {self.project_root}")
        print(f"Output Directory: {self.output_dir}")
        print(f"Export Mode: {mode}")

        success = False

        if mode == 'frontend':
            success = self.export_frontend()
        elif mode == 'backend':
            success = self.export_backend()
        elif mode == 'combined':
            success = self.export_combined()
        elif mode == 'all':
            # Export all three versions
            self.export_frontend()
            # Reset stats for backend
            backend_stats = {
                'backend_files': 0,
                'backend_lines': 0,
                'backend_size': 0
            }
            self.stats.update(backend_stats)
            self.export_backend()
            # Reset all stats for combined
            self.stats = {
                'frontend_files': 0,
                'backend_files': 0,
                'frontend_lines': 0,
                'backend_lines': 0,
                'frontend_size': 0,
                'backend_size': 0
            }
            success = self.export_combined()
        else:
            print(f"❌ Invalid mode: {mode}")
            print("   Valid modes: frontend, backend, combined, all")
            return False

        if success:
            print("\n" + "="*60)
            print("✅ EXPORT COMPLETED SUCCESSFULLY")
            print("="*60)

        return success


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Export codebase to Markdown format',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python export_codebase_to_markdown.py                    # Export all (default)
  python export_codebase_to_markdown.py --mode frontend    # Export frontend only
  python export_codebase_to_markdown.py --mode backend     # Export backend only
  python export_codebase_to_markdown.py --mode combined    # Export combined file only
        """
    )

    parser.add_argument(
        '--mode',
        choices=['frontend', 'backend', 'combined', 'all'],
        default='all',
        help='Export mode (default: all)'
    )

    parser.add_argument(
        '--project-root',
        type=Path,
        default=Path.cwd(),
        help='Project root directory (default: current directory)'
    )

    args = parser.parse_args()

    # Create exporter
    exporter = CodebaseExporter(args.project_root)

    # Run export
    success = exporter.run(args.mode)

    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()

