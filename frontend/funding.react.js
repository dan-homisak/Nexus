import React from './vendor/react.js';
import ReactDOM from './vendor/react-dom-client.js';

const {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} = React;

function makeNodeKey(entity) {
  if (!entity) return '';
  if (entity.type && entity.id != null) return `${entity.type}:${entity.id}`;
  if (entity.id != null) return String(entity.id);
  return entity.name || entity.label || Math.random().toString(36).slice(2);
}

function toAmount(fmtCurrency, value) {
  try {
    return fmtCurrency(Number(value || 0));
  } catch (err) {
    return '$0.00';
  }
}

function formatDateTime(value) {
  if (!value) return '—';
  try {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString();
  } catch (err) {
    return String(value);
  }
}

function buildHierarchy(nodes = []) {
  if (!nodes.length) return null;
  const budget = nodes.find((node) => node.type === 'budget');
  if (!budget) return null;

  const projectMap = new Map();
  const categoryMap = new Map();

  nodes.forEach((node) => {
    if (node.type === 'project') {
      node.children = [];
      projectMap.set(node.id, node);
    } else if (node.type === 'category') {
      node.children = [];
      categoryMap.set(node.id, node);
    }
  });

  nodes.forEach((node) => {
    if (node.type !== 'category') return;
    if (node.parent_id) {
      const parent = categoryMap.get(node.parent_id);
      if (parent) {
        parent.children.push(node);
        return;
      }
    }
    const parentProject = projectMap.get(node.project_id || node.item_project_id);
    if (parentProject) parentProject.children.push(node);
  });

  budget.children = Array.from(projectMap.values());
  return budget;
}

function flattenRows(root, fmtCurrency) {
  if (!root) return [];
  const rows = [];
  const walk = (node, path = []) => {
    if (!node) return;
    const data = node.data || node;
    const name = data.name || node.label || 'Untitled';
    const nextPath = data.type === 'budget' ? path : [...path, name];
    if (data.type !== 'budget') {
      rows.push({
        id: makeNodeKey(data),
        type: data.type || node.type,
        name,
        path: nextPath.join(' / '),
        leafAmount: data.amount_leaf,
        rollupAmount: data.rollup_amount,
        leafDisplay: data.amount_leaf != null ? toAmount(fmtCurrency, data.amount_leaf) : '—',
        rollupDisplay: data.rollup_amount != null ? toAmount(fmtCurrency, data.rollup_amount) : '—',
      });
    }
    (node.children || []).forEach((child) => walk(child, nextPath));
  };
  walk(root, []);
  return rows;
}

function collectKeys(node) {
  if (!node) return [];
  const keys = [makeNodeKey(node)];
  (node.children || []).forEach((child) => {
    keys.push(...collectKeys(child));
  });
  return keys;
}

function findNodeByKey(node, key) {
  if (!node || !key) return null;
  if (makeNodeKey(node) === key) return node;
  for (const child of node.children || []) {
    const found = findNodeByKey(child, key);
    if (found) return found;
  }
  return null;
}

function getTagScope(node) {
  const data = node.data || node;
  if (data.type === 'project') return { entity_type: 'item_project', entity_id: data.id };
  if (data.type === 'category') return { entity_type: 'category', entity_id: data.id };
  if (data.type === 'budget') return { entity_type: 'budget', entity_id: data.id };
  return null;
}

function FundingApp({ api, fmtCurrency, showError, fundingState }) {
  const [budgets, setBudgets] = useState(() => fundingState?.budgets || []);
  const [searchTerm, setSearchTerm] = useState(fundingState?.searchTerm || '');
  const [selectedBudgetId, setSelectedBudgetId] = useState(fundingState?.selectedBudgetId || null);
  const [hierarchy, setHierarchy] = useState(() => fundingState?.currentHierarchy || null);
  const [gridRows, setGridRows] = useState(() => flattenRows(fundingState?.currentHierarchy || null, fmtCurrency));
  const [loadingBudgets, setLoadingBudgets] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [selectedNodeKey, setSelectedNodeKey] = useState(null);
  const [expandedKeys, setExpandedKeys] = useState(new Set());

  const searchTimerRef = useRef(null);

  const refreshGrid = useCallback((root) => {
    setGridRows(flattenRows(root, fmtCurrency));
  }, [fmtCurrency]);

  const loadBudgetDetail = useCallback(async (budgetId) => {
    if (!budgetId) {
      setHierarchy(null);
      refreshGrid(null);
      setExpandedKeys(new Set());
      setSelectedNodeKey(null);
      return;
    }
    setLoadingDetail(true);
    try {
      const nodes = await api(`/api/budgets/${budgetId}/tree?include=tags,paths,assets`);
      fundingState.budgetTree = nodes;
      const root = buildHierarchy(nodes);
      fundingState.currentHierarchy = root;
      setHierarchy(root);
      refreshGrid(root);
      if (root) {
        const allKeys = new Set(collectKeys(root));
        setExpandedKeys(allKeys);
        if (!selectedNodeKey || !allKeys.has(selectedNodeKey)) {
          const firstChild = root.children?.[0];
          setSelectedNodeKey(firstChild ? makeNodeKey(firstChild) : makeNodeKey(root));
        }
      } else {
        setSelectedNodeKey(null);
      }
    } catch (err) {
      showError(err);
    } finally {
      setLoadingDetail(false);
    }
  }, [api, fundingState, refreshGrid, selectedNodeKey, showError]);

  const loadBudgets = useCallback(async (term = '') => {
    setLoadingBudgets(true);
    try {
      const query = term
        ? `/api/budgets?include=stats,tags&q=${encodeURIComponent(term)}`
        : '/api/budgets?include=stats,tags';
      const result = await api(query);
      setBudgets(result);
      fundingState.budgets = result;
      fundingState.filteredBudgets = result;
      fundingState.searchTerm = term;
      fundingState.budgetMap = new Map(result.map((b) => [b.id, b]));
      if (!result.length) {
        setSelectedBudgetId(null);
        fundingState.selectedBudgetId = null;
        setHierarchy(null);
        refreshGrid(null);
        setExpandedKeys(new Set());
        setSelectedNodeKey(null);
        return;
      }
      const target = result.find((b) => b.id === selectedBudgetId) || result[0];
      if (target) {
        setSelectedBudgetId(target.id);
        fundingState.selectedBudgetId = target.id;
      }
    } catch (err) {
      showError(err);
    } finally {
      setLoadingBudgets(false);
    }
  }, [api, fundingState, refreshGrid, selectedBudgetId, showError]);

  useEffect(() => {
    loadBudgets(searchTerm);
    return () => {
      if (searchTimerRef.current) {
        clearTimeout(searchTimerRef.current);
        searchTimerRef.current = null;
      }
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selectedBudgetId) {
      setHierarchy(null);
      refreshGrid(null);
      setExpandedKeys(new Set());
      setSelectedNodeKey(null);
      return;
    }
    loadBudgetDetail(selectedBudgetId);
  }, [loadBudgetDetail, refreshGrid, selectedBudgetId]);

  useEffect(() => {
    fundingState.refreshTreeOnly = async () => {
      if (!selectedBudgetId) return;
      await loadBudgetDetail(selectedBudgetId);
    };
    fundingState.refreshCurrentBudget = async () => {
      await loadBudgets(searchTerm);
    };
    return () => {
      fundingState.refreshTreeOnly = undefined;
      fundingState.refreshCurrentBudget = undefined;
    };
  }, [fundingState, loadBudgetDetail, loadBudgets, searchTerm, selectedBudgetId]);

  const handleSelectBudget = useCallback((budgetId) => {
    setSelectedBudgetId(budgetId);
    fundingState.selectedBudgetId = budgetId;
  }, [fundingState]);

  const handleSearchChange = useCallback((value) => {
    setSearchTerm(value);
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    searchTimerRef.current = setTimeout(() => {
      loadBudgets(value.trim());
    }, 220);
  }, [loadBudgets]);

  const selectedBudget = useMemo(() => {
    if (!selectedBudgetId) return null;
    return budgets.find((b) => b.id === selectedBudgetId) || null;
  }, [budgets, selectedBudgetId]);

  const selectedNode = useMemo(() => {
    if (!hierarchy || !selectedNodeKey) return null;
    return findNodeByKey(hierarchy, selectedNodeKey);
  }, [hierarchy, selectedNodeKey]);

  const handleBudgetFieldSave = useCallback(async (field, value) => {
    if (!selectedBudgetId) return;
    try {
      await api(`/api/budgets/${selectedBudgetId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [field]: value }),
      });
      await loadBudgetDetail(selectedBudgetId);
      await loadBudgets(searchTerm);
    } catch (err) {
      showError(err);
    }
  }, [api, loadBudgetDetail, loadBudgets, searchTerm, selectedBudgetId, showError]);

  const handleRenameNode = useCallback(async (node, nextName) => {
    const data = node?.data || node;
    if (!data || !nextName || !nextName.trim()) return;
    const payload = { name: nextName.trim() };
    try {
      if (data.type === 'project') {
        await api(`/api/item-projects/${data.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      } else if (data.type === 'category') {
        await api(`/api/categories/${data.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      }
      await loadBudgetDetail(selectedBudgetId);
    } catch (err) {
      showError(err);
    }
  }, [api, loadBudgetDetail, selectedBudgetId, showError]);

  const handleUpdateAmount = useCallback(async (node, amount) => {
    const data = node?.data || node;
    if (!data || data.type !== 'category') return;
    const numeric = amount === '' ? null : Number(amount);
    if (numeric !== null && Number.isNaN(numeric)) {
      showError(new Error('Amount must be numeric.'));
      return;
    }
    try {
      await api(`/api/categories/${data.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ amount_leaf: numeric }),
      });
      await loadBudgetDetail(selectedBudgetId);
    } catch (err) {
      showError(err);
    }
  }, [api, loadBudgetDetail, selectedBudgetId, showError]);

  const handleTagAdd = useCallback(async (node, tagName) => {
    const scope = getTagScope(node);
    if (!scope) return;
    const cleaned = tagName.trim();
    if (!cleaned) return;
    try {
      const existing = await api(`/api/tags?q=${encodeURIComponent(cleaned)}`);
      let tag = existing.find((entry) => entry.name.toLowerCase() === cleaned.toLowerCase());
      if (!tag) {
        tag = await api('/api/tags', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: cleaned, actor: 'UI' }),
        });
      }
      await api('/api/tags/assign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tag_id: tag.id, entity_type: scope.entity_type, entity_id: scope.entity_id, actor: 'UI' }),
      });
      await loadBudgetDetail(selectedBudgetId);
    } catch (err) {
      showError(err);
    }
  }, [api, loadBudgetDetail, selectedBudgetId, showError]);

  const handleTagRemove = useCallback(async (node, tagId) => {
    const scope = getTagScope(node);
    if (!scope) return;
    try {
      await api('/api/tags/assign', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tag_id: tagId, entity_type: scope.entity_type, entity_id: scope.entity_id, actor: 'UI' }),
      });
      await loadBudgetDetail(selectedBudgetId);
    } catch (err) {
      showError(err);
    }
  }, [api, loadBudgetDetail, selectedBudgetId, showError]);

  const handleAssetAdd = useCallback(async (node, assetName) => {
    const data = node?.data || node;
    if (!data || data.type !== 'project') return;
    const cleaned = assetName.trim();
    if (!cleaned) return;
    try {
      const matches = await api(`/api/line-assets?q=${encodeURIComponent(cleaned)}`);
      let asset = matches.find((item) => item.name.toLowerCase() === cleaned.toLowerCase());
      if (!asset) {
        asset = await api('/api/line-assets', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: cleaned }),
        });
      }
      await api(`/api/item-projects/${data.id}/line-assets`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ line_asset_id: asset.id }),
      });
      await loadBudgetDetail(selectedBudgetId);
    } catch (err) {
      showError(err);
    }
  }, [api, loadBudgetDetail, selectedBudgetId, showError]);

  const handleAssetRemove = useCallback(async (node, assetId) => {
    const data = node?.data || node;
    if (!data || data.type !== 'project') return;
    try {
      await api(`/api/item-projects/${data.id}/line-assets/${assetId}`, {
        method: 'DELETE',
      });
      await loadBudgetDetail(selectedBudgetId);
    } catch (err) {
      showError(err);
    }
  }, [api, loadBudgetDetail, selectedBudgetId, showError]);

  const handleAddChild = useCallback(async (node, name) => {
    const data = node?.data || node;
    const cleaned = name.trim();
    if (!cleaned) return;
    try {
      if (!data || data.type === 'budget') {
        await api('/api/item-projects', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ budget_id: selectedBudgetId, name: cleaned }),
        });
      } else {
        const payload = {
          name: cleaned,
          project_id: data.type === 'project' ? data.id : data.project_id || data.item_project_id,
          budget_id: selectedBudgetId,
          parent_id: data.type === 'category' ? data.id : null,
          is_leaf: true,
          amount_leaf: null,
        };
        await api('/api/categories', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      }
      await loadBudgetDetail(selectedBudgetId);
    } catch (err) {
      showError(err);
    }
  }, [api, loadBudgetDetail, selectedBudgetId, showError]);

  const handleMoveCategory = useCallback(async (node, targetId) => {
    const data = node?.data || node;
    if (!data || data.type !== 'category') return;
    const parsed = targetId === '' ? null : Number(targetId);
    if (parsed !== null && Number.isNaN(parsed)) {
      showError(new Error('Target must be numeric.'));
      return;
    }
    try {
      await api(`/api/categories/${data.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ parent_id: parsed }),
      });
      await loadBudgetDetail(selectedBudgetId);
    } catch (err) {
      showError(err);
    }
  }, [api, loadBudgetDetail, selectedBudgetId, showError]);

  const handleToggle = useCallback((key) => {
    setExpandedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  return (
    React.createElement('div', { className: 'funding-shell' },
      React.createElement(BudgetSidebar, {
        budgets,
        loading: loadingBudgets,
        searchTerm,
        onSearch: handleSearchChange,
        onSelect: handleSelectBudget,
        selectedId: selectedBudgetId,
        fmtCurrency,
      }),
      React.createElement('section', { className: 'funding-ledger funding-ledger-react' },
        loadingDetail
          ? React.createElement('div', { className: 'funding-empty' }, 'Loading details…')
          : React.createElement(React.Fragment, null,
              React.createElement(SummaryCard, {
                budget: selectedBudget,
                fmtCurrency,
                onSave: handleBudgetFieldSave,
              }),
              React.createElement('div', { className: 'ledger-body ledger-body-react' },
                React.createElement('div', { className: 'ledger-main' },
                  React.createElement(HierarchyView, {
                    root: hierarchy,
                    fmtCurrency,
                    expandedKeys,
                    selectedKey: selectedNodeKey,
                    onToggle: handleToggle,
                    onSelect: setSelectedNodeKey,
                  }),
                  React.createElement(InspectorPanel, {
                    node: selectedNode,
                    fmtCurrency,
                    onRename: handleRenameNode,
                    onAmountChange: handleUpdateAmount,
                    onTagAdd: handleTagAdd,
                    onTagRemove: handleTagRemove,
                    onAssetAdd: handleAssetAdd,
                    onAssetRemove: handleAssetRemove,
                    onAddChild: handleAddChild,
                    onMoveCategory: handleMoveCategory,
                  })
                ),
                React.createElement(DataTable, { rows: gridRows })
              )
            )
      )
    )
  );
}

function BudgetSidebar({ budgets, loading, searchTerm, onSearch, onSelect, selectedId, fmtCurrency }) {
  return (
    React.createElement('aside', { className: 'funding-sidebar' },
      React.createElement('div', { className: 'funding-toolbar' },
        React.createElement('input', {
          className: 'input',
          placeholder: 'Search budgets…',
          value: searchTerm,
          onChange: (evt) => onSearch(evt.target.value),
        })
      ),
      loading
        ? React.createElement('div', { className: 'funding-list funding-list-loading' }, 'Loading…')
        : React.createElement('div', { className: 'funding-list' },
            budgets.length === 0
              ? React.createElement('div', { className: 'funding-list-empty' }, 'No funding sources found.')
              : budgets.map((budget) => (
                  React.createElement('button', {
                    key: budget.id,
                    className: `funding-item${budget.id === selectedId ? ' active' : ''}`,
                    type: 'button',
                    onClick: () => onSelect(budget.id),
                  },
                    React.createElement('div', { className: 'funding-item-name' }, budget.name),
                    React.createElement('div', { className: 'funding-item-total' }, toAmount(fmtCurrency, budget.budget_amount_cache)),
                    React.createElement('div', { className: 'funding-item-metrics' },
                      React.createElement('span', { className: 'funding-item-metric' }, 'Categories', React.createElement('strong', null, budget.stats?.category_count ?? '—')),
                      React.createElement('span', { className: 'funding-item-metric' }, 'Leaves', React.createElement('strong', null, budget.stats?.leaf_count ?? '—')),
                      React.createElement('span', { className: 'funding-item-metric' }, 'Entries', React.createElement('strong', null, budget.stats?.entry_count ?? '—'))
                    ),
                    (budget.tags?.direct?.length)
                      ? React.createElement('div', { className: 'funding-item-tags' },
                          budget.tags.direct.slice(0, 4).map((tag) => (
                            React.createElement('span', { key: tag.id }, `#${tag.name}`)
                          ))
                        )
                      : null
                  )
                ))
          )
    )
  );
}

function SummaryCard({ budget, fmtCurrency, onSave }) {
  const [owner, setOwner] = useState(budget?.owner || '');
  const [costCenter, setCostCenter] = useState(!!budget?.is_cost_center);
  const [closure, setClosure] = useState(budget?.closure_date ? String(budget.closure_date).slice(0, 10) : '');
  const [description, setDescription] = useState(budget?.description || '');

  useEffect(() => {
    setOwner(budget?.owner || '');
    setCostCenter(!!budget?.is_cost_center);
    setClosure(budget?.closure_date ? String(budget.closure_date).slice(0, 10) : '');
    setDescription(budget?.description || '');
  }, [budget?.id]);

  if (!budget) {
    return React.createElement('div', { className: 'ledger-budget-card ledger-budget-card-react' },
      React.createElement('div', { className: 'funding-empty' }, 'Select a funding source to inspect.')
    );
  }

  return (
    React.createElement('div', { className: 'ledger-budget-card ledger-budget-card-react' },
      React.createElement('div', { className: 'summary-grid' },
        React.createElement(InfoField, {
          label: 'Owner',
          value: owner,
          onChange: setOwner,
          onCommit: (value) => onSave('owner', value?.trim() || null),
        }),
        React.createElement(ToggleField, {
          label: 'Cost Center',
          checked: costCenter,
          onToggle: (next) => {
            setCostCenter(next);
            onSave('is_cost_center', next);
          },
        }),
        React.createElement(DateField, {
          label: 'Closure',
          value: closure,
          onCommit: (value) => {
            setClosure(value || '');
            onSave('closure_date', value || null);
          },
        }),
        React.createElement(StaticField, {
          label: 'Budget',
          value: toAmount(fmtCurrency, budget.budget_amount_cache),
        })
      ),
      React.createElement(TextAreaField, {
        label: 'Description',
        value: description,
        onChange: setDescription,
        onCommit: (value) => onSave('description', value?.trim() || null),
      }),
      React.createElement('div', { className: 'summary-tags' },
        (budget.tags?.direct || []).map((tag) => React.createElement('span', { key: tag.id }, `#${tag.name}`))
      )
    )
  );
}

function InfoField({ label, value, onChange, onCommit }) {
  return (
    React.createElement('label', { className: 'info-field' },
      React.createElement('span', { className: 'info-field-label' }, label),
      React.createElement('input', {
        className: 'info-field-input',
        value: value ?? '',
        onChange: (evt) => onChange?.(evt.target.value),
        onBlur: (evt) => onCommit?.(evt.target.value),
      })
    )
  );
}

function DateField({ label, value, onCommit }) {
  return (
    React.createElement('label', { className: 'info-field' },
      React.createElement('span', { className: 'info-field-label' }, label),
      React.createElement('input', {
        type: 'date',
        className: 'info-field-input',
        value: value || '',
        onChange: (evt) => onCommit?.(evt.target.value || null),
      })
    )
  );
}

function ToggleField({ label, checked, onToggle }) {
  return (
    React.createElement('label', { className: 'info-field toggle-field' },
      React.createElement('span', { className: 'info-field-label' }, label),
      React.createElement('input', {
        type: 'checkbox',
        checked,
        onChange: (evt) => onToggle?.(evt.target.checked),
      })
    )
  );
}

function TextAreaField({ label, value, onChange, onCommit }) {
  return (
    React.createElement('label', { className: 'info-field textarea-field' },
      React.createElement('span', { className: 'info-field-label' }, label),
      React.createElement('textarea', {
        className: 'info-field-input info-field-textarea',
        value: value || '',
        rows: 3,
        onChange: (evt) => onChange?.(evt.target.value),
        onBlur: (evt) => onCommit?.(evt.target.value),
      })
    )
  );
}

function StaticField({ label, value }) {
  return (
    React.createElement('label', { className: 'info-field static-field' },
      React.createElement('span', { className: 'info-field-label' }, label),
      React.createElement('span', { className: 'info-field-value' }, value)
    )
  );
}

function HierarchyView({ root, fmtCurrency, expandedKeys, selectedKey, onToggle, onSelect }) {
  if (!root) {
    return React.createElement('div', { className: 'hierarchy-empty' }, 'Pick a budget to view its hierarchy.');
  }
  if (!(root.children || []).length) {
    return React.createElement('div', { className: 'hierarchy-empty' }, 'This budget has no projects yet.');
  }
  return (
    React.createElement('div', { className: 'hierarchy-tree' },
      root.children.map((child) => (
        React.createElement(HierarchyNode, {
          key: makeNodeKey(child),
          node: child,
          depth: 0,
          fmtCurrency,
          expandedKeys,
          selectedKey,
          onToggle,
          onSelect,
        })
      ))
    )
  );
}

function HierarchyNode({ node, depth, fmtCurrency, expandedKeys, selectedKey, onToggle, onSelect }) {
  const data = node.data || node;
  const key = makeNodeKey(node);
  const children = node.children || [];
  const isOpen = expandedKeys.has(key) || !children.length;
  const amount = data.type === 'category' || data.type === 'project'
    ? toAmount(fmtCurrency, data.rollup_amount)
    : toAmount(fmtCurrency, data.amount_leaf);

  const handleClick = () => {
    if (children.length) onToggle(key);
    onSelect(key);
  };

  return (
    React.createElement('div', { className: 'hierarchy-node', style: { marginLeft: depth ? `${depth * 16}px` : 0 } },
      React.createElement('div', {
        className: `hierarchy-row${!children.length ? ' leaf' : ''}${selectedKey === key ? ' active' : ''}`,
        onClick: handleClick,
      },
        React.createElement('div', { className: 'hierarchy-main' },
          children.length
            ? React.createElement('span', { className: 'hierarchy-toggle' }, isOpen ? '▾' : '▸')
            : React.createElement('span', { className: 'hierarchy-toggle-placeholder' }, '•'),
          React.createElement('span', { className: `tree-pill tree-pill-${data.type || 'node'}` }, (data.type || 'node').toUpperCase()),
          React.createElement('span', { className: 'tree-name' }, data.name || node.label || 'Untitled')
        ),
        React.createElement('div', { className: 'hierarchy-meta' }, amount)
      ),
      isOpen && children.length
        ? React.createElement('div', { className: 'hierarchy-children' },
            children.map((child) => (
              React.createElement(HierarchyNode, {
                key: makeNodeKey(child),
                node: child,
                depth: depth + 1,
                fmtCurrency,
                expandedKeys,
                selectedKey,
                onToggle,
                onSelect,
              })
            ))
          )
        : null
    )
  );
}

function InspectorPanel({
  node,
  fmtCurrency,
  onRename,
  onAmountChange,
  onTagAdd,
  onTagRemove,
  onAssetAdd,
  onAssetRemove,
  onAddChild,
  onMoveCategory,
}) {
  if (!node) {
    return React.createElement('aside', { className: 'inspector-panel' },
      React.createElement('div', { className: 'inspector-placeholder' }, 'Select a project or item to view details.')
    );
  }

  const data = node.data || node;
  const isProject = data.type === 'project';
  const isCategory = data.type === 'category';
  const tags = data.tags || {};
  const assets = data.assets?.items || [];

  const historyEntries = [];

  if (data.created_at) {
    historyEntries.push({ id: 'created', label: 'Created', detail: formatDateTime(data.created_at) });
  }
  if (data.updated_at && data.updated_at !== data.created_at) {
    historyEntries.push({ id: 'updated', label: 'Last Updated', detail: formatDateTime(data.updated_at) });
  }
  if (isCategory && data.amount_leaf != null) {
    historyEntries.push({ id: 'leaf', label: 'Leaf Amount', detail: toAmount(fmtCurrency, data.amount_leaf) });
  }
  if (isProject && assets.length) {
    historyEntries.push({ id: 'assets', label: 'Assets Linked', detail: assets.map((asset) => asset.name).join(', ') });
  }
  if ((tags.direct || []).length) {
    historyEntries.push({ id: 'tags-direct', label: 'Direct Tags', detail: tags.direct.map((tag) => `#${tag.name}`).join(', ') });
  }
  if ((tags.inherited || []).length) {
    historyEntries.push({ id: 'tags-inherited', label: 'Inherited Tags', detail: tags.inherited.map((tag) => `#${tag.name}`).join(', ') });
  }
  if (!historyEntries.length) {
    historyEntries.push({ id: 'empty', label: 'No history yet', detail: 'Updates will appear here after edits.' });
  }

  const handleRename = (evt) => {
    const next = evt.target.value;
    onRename?.(node, next);
  };

  const handleAmount = (evt) => {
    onAmountChange?.(node, evt.target.value);
  };

  const addTag = () => {
    const value = window.prompt('Tag name (existing or new)');
    if (value) onTagAdd?.(node, value);
  };

  const addAsset = () => {
    const value = window.prompt('Asset name');
    if (value) onAssetAdd?.(node, value);
  };

  const addChild = () => {
    const value = window.prompt(isProject ? 'New item name' : 'New child item name');
    if (value) onAddChild?.(node, value);
  };

  const moveCategory = () => {
    if (!isCategory) return;
    const value = window.prompt('Move to category id (blank for project root)');
    if (value !== null) onMoveCategory?.(node, value.trim());
  };

  const sections = [];

  sections.push(
    React.createElement('div', { className: 'inspector-section', key: 'info' },
      React.createElement('h3', { className: 'inspector-heading' }, `${(data.type || 'node').toUpperCase()} DETAILS`),
      React.createElement('label', { className: 'info-field' },
        React.createElement('span', { className: 'info-field-label' }, 'Name'),
        React.createElement('input', {
          className: 'info-field-input',
          defaultValue: data.name || node.label || '',
          onBlur: handleRename,
        })
      ),
      (isCategory && data.is_leaf)
        ? React.createElement('label', { className: 'info-field', key: 'amount' },
            React.createElement('span', { className: 'info-field-label' }, 'Amount'),
            React.createElement('input', {
              className: 'info-field-input',
              type: 'number',
              defaultValue: data.amount_leaf != null ? data.amount_leaf : '',
              onBlur: handleAmount,
            })
          )
        : null,
      React.createElement('div', { className: 'info-field static-field' },
        React.createElement('span', { className: 'info-field-label' }, 'Subtotal'),
        React.createElement('span', { className: 'info-field-value' }, toAmount(fmtCurrency, data.rollup_amount))
      )
    )
  );

  const tagChildren = [];
  tagChildren.push(
    React.createElement('div', { className: 'inspector-tags-group', key: 'direct' },
      React.createElement('div', { className: 'inspector-tags-label' }, 'Direct'),
      React.createElement('div', { className: 'inspector-tags' },
        (data.tags?.direct || []).map((tag) => (
          React.createElement('span', { className: 'tag-pill', key: tag.id },
            `#${tag.name}`,
            React.createElement('button', {
              type: 'button',
              className: 'tag-pill-remove',
              onClick: () => onTagRemove?.(node, tag.id),
            }, '×')
          )
        ))
      )
    )
  );

  tagChildren.push(
    React.createElement('div', { className: 'inspector-tags-group muted', key: 'inherited' },
      React.createElement('div', { className: 'inspector-tags-label' }, 'Inherited'),
      React.createElement('div', { className: 'inspector-tags' },
        (data.tags?.inherited || []).map((tag) => (
          React.createElement('span', { className: 'tag-pill', key: tag.id }, `#${tag.name}`)
        ))
      )
    )
  );

  sections.push(
    React.createElement('div', { className: 'inspector-section', key: 'tags' },
      React.createElement('div', { className: 'inspector-heading-row' },
        React.createElement('h4', null, 'Tags'),
        React.createElement('button', { type: 'button', className: 'mini-btn', onClick: addTag }, '+ Add')
      ),
      ...tagChildren
    )
  );

  if (isProject) {
    sections.push(
      React.createElement('div', { className: 'inspector-section', key: 'assets' },
        React.createElement('div', { className: 'inspector-heading-row' },
          React.createElement('h4', null, 'Assets'),
          React.createElement('button', { type: 'button', className: 'mini-btn', onClick: addAsset }, '+ Add')
        ),
        React.createElement('div', { className: 'inspector-tags' },
          assets.map((asset) => (
            React.createElement('span', { className: 'tag-pill', key: asset.id },
              asset.name,
              React.createElement('button', {
                type: 'button',
                className: 'tag-pill-remove',
                onClick: () => onAssetRemove?.(node, asset.id),
              }, '×')
            )
          )),
          !assets.length
            ? React.createElement('span', { className: 'inspector-empty' }, 'No assets linked.')
            : null
        )
      )
    );
  }

  const actionButtons = [
    React.createElement('button', { type: 'button', className: 'mini-btn', onClick: addChild, key: 'add' }, isProject ? '+ New Item' : '+ New Child'),
  ];
  if (isCategory) {
    actionButtons.push(React.createElement('button', { type: 'button', className: 'mini-btn', onClick: moveCategory, key: 'move' }, 'Move…'));
  }
  sections.push(
    React.createElement('div', { className: 'inspector-section inspector-actions', key: 'actions' }, actionButtons)
  );

  sections.push(
    React.createElement('div', { className: 'inspector-section muted', key: 'history' },
      React.createElement('h4', null, 'History'),
      React.createElement('ul', { className: 'history-list' },
        historyEntries.map((entry) => (
          React.createElement('li', { className: 'history-entry', key: entry.id },
            React.createElement('span', { className: 'history-label' }, entry.label),
            React.createElement('span', { className: 'history-detail' }, entry.detail)
          )
        ))
      )
    )
  );

  return React.createElement('aside', { className: 'inspector-panel' }, ...sections);
}
function DataTable({ rows }) {
  if (!rows.length) {
    return React.createElement('div', { className: 'table-panel' },
      React.createElement('div', { className: 'funding-empty' }, 'No entries in this hierarchy yet.')
    );
  }
  return (
    React.createElement('div', { className: 'table-panel' },
      React.createElement('table', { className: 'summary-table' },
        React.createElement('thead', null,
          React.createElement('tr', null,
            React.createElement('th', null, 'Type'),
            React.createElement('th', null, 'Name'),
            React.createElement('th', null, 'Path'),
            React.createElement('th', null, 'Leaf Amount'),
            React.createElement('th', null, 'Subtotal')
          )
        ),
        React.createElement('tbody', null,
          rows.map((row) => (
            React.createElement('tr', { key: row.id },
              React.createElement('td', null, row.type || '—'),
              React.createElement('td', null, row.name || 'Untitled'),
              React.createElement('td', null, row.path || '—'),
              React.createElement('td', null, row.leafDisplay),
              React.createElement('td', null, row.rollupDisplay)
            )
          ))
        )
      )
    )
  );
}

function renderFundingPage({ container, ...props }) {
  if (!container) throw new Error('renderFundingPage requires a container');
  const root = ReactDOM.createRoot(container);
  root.render(React.createElement(FundingApp, props));
  return () => root.unmount();
}

export { renderFundingPage };
