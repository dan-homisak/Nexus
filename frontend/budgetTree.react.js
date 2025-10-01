import React from './vendor/react.js';
import ReactDOM from './vendor/react-dom-client.js';

function TreeNode({ node }) {
  const hasChildren = Array.isArray(node.children) && node.children.length > 0;
  return React.createElement(
    'li',
    null,
    React.createElement('div', null, node.label || '(untitled)'),
    hasChildren
      ? React.createElement(
          'ul',
          null,
          node.children.map((child) =>
            React.createElement(TreeNode, { node: child, key: child.key || child.id || child.label })
          )
        )
      : null
  );
}

function TreeRoot({ nodes = [] }) {
  return React.createElement(
    'ul',
    { className: 'bt-tree' },
    nodes.map((node) => React.createElement(TreeNode, { node, key: node.key || node.id || node.label }))
  );
}

function ensureRoot(container) {
  let root = container.__btRoot;
  if (!root) {
    root = ReactDOM.createRoot(container);
    container.__btRoot = root;
  }
  return root;
}

function render(container, props) {
  const root = ensureRoot(container);
  root.render(React.createElement(TreeRoot, props));
}

function unmount(container) {
  const root = container.__btRoot;
  if (root) {
    root.unmount();
    delete container.__btRoot;
  }
}

window.BudgetTreeReact = { render, unmount };
