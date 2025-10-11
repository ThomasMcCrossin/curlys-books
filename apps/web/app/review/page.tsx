'use client';

import { useState, useEffect } from 'react';

// Types matching backend Reviewable schema
interface SourceRef {
  table: string;
  schema?: string;
  pk: string;
}

interface Reviewable {
  id: string;
  type: string;
  entity: 'corp' | 'soleprop';
  created_at: string;
  source_ref: SourceRef;
  summary: string;
  details: Record<string, any>;
  confidence: number | null;
  requires_review: boolean;
  status: 'pending' | 'approved' | 'rejected' | 'snoozed' | 'needs_info' | 'posted';
  assignee?: string;
  vendor?: string;
  date?: string;
  amount?: number;
  age_hours?: number;
}

interface ReviewMetrics {
  entity: string;
  pending_count: number;
  approved_today: number;
  rejected_today: number;
  confidence_bands: {
    '<0.80': number;
    '0.80-0.90': number;
    '≥0.90': number;
  };
}

export default function ReviewQueuePage() {
  const [items, setItems] = useState<Reviewable[]>([]);
  const [stats, setStats] = useState<ReviewMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [entityFilter, setEntityFilter] = useState<string>('');
  const [typeFilter, setTypeFilter] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('pending');
  const [confidenceFilter, setConfidenceFilter] = useState<number>(80);

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

  // Fetch review queue
  useEffect(() => {
    fetchReviewQueue();
    fetchStats();
  }, [entityFilter, typeFilter, statusFilter, confidenceFilter]);

  const fetchReviewQueue = async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      if (entityFilter) params.append('entity', entityFilter);
      if (typeFilter) params.append('type', typeFilter);
      if (statusFilter) params.append('status', statusFilter);
      params.append('max_confidence', (confidenceFilter / 100).toString());
      params.append('limit', '50');

      const response = await fetch(`${apiUrl}/api/v1/review/tasks?${params}`);
      if (!response.ok) throw new Error('Failed to fetch review queue');

      const data = await response.json();
      setItems(data.items || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  const fetchStats = async () => {
    try {
      const response = await fetch(`${apiUrl}/api/v1/review/metrics`);
      if (!response.ok) throw new Error('Failed to fetch stats');

      const data = await response.json();
      setStats(data);
    } catch (err) {
      console.error('Failed to fetch stats:', err);
    }
  };

  const handleApprove = async (id: string) => {
    try {
      const response = await fetch(`${apiUrl}/api/v1/review/tasks/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'approve',
          performed_by: 'web_ui_user'
        }),
      });

      if (!response.ok) throw new Error('Failed to approve item');

      // Refresh queue
      await fetchReviewQueue();
      await fetchStats();
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to approve');
    }
  };

  const handleReject = async (id: string, reason: string) => {
    try {
      const response = await fetch(`${apiUrl}/api/v1/review/tasks/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'reject',
          reason: reason,
          performed_by: 'web_ui_user'
        }),
      });

      if (!response.ok) throw new Error('Failed to reject item');

      await fetchReviewQueue();
      await fetchStats();
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to reject');
    }
  };

  const handleCorrect = async (id: string, payload: Record<string, any>) => {
    try {
      const response = await fetch(`${apiUrl}/api/v1/review/tasks/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'correct',
          payload: payload,
          performed_by: 'web_ui_user'
        }),
      });

      if (!response.ok) throw new Error('Failed to save corrections');

      await fetchReviewQueue();
      await fetchStats();
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to save corrections');
    }
  };

  const formatConfidence = (confidence: number | null) => {
    if (confidence === null) return 'N/A';
    return `${(confidence * 100).toFixed(0)}%`;
  };

  const getConfidenceColor = (confidence: number | null) => {
    if (confidence === null) return 'text-gray-400';
    if (confidence >= 0.9) return 'text-green-600';
    if (confidence >= 0.8) return 'text-yellow-600';
    return 'text-red-600';
  };

  return (
    <div className="min-h-screen bg-gray-50 p-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900">Review Queue</h1>
          <p className="text-gray-600 mt-2">
            Review and approve AI-categorized items that need your attention
          </p>
        </div>

        {/* Stats Cards */}
        {stats && (
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
            <div className="bg-white p-6 rounded-lg shadow">
              <div className="text-sm text-gray-600">Total Pending</div>
              <div className="text-3xl font-bold text-gray-900 mt-2">
                {stats.pending_count}
              </div>
            </div>
            <div className="bg-white p-6 rounded-lg shadow">
              <div className="text-sm text-gray-600">Low Confidence</div>
              <div className="text-3xl font-bold text-red-600 mt-2">
                {stats.confidence_bands['<0.80'] || 0}
              </div>
            </div>
            <div className="bg-white p-6 rounded-lg shadow">
              <div className="text-sm text-gray-600">Medium Confidence</div>
              <div className="text-3xl font-bold text-yellow-600 mt-2">
                {stats.confidence_bands['0.80-0.90'] || 0}
              </div>
            </div>
            <div className="bg-white p-6 rounded-lg shadow">
              <div className="text-sm text-gray-600">Approved Today</div>
              <div className="text-3xl font-bold text-green-600 mt-2">
                {stats.approved_today}
              </div>
            </div>
          </div>
        )}

        {/* Filters */}
        <div className="bg-white p-6 rounded-lg shadow mb-8">
          <h2 className="text-lg font-semibold mb-4">Filters</h2>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Entity
              </label>
              <select
                value={entityFilter}
                onChange={(e) => setEntityFilter(e.target.value)}
                className="w-full border border-gray-300 rounded px-3 py-2"
              >
                <option value="">All Entities</option>
                <option value="corp">Corp (Canteen)</option>
                <option value="soleprop">Sole Prop (Sports)</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Type
              </label>
              <select
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
                className="w-full border border-gray-300 rounded px-3 py-2"
              >
                <option value="">All Types</option>
                <option value="categorization">Categorization</option>
                <option value="receipt">Receipt</option>
                <option value="transaction">Transaction</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Status
              </label>
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="w-full border border-gray-300 rounded px-3 py-2"
              >
                <option value="">All Statuses</option>
                <option value="pending">Pending</option>
                <option value="approved">Approved</option>
                <option value="rejected">Rejected</option>
                <option value="snoozed">Snoozed</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Max Confidence: {confidenceFilter}%
              </label>
              <input
                type="range"
                min="0"
                max="100"
                value={confidenceFilter}
                onChange={(e) => setConfidenceFilter(Number(e.target.value))}
                className="w-full"
              />
            </div>
          </div>
        </div>

        {/* Error State */}
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-8">
            <strong>Error:</strong> {error}
          </div>
        )}

        {/* Loading State */}
        {loading && (
          <div className="text-center py-12">
            <div className="text-gray-600">Loading review queue...</div>
          </div>
        )}

        {/* Empty State */}
        {!loading && items.length === 0 && (
          <div className="bg-white rounded-lg shadow p-12 text-center">
            <div className="text-gray-400 text-5xl mb-4">✓</div>
            <h3 className="text-xl font-semibold text-gray-700 mb-2">
              All caught up!
            </h3>
            <p className="text-gray-600">
              No items need review at this time.
            </p>
          </div>
        )}

        {/* Review Items */}
        {!loading && items.length > 0 && (
          <div className="space-y-4">
            {items.map((item) => (
              <div
                key={item.id}
                className="bg-white rounded-lg shadow p-6 hover:shadow-lg transition-shadow"
              >
                <div className="flex items-start justify-between mb-4 gap-6">
                  {/* Receipt Image */}
                  {item.details?.receipt_id && (
                    <div className="flex-shrink-0 w-96">
                      <div className="sticky top-4">
                        <div className="bg-blue-50 border border-blue-200 rounded-t-lg px-3 py-2">
                          <div className="text-xs font-medium text-blue-900">
                            Receipt #{item.details.receipt_id.substring(0, 8)}...
                          </div>
                          {item.details.line_number && (
                            <div className="text-xs text-blue-700 mt-1 flex items-center gap-2">
                              <span className="inline-block w-2 h-2 bg-red-500 rounded-full animate-pulse"></span>
                              Line {item.details.line_number}
                              {item.details.description && (
                                <span className="text-gray-600">- Look for: "{item.details.description.substring(0, 30)}..."</span>
                              )}
                            </div>
                          )}
                        </div>
                        <div className="relative bg-gray-100">
                          <img
                            src={`${apiUrl}/api/v1/receipts/${item.details.receipt_id}/file?type=normalized`}
                            alt="Receipt"
                            className="w-full h-auto rounded-b-lg border-2 border-gray-300 cursor-zoom-in hover:border-blue-400 transition-colors"
                            onClick={(e) => {
                              // Open in new tab for full size view
                              window.open(`${apiUrl}/api/v1/receipts/${item.details.receipt_id}/file`, '_blank');
                            }}
                            onError={(e) => {
                              // Fallback to original if normalized doesn't exist
                              const target = e.currentTarget;
                              if (!target.src.includes('type=original')) {
                                target.src = `${apiUrl}/api/v1/receipts/${item.details.receipt_id}/file?type=original`;
                              } else {
                                target.style.display = 'none';
                              }
                            }}
                          />
                          {/* Bounding box highlight from Textract */}
                          {item.details.bounding_box && (
                            <div
                              className="absolute border-4 border-red-500 bg-red-500 bg-opacity-20 pointer-events-none animate-pulse"
                              style={{
                                left: `${item.details.bounding_box.left * 100}%`,
                                top: `${item.details.bounding_box.top * 100}%`,
                                width: `${item.details.bounding_box.width * 100}%`,
                                height: `${item.details.bounding_box.height * 100}%`,
                              }}
                            >
                              <div className="absolute -top-6 left-0 bg-red-500 text-white px-2 py-1 rounded text-xs font-bold">
                                Problem Line
                              </div>
                            </div>
                          )}
                          {/* Fallback visual indicator if no bounding box */}
                          {!item.details.bounding_box && item.details.line_number && (
                            <div className="absolute bottom-4 left-0 right-0 flex justify-center pointer-events-none">
                              <div className="bg-red-500 text-white px-3 py-1 rounded-full text-xs font-bold shadow-lg animate-bounce">
                                ⬇ Line {item.details.line_number} Near Bottom ⬇
                              </div>
                            </div>
                          )}
                        </div>
                        <div className="mt-2 text-xs text-gray-600 text-center space-y-1">
                          <div>🔍 Click image to view full size</div>
                          <div className="text-blue-600">💡 Look near the bottom of receipt for this line</div>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Item Details */}
                  <div className="flex-1">
                    <div className="flex items-center gap-3 mb-2">
                      <span className="px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm font-medium">
                        {item.type}
                      </span>
                      <span className="px-3 py-1 bg-gray-100 text-gray-800 rounded-full text-sm">
                        {item.entity === 'corp' ? 'Corp' : 'Sole Prop'}
                      </span>
                      <span className={`font-semibold ${getConfidenceColor(item.confidence)}`}>
                        {formatConfidence(item.confidence)} confidence
                      </span>
                    </div>

                    <h3 className="text-lg font-semibold text-gray-900 mb-1">
                      {item.summary}
                    </h3>

                    <div className="text-sm text-gray-600 space-y-1">
                      {item.vendor && <div>Vendor: {item.vendor}</div>}
                      {item.date && <div>Date: {new Date(item.date).toLocaleDateString()}</div>}
                      {item.amount !== undefined && <div>Amount: ${Number(item.amount).toFixed(2)}</div>}
                    </div>

                    {item.details && (item.details.product_category || item.details.account_code) && (
                      <div className="mt-3 p-3 bg-yellow-50 border border-yellow-200 rounded">
                        <div className="text-sm font-medium text-yellow-900">AI Suggestion:</div>
                        <div className="text-sm text-yellow-800 mt-1">
                          {item.details.product_category && <div>Category: {item.details.product_category}</div>}
                          {item.details.account_code && <div>Account: {item.details.account_code}</div>}
                          {item.details.description && <div>Item: {item.details.description}</div>}
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                {/* Actions */}
                <div className="flex gap-3 mt-4 pt-4 border-t">
                  <button
                    onClick={() => handleApprove(item.id)}
                    className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 font-medium"
                  >
                    ✓ Approve
                  </button>
                  <button
                    onClick={() => {
                      const reason = prompt('Rejection reason:');
                      if (reason) handleReject(item.id, reason);
                    }}
                    className="px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700 font-medium"
                  >
                    ✗ Reject
                  </button>
                  <button
                    onClick={() => {
                      // TODO: Open correction modal
                      alert('Correction modal coming soon');
                    }}
                    className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 font-medium"
                  >
                    ✎ Correct
                  </button>
                  <button
                    className="px-4 py-2 bg-gray-200 text-gray-700 rounded hover:bg-gray-300 font-medium"
                  >
                    Details →
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
