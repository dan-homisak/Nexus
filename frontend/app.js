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
  
        // ---- UI helpers ----
        const escapeTip = (s) => String(s).replace(/"/g, '&quot;');
        const labelFor = (name, text, tip) => {
          const tipHtml = tip ? `<span class="info" data-tip="${escapeTip(tip)}">i</span>` : '';
          return `<label for="${name}">${text}${tipHtml}</label>`;
        };
        const field = (name, labelHtml, inputHtml) => `<div class="field">${labelHtml}${inputHtml}</div>`;
        const input = (name, placeholder='') => `<input class="input" name="${name}" placeholder="${placeholder}"/>`;
        const select = (name, opts) => `<select name="${name}">${opts.map(o=>`<option value="${o.value}">${o.label}</option>`).join('')}</select>`;
        const card = (title, inner='') => `<div class="card"><h3>${title}</h3>${inner}</div>`;
        const table = (rows, cols, base) => {
          if (!rows || !rows.length) return '<div>(empty)</div>';
          const head = '<tr>' + cols.map(c=>`<th>${c}</th>`).join('') + '<th>Actions</th></tr>';
          const body = rows.map(r => `
            <tr>
              ${cols.map(c=>{
                const editable = c === 'id' ? '' : ' contenteditable';
                return `<td${editable} data-field="${c}" data-id="${r.id}">${r[c] ?? ''}</td>`;
              }).join('')}
              <td>
                <button onclick="window.__updateRow?.('${base}', ${r.id}, this)">Save</button>
                <button onclick="window.__deleteRow?.('${base}', ${r.id})">Delete</button>
              </td>
            </tr>`).join('');
          return `<table class="table"><thead>${head}</thead><tbody>${body}</tbody></table>`;
        };
  
        const mapBy = (arr, key='id') => Object.fromEntries(arr.map(x=>[x[key], x]));
        const catPath = (cat, byId) => {
          const path = []; let cur = cat;
          while (cur) { path.unshift(cur.name); if (!cur.parent_id) break; cur = byId[cur.parent_id]; }
          return path.join(' > ');
        };
  
        // Expose update/delete for table buttons
        window.__updateRow = async function(base, id, btn){
          try {
            const tr = btn.closest('tr');
            const tds = [...tr.querySelectorAll('[data-field]')];
            const body = {};
            tds.forEach(td => { body[td.dataset.field] = td.innerText.trim(); });
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
            card('Add Portfolio', `
              <div class="row">
                ${field('name', labelFor('name','Name', 'e.g., "FY25 CapEx – Line EX6".'), input('name','FY25 CapEx'))}
                ${field('fiscal_year', labelFor('fiscal_year','Fiscal Year', 'Optional: FY25 or 2025.'), input('fiscal_year','FY25'))}
                ${field('owner', labelFor('owner','Owner', 'Approver/owner.'), input('owner','Dan'))}
                <div class="field"><label>&nbsp;</label><button id="add">Add</button></div>
              </div>`)
            + card('All Portfolios', table(portfolios, ['id','name','fiscal_year','owner'], '/api/portfolios'));
  
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
                ${field('code', labelFor('code','Code', 'Short code shared across portfolios. e.g., "COBRA".'), input('code','COBRA'))}
                ${field('name', labelFor('name','Name', 'Program name (rollup label).'), input('name','Cobra Program'))}
                ${field('description', labelFor('description','Description','What counts as this program.'), `<textarea class="input" name="description" rows="1" placeholder="Optional"></textarea>`)}
                <div class="field"><label>&nbsp;</label><button id="add">Add</button></div>
              </div>`)
            + card('All Project Groups', table(pgs, ['id','code','name','description'], '/api/project-groups'));
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
          const portfolioOpts = portfolios.map(p=>({value:p.id, label:`${p.name}${p.fiscal_year ? ' • FY '+p.fiscal_year : ''}`}));
          const pgOpts = [{value:'', label:'(none)'}].concat(pgs.map(pg=>({value:pg.id, label:`${pg.code?pg.code+' – ':''}${pg.name}`})));

          content.innerHTML =
            card('Add Project', `
              <div class="row">
                ${field('portfolio_id', labelFor('portfolio_id','Portfolio', 'Each project belongs to a single portfolio.'), select('portfolio_id', portfolioOpts))}
                ${field('name', labelFor('name','Project Name', 'Per-portfolio project name (duplicates allowed across portfolios).'), input('name','Cobra'))}
                ${field('group_id', labelFor('group_id','Project Group', 'Use to roll up similar projects across portfolios.'), select('group_id', pgOpts))}
                ${field('code', labelFor('code','Project Code (optional)','Internal alias'), input('code','COBRA-PM1'))}
                ${field('line', labelFor('line','Line/Asset (optional)','e.g., EX6'), input('line','EX6'))}
                <div class="field"><label>&nbsp;</label><button id="add">Add</button></div>
              </div>`)
            + card('All Projects', table(projects, ['id','portfolio_id','name','group_id','code','line'], '/api/projects'));

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
          const projOpts = [{value:'', label:'(Global)'}].concat(projects.map(p=>({
            value: p.id, label: `Project #${p.id} — ${p.name} [Portfolio ${p.portfolio_id}]`
          })));
          const catOpts = [{value:'', label:'(No parent)'}].concat(categories.map(c=>({value:c.id, label:`#${c.id} — ${c.name}`})));
  
          content.innerHTML =
            card('Add Category (n-level)', `
              <div class="row">
                ${field('name', labelFor('name','Name', 'E.g., "Parts" → "Long Lead".'), input('name','Parts / Long Lead'))}
                ${field('parent_id', labelFor('parent_id','Parent', 'Choose a parent to nest; else root.'), select('parent_id', catOpts))}
                ${field('project_id', labelFor('project_id','Scope (Project)','Blank = global tree; otherwise project-scoped.'), select('project_id', projOpts))}
                <div class="field"><label>&nbsp;</label><button id="add">Add</button></div>
              </div>
            `)
            + card('All Categories', table(categories, ['id','name','parent_id','project_id'], '/api/categories'));
  
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
            + card('All Vendors', table(vendors, ['id','name'], '/api/vendors'));
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
          budget: { title:'Budget', text:`Sets the planned target (limit) for a category/project/portfolio.`, required:['amount','portfolio_id'] },
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
          const [portfolios, projects, categories, vendors, entries] = await Promise.all([
            apiList('/api/portfolios'), apiList('/api/projects'), apiList('/api/categories'), apiList('/api/vendors'), apiList('/api/entries')
          ]);
          const portfolioMap = mapBy(portfolios);
          const portfolioOpts = portfolios.map(p=>({value:p.id,label:`${p.name}${p.fiscal_year ? ' • FY '+p.fiscal_year : ''}`}));
          const projOpts = projects.map(p=>{
            const portfolio = portfolioMap[p.portfolio_id];
            const portfolioLabel = portfolio ? `${portfolio.name}${portfolio.fiscal_year ? ' • FY '+portfolio.fiscal_year : ''}` : `Portfolio ${p.portfolio_id}`;
            return {value:p.id, label:`[${portfolioLabel}] ${p.name}`};
          });
          const catMap = mapBy(categories);
          const catOpts = categories.map(c=>({value:c.id, label:`${catPath(c, catMap)}${c.project_id ? ` (Project ${c.project_id})` : ''}`}));
          const vendorOpts = vendors.map(v=>({value:v.id,label:v.name}));

          content.innerHTML =
            card('Add Entry', `
              <div class="row two">
                <div>
                  <div class="section">
                    <div class="title">Basics <span class="hint">(date, kind, amount)</span></div>
                    <div class="row three">
                      ${field('date', labelFor('date','Date','Optional (YYYY-MM-DD).'), `<input class="input" type="date" name="date"/>`)}
                      ${field('kind', labelFor('kind','What are you adding?','Budget sets limits; PO/Unplanned/Adjustment count to actuals; Quote is informational.'), `<select name="kind">
                        <option value="budget">budget (sets target)</option>
                        <option value="quote">quote (informational)</option>
                        <option value="po">po (actual)</option>
                        <option value="unplanned">unplanned (actual)</option>
                        <option value="adjustment">adjustment (actual)</option>
                      </select>`)}
                      ${field('amount', labelFor('amount','Amount','Positive number; negative for adjustment credits.'), input('amount','1000'))}
                    </div>
                  </div>

                  <div class="section">
                    <div class="title">Scope</div>
                    <div class="row three">
                      ${field('portfolio_id', labelFor('portfolio_id','Portfolio','Primary portfolio charged.'), select('portfolio_id', portfolioOpts))}
                      ${field('project_id', labelFor('project_id','Project','Per-portfolio project (groups roll up across portfolios).'), select('project_id', projOpts))}
                      ${field('category_id', labelFor('category_id','Category (n-level)','Pick most specific leaf.'), select('category_id', catOpts))}
                    </div>
                  </div>

                  <div class="section">
                    <div class="title">Commercial</div>
                    <div class="row three">
                      ${field('vendor_id', labelFor('vendor_id','Vendor','Who provided the quote/PO.'), select('vendor_id', vendorOpts))}
                      ${field('quote_ref', labelFor('quote_ref','Quote Ref','For quotes.'), input('quote_ref','QT-0097'))}
                      ${field('po_number', labelFor('po_number','PO #','For POs.'), input('po_number','4500123456'))}
                    </div>
                  </div>

                  <div class="section">
                    <div class="title">Wrong Portfolio? <span class="hint">(flag to fix later)</span></div>
                    <div class="row two">
                      <div class="field">
                        ${labelFor('mischarged','Mark as mischarged','Check to flag this entry as charged to the wrong portfolio.')}
                        <input type="checkbox" name="mischarged"/>
                      </div>
                      ${field('intended_portfolio_id', labelFor('intended_portfolio_id','Intended Portfolio','Where it *should* be charged. Used in Ideal scenario.'), select('intended_portfolio_id', [{value:'',label:'(none)'}].concat(portfolioOpts)))}
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
                    <div class="title">Allocations <span class="hint">(optional)</span> <span class="info" data-tip="Split the amount across multiple portfolios. Sum must equal Amount.">i</span></div>
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
              'id','date','kind','amount','portfolio_id','project_id','category_id','vendor_id','po_number','quote_ref','mischarged','intended_portfolio_id','description'
            ], '/api/entries'));

          // Show/Hide intended portfolio when mischarged checked
          const misBox = content.querySelector('input[name=mischarged]');
          const intendedSel = content.querySelector('select[name=intended_portfolio_id]');
          if (misBox && intendedSel) {
            const sync = () => { intendedSel.parentElement.parentElement.style.display = misBox.checked ? '' : 'none'; };
            sync(); misBox.addEventListener('change', sync);
          }

          const allocsDiv = document.getElementById('allocs');
          const addAlloc = document.getElementById('addAlloc');
          if (addAlloc) addAlloc.onclick = () => {
            allocsDiv.insertAdjacentHTML('beforeend', `
              <div class="row four" data-row="1" style="margin-bottom:6px">
                ${field('alloc_portfolio', labelFor('alloc_portfolio','Alloc Portfolio','Portfolio receiving part of this amount.'), select('alloc_portfolio', portfolioOpts))}
                ${field('alloc_amount', labelFor('alloc_amount','Amount','Portion to this portfolio.'), input('alloc_amount',''))}
                <div class="field"><label>&nbsp;</label><button onclick="this.closest('[data-row]').remove()">Remove</button></div>
              </div>`);
          };

          const kindSel = content.querySelector('select[name=kind]');
          const markRequired = () => {
            const k = KIND_HELP[kindSel.value];
            const box = document.getElementById('kindHelp');
            if (box) box.outerHTML = helpBox(kindSel.value);
            content.querySelectorAll('.required').forEach(el=>el.classList.remove('required'));
            ['amount','portfolio_id','vendor_id','quote_ref','po_number'].forEach(n=>{
              const el = content.querySelector(`[for="${n}"]`);
              if (el) el.classList.remove('required');
            });
            k.required.forEach(name=>{
              const el = content.querySelector(`[for="${name}"]`);
              if (el) el.classList.add('required');
            });
          };
          if (kindSel) kindSel.onchange = markRequired;
          markRequired();

          const addBtn = document.getElementById('addEntry');
          if (addBtn) addBtn.onclick = async ()=>{
            try {
              const get = name => {
                const el = content.querySelector(`[name=${name}]`);
                if (!el) return null;
                if (el.type === 'checkbox') return !!el.checked;
                return el.value === '' ? null : el.value;
              };
              const allocations = [...allocsDiv.querySelectorAll('[data-row]')].map(div => ({
                portfolio_id: Number(div.querySelector('select[name=alloc_portfolio]').value),
                amount: Number(div.querySelector('input[name=alloc_amount]').value)
              }));
  
              const body = {
                date: get('date'),
                kind: String(get('kind') || 'budget'),
                amount: Number(get('amount')),
                description: get('description'),
                portfolio_id: get('portfolio_id') ? Number(get('portfolio_id')) : null,
                project_id: get('project_id') ? Number(get('project_id')) : null,
                category_id: get('category_id') ? Number(get('category_id')) : null,
                vendor_id: get('vendor_id') ? Number(get('vendor_id')) : null,
                po_number: get('po_number'),
                quote_ref: get('quote_ref'),
                mischarged: get('mischarged') || false,
                intended_portfolio_id: get('intended_portfolio_id') ? Number(get('intended_portfolio_id')) : null,
                allocations: allocations.length? allocations : null,
                tags: (get('tags')||'').split(',').map(s=>s.trim()).filter(Boolean) || null
              };
  
              const req = KIND_HELP[body.kind].required;
              const missing = [];
              req.forEach(name=>{
                const v = body[name];
                const ok = (typeof v === 'number') ? !Number.isNaN(v) : !!v;
                if(!ok){ missing.push(name); const el = content.querySelector(`[name=${name}]`); if(el) el.classList.add('invalid'); }
              });
              if(missing.length){
                alert(`Missing required fields for kind="${body.kind}": ${missing.join(', ')}`);
                return;
              }
              if (body.mischarged && !body.intended_portfolio_id) {
                alert('Please choose the intended portfolio for a mischarged entry.');
                return;
              }
              if (body.allocations && body.allocations.length){
                const sum = body.allocations.reduce((a,b)=>a + (Number(b.amount)||0), 0);
                if (Math.abs(sum - body.amount) > 1e-6){
                  alert(`Allocations must sum to Amount (${body.amount}). Current total: ${sum}`);
                  return;
                }
              }
  
              await apiCreate('/api/entries', body);
              renderEntries();
            } catch(e) { showError(e); }
          };
        }
  
        // ---- Pivots & Health ----
        let chartInstance;
        async function renderPivots(){
          const [portfolios, categories] = await Promise.all([apiList('/api/portfolios'), apiList('/api/categories')]);
          const portfolioOpts = [{value:'',label:'(All Portfolios)'}].concat(portfolios.map(c=>({value:c.id,label:`${c.name}${c.fiscal_year ? ' • FY '+c.fiscal_year : ''}`})));
          const catMap = mapBy(categories);
  
          const ui = document.createElement('div');
          ui.innerHTML = `
            <div class="card">
              <h3>Pivot & Health</h3>
              <div class="row three">
                <div class="field">
                  ${labelFor('scenario','Scenario','Actual = as charged today; Ideal = re-map mischarged entries to intended portfolios.')}
                  <select name="scenario">
                    <option value="actual">Actual</option>
                    <option value="ideal">Ideal</option>
                  </select>
                </div>
                <div class="field">
                  ${labelFor('by','Pivot By','Choose grouping for the pivot table below.')}
                  <select name="by">
                    <option value="">Detailed (portfolio+project+category+vendor+kind)</option>
                    <option value="portfolio">By Portfolio</option>
                    <option value="project">By Project</option>
                    <option value="group">By Project Group</option>
                    <option value="category">By Category</option>
                    <option value="vendor">By Vendor</option>
                    <option value="kind">By Kind</option>
                  </select>
                </div>
                <div class="field">
                  ${labelFor('portfolioFilter','Portfolio (for Category Health)','Pick a portfolio to see category-level health.')}
                  ${select('portfolioFilter', portfolioOpts)}
                </div>
              </div>
            </div>
            <div id="pv"></div>
            <div class="card"><canvas id="chart"></canvas></div>
            <div id="health"></div>
          `;
          content.innerHTML = ui.outerHTML;
  
          async function draw(){
            try {
              const scenario = content.querySelector('select[name=scenario]').value || 'actual';
              const by = content.querySelector('select[name=by]').value;
              const portfolioFilter = content.querySelector('select[name=portfolioFilter]').value;
  
              // Pivot
              const rows = await apiList(`/api/pivot/summary${by ? '?by=' + by : ''}${by ? '&' : '?'}scenario=${scenario}`);
              document.getElementById('pv').innerHTML = card('Pivot Summary', table(rows, Object.keys(rows[0] || {})));
  
              // Chart totals
              const totals = {};
              rows.forEach(r => {
                const label = by ? Object.values(r)[0] : r.kind;
                const k = String(label ?? 'n/a');
                totals[k] = (totals[k]||0) + (r.total||0);
              });
              const labels = Object.keys(totals), data = Object.values(totals);
              const ctx = document.getElementById('chart');
              if(chartInstance) chartInstance.destroy();
              chartInstance = new Chart(ctx, { type: 'bar', data: { labels, datasets: [{ label: 'Totals', data }] }, options: { responsive:true } });
  
              // Health by portfolio
              const healthPortfolio = await apiList(`/api/status/health?level=portfolio&scenario=${scenario}`);
              const portfolioRows = healthPortfolio.map(h => {
                const portfolio = portfolios.find(p=>p.id === h.portfolio_id);
                const name = portfolio ? `${portfolio.name}${portfolio.fiscal_year? ' • FY '+portfolio.fiscal_year:''}` : h.portfolio_id;
                return { name, budget: h.budget || 0, actual: h.actual || 0, variance: (h.actual||0)-(h.budget||0), variance_pct: h.variance_pct ?? null, status: h.status };
              });
              const portfolioTable = table(portfolioRows, ['name','budget','actual','variance','variance_pct','status']);
              // Health by Category (if chosen Portfolio)
              let catTable = '<div class="card"><em>Select a portfolio above to see category health.</em></div>';
              if (portfolioFilter) {
                const healthCat = await apiList(`/api/status/health?level=category&portfolio_id=${portfolioFilter}&scenario=${scenario}`);
                const catRows = healthCat.map(h => {
                  const path = catMap[h.category_id] ? catPath(catMap[h.category_id], catMap) : '(none)';
                  return { category: path, budget: h.budget||0, actual: h.actual||0, variance: (h.actual||0)-(h.budget||0), variance_pct: h.variance_pct ?? null, status: h.status };
                });
                catTable = table(catRows, ['category','budget','actual','variance','variance_pct','status']);
                catTable = card('Health — By Category (selected portfolio)', catTable);
              }
              document.getElementById('health').innerHTML = card('Health — By Portfolio', portfolioTable) + catTable;
            } catch (e) { showError(e); }
          }
  
          content.querySelector('select[name=scenario]').onchange = draw;
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
            + card('All Tags', table(tags, ['id','name'], '/api/tags'));
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
  
        const firstTab = nav.querySelector('button[data-tab]');
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
  