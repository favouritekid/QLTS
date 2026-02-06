// src/components/ui/form.test.tsx
/**
 * Form Component Tests
 *
 * Tests for form components used in dialogs and pages:
 * - FormItem has min-w-0 to prevent overflow in grid layouts
 */

import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { useForm } from 'react-hook-form';
import {
  Form,
  FormItem,
  FormLabel,
  FormControl,
  FormDescription,
  FormMessage,
  FormField,
} from './form';
import { Input } from './input';

// Helper to get computed class names
const getClassList = (element: HTMLElement): string[] => {
  return element.className.split(' ').filter(Boolean);
};

// Test wrapper component
function TestFormWrapper({ children }: { children: React.ReactNode }) {
  const form = useForm({
    defaultValues: {
      test: '',
    },
  });

  return <Form {...form}>{children}</Form>;
}

describe('FormItem', () => {
  it('has min-w-0 to allow shrinking in grid layouts', () => {
    render(
      <TestFormWrapper>
        <FormField
          name="test"
          render={({ field }) => (
            <FormItem data-testid="form-item">
              <FormLabel>Test</FormLabel>
              <FormControl>
                <Input {...field} />
              </FormControl>
            </FormItem>
          )}
        />
      </TestFormWrapper>
    );

    const formItem = screen.getByTestId('form-item');
    const classes = getClassList(formItem);

    // min-w-0 is critical for preventing overflow in CSS Grid
    expect(classes).toContain('min-w-0');
  });

  it('has proper spacing', () => {
    render(
      <TestFormWrapper>
        <FormField
          name="test"
          render={({ field }) => (
            <FormItem data-testid="form-item">
              <FormLabel>Test</FormLabel>
              <FormControl>
                <Input {...field} />
              </FormControl>
            </FormItem>
          )}
        />
      </TestFormWrapper>
    );

    const formItem = screen.getByTestId('form-item');
    const classes = getClassList(formItem);

    expect(classes).toContain('space-y-2');
  });

  it('accepts custom className', () => {
    render(
      <TestFormWrapper>
        <FormField
          name="test"
          render={({ field }) => (
            <FormItem data-testid="form-item" className="custom-class">
              <FormLabel>Test</FormLabel>
              <FormControl>
                <Input {...field} />
              </FormControl>
            </FormItem>
          )}
        />
      </TestFormWrapper>
    );

    const formItem = screen.getByTestId('form-item');
    expect(formItem.className).toContain('custom-class');
  });
});

describe('FormLabel', () => {
  it('renders label text', () => {
    render(
      <TestFormWrapper>
        <FormField
          name="test"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Test Label</FormLabel>
              <FormControl>
                <Input {...field} />
              </FormControl>
            </FormItem>
          )}
        />
      </TestFormWrapper>
    );

    expect(screen.getByText('Test Label')).toBeInTheDocument();
  });
});

describe('FormDescription', () => {
  it('renders description text with muted style', () => {
    render(
      <TestFormWrapper>
        <FormField
          name="test"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Test</FormLabel>
              <FormControl>
                <Input {...field} />
              </FormControl>
              <FormDescription>Helper text</FormDescription>
            </FormItem>
          )}
        />
      </TestFormWrapper>
    );

    const description = screen.getByText('Helper text');
    expect(description).toBeInTheDocument();
    expect(description.className).toContain('text-muted-foreground');
  });
});

describe('Form integration with grid layout', () => {
  it('FormItem with min-w-0 allows inputs to respect grid boundaries', () => {
    render(
      <div className="grid grid-cols-2 gap-4" style={{ width: '300px' }}>
        <TestFormWrapper>
          <FormField
            name="test"
            render={({ field }) => (
              <FormItem data-testid="form-item">
                <FormLabel>Test</FormLabel>
                <FormControl>
                  <Input {...field} placeholder="Long placeholder text that might overflow" />
                </FormControl>
              </FormItem>
            )}
          />
        </TestFormWrapper>
      </div>
    );

    const formItem = screen.getByTestId('form-item');
    const classes = getClassList(formItem);

    // min-w-0 ensures the item can shrink below its content size
    expect(classes).toContain('min-w-0');
  });
});
