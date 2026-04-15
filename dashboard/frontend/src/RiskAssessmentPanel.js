// RiskAssessmentPanel.js - Live Risk Assessment Summary for a participant
// Displays EMA scores, C-SSRS results, safety plan, and alert history.
// Includes PDF generation + Slack distribution.

import React, { useState, useEffect, useCallback } from 'react';
import { AlertTriangle, FileText, RefreshCw, Send, Shield, Activity, ClipboardList } from 'lucide-react';
import { API_BASE_URL, authFetch } from './SocialScope';

const RISK_COLORS = {
  LOW: { bg: 'bg-green-100', text: 'text-green-800', border: 'border-green-400', badge: 'bg-green-600' },
  MODERATE: { bg: 'bg-amber-100', text: 'text-amber-800', border: 'border-amber-400', badge: 'bg-amber-500' },
  HIGH: { bg: 'bg-red-100', text: 'text-red-800', border: 'border-red-400', badge: 'bg-red-600' },
  IMMINENT: { bg: 'bg-red-200', text: 'text-red-900', border: 'border-red-600', badge: 'bg-red-700' },
};

const RiskAssessmentPanel = ({ participantId }) => {
  const [assessment, setAssessment] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [pdfLoading, setPdfLoading] = useState(false);
  const [pdfResult, setPdfResult] = useState(null);
  const [expanded, setExpanded] = useState({ ema: true, cssrsScreen: true, cssrsPed: false, plan: false, alerts: false });

  const fetchAssessment = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authFetch(`${API_BASE_URL}/api/participant/${participantId}/risk-assessment`);
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Failed to fetch');
      setAssessment(await res.json());
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, [participantId]);

  useEffect(() => { fetchAssessment(); }, [fetchAssessment]);

  const generatePdf = async () => {
    setPdfLoading(true);
    setPdfResult(null);
    try {
      const res = await authFetch(`${API_BASE_URL}/api/participant/${participantId}/risk-assessment/pdf?send_to_slack=true`, { method: 'POST' });
      const data = await res.json();
      setPdfResult(data);
    } catch (e) { setPdfResult({ error: e.message }); }
    finally { setPdfLoading(false); }
  };

  const toggle = (section) => setExpanded(prev => ({ ...prev, [section]: !prev[section] }));

  if (loading) return <div className="flex justify-center py-8"><div className="animate-spin rounded-full h-8 w-8 border-4 border-blue-500 border-t-transparent" /></div>;
  if (error) return <div className="text-red-600 p-4">Error: {error}</div>;
  if (!assessment) return <div className="text-gray-500 p-4">No data available</div>;

  const rc = RISK_COLORS[assessment.riskLevel] || RISK_COLORS.LOW;
  const fmtDate = (d) => {
    if (!d) return '—';
    try {
      const dt = typeof d === 'string' ? new Date(d) : (d._seconds ? new Date(d._seconds * 1000) : new Date(d));
      return dt.toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
    } catch { return '—'; }
  };

  return (
    <div className="space-y-4">
      {/* Risk Level Header */}
      <div className={`rounded-lg border-2 p-4 ${rc.bg} ${rc.border}`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Shield size={24} className={rc.text} />
            <div>
              <div className="flex items-center gap-2">
                <span className={`px-3 py-1 rounded text-white font-bold text-sm ${rc.badge}`}>
                  {assessment.riskLevel} RISK
                </span>
                {assessment.imminentRisk && (
                  <span className="px-2 py-1 bg-red-700 text-white text-xs font-bold rounded animate-pulse">IMMINENT</span>
                )}
              </div>
              <div className="text-xs text-gray-600 mt-1">
                EMA Score: <strong>{assessment.emaScore}</strong> | C-SSRS Severity: <strong>{assessment.cssrsSeverity}</strong>
              </div>
            </div>
          </div>
          <div className="flex gap-2">
            <button onClick={fetchAssessment} className="p-2 text-gray-600 hover:bg-white rounded" title="Refresh">
              <RefreshCw size={16} />
            </button>
            <button onClick={generatePdf} disabled={pdfLoading}
              className="flex items-center gap-1 px-3 py-1 bg-blue-600 text-white text-xs rounded hover:bg-blue-700 disabled:opacity-50">
              {pdfLoading ? <div className="animate-spin h-3 w-3 border-2 border-white border-t-transparent rounded-full" /> : <Send size={14} />}
              {pdfLoading ? 'Generating...' : 'PDF to Slack'}
            </button>
          </div>
        </div>
        {pdfResult && (
          <div className={`mt-2 text-xs ${pdfResult.error ? 'text-red-700' : 'text-green-700'}`}>
            {pdfResult.error ? `Error: ${pdfResult.error}` : `PDF generated and sent to Slack (${pdfResult.risk_level})`}
          </div>
        )}
      </div>

      {/* Contact Info */}
      {assessment.contactInfo && (
        <div className="bg-white rounded-lg border border-gray-200 p-3">
          <h3 className="text-sm font-semibold text-gray-700 mb-2 flex items-center gap-1">
            <FileText size={16} className="text-gray-500" /> Participant Contact Info
          </h3>
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
            {assessment.contactInfo.phone && (
              <div><span className="text-gray-500">Phone:</span> <span className="font-medium">{assessment.contactInfo.phone}</span></div>
            )}
            {assessment.contactInfo.email && (
              <div><span className="text-gray-500">Email:</span> <span className="font-medium">{assessment.contactInfo.email}</span></div>
            )}
            {assessment.contactInfo.address && (
              <div className="col-span-2"><span className="text-gray-500">Address:</span> <span className="font-medium">{assessment.contactInfo.address}</span></div>
            )}
            {assessment.contactInfo.county && (
              <div><span className="text-gray-500">County:</span> <span className="font-medium">{assessment.contactInfo.county}</span></div>
            )}
            {assessment.contactInfo.erServiceNumber && (
              <div><span className="text-gray-500">Emergency Services:</span> <span className="font-medium">{assessment.contactInfo.erServiceNumber}</span></div>
            )}
          </div>
          {/* Clinician */}
          {assessment.contactInfo.clinician?.name && (
            <div className="mt-2 pt-2 border-t border-gray-100 text-sm">
              <span className="text-gray-500">Clinician:</span>{' '}
              <span className="font-medium">{assessment.contactInfo.clinician.name}</span>
              {assessment.contactInfo.clinician.phone && <span> — {assessment.contactInfo.clinician.phone}</span>}
              {assessment.contactInfo.clinician.erContact && assessment.contactInfo.clinician.erContact !== 'N/a' && (
                <span className="text-xs text-gray-500 ml-2">(After-hours: {assessment.contactInfo.clinician.erContact})</span>
              )}
            </div>
          )}
          {/* Local ER */}
          {assessment.contactInfo.localER?.name && (
            <div className="text-sm mt-1">
              <span className="text-gray-500">Local ER:</span>{' '}
              <span className="font-medium">{assessment.contactInfo.localER.name}</span>
              {assessment.contactInfo.localER.phone && <span> — {assessment.contactInfo.localER.phone}</span>}
              {assessment.contactInfo.localER.address && <span className="text-xs text-gray-500 ml-2">({assessment.contactInfo.localER.address})</span>}
            </div>
          )}
          {/* Emergency Contacts */}
          {assessment.contactInfo.emergencyContacts?.length > 0 && (
            <div className="mt-2 pt-2 border-t border-gray-100">
              <div className="text-xs font-bold text-gray-500 uppercase mb-1">Emergency Contacts</div>
              {assessment.contactInfo.emergencyContacts.map((ec, i) => (
                <div key={i} className="text-sm">
                  <span className="font-medium">{ec.name}</span>
                  {ec.phone && <span> — {ec.phone}</span>}
                  {ec.relationship && <span className="text-xs text-gray-500 ml-1">({ec.relationship})</span>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* EMA Section */}
      <CollapsibleSection title="EMA Check-in" icon={<Activity size={18} />} color="blue"
        expanded={expanded.ema} onToggle={() => toggle('ema')}
        badge={assessment.latestEma ? fmtDate(assessment.latestEma.completedAt) : 'No data'}>
        {assessment.latestEma ? (
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="bg-gray-50">
                <th className="text-left p-2 border-b font-medium text-gray-600">Question</th>
                <th className="text-left p-2 border-b font-medium text-gray-600 w-32">Response</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(assessment.latestEma.questions).map(([field, q]) => {
                const val = q.value;
                const valStr = val === true ? 'Yes' : val === false ? 'No' : val != null ? String(val) : '—';
                return (
                  <tr key={field} className={q.exceedsThreshold ? 'bg-red-50 font-semibold text-red-800' : ''}>
                    <td className="p-2 border-b">
                      <div>{q.label}</div>
                      {q.anchors && <div className="text-xs text-gray-400 mt-0.5">{q.anchors}</div>}
                    </td>
                    <td className="p-2 border-b">
                      {valStr}
                      {q.exceedsThreshold && <span className="ml-2 text-red-600 text-xs font-bold">TRIGGER</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : <p className="text-gray-500 text-sm p-2">No EMA data available</p>}
      </CollapsibleSection>

      {/* C-SSRS Screen (Weekly) */}
      <CollapsibleSection title="C-SSRS Screen (Weekly)" icon={<ClipboardList size={18} />} color="purple"
        expanded={expanded.cssrsScreen} onToggle={() => toggle('cssrsScreen')}
        badge={assessment.cssrsScreen ? `Severity: ${assessment.cssrsScreen.severity}` : 'Not synced'}>
        {assessment.cssrsScreen ? (
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="bg-gray-50">
                <th className="text-left p-2 border-b font-medium text-gray-600">Question</th>
                <th className="text-left p-2 border-b font-medium text-gray-600 w-24">Response</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(assessment.cssrsScreen.questions || {}).map(([field, q]) => {
                const val = q.value;
                const isCrisis = ['cssrs_scr_4', 'cssrs_scr_5', 'cssrs_scr_6'].includes(field) && val === true;
                return (
                  <tr key={field} className={isCrisis ? 'bg-red-50 font-semibold text-red-800' : ''}>
                    <td className="p-2 border-b">{q.label}</td>
                    <td className="p-2 border-b">
                      {val === true ? 'Yes' : val === false ? 'No' : '—'}
                      {isCrisis && <span className="ml-1 text-red-600 text-xs font-bold">CRISIS</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : <p className="text-gray-500 text-sm p-2">No weekly C-SSRS data. Will populate when synced from REDCap.</p>}
      </CollapsibleSection>

      {/* C-SSRS Pediatric (Interview) */}
      <CollapsibleSection title="C-SSRS Interview (Pediatric)" icon={<ClipboardList size={18} />} color="indigo"
        expanded={expanded.cssrsPed} onToggle={() => toggle('cssrsPed')}
        badge={assessment.cssrsPediatric ? `Severity: ${assessment.cssrsPediatric.severity}` : 'Not synced'}>
        {assessment.cssrsPediatric ? (
          <div>
            <h4 className="text-xs font-bold text-gray-500 uppercase mt-2 mb-1 px-2">Suicidal Ideation</h4>
            <table className="w-full text-sm border-collapse">
              <tbody>
                {[
                  ['wish_to_be_dead', '1. Wish to be Dead'],
                  ['nonspecific_thoughts', '2. Non-Specific Active Suicidal Thoughts'],
                  ['ideation_with_methods', '3. Ideation with Methods'],
                  ['ideation_with_intent', '4. Ideation with Intent'],
                  ['ideation_with_plan', '5. Ideation with Plan and Intent'],
                ].map(([key, label]) => {
                  const val = (assessment.cssrsPediatric.ideation || {})[key];
                  const isCrisis = (key === 'ideation_with_intent' || key === 'ideation_with_plan') && val === true;
                  return (
                    <tr key={key} className={isCrisis ? 'bg-red-50 font-semibold text-red-800' : ''}>
                      <td className="p-2 border-b">{label}</td>
                      <td className="p-2 border-b w-24">
                        {val === true ? 'Yes' : val === false ? 'No' : '—'}
                        {isCrisis && <span className="ml-1 text-xs font-bold text-red-600">CRISIS</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <h4 className="text-xs font-bold text-gray-500 uppercase mt-3 mb-1 px-2">Suicidal Behavior</h4>
            <table className="w-full text-sm border-collapse">
              <tbody>
                {[
                  ['actual_attempt', 'Actual Attempt'],
                  ['interrupted_attempt', 'Interrupted Attempt'],
                  ['aborted_attempt', 'Aborted Attempt'],
                  ['preparatory_acts', 'Preparatory Acts'],
                  ['non_suicidal_self_harm', 'Non-Suicidal Self-Harm'],
                ].map(([key, label]) => {
                  const val = (assessment.cssrsPediatric.behavior || {})[key];
                  return (
                    <tr key={key} className={val === true ? 'bg-red-50 font-semibold text-red-800' : ''}>
                      <td className="p-2 border-b">{label}</td>
                      <td className="p-2 border-b w-24">{val === true ? 'Yes' : val === false ? 'No' : '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : <p className="text-gray-500 text-sm p-2">No interview C-SSRS data. Will populate when synced from REDCap.</p>}
      </CollapsibleSection>

      {/* Safety Plan */}
      <CollapsibleSection title="Safety Plan" icon={<Shield size={18} />} color="teal"
        expanded={expanded.plan} onToggle={() => toggle('plan')}
        badge={assessment.safetyPlan ? 'Loaded' : 'Not synced'}>
        {assessment.safetyPlan ? (
          <div className="space-y-3 text-sm p-2">
            {assessment.safetyPlan.warningSigns?.length > 0 && (
              <div>
                <h4 className="font-semibold text-gray-700">Warning Signs</h4>
                <ul className="list-disc list-inside text-gray-600">
                  {assessment.safetyPlan.warningSigns.map((w, i) => <li key={i}>{w}</li>)}
                </ul>
              </div>
            )}
            {assessment.safetyPlan.copingStrategies?.length > 0 && (
              <div>
                <h4 className="font-semibold text-gray-700">Coping Strategies</h4>
                <ul className="list-disc list-inside text-gray-600">
                  {assessment.safetyPlan.copingStrategies.map((c, i) => <li key={i}>{c}</li>)}
                </ul>
              </div>
            )}
            {assessment.safetyPlan.supportContacts?.length > 0 && (
              <div>
                <h4 className="font-semibold text-gray-700">Support Network</h4>
                <ul className="list-disc list-inside text-gray-600">
                  {assessment.safetyPlan.supportContacts.map((c, i) => <li key={i}>{c.name} — {c.phone}</li>)}
                </ul>
              </div>
            )}
            {assessment.safetyPlan.clinicianName && (
              <div>
                <h4 className="font-semibold text-gray-700">Clinician</h4>
                <p className="text-gray-600">{assessment.safetyPlan.clinicianName} — {assessment.safetyPlan.clinicianPhone}</p>
              </div>
            )}
            {assessment.safetyPlan.localErName && (
              <div>
                <h4 className="font-semibold text-gray-700">Local ER</h4>
                <p className="text-gray-600">{assessment.safetyPlan.localErName} — {assessment.safetyPlan.localErPhone} — {assessment.safetyPlan.localErAddress}</p>
              </div>
            )}
          </div>
        ) : <p className="text-gray-500 text-sm p-2">Safety plan not yet synced from REDCap.</p>}
      </CollapsibleSection>

      {/* Alert History */}
      <CollapsibleSection title="Recent Alerts" icon={<AlertTriangle size={18} />} color="red"
        expanded={expanded.alerts} onToggle={() => toggle('alerts')}
        badge={`${assessment.alertHistory?.length || 0} alerts`}>
        {assessment.alertHistory?.length > 0 ? (
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="bg-gray-50">
                <th className="text-left p-2 border-b font-medium text-gray-600">Date</th>
                <th className="text-left p-2 border-b font-medium text-gray-600">Type</th>
                <th className="text-left p-2 border-b font-medium text-gray-600">Source</th>
                <th className="text-left p-2 border-b font-medium text-gray-600">Handled</th>
              </tr>
            </thead>
            <tbody>
              {assessment.alertHistory.map((a, i) => (
                <tr key={i} className={a.confirmedDanger ? 'bg-red-50' : ''}>
                  <td className="p-2 border-b">{fmtDate(a.triggeredAt)}</td>
                  <td className="p-2 border-b">{a.type || '—'}</td>
                  <td className="p-2 border-b">{a.source || '—'}</td>
                  <td className="p-2 border-b">{a.handled ? 'Yes' : 'No'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="text-gray-500 text-sm p-2">No alerts in the last 30 days.</p>}
      </CollapsibleSection>
    </div>
  );
};


const CollapsibleSection = ({ title, icon, color, expanded, onToggle, badge, children }) => {
  const colorMap = {
    blue: 'border-blue-300', purple: 'border-purple-300', indigo: 'border-indigo-300',
    teal: 'border-teal-300', red: 'border-red-300',
  };
  const textMap = {
    blue: 'text-blue-600', purple: 'text-purple-600', indigo: 'text-indigo-600',
    teal: 'text-teal-600', red: 'text-red-600',
  };

  return (
    <div className={`bg-white rounded-lg border ${colorMap[color] || 'border-gray-200'} overflow-hidden`}>
      <button onClick={onToggle}
        className="w-full flex items-center justify-between p-3 hover:bg-gray-50 transition-colors">
        <div className="flex items-center gap-2">
          <span className={textMap[color] || 'text-gray-600'}>{icon}</span>
          <span className="font-semibold text-gray-800 text-sm">{title}</span>
          {badge && <span className="text-xs text-gray-500 ml-2">{badge}</span>}
        </div>
        <span className="text-gray-400 text-xs">{expanded ? 'collapse' : 'expand'}</span>
      </button>
      {expanded && <div className="border-t border-gray-100">{children}</div>}
    </div>
  );
};


export default RiskAssessmentPanel;
