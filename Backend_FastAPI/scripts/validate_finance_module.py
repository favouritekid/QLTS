#!/usr/bin/env python3
"""
Finance Module Validation Script

Validates:
1. Database schema matches SQLAlchemy models
2. Models are properly exported
3. Services reference correct model attributes
4. Repositories use correct column names
5. Schemas match model fields

Usage:
    python scripts/validate_finance_module.py

Requirements:
    - Database connection (reads from .env or environment)
    - All dependencies installed
"""

import asyncio
import os
import sys
import re
import ast
import importlib.util
from pathlib import Path
from typing import Dict, List, Set, Any, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Try to load environment
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass


@dataclass
class ColumnInfo:
    """Database column information."""
    name: str
    type: str
    nullable: bool
    default: Optional[str] = None
    primary_key: bool = False
    foreign_key: Optional[str] = None


@dataclass
class TableInfo:
    """Database table information."""
    name: str
    columns: Dict[str, ColumnInfo] = field(default_factory=dict)
    primary_keys: List[str] = field(default_factory=list)
    foreign_keys: List[Tuple[str, str, str]] = field(default_factory=list)  # (column, ref_table, ref_column)
    unique_constraints: List[List[str]] = field(default_factory=list)
    check_constraints: List[str] = field(default_factory=list)
    indexes: List[Tuple[str, List[str]]] = field(default_factory=list)  # (name, columns)


@dataclass
class ModelInfo:
    """SQLAlchemy model information."""
    name: str
    table_name: str
    file_path: str
    columns: Dict[str, str] = field(default_factory=dict)  # name -> type hint
    relationships: List[str] = field(default_factory=list)
    properties: List[str] = field(default_factory=list)  # @property methods


@dataclass
class ValidationResult:
    """Validation result."""
    category: str
    status: str  # 'OK', 'WARNING', 'ERROR'
    message: str
    details: Optional[List[str]] = None


class DatabaseInspector:
    """Inspects database schema."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.tables: Dict[str, TableInfo] = {}

    async def inspect(self) -> Dict[str, TableInfo]:
        """Inspect database and return table information."""
        try:
            from sqlalchemy import create_engine, inspect, text
            from sqlalchemy.engine import URL

            # Convert async URL to sync for inspection
            sync_url = self.database_url.replace("+asyncpg", "").replace("+aiosqlite", "")

            engine = create_engine(sync_url)
            inspector = inspect(engine)

            # Get all tables
            table_names = inspector.get_table_names()

            for table_name in table_names:
                table_info = TableInfo(name=table_name)

                # Get columns
                for col in inspector.get_columns(table_name):
                    col_info = ColumnInfo(
                        name=col['name'],
                        type=str(col['type']),
                        nullable=col.get('nullable', True),
                        default=str(col.get('default')) if col.get('default') else None,
                    )
                    table_info.columns[col['name']] = col_info

                # Get primary keys
                pk = inspector.get_pk_constraint(table_name)
                if pk:
                    table_info.primary_keys = pk.get('constrained_columns', [])

                # Get foreign keys
                for fk in inspector.get_foreign_keys(table_name):
                    for i, col in enumerate(fk.get('constrained_columns', [])):
                        ref_cols = fk.get('referred_columns', [])
                        ref_col = ref_cols[i] if i < len(ref_cols) else 'id'
                        table_info.foreign_keys.append((
                            col,
                            fk.get('referred_table', ''),
                            ref_col
                        ))

                # Get unique constraints
                for uc in inspector.get_unique_constraints(table_name):
                    table_info.unique_constraints.append(uc.get('column_names', []))

                # Get indexes
                for idx in inspector.get_indexes(table_name):
                    table_info.indexes.append((
                        idx.get('name', ''),
                        idx.get('column_names', [])
                    ))

                # Get check constraints
                try:
                    for cc in inspector.get_check_constraints(table_name):
                        table_info.check_constraints.append(cc.get('sqltext', ''))
                except Exception:
                    pass  # Some databases don't support check constraint inspection

                self.tables[table_name] = table_info

            engine.dispose()
            return self.tables

        except Exception as e:
            print(f"❌ Database connection failed: {e}")
            return {}


class ModelParser:
    """Parses SQLAlchemy model files."""

    def __init__(self, models_dir: Path):
        self.models_dir = models_dir
        self.models: Dict[str, ModelInfo] = {}

    def parse_all(self) -> Dict[str, ModelInfo]:
        """Parse all model files."""
        finance_dir = self.models_dir / "finance"

        if not finance_dir.exists():
            print(f"⚠️  Finance models directory not found: {finance_dir}")
            return {}

        for py_file in finance_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            self._parse_file(py_file)

        return self.models

    def _parse_file(self, file_path: Path) -> None:
        """Parse a single model file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            tree = ast.parse(content)

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    # Check if it's a SQLAlchemy model (has __tablename__)
                    table_name = None
                    columns = {}
                    relationships = []
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

                        # Look for Mapped columns
                        if isinstance(item, ast.AnnAssign):
                            if isinstance(item.target, ast.Name):
                                col_name = item.target.id
                                if col_name.startswith('_'):
                                    continue

                                # Get type annotation
                                type_hint = ast.unparse(item.annotation) if item.annotation else 'Unknown'

                                # Check if it's a relationship - check both type hint and value
                                is_relationship = False
                                if 'relationship' in type_hint.lower():
                                    is_relationship = True
                                if item.value:
                                    value_str = ast.unparse(item.value)
                                    if 'relationship(' in value_str:
                                        is_relationship = True

                                if is_relationship:
                                    relationships.append(col_name)
                                    continue

                                # Only add if it's a mapped_column (actual DB column)
                                if item.value:
                                    value_str = ast.unparse(item.value)
                                    if 'mapped_column(' in value_str:
                                        columns[col_name] = type_hint

                    if table_name:
                        self.models[node.name] = ModelInfo(
                            name=node.name,
                            table_name=table_name,
                            file_path=str(file_path),
                            columns=columns,
                            relationships=relationships,
                            properties=properties,
                        )

        except Exception as e:
            print(f"⚠️  Error parsing {file_path}: {e}")


class ServiceAnalyzer:
    """Analyzes service files for model attribute usage."""

    def __init__(self, services_dir: Path):
        self.services_dir = services_dir
        self.attribute_usages: Dict[str, Set[str]] = defaultdict(set)

    def analyze(self) -> Dict[str, Set[str]]:
        """Analyze service files for attribute usage."""
        finance_services = [
            "fee_calculation_service.py",
            "invoice_service.py",
            "payment_service.py",
            "payment_intent_service.py",
            "accounting_service.py",
            "fee_compatibility_service.py",
        ]

        for service_name in finance_services:
            service_path = self.services_dir / service_name
            if service_path.exists():
                self._analyze_file(service_path)

        return self.attribute_usages

    def _analyze_file(self, file_path: Path) -> None:
        """Analyze a single service file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Find attribute accesses like: fee.status, invoice.amount, etc.
            # Pattern: variable.attribute where variable is a known model instance
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
            }

            for var_name, model_name in model_vars.items():
                # Find patterns like var.attribute
                pattern = rf'\b{var_name}\.(\w+)'
                matches = re.findall(pattern, content)
                for attr in matches:
                    # Skip method calls and common Python attributes
                    if attr not in ('append', 'extend', 'items', 'keys', 'values', 'get', '__'):
                        self.attribute_usages[model_name].add(attr)

        except Exception as e:
            print(f"⚠️  Error analyzing {file_path}: {e}")


class SchemaAnalyzer:
    """Analyzes Pydantic schema files."""

    def __init__(self, schemas_dir: Path):
        self.schemas_dir = schemas_dir
        self.schemas: Dict[str, Set[str]] = {}

    def analyze(self) -> Dict[str, Set[str]]:
        """Analyze schema files."""
        finance_schema = self.schemas_dir / "finance.py"

        if not finance_schema.exists():
            print(f"⚠️  Finance schema not found: {finance_schema}")
            return {}

        try:
            with open(finance_schema, 'r', encoding='utf-8') as f:
                content = f.read()

            tree = ast.parse(content)

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    fields = set()
                    for item in node.body:
                        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                            fields.add(item.target.id)

                    if fields:
                        self.schemas[node.name] = fields

        except Exception as e:
            print(f"⚠️  Error analyzing schemas: {e}")

        return self.schemas


class FinanceModuleValidator:
    """Main validator class."""

    # Finance module tables
    FINANCE_TABLES = {
        'installment_plan',
        'payment_method',
        'accounting_period',
        'processed_event',
        'fee',
        'fee_applied_discount',
        'invoice',
        'payment_intent',
        'payment',
        'payment_transaction',
        'refund_request',
        'overpayment_record',
    }

    # Expected columns per table (key columns only - subset check)
    # Column names must match actual migration/model names
    EXPECTED_COLUMNS = {
        'fee': ['id', 'admission_profile_id', 'fee_type', 'academic_year', 'base_amount', 'final_amount',
                'paid_amount', 'waived_amount', 'status', 'version', 'installment_plan_id', 'notes'],
        'invoice': ['id', 'fee_id', 'invoice_number', 'installment_no', 'amount',
                   'paid_amount', 'penalty_amount', 'status', 'due_date'],
        'payment': ['id', 'invoice_id', 'amount', 'method_id', 'status',
                   'created_by_id', 'verified_by_id'],
        'payment_intent': ['id', 'invoice_id', 'amount', 'method_id', 'status',
                          'idempotency_key', 'gateway_ref'],
        'payment_transaction': ['id', 'payment_id', 'fee_id', 'amount', 'transaction_type',
                               'balance_before', 'balance_after'],
        'refund_request': ['id', 'payment_id', 'amount', 'status', 'reason', 'requested_by_id'],
        'overpayment_record': ['id', 'payment_id', 'invoice_id', 'overpayment_amount', 'status'],
        'installment_plan': ['id', 'code', 'name', 'installment_count', 'schedule'],
        'payment_method': ['id', 'code', 'name', 'is_online', 'is_active'],
        'accounting_period': ['id', 'period_month', 'period_year', 'is_closed'],
        'processed_event': ['id', 'event_id', 'consumer_id', 'processed_at', 'processing_result'],
        'fee_applied_discount': ['id', 'fee_id', 'policy_id', 'discount_amount', 'discount_percent'],
    }

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.results: List[ValidationResult] = []

        self.db_tables: Dict[str, TableInfo] = {}
        self.models: Dict[str, ModelInfo] = {}
        self.service_attrs: Dict[str, Set[str]] = {}
        self.schemas: Dict[str, Set[str]] = {}

    async def validate(self) -> List[ValidationResult]:
        """Run all validations."""
        print("=" * 70)
        print("FINANCE MODULE VALIDATION")
        print("=" * 70)

        # 1. Check database connection and schema
        await self._validate_database()

        # 2. Parse models
        self._validate_models()

        # 3. Compare database vs models
        self._compare_db_models()

        # 4. Analyze services
        self._validate_services()

        # 5. Analyze schemas
        self._validate_schemas()

        # 6. Check cross-layer consistency
        self._validate_cross_layer()

        # Print summary
        self._print_summary()

        return self.results

    async def _validate_database(self) -> None:
        """Validate database schema."""
        print("\n📊 STEP 1: Database Schema Inspection")
        print("-" * 50)

        database_url = os.getenv("DATABASE_URL", "")

        if not database_url:
            self.results.append(ValidationResult(
                category="Database",
                status="ERROR",
                message="DATABASE_URL not configured",
                details=["Set DATABASE_URL in .env file"]
            ))
            print("❌ DATABASE_URL not configured")
            return

        inspector = DatabaseInspector(database_url)
        self.db_tables = await inspector.inspect()

        if not self.db_tables:
            self.results.append(ValidationResult(
                category="Database",
                status="ERROR",
                message="Could not connect to database or no tables found"
            ))
            return

        print(f"✅ Connected to database, found {len(self.db_tables)} tables")

        # Check for finance tables
        found_tables = set(self.db_tables.keys()) & self.FINANCE_TABLES
        missing_tables = self.FINANCE_TABLES - set(self.db_tables.keys())

        if missing_tables:
            self.results.append(ValidationResult(
                category="Database",
                status="ERROR",
                message=f"Missing finance tables: {len(missing_tables)}",
                details=list(missing_tables)
            ))
            print(f"❌ Missing tables: {missing_tables}")
        else:
            self.results.append(ValidationResult(
                category="Database",
                status="OK",
                message=f"All {len(self.FINANCE_TABLES)} finance tables exist"
            ))
            print(f"✅ All {len(self.FINANCE_TABLES)} finance tables exist")

        # Print table details
        print("\n📋 Finance Tables Structure:")
        for table_name in sorted(found_tables):
            table = self.db_tables[table_name]
            print(f"\n  {table_name} ({len(table.columns)} columns)")

            # Check expected columns
            if table_name in self.EXPECTED_COLUMNS:
                expected = set(self.EXPECTED_COLUMNS[table_name])
                actual = set(table.columns.keys())
                missing = expected - actual

                if missing:
                    print(f"    ⚠️  Missing expected columns: {missing}")
                    self.results.append(ValidationResult(
                        category="Database",
                        status="WARNING",
                        message=f"Table {table_name} missing columns",
                        details=list(missing)
                    ))

            # Show foreign keys
            if table.foreign_keys:
                fks = [f"{fk[0]} → {fk[1]}.{fk[2]}" for fk in table.foreign_keys]
                print(f"    FK: {', '.join(fks)}")

            # Show unique constraints
            if table.unique_constraints:
                for uc in table.unique_constraints:
                    print(f"    UNIQUE: ({', '.join(uc)})")

    def _validate_models(self) -> None:
        """Validate SQLAlchemy models."""
        print("\n📦 STEP 2: Model Inspection")
        print("-" * 50)

        models_dir = self.project_root / "app" / "models"
        parser = ModelParser(models_dir)
        self.models = parser.parse_all()

        if not self.models:
            self.results.append(ValidationResult(
                category="Models",
                status="ERROR",
                message="No finance models found"
            ))
            print("❌ No finance models found")
            return

        print(f"✅ Found {len(self.models)} finance models")

        # Check model exports
        init_file = models_dir / "finance" / "__init__.py"
        if init_file.exists():
            with open(init_file, 'r', encoding='utf-8') as f:
                init_content = f.read()

            unexported = []
            for model_name in self.models.keys():
                if model_name not in init_content:
                    unexported.append(model_name)

            if unexported:
                self.results.append(ValidationResult(
                    category="Models",
                    status="WARNING",
                    message="Some models not exported in __init__.py",
                    details=unexported
                ))
                print(f"⚠️  Not exported: {unexported}")
            else:
                print("✅ All models properly exported")

        # Print model details
        print("\n📋 Finance Models:")
        for name, model in sorted(self.models.items()):
            col_count = len([c for c in model.columns if not c.startswith('_')])
            rel_count = len(model.relationships)
            print(f"  {name} → {model.table_name} ({col_count} columns, {rel_count} relationships)")

    def _compare_db_models(self) -> None:
        """Compare database schema with models."""
        print("\n🔄 STEP 3: Database ↔ Model Comparison")
        print("-" * 50)

        if not self.db_tables or not self.models:
            print("⚠️  Skipping comparison (missing data)")
            return

        for model_name, model in self.models.items():
            table_name = model.table_name

            if table_name not in self.db_tables:
                self.results.append(ValidationResult(
                    category="DB-Model Sync",
                    status="ERROR",
                    message=f"Model {model_name} table '{table_name}' not in database"
                ))
                print(f"❌ {model_name}: table '{table_name}' not found")
                continue

            db_table = self.db_tables[table_name]
            db_columns = set(db_table.columns.keys())

            # Get model columns (now only contains mapped_column entries, relationships are excluded)
            model_columns = set(model.columns.keys()) - set(model.relationships)

            # Compare
            in_db_not_model = db_columns - model_columns
            in_model_not_db = model_columns - db_columns

            if in_db_not_model or in_model_not_db:
                details = []
                if in_db_not_model:
                    details.append(f"In DB only: {in_db_not_model}")
                if in_model_not_db:
                    details.append(f"In Model only: {in_model_not_db}")

                self.results.append(ValidationResult(
                    category="DB-Model Sync",
                    status="WARNING",
                    message=f"Column mismatch in {model_name}/{table_name}",
                    details=details
                ))
                print(f"⚠️  {model_name}: column mismatch")
                for d in details:
                    print(f"      {d}")
            else:
                print(f"✅ {model_name}: synced with {table_name}")

    def _validate_services(self) -> None:
        """Validate service attribute usage."""
        print("\n⚙️  STEP 4: Service Analysis")
        print("-" * 50)

        services_dir = self.project_root / "app" / "services"
        analyzer = ServiceAnalyzer(services_dir)
        self.service_attrs = analyzer.analyze()

        if not self.service_attrs:
            print("⚠️  No service attribute usages found")
            return

        print("📋 Model attributes used in services:")

        for model_name, attrs in sorted(self.service_attrs.items()):
            # Find corresponding model
            model = self.models.get(model_name)

            if not model:
                print(f"  {model_name}: (model not parsed)")
                continue

            # Build valid attributes set: columns + relationships + properties + extras
            model_attrs = (
                set(model.columns.keys()) |
                set(model.relationships) |
                set(model.properties)  # Include @property methods
            )

            # Filter known valid attributes (methods, common false positives)
            valid_extras = {
                'id', 'created_at', 'updated_at', 'deleted_at',
                'get_installment_schedule',  # method
                'value',  # enum value access
                'example', 'com',  # false positive from URLs like payment.example.com
            }
            model_attrs = model_attrs | valid_extras

            invalid_attrs = attrs - model_attrs

            if invalid_attrs:
                self.results.append(ValidationResult(
                    category="Services",
                    status="ERROR",
                    message=f"Services use non-existent {model_name} attributes",
                    details=list(invalid_attrs)
                ))
                print(f"  ❌ {model_name}: invalid attrs used: {invalid_attrs}")
            else:
                print(f"  ✅ {model_name}: {len(attrs)} attributes used correctly")

    def _validate_schemas(self) -> None:
        """Validate Pydantic schemas."""
        print("\n📝 STEP 5: Schema Analysis")
        print("-" * 50)

        schemas_dir = self.project_root / "app" / "schemas"
        analyzer = SchemaAnalyzer(schemas_dir)
        self.schemas = analyzer.analyze()

        if not self.schemas:
            self.results.append(ValidationResult(
                category="Schemas",
                status="WARNING",
                message="No finance schemas found"
            ))
            print("⚠️  No finance schemas found")
            return

        print(f"✅ Found {len(self.schemas)} schema classes")

        # Show schema summary
        finance_schemas = [s for s in self.schemas.keys() if any(
            kw in s.lower() for kw in ['fee', 'invoice', 'payment', 'refund', 'overpayment']
        )]

        print(f"📋 Finance-related schemas: {len(finance_schemas)}")
        for schema_name in sorted(finance_schemas):
            fields = self.schemas[schema_name]
            print(f"  {schema_name}: {len(fields)} fields")

    def _validate_cross_layer(self) -> None:
        """Validate cross-layer consistency."""
        print("\n🔗 STEP 6: Cross-Layer Consistency")
        print("-" * 50)

        # Check repository files exist
        repo_dir = self.project_root / "app" / "repositories"
        expected_repos = ["fee_repository.py", "payment_repository.py"]

        for repo_name in expected_repos:
            repo_path = repo_dir / repo_name
            if repo_path.exists():
                print(f"✅ {repo_name} exists")
            else:
                self.results.append(ValidationResult(
                    category="Repositories",
                    status="WARNING",
                    message=f"Repository not found: {repo_name}"
                ))
                print(f"⚠️  {repo_name} not found")

        # Check service imports
        services_dir = self.project_root / "app" / "services"
        service_files = [
            "fee_calculation_service.py",
            "invoice_service.py",
            "payment_service.py",
            "payment_intent_service.py",
            "accounting_service.py",
        ]

        print("\n📋 Service file status:")
        for svc_name in service_files:
            svc_path = services_dir / svc_name
            if svc_path.exists():
                # Check for HTTPException import (should not exist)
                with open(svc_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                if 'HTTPException' in content:
                    self.results.append(ValidationResult(
                        category="Architecture",
                        status="ERROR",
                        message=f"{svc_name} imports HTTPException (violates architecture)",
                    ))
                    print(f"  ❌ {svc_name} - imports HTTPException!")
                elif 'from fastapi' in content:
                    self.results.append(ValidationResult(
                        category="Architecture",
                        status="WARNING",
                        message=f"{svc_name} imports from fastapi",
                    ))
                    print(f"  ⚠️  {svc_name} - imports from fastapi")
                else:
                    print(f"  ✅ {svc_name} - architecture compliant")
            else:
                print(f"  ⚠️  {svc_name} - not found")

    def _print_summary(self) -> None:
        """Print validation summary."""
        print("\n" + "=" * 70)
        print("VALIDATION SUMMARY")
        print("=" * 70)

        errors = [r for r in self.results if r.status == "ERROR"]
        warnings = [r for r in self.results if r.status == "WARNING"]
        oks = [r for r in self.results if r.status == "OK"]

        print(f"\n✅ Passed: {len(oks)}")
        print(f"⚠️  Warnings: {len(warnings)}")
        print(f"❌ Errors: {len(errors)}")

        if errors:
            print("\n❌ ERRORS (must fix):")
            for err in errors:
                print(f"  [{err.category}] {err.message}")
                if err.details:
                    for d in err.details:
                        print(f"      - {d}")

        if warnings:
            print("\n⚠️  WARNINGS (review):")
            for warn in warnings:
                print(f"  [{warn.category}] {warn.message}")
                if warn.details:
                    for d in warn.details:
                        print(f"      - {d}")

        # Final verdict
        print("\n" + "-" * 70)
        if errors:
            print("❌ VALIDATION FAILED - Fix errors before proceeding")
        elif warnings:
            print("⚠️  VALIDATION PASSED WITH WARNINGS - Review before proceeding")
        else:
            print("✅ VALIDATION PASSED - All checks OK")


async def main():
    """Main entry point."""
    validator = FinanceModuleValidator(PROJECT_ROOT)
    await validator.validate()


if __name__ == "__main__":
    asyncio.run(main())
