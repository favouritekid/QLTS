#!/usr/bin/env python3
"""
📊 Repository Pattern Performance Benchmark
============================================
Measures query performance before/after Repository Pattern refactoring.

Usage:
    cd Backend_FastAPI
    python scripts/benchmark_repository.py

Requirements:
    - Database must be running and accessible
    - At least some test data in leads, users, organizations tables
"""

import asyncio
import time
import statistics
from typing import Callable, Any, List, Dict
from contextlib import asynccontextmanager

# Setup path for imports
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app import models
from app.repositories import (
    LeadRepository,
    UserRepository,
    OrganizationRepository,
    ApplicationRepository,
    PipelineRepository,
)


# =============================================================================
# BENCHMARK UTILITIES
# =============================================================================

class BenchmarkResult:
    """Holds benchmark results for a single test."""
    def __init__(self, name: str, times: List[float], query_count: int = 0):
        self.name = name
        self.times = times
        self.query_count = query_count
    
    @property
    def avg_ms(self) -> float:
        return statistics.mean(self.times) * 1000
    
    @property
    def min_ms(self) -> float:
        return min(self.times) * 1000
    
    @property
    def max_ms(self) -> float:
        return max(self.times) * 1000
    
    @property
    def std_dev_ms(self) -> float:
        return statistics.stdev(self.times) * 1000 if len(self.times) > 1 else 0
    
    def __str__(self) -> str:
        return (
            f"{self.name:40s} | "
            f"Avg: {self.avg_ms:7.2f}ms | "
            f"Min: {self.min_ms:7.2f}ms | "
            f"Max: {self.max_ms:7.2f}ms | "
            f"StdDev: {self.std_dev_ms:6.2f}ms"
        )


async def run_benchmark(
    name: str,
    func: Callable,
    iterations: int = 10,
    warmup: int = 2
) -> BenchmarkResult:
    """Run a benchmark function multiple times and collect timing."""
    # Warmup runs (not counted)
    for _ in range(warmup):
        await func()
    
    # Actual benchmark runs
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        await func()
        end = time.perf_counter()
        times.append(end - start)
    
    return BenchmarkResult(name, times)


@asynccontextmanager
async def get_session():
    """Get async database session."""
    async with AsyncSessionLocal() as session:
        yield session


# =============================================================================
# BENCHMARK TESTS - LEAD REPOSITORY
# =============================================================================

async def benchmark_lead_repository():
    """Benchmark LeadRepository methods vs direct queries."""
    print("\n" + "=" * 80)
    print("📊 LEAD REPOSITORY BENCHMARKS")
    print("=" * 80)
    
    results = []
    
    async with get_session() as db:
        repo = LeadRepository(db)
        
        # Get a sample lead ID
        result = await db.execute(select(models.Lead.id).limit(1))
        lead_id = result.scalar()
        
        if not lead_id:
            print("⚠️  No leads found in database. Skipping lead benchmarks.")
            return results
        
        # Benchmark 1: get_by_id_shallow (Repository)
        async def test_repo_shallow():
            await repo.get_by_id_shallow(lead_id)
        
        results.append(await run_benchmark(
            "LeadRepository.get_by_id_shallow",
            test_repo_shallow
        ))
        
        # Benchmark 2: get_by_id_full (Repository)
        async def test_repo_full():
            await repo.get_by_id_full(lead_id)
        
        results.append(await run_benchmark(
            "LeadRepository.get_by_id_full",
            test_repo_full
        ))
        
        # Benchmark 3: Direct query (old pattern)
        async def test_direct_query():
            query = (
                select(models.Lead)
                .options(
                    selectinload(models.Lead.offering),
                    selectinload(models.Lead.unit),
                    selectinload(models.Lead.assigned_officer),
                )
                .where(models.Lead.id == lead_id)
            )
            await db.execute(query)
        
        results.append(await run_benchmark(
            "Direct Query (comparable)",
            test_direct_query
        ))
    
    for r in results:
        print(r)
    
    return results


# =============================================================================
# BENCHMARK TESTS - USER REPOSITORY
# =============================================================================

async def benchmark_user_repository():
    """Benchmark UserRepository methods."""
    print("\n" + "=" * 80)
    print("📊 USER REPOSITORY BENCHMARKS")
    print("=" * 80)
    
    results = []
    
    async with get_session() as db:
        repo = UserRepository(db)
        
        # Benchmark 1: get_filtered (simple list)
        async def test_filtered():
            await repo.get_filtered(limit=50)
        
        results.append(await run_benchmark(
            "UserRepository.get_filtered(50)",
            test_filtered
        ))
        
        # Benchmark 2: search_with_hierarchy
        async def test_hierarchy():
            await repo.search_with_hierarchy(limit=50, include_children=True)
        
        results.append(await run_benchmark(
            "UserRepository.search_with_hierarchy",
            test_hierarchy
        ))
        
        # Benchmark 3: get_all (new hotfix method)
        async def test_get_all():
            await repo.get_all()
        
        results.append(await run_benchmark(
            "UserRepository.get_all",
            test_get_all
        ))
    
    for r in results:
        print(r)
    
    return results


# =============================================================================
# BENCHMARK TESTS - ORGANIZATION REPOSITORY
# =============================================================================

async def benchmark_organization_repository():
    """Benchmark OrganizationRepository methods."""
    print("\n" + "=" * 80)
    print("📊 ORGANIZATION REPOSITORY BENCHMARKS")
    print("=" * 80)
    
    results = []
    
    async with get_session() as db:
        repo = OrganizationRepository(db)
        
        # Get a sample unit ID
        result = await db.execute(select(models.OrganizationUnit.id).limit(1))
        unit_id = result.scalar()
        
        if not unit_id:
            print("⚠️  No organization units found. Skipping org benchmarks.")
            return results
        
        # Benchmark 1: get_by_id_full
        async def test_full():
            await repo.get_by_id_full(unit_id)
        
        results.append(await run_benchmark(
            "OrganizationRepository.get_by_id_full",
            test_full
        ))
        
        # Benchmark 2: get_all (simple list without tree complexity)
        async def test_list():
            await repo.get_all()
        
        results.append(await run_benchmark(
            "OrganizationRepository.get_all",
            test_list
        ))
    
    for r in results:
        print(r)
    
    return results


# =============================================================================
# BENCHMARK TESTS - PIPELINE REPOSITORY
# =============================================================================

async def benchmark_pipeline_repository():
    """Benchmark PipelineRepository methods."""
    print("\n" + "=" * 80)
    print("📊 PIPELINE REPOSITORY BENCHMARKS")
    print("=" * 80)
    
    results = []
    
    async with get_session() as db:
        repo = PipelineRepository(db)
        
        # Benchmark 1: get_all_stages_ordered
        async def test_stages():
            await repo.get_all_stages_ordered()
        
        results.append(await run_benchmark(
            "PipelineRepository.get_all_stages_ordered",
            test_stages
        ))
        
        # Benchmark 2: get_all_statuses
        async def test_statuses():
            await repo.get_all_statuses()
        
        results.append(await run_benchmark(
            "PipelineRepository.get_all_statuses",
            test_statuses
        ))
        
        # Benchmark 3: get_all_transitions_with_statuses
        async def test_transitions():
            await repo.get_all_transitions_with_statuses()
        
        results.append(await run_benchmark(
            "PipelineRepository.get_all_transitions",
            test_transitions
        ))
    
    for r in results:
        print(r)
    
    return results


# =============================================================================
# SUMMARY REPORT
# =============================================================================

def print_summary(all_results: List[BenchmarkResult]):
    """Print summary comparison."""
    print("\n" + "=" * 80)
    print("📈 BENCHMARK SUMMARY")
    print("=" * 80)
    
    if not all_results:
        print("No results to summarize.")
        return
    
    # Sort by average time
    sorted_results = sorted(all_results, key=lambda r: r.avg_ms)
    
    print(f"\n{'Rank':<5} {'Method':<45} {'Avg (ms)':<12}")
    print("-" * 65)
    
    for i, r in enumerate(sorted_results, 1):
        print(f"{i:<5} {r.name:<45} {r.avg_ms:<12.2f}")
    
    # Performance insights
    print("\n📋 INSIGHTS:")
    print("-" * 65)
    
    fastest = sorted_results[0]
    slowest = sorted_results[-1]
    
    print(f"✅ Fastest: {fastest.name} ({fastest.avg_ms:.2f}ms)")
    print(f"⚠️  Slowest: {slowest.name} ({slowest.avg_ms:.2f}ms)")
    
    avg_all = statistics.mean([r.avg_ms for r in all_results])
    print(f"📊 Average across all methods: {avg_all:.2f}ms")


# =============================================================================
# MAIN
# =============================================================================

async def main():
    """Run all benchmarks."""
    print("=" * 80)
    print("🚀 REPOSITORY PATTERN PERFORMANCE BENCHMARK")
    print("=" * 80)
    print(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("Iterations per test: 10 (with 2 warmup runs)")
    
    all_results = []
    
    try:
        # Run all benchmark suites
        all_results.extend(await benchmark_lead_repository())
        all_results.extend(await benchmark_user_repository())
        all_results.extend(await benchmark_organization_repository())
        all_results.extend(await benchmark_pipeline_repository())
        
        # Print summary
        print_summary(all_results)
        
        print("\n" + "=" * 80)
        print("✅ BENCHMARK COMPLETE")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n❌ Benchmark failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
