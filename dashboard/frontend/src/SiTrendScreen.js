// SiTrendScreen.js - Non-crisis SI trend for one participant.
// Staff-facing signal only: it never triggers outreach or paging.

import React, { useState, useEffect, useCallback } from 'react';
import { ChevronLeft, TrendingUp, Minus, HelpCircle, RefreshCw } from 'lucide-react';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine,
} from 'recharts';
import { API_BASE_URL, authFetch } from './SocialScope';

export const TREND_STYLE = {
  rising:       { label: 'Rising',            cls: 'bg-orange-100 text-orange-800 border-orange-300', Icon: TrendingUp },
  stable:       { label: 'Stable',            cls: 'bg-gray-100 text-gray-600 border-gray-300',       Icon: Minus },
  insufficient: { label: 'Insufficient data', cls: 'bg-gray-50 text-gray-400 border-gray-200',        Icon: HelpCircle },
};

// Compact badge used on the overview table and the participant page.
export const SiTrendBadge = ({ trend, onClick }) => {
  const s = TREND_STYLE[trend?.status] || TREND_STYLE.insufficient;
  const { Icon } = s;
  const title = trend?.status === 'rising'
    ? `SI composite rising: ${trend.slopePerDay > 0 ? '+' : ''}${trend.slopePerDay}/day, last week +${trend.levelDelta} vs prior week`
    : trend?.status === 'stable'
      ? `SI composite stable (last-7 mean ${trend.last7Mean ?? '—'})`
      : 'Not enough check-ins in the last 7 days to assess a trend';
  return (
    <button onClick={onClick} title={title}
      className={`ml-2 inline-flex items-center gap-1 px-1.5 py-0.5 text-xs rounded border ${s.cls} hover:opacity-80`}>
      <Icon size={12} />
      {trend?.status === 'rising' ? 'SI ↑' : trend?.status === 'stable' ? 'SI —' : 'SI ?'}
    </button>
  );
};

const SiTrendScreen = ({ participantId, goToParticipantView }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const res = await authFetch(`${API_BASE_URL}/api/participant/${participantId}/si-trend`);
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Failed to load');
      setData(await res.json());
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, [participantId]);

  useEffect(() => { load(); }, [load]);

  const s = TREND_STYLE[data?.status] || TREND_STYLE.insufficient;
  const { Icon } = s;
  const series = (data?.series || []).map(p => ({ ...p, label: p.date.slice(5) }));
  const rule = data?.rule || {};

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <button onClick={() => goToParticipantView(participantId)}
          className="flex items-center gap-1 text-blue-600 hover:text-blue-800 text-sm font-medium">
          <ChevronLeft size={18} /> Back to {participantId}
        </button>
        <button onClick={load} className="p-1.5 rounded hover:bg-white text-gray-500" title="Refresh">
          <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      <div className="bg-white rounded-lg shadow overflow-hidden">
        <div className="px-6 py-4 border-b bg-gradient-to-r from-orange-50 to-amber-50">
          <h1 className="text-xl font-bold text-gray-800 flex items-center gap-2">
            <TrendingUp size={22} className="text-orange-600" /> SI Trend — Participant {participantId}
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Non-crisis signal from recent check-ins. Does not page anyone or contact the participant.
          </p>
        </div>

        <div className="p-6 space-y-6">
          {error && <div className="text-red-600 text-sm">Error: {error}</div>}
          {loading && !data && <div className="text-gray-500 text-sm">Loading…</div>}

          {data && (
            <>
              <div className="flex flex-wrap items-center gap-3">
                <span className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-sm font-semibold ${s.cls}`}>
                  <Icon size={16} /> {s.label}
                </span>
                {data.status === 'rising' && (
                  <span className="text-sm text-orange-800">
                    Composite climbing {data.slopePerDay > 0 ? '+' : ''}{data.slopePerDay} points/day; last week averaged {data.last7Mean}, up {data.levelDelta} from {data.prior7Mean}.
                  </span>
                )}
                {data.status === 'stable' && (
                  <span className="text-sm text-gray-600">
                    Last-7 mean {data.last7Mean ?? '—'}{data.prior7Mean != null ? `, prior-7 mean ${data.prior7Mean}` : ''}
                    {data.noPriorWeek ? ' — first week, no prior week to compare.' : '.'}
                  </span>
                )}
                {data.status === 'insufficient' && (
                  <span className="text-sm text-gray-500">
                    {data.checkins7 ?? 0} check-ins across {data.days7 ?? 0} days in the last 7 (needs {rule.minCheckins7d} across {rule.minDays7d}).
                  </span>
                )}
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                {[['Slope / day', data.slopePerDay], ['Last 7 mean', data.last7Mean],
                  ['Prior 7 mean', data.prior7Mean], ['Check-ins (7d)', `${data.checkins7} on ${data.days7} days`]]
                  .map(([k, v]) => (
                    <div key={k} className="bg-gray-50 rounded p-3">
                      <div className="text-xs text-gray-500">{k}</div>
                      <div className="text-lg font-semibold text-gray-800">{v ?? '—'}</div>
                    </div>
                  ))}
              </div>

              <div>
                <div className="text-sm font-semibold text-gray-700 mb-2">Daily SI composite, last 14 days (0–100)</div>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={series} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
                      <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                      <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
                      <Tooltip formatter={(v, n, p) => [v == null ? 'no check-ins' : `${v} (${p.payload.n} check-in${p.payload.n === 1 ? '' : 's'})`, 'composite']} />
                      <ReferenceLine y={30} stroke="#f59e0b" strokeDasharray="4 4" label={{ value: 'alert threshold', fontSize: 10, fill: '#b45309', position: 'insideTopRight' }} />
                      <Line type="monotone" dataKey="mean" stroke="#ea580c" strokeWidth={2} dot={{ r: 3 }} connectNulls={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="text-xs text-gray-500 border-t pt-3 space-y-1">
                <div><b>Composite:</b> {rule.composite}.</div>
                <div><b>Rising when:</b> 7-day slope &gt; +{rule.slopeMinPerDay}/day <i>and</i> last-7 mean exceeds prior-7 mean by ≥ {rule.levelDeltaMin}, with ≥ {rule.minCheckins7d} check-ins across ≥ {rule.minDays7d} days.</div>
                <div>Timezone {data.tz}. Computed {data.computedAt ? new Date(data.computedAt).toLocaleString('en-US', { timeZone: 'America/New_York' }) : ''} ET.</div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default SiTrendScreen;
