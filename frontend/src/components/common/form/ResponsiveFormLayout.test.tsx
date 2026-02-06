// src/components/common/form/ResponsiveFormLayout.test.tsx
/**
 * ResponsiveFormLayout Component Tests
 *
 * Tests for mobile-responsive form layout components:
 * - FormRow: responsive grid columns
 * - FormActions: button stacking and dividers
 * - FormSection: section headers and spacing
 * - FormContainer: max-width constraints
 */

import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import {
  FormContainer,
  FormSection,
  FormRow,
  FormActions,
  FormDivider,
  FormFieldWrapper,
} from './ResponsiveFormLayout';

// Helper to get computed class names
const getClassList = (element: HTMLElement): string[] => {
  return element.className.split(' ').filter(Boolean);
};

describe('FormRow', () => {
  it('renders with single column on mobile', () => {
    render(
      <FormRow data-testid="form-row">
        <div>Field 1</div>
        <div>Field 2</div>
      </FormRow>
    );

    const row = screen.getByTestId('form-row');
    const classes = getClassList(row);

    expect(classes).toContain('grid');
    expect(classes).toContain('grid-cols-1');
  });

  it('renders with 2 columns on sm+ by default', () => {
    render(
      <FormRow data-testid="form-row">
        <div>Field 1</div>
        <div>Field 2</div>
      </FormRow>
    );

    const row = screen.getByTestId('form-row');
    const classes = getClassList(row);

    expect(classes).toContain('sm:grid-cols-2');
  });

  it('supports 3 columns', () => {
    render(
      <FormRow columns={3} data-testid="form-row">
        <div>Field 1</div>
        <div>Field 2</div>
        <div>Field 3</div>
      </FormRow>
    );

    const row = screen.getByTestId('form-row');
    const classList = row.className;

    expect(classList).toContain('sm:grid-cols-2');
    expect(classList).toContain('lg:grid-cols-3');
  });

  it('supports 4 columns', () => {
    render(
      <FormRow columns={4} data-testid="form-row">
        <div>Field 1</div>
        <div>Field 2</div>
        <div>Field 3</div>
        <div>Field 4</div>
      </FormRow>
    );

    const row = screen.getByTestId('form-row');
    const classList = row.className;

    expect(classList).toContain('sm:grid-cols-2');
    expect(classList).toContain('lg:grid-cols-4');
  });

  it('applies correct gap classes', () => {
    render(
      <FormRow gap="md" data-testid="form-row">
        <div>Field 1</div>
        <div>Field 2</div>
      </FormRow>
    );

    const row = screen.getByTestId('form-row');
    const classes = getClassList(row);

    expect(classes).toContain('gap-4');
  });

  it('supports custom className', () => {
    render(
      <FormRow className="custom-class" data-testid="form-row">
        <div>Field 1</div>
        <div>Field 2</div>
      </FormRow>
    );

    const row = screen.getByTestId('form-row');
    expect(row.className).toContain('custom-class');
  });
});

describe('FormActions', () => {
  it('stacks buttons on mobile by default', () => {
    render(
      <FormActions data-testid="form-actions">
        <button>Cancel</button>
        <button>Submit</button>
      </FormActions>
    );

    const actions = screen.getByTestId('form-actions');
    const innerDiv = actions.querySelector('div');

    expect(innerDiv?.className).toContain('flex-col-reverse');
    expect(innerDiv?.className).toContain('sm:flex-row');
  });

  it('renders with gap between buttons', () => {
    render(
      <FormActions data-testid="form-actions">
        <button>Cancel</button>
        <button>Submit</button>
      </FormActions>
    );

    const actions = screen.getByTestId('form-actions');
    const innerDiv = actions.querySelector('div');

    expect(innerDiv?.className).toContain('gap-3');
  });

  it('shows divider when showDivider is true', () => {
    render(
      <FormActions showDivider data-testid="form-actions">
        <button>Cancel</button>
        <button>Submit</button>
      </FormActions>
    );

    const actions = screen.getByTestId('form-actions');
    const classes = getClassList(actions);

    expect(classes).toContain('border-t');
    expect(classes).toContain('pt-4');
    expect(classes).toContain('mt-4');
  });

  it('applies full-width to buttons on mobile when stacked', () => {
    render(
      <FormActions stackOnMobile data-testid="form-actions">
        <button>Cancel</button>
        <button>Submit</button>
      </FormActions>
    );

    const actions = screen.getByTestId('form-actions');
    const innerDiv = actions.querySelector('div');

    // Check for the full-width selector
    expect(innerDiv?.className).toContain('[&>*]:w-full');
    expect(innerDiv?.className).toContain('[&>*]:sm:w-auto');
  });

  it('supports different alignments', () => {
    render(
      <FormActions align="between" data-testid="form-actions">
        <button>Cancel</button>
        <button>Submit</button>
      </FormActions>
    );

    const actions = screen.getByTestId('form-actions');
    const innerDiv = actions.querySelector('div');

    expect(innerDiv?.className).toContain('justify-between');
  });

  it('does not stack when stackOnMobile is false', () => {
    render(
      <FormActions stackOnMobile={false} data-testid="form-actions">
        <button>Cancel</button>
        <button>Submit</button>
      </FormActions>
    );

    const actions = screen.getByTestId('form-actions');
    const innerDiv = actions.querySelector('div');

    expect(innerDiv?.className).toContain('flex-row');
    expect(innerDiv?.className).not.toContain('flex-col-reverse');
  });
});

describe('FormSection', () => {
  it('renders title and description', () => {
    render(
      <FormSection title="Personal Info" description="Enter your details">
        <div>Form fields</div>
      </FormSection>
    );

    expect(screen.getByText('Personal Info')).toBeInTheDocument();
    expect(screen.getByText('Enter your details')).toBeInTheDocument();
  });

  it('renders without header when no title/description', () => {
    render(
      <FormSection data-testid="form-section">
        <div>Form fields</div>
      </FormSection>
    );

    const section = screen.getByTestId('form-section');
    const header = section.querySelector('.mb-4');

    expect(header).not.toBeInTheDocument();
  });

  it('applies correct spacing', () => {
    render(
      <FormSection spacing="normal" data-testid="form-section">
        <div>Field 1</div>
        <div>Field 2</div>
      </FormSection>
    );

    const section = screen.getByTestId('form-section');
    const contentDiv = section.querySelector('.space-y-6');

    expect(contentDiv).toBeInTheDocument();
  });
});

describe('FormContainer', () => {
  it('renders with max-width constraint', () => {
    render(
      <FormContainer data-testid="form-container">
        <div>Form content</div>
      </FormContainer>
    );

    const container = screen.getByTestId('form-container');
    const classes = getClassList(container);

    expect(classes).toContain('w-full');
    expect(classes).toContain('max-w-2xl'); // lg default
  });

  it('supports different max-widths', () => {
    render(
      <FormContainer maxWidth="sm" data-testid="form-container">
        <div>Form content</div>
      </FormContainer>
    );

    const container = screen.getByTestId('form-container');
    const classes = getClassList(container);

    expect(classes).toContain('max-w-sm');
  });

  it('can render as div instead of form', () => {
    render(
      <FormContainer asDiv data-testid="form-container">
        <div>Form content</div>
      </FormContainer>
    );

    const container = screen.getByTestId('form-container');
    expect(container.tagName.toLowerCase()).toBe('div');
  });

  it('renders as form by default', () => {
    render(
      <FormContainer data-testid="form-container">
        <div>Form content</div>
      </FormContainer>
    );

    const container = screen.getByTestId('form-container');
    expect(container.tagName.toLowerCase()).toBe('form');
  });
});

describe('FormDivider', () => {
  it('renders simple divider without label', () => {
    render(<FormDivider data-testid="divider" />);

    const divider = screen.getByTestId('divider');
    const classes = getClassList(divider);

    expect(classes).toContain('border-t');
    expect(classes).toContain('my-6');
  });

  it('renders divider with label', () => {
    render(<FormDivider label="Or continue with" />);

    expect(screen.getByText('Or continue with')).toBeInTheDocument();
  });
});

describe('FormFieldWrapper', () => {
  it('renders label with required indicator', () => {
    render(
      <FormFieldWrapper label="Email" required>
        <input type="email" />
      </FormFieldWrapper>
    );

    expect(screen.getByText('Email')).toBeInTheDocument();
    expect(screen.getByText('*')).toBeInTheDocument();
  });

  it('renders help text', () => {
    render(
      <FormFieldWrapper helpText="Enter a valid email">
        <input type="email" />
      </FormFieldWrapper>
    );

    expect(screen.getByText('Enter a valid email')).toBeInTheDocument();
  });

  it('renders error instead of help text when error is present', () => {
    render(
      <FormFieldWrapper helpText="Enter a valid email" error="Invalid email">
        <input type="email" />
      </FormFieldWrapper>
    );

    expect(screen.getByText('Invalid email')).toBeInTheDocument();
    expect(screen.queryByText('Enter a valid email')).not.toBeInTheDocument();
  });

  it('applies full-width class when specified', () => {
    render(
      <FormFieldWrapper fullWidth data-testid="field-wrapper">
        <input type="text" />
      </FormFieldWrapper>
    );

    const wrapper = screen.getByTestId('field-wrapper');
    const classes = getClassList(wrapper);

    expect(classes).toContain('col-span-full');
  });
});

describe('Integration: FormActions inside Dialog context', () => {
  it('FormActions with showDivider works correctly', () => {
    // Simulating DialogContent structure
    render(
      <div className="p-5" data-testid="dialog-content-mock">
        <div>Form fields</div>
        <FormActions stackOnMobile showDivider data-testid="form-actions">
          <button>Cancel</button>
          <button>Submit</button>
        </FormActions>
      </div>
    );

    const actions = screen.getByTestId('form-actions');

    // Should have border-t for divider
    expect(actions.className).toContain('border-t');
    expect(actions.className).toContain('pt-4');
  });

  it('FormRow columns work correctly inside form', () => {
    render(
      <div className="p-5" data-testid="dialog-content-mock">
        <FormRow columns={2} data-testid="form-row">
          <div>Name</div>
          <div>Phone</div>
        </FormRow>
      </div>
    );

    const row = screen.getByTestId('form-row');

    expect(row.className).toContain('grid-cols-1');
    expect(row.className).toContain('sm:grid-cols-2');
  });
});
