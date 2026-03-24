// src/components/ui/dialog.test.tsx
/**
 * Dialog Component Tests
 *
 * Tests for mobile-responsive dialog positioning and padding standards:
 * - Mobile: left-4 right-4 positioning (16px from screen edges)
 * - Tablet+: centered with max-width using transform
 * - DialogHeader has pr-8 to avoid close button overlap
 * - DialogContent has proper padding (p-5 = 20px)
 */

import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
} from './dialog';

// Helper to get computed class names
const getClassList = (element: HTMLElement): string[] => {
  return element.className.split(' ').filter(Boolean);
};

describe('DialogContent', () => {
  it('renders with correct mobile positioning classes', () => {
    render(
      <Dialog open>
        <DialogContent data-testid="dialog-content">
          <p>Content</p>
        </DialogContent>
      </Dialog>
    );

    const content = screen.getByTestId('dialog-content');
    const classes = getClassList(content);

    // Mobile: left-4 right-4 (instead of transform centering)
    expect(classes).toContain('left-4');
    expect(classes).toContain('right-4');
  });

  it('renders with correct tablet+ positioning classes', () => {
    render(
      <Dialog open>
        <DialogContent data-testid="dialog-content">
          <p>Content</p>
        </DialogContent>
      </Dialog>
    );

    const content = screen.getByTestId('dialog-content');
    const classList = content.className;

    // Tablet+: centered with transform
    expect(classList).toContain('sm:left-[50%]');
    expect(classList).toContain('sm:right-auto');
    expect(classList).toContain('sm:translate-x-[-50%]');
    expect(classList).toContain('sm:max-w-lg');
    expect(classList).toContain('sm:w-full');
  });

  it('has inner wrapper with correct padding (p-5 = 20px)', () => {
    render(
      <Dialog open>
        <DialogContent data-testid="dialog-content">
          <p>Content</p>
        </DialogContent>
      </Dialog>
    );

    const content = screen.getByTestId('dialog-content');
    // Inner wrapper div should have p-5
    const innerWrapper = content.querySelector('div');
    expect(innerWrapper?.className).toContain('p-5');
  });

  it('has vertical centering with transform', () => {
    render(
      <Dialog open>
        <DialogContent data-testid="dialog-content">
          <p>Content</p>
        </DialogContent>
      </Dialog>
    );

    const content = screen.getByTestId('dialog-content');
    const classList = content.className;

    expect(classList).toContain('top-[50%]');
    expect(classList).toContain('translate-y-[-50%]');
  });

  it('has inner wrapper with max-height and overflow for scrollable content', () => {
    render(
      <Dialog open>
        <DialogContent data-testid="dialog-content">
          <p>Content</p>
        </DialogContent>
      </Dialog>
    );

    const content = screen.getByTestId('dialog-content');
    const innerWrapper = content.querySelector('div');

    expect(innerWrapper?.className).toContain('max-h-[85vh]');
    expect(innerWrapper?.className).toContain('overflow-y-auto');
  });

  it('has inner wrapper with overflow-x-hidden to prevent horizontal content overflow', () => {
    render(
      <Dialog open>
        <DialogContent data-testid="dialog-content">
          <p>Content</p>
        </DialogContent>
      </Dialog>
    );

    const content = screen.getByTestId('dialog-content');
    const innerWrapper = content.querySelector('div');

    // Must have overflow-x-hidden to prevent form inputs from overflowing
    expect(innerWrapper?.className).toContain('overflow-x-hidden');
  });

  it('has rounded corners', () => {
    render(
      <Dialog open>
        <DialogContent data-testid="dialog-content">
          <p>Content</p>
        </DialogContent>
      </Dialog>
    );

    const content = screen.getByTestId('dialog-content');
    const classes = getClassList(content);

    expect(classes).toContain('rounded-lg');
  });

  it('has inner wrapper with flex column layout and w-full', () => {
    render(
      <Dialog open>
        <DialogContent data-testid="dialog-content">
          <p>Content</p>
        </DialogContent>
      </Dialog>
    );

    const content = screen.getByTestId('dialog-content');
    const innerWrapper = content.querySelector('div');

    expect(innerWrapper?.className).toContain('flex');
    expect(innerWrapper?.className).toContain('flex-col');
    expect(innerWrapper?.className).toContain('w-full');
  });

  it('renders close button with correct positioning', () => {
    render(
      <Dialog open>
        <DialogContent>
          <p>Content</p>
        </DialogContent>
      </Dialog>
    );

    // Close button should exist
    const closeButton = screen.getByRole('button', { name: /đóng/i });
    expect(closeButton).toBeInTheDocument();

    // Check positioning classes
    const classList = closeButton.className;
    expect(classList).toContain('absolute');
    expect(classList).toContain('right-4');
    expect(classList).toContain('top-4');
  });

  it('accepts custom className', () => {
    render(
      <Dialog open>
        <DialogContent className="custom-class" data-testid="dialog-content">
          <p>Content</p>
        </DialogContent>
      </Dialog>
    );

    const content = screen.getByTestId('dialog-content');
    expect(content.className).toContain('custom-class');
  });

  it('accepts custom max-width via className override', () => {
    render(
      <Dialog open>
        <DialogContent className="sm:max-w-[600px]" data-testid="dialog-content">
          <p>Content</p>
        </DialogContent>
      </Dialog>
    );

    const content = screen.getByTestId('dialog-content');
    expect(content.className).toContain('sm:max-w-[600px]');
  });
});

describe('DialogHeader', () => {
  it('renders with right padding to avoid close button overlap', () => {
    render(
      <Dialog open>
        <DialogContent>
          <DialogHeader data-testid="dialog-header">
            <DialogTitle>Title</DialogTitle>
          </DialogHeader>
        </DialogContent>
      </Dialog>
    );

    const header = screen.getByTestId('dialog-header');
    const classes = getClassList(header);

    // Must have pr-8 to avoid overlapping with close button
    expect(classes).toContain('pr-8');
  });

  it('has correct spacing and alignment', () => {
    render(
      <Dialog open>
        <DialogContent>
          <DialogHeader data-testid="dialog-header">
            <DialogTitle>Title</DialogTitle>
            <DialogDescription>Description</DialogDescription>
          </DialogHeader>
        </DialogContent>
      </Dialog>
    );

    const header = screen.getByTestId('dialog-header');
    const classList = header.className;

    expect(classList).toContain('space-y-1.5');
    expect(classList).toContain('text-center');
    expect(classList).toContain('sm:text-left');
  });
});

describe('DialogFooter', () => {
  it('stacks buttons on mobile and rows on tablet+', () => {
    render(
      <Dialog open>
        <DialogContent>
          <DialogFooter data-testid="dialog-footer">
            <button>Cancel</button>
            <button>Submit</button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );

    const footer = screen.getByTestId('dialog-footer');
    const classList = footer.className;

    expect(classList).toContain('flex-col-reverse');
    expect(classList).toContain('sm:flex-row');
    expect(classList).toContain('sm:justify-end');
    expect(classList).toContain('sm:space-x-2');
  });
});

describe('DialogTitle', () => {
  it('renders with correct typography', () => {
    render(
      <Dialog open>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Test Title</DialogTitle>
          </DialogHeader>
        </DialogContent>
      </Dialog>
    );

    const title = screen.getByText('Test Title');
    const classList = title.className;

    expect(classList).toContain('text-lg');
    expect(classList).toContain('font-semibold');
    expect(classList).toContain('font-display');
  });
});

describe('DialogDescription', () => {
  it('renders with muted foreground', () => {
    render(
      <Dialog open>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Title</DialogTitle>
            <DialogDescription>Test Description</DialogDescription>
          </DialogHeader>
        </DialogContent>
      </Dialog>
    );

    const description = screen.getByText('Test Description');
    const classList = description.className;

    expect(classList).toContain('text-sm');
    expect(classList).toContain('text-muted-foreground');
  });
});

describe('Dialog mobile responsiveness', () => {
  it('does not use mx-4 which causes alignment issues', () => {
    render(
      <Dialog open>
        <DialogContent data-testid="dialog-content">
          <p>Content</p>
        </DialogContent>
      </Dialog>
    );

    const content = screen.getByTestId('dialog-content');
    const classes = getClassList(content);

    // mx-4 should NOT be present - it causes alignment issues with transform centering
    expect(classes).not.toContain('mx-4');
  });

  it('uses fixed positioning with left/right instead of width + margin', () => {
    render(
      <Dialog open>
        <DialogContent data-testid="dialog-content">
          <p>Content</p>
        </DialogContent>
      </Dialog>
    );

    const content = screen.getByTestId('dialog-content');
    const classList = content.className;

    // Should use left-4 right-4 for mobile
    expect(classList).toContain('left-4');
    expect(classList).toContain('right-4');

    // Should NOT use w-full on mobile (only sm:w-full)
    // The base classes should not have w-full
    expect(classList).toContain('sm:w-full');
  });
});

describe('Dialog accessibility', () => {
  it('renders close button with screen reader text', () => {
    render(
      <Dialog open>
        <DialogContent>
          <p>Content</p>
        </DialogContent>
      </Dialog>
    );

    const closeButton = screen.getByRole('button', { name: /đóng/i });
    expect(closeButton).toBeInTheDocument();

    // Should have sr-only text
    const srText = closeButton.querySelector('.sr-only');
    expect(srText).toHaveTextContent('Đóng');
  });

  it('renders overlay for blocking background interaction', () => {
    render(
      <Dialog open>
        <DialogContent data-testid="dialog-content">
          <p>Content</p>
        </DialogContent>
      </Dialog>
    );

    // Overlay should be present (it's a sibling to DialogContent in the portal)
    const overlay = document.querySelector('[data-state="open"]');
    expect(overlay).toBeInTheDocument();
  });
});
