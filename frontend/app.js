(() => {
    // ---- Error panel (visible in UI) ----
    function showError(err) {
      try { console.error(err); } catch {}
      const content = document.getElementById('content');
      if (!content) return;
      const html = `
        <div class="card" style="border-color:#d05c5c">
          <h3>Something went wrong</h3>
          <div class="help-box">
            <p>Please screenshot this and paste it to me:</p>
            <pre style="white-space:pre-wrap">${(err && (err.stack || err.message || err)) || String(err)}</pre>
          </div>
        </div>`;
      content.insertAdjacentHTML('afterbegin', html);
    }
  
    window.addEventListener('DOMContentLoaded', init);
  
    async function init() {
      try {
        const content = document.getElementById('content');
        const nav = document.querySelector('nav');
        const saveBtn = document.getElementById('saveBtn');
        const loadBtn = document.getElementById('loadBtn');
        const quitBtn = document.getElementById('quitBtn'); // <-- new
        if (!content || !nav) throw new Error('Base DOM not found');
  
        // ---- API helpers ----
        async function api(path, opts) {
          const r = await fetch(path, opts);
          const ct = r.headers.get('content-type') || '';
          const body = ct.includes('application/json') ? await r.json() : await r.text();
          if (!r.ok) throw new Error(typeof body === 'string' ? body : JSON.stringify(body, null, 2));
          return body;
        }
        const apiList = (p) => api(p);
        const apiCreate = (p, b) => api(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
        const apiUpdate = (p, b) => api(p, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
        const apiDelete = (p) => api(p, { method: 'DELETE' });

        const ApiNew = window.Api || {};
        const FEATURES = window.FEATURES || {};
  
        // ---- UI helpers ----
        const escapeTip = (s) => String(s).replace(/"/g, '&quot;');
        const escapeHtml = (s = '') => String(s)
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;')
          .replace(/'/g, '&#39;');
        const labelFor = (name, text, tip) => {
          const tipHtml = tip ? `<span class="info" data-tip="${escapeTip(tip)}">i</span>` : '';
          return `<label for="${name}">${text}${tipHtml}</label>`;
        };
        const field = (name, labelHtml, inputHtml) => `<div class="field">${labelHtml}${inputHtml}</div>`;
        const input = (name, placeholder='') => `<input class="input" name="${name}" placeholder="${placeholder}"/>`;
        const dropdownRegistry = new Map();
        let dropdownSeq = 0;
        const select = (name, opts, config = {}) => {
          const id = `dd-${++dropdownSeq}`;
          const options = (opts || []).map(opt => ({
            value: opt.value === undefined || opt.value === null ? '' : String(opt.value),
            label: opt.label === undefined || opt.label === null ? '' : String(opt.label),
            raw: opt.raw !== undefined ? opt.raw : opt,
          }));
          dropdownRegistry.set(id, { name, options, config });
          const optionsHtml = options.map(o => `<option value="${escapeHtml(o.value)}">${escapeHtml(o.label)}</option>`).join('');
          const placeholder = config.placeholder || 'Search…';
          return `
            <div class="dropdown" data-dropdown-id="${id}">
              <div class="dropdown-box">
                <input id="${name}-${id}" class="dropdown-input" data-dropdown-input placeholder="${escapeHtml(placeholder)}" autocomplete="off" />
                <button type="button" class="dropdown-toggle" data-dropdown-toggle aria-label="Toggle options">▾</button>
              </div>
              <div class="dropdown-menu" data-dropdown-menu role="listbox"></div>
              <select id="${name}" name="${name}" data-dropdown-native style="display:none">${optionsHtml}</select>
            </div>`;
        };

        const DROPDOWN_DEFAULTS = {
          allowCreate: true,
          allowEdit: true,
          allowDelete: true,
          matcher: (option, needle) => option.label.toLowerCase().includes(needle),
          sorter: (a, b) => a.label.localeCompare(b.label),
        };

        const dropdownInstances = new Set();
        const dropdownGroups = new Map();

        const registerDropdownState = (state) => {
          dropdownInstances.add(state);
          if (state.config && state.config.key) {
            if (!dropdownGroups.has(state.config.key)) dropdownGroups.set(state.config.key, new Set());
            dropdownGroups.get(state.config.key).add(state);
          }
        };

        const cloneOption = (opt) => ({ value: opt.value, label: opt.label, raw: opt.raw });

        const propagateAdd = (source, option) => {
          const key = source.config?.key;
          if (!key) return;
          const peers = dropdownGroups.get(key);
          if (!peers) return;
          peers.forEach(peer => {
            if (peer === source) return;
            if (peer.optionMap.has(option.value)) return;
            const copy = cloneOption(option);
            peer.options.push(copy);
            peer.optionMap.set(copy.value, copy);
            peer.selectEl.insertAdjacentHTML('beforeend', `<option value="${escapeHtml(copy.value)}">${escapeHtml(copy.label)}</option>`);
            peer.filtered = peer.options.slice().sort(peer.config.sorter);
            if (peer.open) {
              peer.filterOptions(peer.inputEl.value);
            }
          });
        };

        const propagateUpdate = (source, option) => {
          const key = source.config?.key;
          if (!key) return;
          const peers = dropdownGroups.get(key);
          if (!peers) return;
          peers.forEach(peer => {
            if (peer === source) return;
            const target = peer.optionMap.get(option.value);
            if (!target) return;
            target.label = option.label;
            target.raw = option.raw;
            [...peer.selectEl.options].forEach(o => {
              if (o.value === option.value) o.textContent = option.label;
            });
            if (peer.selected && peer.selected.value === option.value) {
              peer.inputEl.value = option.label;
            }
            peer.filtered = peer.options.slice().sort(peer.config.sorter);
            if (peer.open) peer.filterOptions(peer.inputEl.value);
          });
        };

        const propagateRemove = (source, option) => {
          const key = source.config?.key;
          if (!key) return;
          const peers = dropdownGroups.get(key);
          if (!peers) return;
          peers.forEach(peer => {
            if (peer === source) return;
            peer.options = peer.options.filter(o => o.value !== option.value);
            peer.optionMap.delete(option.value);
            [...peer.selectEl.options].forEach(o => { if (o.value === option.value) o.remove(); });
            if (peer.selected && peer.selected.value === option.value) {
              peer.selected = null;
              peer.selectEl.value = '';
              peer.inputEl.value = '';
            }
            peer.filtered = peer.options.slice().sort(peer.config.sorter);
            if (peer.open) peer.filterOptions(peer.inputEl.value);
          });
        };

        function initializeDropdowns(root) {
          root.querySelectorAll('[data-dropdown-id]').forEach(wrapper => {
            if (wrapper.dataset.dropdownReady) return;
            const id = wrapper.dataset.dropdownId;
            const meta = dropdownRegistry.get(id);
            if (!meta) return;
            dropdownRegistry.delete(id);
            wrapper.dataset.dropdownReady = '1';

            const selectEl = wrapper.querySelector('select[data-dropdown-native]');
            const inputEl = wrapper.querySelector('[data-dropdown-input]');
            const menuEl = wrapper.querySelector('[data-dropdown-menu]');
            const toggleEl = wrapper.querySelector('[data-dropdown-toggle]');
            if (!selectEl || !inputEl || !menuEl) return;

            const rawConfig = meta.config || {};
            const config = Object.assign({}, DROPDOWN_DEFAULTS, rawConfig);
            config.allowCreate = !!config.create && config.allowCreate !== false;
            config.allowEdit = !!config.edit && config.allowEdit !== false;
            config.allowDelete = !!config.remove && config.allowDelete !== false;
            config.prefill = rawConfig.prefill !== false;
            const options = Array.isArray(meta.options) ? meta.options.slice() : [];
            const optionMap = new Map(options.map(opt => [opt.value, opt]));

            if (!config.allowEdit) wrapper.classList.add('dropdown-no-edit');
            if (!config.allowDelete) wrapper.classList.add('dropdown-no-delete');

            // ensure native select reflects provided options
            selectEl.innerHTML = options.map(o => `<option value="${escapeHtml(o.value)}">${escapeHtml(o.label)}</option>`).join('');

            const state = {
              wrapper,
              inputEl,
              menuEl,
              selectEl,
              toggleEl,
              config,
              options,
              optionMap,
              filtered: options.slice().sort(config.sorter),
              open: false,
              highlightIndex: -1,
              selected: null,
              showSelection: config.prefill,
            };

            state.filterOptions = () => {};
            state.openMenu = () => {};
            state.closeMenu = () => {};
            state.renderMenu = () => {};
            state.chooseOption = () => {};

            registerDropdownState(state);

            const syncSelectedFromSelect = () => {
              const currentValue = selectEl.value;
              const option = optionMap.get(currentValue) || null;
              state.selected = option;
              if (option && state.showSelection) {
                inputEl.value = option.label;
              } else if (!option) {
                inputEl.value = '';
              } else if (!state.showSelection) {
                inputEl.value = '';
              }
            };

            selectEl.addEventListener('change', syncSelectedFromSelect);
            wrapper.__dropdown = state;
            selectEl.__dropdown = state;

            state.renderMenu = () => {
              menuEl.innerHTML = '';
              if (!state.filtered.length) {
                const empty = document.createElement('div');
                empty.className = 'dropdown-empty';
                empty.textContent = 'No matches';
                menuEl.appendChild(empty);
                state.highlightIndex = -1;
                return;
              }

              state.filtered.forEach((opt, idx) => {
                const item = document.createElement('div');
                item.className = 'dropdown-item';
                item.dataset.value = opt.value;
                item.setAttribute('role', 'option');

                const labelSpan = document.createElement('span');
                labelSpan.className = 'dropdown-label';
                labelSpan.textContent = opt.label;
                item.appendChild(labelSpan);

                const allowModify = opt.value !== '' && opt.value !== null;

                if (config.allowEdit && allowModify) {
                  const editBtn = document.createElement('button');
                  editBtn.type = 'button';
                  editBtn.className = 'dropdown-action dropdown-edit';
                  editBtn.title = 'Edit';
                  editBtn.dataset.action = 'edit';
                  editBtn.textContent = '✎';
                  item.appendChild(editBtn);
                }

                if (config.allowDelete && allowModify) {
                  const deleteBtn = document.createElement('button');
                  deleteBtn.type = 'button';
                  deleteBtn.className = 'dropdown-action dropdown-delete';
                  deleteBtn.title = 'Delete';
                  deleteBtn.dataset.action = 'delete';
                  deleteBtn.textContent = '×';
                  item.appendChild(deleteBtn);
                }

                item.addEventListener('mousedown', (evt) => {
                  evt.preventDefault();
                  const action = evt.target.dataset.action;
                  if (action === 'edit') {
                    handleEdit(opt);
                    return;
                  }
                  if (action === 'delete') {
                    handleDelete(opt);
                    return;
                  }
                  state.chooseOption(opt);
                });

                if (idx === state.highlightIndex) {
                  item.classList.add('highlight');
                }

                menuEl.appendChild(item);
              });
            };

            state.openMenu = () => {
              if (state.open) return;
              state.open = true;
              wrapper.classList.add('open');
              state.renderMenu();
            };

            state.closeMenu = () => {
              if (!state.open) return;
              state.open = false;
              wrapper.classList.remove('open');
            };

            state.filterOptions = (needle) => {
              const query = needle.trim().toLowerCase();
              if (!query) {
                state.filtered = state.options.slice().sort(config.sorter);
                state.highlightIndex = state.filtered.findIndex(opt => state.selected && opt.value === state.selected.value);
                state.renderMenu();
                return;
              }

              state.filtered = state.options.filter(opt => config.matcher(opt, query)).sort(config.sorter);
              state.highlightIndex = state.filtered.length ? 0 : -1;
              state.renderMenu();
            };

            state.chooseOption = (opt) => {
              state.selected = opt;
              selectEl.value = opt ? opt.value : '';
              state.showSelection = true;
              inputEl.value = opt ? opt.label : '';
              state.closeMenu();
              selectEl.dispatchEvent(new Event('change', { bubbles: true }));
            };

            const handleCreate = async (label) => {
              if (!config.allowCreate || !config.create) {
                alert('Cannot create new option here.');
                return;
              }
              try {
                const created = await config.create(label, state);
                if (!created) return;
                const option = {
                  value: created.value === undefined || created.value === null ? '' : String(created.value),
                  label: created.label === undefined || created.label === null ? label : String(created.label),
                  raw: created.raw !== undefined ? created.raw : created,
                };
                state.options.push(option);
                optionMap.set(option.value, option);
                selectEl.insertAdjacentHTML('beforeend', `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`);
                propagateAdd(state, option);
                state.filterOptions('');
                state.chooseOption(option);
              } catch (err) {
                showError(err);
              }
            };

            const handleEdit = async (opt) => {
              if (!config.allowEdit || !config.edit) return;
              if (!opt || opt.value === '' || opt.value === null) return;
              const nextLabel = prompt('Rename item', opt.label);
              if (!nextLabel || nextLabel.trim() === opt.label.trim()) return;
              try {
                const updated = await config.edit(opt, nextLabel.trim(), state);
                opt.label = updated && updated.label ? String(updated.label) : nextLabel.trim();
                opt.raw = updated && updated.raw !== undefined ? updated.raw : opt.raw;
                const nativeOpt = [...selectEl.options].find(o => o.value === opt.value);
                if (nativeOpt) nativeOpt.textContent = opt.label;
                inputEl.value = state.selected && state.selected.value === opt.value ? opt.label : inputEl.value;
                propagateUpdate(state, opt);
                state.filterOptions(inputEl.value);
              } catch (err) {
                showError(err);
              }
            };

            const handleDelete = async (opt) => {
              if (!config.allowDelete || !config.remove) return;
              if (!opt || opt.value === '' || opt.value === null) return;
              if (!confirm(`Delete "${opt.label}"?`)) return;
              if (!confirm('This action cannot be undone. Continue?')) return;
              try {
                await config.remove(opt, state);
                state.options = state.options.filter(o => o.value !== opt.value);
                optionMap.delete(opt.value);
                [...selectEl.options].forEach(o => { if (o.value === opt.value) o.remove(); });
                if (state.selected && state.selected.value === opt.value) {
                  state.selected = null;
                  selectEl.value = '';
                  inputEl.value = '';
                  state.showSelection = config.prefill;
                }
                propagateRemove(state, opt);
                state.filterOptions(inputEl.value);
              } catch (err) {
                showError(err);
              }
            };

            const handleKeyDown = (evt) => {
              if (evt.key === 'ArrowDown') {
                evt.preventDefault();
                if (!state.open) {
                  state.openMenu();
                  state.filterOptions('');
                }
                if (!state.filtered.length) return;
                state.highlightIndex = (state.highlightIndex + 1) % state.filtered.length;
                highlightCurrent();
              } else if (evt.key === 'ArrowUp') {
                evt.preventDefault();
                if (!state.open) {
                  state.openMenu();
                  state.filterOptions('');
                }
                if (!state.filtered.length) return;
                state.highlightIndex = state.highlightIndex <= 0 ? state.filtered.length - 1 : state.highlightIndex - 1;
                highlightCurrent();
              } else if (evt.key === 'Enter') {
                evt.preventDefault();
                if (state.open && state.highlightIndex >= 0 && state.highlightIndex < state.filtered.length) {
                  state.chooseOption(state.filtered[state.highlightIndex]);
                } else {
                  const label = inputEl.value.trim();
                  const existing = state.options.find(o => o.label.toLowerCase() === label.toLowerCase());
                  if (existing) {
                    state.chooseOption(existing);
                  } else if (label) {
                    handleCreate(label);
                  }
                }
              } else if (evt.key === 'Escape') {
                state.closeMenu();
              }
            };

            const highlightCurrent = () => {
              [...menuEl.querySelectorAll('.dropdown-item')].forEach((item, idx) => {
                if (idx === state.highlightIndex) item.classList.add('highlight');
                else item.classList.remove('highlight');
              });
            };

            inputEl.addEventListener('focus', () => {
              state.openMenu();
              state.filterOptions('');
            });
            inputEl.addEventListener('input', () => {
              state.filterOptions(inputEl.value);
              state.openMenu();
            });
            inputEl.addEventListener('keydown', handleKeyDown);
            if (toggleEl) {
              toggleEl.addEventListener('mousedown', (evt) => {
                evt.preventDefault();
                if (state.open) state.closeMenu(); else {
                  state.openMenu();
                  state.filterOptions('');
                  inputEl.focus();
                }
              });
            }

            document.addEventListener('mousedown', (evt) => {
              if (!wrapper.contains(evt.target)) {
                state.closeMenu();
              }
            });

            syncSelectedFromSelect();
            state.filterOptions('');
          });
        }

        function refreshAllDropdowns() {
          dropdownInstances.forEach(state => {
            const { options, selectEl, config, inputEl } = state;
            const optionMap = new Map(options.map(opt => [opt.value, opt]));
            state.optionMap = optionMap;
            state.filtered = options.slice().sort(config.sorter);
            selectEl.innerHTML = options.map(o => `<option value="${escapeHtml(o.value)}">${escapeHtml(o.label)}</option>`).join('');
            if (state.selected) {
              const current = optionMap.get(state.selected.value);
              if (current) {
                state.selected = current;
                selectEl.value = current.value;
                if (state.showSelection) inputEl.value = current.label;
                else inputEl.value = '';
              }
            }
          });
        }

        let tableDropdownSeq = 0;
        function setupTableEditing(container, base, rows, columnConfig = {}) {
          if (!container) return;
          const tableEl = container.querySelector(`table[data-table-base="${base}"]`);
          if (!tableEl) return;
          const rowMap = Object.fromEntries((rows || []).map(r => [String(r.id), r]));
          const dropdownCells = [];

          tableEl.querySelectorAll('td[data-field]').forEach(td => {
            const field = td.dataset.field;
            const rowId = td.dataset.id || '';
            const row = rowMap[rowId] || {};
            const rawValue = row[field];
            const rawString = rawValue === null || rawValue === undefined ? '' : String(rawValue);
            td.dataset.raw = rawString;
            td.title = rawString;

            const cfg = columnConfig[field];
            if (!cfg) return;

            if (cfg.render) {
              const rendered = cfg.render(rawValue, row);
              td.textContent = rendered === null || rendered === undefined ? '' : rendered;
            }

            if (cfg.type === 'dropdown') {
              const optionSource = cfg.getOptions ? cfg.getOptions(row, rawValue) : (cfg.options || []);
              const allowNull = cfg.allowNull ?? false;
              const nullOptionLabel = cfg.nullOptionLabel || '(none)';
              const options = [];
              if (allowNull) options.push({ value: '', label: nullOptionLabel, raw: null });
              optionSource.forEach(opt => {
                if (!opt) return;
                options.push({
                  value: opt.value,
                  label: opt.label,
                  raw: opt.raw !== undefined ? opt.raw : opt,
                });
              });

              const dropdownName = `${field}_${rowId || 'row'}_${++tableDropdownSeq}`;
              const dropdownConfig = Object.assign({}, cfg.handlers || {}, {
                allowCreate: cfg.allowCreate !== false,
                allowEdit: cfg.allowEdit !== false,
                allowDelete: cfg.allowDelete !== false,
                prefill: cfg.prefill !== false,
              });
              td.innerHTML = select(dropdownName, options, dropdownConfig);
              td.dataset.editor = 'dropdown';
              td.dataset.valueType = cfg.valueType || 'string';
              if (allowNull) td.dataset.allowNull = '1'; else delete td.dataset.allowNull;
              td.removeAttribute('contenteditable');
              dropdownCells.push({ td, rawString });
            }
          });

          dropdownCells.forEach(({ td }) => initializeDropdowns(td));
          dropdownCells.forEach(({ td, rawString }) => {
            const selectEl = td.querySelector('select');
            if (!selectEl) return;
            selectEl.value = rawString;
            selectEl.dispatchEvent(new Event('change'));
            const updateTooltip = () => {
              const val = selectEl.value;
              td.dataset.raw = val;
              td.title = val;
              const wrapper = td.querySelector('.dropdown');
              if (wrapper) wrapper.title = val;
            };
            selectEl.addEventListener('change', updateTooltip);
            updateTooltip();
          });
        }

        const stripId = (obj) => {
          if (!obj || typeof obj !== 'object') return {};
          const copy = { ...obj };
          delete copy.id;
          return copy;
        };

        function buildResourceDropdownHandlers(resourcePath, options = {}) {
          const {
            formatLabel = (item) => item && item.name ? item.name : (item && item.label ? item.label : String(item?.id ?? '')),
            createDefaults = {},
            buildCreateBody,
            buildUpdateBody,
            matcherFields = [],
            matcherText,
            normalize,
          } = options;

          const normalise = (item) => normalize ? normalize(item) : item;

          return {
            create: async (label) => {
              const payload = buildCreateBody
                ? buildCreateBody(label)
                : { ...createDefaults, name: label };
              const created = await apiCreate(resourcePath, payload);
              const raw = normalise(created);
              return {
                value: raw?.id ?? created?.id ?? label,
                label: formatLabel(raw),
                raw,
              };
            },
            edit: async (option, nextLabel) => {
              const raw = normalise(option.raw || {});
              const payload = buildUpdateBody
                ? buildUpdateBody(raw, nextLabel)
                : { ...stripId(raw), name: nextLabel };
              const updated = await apiUpdate(`${resourcePath}/${option.value}`, payload);
              const norm = normalise(updated);
              return {
                value: norm?.id ?? option.value,
                label: formatLabel(norm),
                raw: norm,
              };
            },
            remove: async (option) => {
              await apiDelete(`${resourcePath}/${option.value}`);
            },
            matcher: (option, needle) => {
              const raw = normalise(option.raw || {});
              if (matcherText) {
                return matcherText(raw, option).toLowerCase().includes(needle);
              }
              const parts = [option.label];
              matcherFields.forEach(field => {
                if (raw && raw[field] !== undefined && raw[field] !== null) parts.push(String(raw[field]));
              });
              return parts.join(' ').toLowerCase().includes(needle);
            },
          };
        }

        const card = (title, inner='') => `<div class="card"><h3>${title}</h3>${inner}</div>`;
        const normaliseColumns = (cols) => cols.map(col => {
          if (typeof col === 'string') {
            const pretty = col.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
            return { key: col, label: pretty };
          }
          return col;
        });
        const table = (rows, cols, base) => {
          const columns = normaliseColumns(cols);
          if (!rows || !rows.length) return '<div>(empty)</div>';
          const head = '<tr>' + columns.map(c=>`<th>${c.label}</th>`).join('') + '<th>Actions</th></tr>';
          const body = rows.map(r => `
            <tr>
              ${columns.map(col=>{
                const value = r[col.key];
                const text = value === null || value === undefined ? '' : String(value);
                const editable = col.key === 'id' ? '' : ' contenteditable';
                const rawAttr = escapeHtml(text);
                const title = rawAttr ? ` title="${rawAttr}"` : '';
                return `<td${editable} data-field="${col.key}" data-id="${r.id}" data-raw="${rawAttr}"${title}>${escapeHtml(text)}</td>`;
              }).join('')}
              <td>
                <button onclick="window.__updateRow?.('${base}', ${r.id}, this)">Save</button>
                <button onclick="window.__deleteRow?.('${base}', ${r.id})">Delete</button>
                ${base === '/api/entries' && FEATURES.REALLOCATE ? `<button class="btn-reallocate" data-entry-id="${r.id}">⋯</button>` : ''}
              </td>
            </tr>`).join('');
          return `<table class="table" data-table-base="${escapeHtml(base)}"><thead>${head}</thead><tbody>${body}</tbody></table>`;
        };

        const fmtCurrency = (value) => {
          if (value === null || value === undefined || value === '') return '-';
          const num = Number(value);
          if (Number.isNaN(num)) return String(value);
          return '$' + num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        };

        const readOnlyTable = (rows, columns) => {
          if (!rows || !rows.length) return '<div>(empty)</div>';
          const thead = '<tr>' + columns.map(col => `<th>${col.label}</th>`).join('') + '</tr>';
          const tbody = rows.map(row => {
            const cells = columns.map(col => {
              const value = row[col.key];
              return `<td>${col.format ? col.format(value, row) : (value ?? '')}</td>`;
            }).join('');
            return `<tr>${cells}</tr>`;
          }).join('');
          return `<table class="table"><thead>${thead}</thead><tbody>${tbody}</tbody></table>`;
        };

        const computeStatus = (budget, actual) => {
          const b = Number(budget || 0);
          const a = Number(actual || 0);
          if (b <= 0 && a > 0) return 'Over';
          if (a <= b) return 'On Track';
          const pct = b ? ((a - b) / b) * 100 : 100;
          if (pct <= 10) return 'Warning';
          return 'Over';
        };

        const ensureTabVisibility = () => {
          nav.querySelectorAll('button[data-feature]').forEach(btn => {
            const flag = btn.dataset.feature;
            if (!FEATURES[flag]) btn.style.display = 'none';
          });
        };
        ensureTabVisibility();
  
        const mapBy = (arr, key='id') => Object.fromEntries(arr.map(x=>[x[key], x]));
        const catPath = (cat, byId) => {
          const path = []; let cur = cat;
          while (cur) { path.unshift(cur.name); if (!cur.parent_id) break; cur = byId[cur.parent_id]; }
          return path.join(' > ');
        };
        const formatPortfolioLabel = (p) => `${p.name}${p.fiscal_year ? ' • FY ' + p.fiscal_year : ''}`;
        const formatProjectLabel = (project, portfolioLookup) => {
          const fs = portfolioLookup && portfolioLookup[project.portfolio_id];
          const fsLabel = fs ? formatPortfolioLabel(fs) : `Funding Source ${project.portfolio_id}`;
          return `[${fsLabel}] ${project.name}`;
        };

        let reallocateDrawer = null;
        let reallocateCurrent = null;
        let reallocateSubmit = null;

        const fundingState = {
            budgets: [],
            filteredBudgets: [],
            selectedBudgetId: null,
            budgetMap: new Map(),
            budgetTree: [],
            expanded: new Set(),
            bannerEl: null,
            bannerTimer: null,
            jobPollers: new Map(),
            tagCache: new Map(),
            usageCache: null,
            inspector: { open: false, entity: null },
            lineAssetCache: new Map(),
            projectNodeMap: new Map(),
            categoryNodeMap: new Map(),
          };

        const TAG_SCOPE_TYPES = {
          budget: 'Budget',
          item_project: 'Item / Project',
          category: 'Category',
          line_asset: 'Line Asset',
          entry: 'Entry',
        };

        const TAG_COLORS = [
          '#5c6bf1', '#49a078', '#f1a45c', '#f16a6a', '#7f7aea', '#5cc1f1', '#a05cf1', '#f15ccc', '#8dd06c', '#f1c65c',
        ];
        const DEFAULT_TAG_COLOR = '#4b5771';
        const TEXT_FIELD_TYPES = new Set(['text', 'textarea']);

        const randomTagColor = () => TAG_COLORS[Math.floor(Math.random() * TAG_COLORS.length)];

        function parseHexColor(input) {
          if (!input) return null;
          const normalized = String(input).trim();
          const match = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(normalized);
          if (!match) return null;
          let hex = match[1];
          if (hex.length === 3) hex = hex.split('').map(ch => ch + ch).join('');
          const int = parseInt(hex, 16);
          return {
            r: (int >> 16) & 0xff,
            g: (int >> 8) & 0xff,
            b: int & 0xff,
          };
        }

        function buildTagPalette(color) {
          const rgb = parseHexColor(color) || parseHexColor(DEFAULT_TAG_COLOR);
          if (!rgb) return null;
          const { r, g, b } = rgb;
          const text = '#ffffff';
          return {
            border: `rgba(${r}, ${g}, ${b}, 0.55)`,
            background: `rgba(${r}, ${g}, ${b}, 0.18)`,
            hover: `rgba(${r}, ${g}, ${b}, 0.26)`,
            text,
          };
        }

        function inferTagTone(name) {
          const lower = (name || '').toLowerCase();
          if (lower.includes('priority') && lower.includes('high')) return 'warn';
          if (lower.includes('risk') || lower.includes('alert')) return 'warn';
          if (lower.includes('info') || lower.includes('safety') || lower.includes('quality')) return 'info';
          return 'neutral';
        }

        function styleTagPill(pill, tag) {
          if (!pill) return;
          const palette = buildTagPalette(tag.color);
          if (palette) {
            delete pill.dataset.tone;
            pill.style.setProperty('--tag-border', palette.border);
            pill.style.setProperty('--tag-bg', palette.background);
            pill.style.setProperty('--tag-bg-hover', palette.hover);
            pill.style.setProperty('--tag-text', palette.text);
          } else {
            const tone = inferTagTone(tag.name);
            if (tone && tone !== 'neutral') {
              pill.dataset.tone = tone;
            } else {
              delete pill.dataset.tone;
            }
            pill.style.removeProperty('--tag-border');
            pill.style.removeProperty('--tag-bg');
            pill.style.removeProperty('--tag-bg-hover');
            pill.style.removeProperty('--tag-text');
          }
        }

        function createTagChip(tag, { inherited = false, onEdit, onRemove } = {}) {
          const label = `#${tag.name}`;
          const chip = document.createElement('span');
          chip.className = 'tag-pill';
          chip.dataset.inherited = inherited ? '1' : '0';
          chip.tabIndex = 0;
          chip.setAttribute('role', 'button');
          chip.title = label;

          const textEl = document.createElement('span');
          textEl.className = 'tag-pill-label';
          textEl.textContent = label;
          chip.appendChild(textEl);

          styleTagPill(chip, tag);

          if (typeof onRemove === 'function' && !inherited) {
            const removeBtn = document.createElement('button');
            removeBtn.type = 'button';
            removeBtn.className = 'tag-pill-remove';
            removeBtn.innerHTML = '×';
            removeBtn.title = `Remove ${label}`;
            removeBtn.setAttribute('aria-label', `Remove ${label}`);
            removeBtn.addEventListener('click', (evt) => {
              evt.stopPropagation();
              onRemove(tag, chip, evt);
            });
            chip.appendChild(removeBtn);
          }

          if (typeof onEdit === 'function') {
            const openEditor = (evt) => {
              onEdit(tag, chip, evt);
            };
            chip.addEventListener('click', (evt) => {
              if (!inherited && typeof onRemove === 'function' && (evt.altKey || evt.metaKey || evt.shiftKey)) {
                evt.stopPropagation();
                onRemove(tag, chip, evt);
                return;
              }
              openEditor(evt);
            });
            chip.addEventListener('keydown', (evt) => {
              if (evt.key === 'Enter' || evt.key === ' ') {
                evt.preventDefault();
                openEditor(evt);
              }
              if (!inherited && typeof onRemove === 'function' && (evt.key === 'Backspace' || evt.key === 'Delete')) {
                evt.preventDefault();
                onRemove(tag, chip, evt);
              }
            });
          }

          return chip;
        }

        function openFormModal({ title, fields, submitLabel = 'Save', onSubmit, width }) {
          const overlay = document.createElement('div');
          overlay.className = 'modal-overlay';
          const panel = document.createElement('div');
          panel.className = 'modal';
          if (width) panel.style.width = width;
          const form = document.createElement('form');
          form.className = 'modal-form';
          const header = document.createElement('h3');
          header.textContent = title || 'Details';
          const body = document.createElement('div');
          body.className = 'modal-body';
          const errorBox = document.createElement('div');
          errorBox.className = 'modal-error hidden';
          const actions = document.createElement('div');
          actions.className = 'modal-actions';
          const submitBtn = document.createElement('button');
          submitBtn.type = 'submit';
          submitBtn.textContent = submitLabel;
          submitBtn.className = 'modal-submit';
          const cancelBtn = document.createElement('button');
          cancelBtn.type = 'button';
          cancelBtn.textContent = 'Cancel';
          cancelBtn.className = 'modal-cancel';
          actions.append(cancelBtn, submitBtn);

          const fieldRefs = new Map();
          (fields || []).forEach(field => {
            const wrapper = document.createElement('label');
            wrapper.className = 'modal-field';
            wrapper.dataset.field = field.name;
            const title = document.createElement('span');
            title.textContent = field.label || field.name;
            const required = !!field.required;
            if (required) {
              const star = document.createElement('span');
              star.textContent = '*';
              star.className = 'modal-required';
              title.append(star);
            }
            wrapper.appendChild(title);
            let input;
            const type = field.type || 'text';
            if (TEXT_FIELD_TYPES.has(type)) {
              const rows = field.rows || (type === 'textarea' ? 3 : 1);
              input = document.createElement('textarea');
              input.rows = rows;
              input.value = field.value ?? '';
              if (!field.disableAutoGrow) {
                const minHeight = field.minHeight ?? Math.max(26, rows * 22);
                setupAutoGrow(input, {
                  maxPercent: field.maxPercent ?? 0.95,
                  minWidth: field.minWidth ?? 200,
                  maxWidth: field.maxWidth ?? null,
                  minHeight,
                });
                requestAnimationFrame(() => triggerAutoGrow(input));
              }
            } else if (type === 'checkbox') {
              input = document.createElement('input');
              input.type = 'checkbox';
              input.checked = !!field.value;
              wrapper.classList.add('modal-field-checkbox');
            } else if (type === 'select') {
              input = document.createElement('select');
              (field.options || []).forEach(opt => {
                const optionEl = document.createElement('option');
                if (typeof opt === 'string') {
                  optionEl.value = opt;
                  optionEl.textContent = opt;
                } else {
                  optionEl.value = opt.value;
                  optionEl.textContent = opt.label;
                }
                input.appendChild(optionEl);
              });
              if (field.value !== undefined && field.value !== null) input.value = field.value;
            } else {
              input = document.createElement('input');
              input.type = type;
              input.value = field.value ?? '';
            }
            if (field.placeholder) input.placeholder = field.placeholder;
            if (field.maxLength) input.maxLength = field.maxLength;
            if (field.disabled) input.disabled = true;
            input.name = field.name;
            wrapper.appendChild(input);
            if (field.hint) {
              const hint = document.createElement('small');
              hint.className = 'modal-hint';
              hint.textContent = field.hint;
              wrapper.appendChild(hint);
            }
            body.appendChild(wrapper);
            fieldRefs.set(field.name, { config: field, element: input });
          });

          const close = () => {
            document.removeEventListener('keydown', handleKeydown);
            overlay.remove();
          };

          const setError = (message) => {
            if (!message) {
              errorBox.classList.add('hidden');
              errorBox.textContent = '';
            } else {
              errorBox.textContent = message;
              errorBox.classList.remove('hidden');
            }
          };

          const setBusy = (busy) => {
            submitBtn.disabled = !!busy;
            form.classList.toggle('modal-busy', !!busy);
          };

          const handleKeydown = (evt) => {
            if (evt.key === 'Escape') {
              evt.preventDefault();
              close();
            }
          };

          form.addEventListener('submit', async (evt) => {
            evt.preventDefault();
            if (!onSubmit) {
              close();
              return;
            }
            const data = {};
            for (const [name, ref] of fieldRefs.entries()) {
              const { config, element } = ref;
              let value;
              if (config.type === 'checkbox') {
                value = !!element.checked;
              } else if (config.type === 'number') {
                value = element.value === '' ? null : Number(element.value);
              } else {
                value = element.value;
                if (config.trim !== false && typeof value === 'string') value = value.trim();
              }
              if (config.required && (value === '' || value === null || value === undefined)) {
                setError(`${config.label || config.name} is required.`);
                element.focus();
                return;
              }
              data[name] = value;
            }
            setError('');
            try {
              setBusy(true);
              await onSubmit(data, { close, setError, setBusy });
            } catch (err) {
              console.error(err);
              setError(err?.message || String(err));
            } finally {
              setBusy(false);
            }
          });

          cancelBtn.addEventListener('click', () => close());
          overlay.addEventListener('click', (evt) => {
            if (evt.target === overlay) close();
          });
          document.addEventListener('keydown', handleKeydown);

          form.append(header, errorBox, body, actions);
          panel.appendChild(form);
          overlay.appendChild(panel);
          document.body.appendChild(overlay);

          const firstInput = body.querySelector('input, textarea, select');
          if (firstInput && typeof firstInput.focus === 'function') {
            setTimeout(() => firstInput.focus(), 60);
          }

          return { close, setError, setBusy };
        }

        function ensureBanner() {
          if (fundingState.bannerEl) return fundingState.bannerEl;
          const banner = document.createElement('div');
          banner.id = 'jobBanner';
          banner.className = 'banner hidden';
          document.body.appendChild(banner);
          fundingState.bannerEl = banner;
          return banner;
        }

        function showBanner(message, tone = 'info') {
          const banner = ensureBanner();
          banner.textContent = message;
          banner.className = `banner banner-${tone}`;
          banner.classList.remove('hidden');
          if (fundingState.bannerTimer) {
            clearTimeout(fundingState.bannerTimer);
            fundingState.bannerTimer = null;
          }
        }

        function hideBanner(delay = 0) {
          const banner = ensureBanner();
          if (delay) {
            if (fundingState.bannerTimer) clearTimeout(fundingState.bannerTimer);
            fundingState.bannerTimer = setTimeout(() => {
              banner.classList.add('hidden');
              fundingState.bannerTimer = null;
            }, delay);
          } else {
            banner.classList.add('hidden');
          }
        }

        async function pollJob(jobId, onDone) {
          const poll = async () => {
            try {
              const info = await api(`/api/admin/jobs/${jobId}`);
              if (info.status === 'running' || info.status === 'queued') {
                fundingState.jobPollers.set(jobId, setTimeout(poll, 1200));
                return;
              }
              fundingState.jobPollers.delete(jobId);
              onDone(info);
            } catch (err) {
              fundingState.jobPollers.delete(jobId);
              onDone({ status: 'error', error: err.message || String(err) });
            }
          };
          await poll();
        }

        async function enqueueScopedRebuild(scope, actor = 'UI') {
          try {
            const query = scope ? `?only_for=${encodeURIComponent(`${scope.entity_type}:${scope.entity_id}`)}` : '';
            const job = await api(`/api/admin/rebuild-effective-tags${query}`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ actor }),
            });
            showBanner('Updating tags…', 'info');
            await pollJob(job.id, (info) => {
              if (info.status === 'success') {
                showBanner('Tags updated', 'success');
                hideBanner(1200);
              } else {
                showBanner(`Tag rebuild failed: ${info.error || 'unknown error'}`, 'error');
              }
            });
          } catch (err) {
            showError(err);
          }
        }

        function clearFundingState() {
          fundingState.budgets = [];
          fundingState.filteredBudgets = [];
          fundingState.selectedBudgetId = null;
          fundingState.budgetMap.clear();
          fundingState.budgetTree = [];
          fundingState.expanded.clear();
        }

        async function fetchTagsCached(query = '') {
          const needle = query.trim().toLowerCase();
          if (fundingState.tagCache.has(needle)) return fundingState.tagCache.get(needle);
          const list = await api(`/api/tags${needle ? `?q=${encodeURIComponent(needle)}` : ''}`);
          fundingState.tagCache.set(needle, list);
          return list;
        }

        async function refreshTagUsage() {
          fundingState.usageCache = await api('/api/tags/usage');
          return fundingState.usageCache;
        }

        function getUsageFor(tagId) {
          if (!fundingState.usageCache) return null;
          const entry = fundingState.usageCache.find(item => item.tag.id === tagId);
          return entry ? entry.assignments : null;
        }

        function formatTagLabel(tag) {
          return `#${tag.name}`;
        }

        const TAG_PICKERS = new Set();
        const TAG_EDITORS = new Set();

        function closeAllPopovers(except = null) {
          TAG_PICKERS.forEach(p => { if (p !== except) p.destroy(); });
          TAG_EDITORS.forEach(p => { if (p !== except) p.destroy(); });
        }

        document.addEventListener('click', (evt) => {
          const target = evt.target;
          const inPicker = target.closest?.('.tag-picker-panel');
          const inEditor = target.closest?.('.tag-editor-panel');
          if (!inPicker) TAG_PICKERS.forEach(p => p.destroy());
          if (!inEditor) TAG_EDITORS.forEach(p => p.destroy());
        });

        function toScopeType(nodeType) {
          if (nodeType === 'project') return 'item_project';
          return nodeType;
        }

        function mutateBundle(bundle, updater) {
          if (!bundle) return;
          ['direct', 'inherited', 'effective'].forEach(key => {
            const list = bundle[key];
            if (!Array.isArray(list)) return;
            bundle[key] = list.map(item => updater({ ...item }))
              .filter(Boolean);
          });
        }

        function applyTagUpdate(updated) {
          const apply = (bundle) => mutateBundle(bundle, chip => {
            if (chip.id === updated.id) {
              chip.name = updated.name;
              chip.color = updated.color;
              chip.is_deprecated = updated.is_deprecated;
            }
            return chip;
          });
          fundingState.budgets.forEach(b => apply(b.tags));
          fundingState.budgetTree.forEach(node => apply(node.tags));
          fundingState.budgetMap.forEach(budget => apply(budget.tags));
        }

        function removeTagFromBundles(tagId, scope) {
          const predicate = (chip) => (chip.id === tagId && (!scope || toScopeType(scope.entity_type) === toScopeType(scope.type)));
          const remove = (bundle) => mutateBundle(bundle, chip => predicate(chip) ? null : chip);
          fundingState.budgets.forEach(b => remove(b.tags));
          fundingState.budgetTree.forEach(node => remove(node.tags));
          fundingState.budgetMap.forEach(budget => remove(budget.tags));
        }

        function updateTagCaches(tag) {
          fundingState.tagCache.forEach((arr, key) => {
            const idx = arr.findIndex(t => t.id === tag.id);
            if (idx >= 0) arr[idx] = { ...arr[idx], ...tag };
          });
        }

        function destroyPopover(popover, set) {
          if (!popover) return;
          popover.remove();
          set.delete(popover.__controller);
        }

        function positionPopover(panel, anchor, offsetY = 6) {
          const rect = anchor.getBoundingClientRect();
          const bodyRect = document.body.getBoundingClientRect();
          const top = rect.bottom + offsetY;
          const left = Math.min(rect.left, window.innerWidth - panel.offsetWidth - 16);
          panel.style.top = `${Math.max(8, top + window.scrollY)}px`;
          panel.style.left = `${Math.max(8, left + window.scrollX)}px`;
        }

        function formatUsageSummary(assignments) {
          if (!assignments) return '';
          const parts = Object.entries(assignments).filter(([, v]) => v > 0).map(([k, v]) => `${k}: ${v}`);
          return parts.join(', ');
        }

        function openTagEditor(anchor, tag, { onSaved } = {}) {
          closeAllPopovers();
          const panel = document.createElement('div');
          panel.className = 'tag-editor-panel';
          panel.innerHTML = `
            <div class="tag-editor">
              <div class="tag-editor-header">
                <span class="tag-editor-title">Edit tag</span>
                <button type="button" class="tag-editor-close">×</button>
              </div>
              <label class="tag-editor-field">Name
                <div class="tag-editor-input-group">
                  <span>#</span>
                  <input type="text" class="tag-editor-name" value="${escapeHtml(tag.name)}" autocomplete="off" />
                </div>
              </label>
              <label class="tag-editor-field">Color
                <input type="color" class="tag-editor-color" value="${tag.color || randomTagColor()}" />
              </label>
              <label class="tag-editor-field">Description
                <textarea class="tag-editor-desc" rows="3" placeholder="Optional">${escapeHtml(tag.description || '')}</textarea>
              </label>
              <label class="tag-editor-field checkbox"><input type="checkbox" class="tag-editor-deprecated" ${tag.is_deprecated ? 'checked' : ''}/> Deprecated</label>
              <div class="tag-editor-actions">
                <button type="button" class="tag-editor-save">Save</button>
                <button type="button" class="tag-editor-delete">Delete</button>
              </div>
            </div>`;
          document.body.appendChild(panel);
          positionPopover(panel, anchor, 8);

          const controller = {
            destroy() {
              destroyPopover(panel, TAG_EDITORS);
            },
          };
          panel.__controller = controller;
          TAG_EDITORS.add(controller);

          const nameInput = panel.querySelector('.tag-editor-name');
          const colorInput = panel.querySelector('.tag-editor-color');
          const descInput = panel.querySelector('.tag-editor-desc');
          if (descInput) {
            setupAutoGrow(descInput, { maxPercent: 0.9, minWidth: 220, minHeight: 60 });
          }
          const deprecatedInput = panel.querySelector('.tag-editor-deprecated');
          const deleteBtn = panel.querySelector('.tag-editor-delete');
          const closeBtn = panel.querySelector('.tag-editor-close');
          const saveBtn = panel.querySelector('.tag-editor-save');

          let deleteDisabled = false;
          (async () => {
            try {
              const usage = await (fundingState.usageCache ? Promise.resolve(fundingState.usageCache) : refreshTagUsage());
              const entry = usage.find(item => item.tag.id === tag.id);
              const assignments = entry ? entry.assignments : null;
              const summary = formatUsageSummary(assignments);
              if (summary) {
                deleteBtn.disabled = true;
                deleteBtn.title = `Cannot delete — in use (${summary})`;
                deleteDisabled = true;
              }
            } catch (err) {
              console.warn('Usage lookup failed', err);
            }
          })();

          closeBtn.onclick = () => controller.destroy();

          async function persistChanges() {
            const newName = nameInput.value.trim().toLowerCase();
            if (!newName.match(/^[a-z0-9_.:-]+$/)) {
              alert('Tag names must be lowercase alphanumerics or - _ . :');
              return;
            }
            const updates = {};
            const patch = {};
            if (newName && newName !== tag.name) {
              updates.name = newName;
            }
            const newColor = colorInput.value || null;
            if ((tag.color || '').toLowerCase() !== (newColor || '').toLowerCase()) {
              patch.color = newColor;
            }
            const newDesc = descInput.value.trim() || null;
            if ((tag.description || '') !== (newDesc || '')) {
              patch.description = newDesc;
            }
            const newDeprecated = !!deprecatedInput.checked;
            if (!!tag.is_deprecated !== newDeprecated) {
              patch.is_deprecated = newDeprecated;
            }

            try {
              let current = { ...tag };
              if (Object.keys(updates).length) {
                const renamed = await api(`/api/tags/${tag.id}/rename`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ name: updates.name, actor: 'UI' }),
                });
                current = { ...current, ...renamed };
              }
              if (Object.keys(patch).length) {
                const patched = await api(`/api/tags/${tag.id}`, {
                  method: 'PATCH',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ ...patch, actor: 'UI' }),
                });
                current = { ...current, ...patched };
              }
              updateTagCaches(current);
              applyTagUpdate(current);
              fundingState.tagCache.delete('');
              if (typeof onSaved === 'function') onSaved(current);
              controller.destroy();
            } catch (err) {
              showError(err);
            }
          }

          async function deleteTag() {
            if (deleteDisabled) return;
            if (!confirm(`Delete tag #${tag.name}? This cannot be undone.`)) return;
            try {
              await api(`/api/tags/${tag.id}`, { method: 'DELETE' });
              removeTagFromBundles(tag.id);
              fundingState.tagCache.forEach((arr, key) => {
                fundingState.tagCache.set(key, arr.filter(t => t.id !== tag.id));
              });
              if (typeof onSaved === 'function') onSaved(null);
              controller.destroy();
            } catch (err) {
              showError(err);
            }
          }

          panel.addEventListener('keydown', (evt) => {
            if (evt.key === 'Escape') {
              evt.preventDefault();
              controller.destroy();
            }
            if (evt.key === 'Enter' && !evt.shiftKey) {
              evt.preventDefault();
              persistChanges();
            }
          });

          saveBtn.onclick = persistChanges;
          deleteBtn.onclick = deleteTag;
        }

        function openTagPicker(anchor, { node, directIds = new Set(), onAssigned, onCreated } = {}) {
          closeAllPopovers();
          const panel = document.createElement('div');
          panel.className = 'tag-picker-panel';
          panel.innerHTML = `
            <div class="tag-picker">
              <input class="tag-search" placeholder="Search or create…" />
              <div class="tag-results tag-loading">
                <div class="tag-row skeleton"></div>
                <div class="tag-row skeleton"></div>
                <div class="tag-row skeleton"></div>
              </div>
            </div>`;
          document.body.appendChild(panel);
          positionPopover(panel, anchor);

          const controller = {
            destroy() {
              if (!panel.isConnected) return;
              panel.remove();
              TAG_PICKERS.delete(controller);
            }
          };
          panel.__controller = controller;
          TAG_PICKERS.add(controller);

          const scope = { entity_type: toScopeType(node.type), entity_id: node.id };
          const inputEl = panel.querySelector('.tag-search');
          const resultsEl = panel.querySelector('.tag-results');
          let query = '';
          let results = [];
          let highlight = -1;
          let loading = false;
          let pending;

          const inheritedIds = new Set((node.tags?.inherited || []).map(t => t.id));

          function renderRows(list) {
            resultsEl.innerHTML = '';
            if (!list.length && query) {
              const createRow = document.createElement('div');
              createRow.className = 'tag-row create';
              createRow.textContent = `Create tag “#${query}”`;
              createRow.tabIndex = 0;
              createRow.addEventListener('click', () => createTag(query));
              resultsEl.appendChild(createRow);
              highlight = 0;
              return;
            }
            list.forEach((tag, idx) => {
              const row = document.createElement('div');
              row.className = 'tag-row';
              if (tag.is_deprecated) row.classList.add('disabled');
              if (directIds.has(tag.id)) {
                row.classList.add('disabled');
                row.title = 'Already assigned';
              }
              const swatch = document.createElement('span');
              swatch.className = 'tag-swatch';
              swatch.style.background = tag.color || '#4b5771';
              row.appendChild(swatch);
              const name = document.createElement('span');
              name.className = 'tag-name';
              name.textContent = `#${tag.name}`;
              row.appendChild(name);
              if (tag.description) {
                const desc = document.createElement('span');
                desc.className = 'tag-desc';
                desc.textContent = tag.description;
                row.appendChild(desc);
              }
              if (tag.is_deprecated) {
                const badge = document.createElement('span');
                badge.className = 'tag-badge';
                badge.textContent = 'Deprecated';
                row.appendChild(badge);
              }
              const editBtn = document.createElement('button');
              editBtn.type = 'button';
              editBtn.className = 'tag-row-edit';
              editBtn.textContent = '✎';
              editBtn.title = 'Edit tag';
              editBtn.addEventListener('click', (evt) => {
                evt.stopPropagation();
                openTagEditor(editBtn, tag, {
                  onSaved: (updated) => {
                    if (updated) {
                      tag.name = updated.name;
                      tag.color = updated.color;
                      tag.description = updated.description;
                      tag.is_deprecated = updated.is_deprecated;
                      updateTagCaches(updated);
                      renderRows(results);
                    } else {
                      results = results.filter(x => x.id !== tag.id);
                      renderRows(results);
                    }
                  },
                });
              });
              row.appendChild(editBtn);
              row.addEventListener('click', () => {
                if (row.classList.contains('disabled')) return;
                assignTag(tag);
              });
              if (idx === highlight) row.classList.add('highlight');
              resultsEl.appendChild(row);
            });
          }

          async function assignTag(tag) {
            try {
              await api('/api/tags/assign', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tag_id: tag.id, entity_type: scope.entity_type, entity_id: scope.entity_id, actor: 'UI' }),
              });
              controller.destroy();
              if (typeof onAssigned === 'function') await Promise.resolve(onAssigned(tag));
              enqueueScopedRebuild(scope);
            } catch (err) {
              showError(err);
            }
          }

          async function createTag(nameInput) {
            const clean = nameInput.trim().toLowerCase();
            if (!clean.match(/^[a-z0-9_.:-]+$/)) {
              alert('Tag names must be lowercase alphanumerics or - _ . :');
              return;
            }
            try {
              const newTag = await api('/api/tags', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: clean, color: randomTagColor(), actor: 'UI' }),
              });
              fundingState.tagCache.clear();
              if (typeof onCreated === 'function') await Promise.resolve(onCreated(newTag));
              await assignTag(newTag);
            } catch (err) {
              showError(err);
            }
          }

          const load = async () => {
            loading = true;
            resultsEl.classList.add('tag-loading');
            try {
              const res = await fetchTagsCached(query);
              results = res.filter(tag => !directIds.has(tag.id));
              resultsEl.classList.remove('tag-loading');
              loading = false;
              highlight = results.length ? 0 : -1;
              renderRows(results);
            } catch (err) {
              showError(err);
            }
          };

          inputEl.addEventListener('input', () => {
            if (pending) clearTimeout(pending);
            query = inputEl.value.trim();
            pending = setTimeout(load, 220);
          });

          panel.addEventListener('keydown', (evt) => {
            if (evt.key === 'Escape') {
              evt.preventDefault();
              controller.destroy();
            }
            if (evt.key === 'ArrowDown') {
              evt.preventDefault();
              if (!results.length) return;
              highlight = (highlight + 1) % results.length;
              renderRows(results);
            }
            if (evt.key === 'ArrowUp') {
              evt.preventDefault();
              if (!results.length) return;
              highlight = (highlight - 1 + results.length) % results.length;
              renderRows(results);
            }
            if (evt.key === 'Enter') {
              evt.preventDefault();
              if (highlight >= 0 && results[highlight]) {
                assignTag(results[highlight]);
              } else if (!results.length && query) {
                createTag(query);
              }
            }
          });

          load();
          inputEl.focus();
        }



        function setupAutoGrow(field, { maxPercent = 0.33, minWidth = 140, maxWidth = null, minHeight = 26 } = {}) {
          if (!field || field.__autoGrowHandler) return;
          field.style.resize = 'none';
          field.style.overflow = 'hidden';
          field.style.minHeight = `${minHeight}px`;
          field.style.minWidth = `${minWidth}px`;

          const computeWidth = () => {
            const host = field.closest('[data-auto-grow-host], .ledger-row, .ledger-header-line, .ledger-budget-card, .modal-field, .modal');
            const hostWidth = host ? host.clientWidth : 0;
            let limit = hostWidth ? hostWidth * maxPercent : minWidth * 2;
            if (typeof maxWidth === 'number' && !Number.isNaN(maxWidth)) {
              limit = Math.min(limit, maxWidth);
            }
            return Math.max(minWidth, limit || minWidth);
          };

          const update = () => {
            const nextWidth = computeWidth();
            field.style.width = `${nextWidth}px`;
            field.style.height = 'auto';
            const nextHeight = Math.max(minHeight, field.scrollHeight);
            field.style.height = `${nextHeight}px`;
          };

          const handler = () => requestAnimationFrame(update);
          field.__autoGrowHandler = handler;

          const cleanup = () => {
            field.removeEventListener('input', handler);
            field.removeEventListener('focus', handler);
            field.removeEventListener('blur', handler);
            window.removeEventListener('resize', handler);
            if (field.__autoGrowObserver) {
              field.__autoGrowObserver.disconnect();
              delete field.__autoGrowObserver;
            }
            delete field.__autoGrowHandler;
          };

          field.addEventListener('input', handler);
          field.addEventListener('focus', handler);
          field.addEventListener('blur', handler);
          window.addEventListener('resize', handler);

          let observer = null;
          if (typeof MutationObserver !== 'undefined') {
            observer = new MutationObserver(() => {
              if (!field.isConnected) {
                cleanup();
              }
            });
            observer.observe(document.body, { childList: true, subtree: true });
            field.__autoGrowObserver = observer;
          }

          update();
          requestAnimationFrame(update);
          return cleanup;
        }

        function triggerAutoGrow(field) {
          if (field && typeof field.__autoGrowHandler === 'function') {
            field.__autoGrowHandler();
          }
        }

        function ensureReallocateDrawer() {
          if (reallocateDrawer) return reallocateDrawer;
          const drawer = document.createElement('div');
          drawer.id = 'reallocateDrawer';
          drawer.className = 'drawer hidden';
          const reallocateFundingHandlers = { key: 'portfolio', ...buildResourceDropdownHandlers('/api/portfolios', {
            formatLabel: formatPortfolioLabel,
            matcherFields: ['name'],
          }) };
          const reallocateCategoryHandlers = { key: 'category', ...buildResourceDropdownHandlers('/api/categories', {
            formatLabel: (cat) => cat.name,
            matcherFields: ['name'],
          }) };

          drawer.innerHTML = `
            <div class="drawer-panel">
              <div class="drawer-header">
                <h3>Reallocate Entry</h3>
                <button type="button" id="closeReallocate">×</button>
              </div>
              <form id="reallocateForm">
                <div class="field"><label>Source</label><div id="reallocateSource"></div></div>
                <div class="field">
                  <label for="reallocateFunding">Destination Funding Source</label>
                  ${select('funding_source', [], reallocateFundingHandlers)}
                </div>
                <div class="field">
                  <label for="reallocateCategory">Destination Category</label>
                  ${select('category', [], reallocateCategoryHandlers)}
                </div>
                <div class="field">
                  <label for="reallocateAmount">Amount</label>
                  <input id="reallocateAmount" name="amount" type="number" step="0.01" />
                </div>
                <div class="field">
                  <label for="reallocateMemo">Memo</label>
                  <input id="reallocateMemo" name="memo" placeholder="Reason" />
                </div>
                <div class="actions">
                  <button type="submit">Submit</button>
                </div>
              </form>
            </div>`;
          document.body.appendChild(drawer);
          initializeDropdowns(drawer);
          drawer.querySelector('#closeReallocate').onclick = () => closeReallocate();
          reallocateSubmit = drawer.querySelector('#reallocateForm');
          reallocateSubmit.addEventListener('submit', async (evt) => {
            evt.preventDefault();
            if (!reallocateCurrent) return;
            const fsId = Number(drawer.querySelector('select[name=funding_source]').value);
            const categoryId = Number(drawer.querySelector('select[name=category]').value);
            const amount = drawer.querySelector('#reallocateAmount').value;
            const memo = drawer.querySelector('#reallocateMemo').value || 'Reallocate entry';
            if (!fsId || Number.isNaN(fsId)) return alert('Pick a funding source.');
            if (!categoryId || Number.isNaN(categoryId)) return alert('Pick a category.');
            try {
              await ApiNew.postReallocate({
                transaction_id: reallocateCurrent.transaction_id || String(reallocateCurrent.id),
                target_funding_source_id: fsId,
                amount: Number(amount || reallocateCurrent.amount || 0),
                memo,
              });
              alert('Reallocation sent.');
              closeReallocate();
              renderEntries();
            } catch (err) {
              showError(err);
            }
          });
          reallocateDrawer = drawer;
          return drawer;
        }

        function openReallocate(entry, fundingSources, categories) {
          reallocateCurrent = entry;
          const drawer = ensureReallocateDrawer();
          drawer.classList.remove('hidden');
          const sourceBox = drawer.querySelector('#reallocateSource');
          sourceBox.innerHTML = `#${entry.id} • ${entry.kind || ''} • ${fmtCurrency(entry.amount)}\n<small>${entry.description || ''}</small>`;
          const fundingSel = drawer.querySelector('select[name=funding_source]');
          const categorySel = drawer.querySelector('select[name=category]');

          if (fundingSel && fundingSel.__dropdown) {
            const options = fundingSources.map(fs => ({ value: fs.id, label: fs.name, raw: fs }));
            const dropdown = fundingSel.__dropdown;
            dropdown.options = options;
            dropdown.optionMap = new Map(options.map(opt => [String(opt.value), opt]));
            fundingSel.innerHTML = options.map(opt => `<option value="${escapeHtml(opt.value)}">${escapeHtml(opt.label)}</option>`).join('');
            dropdown.filterOptions('');
            dropdown.selected = null;
            dropdown.showSelection = dropdown.config.prefill;
            fundingSel.value = '';
            dropdown.inputEl.value = '';
          } else if (fundingSel) {
            fundingSel.innerHTML = fundingSources.map(fs => `<option value="${fs.id}">${fs.name}</option>`).join('');
          }

          if (categorySel && categorySel.__dropdown) {
            const options = categories.map(c => ({ value: c.id, label: c.label, raw: c }));
            const dropdown = categorySel.__dropdown;
            dropdown.options = options;
            dropdown.optionMap = new Map(options.map(opt => [String(opt.value), opt]));
            categorySel.innerHTML = options.map(opt => `<option value="${escapeHtml(opt.value)}">${escapeHtml(opt.label)}</option>`).join('');
            dropdown.filterOptions('');
            dropdown.selected = null;
            dropdown.showSelection = dropdown.config.prefill;
            categorySel.value = '';
            dropdown.inputEl.value = '';
          } else if (categorySel) {
            categorySel.innerHTML = categories.map(c => `<option value="${c.id}">${c.label}</option>`).join('');
          }
          drawer.querySelector('#reallocateAmount').value = entry.amount || '';
          drawer.querySelector('#reallocateMemo').value = '';
        }

        function closeReallocate() {
          if (reallocateDrawer) reallocateDrawer.classList.add('hidden');
          reallocateCurrent = null;
        }
  
        // Expose update/delete for table buttons
        window.__updateRow = async function(base, id, btn){
          try {
            const tr = btn.closest('tr');
            const tds = [...tr.querySelectorAll('[data-field]')];
            const body = {};
            tds.forEach(td => {
              const field = td.dataset.field;
              let value;
              if (td.dataset.editor === 'dropdown') {
                const selectEl = td.querySelector('select');
                value = selectEl ? selectEl.value : (td.dataset.raw ?? '');
                const wrapper = td.querySelector('.dropdown');
                if (wrapper) wrapper.title = value;
              } else {
                value = td.innerText.trim();
              }
              td.dataset.raw = value;
              td.title = value;
              body[field] = value;
            });
            delete body.id;

            const ALLOW = {
              '/api/portfolios': ['name','fiscal_year','owner'],
              '/api/projects': ['portfolio_id','name','group_id','code','line'],
              '/api/categories': ['name','parent_id','project_id'],
              '/api/vendors': ['name'],
              '/api/entries': ['date','kind','amount','description','portfolio_id','project_id','category_id','vendor_id','po_number','quote_ref','mischarged','intended_portfolio_id']
            };
            const allowed = ALLOW[base];
            if (allowed) Object.keys(body).forEach(k => { if (!allowed.includes(k)) delete body[k]; });
  
            ['portfolio_id','project_id','group_id','parent_id','category_id','vendor_id','intended_portfolio_id'].forEach(k=>{
              if (k in body) body[k] = (body[k]===''? null : Number(body[k]));
            });
            if ('amount' in body) body.amount = body.amount===''? null : Number(body.amount);
            if ('mischarged' in body) {
              const v = (body.mischarged || '').toString().toLowerCase();
              body.mischarged = v === 'true' || v === '1' || v === 'yes';
            }
  
            await apiUpdate(`${base}/${id}`, body);
            alert('Saved');
          } catch (e) { showError(e); }
        };
        window.__deleteRow = async function(base, id){
          try {
            if(!confirm('Delete row ' + id + '?')) return;
            await apiDelete(`${base}/${id}`);
            renderActive();
          } catch (e) { showError(e); }
        };
  
        // ---------- Renderers ----------
        async function renderPortfolios(){
          clearFundingState();
          fundingState.searchTerm = '';
          fundingState.tagCache.clear();
          fundingState.usageCache = null;

          content.innerHTML = `
            <div class="funding-shell">
              <aside class="funding-sidebar">
                <div class="funding-toolbar">
                  <div class="funding-toolbar-actions">
                    <button id="newBudgetButton" class="btn-primary">+ New Budget</button>
                    <button id="tagManagerButton">Tag Manager</button>
                    <button id="rebuildTagsButton">Rebuild Effective Tags</button>
                  </div>
                  <input id="budgetSearch" class="input" placeholder="Search budgets…" autocomplete="off" />
                </div>
                <div id="fundingList" class="funding-list"></div>
              </aside>
              <section id="fundingLedger" class="funding-ledger">
                <div class="funding-empty">Select a funding source to inspect.</div>
              </section>
              <aside id="inspectorDrawer" class="drawer hidden"></aside>
            </div>`;

          const listEl = content.querySelector('#fundingList');
          const ledgerEl = content.querySelector('#fundingLedger');
          const inspectorEl = content.querySelector('#inspectorDrawer');
          const shellEl = content.querySelector('.funding-shell');
          const searchInput = content.querySelector('#budgetSearch');
          const newBudgetBtn = content.querySelector('#newBudgetButton');
          const tagManagerBtn = content.querySelector('#tagManagerButton');
          const rebuildBtn = content.querySelector('#rebuildTagsButton');

          const makeKey = (node) => `${node.type}:${node.id}`;

          const expansionStorageKey = (budgetId) => `funding-expanded-${budgetId}`;

          function loadExpansionState(budgetId, availableKeys) {
            if (!budgetId) return null;
            try {
              const raw = localStorage.getItem(expansionStorageKey(budgetId));
              if (!raw) return null;
              const parsed = JSON.parse(raw);
              if (!Array.isArray(parsed)) return null;
              const set = new Set();
              parsed.forEach(key => {
                if (!availableKeys || availableKeys.has(key)) set.add(key);
              });
              return set;
            } catch (err) {
              console.warn('Failed to load expansion state', err);
              return null;
            }
          }

          function persistExpansionState(budgetId, set = fundingState.expanded) {
            if (!budgetId) return;
            try {
              localStorage.setItem(expansionStorageKey(budgetId), JSON.stringify([...set]));
            } catch (err) {
              console.warn('Failed to persist expansion state', err);
            }
          }

          async function loadBudgets(term = '') {
            fundingState.searchTerm = term;
            const query = term ? `/api/budgets?include=stats,tags&q=${encodeURIComponent(term)}` : '/api/budgets?include=stats,tags';
            const budgets = await api(query);
            fundingState.budgets = budgets;
            fundingState.filteredBudgets = budgets;
            fundingState.budgetMap = new Map(budgets.map(b => [b.id, b]));
          }

          async function loadBudgetTree(budgetId) {
            if (!budgetId) {
              ledgerEl.innerHTML = '<div class="funding-empty">Select a funding source to inspect.</div>';
              return;
            }
            const nodes = await api(`/api/budgets/${budgetId}/tree?include=tags,paths,assets`);
            fundingState.budgetTree = nodes;
            const hierarchy = buildHierarchy(nodes);
            fundingState.currentHierarchy = hierarchy;
            const availableKeys = new Set(nodes.map(node => makeKey(node)));
            const savedExpansion = loadExpansionState(budgetId, availableKeys);
            fundingState.expanded.clear();
            if (savedExpansion && savedExpansion.size) {
              savedExpansion.forEach(key => fundingState.expanded.add(key));
            } else {
              const queue = hierarchy ? [hierarchy] : [];
              while (queue.length) {
                const node = queue.shift();
                const key = makeKey(node);
                if (availableKeys.has(key)) fundingState.expanded.add(key);
                if (node.children && node.children.length) {
                  queue.push(...node.children);
                }
              }
            }
            if (hierarchy) {
              fundingState.expanded.add(makeKey(hierarchy));
            }
            persistExpansionState(budgetId);
            renderLedger();
          }

          function buildHierarchy(nodes) {
            if (!nodes || !nodes.length) return null;
            const budgetNode = nodes.find(n => n.type === 'budget');
            if (!budgetNode) return null;
            const projectMap = new Map();
            const categoryMap = new Map();
            nodes.forEach(node => {
              if (node.type === 'project') {
                node.children = [];
                projectMap.set(node.id, node);
              } else if (node.type === 'category') {
                node.children = [];
                categoryMap.set(node.id, node);
              }
            });
            nodes.forEach(node => {
              if (node.type === 'category') {
                if (node.parent_id) {
                  const parent = categoryMap.get(node.parent_id);
                  if (parent) parent.children.push(node);
                } else {
                  const parentProject = projectMap.get(node.project_id || node.item_project_id);
                  if (parentProject) parentProject.children.push(node);
                }
              }
            });
            budgetNode.children = Array.from(projectMap.values());
            fundingState.projectNodeMap = projectMap;
            fundingState.categoryNodeMap = categoryMap;
            return budgetNode;
          }

          function renderBudgetList() {
            listEl.innerHTML = '';
            if (!fundingState.budgets.length) {
              const empty = document.createElement('div');
              empty.className = 'funding-list-empty';
              empty.textContent = 'No funding sources found.';
              listEl.appendChild(empty);
              return;
            }
            fundingState.budgets.forEach(budget => {
              const item = document.createElement('button');
              item.className = 'funding-item';
              if (budget.id === fundingState.selectedBudgetId) item.classList.add('active');

              const name = document.createElement('div');
              name.className = 'funding-item-name';
              name.textContent = budget.name;
              item.appendChild(name);

              const total = document.createElement('div');
              total.className = 'funding-item-total';
              const numericTotal = Number(budget.budget_amount_cache || 0);
              if (numericTotal < 0) total.classList.add('err');
              else if (!numericTotal) total.classList.add('warn');
              total.textContent = fmtCurrency(numericTotal);
              item.appendChild(total);

              const metrics = document.createElement('div');
              metrics.className = 'funding-item-metrics';
              const stats = budget.stats || {};
              const metricDefs = [
                { label: 'Categories', value: stats.category_count },
                { label: 'Leaves', value: stats.leaf_count },
                { label: 'Entries', value: stats.entry_count },
                { label: 'Alloc', value: stats.allocation_count },
              ];
              metricDefs.forEach(def => {
                if (def.value === undefined || def.value === null) return;
                const span = document.createElement('span');
                span.className = 'funding-item-metric';
                span.innerHTML = `<span>${def.label}</span><strong>${def.value}</strong>`;
                metrics.appendChild(span);
              });
              const owner = document.createElement('span');
              owner.className = 'funding-item-metric';
              owner.innerHTML = `<span>Owner</span><strong>${escapeHtml(budget.owner || '—')}</strong>`;
              metrics.appendChild(owner);
              item.appendChild(metrics);

              const tagsLine = document.createElement('div');
              tagsLine.className = 'funding-item-tags';
              const directTags = (budget.tags?.direct || []).slice(0, 5);
              directTags.forEach(tag => {
                const chip = document.createElement('span');
                chip.textContent = `#${tag.name}`;
                tagsLine.appendChild(chip);
              });
              if (budget.is_cost_center) {
                const chip = document.createElement('span');
                chip.textContent = 'COST CENTER';
                tagsLine.appendChild(chip);
              }
              if (tagsLine.children.length) item.appendChild(tagsLine);

              item.addEventListener('click', () => selectBudget(budget.id));
              listEl.appendChild(item);
            });
          }

          function attachTagRow(container, node, { showLabel = false } = {}) {
            const scope = { entity_type: toScopeType(node.type), entity_id: node.id, type: node.type };
            if (container.__tagObserver) container.__tagObserver.disconnect();
            if (container.__tagOutside) {
              document.removeEventListener('mousedown', container.__tagOutside, true);
            }
            container.innerHTML = '';
            container.classList.add('tag-region');
            container.style.position = 'relative';

            const listEl = document.createElement('div');
            listEl.className = 'tag-list';
            container.appendChild(listEl);

            const addBtn = document.createElement('button');
            addBtn.type = 'button';
            addBtn.className = 'tag-add';
            addBtn.textContent = '+ Add tag';
            container.appendChild(addBtn);

            const tags = node.tags || { direct: [], inherited: [] };
            const directIds = new Set((tags.direct || []).map(t => t.id));
            const tagModels = [
              ...(tags.direct || []).map(tag => ({ ...tag, inherited: false })),
              ...(tags.inherited || []).map(tag => ({ ...tag, inherited: true })),
            ];

            const buildPill = (tag) => {
              const label = `#${tag.name}`;
              const pill = document.createElement('span');
              pill.className = 'tag-pill';
              pill.dataset.inherited = tag.inherited ? '1' : '0';
              pill.tabIndex = 0;
              pill.setAttribute('role', 'button');
              pill.title = label;

              const labelEl = document.createElement('span');
              labelEl.className = 'tag-pill-label';
              labelEl.textContent = label;
              pill.appendChild(labelEl);

              styleTagPill(pill, tag);

              const unassignTag = async () => {
                if (tag.inherited) return;
                try {
                  await api('/api/tags/assign', {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ tag_id: tag.id, entity_type: scope.entity_type, entity_id: scope.entity_id, actor: 'UI' }),
                  });
                  directIds.delete(tag.id);
                  const idx = tagModels.findIndex(model => model.id === tag.id && !model.inherited);
                  if (idx >= 0) tagModels.splice(idx, 1);
                  removeTagFromBundles(tag.id, scope);
                  renderTags();
                  await refreshCurrentBudget();
                  enqueueScopedRebuild(scope);
                } catch (err) {
                  showError(err);
                }
              };

              if (!tag.inherited) {
                const removeBtn = document.createElement('button');
                removeBtn.type = 'button';
                removeBtn.className = 'tag-pill-remove';
                removeBtn.innerHTML = '×';
                removeBtn.title = `Remove ${label}`;
                removeBtn.setAttribute('aria-label', `Remove ${label}`);
                removeBtn.addEventListener('click', (evt) => {
                  evt.stopPropagation();
                  unassignTag();
                });
                pill.appendChild(removeBtn);
              }

              const openEditor = () => {
                openTagEditor(pill, tag, {
                  onSaved: async (updated) => {
                    if (!updated) {
                      await refreshCurrentBudget();
                      return;
                    }
                    applyTagUpdate(updated);
                    const idx = tagModels.findIndex(model => model.id === updated.id);
                    if (idx >= 0) {
                      tagModels[idx] = { ...tagModels[idx], ...updated };
                    }
                    renderTags();
                    await refreshCurrentBudget();
                  },
                });
              };

              pill.addEventListener('click', (evt) => {
                if (!tag.inherited && (evt.altKey || evt.metaKey || evt.shiftKey)) {
                  evt.stopPropagation();
                  unassignTag();
                  return;
                }
                openEditor();
              });

              pill.addEventListener('keydown', (evt) => {
                if (evt.key === 'Enter' || evt.key === ' ') {
                  evt.preventDefault();
                  openEditor();
                }
                if (!tag.inherited && (evt.key === 'Backspace' || evt.key === 'Delete')) {
                  evt.preventDefault();
                  unassignTag();
                }
              });

              return pill;
            };

            function renderTags() {
              listEl.innerHTML = '';
              if (showLabel) {
                const labelEl = document.createElement('span');
                labelEl.className = 'tag-line-label';
                labelEl.textContent = 'Tags:';
                listEl.appendChild(labelEl);
              }
              tagModels.forEach(tag => listEl.appendChild(buildPill(tag)));
            }

            const observer = new ResizeObserver(() => {
              renderTags();
            });
            observer.observe(container);
            container.__tagObserver = observer;

            renderTags();

            addBtn.addEventListener('click', (evt) => {
              evt.stopPropagation();
              openTagPicker(addBtn, {
                node,
                directIds,
                onAssigned: async () => {
                  await refreshCurrentBudget();
                },
                onCreated: async () => {
                  await refreshTagUsage();
                },
              });
            });

            container.__tagOutside = null;
        }

          function makeInlineField(labelText, element, extraClass) {
            const inline = document.createElement('span');
            inline.className = 'ledger-inline';
            inline.dataset.autoGrowHost = '1';
            if (extraClass) inline.classList.add(extraClass);
            const label = document.createElement('span');
            label.className = 'inline-label';
            label.textContent = labelText;
            inline.append(label, element);
            return inline;
          }

          async function saveBudgetPatch(budgetId, patch) {
            if (!patch || !Object.keys(patch).length) return;
            try {
              await api(`/api/budgets/${budgetId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(patch),
              });
              await refreshCurrentBudget();
            } catch (err) {
              showError(err);
            }
          }

          async function saveProjectPatch(projectId, patch) {
            if (!patch || !Object.keys(patch).length) return;
            try {
              await api(`/api/item-projects/${projectId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(patch),
              });
              await refreshCurrentBudget();
            } catch (err) {
              showError(err);
            }
          }

          async function ensureLineAsset(name) {
            const trimmed = (name || '').trim();
            if (!trimmed) return null;
            const key = trimmed.toLowerCase();
            if (fundingState.lineAssetCache.has(key)) return fundingState.lineAssetCache.get(key);
            try {
              const candidates = await api(`/api/line-assets?q=${encodeURIComponent(trimmed)}`);
              const match = (candidates || []).find(asset => asset.name.toLowerCase() === key);
              if (match) {
                fundingState.lineAssetCache.set(key, match);
                return match;
              }
            } catch (err) {
              console.warn('line asset lookup failed', err);
            }
            const created = await apiCreate('/api/line-assets', { name: trimmed });
            fundingState.lineAssetCache.set(key, created);
            return created;
          }

          async function attachAssetToProject(projectId, assetId) {
            await api(`/api/item-projects/${projectId}/line-assets`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ line_asset_id: assetId }),
            });
          }

          async function detachAssetFromProject(projectId, assetId) {
            await api(`/api/item-projects/${projectId}/line-assets/${assetId}`, {
              method: 'DELETE',
            });
          }

          async function saveCategoryPatch(categoryId, patch) {
            if (!patch || !Object.keys(patch).length) return;
            try {
              if (patch.amount_leaf !== undefined && patch.amount_leaf !== null) {
                patch.amount_leaf = Number(patch.amount_leaf);
              }
              await api(`/api/categories/${categoryId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(patch),
              });
              await refreshCurrentBudget();
            } catch (err) {
              showError(err);
            }
          }

          function getProjectNode(projectId) {
            return fundingState.projectNodeMap.get(projectId) || null;
          }

          function getCategoryNode(categoryId) {
            return fundingState.categoryNodeMap.get(categoryId) || null;
          }

          function collectDescendantIds(node, set) {
            if (!node) return;
            set.add(node.id);
            (node.children || []).forEach(child => collectDescendantIds(child, set));
          }

          function buildMoveOptions(projectNode, excludeIds) {
            const options = [];
            if (projectNode) {
              options.push({ value: `project:${projectNode.id}`, label: `${projectNode.name} (Project root)` });
              const queue = [...(projectNode.children || [])];
              while (queue.length) {
                const node = queue.shift();
                if (!node) continue;
                if (excludeIds.has(node.id)) {
                  continue;
                }
                const label = (node.path_names && node.path_names.length)
                  ? node.path_names.join(' › ')
                  : node.name;
                options.push({ value: `category:${node.id}`, label });
                (node.children || []).forEach(child => queue.push(child));
              }
            }
            return options;
          }

          function openCategoryModal({ projectNode, parentCategory = null, isLeaf = false }) {
            if (!projectNode) return;
            const parentName = parentCategory
              ? (parentCategory.path_names && parentCategory.path_names.length
                  ? parentCategory.path_names.join(' › ')
                  : parentCategory.name)
              : projectNode.name;
            openFormModal({
              title: isLeaf ? `New Leaf under ${parentName}` : `New Category under ${parentName}`,
              submitLabel: isLeaf ? 'Create Leaf' : 'Create Category',
              fields: [
                { name: 'name', label: 'Name', required: true, value: '' },
                ...(isLeaf ? [{ name: 'amount', label: 'Initial amount', type: 'number', value: '0.00' }] : []),
              ],
              onSubmit: async (values, helpers) => {
                try {
                  const payload = {
                    name: values.name,
                    project_id: projectNode.id,
                    budget_id: projectNode.budget_id || fundingState.selectedBudgetId,
                    parent_id: parentCategory ? parentCategory.id : null,
                    is_leaf: !!isLeaf,
                    amount_leaf: isLeaf ? Number(values.amount || 0) : null,
                    description: null,
                  };
                  if (isLeaf && Number.isNaN(payload.amount_leaf)) {
                    helpers.setError('Amount must be a number.');
                    return;
                  }
                  if (isLeaf && payload.amount_leaf !== null) {
                    payload.amount_leaf = Math.round(payload.amount_leaf * 100) / 100;
                  }
                  await apiCreate('/api/categories', payload);
                  helpers.close();
                  const budgetKey = projectNode.budget_id || fundingState.selectedBudgetId;
                  if (budgetKey) {
                    const projectKey = `project:${projectNode.id}`;
                    fundingState.expanded.add(projectKey);
                    if (parentCategory) {
                      const parentKey = `${parentCategory.type || 'category'}:${parentCategory.id}`;
                      fundingState.expanded.add(parentKey);
                    }
                    persistExpansionState(budgetKey);
                  }
                  showBanner('Category created', 'success');
                  hideBanner(1500);
                  await refreshCurrentBudget();
                } catch (err) {
                  helpers.setError(err?.message || String(err));
                }
              },
            });
          }

          function openMoveCategoryModal(category) {
            let projectNode = getProjectNode(category.project_id || category.item_project_id);
            if (!projectNode) {
              projectNode = {
                id: category.project_id || category.item_project_id,
                budget_id: fundingState.selectedBudgetId,
                name: 'Project',
                children: [],
              };
            }
            const categoryNode = getCategoryNode(category.id) || category;
            const exclude = new Set();
            collectDescendantIds(categoryNode, exclude);
            const options = buildMoveOptions(projectNode, exclude);
            openFormModal({
              title: `Move ${category.name}`,
              submitLabel: 'Move',
              fields: [
                {
                  name: 'target',
                  label: 'Move to',
                  type: 'select',
                  required: true,
                  options: options.length ? options : [{ value: '', label: 'No available targets' }],
                  value: options.length ? options[0].value : '',
                },
              ],
              onSubmit: async (values, helpers) => {
                try {
                  if (!values.target) {
                    helpers.setError('Select a target for the move.');
                    return;
                  }
                  const [kind, rawId] = values.target.split(':');
                  const targetId = kind === 'category' ? Number(rawId) : null;
                  const query = targetId ? `?new_parent_id=${targetId}` : '';
                  const check = await api(`/api/categories/${category.id}/can-move${query}`);
                  if (!check.can_move) {
                    const reason = check.reason ? check.reason.replace(/_/g, ' ') : 'blocked';
                    const extra = check.count ? ` (count: ${check.count})` : '';
                    helpers.setError(`Cannot move: ${reason}${extra}`);
                    return;
                  }
                  await api(`/api/categories/${category.id}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ parent_id: targetId }),
                  });
                  helpers.close();
                  showBanner('Category moved', 'success');
                  hideBanner(1500);
                  await refreshCurrentBudget();
                } catch (err) {
                  helpers.setError(err?.message || String(err));
                }
              },
            });
          }

          function attachEnterCommit(input) {
            input.addEventListener('keydown', (evt) => {
              if (evt.key === 'Enter' && !evt.shiftKey) {
                evt.preventDefault();
                input.blur();
              }
            });
          }

          function renderBudgetCard(budget, rootNode) {
            const card = document.createElement('div');
            card.className = 'ledger-budget-card';

            const line1 = document.createElement('div');
            line1.className = 'ledger-line';

            const badge = document.createElement('span');
            badge.className = 'label';
            badge.textContent = 'Budget';
            line1.appendChild(badge);

            const nameInput = document.createElement('textarea');
            nameInput.rows = 1;
            nameInput.value = budget.name || '';
            nameInput.placeholder = 'Budget name';
            attachEnterCommit(nameInput);
            setupAutoGrow(nameInput, { maxPercent: 0.6, minWidth: 260, minHeight: 32 });
            nameInput.addEventListener('change', async () => {
              const next = nameInput.value.trim();
              if (!next || next === budget.name) {
                nameInput.value = budget.name || '';
                triggerAutoGrow(nameInput);
                return;
              }
              await saveBudgetPatch(budget.id, { name: next });
              triggerAutoGrow(nameInput);
            });
            line1.appendChild(makeInlineField('Name', nameInput));
            requestAnimationFrame(() => triggerAutoGrow(nameInput));

            const ownerInput = document.createElement('textarea');
            ownerInput.rows = 1;
            ownerInput.value = budget.owner || '';
            ownerInput.placeholder = 'Owner';
            attachEnterCommit(ownerInput);
            setupAutoGrow(ownerInput, { maxPercent: 0.6, minWidth: 220, minHeight: 32 });
            ownerInput.disabled = !!budget.is_cost_center;
            ownerInput.addEventListener('change', async () => {
              const next = ownerInput.value.trim();
              const normalized = next === '' ? null : next;
              if ((budget.owner || null) === normalized) {
                triggerAutoGrow(ownerInput);
                return;
              }
              await saveBudgetPatch(budget.id, { owner: normalized });
              triggerAutoGrow(ownerInput);
            });
            line1.appendChild(makeInlineField('Owner', ownerInput));
            requestAnimationFrame(() => triggerAutoGrow(ownerInput));

            const costCenterInput = document.createElement('input');
            costCenterInput.type = 'checkbox';
            costCenterInput.checked = !!budget.is_cost_center;
            costCenterInput.addEventListener('change', async () => {
              const next = !!costCenterInput.checked;
              if (next === !!budget.is_cost_center) return;
              ownerInput.disabled = next;
              triggerAutoGrow(ownerInput);
              closureInput.disabled = next;
              await saveBudgetPatch(budget.id, { is_cost_center: next });
            });
            const costInline = makeInlineField('Cost Center', costCenterInput);
            costInline.classList.add('inline-checkbox');
            line1.appendChild(costInline);

            const closureInput = document.createElement('input');
            closureInput.type = 'date';
            const closureValue = budget.closure_date ? String(budget.closure_date).slice(0, 10) : '';
            closureInput.value = closureValue;
            closureInput.disabled = !!budget.is_cost_center;
            closureInput.addEventListener('change', async () => {
              const next = closureInput.value || null;
              const current = budget.closure_date ? String(budget.closure_date).slice(0, 10) : null;
              if (current === (next || null)) return;
              await saveBudgetPatch(budget.id, { closure_date: next });
            });
            line1.appendChild(makeInlineField('Closure', closureInput));

            const totalValue = document.createElement('strong');
            totalValue.className = 'value';
            totalValue.textContent = fmtCurrency(budget.budget_amount_cache);
            line1.appendChild(makeInlineField('Budget', totalValue, 'value'));

            card.appendChild(line1);

            const tagLine = document.createElement('div');
            tagLine.className = 'ledger-line ledger-tag-line';
            attachTagRow(tagLine, rootNode, { showLabel: true });
            card.appendChild(tagLine);

            const descLine = document.createElement('div');
            descLine.className = 'ledger-line';
            descLine.dataset.autoGrowHost = '1';
            const descLabel = document.createElement('span');
            descLabel.className = 'label';
            descLabel.textContent = 'Description';
            descLine.appendChild(descLabel);

            const descInput = document.createElement('textarea');
            descInput.rows = 2;
            descInput.placeholder = 'Describe this budget…';
            descInput.value = budget.description || '';
            setupAutoGrow(descInput, { maxPercent: 0.98, minWidth: 320, minHeight: 60 });
            descInput.addEventListener('change', async () => {
              const next = descInput.value.trim();
              const normalized = next === '' ? null : next;
              if ((budget.description || null) === normalized) {
                triggerAutoGrow(descInput);
                return;
              }
              await saveBudgetPatch(budget.id, { description: normalized });
              triggerAutoGrow(descInput);
            });
            descLine.appendChild(descInput);
            card.appendChild(descLine);
            requestAnimationFrame(() => triggerAutoGrow(descInput));

            const actionsRow = document.createElement('div');
            actionsRow.className = 'ledger-controls';
            const newItemBtn = document.createElement('button');
            newItemBtn.type = 'button';
            newItemBtn.className = 'btn-primary';
            newItemBtn.textContent = '+ New Item/Project';
            newItemBtn.addEventListener('click', () => openItemProjectModal(budget));
            actionsRow.appendChild(newItemBtn);
            card.appendChild(actionsRow);

            return card;
          }

          function renderLedger() {
            ledgerEl.innerHTML = '';
            const hierarchy = fundingState.currentHierarchy;
            if (!hierarchy) {
              ledgerEl.innerHTML = '<div class="funding-empty">Select a funding source to inspect.</div>';
              return;
            }
            const budget = fundingState.budgetMap.get(fundingState.selectedBudgetId);
            const header = renderBudgetCard(budget, hierarchy);
            ledgerEl.appendChild(header);

            const body = document.createElement('div');
            body.className = 'ledger-body';
            (hierarchy.children || []).forEach(project => {
              body.appendChild(renderProject(project));
            });
            ledgerEl.appendChild(body);
          }

          function openItemProjectModal(budget) {
            openFormModal({
              title: `New Item/Project for ${budget.name}`,
              submitLabel: 'Create Item/Project',
              fields: [
                { name: 'name', label: 'Name', required: true, value: '' },
                { name: 'assets', label: 'Assets (optional)', type: 'textarea', rows: 3, hint: 'Separate multiple assets with commas or new lines.' },
              ],
              onSubmit: async (values, helpers) => {
                try {
                  const payload = {
                    budget_id: budget.id,
                    name: values.name,
                    description: null,
                  };
                  const created = await apiCreate('/api/item-projects', payload);
                  const parts = (values.assets || '')
                    .split(/\r?\n|,/)
                    .map(part => part.trim())
                    .filter(Boolean);
                  for (const piece of parts) {
                    const asset = await ensureLineAsset(piece);
                    await attachAssetToProject(created.id, asset.id);
                  }
                  helpers.close();
                  showBanner('Item/Project created', 'success');
                  hideBanner(1500);
                  await refreshCurrentBudget();
                } catch (err) {
                  helpers.setError(err?.message || String(err));
                }
              },
            });
          }

          function openAssetModal(project) {
            openFormModal({
              title: `Add assets to ${project.name}`,
              submitLabel: 'Attach Assets',
              fields: [
                { name: 'assets', label: 'Asset names', type: 'textarea', rows: 3, required: true, hint: 'Separate multiple assets with commas or new lines.' },
              ],
              onSubmit: async (values, helpers) => {
                try {
                  const parts = (values.assets || '')
                    .split(/\r?\n|,/)
                    .map(part => part.trim())
                    .filter(Boolean);
                  if (!parts.length) {
                    helpers.setError('Provide at least one asset name.');
                    return;
                  }
                  for (const piece of parts) {
                    const asset = await ensureLineAsset(piece);
                    await attachAssetToProject(project.id, asset.id);
                  }
                  helpers.close();
                  await refreshCurrentBudget();
                } catch (err) {
                  helpers.setError(err?.message || String(err));
                }
              },
            });
          }

          function renderProject(project) {
            const projectNode = getProjectNode(project.id) || project;
            const key = makeKey(project);
            const hasChildren = (projectNode.children && projectNode.children.length) || (project.children && project.children.length);
            const expanded = hasChildren ? fundingState.expanded.has(key) : true;

            const wrapper = document.createElement('div');
            wrapper.className = 'ledger-project';

            const header = document.createElement('div');
            header.className = 'ledger-section-header';

            const line = document.createElement('div');
            line.className = 'ledger-header-line';

            const nameInput = document.createElement('textarea');
            nameInput.rows = 1;
            nameInput.value = project.name || '';
            nameInput.placeholder = 'Project name';
            attachEnterCommit(nameInput);
            setupAutoGrow(nameInput, { maxPercent: 0.75, minWidth: 320, minHeight: 32 });
            nameInput.addEventListener('change', async () => {
              const next = nameInput.value.trim();
              if (!next || next === project.name) {
                nameInput.value = project.name || '';
                triggerAutoGrow(nameInput);
                return;
              }
              await saveProjectPatch(project.id, { name: next });
              triggerAutoGrow(nameInput);
            });
            line.appendChild(makeInlineField('Item/Project', nameInput));
            requestAnimationFrame(() => triggerAutoGrow(nameInput));

            const tagInline = document.createElement('div');
            tagInline.className = 'ledger-inline ledger-inline-tags';
            attachTagRow(tagInline, project, { showLabel: false });
            line.appendChild(tagInline);

            const subtotal = document.createElement('span');
            subtotal.className = 'amount';
            subtotal.textContent = `Subtotal: ${fmtCurrency(project.rollup_amount || 0)}`;
            line.appendChild(subtotal);

            const headerActions = document.createElement('div');
            headerActions.className = 'ledger-actions';

            const toggleBtn = document.createElement('button');
            toggleBtn.type = 'button';
            toggleBtn.className = 'icon-btn';
            toggleBtn.textContent = expanded ? '▾' : '▸';
            toggleBtn.disabled = !hasChildren;
            toggleBtn.addEventListener('click', (evt) => {
              evt.stopPropagation();
              if (!hasChildren) return;
              if (expanded) {
                fundingState.expanded.delete(key);
              } else {
                fundingState.expanded.add(key);
              }
              persistExpansionState(fundingState.selectedBudgetId);
              renderLedger();
            });
            headerActions.appendChild(toggleBtn);

            const groupBtn = document.createElement('button');
            groupBtn.type = 'button';
            groupBtn.textContent = '+ Group';
            groupBtn.addEventListener('click', (evt) => {
              evt.stopPropagation();
              openCategoryModal({ projectNode, parentCategory: null, isLeaf: false });
            });
            headerActions.appendChild(groupBtn);

            const leafBtn = document.createElement('button');
            leafBtn.type = 'button';
            leafBtn.textContent = '+ Leaf';
            leafBtn.addEventListener('click', (evt) => {
              evt.stopPropagation();
              openCategoryModal({ projectNode, parentCategory: null, isLeaf: true });
            });
            headerActions.appendChild(leafBtn);

            const inspectBtn = document.createElement('button');
            inspectBtn.type = 'button';
            inspectBtn.className = 'icon-btn';
            inspectBtn.textContent = 'ℹ';
            inspectBtn.addEventListener('click', (evt) => {
              evt.stopPropagation();
              openInspectorFor(project);
            });
            headerActions.appendChild(inspectBtn);

            line.appendChild(headerActions);
            header.appendChild(line);

            const assetsLine = document.createElement('div');
            assetsLine.className = 'ledger-tag-line';
            const assetsLabel = document.createElement('span');
            assetsLabel.className = 'tag-line-label';
            assetsLabel.textContent = 'Assets:';
            assetsLine.appendChild(assetsLabel);

            const assetList = document.createElement('div');
            assetList.className = 'asset-chip-row';
            const assetItems = (project.assets && project.assets.items) ? project.assets.items : [];
            if (assetItems.length) {
              assetItems.forEach(asset => {
                const chip = document.createElement('span');
                chip.className = 'asset-chip';
                chip.textContent = asset.name;
                const removeBtn = document.createElement('button');
                removeBtn.type = 'button';
                removeBtn.className = 'asset-chip-remove';
                removeBtn.textContent = '×';
                removeBtn.title = 'Remove asset';
                removeBtn.addEventListener('click', async (evt) => {
                  evt.stopPropagation();
                  try {
                    await detachAssetFromProject(project.id, asset.id);
                    await refreshCurrentBudget();
                  } catch (err) {
                    showError(err);
                  }
                });
                chip.appendChild(removeBtn);
                assetList.appendChild(chip);
              });
            } else {
              const empty = document.createElement('span');
              empty.className = 'asset-empty';
              empty.textContent = 'None';
              assetList.appendChild(empty);
            }
            assetsLine.appendChild(assetList);

            const addAssetBtn = document.createElement('button');
            addAssetBtn.type = 'button';
            addAssetBtn.className = 'asset-add-btn';
            addAssetBtn.textContent = '+ Asset';
            addAssetBtn.addEventListener('click', (evt) => {
              evt.stopPropagation();
              openAssetModal(projectNode);
            });
            assetsLine.appendChild(addAssetBtn);
            header.appendChild(assetsLine);

            wrapper.appendChild(header);

            const rows = document.createElement('div');
            rows.className = 'ledger-rows';
            if (!expanded) rows.style.display = 'none';
            const categoryChildren = [...(projectNode.children || project.children || [])];
            categoryChildren.sort((a, b) => {
              const an = (a.path_names && a.path_names.length) ? a.path_names.join(' ') : (a.name || '');
              const bn = (b.path_names && b.path_names.length) ? b.path_names.join(' ') : (b.name || '');
              return an.localeCompare(bn);
            });
            categoryChildren.forEach((child, idx) => {
              const isLast = idx === categoryChildren.length - 1;
              rows.appendChild(renderCategory(child, [], !isLast));
            });
            wrapper.appendChild(rows);

            return wrapper;
          }

          function renderCategory(category, ancestorLines = [], hasSiblingAfter = false) {
            const key = makeKey(category);
            const hasChildren = category.children && category.children.length;
            const expanded = hasChildren ? fundingState.expanded.has(key) : true;

            const fragment = document.createDocumentFragment();

            const depth = ancestorLines.length;

            const row = document.createElement('div');
            row.className = `ledger-row category${category.is_leaf ? ' leaf' : ''}`;
            row.style.setProperty('--depth', depth);
            row.dataset.depth = depth;

            const treeCol = document.createElement('div');
            treeCol.className = 'ledger-tree';
            if (depth === 0) treeCol.classList.add('tree-root');

            if (ancestorLines.length) {
              const stems = document.createElement('div');
              stems.className = 'tree-stems';
              ancestorLines.forEach(hasSibling => {
                const stem = document.createElement('span');
                stem.className = 'tree-stem';
                if (hasSibling) stem.dataset.active = '1';
                stems.appendChild(stem);
              });
              treeCol.appendChild(stems);
            }

            const elbow = document.createElement('div');
            elbow.className = 'tree-elbow';
            if (depth === 0) elbow.classList.add('tree-elbow-root');
            if (hasSiblingAfter || hasChildren) elbow.dataset.extend = '1';

            const collapseBtn = document.createElement('button');
            collapseBtn.className = 'collapse';
            collapseBtn.type = 'button';
            collapseBtn.textContent = hasChildren ? (expanded ? '▾' : '▸') : '';
            collapseBtn.disabled = !hasChildren;
            elbow.appendChild(collapseBtn);
            treeCol.appendChild(elbow);

            const nameCol = document.createElement('div');
            nameCol.className = 'ledger-col name';
            const treeLabel = document.createElement('div');
            treeLabel.className = `tree-label${category.is_leaf ? ' leaf' : ''}`;
            treeLabel.dataset.autoGrowHost = '1';

            const nameInput = document.createElement('textarea');
            nameInput.rows = 1;
            nameInput.value = category.name || '';
            nameInput.placeholder = 'Category name';
            attachEnterCommit(nameInput);
            setupAutoGrow(nameInput, { maxPercent: 0.75, minWidth: 320, minHeight: 32 });
            nameInput.addEventListener('change', async () => {
              const next = nameInput.value.trim();
              if (!next || next === category.name) {
                nameInput.value = category.name || '';
                triggerAutoGrow(nameInput);
                return;
              }
              await saveCategoryPatch(category.id, { name: next });
              triggerAutoGrow(nameInput);
            });
            treeLabel.appendChild(nameInput);
            nameCol.appendChild(treeLabel);
            requestAnimationFrame(() => triggerAutoGrow(nameInput));

            const tagCol = document.createElement('div');
            tagCol.className = 'ledger-col tags';
            attachTagRow(tagCol, category, { showLabel: false });

            const subtotalCol = document.createElement('div');
            subtotalCol.className = 'ledger-col subtotal';
            if (category.is_leaf) {
              const amountInput = document.createElement('textarea');
              amountInput.rows = 1;
              const hasValue = category.amount_leaf !== null && category.amount_leaf !== undefined;
              amountInput.value = hasValue ? Number(category.amount_leaf).toFixed(2) : '';
              attachEnterCommit(amountInput);
              amountInput.inputMode = 'decimal';
              amountInput.spellcheck = false;
              setupAutoGrow(amountInput, { maxPercent: 0.5, minWidth: 140, minHeight: 26, maxWidth: 220 });
              amountInput.addEventListener('change', async () => {
                const raw = amountInput.value.trim();
                let next = null;
                if (raw !== '') {
                  const parsed = Number(raw);
                  if (Number.isNaN(parsed)) {
                    amountInput.value = hasValue ? Number(category.amount_leaf).toFixed(2) : '';
                    showBanner('Amount must be numeric', 'warn');
                    hideBanner(1600);
                    return;
                  }
                  next = Math.round(parsed * 100) / 100;
                }
                await saveCategoryPatch(category.id, { amount_leaf: next });
                triggerAutoGrow(amountInput);
              });
              subtotalCol.appendChild(amountInput);
              requestAnimationFrame(() => triggerAutoGrow(amountInput));
            } else {
              subtotalCol.textContent = `Subtotal: ${fmtCurrency(category.rollup_amount)}`;
            }

            const actionsCol = document.createElement('div');
            actionsCol.className = 'ledger-actions';

            const groupBtn = document.createElement('button');
            groupBtn.type = 'button';
            groupBtn.textContent = '+ Group';
            groupBtn.disabled = category.is_leaf;
            groupBtn.addEventListener('click', (evt) => {
              evt.stopPropagation();
              const projectNode = getProjectNode(category.project_id || category.item_project_id) || {
                id: category.project_id || category.item_project_id,
                budget_id: fundingState.selectedBudgetId,
                name: 'Project',
              };
              const parentNode = getCategoryNode(category.id) || category;
              openCategoryModal({ projectNode, parentCategory: parentNode, isLeaf: false });
            });
            actionsCol.appendChild(groupBtn);

            const addLeafBtn = document.createElement('button');
            addLeafBtn.type = 'button';
            addLeafBtn.textContent = '+ Leaf';
            addLeafBtn.disabled = category.is_leaf;
            addLeafBtn.addEventListener('click', (evt) => {
              evt.stopPropagation();
              const projectNode = getProjectNode(category.project_id || category.item_project_id) || {
                id: category.project_id || category.item_project_id,
                budget_id: fundingState.selectedBudgetId,
                name: 'Project',
              };
              const parentNode = getCategoryNode(category.id) || category;
              openCategoryModal({ projectNode, parentCategory: parentNode, isLeaf: true });
            });
            actionsCol.appendChild(addLeafBtn);

            const moveBtn = document.createElement('button');
            moveBtn.type = 'button';
            moveBtn.textContent = 'Move';
            moveBtn.addEventListener('click', (evt) => {
              evt.stopPropagation();
              openMoveCategoryModal(getCategoryNode(category.id) || category);
            });
            actionsCol.appendChild(moveBtn);

            const inspectBtn = document.createElement('button');
            inspectBtn.type = 'button';
            inspectBtn.className = 'icon-btn';
            inspectBtn.textContent = 'ℹ';
            inspectBtn.addEventListener('click', (evt) => {
              evt.stopPropagation();
              openInspectorFor(category);
            });
            actionsCol.appendChild(inspectBtn);

            row.append(treeCol, nameCol, tagCol, subtotalCol, actionsCol);
            fragment.appendChild(row);

            collapseBtn.addEventListener('click', () => {
              if (!hasChildren) return;
              if (expanded) {
                fundingState.expanded.delete(key);
              } else {
                fundingState.expanded.add(key);
              }
              persistExpansionState(fundingState.selectedBudgetId);
              renderLedger();
            });

            if (hasChildren) {
              const childrenContainer = document.createElement('div');
              childrenContainer.className = 'ledger-children';
              if (!expanded) childrenContainer.style.display = 'none';
              const childNodes = [...(category.children || [])];
              childNodes.sort((a, b) => {
                const an = (a.path_names && a.path_names.length) ? a.path_names.join(' ') : (a.name || '');
                const bn = (b.path_names && b.path_names.length) ? b.path_names.join(' ') : (b.name || '');
                return an.localeCompare(bn);
              });
              childNodes.forEach((child, idx) => {
                const isLast = idx === childNodes.length - 1;
                childrenContainer.appendChild(renderCategory(child, [...ancestorLines, hasSiblingAfter], !isLast));
              });
              fragment.appendChild(childrenContainer);
            }

            return fragment;
          }

          function closeInspector() {
            fundingState.inspector = { open: false, entity: null };
            inspectorEl.classList.add('hidden');
            inspectorEl.innerHTML = '';
            if (shellEl) shellEl.classList.remove('has-inspector');
          }

          async function refreshCurrentBudget() {
            closeInspector();
            fundingState.lineAssetCache.clear();
            await loadBudgets(fundingState.searchTerm);
            renderBudgetList();
            await loadBudgetTree(fundingState.selectedBudgetId);
          }

          fundingState.refreshCurrentBudget = refreshCurrentBudget;

          let searchTimer = null;
          searchInput.addEventListener('input', () => {
            const term = searchInput.value.trim();
            if (searchTimer) clearTimeout(searchTimer);
            searchTimer = setTimeout(async () => {
              await loadBudgets(term);
              renderBudgetList();
              if (!fundingState.budgetMap.has(fundingState.selectedBudgetId)) {
                fundingState.selectedBudgetId = null;
                ledgerEl.innerHTML = '<div class="funding-empty">Select a funding source to inspect.</div>';
              }
            }, 220);
          });

          if (newBudgetBtn) newBudgetBtn.onclick = () => openBudgetModal();

          if (tagManagerBtn) tagManagerBtn.onclick = () => {
            const navBtn = document.querySelector('nav button[data-tab="tags"]');
            if (navBtn) {
              navBtn.click();
            }
          };

          if (rebuildBtn) rebuildBtn.onclick = () => enqueueScopedRebuild(null, 'UI');

          function openBudgetModal() {
            openFormModal({
              title: 'New Budget',
              submitLabel: 'Create Budget',
              fields: [
                { name: 'name', label: 'Name', required: true, value: '' },
                { name: 'owner', label: 'Owner', value: '' },
                { name: 'is_cost_center', label: 'Cost Center?', type: 'checkbox', value: false },
                { name: 'closure_date', label: 'Closure Date', type: 'date', value: '' },
                { name: 'description', label: 'Description', type: 'textarea', rows: 3, value: '' },
              ],
              onSubmit: async (values, helpers) => {
                try {
                  const payload = {
                    name: values.name,
                    owner: values.owner || null,
                    is_cost_center: !!values.is_cost_center,
                    closure_date: values.closure_date || null,
                    description: values.description || null,
                  };
                  const created = await apiCreate('/api/budgets', payload);
                  helpers.close();
                  showBanner('Budget created', 'success');
                  fundingState.searchTerm = '';
                  if (searchInput) searchInput.value = '';
                  await loadBudgets('');
                  renderBudgetList();
                  await selectBudget(created.id);
                } catch (err) {
                  helpers.setError(err?.message || String(err));
                }
              },
            });
          }

          async function selectBudget(budgetId) {
            if (fundingState.selectedBudgetId === budgetId) return;
            fundingState.selectedBudgetId = budgetId;
            renderBudgetList();
            await loadBudgetTree(budgetId);
          }

          try {
            await loadBudgets('');
            renderBudgetList();
            if (fundingState.budgets.length) {
              await selectBudget(fundingState.budgets[0].id);
            }
          } catch (err) {
            showError(err);
          }

          function openInspectorFor(node) {
            fundingState.currentHierarchy && closeInspector();
            openInspectorDrawer(node);
          }

          function openInspectorDrawer(node) {
            fundingState.inspector = { open: true, entity: node };
            inspectorEl.classList.remove('hidden');
            if (shellEl) shellEl.classList.add('has-inspector');
            inspectorEl.innerHTML = '';
            const panel = document.createElement('div');
            panel.className = 'drawer-panel inspector-panel';
            const scopeName = TAG_SCOPE_TYPES[toScopeType(node.type)] || node.type;
            panel.innerHTML = `
              <div class="drawer-header">
                <div>
                  <h3>${escapeHtml(scopeName)}</h3>
                  <div class="inspector-sub">${escapeHtml(node.name || '')}</div>
                </div>
                <button type="button" class="close-inspector">×</button>
              </div>
              <div class="inspector-section">
                <div class="inspector-meta"><strong>ID:</strong> ${node.id}</div>
                ${node.path_names ? `<div class="inspector-meta"><strong>Path:</strong> ${node.path_names.join(' / ')}</div>` : ''}
                <div class="inspector-meta"><strong>Amount:</strong> ${fmtCurrency(node.amount_leaf || node.rollup_amount)}</div>
              </div>
              <div class="inspector-section inspector-tags-block">
                <div class="inspector-tags" data-kind="direct"></div>
                <div class="inspector-tags" data-kind="inherited"></div>
                <div class="inspector-tags" data-kind="effective"></div>
              </div>
              <div class="inspector-actions">
                <button type="button" class="rebuild-scope">Rebuild tags for this scope</button>
              </div>`;
            inspectorEl.appendChild(panel);
            panel.querySelector('.close-inspector').onclick = closeInspector;
            panel.querySelector('.rebuild-scope').onclick = () => enqueueScopedRebuild({ entity_type: toScopeType(node.type), entity_id: node.id }, 'Inspector');
            const bundles = node.tags || { direct: [], inherited: [], effective: [] };
            const directBox = panel.querySelector('[data-kind="direct"]');
            const inheritedBox = panel.querySelector('[data-kind="inherited"]');
            const effectiveBox = panel.querySelector('[data-kind="effective"]');
            directBox.innerHTML = '<div class="inspector-title">Direct</div>';
            (bundles.direct || []).forEach(tag => {
              const chip = createTagChip(tag, {
                inherited: false,
                onEdit: (t, anchor) => openTagEditor(anchor, t, {
                  onSaved: refreshCurrentBudget,
                }),
                onRemove: async (tagToRemove) => {
                  await api('/api/tags/assign', {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ tag_id: tagToRemove.id, entity_type: toScopeType(node.type), entity_id: node.id, actor: 'UI' }),
                  });
                  await refreshCurrentBudget();
                  enqueueScopedRebuild({ entity_type: toScopeType(node.type), entity_id: node.id }, 'Inspector');
                },
              });
              directBox.appendChild(chip);
            });
            inheritedBox.innerHTML = '<div class="inspector-title">Inherited</div>';
            (bundles.inherited || []).forEach(tag => {
              const chip = createTagChip(tag, {
                inherited: true,
                onEdit: (t, anchor) => openTagEditor(anchor, t, {
                  onSaved: refreshCurrentBudget,
                }),
              });
              inheritedBox.appendChild(chip);
            });
            effectiveBox.innerHTML = '<div class="inspector-title">Effective</div>';
            (bundles.effective || []).forEach(tag => {
              const chip = createTagChip(tag, {
                inherited: true,
                onEdit: (t, anchor) => openTagEditor(anchor, t, {
                  onSaved: refreshCurrentBudget,
                }),
              });
              effectiveBox.appendChild(chip);
            });
          }
        }
  
        async function renderVendors(){
          const vendors = await apiList('/api/vendors');
          content.innerHTML =
            card('Add Vendor', `
              <div class="row">
                ${field('name', labelFor('name','Vendor name','e.g., "Acme Co."'), input('name','Acme Co.'))}
                <div class="field"><label>&nbsp;</label><button id="add">Add</button></div>
              </div>`)
            + card('All Vendors', table(vendors, [
              { key: 'id', label: 'ID' },
              { key: 'name', label: 'Vendor Name' },
            ], '/api/vendors'));

          initializeDropdowns(content);
          const add = document.getElementById('add');
          if (add) add.onclick = async ()=>{
            const name = content.querySelector('input[name=name]').value;
            if(!name) return alert('Name required');
            await apiCreate('/api/vendors', {name});
            renderVendors();
          };
        }
  
        // ---- Kind help ----
        const KIND_HELP = {
          budget: { title:'Budget', text:`Sets the planned target (limit) for a category/project/funding source.`, required:['amount','portfolio_id'] },
          quote: { title:'Quote', text:`Vendor quotation (not a PO). Use to compare pricing; does not affect actuals.`, required:['amount','portfolio_id','vendor_id','quote_ref'] },
          po: { title:'PO', text:`Issued/committed spend with a PO number. Counts toward actuals.`, required:['amount','portfolio_id','po_number'] },
          unplanned: { title:'Unplanned', text:`Actual spend not originally budgeted. Counts toward actuals.`, required:['amount','portfolio_id'] },
          adjustment: { title:'Adjustment', text:`Manual correction (+/-). Affects actuals. Use negative for credits.`, required:['amount','portfolio_id'] },
        };
        const helpBox = (k='budget')=>{
          const o = KIND_HELP[k];
          return `<div class="help-box" id="kindHelp">
            <h4>${o.title} — what it means</h4>
            <p>${o.text}</p>
            <p><span class="badge req">Required:</span> ${o.required.map(x=>`<code>${x}</code>`).join(' ')}</p>
          </div>`;
        };
  
        // ---- Entries ----
        async function renderEntries(){
          const [portfolios, projects, categories, vendors, entries, fundingSources] = await Promise.all([
            apiList('/api/portfolios'),
            apiList('/api/projects'),
            apiList('/api/categories'),
            apiList('/api/vendors'),
            apiList('/api/entries'),
            apiList('/api/funding-sources'),
          ]);
          const portfolioMap = mapBy(portfolios);
          const portfolioOpts = portfolios.map(p => ({ value: p.id, label: formatPortfolioLabel(p), raw: p }));
          const basePortfolioHandlers = buildResourceDropdownHandlers('/api/portfolios', {
            formatLabel: formatPortfolioLabel,
            matcherFields: ['fiscal_year', 'owner', 'type', 'car_code', 'cc_code'],
          });
          const portfolioHandlers = {
            key: 'portfolio',
            ...basePortfolioHandlers,
            create: async (label) => {
              const created = await basePortfolioHandlers.create(label);
              const option = { value: created.value, label: created.label, raw: created.raw };
              portfolioOpts.push(option);
              if (option.raw && option.raw.id !== undefined) {
                portfolioMap[option.raw.id] = option.raw;
              }
              return option;
            },
            edit: async (option, nextLabel) => {
              const updated = await basePortfolioHandlers.edit(option, nextLabel);
              if (updated.raw && updated.raw.id !== undefined) {
                portfolioMap[updated.raw.id] = updated.raw;
              }
              updated.label = formatPortfolioLabel(updated.raw);
              return updated;
            },
            remove: async (option) => {
              await basePortfolioHandlers.remove(option);
              if (option.raw && option.raw.id !== undefined) delete portfolioMap[option.raw.id];
            },
          };

          const projectOpts = projects.map(p => ({ value: p.id, label: formatProjectLabel(p, portfolioMap), raw: p }));
          const baseProjectHandlers = buildResourceDropdownHandlers('/api/projects', {
            formatLabel: (proj) => formatProjectLabel(proj, portfolioMap),
            matcherText: (proj) => `${proj.name} ${proj.code || ''} ${proj.line || ''} ${formatPortfolioLabel(portfolioMap[proj.portfolio_id] || { name: proj.portfolio_id })}`,
            buildUpdateBody: (raw, label) => ({ ...stripId(raw), name: label, portfolio_id: raw.portfolio_id ?? null }),
          });
          const projectHandlers = {
            key: 'project',
            ...baseProjectHandlers,
            create: async (label) => {
              const portfolioSelect = content.querySelector('select[name=portfolio_id]');
              const portfolioValue = portfolioSelect ? Number(portfolioSelect.value) : NaN;
              if (!portfolioValue || Number.isNaN(portfolioValue)) {
                alert('Pick a funding source first so the project can be created under it.');
                return null;
              }
              const payload = { name: label, portfolio_id: portfolioValue };
              const created = await apiCreate('/api/projects', payload);
              projectOpts.push({ value: created.id, label: formatProjectLabel(created, portfolioMap), raw: created });
              return { value: created.id, label: formatProjectLabel(created, portfolioMap), raw: created };
            },
            edit: async (option, nextLabel) => {
              const updated = await baseProjectHandlers.edit(option, nextLabel);
              option.raw = updated.raw;
              updated.label = formatProjectLabel(updated.raw, portfolioMap);
              const target = projectOpts.find(opt => String(opt.value) === String(updated.value));
              if (target) {
                target.label = updated.label;
                target.raw = updated.raw;
              }
              return updated;
            },
          };

          const categoryMap = mapBy(categories);
          const categoryOpts = categories.map(c => ({ value: c.id, label: catPath(c, categoryMap), raw: c }));
          const baseCategoryHandlers = buildResourceDropdownHandlers('/api/categories', {
            formatLabel: (cat) => catPath(cat, { ...categoryMap, [cat.id]: cat }),
            matcherText: (cat) => catPath(cat, categoryMap),
            buildUpdateBody: (raw, label) => ({ ...stripId(raw), name: label }),
          });
          const categoryHandlers = {
            key: 'category',
            ...baseCategoryHandlers,
            create: async (label) => {
              const projectSelect = content.querySelector('select[name=project_id]');
              const projectValue = projectSelect ? Number(projectSelect.value) : NaN;
              const payload = { name: label, project_id: Number.isNaN(projectValue) ? null : projectValue || null };
              const created = await apiCreate('/api/categories', payload);
              categoryMap[created.id] = created;
              const option = { value: created.id, label: catPath(created, categoryMap), raw: created };
              categoryOpts.push(option);
              parentOptions.push({ value: created.id, label: option.label, raw: created });
              return option;
            },
            edit: async (option, nextLabel) => {
              const updated = await baseCategoryHandlers.edit(option, nextLabel);
              categoryMap[updated.raw.id] = updated.raw;
              updated.label = catPath(updated.raw, categoryMap);
              const catOption = categoryOpts.find(opt => String(opt.value) === String(updated.value));
              if (catOption) {
                catOption.label = updated.label;
                catOption.raw = updated.raw;
              }
              const parentOption = parentOptions.find(opt => opt.value === updated.raw.id);
              if (parentOption) parentOption.label = updated.label;
              return updated;
            },
          };

          const vendorOpts = vendors.map(v => ({ value: v.id, label: v.name, raw: v }));
          const baseVendorHandlers = buildResourceDropdownHandlers('/api/vendors', {
            formatLabel: (v) => v.name,
            matcherFields: ['name'],
          });
          const vendorHandlers = { key: 'vendor', ...baseVendorHandlers };
          const originalVendorCreate = vendorHandlers.create;
          vendorHandlers.create = async (label) => {
            const created = await originalVendorCreate(label);
            if (created && created.value !== undefined) {
              vendorOpts.push({ value: created.value, label: created.label, raw: created.raw });
            }
            return created;
          };
          const originalVendorEdit = vendorHandlers.edit;
          vendorHandlers.edit = async (option, nextLabel) => {
            const updated = await originalVendorEdit(option, nextLabel);
            const target = vendorOpts.find(opt => String(opt.value) === String(updated.value));
            if (target) {
              target.label = updated.label;
              target.raw = updated.raw;
            }
            return updated;
          };

          const kindOptions = [
            { value: 'budget', label: 'budget (sets target)' },
            { value: 'quote', label: 'quote (informational)' },
            { value: 'po', label: 'po (actual)' },
            { value: 'unplanned', label: 'unplanned (actual)' },
            { value: 'adjustment', label: 'adjustment (actual)' },
          ];

          content.innerHTML =
            card('Add Entry', `
              <div class="row two">
                <div>
                  <div class="section">
                    <div class="title">Basics <span class="hint">(date, kind, amount)</span></div>
                    <div class="row three">
                      ${field('date', labelFor('date','Date','Optional (YYYY-MM-DD).'), `<input class="input" type="date" name="date"/>`)}
                      ${field('kind', labelFor('kind','What are you adding?','Budget sets limits; PO/Unplanned/Adjustment count to actuals; Quote is informational.'), select('kind', kindOptions, { allowCreate: false, allowEdit: false, allowDelete: false, prefill: false }))}
                      ${field('amount', labelFor('amount','Amount','Positive number; negative for adjustment credits.'), input('amount','1000'))}
                    </div>
                  </div>

                  <div class="section">
                    <div class="title">Scope</div>
                    <div class="row three">
                      ${field('portfolio_id', labelFor('portfolio_id','Funding Source','Primary funding source charged.'), select('portfolio_id', portfolioOpts, { ...portfolioHandlers }))}
                      ${field('project_id', labelFor('project_id','Project','Per funding-source project.'), select('project_id', projectOpts, { ...projectHandlers }))}
                      ${field('category_id', labelFor('category_id','Category (n-level)','Pick the most specific leaf.'), select('category_id', categoryOpts, { ...categoryHandlers }))}
                    </div>
                  </div>

                  <div class="section">
                    <div class="title">Commercial</div>
                    <div class="row three">
                      ${field('vendor_id', labelFor('vendor_id','Vendor','Who provided the quote/PO.'), select('vendor_id', vendorOpts, { ...vendorHandlers }))}
                      ${field('quote_ref', labelFor('quote_ref','Quote Ref','For quotes.'), input('quote_ref','QT-0097'))}
                      ${field('po_number', labelFor('po_number','PO #','For POs.'), input('po_number','4500123456'))}
                    </div>
                  </div>

                  <div class="section">
                    <div class="title">Wrong Source? <span class="hint">(flag to fix later)</span></div>
                    <div class="row two">
                      <div class="field">
                        ${labelFor('mischarged','Mark as mischarged','Check to flag this entry as charged to the wrong funding source.')}
                        <input type="checkbox" name="mischarged"/>
                      </div>
                      ${field('intended_portfolio_id', labelFor('intended_portfolio_id','Intended Funding Source','Where it *should* be charged.'), select('intended_portfolio_id', [{ value: '', label: '(none)', raw: null }].concat(portfolioOpts), { ...portfolioHandlers }))}
                    </div>
                  </div>

                  <div class="section">
                    <div class="title">Notes & Tags</div>
                    <div class="row two">
                      ${field('description', labelFor('description','Description','Short note.'), `<input class="input" name="description" placeholder="Optional"/>`)}
                      ${field('tags', labelFor('tags','Tags','Comma-separated (e.g., "long-lead, priority").'), input('tags','long-lead, priority'))}
                    </div>
                  </div>

                  <div class="section">
                    <div class="title">Allocations <span class="hint">(optional)</span> <span class="info" data-tip="Split the amount across multiple funding sources. Sum must equal Amount.">i</span></div>
                    <div id="allocs"></div>
                    <button id="addAlloc">+ Allocation</button>
                  </div>

                  <div class="section">
                    <button id="addEntry">Add Entry</button>
                  </div>
                </div>

                <div>${helpBox('budget')}</div>
              </div>
            `)
            + card('All Entries', table(entries, [
              { key: 'id', label: 'ID' },
              { key: 'date', label: 'Date' },
              { key: 'kind', label: 'Kind' },
              { key: 'amount', label: 'Amount' },
              { key: 'portfolio_id', label: 'Funding Source' },
              { key: 'project_id', label: 'Project' },
              { key: 'category_id', label: 'Category' },
              { key: 'vendor_id', label: 'Vendor' },
              { key: 'po_number', label: 'PO #' },
              { key: 'quote_ref', label: 'Quote Ref' },
              { key: 'mischarged', label: 'Mischarged' },
              { key: 'intended_portfolio_id', label: 'Intended Funding Source' },
              { key: 'description', label: 'Description' },
            ], '/api/entries'));

          initializeDropdowns(content);
          setupTableEditing(content, '/api/entries', entries, {
            portfolio_id: {
              type: 'dropdown',
              options: portfolioOpts,
              handlers: portfolioHandlers,
              valueType: 'number',
            },
            project_id: {
              type: 'dropdown',
              options: projectOpts,
              handlers: projectHandlers,
              valueType: 'number',
              allowNull: true,
              nullOptionLabel: '(none)',
            },
            category_id: {
              type: 'dropdown',
              options: categoryOpts,
              handlers: categoryHandlers,
              valueType: 'number',
              allowNull: true,
              nullOptionLabel: '(none)',
            },
            vendor_id: {
              type: 'dropdown',
              options: vendorOpts,
              handlers: vendorHandlers,
              valueType: 'number',
              allowNull: true,
              nullOptionLabel: '(none)',
            },
            intended_portfolio_id: {
              type: 'dropdown',
              options: portfolioOpts,
              handlers: portfolioHandlers,
              valueType: 'number',
              allowNull: true,
              nullOptionLabel: '(none)',
            },
            mischarged: {
              render: (value) => {
                if (value === true || value === 'true' || value === 1 || value === '1') return 'Yes';
                if (value === false || value === 'false' || value === 0 || value === '0') return '';
                return value == null ? '' : String(value);
              },
            },
          });

          const misBox = content.querySelector('input[name=mischarged]');
          const intendedSel = content.querySelector('select[name=intended_portfolio_id]');
          if (misBox && intendedSel) {
            const sync = () => { intendedSel.parentElement.parentElement.style.display = misBox.checked ? '' : 'none'; };
            sync(); misBox.addEventListener('change', sync);
          }

          if (FEATURES.REALLOCATE) {
            const catOptionsForDrawer = categoryOpts.map(c => ({ id: c.value, label: c.label }));
            content.querySelectorAll('.btn-reallocate').forEach(btn => {
              btn.addEventListener('click', () => {
                const entryId = Number(btn.dataset.entryId);
                const entry = entries.find(e => e.id === entryId);
                if (!entry) return;
                if (!entry.transaction_id && !entry.id) {
                  alert('Entry missing transaction reference; cannot reallocate yet.');
                  return;
                }
                openReallocate(entry, fundingSources, catOptionsForDrawer);
              });
            });
          }

          const allocsDiv = document.getElementById('allocs');
          const addAlloc = document.getElementById('addAlloc');
          if (addAlloc) addAlloc.onclick = () => {
            allocsDiv.insertAdjacentHTML('beforeend', `
              <div class="row four" data-row="1" style="margin-bottom:6px">
                ${field('alloc_portfolio', labelFor('alloc_portfolio','Funding Source','Destination funding source.'), select('alloc_portfolio', portfolioOpts, { ...portfolioHandlers }))}
                ${field('alloc_amount', labelFor('alloc_amount','Amount','Portion to this funding source.'), input('alloc_amount',''))}
                <div class="field"><label>&nbsp;</label><button onclick="this.closest('[data-row]').remove()">Remove</button></div>
              </div>`);
            initializeDropdowns(allocsDiv);
          };

          const kindSel = content.querySelector('select[name=kind]');
          const markRequired = () => {
            const k = KIND_HELP[kindSel.value];
            const box = document.getElementById('kindHelp');
            if (box) box.outerHTML = helpBox(kindSel.value);
            content.querySelectorAll('.required').forEach(el => el.classList.remove('required'));
            ['amount','portfolio_id','vendor_id','quote_ref','po_number'].forEach(name => {
              const label = content.querySelector(`[for="${name}"]`);
              if (label) label.classList.remove('required');
            });
            k.required.forEach(name => {
              const label = content.querySelector(`[for="${name}"]`);
              if (label) label.classList.add('required');
            });
          };
          if (kindSel) kindSel.onchange = markRequired;
          markRequired();

          const addBtn = document.getElementById('addEntry');
          if (addBtn) addBtn.onclick = async () => {
            try {
              const getField = (name) => {
                const el = content.querySelector(`[name=${name}]`);
                if (!el) return null;
                if (el.type === 'checkbox') return !!el.checked;
                return el.value === '' ? null : el.value;
              };
              const allocations = [...allocsDiv.querySelectorAll('[data-row]')].map(div => ({
                portfolio_id: Number(div.querySelector('select[name=alloc_portfolio]').value),
                amount: Number(div.querySelector('input[name=alloc_amount]').value),
              }));

              const body = {
                date: getField('date'),
                kind: String(getField('kind') || 'budget'),
                amount: Number(getField('amount')),
                description: getField('description'),
                portfolio_id: getField('portfolio_id') ? Number(getField('portfolio_id')) : null,
                project_id: getField('project_id') ? Number(getField('project_id')) : null,
                category_id: getField('category_id') ? Number(getField('category_id')) : null,
                vendor_id: getField('vendor_id') ? Number(getField('vendor_id')) : null,
                po_number: getField('po_number'),
                quote_ref: getField('quote_ref'),
                mischarged: getField('mischarged') || false,
                intended_portfolio_id: getField('intended_portfolio_id') ? Number(getField('intended_portfolio_id')) : null,
                allocations: allocations.length ? allocations : null,
                tags: (getField('tags') || '').split(',').map(s => s.trim()).filter(Boolean) || null,
              };

              const req = KIND_HELP[body.kind].required;
              const missing = [];
              req.forEach(name => {
                const value = body[name];
                const ok = typeof value === 'number' ? !Number.isNaN(value) : !!value;
                if (!ok) {
                  missing.push(name);
                  const el = content.querySelector(`[name=${name}]`);
                  if (el) el.classList.add('invalid');
                }
              });

              if (missing.length) {
                alert(`Missing required fields for kind="${body.kind}": ${missing.join(', ')}`);
                return;
              }

              if (body.mischarged && !body.intended_portfolio_id) {
                alert('Please choose the intended funding source for a mischarged entry.');
                return;
              }

              if (body.allocations && body.allocations.length) {
                const sum = body.allocations.reduce((acc, item) => acc + (Number(item.amount) || 0), 0);
                if (Math.abs(sum - body.amount) > 1e-6) {
                  alert(`Allocations must sum to Amount (${body.amount}). Current total: ${sum}`);
                  return;
                }
              }

              await apiCreate('/api/entries', body);
              renderEntries();

            } catch (err) {
              showError(err);
            }
          };
        }
        async function renderPayments(){
          if (!FEATURES.PAYMENT_SCHEDULES) {
            content.innerHTML = card('Payments', '<p>Payment schedule management is disabled.</p>');
            return;
          }

          const [fundingSources, projects, vendors] = await Promise.all([
            apiList('/api/funding-sources'),
            apiList('/api/projects'),
            apiList('/api/vendors'),
          ]);

          const fundingSourceHandlers = { key: 'funding-source', ...buildResourceDropdownHandlers('/api/funding-sources', {
            formatLabel: (fs) => fs.name,
            matcherFields: ['name'],
          }) };
          const fsOptions = [{ value: '', label: '(any funding source)', raw: null }].concat(fundingSources.map(fs => ({ value: fs.id, label: fs.name, raw: fs })));
          const projectHandlers = { key: 'project', ...buildResourceDropdownHandlers('/api/projects', {
            formatLabel: (p) => p.name,
            matcherFields: ['code', 'line'],
            buildUpdateBody: (raw, label) => ({ ...stripId(raw), name: label }),
          }) };
          const projectOptions = [{ value: '', label: '(any project)', raw: null }].concat(projects.map(p => ({ value: p.id, label: p.name, raw: p })));
          const vendorHandlers = { key: 'vendor', ...buildResourceDropdownHandlers('/api/vendors', {
            formatLabel: (v) => v.name,
            matcherFields: ['name'],
          }) };
          const vendorOptions = [{ value: '', label: '(any vendor)', raw: null }].concat(vendors.map(v => ({ value: v.id, label: v.name, raw: v })));
          const paymentStatusOptions = [
            { value: '', label: '(any)' },
            { value: 'PLANNED', label: 'PLANNED' },
            { value: 'DUE', label: 'DUE' },
            { value: 'PAID', label: 'PAID' },
            { value: 'CANCELLED', label: 'CANCELLED' },
          ];

          content.innerHTML = `
            ${card('Payment Schedule Filters', `
              <div class="row four">
                ${field('payment_fs', labelFor('payment_fs', 'Funding Source'), select('payment_fs', fsOptions, { ...fundingSourceHandlers }))}
                ${field('payment_project', labelFor('payment_project', 'Project'), select('payment_project', projectOptions, { ...projectHandlers }))}
                ${field('payment_vendor', labelFor('payment_vendor', 'Vendor'), select('payment_vendor', vendorOptions, { ...vendorHandlers }))}
                ${field('payment_status', labelFor('payment_status', 'Status'), select('payment_status', paymentStatusOptions, { allowCreate: false, allowEdit: false, allowDelete: false }))}
              </div>
              <div class="row three">
                ${field('payment_due_from', labelFor('payment_due_from', 'Due From'), `<input type="date" name="payment_due_from" class="input" />`)}
                ${field('payment_due_to', labelFor('payment_due_to', 'Due To'), `<input type="date" name="payment_due_to" class="input" />`)}
                <div class="field"><label>&nbsp;</label><button id="applyPayments">Apply</button></div>
              </div>
            `)}
            ${card('Generate Default Schedule', `
              <div class="row three">
                ${field('generate_po', labelFor('generate_po','PO ID','Leave blank if generating from invoice.'), input('generate_po','PO id'))}
                ${field('generate_invoice', labelFor('generate_invoice','Invoice ID','Leave blank if generating from PO.'), input('generate_invoice','Invoice id'))}
                <div class="field"><label>&nbsp;</label><button id="generateDefault">Generate</button></div>
              </div>
            `)}
            <div id="paymentsTable" class="card"></div>
          `;

          initializeDropdowns(content);

          const filters = {
            fs: content.querySelector('select[name=payment_fs]'),
            project: content.querySelector('select[name=payment_project]'),
            vendor: content.querySelector('select[name=payment_vendor]'),
            status: content.querySelector('select[name=payment_status]'),
            from: content.querySelector('input[name=payment_due_from]'),
            to: content.querySelector('input[name=payment_due_to]'),
          };

          const tableContainer = document.getElementById('paymentsTable');

          async function loadSchedules(){
            try {
              const params = {};
              if (filters.fs.value) params.funding_source_id = filters.fs.value;
              if (filters.project.value) params.project_id = filters.project.value;
              if (filters.vendor.value) params.vendor_id = filters.vendor.value;
              if (filters.status.value) params.status = filters.status.value;
              if (filters.from.value) params.due_from = filters.from.value;
              if (filters.to.value) params.due_to = filters.to.value;

              const rows = await ApiNew.listPaymentSchedules(params);
              if (!rows.length) {
                tableContainer.innerHTML = '<p>No schedules found.</p>';
                return;
              }
              const html = `
                <table class="table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Doc</th>
                      <th>Rule</th>
                      <th>Due Date</th>
                      <th>Amount</th>
                      <th>Status</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${rows.map(r => {
                      const label = r.invoice_id ? `Invoice ${r.invoice_id}` : (r.purchase_order_id ? `PO ${r.purchase_order_id}` : 'Manual');
                      return `<tr data-id="${r.id}">
                        <td>${r.id}</td>
                        <td>${label}</td>
                        <td>${r.due_date_rule || '-'}</td>
                        <td>${r.due_date || '-'}</td>
                        <td>${fmtCurrency(r.amount)}</td>
                        <td>${r.status}</td>
                        <td><button class="btn-edit-payment">Edit</button></td>
                      </tr>`;
                    }).join('')}
                  </tbody>
                </table>`;
              tableContainer.innerHTML = html;
              tableContainer.querySelectorAll('.btn-edit-payment').forEach(btn => {
                btn.addEventListener('click', async () => {
                  const row = btn.closest('tr');
                  const id = row.getAttribute('data-id');
                  const due = prompt('Due date (YYYY-MM-DD)', row.children[3].textContent.trim());
                  const amountStr = prompt('Amount (USD)', row.children[4].textContent.replace(/[^0-9.\-]/g, ''));
                  const status = prompt('Status (PLANNED/DUE/PAID/CANCELLED)', row.children[5].textContent.trim());
                  if (!due && !amountStr && !status) return;
                  try {
                    await ApiNew.updatePaymentSchedule(id, {
                      due_date: due || undefined,
                      amount: amountStr ? Number(amountStr) : undefined,
                      status: status || undefined,
                    });
                    alert('Payment schedule updated.');
                    loadSchedules();
                  } catch (err) {
                    showError(err);
                  }
                });
              });
            } catch (err) {
              showError(err);
            }
          }

          document.getElementById('applyPayments').onclick = loadSchedules;
          document.getElementById('generateDefault').onclick = async () => {
            try {
              const po = content.querySelector('input[name=generate_po]').value.trim();
              const invoice = content.querySelector('input[name=generate_invoice]').value.trim();
              const body = {};
              if (po) body.po_id = Number(po);
              if (invoice) body.invoice_id = Number(invoice);
              if (!body.po_id && !body.invoice_id) {
                alert('Provide a PO or Invoice id.');
                return;
              }
              await ApiNew.generatePaymentSchedule(body);
              alert('Default schedule generated.');
              loadSchedules();
            } catch (err) {
              showError(err);
            }
          };

          loadSchedules();
        }

        async function renderDeliverables(){
          if (!FEATURES.DELIVERABLES) {
            content.innerHTML = card('Deliverables', '<p>Deliverables tracking is disabled.</p>');
            return;
          }

          const [purchaseOrders, checkpointTypes] = await Promise.all([
            apiList('/api/purchase-orders'),
            ApiNew.listCheckpointTypes(),
          ]);

          const poOptions = [{ value: '', label: '(select PO)', raw: null }].concat(purchaseOrders.map(po => ({ value: po.id, label: `${po.po_number} (${po.currency})`, raw: po })));
          const poHandlers = { key: 'purchase-order', ...buildResourceDropdownHandlers('/api/purchase-orders', {
            formatLabel: (po) => `${po.po_number} (${po.currency})`,
            matcherFields: ['po_number', 'currency'],
          }) };
          const lineHandlers = { allowCreate: false, allowEdit: false, allowDelete: false };
          const baseLineOptions = [{ value: '', label: '(select line)', raw: null }];

          content.innerHTML = `
            ${card('Deliverables & Milestones', `
              <div class="row three">
                ${field('deliverable_po', labelFor('deliverable_po','Purchase Order'), select('deliverable_po', poOptions, { ...poHandlers }))}
                ${field('deliverable_po_line', labelFor('deliverable_po_line','PO Line'), select('deliverable_po_line', baseLineOptions, lineHandlers))}
                <div class="field"><label>&nbsp;</label><button id="refreshDeliverables">Load Lots</button></div>
              </div>
              <div class="row two">
                <div class="field"><label>&nbsp;</label><button id="createLot">Create Lot</button></div>
                <div class="field"><label>&nbsp;</label><button id="applyDeliverableTemplate">Apply Template</button></div>
              </div>
            `)}
            <div id="deliverablesPanel" class="card"><em>Select a PO line to view lots and milestones.</em></div>
          `;

          initializeDropdowns(content);

          const poSelect = content.querySelector('select[name=deliverable_po]');
          const lineSelect = content.querySelector('select[name=deliverable_po_line]');
          const panel = document.getElementById('deliverablesPanel');

          function populateLines(poId){
            const po = purchaseOrders.find(p => p.id === Number(poId));
            const dropdown = lineSelect && lineSelect.__dropdown;
            const options = po
              ? [{ value: '', label: '(all lines)', raw: null }].concat(po.lines.map(line => ({
                  value: line.id,
                  label: `${line.description || 'Line'} — Qty ${line.quantity || 0}`,
                  raw: line,
                })))
              : baseLineOptions.slice();
            if (dropdown) {
              dropdown.options = options;
              dropdown.optionMap = new Map(options.map(opt => [String(opt.value), opt]));
              lineSelect.innerHTML = options.map(opt => `<option value="${escapeHtml(opt.value)}">${escapeHtml(opt.label)}</option>`).join('');
              dropdown.filterOptions('');
              const current = dropdown.optionMap.get(lineSelect.value);
              if (!current) {
                dropdown.selected = null;
                lineSelect.value = '';
                dropdown.inputEl.value = '';
              }
            } else {
              lineSelect.innerHTML = options.map(opt => `<option value="${escapeHtml(opt.value)}">${escapeHtml(opt.label)}</option>`).join('');
            }
          }

          poSelect.addEventListener('change', () => {
            populateLines(poSelect.value);
          });

          async function loadLots(){
            const poId = Number(poSelect.value);
            if (!poId) {
              panel.innerHTML = '<p>Please pick a purchase order.</p>';
              return;
            }
            const lineId = Number(lineSelect.value) || undefined;
            try {
              const params = lineId ? { po_line_id: lineId } : { po_id: poId };
              const lots = await ApiNew.listDeliverables(params);
              if (!lots.length) {
                panel.innerHTML = '<p>No fulfillment lots yet.</p>';
                return;
              }
              const html = lots.map(lot => {
                const milestoneRows = (lot.milestones || []).map(m => {
                  return `<tr data-mid="${m.id}">
                    <td>${m.id}</td>
                    <td>${m.checkpoint_type_id}</td>
                    <td>${m.planned_date || '-'}</td>
                    <td>${m.actual_date || '-'}</td>
                    <td>${m.status}</td>
                    <td><button class="btn-milestone" data-mid="${m.id}">Set Actual</button></td>
                  </tr>`;
                }).join('');
                return `
                  <div class="card">
                    <h4>Lot ${lot.id} — Qty ${lot.lot_qty}</h4>
                    <table class="table">
                      <thead><tr><th>ID</th><th>Checkpoint</th><th>Planned</th><th>Actual</th><th>Status</th><th>Action</th></tr></thead>
                      <tbody>${milestoneRows || '<tr><td colspan="6">No milestones</td></tr>'}</tbody>
                    </table>
                  </div>`;
              }).join('');
              panel.innerHTML = html;
              panel.querySelectorAll('.btn-milestone').forEach(btn => {
                btn.addEventListener('click', async () => {
                  const milestoneId = btn.dataset.mid;
                  const actual = prompt('Actual date (YYYY-MM-DD)', new Date().toISOString().slice(0,10));
                  if (!actual) return;
                  try {
                    await ApiNew.updateMilestone(milestoneId, { actual_date: actual });
                    loadLots();
                  } catch (err) {
                    showError(err);
                  }
                });
              });
            } catch (err) {
              showError(err);
            }
          }

          document.getElementById('refreshDeliverables').onclick = loadLots;

          document.getElementById('createLot').onclick = async () => {
            const lineId = Number(lineSelect.value);
            if (!lineId) {
              alert('Pick a PO line first.');
              return;
            }
            const qty = prompt('Lot quantity', '1');
            if (!qty) return;
            try {
              await ApiNew.createLot(lineId, { lot_qty: Number(qty) });
              alert('Lot created.');
              loadLots();
            } catch (err) {
              showError(err);
            }
          };

          document.getElementById('applyDeliverableTemplate').onclick = async () => {
            const poId = Number(poSelect.value);
            if (!poId) {
              alert('Pick a purchase order.');
              return;
            }
            const lineId = Number(lineSelect.value) || null;
            const lotQty = prompt('Lot quantities (comma separated)', '5,5');
            if (!lotQty) return;
            const checkpoints = prompt('Checkpoint type IDs (comma separated)', checkpointTypes.map(c => c.id).join(','));
            if (!checkpoints) return;
            try {
              await ApiNew.applyDeliverablesTemplate({
                purchase_order_id: poId,
                po_line_ids: lineId ? [lineId] : undefined,
                lot_quantities: lotQty.split(',').map(v => Number(v.trim())).filter(v => !Number.isNaN(v)),
                checkpoint_type_ids: checkpoints.split(',').map(v => Number(v.trim())).filter(v => !Number.isNaN(v)),
              });
              alert('Template applied.');
              loadLots();
            } catch (err) {
              showError(err);
            }
          };

          if (poOptions.length > 1) {
            poSelect.value = poOptions[1].value;
            populateLines(poSelect.value);
            loadLots();
          }
        }

        async function renderReports(){
          if (!FEATURES.SAVED_REPORTS) {
            content.innerHTML = card('Reports', '<p>Saved reports are disabled.</p>');
            return;
          }

          const views = [
            { value: 'v_budget_commit_actual', label: 'Budget vs Commit/Actual' },
            { value: 'v_open_commitments', label: 'Open Commitments' },
            { value: 'v_vendor_spend_aging', label: 'Vendor Spend Aging' },
            { value: 'v_open_items', label: 'Open Items' },
            { value: 'v_future_plan', label: 'Future Plan' },
            { value: 'v_to_car_closure', label: 'To CAR Closure' },
          ];

          const savedReports = await ApiNew.listReports();

          const viewOptions = views.map(v => ({ value: v.value, label: v.label, raw: v }));

          content.innerHTML = `
            <div class="row">
              <div class="card" style="flex:1">
                <h3>Saved Reports</h3>
                <ul id="reportList" class="report-list">
                  ${savedReports.map(r => `<li data-report-id="${r.id}"><strong>${r.name}</strong><br/><small>${r.owner}</small></li>`).join('') || '<li>(none yet)</li>'}
                </ul>
              </div>
              <div class="card" style="flex:2">
                <h3>Report Builder</h3>
                <div class="field">
                  ${labelFor('reportName','Name','Saved report name.')}
                  <input class="input" id="reportName" placeholder="Quarterly actuals" />
                </div>
                <div class="field">
                  ${labelFor('reportOwner','Owner','Displayed owner for saved report.')}
                  <input class="input" id="reportOwner" placeholder="Analyst" />
                </div>
                <div class="field">
                  ${labelFor('reportView','Base View','Underlying SQL view to query.')}
                  ${select('reportView', viewOptions, { allowCreate: false, allowEdit: false, allowDelete: false })}
                </div>
                <div class="row two">
                  <div class="field">
                    ${labelFor('reportDims','Dimensions (comma-separated)','e.g., funding_source,project')}
                    <input class="input" id="reportDims" placeholder="funding_source,project" />
                  </div>
                  <div class="field">
                    ${labelFor('reportMeasures','Measures','e.g., budget_usd,actual_usd')}
                    <input class="input" id="reportMeasures" placeholder="budget_usd,commitment_usd,accrual_usd" />
                  </div>
                </div>
                <div class="field">
                  ${labelFor('reportFilters','Filters (JSON)','Example: {"funding_source_id":123}')}
                  <textarea class="input" id="reportFilters" rows="3" placeholder='{"funding_source_id":123}'></textarea>
                </div>
                <div class="actions">
                  <button id="runReportBtn">Run</button>
                  <button id="saveReportBtn">Save</button>
                </div>
              </div>
            </div>
            <div id="reportResult" class="card"><em>Run or select a report to see data.</em></div>
          `;

          initializeDropdowns(content);

          const reportList = document.getElementById('reportList');
          const resultPanel = document.getElementById('reportResult');

          function parseConfig(){
            const cfg = {
              view: document.getElementById('reportView').value,
            };
            const dims = document.getElementById('reportDims').value.split(',').map(v => v.trim()).filter(Boolean);
            const measures = document.getElementById('reportMeasures').value.split(',').map(v => v.trim()).filter(Boolean);
            if (dims.length) cfg.dimensions = dims;
            if (measures.length) cfg.measures = measures;
            const filters = document.getElementById('reportFilters').value.trim();
            if (filters) {
              try {
                cfg.filters = JSON.parse(filters);
              } catch (err) {
                throw new Error('Invalid filters JSON');
              }
            }
            return cfg;
          }

          async function runReport(config){
            try {
              const data = await ApiNew.runAdhocReport(config);
              const rows = data.rows || [];
              if (!rows.length) {
                resultPanel.innerHTML = '<p>No rows returned.</p>';
                return;
              }
              const columns = Object.keys(rows[0]).map(key => ({ key, label: key, format: (val) => (typeof val === 'number' ? fmtCurrency(val) : val) }));
              resultPanel.innerHTML = card('Results', readOnlyTable(rows, columns));
            } catch (err) {
              showError(err);
            }
          }

          reportList.querySelectorAll('li[data-report-id]').forEach(node => {
            node.addEventListener('click', async () => {
              const id = node.dataset.reportId;
              const report = savedReports.find(r => String(r.id) === String(id));
              if (!report) return;
              document.getElementById('reportName').value = report.name;
              document.getElementById('reportOwner').value = report.owner;
              const viewSelect = document.getElementById('reportView');
              viewSelect.value = report.json_config.view || views[0].value;
              viewSelect.dispatchEvent(new Event('change', { bubbles: true }));
              document.getElementById('reportDims').value = (report.json_config.dimensions || []).join(',');
              document.getElementById('reportMeasures').value = (report.json_config.measures || []).join(',');
              document.getElementById('reportFilters').value = report.json_config.filters ? JSON.stringify(report.json_config.filters) : '';
              runReport(report.json_config);
            });
          });

          document.getElementById('runReportBtn').onclick = async () => {
            try {
              const cfg = parseConfig();
              await runReport(cfg);
            } catch (err) {
              showError(err);
            }
          };

          document.getElementById('saveReportBtn').onclick = async () => {
            const name = document.getElementById('reportName').value.trim();
            const owner = document.getElementById('reportOwner').value.trim() || 'system';
            if (!name) {
              alert('Provide a name.');
              return;
            }
            try {
              const cfg = parseConfig();
              await ApiNew.saveReport({ name, owner, json_config: cfg });
              alert('Report saved. Reload tab to refresh list.');
            } catch (err) {
              showError(err);
            }
          };
        }

        async function renderFx(){
          if (!FEATURES.FX_ADMIN) {
            content.innerHTML = card('FX Rates', '<p>FX administration is disabled.</p>');
            return;
          }

          async function loadRates(filters){
            try {
              const rates = await ApiNew.listFxRates(filters || {});
              if (!rates.length) return '<p>No FX rates.</p>';
              return `
                <table class="table">
                  <thead><tr><th>ID</th><th>Currency</th><th>Valid From</th><th>Valid To</th><th>Rate</th><th>Manual Override</th><th>Actions</th></tr></thead>
                  <tbody>
                    ${rates.map(r => `<tr data-id="${r.id}">
                      <td>${r.id}</td>
                      <td>${r.quote_currency}</td>
                      <td>${r.valid_from}</td>
                      <td>${r.valid_to || '-'}</td>
                      <td>${r.rate}</td>
                      <td>${r.manual_override ? 'Yes' : 'No'}</td>
                      <td>
                        <button class="btn-edit-fx">Edit</button>
                        <button class="btn-delete-fx">Delete</button>
                      </td>
                    </tr>`).join('')}
                  </tbody>
                </table>`;
            } catch (err) {
              showError(err);
              return '<p>Error loading rates.</p>';
            }
          }

          content.innerHTML = `
            ${card('Add FX Rate', `
              <div class="row four">
                ${field('fx_quote', labelFor('fx_quote','Quote Currency','e.g., EUR')), input('fx_quote','EUR')}
                ${field('fx_valid_from', labelFor('fx_valid_from','Valid From'), '<input type="date" class="input" name="fx_valid_from" />')}
                ${field('fx_valid_to', labelFor('fx_valid_to','Valid To'), '<input type="date" class="input" name="fx_valid_to" />')}
                ${field('fx_rate', labelFor('fx_rate','Rate'), input('fx_rate','1.10'))}
              </div>
              <div class="field">
                <label><input type="checkbox" name="fx_override"/> Allow override (outside 0.5–2.0)</label>
              </div>
              <div class="actions"><button id="addFx">Add</button></div>
            `)}
            <div id="fxTable" class="card"><em>Loading...</em></div>
          `;

          const fxTable = document.getElementById('fxTable');

          async function refresh(){
            fxTable.innerHTML = '<em>Loading...</em>';
            fxTable.innerHTML = await loadRates();
            fxTable.querySelectorAll('.btn-edit-fx').forEach(btn => {
              btn.addEventListener('click', async () => {
                const row = btn.closest('tr');
                const id = row.dataset.id;
                const rate = prompt('Rate', row.children[4].textContent.trim());
                const override = confirm('Allow manual override?');
                if (!rate) return;
                if (!override && (Number(rate) < 0.5 || Number(rate) > 2.0)) {
                  alert('Rate outside safety bounds. Enable override if intentional.');
                  return;
                }
                try {
                  await ApiNew.updateFxRate(id, { rate: Number(rate), manual_override: override });
                  refresh();
                } catch (err) {
                  showError(err);
                }
              });
            });
            fxTable.querySelectorAll('.btn-delete-fx').forEach(btn => {
              btn.addEventListener('click', async () => {
                const row = btn.closest('tr');
                const id = row.dataset.id;
                if (!confirm('Delete FX rate?')) return;
                try {
                  await ApiNew.deleteFxRate(id);
                  refresh();
                } catch (err) {
                  showError(err);
                }
              });
            });
          }

          document.getElementById('addFx').onclick = async () => {
            const quote = content.querySelector('input[name=fx_quote]').value.trim().toUpperCase();
            const validFrom = content.querySelector('input[name=fx_valid_from]').value;
            const validTo = content.querySelector('input[name=fx_valid_to]').value || null;
            const rate = Number(content.querySelector('input[name=fx_rate]').value);
            const override = content.querySelector('input[name=fx_override]').checked;
            if (!quote || !validFrom || !rate) {
              alert('Quote currency, date, and rate required.');
              return;
            }
            if (!override && (rate < 0.5 || rate > 2.0)) {
              alert('Rate outside safety bounds. Enable override to proceed.');
              return;
            }
            try {
              await ApiNew.createFxRate({ quote_currency: quote, valid_from: validFrom, valid_to: validTo || undefined, rate, manual_override: override });
              refresh();
            } catch (err) {
              showError(err);
            }
          };

          refresh();
        }
  
        // ---- Pivots & Health ----
        let chartInstance;
        async function renderPivots(){
          if (!FEATURES.READ_FROM_VIEWS) {
            content.innerHTML = card('Pivot & Health', '<p>View-backed analytics are disabled via feature flag.</p>');
            return;
          }
          const [fundingSources, portfolios, projects, categories, vendors] = await Promise.all([
            apiList('/api/funding-sources'),
            apiList('/api/portfolios'),
            apiList('/api/projects'),
            apiList('/api/categories'),
            apiList('/api/vendors'),
          ]);
          const fsById = mapBy(fundingSources);
          const projectMap = mapBy(projects);
          const categoryMap = mapBy(categories);
          const vendorMap = mapBy(vendors);
          const fundingSourceHandlers = { key: 'funding-source', ...buildResourceDropdownHandlers('/api/funding-sources', {
            formatLabel: (fs) => `${fs.name}${fs.closure_date ? ' • closes ' + fs.closure_date : ''}`,
            matcherFields: ['name'],
          }) };
          const portfolioOpts = [{ value: '', label: '(All Funding Sources)', raw: null }].concat(
            fundingSources.map(c => ({ value: c.id, label: `${c.name}${c.closure_date ? ' • closes ' + c.closure_date : ''}`, raw: c }))
          );
          const scenarioOptions = [
            { value: 'actual', label: 'Actual' },
          ];
          const pivotByOptions = [
            { value: '', label: 'Detailed (funding source • project • category • vendor)' },
            { value: 'portfolio', label: 'By Funding Source' },
            { value: 'project', label: 'By Project' },
            { value: 'group', label: 'By Project Group' },
            { value: 'category', label: 'By Category' },
            { value: 'vendor', label: 'By Vendor' },
            { value: 'state', label: 'By State (Forecast/Commitment/etc)' },
          ];

          const ui = document.createElement('div');
          ui.innerHTML = `
            <div class="card">
              <h3>Pivot & Health</h3>
              <div class="row three">
                <div class="field">
                  ${labelFor('scenario','Scenario','Ledger-backed — ideal scenario pending future backfill.')}
                  ${select('scenario', scenarioOptions, { allowCreate: false, allowEdit: false, allowDelete: false })}
                </div>
                <div class="field">
                  ${labelFor('by','Pivot By','Choose grouping for the pivot table below.')}
                  ${select('by', pivotByOptions, { allowCreate: false, allowEdit: false, allowDelete: false })}
                </div>
                <div class="field">
                  ${labelFor('portfolioFilter','Funding Source Filter','Pick a funding source to narrow results and show category health.')}
                  ${select('portfolioFilter', portfolioOpts, { ...fundingSourceHandlers })}
                </div>
              </div>
            </div>
            <div id="pv"></div>
            <div class="card"><canvas id="chart"></canvas></div>
            <div id="health"></div>
          `;
          content.innerHTML = ui.outerHTML;

          initializeDropdowns(content);

          const groupMap = {
            '': 'funding_source,project,category,vendor,currency',
            portfolio: 'funding_source',
            project: 'project',
            group: 'project',
            category: 'category',
            vendor: 'vendor',
            state: 'state',
          };

          function describeRow(row, by) {
            const parts = [];
            if (row.funding_source_id !== undefined && row.funding_source_id !== null) {
              const fs = fsById[row.funding_source_id];
              parts.push(fs ? fs.name : `Funding ${row.funding_source_id}`);
            }
            if ((by === '' || by === 'project' || by === 'group') && row.project_id) {
              const proj = projectMap[row.project_id];
              parts.push(proj ? proj.name : `Project ${row.project_id}`);
              if (by === 'group' && proj && proj.group_id) {
                parts.push(`Group ${proj.group_id}`);
              }
            }
            if ((by === '' || by === 'category') && row.category_id) {
              const cat = categoryMap[row.category_id];
              parts.push(cat ? catPath(cat, categoryMap) : `Category ${row.category_id}`);
            }
            if ((by === '' || by === 'vendor') && row.vendor_id) {
              const vendor = vendorMap[row.vendor_id];
              parts.push(vendor ? vendor.name : `Vendor ${row.vendor_id}`);
            }
            if (by === 'state' && row.state) parts.push(row.state);
            return parts.length ? parts.join(' • ') : 'Total';
          }

          async function draw(){
            try {
              const by = content.querySelector('select[name=by]').value;
              const portfolioFilter = content.querySelector('select[name=portfolioFilter]').value;
              const groupParam = groupMap[by] || groupMap[''];
              const baseParams = { group_by: groupParam };
              const filterId = portfolioFilter ? Number(portfolioFilter) : undefined;
              if (filterId) baseParams.funding_source_id = filterId;

              const portfolioParams = filterId ? { group_by: 'funding_source', funding_source_id: filterId } : { group_by: 'funding_source' };
              const categoryParams = filterId ? { group_by: 'category', funding_source_id: filterId } : null;
              const openParams = filterId ? { funding_source_id: filterId } : {};
              const closureParams = filterId ? { funding_source_id: filterId } : {};

              const [pivotData, summaryData, openData, closureData, categoryData] = await Promise.all([
                ApiNew.getBudgetCommitActual(baseParams),
                ApiNew.getBudgetCommitActual(portfolioParams),
                ApiNew.getOpenCommitments(openParams),
                ApiNew.getToCarClosure(closureParams),
                categoryParams ? ApiNew.getBudgetCommitActual(categoryParams) : Promise.resolve([]),
              ]);

              const pivotRows = pivotData.map(row => {
                const actual = Number(row.accrual_usd || 0) + Number(row.cash_usd || 0);
                return {
                  label: describeRow(row, by || ''),
                  budget_usd: Number(row.budget_usd || 0),
                  commitment_usd: Number(row.commitment_usd || 0),
                  accrual_usd: Number(row.accrual_usd || 0),
                  cash_usd: Number(row.cash_usd || 0),
                  open_commitment_usd: Number(row.open_commitment_usd || 0),
                  variance_usd: Number(row.variance_usd || 0),
                  variance_pct: row.variance_pct,
                  actual_usd: actual,
                };
              });

              const pivotColumns = [
                { key: 'label', label: 'Grouping' },
                { key: 'budget_usd', label: 'Budget (USD)', format: fmtCurrency },
                { key: 'commitment_usd', label: 'Commitment (USD)', format: fmtCurrency },
                { key: 'accrual_usd', label: 'Accrual (USD)', format: fmtCurrency },
                { key: 'cash_usd', label: 'Cash (USD)', format: fmtCurrency },
                { key: 'open_commitment_usd', label: 'Open (USD)', format: fmtCurrency },
                { key: 'variance_usd', label: 'Variance (USD)', format: fmtCurrency },
                { key: 'variance_pct', label: 'Variance %', format: (v) => v === null || v === undefined ? '-' : `${v.toFixed(2)}%` },
              ];
              document.getElementById('pv').innerHTML = card('Pivot Summary', readOnlyTable(pivotRows, pivotColumns));

              const labels = pivotRows.map(r => r.label);
              const values = pivotRows.map(r => r.actual_usd);
              const ctx = document.getElementById('chart');
              if(chartInstance) chartInstance.destroy();
              chartInstance = new Chart(ctx, { type: 'bar', data: { labels, datasets: [{ label: 'Actual (Accrual + Cash)', data: values, backgroundColor: '#4864d6' }] }, options: { responsive:true } });

              const portfolioSummary = summaryData.reduce((acc, row) => {
                const fsId = row.funding_source_id;
                if (!fsId) return acc;
                const actual = Number(row.accrual_usd || 0) + Number(row.cash_usd || 0);
                acc[fsId] = {
                  funding_source_id: fsId,
                  name: fsById[fsId] ? fsById[fsId].name : `Funding ${fsId}`,
                  budget: Number(row.budget_usd || 0),
                  actual,
                  variance: Number(row.variance_usd || 0),
                  variance_pct: row.variance_pct,
                };
                return acc;
              }, {});

              openData.forEach(row => {
                const fsId = row.funding_source_id;
                if (!fsId || !portfolioSummary[fsId]) return;
                portfolioSummary[fsId].open = Number(row.open_commitment_usd || row.commitment_usd || 0);
              });

              closureData.forEach(row => {
                const fsId = row.funding_source_id;
                if (!fsId || !portfolioSummary[fsId]) return;
                portfolioSummary[fsId].closure_date = row.closure_date || null;
              });

              const portfolioRows = Object.values(portfolioSummary).map(row => {
                return {
                  name: row.name,
                  budget: row.budget,
                  actual: row.actual,
                  variance: row.variance,
                  variance_pct: row.variance_pct,
                  open: row.open || 0,
                  closure_date: row.closure_date || '-',
                  status: computeStatus(row.budget, row.actual),
                };
              });

              const portfolioColumns = [
                { key: 'name', label: 'Funding Source' },
                { key: 'budget', label: 'Budget (USD)', format: fmtCurrency },
                { key: 'actual', label: 'Actual (USD)', format: fmtCurrency },
                { key: 'open', label: 'Open Commit (USD)', format: fmtCurrency },
                { key: 'variance', label: 'Variance (USD)', format: fmtCurrency },
                { key: 'variance_pct', label: 'Variance %', format: (v) => v === null || v === undefined ? '-' : `${v.toFixed(2)}%` },
                { key: 'status', label: 'Status' },
                { key: 'closure_date', label: 'Closure Date' },
              ];

              let healthHtml = card('Health — By Funding Source', readOnlyTable(portfolioRows, portfolioColumns));

              if (filterId && categoryData.length) {
                const categoryRows = categoryData.map(row => {
                  const actual = Number(row.accrual_usd || 0) + Number(row.cash_usd || 0);
                  const cat = categoryMap[row.category_id];
                  return {
                    category: cat ? catPath(cat, categoryMap) : `Category ${row.category_id}`,
                    budget: Number(row.budget_usd || 0),
                    actual,
                    variance: Number(row.variance_usd || 0),
                    variance_pct: row.variance_pct,
                    status: computeStatus(row.budget_usd, actual),
                  };
                });
                const categoryColumns = [
                  { key: 'category', label: 'Category' },
                  { key: 'budget', label: 'Budget (USD)', format: fmtCurrency },
                  { key: 'actual', label: 'Actual (USD)', format: fmtCurrency },
                  { key: 'variance', label: 'Variance (USD)', format: fmtCurrency },
                  { key: 'variance_pct', label: 'Variance %', format: (v) => v === null || v === undefined ? '-' : `${v.toFixed(2)}%` },
                  { key: 'status', label: 'Status' },
                ];
                healthHtml += card('Health — By Category (selected funding source)', readOnlyTable(categoryRows, categoryColumns));
              } else {
                healthHtml += card('Health — By Category', '<div><em>Select a funding source above.</em></div>');
              }

              document.getElementById('health').innerHTML = healthHtml;
            } catch (e) { showError(e); }
          }

          content.querySelector('select[name=by]').onchange = draw;
          content.querySelector('select[name=portfolioFilter]').onchange = draw;
          draw();
        }
  
        async function renderTags(){
          content.innerHTML = `
            <div class="tag-manager">
              <div class="tag-manager-header">
                <h2>Tag Manager</h2>
                <div class="tag-manager-actions">
                  <button id="tagNewButton">New Tag</button>
                  <button id="tagRebuildAll">Rebuild Effective Tags</button>
                </div>
              </div>
              <div class="tag-manager-search">
                <input id="tagSearch" class="input" placeholder="Search tags…" autocomplete="off" />
              </div>
              <div id="tagTable" class="tag-manager-table"></div>
            </div>`;

          const tableEl = content.querySelector('#tagTable');
          const searchEl = content.querySelector('#tagSearch');
          const newBtn = content.querySelector('#tagNewButton');
          const rebuildBtn = content.querySelector('#tagRebuildAll');

          let tags = [];
          let usage = [];
          let filtered = [];

          async function loadTags() {
            tags = await api('/api/tags?includeDeprecated=true');
            usage = await api('/api/tags/usage');
            filtered = tags.slice();
            renderTable();
          }

          function usageFor(tagId) {
            const entry = usage.find(item => item.tag.id === tagId);
            return entry ? entry.assignments : { budget: 0, project: 0, category: 0, entry: 0, line_asset: 0 };
          }

          function renderTable() {
            if (!filtered.length) {
              tableEl.innerHTML = '<div class="tag-empty">No tags found.</div>';
              return;
            }
            const table = document.createElement('table');
            table.className = 'tag-table';
            table.innerHTML = `
              <thead>
                <tr>
                  <th>Tag</th>
                  <th>Description</th>
                  <th>Deprecated</th>
                  <th>Usage</th>
                  <th style="width:140px">Actions</th>
                </tr>
              </thead>
              <tbody></tbody>`;
            const tbody = table.querySelector('tbody');
            filtered.forEach(tag => {
              const assignments = usageFor(tag.id);
              const row = document.createElement('tr');
              row.innerHTML = `
                <td>
                  <div class="tag-cell">
                    <span class="tag-swatch" style="background:${tag.color || '#4b5771'}"></span>
                    <span class="tag-name">#${escapeHtml(tag.name)}</span>
                  </div>
                </td>
                <td>${escapeHtml(tag.description || '')}</td>
                <td>${tag.is_deprecated ? 'Yes' : 'No'}</td>
                <td>
                  <div class="tag-usage">${['budget','project','category','entry','line_asset'].map(key => `<span>${key}:${assignments[key] || 0}</span>`).join(' ')}</div>
                </td>
                <td class="tag-actions"></td>`;
              const actionsCell = row.querySelector('.tag-actions');
              const editBtn = document.createElement('button');
              editBtn.textContent = 'Edit';
              editBtn.addEventListener('click', () => {
                openTagEditor(editBtn, tag, {
                  onSaved: async () => {
                    await loadTags();
                    if (typeof fundingState.refreshCurrentBudget === 'function') await fundingState.refreshCurrentBudget();
                  },
                });
              });
              const mergeBtn = document.createElement('button');
              mergeBtn.textContent = 'Merge';
              mergeBtn.addEventListener('click', async () => {
                const targetName = prompt('Merge into which tag? Enter name (without #)');
                if (!targetName) return;
                const target = tags.find(t => t.name.toLowerCase() === targetName.trim().toLowerCase() && t.id !== tag.id);
                if (!target) return alert('Tag not found.');
                if (!confirm(`Merge #${tag.name} into #${target.name}?`)) return;
                try {
                  await api(`/api/tags/${tag.id}/merge-into/${target.id}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ actor: 'UI' }),
                  });
                  fundingState.tagCache.clear();
                  await loadTags();
                  if (typeof fundingState.refreshCurrentBudget === 'function') await fundingState.refreshCurrentBudget();
                } catch (err) {
                  showError(err);
                }
              });
              const deprecateBtn = document.createElement('button');
              deprecateBtn.textContent = tag.is_deprecated ? 'Undeprecate' : 'Deprecate';
              deprecateBtn.addEventListener('click', async () => {
                try {
                  await api(`/api/tags/${tag.id}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ is_deprecated: !tag.is_deprecated, actor: 'UI' }),
                  });
                  await loadTags();
                  if (typeof fundingState.refreshCurrentBudget === 'function') await fundingState.refreshCurrentBudget();
                } catch (err) {
                  showError(err);
                }
              });
              const deleteBtn = document.createElement('button');
              deleteBtn.textContent = 'Delete';
              const totalUsage = Object.values(assignments).reduce((a, b) => a + (b || 0), 0);
              if (totalUsage > 0) {
                deleteBtn.disabled = true;
                deleteBtn.title = 'Cannot delete tag with assignments';
              }
              deleteBtn.addEventListener('click', async () => {
                if (totalUsage > 0) return;
                if (!confirm(`Delete tag #${tag.name}?`)) return;
                try {
                  await api(`/api/tags/${tag.id}`, { method: 'DELETE' });
                  fundingState.tagCache.clear();
                  await loadTags();
                  if (typeof fundingState.refreshCurrentBudget === 'function') await fundingState.refreshCurrentBudget();
                } catch (err) {
                  showError(err);
                }
              });
              actionsCell.append(editBtn, mergeBtn, deprecateBtn, deleteBtn);
              tbody.appendChild(row);
            });
            tableEl.innerHTML = '';
            tableEl.appendChild(table);
          }

          if (newBtn) newBtn.onclick = () => {
            const name = prompt('New tag name (lowercase, no spaces)');
            if (!name) return;
            const clean = name.trim().toLowerCase();
            if (!clean.match(/^[a-z0-9_.:-]+$/)) {
              alert('Tag names must be lowercase alphanumerics or - _ . :');
              return;
            }
            api('/api/tags', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ name: clean, color: randomTagColor(), actor: 'UI' }),
            }).then(async () => {
              fundingState.tagCache.clear();
              await loadTags();
            }).catch(showError);
          };

          if (rebuildBtn) rebuildBtn.onclick = () => enqueueScopedRebuild(null, 'Tag Manager');

          let searchTimer = null;
          searchEl.addEventListener('input', () => {
            const term = searchEl.value.trim().toLowerCase();
            if (searchTimer) clearTimeout(searchTimer);
            searchTimer = setTimeout(() => {
              filtered = tags.filter(tag => tag.name.toLowerCase().includes(term) || (tag.description || '').toLowerCase().includes(term));
              renderTable();
            }, 180);
          });

          try {
            await loadTags();
          } catch (err) {
            showError(err);
          }
        }
  
        // ---- Router ----
        async function renderActive(){
          const active = document.querySelector('nav button.active');
          const tab = active && active.dataset.tab;
          try {
            if(tab==='portfolios') return renderPortfolios();
            if(tab==='vendors') return renderVendors();
            if(tab==='entries') return renderEntries();
            if(tab==='pivots') return renderPivots();
            if(tab==='payments') return renderPayments();
            if(tab==='deliverables') return renderDeliverables();
            if(tab==='reports') return renderReports();
            if(tab==='fx') return renderFx();
            if(tab==='tags') return renderTags();
            content.innerHTML = card('Welcome','Pick a tab above to get started.');
          } catch (e) { showError(e); }
        }

        nav.addEventListener('click', (e)=>{
          const btn = e.target.closest('button[data-tab]');
          if (!btn) return;
          const tab = btn.dataset.tab;
          document.querySelectorAll('nav button').forEach(x=>x.classList.remove('active'));
          btn.classList.add('active');
          renderActive();
        });
  
        const firstTab = Array.from(nav.querySelectorAll('button[data-tab]')).find(btn => btn.style.display !== 'none');
        if (firstTab && !document.querySelector('nav button.active')) firstTab.classList.add('active');
        renderActive();

        // --- Quit wiring & auto-shutdown ---
        const params = new URLSearchParams(location.search);
        const autoQuit = params.get('autoshutdown') === '1';

        // Manual Quit button
        if (quitBtn) {
        quitBtn.onclick = async () => {
            try { await fetch('/api/quit', { method: 'POST' }); } catch (_) {}
        };
        }

        // Auto-quit (only when page launched with ?autoshutdown=1)
        if (autoQuit) {
        const sendQuit = () => {
            try {
            navigator.sendBeacon('/api/quit', 'bye');
            } catch (_) {
            fetch('/api/quit', { method: 'POST', keepalive: true });
            }
        };
        window.addEventListener('pagehide', sendQuit);
        window.addEventListener('beforeunload', sendQuit);
        }

        if (loadBtn) loadBtn.onclick = async () => {
          try { const r = await api('/api/load-latest', {method:'POST'}); alert('Loaded ' + (r.loaded_from || 'empty DB')); renderActive(); }
          catch (e) { showError(e); }
        };
        if (saveBtn) saveBtn.onclick = async () => {
          try { const r = await api('/api/save-snapshot', {method:'POST'}); alert('Saved to ' + r.saved_to); }
          catch (e) { showError(e); }
        };
      } catch (e) {
        showError(e);
      }
    }
  })();
  
