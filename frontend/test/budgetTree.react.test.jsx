import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { act } from 'react';
import { describe, expect, test, vi } from 'vitest';

import { TreeRoot } from '../budgetTree.react.js';

const sampleNodes = [
  {
    key: 'project:1',
    label: 'Project A',
    type: 'project',
    children: [
      {
        key: 'category:1',
        label: 'Category A1',
        type: 'category',
      },
    ],
  },
];

describe('TreeRoot', () => {
  test('renders nested nodes and respects expandedKeys', () => {
    const view = render(<TreeRoot nodes={sampleNodes} expandedKeys={['project:1']} />);

    expect(screen.getByDisplayValue('Project A')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Category A1')).toBeVisible();

    view.rerender(<TreeRoot nodes={sampleNodes} expandedKeys={[]} />);

    const child = screen.getByDisplayValue('Category A1');
    expect(child).not.toBeVisible();
  });

  test('toggle button collapses and expands nodes while invoking callback', async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();

    render(
      <TreeRoot
        nodes={sampleNodes}
        expandedKeys={['project:1']}
        onToggle={onToggle}
      />
    );

    const toggle = screen.getByRole('button', { name: 'Collapse' });
    const child = screen.getByDisplayValue('Category A1');
    expect(child).toBeVisible();

    await act(async () => {
      await user.click(toggle);
    });

    expect(onToggle).toHaveBeenCalledWith(
      expect.objectContaining({ key: 'project:1' }),
      false
    );
    const expandButton = await screen.findByRole('button', { name: 'Expand' });
    await waitFor(() => expect(child).not.toBeVisible());

    await act(async () => {
      await user.click(expandButton);
    });
    expect(onToggle).toHaveBeenCalledWith(
      expect.objectContaining({ key: 'project:1' }),
      true
    );
    await waitFor(() => expect(screen.getByDisplayValue('Category A1')).toBeVisible());
  });

  test('row content can opt out of toggle handling with data-bt-stop-toggle', async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();

    const nodes = [
      {
        key: 'project:2',
        label: 'Project B',
        type: 'project',
        children: [
          { key: 'category:2', label: 'Category B1', type: 'category' },
        ],
      },
    ];

    const renderRow = ({ node }) => ({
      main: [
        <span key="title" className="bt-title">{node.label}</span>,
        <button
          key="action"
          type="button"
          data-bt-stop-toggle="1"
        >
          Action
        </button>,
      ],
    });

    render(
      <TreeRoot
        nodes={nodes}
        expandedKeys={['project:2']}
        onToggle={onToggle}
        renderRow={renderRow}
      />
    );

    const [actionButton] = screen.getAllByRole('button', { name: 'Action' });
    await act(async () => {
      await user.click(actionButton);
    });
    expect(onToggle).not.toHaveBeenCalled();

    await act(async () => {
      await user.click(screen.getByText('Project B'));
    });
    expect(onToggle).toHaveBeenCalledWith(
      expect.objectContaining({ key: 'project:2' }),
      false
    );
  });
});
