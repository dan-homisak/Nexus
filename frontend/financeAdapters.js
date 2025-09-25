// Minimal adapters for the new finance endpoints. Existing screens continue to use
// legacy endpoints; these helpers let us wire the new routes incrementally.
export async function fetchFundingSources() {
  const resp = await fetch('/api/funding-sources');
  if (!resp.ok) throw new Error('Failed to load funding sources');
  return resp.json();
}

export async function createPurchaseOrder(payload) {
  const resp = await fetch('/api/purchase-orders', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) throw new Error('Failed to create purchase order');
  return resp.json();
}

export async function runSavedReport(id) {
  const resp = await fetch(`/api/report/run/${id}`);
  if (!resp.ok) throw new Error('Failed to execute saved report');
  return resp.json();
}
