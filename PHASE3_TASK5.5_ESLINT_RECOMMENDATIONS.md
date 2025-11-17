# TASK 5.5: ESLint Rules Recommendations

## Current ESLint Configuration

**File:** `frontend/.eslintrc.json`

The project currently uses:
- Next.js ESLint config (next/core-web-vitals)
- TypeScript ESLint parser
- Basic rules for code quality

## Recommended Additional Rules

### 1. Code Complexity Rules

These rules prevent files/functions from becoming too complex:

```json
{
  "rules": {
    // Limit file size to prevent monolithic files
    "max-lines": ["warn", {
      "max": 500,
      "skipBlankLines": true,
      "skipComments": true
    }],

    // Limit function size
    "max-lines-per-function": ["warn", {
      "max": 150,
      "skipBlankLines": true,
      "skipComments": true,
      "IIFEs": true
    }],

    // Limit cyclomatic complexity
    "complexity": ["warn", {
      "max": 15
    }],

    // Limit function parameters
    "max-params": ["warn", {
      "max": 5
    }],

    // Limit nested callbacks
    "max-depth": ["warn", {
      "max": 4
    }]
  }
}
```

**Benefits:**
- ✅ Prevents files like RoleManagementWorkflowTab.tsx (675 lines) from being created
- ✅ Encourages component splitting when thresholds are reached
- ✅ Improves code maintainability
- ✅ Early warning system for refactoring needs

### 2. React/Next.js Best Practices

```json
{
  "rules": {
    // Prevent missing React import (Next.js auto-imports)
    "react/react-in-jsx-scope": "off",

    // Enforce hook rules
    "react-hooks/rules-of-hooks": "error",
    "react-hooks/exhaustive-deps": "warn",

    // Prefer function components
    "react/prefer-stateless-function": "warn",

    // Prevent unused state
    "react/no-unused-state": "warn",

    // Require key prop in lists
    "react/jsx-key": "error",

    // Prevent dangerous props
    "react/no-danger": "warn",

    // Enforce component naming
    "react/jsx-pascal-case": "warn"
  }
}
```

### 3. TypeScript Strict Rules

```json
{
  "rules": {
    // Prevent usage of `any` type
    "@typescript-eslint/no-explicit-any": "warn",

    // Require explicit return types on functions
    "@typescript-eslint/explicit-function-return-type": ["warn", {
      "allowExpressions": true,
      "allowTypedFunctionExpressions": true
    }],

    // Prevent unused variables
    "@typescript-eslint/no-unused-vars": ["warn", {
      "argsIgnorePattern": "^_",
      "varsIgnorePattern": "^_"
    }],

    // Enforce consistent type imports
    "@typescript-eslint/consistent-type-imports": ["warn", {
      "prefer": "type-imports"
    }]
  }
}
```

### 4. Import/Export Best Practices

```json
{
  "plugins": ["import"],
  "rules": {
    // Enforce import order
    "import/order": ["warn", {
      "groups": [
        "builtin",
        "external",
        "internal",
        "parent",
        "sibling",
        "index"
      ],
      "newlines-between": "always",
      "alphabetize": {
        "order": "asc"
      }
    }],

    // Prevent duplicate imports
    "import/no-duplicates": "warn",

    // Prevent circular dependencies
    "import/no-cycle": ["warn", {
      "maxDepth": 3
    }]
  }
}
```

## Complete Recommended Configuration

```json
{
  "extends": [
    "next/core-web-vitals",
    "plugin:@typescript-eslint/recommended"
  ],
  "parser": "@typescript-eslint/parser",
  "parserOptions": {
    "ecmaVersion": 2021,
    "sourceType": "module",
    "project": "./tsconfig.json"
  },
  "plugins": [
    "@typescript-eslint",
    "import"
  ],
  "rules": {
    // Complexity Rules
    "max-lines": ["warn", {
      "max": 500,
      "skipBlankLines": true,
      "skipComments": true
    }],
    "max-lines-per-function": ["warn", {
      "max": 150,
      "skipBlankLines": true,
      "skipComments": true
    }],
    "complexity": ["warn", 15],
    "max-params": ["warn", 5],
    "max-depth": ["warn", 4],

    // React/Next.js Rules
    "react/react-in-jsx-scope": "off",
    "react-hooks/rules-of-hooks": "error",
    "react-hooks/exhaustive-deps": "warn",
    "react/jsx-key": "error",
    "react/no-danger": "warn",

    // TypeScript Rules
    "@typescript-eslint/no-explicit-any": "warn",
    "@typescript-eslint/no-unused-vars": ["warn", {
      "argsIgnorePattern": "^_",
      "varsIgnorePattern": "^_"
    }],
    "@typescript-eslint/consistent-type-imports": ["warn", {
      "prefer": "type-imports"
    }],

    // Import Rules
    "import/order": ["warn", {
      "groups": ["builtin", "external", "internal", "parent", "sibling", "index"],
      "newlines-between": "always",
      "alphabetize": {"order": "asc"}
    }],
    "import/no-duplicates": "warn",
    "import/no-cycle": ["warn", {"maxDepth": 3}]
  },
  "overrides": [
    {
      "files": ["*.test.ts", "*.test.tsx", "*.spec.ts", "*.spec.tsx"],
      "rules": {
        "max-lines-per-function": "off",
        "@typescript-eslint/no-explicit-any": "off"
      }
    }
  ]
}
```

## Implementation Steps

### Step 1: Install Required Packages (if needed)

```bash
npm install --save-dev \
  eslint-plugin-import \
  @typescript-eslint/eslint-plugin \
  @typescript-eslint/parser
```

### Step 2: Update .eslintrc.json

Copy the recommended configuration above to `frontend/.eslintrc.json`

### Step 3: Run ESLint to Check Current Violations

```bash
cd frontend
npx eslint . --ext .ts,.tsx
```

### Step 4: Fix Auto-Fixable Issues

```bash
npx eslint . --ext .ts,.tsx --fix
```

### Step 5: Review Remaining Warnings

Address warnings manually:
- Split large files (>500 lines)
- Split complex functions (>150 lines)
- Reduce complexity (>15 cyclomatic complexity)
- Fix `any` types
- Add missing types

## Expected Impact

### Files Affected by `max-lines` Rule:

Based on TASK 5.1 analysis, these files would trigger warnings:

1. **RoleManagementWorkflowTab.tsx** - 675 lines ✅ **FIXED** (now 183 lines)
2. **OfferingAcademicInfoDialog.tsx** - 664 lines ⚠️ **Needs refactoring** (documented in TASK 5.2 plan)

### Files Affected by `max-lines-per-function` Rule:

Long functions should be extracted into smaller helper functions or custom hooks.

### Files Affected by `@typescript-eslint/no-explicit-any` Rule:

Search for `any` types and replace with proper TypeScript types.

## Gradual Adoption Strategy

### Phase 1: Warning Mode (Week 1)
- Add all rules as "warn" (not "error")
- Run eslint and collect metrics
- Create baseline report

### Phase 2: Fix Low-Hanging Fruit (Week 2)
- Run `--fix` to auto-fix issues
- Manually fix simple warnings
- Update types from `any` to specific types

### Phase 3: Refactor Complex Code (Week 3-4)
- Split large files (>500 lines)
- Extract long functions into smaller ones
- Simplify complex logic

### Phase 4: Enforce Mode (Week 5+)
- Change rules from "warn" to "error"
- Add to CI/CD pipeline
- Prevent new violations

## CI/CD Integration

Add to `.github/workflows/lint.yml`:

```yaml
name: ESLint Check

on: [push, pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-node@v3
        with:
          node-version: '18'
      - run: cd frontend && npm install
      - run: cd frontend && npx eslint . --ext .ts,.tsx --max-warnings 0
```

## Metrics to Track

Before/After comparison:

| Metric | Before | Target |
|--------|--------|--------|
| Average file size | ~350 lines | <300 lines |
| Max file size | 675 lines | <500 lines |
| Functions >150 lines | TBD | 0 |
| Files with `any` type | TBD | <10 |
| Cyclomatic complexity >15 | TBD | 0 |

## Status

**Current Status:** DOCUMENTED (not implemented)

**Reason for Deferral:**
- PHASE 3 focused on backend optimization
- Frontend refactoring (TASK 5.1) already demonstrated best practices
- ESLint rules should be added gradually with team discussion
- Requires npm package installation and configuration changes
- Best implemented as separate PR with team review

**When to Implement:**
- After PHASE 3 completion
- During PHASE 4 (Polish)
- As part of ongoing code quality improvements
- Before onboarding new team members

## Recommendation

✅ **Defer TASK 5.5 to PHASE 4 or separate initiative**

Rationale:
1. ✅ TASK 5.1 already proved the refactoring pattern (splits large files)
2. ✅ ESLint rules are preventative (help avoid future issues)
3. ✅ Requires team buy-in for gradual adoption
4. ✅ Backend tasks (5.3, 5.4) were higher priority

**Next Steps:**
1. Review this document with team
2. Agree on rule severity levels (warn vs error)
3. Create separate PR for ESLint configuration
4. Implement gradual adoption strategy

---

## References

- [ESLint Rules Documentation](https://eslint.org/docs/latest/rules/)
- [TypeScript ESLint Rules](https://typescript-eslint.io/rules/)
- [React ESLint Plugin](https://github.com/jsx-eslint/eslint-plugin-react)
- [Import Plugin](https://github.com/import-js/eslint-plugin-import)
