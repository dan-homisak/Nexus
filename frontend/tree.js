(function (global) {
  'use strict';

  const INTERACTIVE_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT', 'OPTION']);

  function renderTree(container, nodes, options = {}) {
    if (!container) {
      throw new Error('TreeView.renderTree requires a container');
    }
    container.classList.add('tv');
    container.setAttribute('role', options.role || 'tree');

    const ctx = {
      container,
      options,
      nodeByKey: new Map(),
      elementByKey: new Map(),
    };
    container.__tvContext = ctx;

    const fragment = document.createDocumentFragment();
    (nodes || []).forEach((node) => {
      const rendered = renderNode(node, ctx, 0);
      if (rendered) fragment.appendChild(rendered);
    });

    container.innerHTML = '';
    container.appendChild(fragment);

    updateTabIndexes(container);

    if (!container.__tvHandlersAttached) {
      container.addEventListener('keydown', handleKeyDown);
      container.addEventListener('focusin', handleFocusIn);
      container.addEventListener('click', handleContainerClick);
      container.__tvHandlersAttached = true;
    }
  }

  function renderNode(node, ctx, depth) {
    if (!node) return null;
    const key = node.key != null ? String(node.key) : node.id != null ? String(node.id) : null;
    if (!key) {
      throw new Error('TreeView node requires a key or id');
    }

    const childNodes = Array.isArray(node.children) ? node.children : [];
    const hasChildren = childNodes.length > 0;
    const isLeafType = node.isLeaf === true;
    const expanded = hasChildren ? getInitialExpanded(node, ctx.options) : false;

    const li = document.createElement('li');
    li.className = 'tv__li';
    li.dataset.key = key;
    li.dataset.type = node.type || '';
    li.dataset.leaf = String(isLeafType);
    li.dataset.hasChildren = String(hasChildren);
    li.dataset.depth = String(depth);
    li.setAttribute('role', 'treeitem');
    li.tabIndex = -1;
    if (hasChildren) {
      li.setAttribute('aria-expanded', String(expanded));
    }

    const row = document.createElement('div');
    row.className = 'tv__row';
    row.dataset.type = node.type || '';
    row.dataset.leaf = String(isLeafType);
    row.dataset.hasChildren = String(hasChildren);
    row.tabIndex = -1;

    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'tv__toggle';
    toggle.dataset.tvStopToggle = '1';
    toggle.dataset.tvNavOk = '1';
    toggle.setAttribute('aria-label', hasChildren ? 'Toggle children' : 'Leaf');
    toggle.tabIndex = -1;
    if (!hasChildren) {
      toggle.disabled = true;
    }
    row.appendChild(toggle);

    const main = document.createElement('div');
    main.className = 'tv__main';
    row.appendChild(main);

    const end = document.createElement('div');
    end.className = 'tv__end';
    row.appendChild(end);

    li.appendChild(row);

    ctx.nodeByKey.set(key, node);
    ctx.elementByKey.set(key, li);

    const setExpanded = (value) => {
      setExpandedState(li, !!value, ctx, { origin: 'decorator' });
    };

    const decoratorArgs = {
      node,
      li,
      row,
      toggle,
      main,
      end,
      hasChildren,
      expanded,
      depth,
      setExpanded,
      isExpanded: () => isExpanded(li),
    };

    if (typeof ctx.options.decorateRow === 'function') {
      ctx.options.decorateRow(decoratorArgs);
    } else {
      applyDefaultRow(node, decoratorArgs);
    }

    toggle.addEventListener('click', (ev) => {
      ev.stopPropagation();
      if (!hasChildren) return;
      const next = !isExpanded(li);
      setExpandedState(li, next, ctx, { origin: 'toggle' });
      focusRow(row, ctx.container);
    });

    main.addEventListener('click', (ev) => {
      if (!hasChildren) return;
      if (shouldSuppressToggle(ev.target)) return;
      const next = !isExpanded(li);
      setExpandedState(li, next, ctx, { origin: 'main' });
    });

    if (hasChildren) {
      const childList = document.createElement('ul');
      childList.className = 'tv__children';
      childList.setAttribute('role', 'group');
      if (!expanded) childList.hidden = true;
      childNodes.forEach((child) => {
        const renderedChild = renderNode(child, ctx, depth + 1);
        if (renderedChild) childList.appendChild(renderedChild);
      });
      li.appendChild(childList);
    }

    ctx.options.onRowCreated?.({ ...decoratorArgs });
    return li;
  }

  function applyDefaultRow(node, parts) {
    const title = document.createElement('span');
    title.className = 'tv__title';
    title.textContent = node.label || '';
    parts.main.appendChild(title);
    if (node.meta && node.meta.text) {
      const meta = document.createElement('span');
      meta.className = 'tv__meta';
      meta.textContent = node.meta.text;
      parts.main.appendChild(meta);
    }
    if (Array.isArray(node.tags) && node.tags.length) {
      const tags = document.createElement('span');
      tags.className = 'tv__meta';
      tags.textContent = '#' + node.tags.join(' #');
      parts.main.appendChild(tags);
    }
  }

  function getInitialExpanded(node, options) {
    if (!node) return true;
    if (typeof options.getExpanded === 'function') {
      return !!options.getExpanded(node);
    }
    if (typeof node.expanded === 'boolean') {
      return node.expanded;
    }
    return true;
  }

  function isExpanded(li) {
    return li.getAttribute('aria-expanded') === 'true';
  }

  function setExpandedState(li, expand, ctx, meta = {}) {
    if (!li || li.dataset.hasChildren !== 'true') return;
    const current = isExpanded(li);
    if (current === expand) return;
    li.setAttribute('aria-expanded', String(expand));
    const children = getChildrenContainer(li);
    if (children) children.hidden = !expand;

    const key = li.dataset.key;
    const node = key ? ctx.nodeByKey.get(key) : null;
    ctx.options.setExpanded?.(node, expand);
    ctx.options.onToggle?.(node, expand, meta);

    updateTabIndexes(ctx.container);
  }

  function getChildrenContainer(li) {
    return li.querySelector(':scope > .tv__children');
  }

  function handleKeyDown(ev) {
    const container = ev.currentTarget;
    const ctx = container.__tvContext;
    if (!ctx) return;
    if (shouldSkipKeyHandling(ev.target)) return;

    const activeLi = ev.target.closest('.tv__li');
    if (!activeLi || !container.contains(activeLi)) return;

    const visibleItems = getVisibleItems(container);
    const index = visibleItems.indexOf(activeLi);
    if (index === -1) return;

    const key = ev.key;
    const hasChildren = activeLi.dataset.hasChildren === 'true';

    const moveFocus = (targetLi) => {
      if (!targetLi) return;
      focusRow(getRow(targetLi), container);
    };

    switch (key) {
      case 'ArrowDown': {
        const next = visibleItems[index + 1];
        if (next) {
          ev.preventDefault();
          moveFocus(next);
        }
        break;
      }
      case 'ArrowUp': {
        const prev = visibleItems[index - 1];
        if (prev) {
          ev.preventDefault();
          moveFocus(prev);
        }
        break;
      }
      case 'Home': {
        const first = visibleItems[0];
        if (first) {
          ev.preventDefault();
          moveFocus(first);
        }
        break;
      }
      case 'End': {
        const last = visibleItems[visibleItems.length - 1];
        if (last) {
          ev.preventDefault();
          moveFocus(last);
        }
        break;
      }
      case 'ArrowRight': {
        if (!hasChildren) {
          const next = visibleItems[index + 1];
          if (next) {
            ev.preventDefault();
            moveFocus(next);
          }
          break;
        }
        if (!isExpanded(activeLi)) {
          ev.preventDefault();
          setExpandedState(activeLi, true, ctx, { origin: 'keyboard' });
          break;
        }
        const firstChild = getChildrenContainer(activeLi)?.querySelector('.tv__li');
        if (firstChild) {
          ev.preventDefault();
          moveFocus(firstChild);
        }
        break;
      }
      case 'ArrowLeft': {
        if (hasChildren && isExpanded(activeLi)) {
          ev.preventDefault();
          setExpandedState(activeLi, false, ctx, { origin: 'keyboard' });
          break;
        }
        const parent = activeLi.parentElement?.closest('.tv__li');
        if (parent) {
          ev.preventDefault();
          moveFocus(parent);
        }
        break;
      }
      case 'Enter':
      case ' ': {
        if (hasChildren) {
          ev.preventDefault();
          setExpandedState(activeLi, !isExpanded(activeLi), ctx, { origin: 'keyboard' });
        }
        break;
      }
      default:
        break;
    }
  }

  function handleFocusIn(ev) {
    const container = ev.currentTarget;
    const row = ev.target.closest('.tv__row');
    if (!row || !container.contains(row)) return;
    setActiveRow(container, row);
  }

  function handleContainerClick(ev) {
    const container = ev.currentTarget;
    const row = ev.target.closest('.tv__row');
    if (!row || !container.contains(row)) return;
    if (isInteractiveElement(ev.target)) return;
    focusRow(row, container);
  }

  function shouldSkipKeyHandling(target) {
    if (!target) return false;
    if (target.closest('[data-tv-stop-nav="1"]')) return true;
    const tag = target.tagName;
    if (INTERACTIVE_TAGS.has(tag)) return true;
    if (target.isContentEditable) return true;
    return false;
  }

  function shouldSuppressToggle(target) {
    if (!target) return false;
    if (target.closest('[data-tv-stop-toggle="1"]')) return true;
    return isInteractiveElement(target);
  }

  function isInteractiveElement(target) {
    if (!target) return false;
    const tag = target.tagName;
    if (tag === 'BUTTON' || tag === 'A') return true;
    if (INTERACTIVE_TAGS.has(tag)) return true;
    if (target.isContentEditable) return true;
    return false;
  }

  function getVisibleItems(container) {
    const items = Array.from(container.querySelectorAll('.tv__li'));
    return items.filter((li) => isLiVisible(li, container));
  }

  function isLiVisible(li, container) {
    let parent = li.parentElement;
    while (parent && parent !== container) {
      if (parent.classList.contains('tv__children')) {
        const owner = parent.parentElement;
        if (owner && owner.matches('.tv__li') && owner.getAttribute('aria-expanded') === 'false') {
          return false;
        }
      }
      parent = parent.parentElement;
    }
    return true;
  }

  function getRow(li) {
    return li ? li.querySelector(':scope > .tv__row') : null;
  }

  function focusRow(row, container) {
    if (!row) return;
    setActiveRow(container, row);
    if (document.activeElement !== row) {
      row.focus({ preventScroll: true });
    }
  }

  function setActiveRow(container, row) {
    if (!container) return;
    const prev = container.__tvActiveRow;
    if (prev && prev !== row) {
      prev.tabIndex = -1;
    }
    if (row) {
      row.tabIndex = 0;
      container.__tvActiveRow = row;
    } else {
      container.__tvActiveRow = null;
    }
  }

  function updateTabIndexes(container) {
    if (!container) return;
    const rows = Array.from(container.querySelectorAll('.tv__row'));
    const active = rows.find((row) => row === container.__tvActiveRow && isRowVisible(row));
    rows.forEach((row) => {
      row.tabIndex = -1;
    });
    const target = active || findFirstVisibleRow(container);
    if (target) {
      target.tabIndex = 0;
      container.__tvActiveRow = target;
    } else {
      container.__tvActiveRow = null;
    }
  }

  function findFirstVisibleRow(container) {
    const firstLi = getVisibleItems(container)[0];
    return getRow(firstLi) || null;
  }

  function isRowVisible(row) {
    if (!row) return false;
    const li = row.closest('.tv__li');
    if (!li) return false;
    const container = li.closest('.tv');
    return isLiVisible(li, container);
  }

  global.TreeView = {
    renderTree,
  };
})(window);
