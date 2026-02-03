/* eslint-disable @typescript-eslint/no-require-imports */
const fs = require('fs');
const path = require('path');

// Configuration
const TARGET_DIR = path.join(__dirname, '../src');
const EXTENSIONS = ['.tsx', '.ts'];
const IGNORE_DIRS = ['node_modules', '.next', 'out', 'dist', 'styles/themes'];

// Files to exclude from scanning (internal components that handle colors safely)
const EXCLUDE_FILES = [
  'dynamic-color-badge.tsx',
  'dynamic-color.ts',
  'useTheme.ts',
];

// Colors to forbid (raw tailwind that don't have semantic CSS variable definitions)
// Note: Colors defined with CSS variables in tailwind.config.ts are theme-aware
// and acceptable to use directly. These are excluded from scanning.
const RAW_COLORS = [
  'red', 'lime', 'green', 'emerald',
  'sky', 'blue', 'fuchsia', 'rose',
  'slate', 'neutral', 'stone'
  // Allowed (defined with CSS variables): purple, cyan, gray, indigo, violet, zinc, amber, orange, yellow, pink, teal
];

// Allowed arbitrary spacing patterns (legitimate uses)
const ALLOWED_ARBITRARY_SPACING = [
  /h-\[1px\]/,        // Divider lines
  /w-\[1px\]/,        // Vertical dividers
  /h-\[2px\]/,        // Thick dividers
  /min-h-\[0\]/,      // Reset min-height
  /top-\[50%\]/,      // Centering
  /left-\[50%\]/,     // Centering
];

// Violation Rules
const RULES = [
  // --- COLOR SYSTEM VIOLATIONS ---
  {
    id: 'hardcoded-white-bg',
    pattern: /className="[^"]*\bbg-white\b[^"]*"/g,
    description: 'Hardcoded white background (breaks dark mode)',
    severity: 'ERROR',
    fix: 'Use bg-card, bg-background, or bg-popover'
  },
  {
    id: 'hardcoded-black-text',
    pattern: /className="[^"]*\btext-black\b[^"]*"/g,
    description: 'Hardcoded black text (breaks dark mode)',
    severity: 'ERROR',
    fix: 'Use text-foreground'
  },
  {
    id: 'arbitrary-bg-hex',
    pattern: /bg-\[#[0-9a-fA-F]{3,6}\]/g,
    description: 'Arbitrary background hex value',
    severity: 'WARNING',
    fix: 'Use design system tokens'
  },
  {
    id: 'arbitrary-text-hex',
    pattern: /text-\[#[0-9a-fA-F]{3,6}\]/g,
    description: 'Arbitrary text hex value',
    severity: 'WARNING',
    fix: 'Use design system tokens'
  },
  {
    id: 'raw-tailwind-color',
    // Matches bg-red-500, text-blue-600, etc. but NOT in dark: variants
    pattern: new RegExp(`(?<!dark:)(bg|text|border|ring)-(${RAW_COLORS.join('|')})-[0-9]{2,3}(?!/)`, 'g'),
    description: 'Raw Tailwind color without semantic token',
    severity: 'ERROR',
    fix: 'Use semantic tokens: primary, secondary, destructive, warning, success, info, muted-foreground, etc.'
  },

  // --- SPACING & LAYOUT VIOLATIONS ---
  {
    id: 'arbitrary-spacing',
    // Matches p-[10px], m-[5px], w-[300px] etc. - but validated against allowed list
    pattern: /(p|m|gap|w|h|min-w|max-w|min-h|max-h|top|left|right|bottom)-\[\d+px\]/g,
    description: 'Arbitrary spacing/sizing value',
    severity: 'WARNING',
    fix: 'Use design system spacing tokens (1 = 4px). For layout: w-48 (192px), w-64 (256px), w-80 (320px)',
    validate: (match) => {
      // Allow certain patterns
      return !ALLOWED_ARBITRARY_SPACING.some(allowed => allowed.test(match));
    }
  },

  // --- ACCESSIBILITY VIOLATIONS ---
  {
    id: 'missing-aria-label-icon-btn',
    // Check for Button with size="icon" that doesn't have aria-label
    // Note: Buttons with asChild pass aria-label to child element, so exclude them
    // Using negative lookahead (?!<Button) to prevent matching across multiple Button tags
    // Using (?<!=)>(?!\s*\d) to not terminate on => (arrow functions) or > 0 (comparisons)
    pattern: /<Button(?:(?!<Button)[\s\S])*?size=["']icon["'](?:(?!<Button)[\s\S])*?(?<!=)>(?!\s*\d)/g,
    description: 'Icon button missing aria-label',
    severity: 'ERROR',
    fix: 'Add aria-label="Action Name" for screen readers',
    validate: (match) => {
      // Skip if has aria-label
      if (/aria-label=/.test(match)) return false;
      // Skip if has asChild (aria-label should be on child element)
      if (/asChild/.test(match)) return false;
      // Skip if has title (provides accessible name)
      if (/\btitle=/.test(match)) return false;
      return true;
    }
  },
  {
    id: 'remove-outline-no-focus',
    // Only flag outline-none when not followed by focus-visible in same className
    pattern: /className="[^"]*outline-none(?![^"]*focus-visible)[^"]*"/g,
    description: 'Removed outline without focus-visible replacement',
    severity: 'ERROR',
    fix: 'Add focus-visible:ring-2 focus-visible:ring-ring'
  },

  // --- PATTERN VIOLATIONS ---
  {
    id: 'no-hardcoded-gray-text',
    pattern: /\btext-gray-(400|500)\b/g,
    description: 'Low contrast gray text',
    severity: 'WARNING',
    fix: 'Use text-muted-foreground for proper contrast in both themes'
  }
];

// Special rule: inline backgroundColor styles (needs context check)
const INLINE_STYLE_RULE = {
  id: 'dynamic-style-bg',
  pattern: /style=\{\{[^}]*backgroundColor[^}]*\}\}/g,
  description: 'Inline dynamic background color',
  severity: 'INFO',
  fix: 'Consider using <DynamicColorBadge /> for status colors, or document exception'
};

// Helper to walk directory
function walkSync(dir, filelist = []) {
  if (!fs.existsSync(dir)) return filelist;

  const files = fs.readdirSync(dir);
  files.forEach(file => {
    const filepath = path.join(dir, file);
    const stat = fs.statSync(filepath);

    if (stat.isDirectory()) {
      if (!IGNORE_DIRS.includes(file)) {
        filelist = walkSync(filepath, filelist);
      }
    } else {
      if (EXTENSIONS.includes(path.extname(file))) {
        // Skip excluded files
        if (!EXCLUDE_FILES.includes(file)) {
          filelist.push(filepath);
        }
      }
    }
  });
  return filelist;
}

// Helper to check if match is inside a comment or string that should be ignored
function shouldIgnoreMatch(content, matchIndex, match) {
  // Check if inside a code comment (// or /* */)
  const beforeMatch = content.substring(Math.max(0, matchIndex - 100), matchIndex);
  if (beforeMatch.includes('//') && !beforeMatch.includes('\n')) {
    return true; // Single line comment
  }
  // Check if it's in a constant/config definition (likely intentional)
  if (/const\s+\w+\s*=\s*["']/.test(beforeMatch.slice(-50))) {
    return true;
  }
  return false;
}

// Main execution
console.log('🔍 Starting Strict UI Violation Scan...');
console.log('Validating against DESIGN_SYSTEM.md & dynamic-color-system.md...\n');
console.log(`Target: ${TARGET_DIR}`);
console.log(`Excluded files: ${EXCLUDE_FILES.join(', ')}\n`);

const files = walkSync(TARGET_DIR);
let totalViolations = 0;
let errorCount = 0;
let warningCount = 0;
let infoCount = 0;
let filesWithViolations = 0;

files.forEach(file => {
  const content = fs.readFileSync(file, 'utf8');
  const relativePath = path.relative(path.join(__dirname, '..'), file);
  let fileViolations = [];

  // Check main rules
  RULES.forEach(rule => {
    // Reset regex lastIndex if global
    rule.pattern.lastIndex = 0;

    let match;
    while ((match = rule.pattern.exec(content)) !== null) {
      const matchStr = match[0];
      const matchIndex = match.index;

      // Skip if should be ignored
      if (shouldIgnoreMatch(content, matchIndex, matchStr)) {
        continue;
      }

      // Run custom validation if exists
      if (rule.validate && !rule.validate(matchStr)) {
        continue;
      }

      // Find line number
      const lines = content.substring(0, matchIndex).split('\n');
      const lineNum = lines.length;

      fileViolations.push({
        ruleId: rule.id,
        match: matchStr.length > 60 ? matchStr.substring(0, 60) + '...' : matchStr,
        line: lineNum,
        description: rule.description,
        severity: rule.severity,
        fix: rule.fix
      });
    }
  });

  // Check inline style rule separately (INFO level, less strict)
  INLINE_STYLE_RULE.pattern.lastIndex = 0;
  let styleMatch;
  while ((styleMatch = INLINE_STYLE_RULE.pattern.exec(content)) !== null) {
    // Only report if NOT in a component that's already using DynamicColorBadge
    if (!content.includes('DynamicColorBadge') && !content.includes('ColorDot')) {
      const lines = content.substring(0, styleMatch.index).split('\n');
      fileViolations.push({
        ruleId: INLINE_STYLE_RULE.id,
        match: styleMatch[0].length > 60 ? styleMatch[0].substring(0, 60) + '...' : styleMatch[0],
        line: lines.length,
        description: INLINE_STYLE_RULE.description,
        severity: INLINE_STYLE_RULE.severity,
        fix: INLINE_STYLE_RULE.fix
      });
    }
  }

  // Deduplicate violations (same line, same rule)
  const seen = new Set();
  fileViolations = fileViolations.filter(v => {
    const key = `${v.ruleId}:${v.line}:${v.match}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  if (fileViolations.length > 0) {
    filesWithViolations++;
    totalViolations += fileViolations.length;

    console.log(`📄 ${relativePath}`);
    fileViolations.forEach(v => {
      if (v.severity === 'ERROR') errorCount++;
      else if (v.severity === 'WARNING') warningCount++;
      else infoCount++;

      const color = v.severity === 'ERROR' ? '\x1b[31m' : (v.severity === 'WARNING' ? '\x1b[33m' : '\x1b[36m');
      const reset = '\x1b[0m';
      console.log(`  ${color}[${v.severity}]${reset} Line ${v.line}: ${v.match}`);
      console.log(`    → ${v.description}`);
      console.log(`    💡 ${v.fix}`);
    });
    console.log('');
  }
});

console.log('══════════════════════════════════════════════════');
console.log('📊 SCAN SUMMARY');
console.log('══════════════════════════════════════════════════');
console.log(`Files scanned:        ${files.length}`);
console.log(`Files with issues:    ${filesWithViolations}`);
console.log('──────────────────────────────────────────────────');
console.log(`\x1b[31m❌ ERRORS:   ${errorCount}\x1b[0m ${errorCount > 0 ? '(must fix)' : ''}`);
console.log(`\x1b[33m⚠️  WARNINGS: ${warningCount}\x1b[0m ${warningCount > 0 ? '(should fix)' : ''}`);
console.log(`\x1b[36mℹ️  INFO:     ${infoCount}\x1b[0m ${infoCount > 0 ? '(review)' : ''}`);
console.log('──────────────────────────────────────────────────');
console.log(`TOTAL:                ${totalViolations}`);
console.log('══════════════════════════════════════════════════');

// Exit with error only if there are ERROR-level violations
if (errorCount > 0) {
  console.log('\n❌ Build would fail due to ERROR violations.');
  process.exit(1);
} else if (warningCount > 0) {
  console.log('\n⚠️  Warnings found. Consider fixing for better code quality.');
  process.exit(0);
} else {
  console.log('\n✅ All checks passed!');
  process.exit(0);
}
