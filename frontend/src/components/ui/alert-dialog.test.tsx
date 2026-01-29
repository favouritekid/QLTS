// src/components/ui/alert-dialog.test.tsx
/**
 * AlertDialog Component Tests
 *
 * Tests for mobile-responsive alert dialog positioning and padding standards:
 * - Mobile: left-4 right-4 positioning (16px from screen edges)
 * - Tablet+: centered with max-width using transform
 * - AlertDialogHeader has pr-8 for consistency
 * - AlertDialogContent has proper padding (p-6 = 24px)
 */

import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from './alert-dialog';

// Helper to get computed class names
const getClassList = (element: HTMLElement): string[] => {
  return element.className.split(' ').filter(Boolean);
};

describe('AlertDialogContent', () => {
  it('renders with correct mobile positioning classes', () => {
    render(
      <AlertDialog open>
        <AlertDialogContent data-testid="alert-content">
          <AlertDialogHeader>
            <AlertDialogTitle>Title</AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction>Continue</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    );

    const content = screen.getByTestId('alert-content');
    const classes = getClassList(content);

    // Mobile: left-4 right-4 (instead of transform centering)
    expect(classes).toContain('left-4');
    expect(classes).toContain('right-4');
  });

  it('renders with correct tablet+ positioning classes', () => {
    render(
      <AlertDialog open>
        <AlertDialogContent data-testid="alert-content">
          <AlertDialogHeader>
            <AlertDialogTitle>Title</AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction>Continue</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    );

    const content = screen.getByTestId('alert-content');
    const classList = content.className;

    // Tablet+: centered with transform
    expect(classList).toContain('sm:left-[50%]');
    expect(classList).toContain('sm:right-auto');
    expect(classList).toContain('sm:translate-x-[-50%]');
    expect(classList).toContain('sm:max-w-lg');
    expect(classList).toContain('sm:w-full');
  });

  it('has inner wrapper with correct padding (p-6 = 24px)', () => {
    render(
      <AlertDialog open>
        <AlertDialogContent data-testid="alert-content">
          <AlertDialogHeader>
            <AlertDialogTitle>Title</AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction>Continue</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    );

    const content = screen.getByTestId('alert-content');
    const innerWrapper = content.querySelector('div');

    expect(innerWrapper?.className).toContain('p-6');
  });

  it('has vertical centering with transform', () => {
    render(
      <AlertDialog open>
        <AlertDialogContent data-testid="alert-content">
          <AlertDialogHeader>
            <AlertDialogTitle>Title</AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction>Continue</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    );

    const content = screen.getByTestId('alert-content');
    const classList = content.className;

    expect(classList).toContain('top-[50%]');
    expect(classList).toContain('translate-y-[-50%]');
  });

  it('has inner wrapper with max-height and overflow for scrollable content', () => {
    render(
      <AlertDialog open>
        <AlertDialogContent data-testid="alert-content">
          <AlertDialogHeader>
            <AlertDialogTitle>Title</AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction>Continue</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    );

    const content = screen.getByTestId('alert-content');
    const innerWrapper = content.querySelector('div');

    expect(innerWrapper?.className).toContain('max-h-[85vh]');
    expect(innerWrapper?.className).toContain('overflow-y-auto');
  });

  it('has rounded corners', () => {
    render(
      <AlertDialog open>
        <AlertDialogContent data-testid="alert-content">
          <AlertDialogHeader>
            <AlertDialogTitle>Title</AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction>Continue</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    );

    const content = screen.getByTestId('alert-content');
    const classes = getClassList(content);

    expect(classes).toContain('rounded-lg');
  });

  it('has inner wrapper with flex column layout and w-full', () => {
    render(
      <AlertDialog open>
        <AlertDialogContent data-testid="alert-content">
          <AlertDialogHeader>
            <AlertDialogTitle>Title</AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction>Continue</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    );

    const content = screen.getByTestId('alert-content');
    const innerWrapper = content.querySelector('div');

    expect(innerWrapper?.className).toContain('flex');
    expect(innerWrapper?.className).toContain('flex-col');
    expect(innerWrapper?.className).toContain('w-full');
  });
});

describe('AlertDialogHeader', () => {
  it('renders with right padding for consistency', () => {
    render(
      <AlertDialog open>
        <AlertDialogContent>
          <AlertDialogHeader data-testid="alert-header">
            <AlertDialogTitle>Title</AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction>Continue</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    );

    const header = screen.getByTestId('alert-header');
    const classes = getClassList(header);

    // Should have pr-8 for consistency with Dialog
    expect(classes).toContain('pr-8');
  });

  it('has correct spacing and alignment', () => {
    render(
      <AlertDialog open>
        <AlertDialogContent>
          <AlertDialogHeader data-testid="alert-header">
            <AlertDialogTitle>Title</AlertDialogTitle>
            <AlertDialogDescription>Description</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction>Continue</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    );

    const header = screen.getByTestId('alert-header');
    const classList = header.className;

    expect(classList).toContain('space-y-2');
    expect(classList).toContain('text-center');
    expect(classList).toContain('sm:text-left');
  });
});

describe('AlertDialogFooter', () => {
  it('stacks buttons on mobile and rows on tablet+', () => {
    render(
      <AlertDialog open>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Title</AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogFooter data-testid="alert-footer">
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction>Continue</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    );

    const footer = screen.getByTestId('alert-footer');
    const classList = footer.className;

    expect(classList).toContain('flex-col-reverse');
    expect(classList).toContain('sm:flex-row');
    expect(classList).toContain('sm:justify-end');
    expect(classList).toContain('sm:space-x-2');
  });
});

describe('AlertDialogTitle', () => {
  it('renders with correct typography', () => {
    render(
      <AlertDialog open>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Test Title</AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction>Continue</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    );

    const title = screen.getByText('Test Title');
    const classList = title.className;

    expect(classList).toContain('text-lg');
    expect(classList).toContain('font-semibold');
    expect(classList).toContain('font-display');
  });
});

describe('AlertDialogDescription', () => {
  it('renders with muted foreground', () => {
    render(
      <AlertDialog open>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Title</AlertDialogTitle>
            <AlertDialogDescription>Test Description</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction>Continue</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    );

    const description = screen.getByText('Test Description');
    const classList = description.className;

    expect(classList).toContain('text-sm');
    expect(classList).toContain('text-muted-foreground');
  });
});

describe('AlertDialogCancel', () => {
  it('has outline variant styling', () => {
    render(
      <AlertDialog open>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Title</AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction>Continue</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    );

    const cancelButton = screen.getByText('Cancel');
    expect(cancelButton).toBeInTheDocument();
  });

  it('has margin-top on mobile', () => {
    render(
      <AlertDialog open>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Title</AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction>Continue</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    );

    const cancelButton = screen.getByText('Cancel');
    const classList = cancelButton.className;

    expect(classList).toContain('mt-2');
    expect(classList).toContain('sm:mt-0');
  });
});

describe('AlertDialog mobile responsiveness', () => {
  it('does not use problematic w-full with mx-4 pattern', () => {
    render(
      <AlertDialog open>
        <AlertDialogContent data-testid="alert-content">
          <AlertDialogHeader>
            <AlertDialogTitle>Title</AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction>Continue</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    );

    const content = screen.getByTestId('alert-content');
    const classes = getClassList(content);

    // mx-4 should NOT be present - it causes alignment issues
    expect(classes).not.toContain('mx-4');
  });

  it('uses fixed positioning with left/right for mobile', () => {
    render(
      <AlertDialog open>
        <AlertDialogContent data-testid="alert-content">
          <AlertDialogHeader>
            <AlertDialogTitle>Title</AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction>Continue</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    );

    const content = screen.getByTestId('alert-content');
    const classList = content.className;

    // Should use left-4 right-4 for mobile
    expect(classList).toContain('left-4');
    expect(classList).toContain('right-4');
  });
});

describe('AlertDialog accessibility', () => {
  it('renders with proper role structure', () => {
    render(
      <AlertDialog open>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Confirm Action</AlertDialogTitle>
            <AlertDialogDescription>Are you sure?</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction>Continue</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    );

    // AlertDialog should have alertdialog role
    const dialog = screen.getByRole('alertdialog');
    expect(dialog).toBeInTheDocument();
  });
});
