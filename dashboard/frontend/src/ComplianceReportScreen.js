// ComplianceReportScreen.js - Study-wide compliance + compensation for one participant.
// Read-only view: EMAs credited within 4 h of their prompt, weekly app use,
// REDCap completions, and the dollars each line earns.

import React, { useState, useEffect, useCallback } from 'react';
import { ChevronLeft, DollarSign, Download, RefreshCw, CheckCircle, XCircle, Clock } from 'lucide-react';
import { API_BASE_URL, authFetch } from './SocialScope';

const money = (v) => `$${Number(v || 0).toFixed(2)}`;
const fmtDate = (iso) => iso ? new Date(iso).toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '—';

const Done = ({ ok, at }) => ok
  ? <span className="inline-flex items-center gap-1 text-green-700 text-sm"><CheckCircle size={14} /> Complete{at ? ` · ${fmtDate(at)}` : ''}</span>
  : <span className="inline-flex items-center gap-1 text-gray-500 text-sm"><XCircle size={14} /> Not complete</span>;

const ComplianceReportScreen = ({ participantId, goToParticipantView, goToDayView }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showDays, setShowDays] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const res = await authFetch(`${API_BASE_URL}/api/participant/${participantId}/compliance-report`);
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Failed to load');
      setData(await res.json());
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, [participantId]);

  useEffect(() => { load(); }, [load]);

  const downloadCsv = async () => {
    try {
      const res = await authFetch(`${API_BASE_URL}/api/participant/${participantId}/compliance-report.csv`);
      const text = await res.text();
      const blob = new Blob([text], { type: 'text/csv' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `compliance_${participantId}_${(data?.today || '').replace(/-/g, '')}.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) { setError(e.message); }
  };

  const comp = data?.compensation; const ema = data?.ema; const app = data?.appUse; const rc = data?.redcap;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <button onClick={() => goToParticipantView(participantId)}
          className="flex items-center gap-1 text-blue-600 hover:text-blue-800 text-sm font-medium">
          <ChevronLeft size={18} /> Back to {participantId}
        </button>
        <div className="flex items-center gap-2">
          <button onClick={downloadCsv} disabled={!data?.available}
            className="flex items-center gap-1 px-3 py-1.5 text-sm bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-40">
            <Download size={14} /> CSV
          </button>
          <button onClick={load} className="p-1.5 rounded hover:bg-white text-gray-500" title="Refresh">
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      <div className="bg-white rounded-lg shadow overflow-hidden">
        <div className="px-6 py-4 border-b bg-gradient-to-r from-green-50 to-emerald-50">
          <h1 className="text-xl font-bold text-gray-800 flex items-center gap-2">
            <DollarSign size={22} className="text-green-700" /> Compliance &amp; Compensation — Participant {participantId}
          </h1>
          {data?.available && (
            <p className="text-sm text-gray-500 mt-1">
              Study day {data.studyDay} of 90 · {data.studyStart} → {data.studyEnd} · prompts {data.schedule.promptTimes.join(' / ')} {data.schedule.tz}
              {data.schedule.source === 'default' && <span className="ml-1 text-amber-700">(device never logged a schedule — study default assumed)</span>}
            </p>
          )}
        </div>

        <div className="p-6 space-y-8">
          {error && <div className="text-red-600 text-sm">Error: {error}</div>}
          {loading && !data && <div className="text-gray-500 text-sm">Loading…</div>}
          {data && !data.available && <div className="text-amber-700 text-sm">{data.error}</div>}

          {data?.available && (
            <>
              {/* Compensation */}
              <section>
                <h2 className="text-sm font-semibold text-gray-700 mb-2">Compensation to date</h2>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 text-gray-600">
                      <tr><th className="text-left px-3 py-2">Item</th><th className="text-right px-3 py-2">Count</th><th className="text-right px-3 py-2">Rate</th><th className="text-right px-3 py-2">Earned</th><th className="text-right px-3 py-2">Max</th><th className="text-left px-3 py-2">Note</th></tr>
                    </thead>
                    <tbody className="divide-y">
                      {comp.lines.map(l => (
                        <tr key={l.item} className={l.max === 0 ? 'text-gray-400' : ''}>
                          <td className="px-3 py-2">{l.item}</td>
                          <td className="px-3 py-2 text-right">{l.count}</td>
                          <td className="px-3 py-2 text-right">{l.unit ? money(l.unit) : '—'}</td>
                          <td className="px-3 py-2 text-right font-medium">{money(l.amount)}</td>
                          <td className="px-3 py-2 text-right">{l.max ? money(l.max) : '—'}</td>
                          <td className="px-3 py-2 text-xs">{l.note || ''}</td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot className="bg-green-50 font-semibold">
                      <tr><td className="px-3 py-2" colSpan={3}>Total earned to date</td><td className="px-3 py-2 text-right text-green-800">{money(comp.earned)}</td><td className="px-3 py-2 text-right">{money(comp.maxPossible)}</td><td /></tr>
                    </tfoot>
                  </table>
                </div>
              </section>

              {/* EMA */}
              <section>
                <div className="flex items-center justify-between mb-2">
                  <h2 className="text-sm font-semibold text-gray-700">Daily check-ins (EMA)</h2>
                  <button onClick={() => setShowDays(s => !s)} className="text-xs text-blue-600 hover:underline">{showDays ? 'Hide' : 'Show'} day-by-day</button>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-sm">
                  {[['Credited (paid)', ema.creditedPaid], ['Expected so far', ema.expectedToDate],
                    ['Credit rate', ema.rate != null ? `${Math.round(ema.rate * 100)}%` : '—'],
                    ['Completed total', ema.completed], ['Off-window / duplicate', ema.offWindow]].map(([k, v]) => (
                    <div key={k} className="bg-gray-50 rounded p-3"><div className="text-xs text-gray-500">{k}</div><div className="text-lg font-semibold text-gray-800">{v}</div></div>
                  ))}
                </div>
                <p className="text-xs text-gray-500 mt-2">A check-in is credited to the most recent prompt it follows within {comp.rules.emaCreditHours} hours; one credit per window; $1 each up to {comp.rules.emaCap}.</p>
                {showDays && (
                  <div className="mt-3 max-h-80 overflow-y-auto border rounded">
                    <table className="w-full text-xs">
                      <thead className="bg-gray-50 sticky top-0"><tr><th className="text-left px-2 py-1">Date</th><th className="text-left px-2 py-1">Prompts (✓ credited)</th><th className="text-right px-2 py-1">Credited</th></tr></thead>
                      <tbody className="divide-y">
                        {ema.days.slice().reverse().map(d => (
                          <tr key={d.date} className="hover:bg-blue-50 cursor-pointer" onClick={() => goToDayView && goToDayView(participantId, d.date)}>
                            <td className="px-2 py-1 text-blue-600">{d.date}</td>
                            <td className="px-2 py-1">{d.prompts.map(p => (
                              <span key={p.time} className={`inline-block mr-2 ${p.credited ? 'text-green-700 font-medium' : p.fired ? 'text-gray-400 line-through' : 'text-gray-300'}`} title={p.completedAt ? `completed ${fmtDate(p.completedAt)}` : p.fired ? 'missed' : 'not yet fired'}>{p.credited ? '✓' : ''}{p.time}</span>
                            ))}</td>
                            <td className="px-2 py-1 text-right">{d.credited}/{d.expected}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>

              {/* Weekly app use */}
              <section>
                <h2 className="text-sm font-semibold text-gray-700 mb-2">Weekly app use — $1.50 per qualifying week (≥ {comp.rules.appWeekMinActiveDays} active days and ≥ {comp.rules.appWeekMinScreenshots} screenshots)</h2>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 text-gray-600"><tr><th className="text-left px-3 py-2">Week</th><th className="text-left px-3 py-2">Dates</th><th className="text-right px-3 py-2">Active days</th><th className="text-right px-3 py-2">Screenshots</th><th className="text-right px-3 py-2">Reddit / X</th><th className="text-left px-3 py-2">Status</th></tr></thead>
                    <tbody className="divide-y">
                      {app.weeks.filter(w => w.started).map(w => (
                        <tr key={w.week}>
                          <td className="px-3 py-2">{w.week}{w.days < 7 ? <span className="text-xs text-gray-400"> ({w.days}d)</span> : ''}</td>
                          <td className="px-3 py-2 text-gray-600">{w.start} → {w.end}</td>
                          <td className={`px-3 py-2 text-right ${w.activeDays >= comp.rules.appWeekMinActiveDays ? 'text-green-700' : 'text-red-600'}`}>{w.activeDays}</td>
                          <td className={`px-3 py-2 text-right ${w.screenshots >= comp.rules.appWeekMinScreenshots ? 'text-green-700' : 'text-red-600'}`}>{w.screenshots}</td>
                          <td className="px-3 py-2 text-right text-gray-500">{w.reddit} / {w.twitter}</td>
                          <td className="px-3 py-2">
                            {w.paid ? <span className="text-green-700 font-medium">Paid $1.50</span>
                              : w.onTrack ? <span className="text-blue-700 inline-flex items-center gap-1"><Clock size={12} /> On track (in progress)</span>
                              : w.complete ? <span className="text-red-600">Did not qualify</span>
                              : <span className="text-gray-500 inline-flex items-center gap-1"><Clock size={12} /> In progress</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="text-xs text-gray-500 mt-2">{app.paidWeeks} of {app.completedWeeks} completed weeks qualified. Period 13 is the final 6 days, held to the same threshold.</p>
              </section>

              {/* REDCap */}
              <section>
                <h2 className="text-sm font-semibold text-gray-700 mb-2">REDCap completions</h2>
                {!rc?.available ? (
                  <div className="text-sm text-amber-700">REDCap data unavailable: {rc?.reason || 'not mapped'}</div>
                ) : (
                  <div className="grid gap-2 md:grid-cols-2 text-sm">
                    <div className="bg-gray-50 rounded p-3"><div className="text-xs text-gray-500 mb-1">Screening — $10</div><Done ok={rc.screening.complete} at={rc.screening.at} /></div>
                    <div className="bg-gray-50 rounded p-3"><div className="text-xs text-gray-500 mb-1">Baseline interview — $20</div><Done ok={rc.interview.complete} at={rc.interview.at} /></div>
                    <div className="bg-gray-50 rounded p-3"><div className="text-xs text-gray-500 mb-1">Exit survey — $20</div><Done ok={rc.exit.complete} at={rc.exit.at} /></div>
                    <div className="bg-gray-50 rounded p-3"><div className="text-xs text-gray-500 mb-1">Post-interview baseline battery (not compensated)</div>
                      <div className="text-sm">{rc.baselineBattery.completed} of {rc.baselineBattery.total} instruments{rc.baselineBattery.missing?.length ? <span className="text-xs text-gray-500"> — missing: {rc.baselineBattery.missing.join(', ')}</span> : ''}</div></div>
                    <div className="bg-gray-50 rounded p-3 md:col-span-2"><div className="text-xs text-gray-500 mb-1">Weekly surveys (not compensated)</div>
                      <div className="text-sm">{rc.weekly?.totalCompleted ?? 0} completed{rc.weekly?.lastCompletedAt ? ` · last ${fmtDate(rc.weekly.lastCompletedAt)}` : ''}</div></div>
                  </div>
                )}
              </section>

              <div className="text-xs text-gray-400 border-t pt-3">Read-only report. Generated {fmtDate(data.generatedAt)} ET. Nothing here modifies participant data.</div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default ComplianceReportScreen;
