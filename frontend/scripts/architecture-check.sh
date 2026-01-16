#!/usr/bin/env bash
set -e

echo "🔍 Architecture Violation Check (FRONTEND_ARCHITECTURE_V3.md)..."
echo ""

VIOLATIONS=0

# 1. setState trong useEffect (trừ RHF reset)
echo "📋 Check 1: setState in useEffect..."
SETSTATE_VIOLATIONS=$(grep -rn "useEffect.*set[A-Z]" src --include="*.ts" --include="*.tsx" 2>/dev/null | grep -v "form.reset" | grep -v "__tests__" | grep -v ".test." || true)
if [ -n "$SETSTATE_VIOLATIONS" ]; then
  echo "❌ Violation: setState inside useEffect"
  echo "$SETSTATE_VIOLATIONS" | head -10
  VIOLATIONS=$((VIOLATIONS + 1))
else
  echo "✅ No setState in useEffect violations"
fi
echo ""

# 2. eslint-disable
echo "📋 Check 2: eslint-disable comments..."
ESLINT_DISABLE=$(grep -rn "eslint-disable" src --include="*.ts" --include="*.tsx" 2>/dev/null | grep -v "__tests__" | grep -v ".test." || true)
if [ -n "$ESLINT_DISABLE" ]; then
  echo "❌ Violation: eslint-disable found"
  echo "$ESLINT_DISABLE" | head -10
  VIOLATIONS=$((VIOLATIONS + 1))
else
  echo "✅ No eslint-disable violations"
fi
echo ""

# 3. any trong source (cho phép test, loại trừ comments)
echo "📋 Check 3: Explicit 'any' type..."
ANY_VIOLATIONS=$(grep -rn ": any" src --include="*.ts" --include="*.tsx" 2>/dev/null | grep -v "__tests__" | grep -v ".test." | grep -v "// @allow-any" | grep -v "^\s*\*" | grep -v "^\s*//" || true)
if [ -n "$ANY_VIOLATIONS" ]; then
  echo "❌ Violation: explicit 'any' in source"
  echo "$ANY_VIOLATIONS" | head -20
  ANY_COUNT=$(echo "$ANY_VIOLATIONS" | wc -l)
  echo "   ... Total: $ANY_COUNT occurrences"
  VIOLATIONS=$((VIOLATIONS + 1))
else
  echo "✅ No explicit 'any' violations"
fi
echo ""

# 4. Business logic in FE (inferring status)
echo "📋 Check 4: FE business logic inference..."
BUSINESS_LOGIC=$(grep -rn "const is.*= .*status ===" src --include="*.ts" --include="*.tsx" 2>/dev/null | grep -v "__tests__" | grep -v ".test." || true)
if [ -n "$BUSINESS_LOGIC" ]; then
  echo "⚠️ Warning: Potential business state inference"
  echo "$BUSINESS_LOGIC" | head -10
else
  echo "✅ No obvious business logic inference"
fi
echo ""

# 5. Summary
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ $VIOLATIONS -gt 0 ]; then
  echo "❌ FAILED: $VIOLATIONS violation type(s) found"
  exit 1
else
  echo "✅ Architecture check PASSED"
  exit 0
fi
