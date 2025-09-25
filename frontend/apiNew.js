(function () {
  const defaultHeaders = { 'Content-Type': 'application/json' };

  function toQuery(params) {
    if (!params) return '';
    const pairs = Object.entries(params)
      .filter(([, value]) => value !== undefined && value !== null && value !== '')
      .map(([key, value]) => {
        if (value instanceof Date) {
          value = value.toISOString().slice(0, 10);
        }
        return encodeURIComponent(key) + '=' + encodeURIComponent(value);
      });
    return pairs.length ? '?' + pairs.join('&') : '';
  }

  async function request(path, { method = 'GET', params, body } = {}) {
    const url = path + toQuery(params);
    const options = { method, headers: defaultHeaders };
    if (body !== undefined) {
      options.body = typeof body === 'string' ? body : JSON.stringify(body);
    }
    const resp = await fetch(url, options);
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(text || resp.statusText);
    }
    const contentType = resp.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      return resp.json();
    }
    return resp.text();
  }

  const api = {
    getBudgetCommitActual: (params) => request('/api/views/budget-commit-actual', { params }),
    getOpenCommitments: (params) => request('/api/views/open-commitments', { params }),
    getVendorSpendAging: (params) => request('/api/views/vendor-spend-aging', { params }),
    getOpenItems: (params) => request('/api/views/open-items', { params }),
    getFuturePlan: (params) => request('/api/views/future-plan', { params }),
    getToCarClosure: (params) => request('/api/views/to-car-closure', { params }),
    postReallocate: (body) => request('/api/reallocate', { method: 'POST', body }),
    listPaymentSchedules: (params) => request('/api/payment-schedules', { params }),
    generatePaymentSchedule: (body) => request('/api/payment-schedules/generate', { method: 'POST', body }),
    updatePaymentSchedule: (id, body) => request(`/api/payment-schedules/${id}`, { method: 'PUT', body }),
    listDeliverables: (params) => request('/api/deliverables', { params }),
    listCheckpointTypes: () => request('/api/deliverables/checkpoints'),
    applyDeliverablesTemplate: (body) => request('/api/deliverables/template/apply', { method: 'POST', body }),
    createLot: (poLineId, body) => request(`/api/po-lines/${poLineId}/lots`, { method: 'POST', body }),
    updateMilestone: (id, body) => request(`/api/milestones/${id}`, { method: 'PUT', body }),
    listFxRates: (params) => request('/api/fx-rates', { params }),
    createFxRate: (body) => request('/api/fx-rates', { method: 'POST', body }),
    updateFxRate: (id, body) => request(`/api/fx-rates/${id}`, { method: 'PUT', body }),
    deleteFxRate: (id) => request(`/api/fx-rates/${id}`, { method: 'DELETE' }),
    saveReport: (body) => request('/api/reports', { method: 'POST', body }),
    listReports: () => request('/api/reports'),
    runReport: (id) => request(`/api/report/run/${id}`),
    runAdhocReport: (config) => request('/api/report/run', { method: 'POST', body: { json_config: config } }),
  };

  if (typeof window !== 'undefined') {
    window.ApiNew = api;
  }
})();
