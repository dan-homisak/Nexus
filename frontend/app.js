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
        const formatProjectGroupLabel = (pg) => `${pg.code ? pg.code + ' – ' : ''}${pg.name}`;
        const formatProjectLabel = (project, portfolioLookup) => {
          const fs = portfolioLookup && portfolioLookup[project.portfolio_id];
          const fsLabel = fs ? formatPortfolioLabel(fs) : `Funding Source ${project.portfolio_id}`;
          return `[${fsLabel}] ${project.name}`;
        };

        let reallocateDrawer = null;
        let reallocateCurrent = null;
        let reallocateSubmit = null;

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
              '/api/project-groups': ['code','name','description'],
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
          const portfolios = await apiList('/api/portfolios');
          content.innerHTML =
            card('Add Funding Source', `
              <div class="row">
                ${field('name', labelFor('name','Name', 'e.g., "FY25 CapEx – Line EX6".'), input('name','FY25 CapEx'))}
                ${field('fiscal_year', labelFor('fiscal_year','Fiscal Year', 'Optional metadata (FY25 or 2025).'), input('fiscal_year','FY25'))}
                ${field('owner', labelFor('owner','Owner', 'Approver / controller.'), input('owner','Dan'))}
                <div class="field"><label>&nbsp;</label><button id="add">Add</button></div>
              </div>`)
            + card('All Funding Sources', table(portfolios, [
              { key: 'id', label: 'ID' },
              { key: 'name', label: 'Funding Source Name' },
              { key: 'fiscal_year', label: 'Fiscal Year' },
              { key: 'owner', label: 'Owner' },
            ], '/api/portfolios'));

          initializeDropdowns(content);

          const add = document.getElementById('add');
          if (add) add.onclick = async ()=>{
            const [name, fiscal_year, owner] = [...content.querySelectorAll('input')].map(i=>i.value);
            if(!name) return alert('Name required');
            await apiCreate('/api/portfolios', {name, fiscal_year, owner});
            renderPortfolios();
          };
        }
  
        async function renderProjectGroups(){
          const pgs = await apiList('/api/project-groups');
          content.innerHTML =
            card('Add Project Group', `
              <div class="row">
                ${field('code', labelFor('code','Code', 'Short code shared across funding sources e.g., "COBRA".'), input('code','COBRA'))}
                ${field('name', labelFor('name','Name', 'Program name (rollup label).'), input('name','Cobra Program'))}
                ${field('description', labelFor('description','Description','What counts as this program.'), `<textarea class="input" name="description" rows="1" placeholder="Optional"></textarea>`)}
                <div class="field"><label>&nbsp;</label><button id="add">Add</button></div>
              </div>`)
            + card('All Project Groups', table(pgs, [
              { key: 'id', label: 'ID' },
              { key: 'code', label: 'Code' },
              { key: 'name', label: 'Project Group Name' },
              { key: 'description', label: 'Description' },
            ], '/api/project-groups'));

          initializeDropdowns(content);
          const add = document.getElementById('add');
          if (add) add.onclick = async ()=>{
            const code = content.querySelector('input[name=code]').value;
            const name = content.querySelector('input[name=name]').value;
            const description = content.querySelector('textarea[name=description]').value;
            if(!name) return alert('Name required');
            await apiCreate('/api/project-groups', {code:code||null, name, description:description||null});
            renderProjectGroups();
          };
        }
  
        async function renderProjects(){
          const [portfolios, pgs, projects] = await Promise.all([
            apiList('/api/portfolios'), apiList('/api/project-groups'), apiList('/api/projects')
          ]);
          const portfolioOpts = portfolios.map(p => ({ value: p.id, label: formatPortfolioLabel(p), raw: p }));
          const basePortfolioHandlers = buildResourceDropdownHandlers('/api/portfolios', {
            formatLabel: formatPortfolioLabel,
            buildCreateBody: (label) => ({ name: label }),
            buildUpdateBody: (raw, label) => ({ ...stripId(raw), name: label }),
            matcherFields: ['fiscal_year', 'owner', 'type', 'car_code', 'cc_code'],
          });
          const portfolioHandlers = { key: 'portfolio', ...basePortfolioHandlers };
          const pgOpts = [{ value: '', label: '(none)', raw: null }].concat(
            pgs.map(pg => ({ value: pg.id, label: formatProjectGroupLabel(pg), raw: pg }))
          );
          const baseProjectGroupHandlers = buildResourceDropdownHandlers('/api/project-groups', {
            formatLabel: formatProjectGroupLabel,
            buildCreateBody: (label) => ({ name: label }),
            buildUpdateBody: (raw, label) => ({ ...stripId(raw), name: label }),
            matcherFields: ['code', 'description'],
          });
          const projectGroupHandlers = { key: 'project-group', ...baseProjectGroupHandlers };
          const projectGroupOptions = pgs.map(pg => ({ value: pg.id, label: formatProjectGroupLabel(pg), raw: pg }));
          const originalGroupCreate = projectGroupHandlers.create;
          projectGroupHandlers.create = async (label) => {
            const created = await originalGroupCreate(label);
            if (created && created.value !== undefined) {
              projectGroupOptions.push({ value: created.value, label: created.label, raw: created.raw });
            }
            return created;
          };

          content.innerHTML =
            card('Add Project', `
              <div class="row">
                ${field('portfolio_id', labelFor('portfolio_id','Funding Source', 'Each project belongs to a single funding source.'), select('portfolio_id', portfolioOpts, portfolioHandlers))}
                ${field('name', labelFor('name','Project Name', 'Per funding source project name (duplicates allowed across funding sources).'), input('name','Cobra'))}
                ${field('group_id', labelFor('group_id','Project Group', 'Use to roll up similar projects across funding sources.'), select('group_id', pgOpts, projectGroupHandlers))}
                ${field('code', labelFor('code','Project Code (optional)','Internal alias'), input('code','COBRA-PM1'))}
                ${field('line', labelFor('line','Line/Asset (optional)','e.g., EX6'), input('line','EX6'))}
                <div class="field"><label>&nbsp;</label><button id="add">Add</button></div>
              </div>`)
            + card('All Projects', table(projects, [
              { key: 'id', label: 'ID' },
              { key: 'portfolio_id', label: 'Funding Source' },
              { key: 'name', label: 'Project Name' },
              { key: 'group_id', label: 'Project Group' },
              { key: 'code', label: 'Project Code' },
              { key: 'line', label: 'Line / Asset' },
            ], '/api/projects'));

          initializeDropdowns(content);
          setupTableEditing(content, '/api/projects', projects, {
            portfolio_id: {
              type: 'dropdown',
              options: portfolioOpts,
              handlers: portfolioHandlers,
              valueType: 'number',
            },
            group_id: {
              type: 'dropdown',
              getOptions: () => projectGroupOptions,
              handlers: projectGroupHandlers,
              valueType: 'number',
              allowNull: true,
              nullOptionLabel: '(none)',
            },
          });

          const add = document.getElementById('add');
          if (add) add.onclick = async ()=>{
            const body = {
              portfolio_id: Number(content.querySelector('select[name=portfolio_id]').value),
              name: content.querySelector('input[name=name]').value,
              group_id: content.querySelector('select[name=group_id]').value ? Number(content.querySelector('select[name=group_id]').value) : null,
              code: content.querySelector('input[name=code]').value || null,
              line: content.querySelector('input[name=line]').value || null
            };
            if(!body.name) return alert('Project name required');
            await apiCreate('/api/projects', body);
            renderProjects();
          };
        }
  
        async function renderCategories(){
          const [projects, categories] = await Promise.all([apiList('/api/projects'), apiList('/api/categories')]);
          const categoryMap = mapBy(categories);
          const projectMap = mapBy(projects);

          const projOpts = [{ value: '', label: '(Global)', raw: null }].concat(projects.map(p=>({
            value: p.id,
            label: `Project #${p.id} — ${p.name} [Funding Source ${p.portfolio_id}]`,
            raw: p,
          })));
          const projectHandlers = { key: 'project', ...buildResourceDropdownHandlers('/api/projects', {
            formatLabel: (p) => `Project #${p.id} — ${p.name} [Funding Source ${p.portfolio_id}]`,
            buildCreateBody: (label) => ({ name: label, portfolio_id: projects[0]?.portfolio_id ?? 1 }),
            buildUpdateBody: (raw, label) => ({ ...stripId(raw), name: label }),
            matcherFields: ['portfolio_id', 'code', 'line'],
          }) };
          const catOpts = [{ value: '', label: '(No parent)', raw: null }].concat(categories.map(c=>({
            value: c.id,
            label: catPath(c, categoryMap),
            raw: c,
          })));
          const categoryHandlers = { key: 'category', ...buildResourceDropdownHandlers('/api/categories', {
            formatLabel: (c) => catPath(c, { ...categoryMap, [c.id]: c }),
            buildCreateBody: (label) => ({ name: label }),
            buildUpdateBody: (raw, label) => ({ ...stripId(raw), name: label }),
            matcherFields: ['project_id', 'parent_id'],
          }) };

          const parentOptions = categories.map(c => ({ value: c.id, label: catPath(c, categoryMap), raw: c }));
          const projectOptions = projects.map(p => ({ value: p.id, label: `Project #${p.id} — ${p.name}`, raw: p }));
          const originalProjectCreateForCategories = projectHandlers.create;
          projectHandlers.create = async (label) => {
            const created = await originalProjectCreateForCategories(label);
            if (created && created.value !== undefined) {
              projectOptions.push({ value: created.value, label: created.label, raw: created.raw });
            }
            return created;
          };
          const originalProjectEditForCategories = projectHandlers.edit;
          projectHandlers.edit = async (option, nextLabel) => {
            const updated = await originalProjectEditForCategories(option, nextLabel);
            const target = projectOptions.find(opt => opt.value === updated.value);
            if (target) target.label = updated.label;
            return updated;
          };

          content.innerHTML =
            card('Add Category (n-level)', `
              <div class="row">
                ${field('name', labelFor('name','Name', 'E.g., "Parts" → "Long Lead".'), input('name','Parts / Long Lead'))}
                ${field('parent_id', labelFor('parent_id','Parent', 'Choose a parent to nest; else root.'), select('parent_id', catOpts, { ...categoryHandlers, allowCreate: false, allowDelete: false }))}
                ${field('project_id', labelFor('project_id','Scope (Project)','Blank = global tree; otherwise project-scoped.'), select('project_id', projOpts, { ...projectHandlers, allowCreate: false }))}
                <div class="field"><label>&nbsp;</label><button id="add">Add</button></div>
              </div>
            `)
            + card('All Categories', table(categories, [
              { key: 'id', label: 'ID' },
              { key: 'name', label: 'Category Name' },
              { key: 'parent_id', label: 'Parent Category' },
              { key: 'project_id', label: 'Project Scope' },
            ], '/api/categories'));

          initializeDropdowns(content);
          setupTableEditing(content, '/api/categories', categories, {
            parent_id: {
              type: 'dropdown',
              getOptions: (row) => parentOptions.filter(opt => opt.value !== row.id),
              handlers: categoryHandlers,
              valueType: 'number',
              allowNull: true,
              nullOptionLabel: '(No parent)',
            },
            project_id: {
              type: 'dropdown',
              options: projectOptions,
              handlers: projectHandlers,
              valueType: 'number',
              allowNull: true,
              nullOptionLabel: '(Global)',
            },
          });
  
          const add = document.getElementById('add');
          if (add) add.onclick = async ()=>{
            const name = content.querySelector('input[name=name]').value;
            const parentRaw = content.querySelector('select[name=parent_id]').value;
            const projectRaw = content.querySelector('select[name=project_id]').value;
            const body = {
              name,
              parent_id: parentRaw ? Number(parentRaw) : null,
              project_id: projectRaw ? Number(projectRaw) : null
            };
            if(!name) return alert('Name required');
            await apiCreate('/api/categories', body);
            renderCategories();
          };
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
          const tags = await apiList('/api/tags');
          content.innerHTML =
            card('Add Tag', `
              <div class="row">
                ${field('name', labelFor('name','Tag','Freeform label to group entries for ad-hoc reporting.'), input('name','long-lead'))}
                <div class="field"><label>&nbsp;</label><button id="add">Add</button></div>
              </div>`)
            + card('All Tags', table(tags, [
              { key: 'id', label: 'ID' },
              { key: 'name', label: 'Tag Name' },
            ], '/api/tags'));
          const add = document.getElementById('add');
          if (add) add.onclick = async ()=>{
            const name = content.querySelector('input[name=name]').value;
            if(!name) return alert('Tag required');
            await apiCreate('/api/tags', {name});
            renderTags();
          };
        }
  
        // ---- Router ----
        async function renderActive(){
          const active = document.querySelector('nav button.active');
          const tab = active && active.dataset.tab;
          try {
            if(tab==='portfolios') return renderPortfolios();
            if(tab==='project_groups') return renderProjectGroups();
            if(tab==='projects') return renderProjects();
            if(tab==='categories') return renderCategories();
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
  
