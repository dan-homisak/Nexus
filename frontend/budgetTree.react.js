import React from './vendor/react.js';
import ReactDOM from './vendor/react-dom-client.js';

const { useCallback, useEffect, useMemo, useRef, useState } = React;

const INTERACTIVE_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT', 'OPTION', 'BUTTON', 'A']);

function listToSignature(values) {
  return [...values].map(String).sort().join('|');
}

function getNodeKey(node) {
  if (!node) return '';
  if (node.key != null) return String(node.key);
  if (node.id != null) return String(node.id);
  if (node.label) return `label:${node.label}`;
  return '';
}

function normalizeArray(value) {
  if (Array.isArray(value)) return value;
  if (value === undefined || value === null) return [];
  return [value];
}

function shouldSuppressToggle(target, container) {
  let el = target;
  while (el && el !== container) {
    if (el.dataset && el.dataset.btStopToggle === '1') return true;
    if (INTERACTIVE_TAGS.has(el.tagName)) return true;
    el = el.parentElement;
  }
  return false;
}

function formatCurrency(actions, value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) {
    return '—';
  }
  if (typeof actions?.fmtCurrency === 'function') {
    try {
      return actions.fmtCurrency(Number(value));
    } catch (err) {
      console.warn('fmtCurrency failed', err);
    }
  }
  return Number(value).toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function typeLabel(nodeData) {
  const type = nodeData?.type;
  if (type === 'project') return 'Item/Project';
  if (type === 'category') {
    return nodeData?.is_leaf ? 'Item' : 'Item (Rollup)';
  }
  return type || 'Node';
}

function toAmountInputString(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) {
    return '';
  }
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toFixed(2) : String(value);
}

function useAutoResize(ref, value) {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const resize = () => {
      el.style.height = 'auto';
      el.style.height = `${el.scrollHeight}px`;
    };
    resize();
  }, [ref, value]);
}

function TagRegion({ node, actions }) {
  const ref = useRef(null);
  const data = node?.data ?? {};

  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    if (typeof actions?.attachTagRow !== 'function') {
      el.innerHTML = '';
      return undefined;
    }
    actions.attachTagRow(el, data, { showLabel: false });
    return () => {
      if (el.__tagObserver && typeof el.__tagObserver.disconnect === 'function') {
        try {
          el.__tagObserver.disconnect();
        } catch (err) {
          console.warn('failed to disconnect tag observer', err);
        }
        el.__tagObserver = null;
      }
      if (el.__tagOutside) {
        document.removeEventListener('mousedown', el.__tagOutside, true);
        el.__tagOutside = null;
      }
      el.innerHTML = '';
    };
  }, [actions, data]);

  return React.createElement('div', {
    className: 'bt-tagsRegion tag-region',
    'data-bt-stop-toggle': '1',
    ref,
  });
}

function NameField({ node, actions }) {
  const data = node?.data ?? {};
  const type = data.type || node?.type;
  const [value, setValue] = useState(data.name ?? node?.label ?? '');
  const textRef = useRef(null);

  useEffect(() => {
    setValue(data.name ?? node?.label ?? '');
  }, [data.name, node?.label]);

  useAutoResize(textRef, value);

  const canEdit = (type === 'project' && typeof actions?.saveProjectPatch === 'function')
    || (type === 'category' && typeof actions?.saveCategoryPatch === 'function');

  const originalName = useMemo(() => (data.name ?? node?.label ?? '').trim(), [data.name, node?.label]);

  const handleBlur = useCallback(async () => {
    if (!canEdit) {
      setValue(originalName);
      return;
    }
    const next = value.trim();
    if (!next) {
      setValue(originalName);
      return;
    }
    if (next === originalName) return;
    try {
      if (type === 'project') {
        await actions.saveProjectPatch?.(data.id, { name: next });
      } else if (type === 'category') {
        await actions.saveCategoryPatch?.(data.id, { name: next });
      }
    } catch (err) {
      actions.showError?.(err);
      setValue(originalName);
    }
  }, [actions, canEdit, data.id, originalName, type, value]);

  const handleKeyDown = useCallback((evt) => {
    if (evt.key === 'Enter' && !evt.shiftKey) {
      evt.preventDefault();
      evt.currentTarget.blur();
    }
  }, []);

  return React.createElement('textarea', {
    ref: textRef,
    className: 'bt-nameInput',
    rows: 1,
    value,
    readOnly: !canEdit,
    onChange: (evt) => setValue(evt.target.value),
    onBlur: handleBlur,
    onKeyDown: handleKeyDown,
    'data-bt-stop-toggle': '1',
    'aria-label': `${typeLabel(data)} name`,
  });
}

function AssetRegion({ node, actions }) {
  const data = node?.data ?? {};
  if (data.type !== 'project') return null;
  const assets = Array.isArray(data.assets?.items) ? data.assets.items : [];
  const projectNode = data;

  const canAdd = typeof actions?.openAssetModal === 'function';
  const canRemove = typeof actions?.detachAssetFromProject === 'function';

  const handleAdd = useCallback(() => {
    if (!canAdd) return;
    actions.openAssetModal?.(projectNode);
  }, [actions, canAdd, projectNode]);

  const handleRemove = useCallback(async (asset) => {
    if (!canRemove) return;
    try {
      await actions.detachAssetFromProject?.(projectNode.id, asset.id);
      await actions.refreshTreeOnly?.();
    } catch (err) {
      actions.showError?.(err);
    }
  }, [actions, canRemove, projectNode]);

  const chips = assets.length
    ? React.createElement(
        'div',
        { className: 'asset-chip-row' },
        assets.map((asset) =>
          React.createElement(
            'span',
            { className: 'asset-chip', key: asset.id },
            asset.name,
            canRemove
              ? React.createElement(
                  'button',
                  {
                    type: 'button',
                    className: 'asset-chip-remove',
                    onClick: (evt) => {
                      evt.stopPropagation();
                      handleRemove(asset);
                    },
                    'aria-label': `Remove asset ${asset.name}`,
                  },
                  '×'
                )
              : null
          )
        )
      )
    : React.createElement('span', { className: 'asset-empty' }, 'None');

  const addButton = canAdd
    ? React.createElement(
        'button',
        {
          type: 'button',
          className: 'asset-add-btn',
          onClick: (evt) => {
            evt.stopPropagation();
            handleAdd();
          },
        },
        '+ Asset'
      )
    : null;

  return React.createElement(
    'div',
    { className: 'bt-assets', 'data-bt-stop-toggle': '1' },
    React.createElement('span', { className: 'bt-assetsLabel' }, 'Assets'),
    chips,
    addButton
  );
}

function LeafAmountEditor({ node, actions }) {
  const data = node?.data ?? {};
  const canEdit = typeof actions?.saveCategoryPatch === 'function';
  const [value, setValue] = useState(toAmountInputString(data.amount_leaf));

  useEffect(() => {
    setValue(toAmountInputString(data.amount_leaf));
  }, [data.amount_leaf]);

  const handleBlur = useCallback(async () => {
    if (!canEdit) {
      setValue(toAmountInputString(data.amount_leaf));
      return;
    }
    const trimmed = value.trim();
    const original = toAmountInputString(data.amount_leaf);
    if (trimmed === original) return;
    if (!trimmed) {
      try {
        await actions.saveCategoryPatch?.(data.id, { amount_leaf: null });
      } catch (err) {
        actions.showError?.(err);
      }
      return;
    }
    const numeric = Number(trimmed);
    if (Number.isNaN(numeric)) {
      actions.showError?.('Amount must be a number');
      setValue(original);
      return;
    }
    try {
      await actions.saveCategoryPatch?.(data.id, { amount_leaf: numeric });
    } catch (err) {
      actions.showError?.(err);
      setValue(original);
    }
  }, [actions, canEdit, data.amount_leaf, data.id, value]);

  const handleKeyDown = useCallback((evt) => {
    if (evt.key === 'Enter') {
      evt.preventDefault();
      evt.currentTarget.blur();
    }
  }, []);

  return React.createElement(
    'div',
    { className: 'bt-amountWrap', 'data-bt-stop-toggle': '1' },
    React.createElement('span', { className: 'bt-amountLabel' }, 'Amount'),
    React.createElement('input', {
      className: 'bt-amountInput',
      value,
      onChange: (evt) => setValue(evt.target.value),
      onBlur: handleBlur,
      onKeyDown: handleKeyDown,
      inputMode: 'decimal',
      placeholder: '0.00',
      readOnly: !canEdit,
      'aria-label': 'Amount',
    })
  );
}

function AmountRegion({ node, actions }) {
  const data = node?.data ?? {};
  const type = data.type || node?.type;
  if (type === 'project') {
    return React.createElement(
      'div',
      { className: 'bt-amountWrap', 'data-bt-stop-toggle': '1' },
      React.createElement('span', { className: 'bt-amountLabel' }, 'Subtotal'),
      React.createElement('span', { className: 'bt-amountValue' }, formatCurrency(actions, data.rollup_amount))
    );
  }
  if (type === 'category') {
    if (data.is_leaf) {
      return React.createElement(LeafAmountEditor, { node, actions });
    }
    return React.createElement(
      'div',
      { className: 'bt-amountWrap', 'data-bt-stop-toggle': '1' },
      React.createElement('span', { className: 'bt-amountLabel' }, 'Subtotal'),
      React.createElement('span', { className: 'bt-amountValue' }, formatCurrency(actions, data.rollup_amount))
    );
  }
  return null;
}

function RowActions({ node, actions }) {
  const data = node?.data ?? {};
  const type = data.type || node?.type;
  const projectId = type === 'project' ? data.id : data.project_id;
  const projectNode = type === 'project'
    ? data
    : (projectId != null ? actions?.getProjectNode?.(projectId) : null);

  const canAdd = typeof actions?.openCategoryModal === 'function' && projectNode;
  const canMove = type === 'category' && typeof actions?.openMoveCategoryModal === 'function';
  const canInspect = typeof actions?.openInspector === 'function';

  const handleAdd = useCallback(() => {
    if (!canAdd) return;
    if (type === 'project') {
      actions.openCategoryModal?.({ projectNode: data, parentCategory: null });
    } else if (type === 'category') {
      actions.openCategoryModal?.({ projectNode, parentCategory: data });
    }
  }, [actions, canAdd, data, projectNode, type]);

  const handleMove = useCallback(() => {
    if (!canMove) return;
    actions.openMoveCategoryModal?.(data);
  }, [actions, canMove, data]);

  const handleInspect = useCallback(() => {
    if (!canInspect) return;
    actions.openInspector?.(data);
  }, [actions, canInspect, data]);

  if (!canAdd && !canMove && !canInspect) {
    return null;
  }

  const buttons = [];

  if (canAdd) {
    buttons.push(
      React.createElement(
        'button',
        {
          type: 'button',
          className: 'bt-action-btn',
          onClick: (evt) => {
            evt.stopPropagation();
            handleAdd();
          },
        },
        '+ Item'
      )
    );
  }

  if (canMove) {
    buttons.push(
      React.createElement(
        'button',
        {
          type: 'button',
          className: 'bt-action-btn',
          onClick: (evt) => {
            evt.stopPropagation();
            handleMove();
          },
        },
        'Move'
      )
    );
  }

  if (canInspect) {
    buttons.push(
      React.createElement(
        'button',
        {
          type: 'button',
          className: 'icon-btn',
          'aria-label': 'Open inspector',
          onClick: (evt) => {
            evt.stopPropagation();
            handleInspect();
          },
        },
        'i'
      )
    );
  }

  return React.createElement(
    'div',
    { className: 'ledger-actions bt-actions', 'data-bt-stop-toggle': '1' },
    ...buttons
  );
}

function MainColumns({ node, actions }) {
  const data = node?.data ?? {};
  const showAssets = data.type === 'project';
  const columns = [
    React.createElement(
      'div',
      { className: 'bt-col bt-col--name', key: 'name' },
      React.createElement('span', { className: 'bt-type' }, typeLabel(data)),
      React.createElement(NameField, { node, actions })
    ),
    React.createElement(
      'div',
      { className: 'bt-col bt-col--tags', key: 'tags' },
      React.createElement('span', { className: 'bt-colLabel' }, 'Tags'),
      React.createElement(TagRegion, { node, actions })
    ),
  ];

  if (showAssets) {
    columns.push(
      React.createElement(
        'div',
        { className: 'bt-col bt-col--assets', key: 'assets' },
        React.createElement(AssetRegion, { node, actions })
      )
    );
  }

  return React.createElement(
    'div',
    {
      className: 'bt-mainContent',
      'data-has-assets': showAssets ? 'true' : 'false',
      'data-bt-stop-toggle': '1',
    },
    ...columns
  );
}

function defaultRenderRow(args) {
  return {
    rowClassName: 'bt-row--detailed',
    main: React.createElement(MainColumns, { ...args }),
    end: [
      React.createElement(AmountRegion, { ...args, key: 'amount' }),
      React.createElement(RowActions, { ...args, key: 'actions' }),
    ],
  };
}

const TreeNode = React.memo(function TreeNode({
  node,
  depth,
  expandedSet,
  toggleNode,
  actions,
  renderRow,
  focusable = false,
}) {
  if (!node) return null;
  const key = getNodeKey(node);
  const childNodes = Array.isArray(node.children) ? node.children.filter(Boolean) : [];
  const hasChildren = childNodes.length > 0;
  const isLeaf = node.isLeaf === true || !hasChildren;
  const expanded = hasChildren ? expandedSet.has(key) : false;

  const handleToggle = useCallback((event) => {
    event.stopPropagation();
    if (!hasChildren) return;
    toggleNode(node, !expanded);
  }, [hasChildren, expanded, node, toggleNode]);

  const handleRowClick = useCallback((event) => {
    if (!hasChildren) return;
    if (shouldSuppressToggle(event.target, event.currentTarget)) return;
    toggleNode(node, !expanded);
  }, [hasChildren, expanded, node, toggleNode]);

  let rowClassName = 'bt-row';
  let mainChildren = [];
  let endChildren = [];

  if (typeof renderRow === 'function') {
    const custom = renderRow({ node, depth, actions, expanded, hasChildren });
    if (custom && typeof custom === 'object') {
      if (custom.rowClassName) {
        rowClassName = `${rowClassName} ${custom.rowClassName}`.trim();
      }
      if (custom.main !== undefined) {
        mainChildren = normalizeArray(custom.main);
      }
      if (custom.end !== undefined) {
        endChildren = normalizeArray(custom.end);
      }
    }
  }

  const depthValue = Number.isFinite(depth) ? depth : 0;

  const liProps = {
    className: 'bt-node',
    role: 'treeitem',
    'aria-level': depth + 1,
    'data-depth': depth,
    'data-leaf': String(isLeaf),
    'data-has-children': String(hasChildren),
    tabIndex: -1,
    style: { '--bt-depth': depthValue },
  };
  if (key) {
    liProps['data-key'] = key;
  }
  if (node.type) {
    liProps['data-type'] = node.type;
    rowClassName += ` bt-row--${node.type}`;
  }
  if (hasChildren) {
    liProps['aria-expanded'] = String(expanded);
    liProps['data-expanded'] = String(expanded);
  }

  const toggleProps = {
    type: 'button',
    className: 'bt-toggle',
    'aria-label': hasChildren ? (expanded ? 'Collapse' : 'Expand') : 'Leaf node',
    disabled: !hasChildren,
    'data-bt-stop-toggle': '1',
    onClick: handleToggle,
  };

  const mainProps = {
    className: 'bt-main',
  };

  const endProps = {
    className: 'bt-end',
  };

  const rowProps = {
    className: rowClassName,
    tabIndex: focusable ? 0 : -1,
    onClick: handleRowClick,
    'data-depth': depth,
    style: { '--bt-depth': depthValue },
  };

  if (!mainChildren.length) {
    mainChildren = [React.createElement('span', { className: 'bt-title-fallback' }, node.label || '')];
  }

  const children = [
    React.createElement(
      'div',
      rowProps,
      React.createElement('span', { className: 'bt-toggle-hit', 'aria-hidden': 'true' }),
      React.createElement('button', toggleProps),
      React.createElement('div', mainProps, ...mainChildren),
      React.createElement('div', endProps, ...endChildren)
    ),
  ];

  if (hasChildren) {
    children.push(
      React.createElement(
        'ul',
        {
          className: 'bt-children',
          role: 'group',
          hidden: !expanded,
          style: { '--bt-depth': depthValue + 1 },
        },
        childNodes.map((child, index) =>
          React.createElement(TreeNode, {
            node: child,
            depth: depth + 1,
            key: getNodeKey(child) || `${key || 'node'}:${index}`,
            expandedSet,
            toggleNode,
            actions,
            renderRow,
            focusable: false,
          })
        )
      )
    );
  }

  return React.createElement('li', liProps, ...children);
});

function TreeRoot({
  nodes = [],
  expandedKeys = [],
  onToggle,
  actions,
  renderRow,
  role = 'tree',
}) {
  const normalizedExpandedKeys = Array.isArray(expandedKeys) ? expandedKeys : [];
  const expansionSignature = useMemo(() => listToSignature(normalizedExpandedKeys), [normalizedExpandedKeys]);
  const normalizedExpandedKeyStrings = useMemo(() => normalizedExpandedKeys.map(String), [expansionSignature]);

  const [expandedSet, setExpandedSet] = useState(() => new Set(normalizedExpandedKeyStrings));
  const lastPropSignatureRef = useRef(expansionSignature);

  useEffect(() => {
    if (lastPropSignatureRef.current === expansionSignature) return;
    lastPropSignatureRef.current = expansionSignature;
    setExpandedSet(new Set(normalizedExpandedKeyStrings));
  }, [expansionSignature, normalizedExpandedKeyStrings]);

  const toggleNode = useCallback((node, next) => {
    const key = getNodeKey(node);
    if (!key) return;
    setExpandedSet((prev) => {
      const nextSet = new Set(prev);
      if (next) {
        if (nextSet.has(key)) return prev;
        nextSet.add(key);
      } else {
        if (!nextSet.has(key)) return prev;
        nextSet.delete(key);
      }
      return nextSet;
    });
    if (typeof onToggle === 'function') {
      onToggle(node, next);
    }
  }, [onToggle]);

  const items = Array.isArray(nodes) ? nodes.filter(Boolean) : [];
  const rowRenderer = renderRow ?? defaultRenderRow;

  return React.createElement(
    'ul',
    { className: 'bt-tree', role },
    items.map((node, index) =>
      React.createElement(TreeNode, {
        node,
        depth: 0,
        key: getNodeKey(node) || `root-${index}`,
        expandedSet,
        toggleNode,
        actions,
        renderRow: rowRenderer,
        focusable: index === 0,
      })
    )
  );
}

function ensureRoot(container) {
  if (!container) throw new Error('BudgetTreeReact.render requires a container');
  let root = container.__btRoot;
  if (!root) {
    root = ReactDOM.createRoot(container);
    container.__btRoot = root;
  }
  return root;
}

function render(container, props) {
  const root = ensureRoot(container);
  root.render(React.createElement(TreeRoot, props || {}));
}

function unmount(container) {
  const root = container?.__btRoot;
  if (root) {
    root.unmount();
    delete container.__btRoot;
  }
}

export { TreeRoot, render, unmount };

if (typeof window !== 'undefined') {
  window.BudgetTreeReact = { render, unmount };
}
