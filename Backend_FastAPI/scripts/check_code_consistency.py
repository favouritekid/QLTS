#!/usr/bin/env python3
"""
Code Consistency Checker

Validates consistency between:
1. SQLAlchemy Models (app/models/finance/)
2. Alembic Migrations (alembic/versions/fin*.py)
3. Services (app/services/*_service.py)
4. Repositories (app/repositories/*_repository.py)
5. Schemas (app/schemas/finance.py)

Does NOT require database connection or importable modules.
Uses AST parsing and regex for analysis.

Usage:
    python scripts/check_code_consistency.py
"""

import os
import sys
import re
import ast
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass, field
from collections import defaultdict

PROJECT_ROOT = Path(__file__).parent.parent


@dataclass
class ModelColumn:
    """Model column information."""
    name: str
    type_hint: str
    mapped_column: bool = False
    nullable: Optional[bool] = None
    has_default: bool = False


@dataclass
class ModelClass:
    """Model class information."""
    name: str
    table_name: str
    file_path: str
    columns: Dict[str, ModelColumn] = field(default_factory=dict)
    relationships: List[str] = field(default_factory=list)
    enums_used: List[str] = field(default_factory=list)
    properties: List[str] = field(default_factory=list)  # @property methods


@dataclass
class MigrationTable:
    """Migration table information."""
    name: str
    columns: List[str] = field(default_factory=list)
    foreign_keys: List[Tuple[str, str]] = field(default_factory=list)


@dataclass
class Issue:
    """Validation issue."""
    severity: str  # ERROR, WARNING, INFO
    category: str
    message: str
    file: Optional[str] = None
    line: Optional[int] = None


class ModelParser:
    """Parse SQLAlchemy model files."""

    def __init__(self):
        self.models: Dict[str, ModelClass] = {}

    def parse_directory(self, models_dir: Path) -> Dict[str, ModelClass]:
        """Parse all model files in directory."""
        finance_dir = models_dir / "finance"

        if not finance_dir.exists():
            return {}

        for py_file in finance_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                # Parse __init__.py for exports
                if py_file.name == "__init__.py":
                    self._parse_init(py_file)
                continue
            self._parse_model_file(py_file)

        return self.models

    def _parse_init(self, file_path: Path) -> List[str]:
        """Parse __init__.py for exports."""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find __all__ or from imports
        exports = []
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == '__all__':
                            if isinstance(node.value, ast.List):
                                for elt in node.value.elts:
                                    if isinstance(elt, ast.Constant):
                                        exports.append(elt.value)
        except:
            pass

        return exports

    def _parse_model_file(self, file_path: Path) -> None:
        """Parse a single model file."""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            print(f"⚠️  Syntax error in {file_path}: {e}")
            return

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                model = self._parse_class(node, file_path)
                if model:
                    self.models[model.name] = model

    def _parse_class(self, node: ast.ClassDef, file_path: Path) -> Optional[ModelClass]:
        """Parse a class definition."""
        # Check if it has __tablename__
        table_name = None
        columns = {}
        relationships = []
        enums_used = []
        properties = []

        for item in node.body:
            # Look for __tablename__
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name) and target.id == '__tablename__':
                        if isinstance(item.value, ast.Constant):
                            table_name = item.value.value

            # Look for @property decorated methods
            if isinstance(item, ast.FunctionDef):
                for decorator in item.decorator_list:
                    if isinstance(decorator, ast.Name) and decorator.id == 'property':
                        properties.append(item.name)
                        break

            # Look for annotated assignments (columns)
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                col_name = item.target.id

                # Skip private/dunder
                if col_name.startswith('_'):
                    continue

                type_hint = ast.unparse(item.annotation) if item.annotation else 'Unknown'

                # Check if it's a relationship - check both type hint and value
                is_relationship = False

                # Check type hint for relationship keyword
                if 'relationship' in type_hint.lower():
                    is_relationship = True

                # Check if value is a relationship() call
                if item.value:
                    value_str = ast.unparse(item.value)
                    if 'relationship(' in value_str:
                        is_relationship = True

                if is_relationship:
                    relationships.append(col_name)
                    continue

                # Check if it's a mapped_column (actual DB column)
                is_mapped = 'Mapped[' in type_hint
                has_mapped_column_call = False
                if item.value:
                    value_str = ast.unparse(item.value)
                    has_mapped_column_call = 'mapped_column(' in value_str

                # Only add as column if it has mapped_column() call (actual DB column)
                # This filters out relationships that use relationship() calls
                if has_mapped_column_call:
                    # Check for enum usage
                    if 'Enum' in type_hint or any(e in type_hint for e in ['StatusEnum', 'TypeEnum']):
                        enums_used.append(col_name)

                    columns[col_name] = ModelColumn(
                        name=col_name,
                        type_hint=type_hint,
                        mapped_column=is_mapped,
                        has_default=True,
                    )

        if table_name:
            return ModelClass(
                name=node.name,
                table_name=table_name,
                file_path=str(file_path),
                columns=columns,
                relationships=relationships,
                enums_used=enums_used,
                properties=properties,
            )

        return None


class MigrationParser:
    """Parse Alembic migration files."""

    def __init__(self):
        self.tables: Dict[str, MigrationTable] = {}

    def parse_migrations(self, alembic_dir: Path) -> Dict[str, MigrationTable]:
        """Parse finance migration files."""
        versions_dir = alembic_dir / "versions"

        if not versions_dir.exists():
            return {}

        # Find finance migrations
        for py_file in versions_dir.glob("fin*.py"):
            self._parse_migration(py_file)

        return self.tables

    def _parse_migration(self, file_path: Path) -> None:
        """Parse a migration file."""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find all op.create_table calls
        table_pattern = r"op\.create_table\s*\(\s*['\"](\w+)['\"]"
        table_matches = list(re.finditer(table_pattern, content))

        for i, match in enumerate(table_matches):
            table_name = match.group(1)
            start_pos = match.start()

            # Find the end of this table block (next op.create_table or op.create_index)
            if i + 1 < len(table_matches):
                end_pos = table_matches[i + 1].start()
            else:
                # Last table - find next major operation or end of upgrade function
                next_op = content.find("op.create_index", start_pos + 50)
                downgrade_pos = content.find("def downgrade", start_pos)
                if next_op > 0 and (downgrade_pos < 0 or next_op < downgrade_pos):
                    end_pos = next_op
                elif downgrade_pos > 0:
                    end_pos = downgrade_pos
                else:
                    end_pos = len(content)

            block = content[start_pos:end_pos]

            # Find sa.Column calls
            col_pattern = r"sa\.Column\s*\(\s*['\"](\w+)['\"]"
            columns = re.findall(col_pattern, block)

            # Find ForeignKey references
            fk_pattern = r"sa\.ForeignKey\s*\(\s*['\"](\w+)\.(\w+)['\"]"
            foreign_keys = re.findall(fk_pattern, block)

            self.tables[table_name] = MigrationTable(
                name=table_name,
                columns=columns,
                foreign_keys=foreign_keys,
            )


class ServiceAnalyzer:
    """Analyze service files for model usage."""

    def __init__(self):
        self.usages: Dict[str, Dict[str, Set[str]]] = {}  # service -> model -> attributes

    def analyze(self, services_dir: Path) -> Dict[str, Dict[str, Set[str]]]:
        """Analyze service files."""
        finance_services = [
            'fee_calculation_service.py',
            'invoice_service.py',
            'payment_service.py',
            'payment_intent_service.py',
            'accounting_service.py',
        ]

        for svc_name in finance_services:
            svc_path = services_dir / svc_name
            if svc_path.exists():
                self.usages[svc_name] = self._analyze_file(svc_path)

        return self.usages

    def _analyze_file(self, file_path: Path) -> Dict[str, Set[str]]:
        """Analyze a single service file."""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        result = defaultdict(set)

        # Model variable patterns
        model_vars = {
            'fee': 'Fee',
            'invoice': 'Invoice',
            'payment': 'Payment',
            'payment_intent': 'PaymentIntent',
            'installment_plan': 'InstallmentPlan',
            'payment_method': 'PaymentMethod',
            'refund': 'RefundRequest',
            'overpayment': 'OverpaymentRecord',
            'period': 'AccountingPeriod',
            'transaction': 'PaymentTransaction',
            'discount': 'FeeAppliedDiscount',
            'event': 'ProcessedEvent',
        }

        for var_name, model_name in model_vars.items():
            # Find attribute access: var.attribute
            pattern = rf'\b{var_name}\.(\w+)'
            for match in re.finditer(pattern, content):
                attr = match.group(1)
                # Filter out method calls and Python built-ins
                if attr not in ('append', 'extend', 'items', 'keys', 'values', 'get', 'pop',
                               'update', 'copy', 'clear', '__', 'model_dump'):
                    result[model_name].add(attr)

        return dict(result)


class SchemaAnalyzer:
    """Analyze Pydantic schema files."""

    def __init__(self):
        self.schemas: Dict[str, Set[str]] = {}

    def analyze(self, schemas_dir: Path) -> Dict[str, Set[str]]:
        """Analyze finance schema file."""
        finance_schema = schemas_dir / "finance.py"

        if not finance_schema.exists():
            return {}

        with open(finance_schema, 'r', encoding='utf-8') as f:
            content = f.read()

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return {}

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                fields = set()
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        fields.add(item.target.id)
                if fields:
                    self.schemas[node.name] = fields

        return self.schemas


class ConsistencyChecker:
    """Main consistency checker."""

    def __init__(self):
        self.issues: List[Issue] = []
        self.models: Dict[str, ModelClass] = {}
        self.migrations: Dict[str, MigrationTable] = {}
        self.service_usages: Dict[str, Dict[str, Set[str]]] = {}
        self.schemas: Dict[str, Set[str]] = {}

    def check_all(self) -> List[Issue]:
        """Run all checks."""
        print("=" * 70)
        print("CODE CONSISTENCY CHECK")
        print("=" * 70)

        # Parse all sources
        self._parse_models()
        self._parse_migrations()
        self._parse_services()
        self._parse_schemas()

        # Run checks
        self._check_model_migration_sync()
        self._check_service_model_attrs()
        self._check_architecture_violations()
        self._check_enum_consistency()
        self._check_model_exports()

        # Print results
        self._print_results()

        return self.issues

    def _parse_models(self) -> None:
        """Parse model files."""
        print("\n📦 Parsing Models...")
        parser = ModelParser()
        self.models = parser.parse_directory(PROJECT_ROOT / "app" / "models")
        print(f"   Found {len(self.models)} model classes")

    def _parse_migrations(self) -> None:
        """Parse migration files."""
        print("\n📜 Parsing Migrations...")
        parser = MigrationParser()
        self.migrations = parser.parse_migrations(PROJECT_ROOT / "alembic")
        print(f"   Found {len(self.migrations)} tables in migrations")

    def _parse_services(self) -> None:
        """Parse service files."""
        print("\n⚙️  Parsing Services...")
        analyzer = ServiceAnalyzer()
        self.service_usages = analyzer.analyze(PROJECT_ROOT / "app" / "services")
        print(f"   Analyzed {len(self.service_usages)} service files")

    def _parse_schemas(self) -> None:
        """Parse schema files."""
        print("\n📝 Parsing Schemas...")
        analyzer = SchemaAnalyzer()
        self.schemas = analyzer.analyze(PROJECT_ROOT / "app" / "schemas")
        print(f"   Found {len(self.schemas)} schema classes")

    def _check_model_migration_sync(self) -> None:
        """Check if models match migrations."""
        print("\n🔄 Checking Model ↔ Migration Sync...")

        for model_name, model in self.models.items():
            table_name = model.table_name

            if table_name not in self.migrations:
                self.issues.append(Issue(
                    severity="WARNING",
                    category="Migration",
                    message=f"Model {model_name} table '{table_name}' not found in migrations",
                    file=model.file_path,
                ))
                continue

            migration = self.migrations[table_name]

            # Get model columns (exclude relationships which are not DB columns)
            model_cols = set(model.columns.keys()) - set(model.relationships)
            migration_cols = set(migration.columns)

            # Check for mismatches
            in_model_not_migration = model_cols - migration_cols
            in_migration_not_model = migration_cols - model_cols

            if in_model_not_migration:
                self.issues.append(Issue(
                    severity="ERROR",
                    category="Model-Migration",
                    message=f"{model_name}: columns in model but not migration: {in_model_not_migration}",
                    file=model.file_path,
                ))

            if in_migration_not_model:
                self.issues.append(Issue(
                    severity="WARNING",
                    category="Model-Migration",
                    message=f"{model_name}: columns in migration but not model: {in_migration_not_model}",
                    file=model.file_path,
                ))

            if not in_model_not_migration and not in_migration_not_model:
                print(f"   ✅ {model_name} ↔ {table_name}: synced ({len(migration_cols)} columns)")

            if not in_model_not_migration and not in_migration_not_model:
                print(f"   ✅ {model_name} ↔ {table_name}: synced")

    def _check_service_model_attrs(self) -> None:
        """Check if services use valid model attributes."""
        print("\n🔍 Checking Service Model Attribute Usage...")

        # Known valid non-column attributes
        valid_extras = {
            'id', 'created_at', 'updated_at', 'deleted_at',
            'get_installment_schedule',  # method
            'value',  # enum value
            'example',  # false positive from URLs like payment.example.com
            'com',  # false positive from URLs
        }

        for service_name, model_usages in self.service_usages.items():
            for model_name, attrs in model_usages.items():
                if model_name not in self.models:
                    continue

                model = self.models[model_name]
                model_attrs = (
                    set(model.columns.keys()) |
                    set(model.relationships) |
                    set(model.properties) |  # Include @property methods
                    valid_extras
                )

                invalid = attrs - model_attrs

                if invalid:
                    self.issues.append(Issue(
                        severity="ERROR",
                        category="Service",
                        message=f"{service_name} uses invalid {model_name} attrs: {invalid}",
                        file=f"app/services/{service_name}",
                    ))
                else:
                    print(f"   ✅ {service_name}: {model_name} attrs OK")

    def _check_architecture_violations(self) -> None:
        """Check for architecture rule violations."""
        print("\n🏛️  Checking Architecture Rules...")

        services_dir = PROJECT_ROOT / "app" / "services"

        for svc_file in services_dir.glob("*_service.py"):
            if not any(kw in svc_file.name for kw in ['fee', 'invoice', 'payment', 'accounting']):
                continue

            with open(svc_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # Check for HTTPException
            if 'HTTPException' in content:
                self.issues.append(Issue(
                    severity="ERROR",
                    category="Architecture",
                    message="Service imports/uses HTTPException (should use domain exceptions)",
                    file=str(svc_file),
                ))

            # Check for Request/Response
            if re.search(r'from fastapi import.*Request', content):
                self.issues.append(Issue(
                    severity="ERROR",
                    category="Architecture",
                    message="Service imports Request from fastapi",
                    file=str(svc_file),
                ))

            # Check for db.commit()
            if 'db.commit()' in content or 'await db.commit()' in content:
                self.issues.append(Issue(
                    severity="WARNING",
                    category="Architecture",
                    message="Service calls db.commit() (should only flush, router commits)",
                    file=str(svc_file),
                ))

            print(f"   Checked {svc_file.name}")

    def _check_enum_consistency(self) -> None:
        """Check enum usage consistency."""
        print("\n🔢 Checking Enum Consistency...")

        # Find all enum definitions in models
        enums_defined = set()
        enum_pattern = r'class\s+(\w+Enum)\s*\('

        for model in self.models.values():
            with open(model.file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            enums_defined.update(re.findall(enum_pattern, content))

        print(f"   Found {len(enums_defined)} enum classes")

        # Check if enums are exported
        init_file = PROJECT_ROOT / "app" / "models" / "finance" / "__init__.py"
        if init_file.exists():
            with open(init_file, 'r', encoding='utf-8') as f:
                init_content = f.read()

            for enum_name in enums_defined:
                if enum_name not in init_content:
                    self.issues.append(Issue(
                        severity="WARNING",
                        category="Exports",
                        message=f"Enum {enum_name} not exported in __init__.py",
                    ))

    def _check_model_exports(self) -> None:
        """Check if all models are properly exported."""
        print("\n📤 Checking Model Exports...")

        init_file = PROJECT_ROOT / "app" / "models" / "finance" / "__init__.py"
        if not init_file.exists():
            self.issues.append(Issue(
                severity="ERROR",
                category="Exports",
                message="finance/__init__.py not found",
            ))
            return

        with open(init_file, 'r', encoding='utf-8') as f:
            init_content = f.read()

        for model_name in self.models.keys():
            if model_name not in init_content:
                self.issues.append(Issue(
                    severity="WARNING",
                    category="Exports",
                    message=f"Model {model_name} not exported in __init__.py",
                ))
            else:
                print(f"   ✅ {model_name} exported")

    def _print_results(self) -> None:
        """Print validation results."""
        print("\n" + "=" * 70)
        print("RESULTS SUMMARY")
        print("=" * 70)

        errors = [i for i in self.issues if i.severity == "ERROR"]
        warnings = [i for i in self.issues if i.severity == "WARNING"]
        infos = [i for i in self.issues if i.severity == "INFO"]

        print(f"\n❌ Errors: {len(errors)}")
        print(f"⚠️  Warnings: {len(warnings)}")
        print(f"ℹ️  Info: {len(infos)}")

        if errors:
            print("\n❌ ERRORS:")
            for err in errors:
                print(f"   [{err.category}] {err.message}")
                if err.file:
                    print(f"      File: {err.file}")

        if warnings:
            print("\n⚠️  WARNINGS:")
            for warn in warnings:
                print(f"   [{warn.category}] {warn.message}")
                if warn.file:
                    print(f"      File: {warn.file}")

        print("\n" + "-" * 70)
        if errors:
            print("❌ FAILED - Fix errors before proceeding")
        elif warnings:
            print("⚠️  PASSED WITH WARNINGS - Review before proceeding")
        else:
            print("✅ PASSED - All checks OK")


def main():
    """Main entry point."""
    checker = ConsistencyChecker()
    checker.check_all()


if __name__ == "__main__":
    main()
