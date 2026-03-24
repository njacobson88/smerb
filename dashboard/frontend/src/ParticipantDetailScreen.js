// ParticipantDetailScreen.js - Single Participant Daily View

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { ChevronLeft, ChevronRight, Download, Loader2, Camera, FileText, AlertTriangle, RefreshCw, Clock, CheckCircle, XCircle, Pencil, Save, X } from 'lucide-react';
import { API_BASE_URL, authFetch } from './SocialScope';

// Color constants
const COLORS = {
  green: "#006164",
  lightGreen: "#57C4AD",
  orange: "#EDA247",
  red: "#DB4325",
  blue: "#4A6CF7",
};

// Platform colors
const PLATFORM_COLORS = {
  reddit: "#FF4500",
  twitter: "#1DA1F2",
};

// Activity level cell styling
const getActivityClass = (value, threshold = 12) => {
  if (value <= 6) return 'bg-red-100 text-red-800';
  if (value <= threshold) return 'bg-orange-100 text-orange-800';
  return '';
};


const ParticipantDetailScreen = ({
  participantId,
  participantList,
  goToOverallView,
  goToParticipantView,
  goToDayView
}) => {
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [currentParticipantId, setCurrentParticipantId] = useState(participantId);
  const [lastUpdated, setLastUpdated] = useState(null);

  // Export state
  const [exportLoading, setExportLoading] = useState(false);
  const [exportError, setExportError] = useState(null);
  const [exportDownload, setExportDownload] = useState(null);
  const [exportLevel, setExportLevel] = useState(1);
  const [showExportOptions, setShowExportOptions] = useState(false);
  const [showExportConfirm, setShowExportConfirm] = useState(false);
  const [pendingExportLevel, setPendingExportLevel] = useState(null);
  const [activeExport, setActiveExport] = useState(null); // Track async export job
  const pollIntervalRef = useRef(null);

  // Study start date editing state
  const [editingStudyStart, setEditingStudyStart] = useState(false);
  const [studyStartInput, setStudyStartInput] = useState('');
  const [studyStartSaving, setStudyStartSaving] = useState(false);
  const [studyStartError, setStudyStartError] = useState(null);
  const [studyStartSuccess, setStudyStartSuccess] = useState(false);

  // Active status toggle state
  const [activeStatusSaving, setActiveStatusSaving] = useState(false);
  const [activeStatusError, setActiveStatusError] = useState(null);
  const [showInactiveConfirm, setShowInactiveConfirm] = useState(false);
  const [inactiveReason, setInactiveReason] = useState('');

  // App distribution state
  const [distEmail, setDistEmail] = useState('');
  const [distDeviceType, setDistDeviceType] = useState('');
  const [distManualOverride, setDistManualOverride] = useState(false);
  const [distInviteStatus, setDistInviteStatus] = useState(null);
  const [distInviteSentAt, setDistInviteSentAt] = useState(null);
  const [distSaving, setDistSaving] = useState(false);
  const [distSending, setDistSending] = useState(false);
  const [distError, setDistError] = useState(null);
  const [distSuccess, setDistSuccess] = useState(null);
  const [showDistPanel, setShowDistPanel] = useState(false);

  // Compliance notification state
  const [complianceData, setComplianceData] = useState(null);
  const [showCompliancePanel, setShowCompliancePanel] = useState(false);
  const [notifCategory, setNotifCategory] = useState('ema');
  const [notifPreview, setNotifPreview] = useState(null);
  const [notifDelivery, setNotifDelivery] = useState(['email']);
  const [notifSending, setNotifSending] = useState(false);
  const [notifResult, setNotifResult] = useState(null);

  // Find current index in participant list
  const currentIndex = participantList?.indexOf(currentParticipantId) ?? -1;

  // Navigation between participants
  const goToPrevParticipant = useCallback(() => {
    if (currentIndex > 0) {
      const prevId = participantList[currentIndex - 1];
      setCurrentParticipantId(prevId);
      goToParticipantView(prevId);
    }
  }, [currentIndex, participantList, goToParticipantView]);

  const goToNextParticipant = useCallback(() => {
    if (currentIndex < participantList.length - 1) {
      const nextId = participantList[currentIndex + 1];
      setCurrentParticipantId(nextId);
      goToParticipantView(nextId);
    }
  }, [currentIndex, participantList, goToParticipantView]);

  // Fetch participant summary
  const fetchSummary = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await authFetch(
        `${API_BASE_URL}/api/participant/${currentParticipantId}/summary`
      );

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `Server responded with ${response.status}`);
      }

      const data = await response.json();
      setSummary(data);
      setLastUpdated(new Date());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [currentParticipantId]);

  useEffect(() => {
    if (currentParticipantId) {
      fetchSummary();
    }
  }, [currentParticipantId, fetchSummary]);

  // Poll for async export status
  const pollExportStatus = useCallback(async (jobId) => {
    try {
      const response = await authFetch(`${API_BASE_URL}/api/export/jobs/${jobId}`);
      if (response.ok) {
        const job = await response.json();
        setActiveExport(job);

        if (job.status === 'completed') {
          // Stop polling and show download
          if (pollIntervalRef.current) {
            clearInterval(pollIntervalRef.current);
            pollIntervalRef.current = null;
          }
          // Handle both absolute URLs (signed Firebase Storage) and relative paths
          // Async jobs use downloadUrl (camelCase) from Firestore
          const url = job.downloadUrl || job.download_url;
          setExportDownload({
            url: url?.startsWith('http') ? url : `${API_BASE_URL}${url}`,
            filename: job.filename
          });
        } else if (job.status === 'failed') {
          // Stop polling on failure
          if (pollIntervalRef.current) {
            clearInterval(pollIntervalRef.current);
            pollIntervalRef.current = null;
          }
          setExportError(job.error || 'Export failed');
        }
      }
    } catch (err) {
      console.error('Error polling export status:', err);
    }
  }, []);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, []);

  // Fetch distribution info when participant changes
  const fetchDistribution = useCallback(async () => {
    try {
      const res = await authFetch(`${API_BASE_URL}/api/participant/${currentParticipantId}/distribution`);
      if (res.ok) {
        const data = await res.json();
        if (data.distribution) {
          setDistEmail(data.distribution.email || '');
          setDistDeviceType(data.distribution.deviceType || '');
          setDistManualOverride(data.distribution.manualOverride || false);
          setDistInviteStatus(data.distribution.inviteStatus);
          setDistInviteSentAt(data.distribution.inviteSentAt);
        }
      }
    } catch (e) { /* ignore */ }
  }, [currentParticipantId]);

  useEffect(() => {
    if (currentParticipantId) fetchDistribution();
  }, [currentParticipantId, fetchDistribution]);

  // Fetch compliance data
  const fetchCompliance = useCallback(async () => {
    try {
      const res = await authFetch(`${API_BASE_URL}/api/compliance/${currentParticipantId}?days=3`);
      if (res.ok) {
        const data = await res.json();
        console.log('[Compliance] Data loaded:', data);
        setComplianceData(data);
      } else {
        console.log('[Compliance] Fetch failed:', res.status);
        // Still show the panel with defaults so the notification UI is accessible
        setComplianceData({ threeDay: { compliance_pct: 0, needs_notification: true, ema_count: 0, ema_expected: 9 }, weekly: null, notificationHistory: [] });
      }
    } catch (e) {
      console.log('[Compliance] Error:', e);
      setComplianceData({ threeDay: { compliance_pct: 0, needs_notification: true, ema_count: 0, ema_expected: 9 }, weekly: null, notificationHistory: [] });
    }
  }, [currentParticipantId]);

  useEffect(() => {
    if (currentParticipantId) fetchCompliance();
  }, [currentParticipantId, fetchCompliance]);

  const previewNotification = async () => {
    setNotifPreview(null); // Clear first to force re-render
    try {
      const res = await authFetch(`${API_BASE_URL}/api/compliance/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          participant_id: currentParticipantId,
          category: notifCategory,
          template_index: notifPreview?.templateIndex ?? null, // Exclude current to get a different one
        }),
      });
      if (res.ok) setNotifPreview(await res.json());
    } catch (e) { /* ignore */ }
  };

  const sendNotification = async () => {
    setNotifSending(true); setNotifResult(null);
    try {
      const payload = {
        participant_id: currentParticipantId,
        category: notifCategory,
        delivery_methods: notifDelivery,
        // Send the edited subject and body (user may have modified the template)
        custom_subject: notifPreview?.subject,
        custom_body: notifPreview?.body,
      };
      const res = await authFetch(`${API_BASE_URL}/api/compliance/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      setNotifResult(res.ok ? { success: true, ...data } : { success: false, error: data.detail });
      if (res.ok) fetchCompliance();
    } catch (e) { setNotifResult({ success: false, error: e.message }); }
    finally { setNotifSending(false); }
  };

  const saveDistribution = async () => {
    setDistSaving(true); setDistError(null); setDistSuccess(null);
    try {
      const res = await authFetch(`${API_BASE_URL}/api/participant/${currentParticipantId}/distribution`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: distEmail, device_type: distDeviceType, manual_override: true }),
      });
      if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.detail || 'Failed to save'); }
      setDistSuccess('Saved');
      setDistManualOverride(true);
      setTimeout(() => setDistSuccess(null), 3000);
    } catch (e) { setDistError(e.message); } finally { setDistSaving(false); }
  };

  const sendInvite = async () => {
    if (!distDeviceType) { setDistError('Please confirm the device type (iOS or Android) before sending.'); return; }
    if (!distEmail) { setDistError('Please enter an email address first.'); return; }
    setDistSending(true); setDistError(null); setDistSuccess(null);
    try {
      const res = await authFetch(`${API_BASE_URL}/api/participant/${currentParticipantId}/distribution/send-invite`, {
        method: 'POST',
      });
      if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.detail || 'Failed to send'); }
      const data = await res.json();
      setDistSuccess(`Invite sent to ${data.email} (${data.deviceType})`);
      setDistInviteStatus('sent');
      setDistInviteSentAt(new Date().toISOString());
    } catch (e) { setDistError(e.message); } finally { setDistSending(false); }
  };

  // Handle data export - show confirmation for Level 3
  const handleExportClick = (level) => {
    setShowExportOptions(false);
    if (level === 3) {
      // Show confirmation dialog for Level 3 (screenshots)
      setPendingExportLevel(level);
      setShowExportConfirm(true);
    } else {
      // Proceed directly for Level 1 and 2
      executeExport(level);
    }
  };

  // Execute the actual export
  const executeExport = async (level) => {
    setExportLoading(true);
    setExportError(null);
    setExportDownload(null);
    setShowExportConfirm(false);
    setActiveExport(null);

    // Clear any existing polling
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }

    try {
      if (level === 3) {
        // Use async export for Level 3 (screenshots)
        const response = await authFetch(`${API_BASE_URL}/api/export/async`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            participant_id: currentParticipantId,
            export_level: level
          })
        });

        if (!response.ok) {
          const errData = await response.json().catch(() => ({}));
          throw new Error(errData.detail || 'Export failed');
        }

        const data = await response.json();

        // Set active export and start polling
        setActiveExport({
          job_id: data.job_id,
          status: 'pending',
          export_level: level,
          participant_id: currentParticipantId,
          created_at: new Date().toISOString(),
          progress: 0
        });

        // Start polling every 3 seconds
        pollIntervalRef.current = setInterval(() => {
          pollExportStatus(data.job_id);
        }, 3000);

        // Also poll immediately
        setTimeout(() => pollExportStatus(data.job_id), 500);
      } else {
        // Synchronous export for Level 1 and 2
        const params = new URLSearchParams({
          participant_id: currentParticipantId,
          export_level: level.toString()
        });
        const response = await authFetch(`${API_BASE_URL}/api/export?${params}`);

        if (!response.ok) {
          const errData = await response.json().catch(() => ({}));
          throw new Error(errData.detail || 'Export failed');
        }

        const data = await response.json();
        // Handle both absolute URLs (signed Firebase Storage) and relative paths
        const url = data.download_url;
        setExportDownload({
          url: url?.startsWith('http') ? url : `${API_BASE_URL}${url}`,
          filename: data.filename
        });
      }
    } catch (err) {
      setExportError(err.message);
    } finally {
      setExportLoading(false);
    }
  };

  const exportLevelDescriptions = {
    1: { name: 'Metadata + EMA', desc: 'Participant info, EMA responses, safety alerts' },
    2: { name: 'Level 1 + Events', desc: 'All events with OCR text data' },
    3: { name: 'Full Export', desc: 'Everything including screenshot images' }
  };

  // Handle study start date edit
  const handleEditStudyStart = () => {
    setStudyStartInput(summary?.study_start_date || '');
    setEditingStudyStart(true);
    setStudyStartError(null);
    setStudyStartSuccess(false);
  };

  const handleCancelStudyStartEdit = () => {
    setEditingStudyStart(false);
    setStudyStartInput('');
    setStudyStartError(null);
  };

  const handleSaveStudyStart = async () => {
    if (!studyStartInput) {
      setStudyStartError('Please enter a date');
      return;
    }

    // Validate date format
    const dateRegex = /^\d{4}-\d{2}-\d{2}$/;
    if (!dateRegex.test(studyStartInput)) {
      setStudyStartError('Invalid date format. Use YYYY-MM-DD.');
      return;
    }

    setStudyStartSaving(true);
    setStudyStartError(null);

    try {
      const response = await authFetch(
        `${API_BASE_URL}/api/participant/${currentParticipantId}/study-start-date`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ study_start_date: studyStartInput })
        }
      );

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `Failed to update study start date`);
      }

      // Update the summary with the new date
      setSummary(prev => ({
        ...prev,
        study_start_date: studyStartInput,
        study_start_is_custom: true
      }));

      setEditingStudyStart(false);
      setStudyStartSuccess(true);

      // Clear success message after 3 seconds
      setTimeout(() => setStudyStartSuccess(false), 3000);
    } catch (err) {
      setStudyStartError(err.message);
    } finally {
      setStudyStartSaving(false);
    }
  };

  // Handle active status toggle
  const handleToggleActiveStatus = async (newStatus) => {
    // If marking as inactive, show confirmation dialog
    if (!newStatus && !showInactiveConfirm) {
      setShowInactiveConfirm(true);
      return;
    }

    setActiveStatusSaving(true);
    setActiveStatusError(null);
    setShowInactiveConfirm(false);

    try {
      const response = await authFetch(
        `${API_BASE_URL}/api/participant/${currentParticipantId}/active-status`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            is_active: newStatus,
            reason: newStatus ? null : (inactiveReason || 'Manually marked inactive')
          })
        }
      );

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to update status');
      }

      // Update local state
      setSummary(prev => ({
        ...prev,
        is_active: newStatus,
        is_active_manual: true,
        inactive_reason: newStatus ? null : (inactiveReason || 'Manually marked inactive')
      }));

      setInactiveReason('');
    } catch (err) {
      setActiveStatusError(err.message);
    } finally {
      setActiveStatusSaving(false);
    }
  };

  // Calculate totals
  const dailySummary = summary?.daily_summary || [];
  const totalScreenshots = dailySummary.reduce((sum, d) => sum + (d.screenshots || 0), 0);
  const totalCheckins = dailySummary.reduce((sum, d) => sum + (d.checkins || 0), 0);
  const totalAlerts = dailySummary.reduce((sum, d) => sum + (d.safety_alerts || 0), 0);
  const totalOcrWords = dailySummary.reduce((sum, d) => sum + (d.ocr_words || 0), 0);

  return (
    <div className="participant-detail-screen">
      {/* Navigation */}
      <div className="mb-4 flex items-center justify-between">
        <button
          onClick={goToOverallView}
          className="text-blue-600 hover:text-blue-800 hover:underline flex items-center"
        >
          <ChevronLeft size={20} /> Back to Overview
        </button>

        <div className="flex items-center space-x-2">
          <button
            onClick={goToPrevParticipant}
            disabled={currentIndex <= 0}
            className="px-3 py-2 bg-gray-100 hover:bg-gray-200 rounded-md disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <ChevronLeft size={18} />
          </button>
          <span className="text-gray-600 text-sm">
            {currentIndex + 1} of {participantList?.length || 0}
          </span>
          <button
            onClick={goToNextParticipant}
            disabled={currentIndex >= (participantList?.length || 0) - 1}
            className="px-3 py-2 bg-gray-100 hover:bg-gray-200 rounded-md disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <ChevronRight size={18} />
          </button>
        </div>
      </div>

      {/* Header */}
      <div className="bg-white rounded-lg shadow p-6 mb-6">
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center mb-2">
              <h1 className="text-2xl font-bold text-gray-800">
                Participant: {currentParticipantId}
              </h1>
              {summary && (
                <button
                  onClick={() => handleToggleActiveStatus(!summary.is_active)}
                  disabled={activeStatusSaving}
                  className={`ml-3 px-3 py-1 rounded-full text-xs font-bold cursor-pointer hover:opacity-80 transition-opacity disabled:opacity-50 ${
                    summary.is_active
                      ? 'bg-green-100 text-green-800 hover:bg-green-200'
                      : 'bg-gray-200 text-gray-600 hover:bg-gray-300'
                  }`}
                  title={summary.is_active ? 'Click to mark as inactive' : 'Click to reactivate'}
                >
                  {activeStatusSaving ? '...' : (summary.is_active ? 'ACTIVE' : 'INACTIVE')}
                </button>
              )}
              {summary && summary.is_active && summary.days_remaining !== undefined && (
                <span className="ml-2 text-sm text-gray-500">
                  Day {summary.study_day}/90 ({summary.days_remaining} days remaining)
                </span>
              )}
              {summary && !summary.is_active && (
                <span className="ml-2 text-sm text-gray-500">
                  {summary.inactive_reason || (summary.is_active_manual ? 'Manually marked inactive' : 'Study completed')}
                </span>
              )}
              {activeStatusError && (
                <span className="ml-2 text-sm text-red-500">{activeStatusError}</span>
              )}
            </div>
            {summary && (
              <div className="text-gray-600 text-sm space-y-1">
                <div className="flex items-center">
                  <span className="mr-2">Study Start:</span>
                  {editingStudyStart ? (
                    <div className="flex items-center space-x-2">
                      <input
                        type="date"
                        value={studyStartInput}
                        onChange={(e) => setStudyStartInput(e.target.value)}
                        className="px-2 py-1 border rounded text-sm"
                        disabled={studyStartSaving}
                      />
                      <button
                        onClick={handleSaveStudyStart}
                        disabled={studyStartSaving}
                        className="p-1 text-green-600 hover:text-green-800 disabled:opacity-50"
                        title="Save"
                      >
                        {studyStartSaving ? (
                          <Loader2 size={16} className="animate-spin" />
                        ) : (
                          <Save size={16} />
                        )}
                      </button>
                      <button
                        onClick={handleCancelStudyStartEdit}
                        disabled={studyStartSaving}
                        className="p-1 text-gray-500 hover:text-gray-700 disabled:opacity-50"
                        title="Cancel"
                      >
                        <X size={16} />
                      </button>
                    </div>
                  ) : (
                    <div className="flex items-center">
                      <span className={summary.study_start_is_custom ? 'font-medium text-blue-600' : ''}>
                        {summary.study_start_date || 'Unknown'}
                      </span>
                      {summary.study_start_is_custom && (
                        <span className="ml-2 text-xs text-blue-500">(custom)</span>
                      )}
                      <button
                        onClick={handleEditStudyStart}
                        className="ml-2 p-1 text-gray-400 hover:text-blue-600 transition-colors"
                        title="Edit study start date"
                      >
                        <Pencil size={14} />
                      </button>
                      {studyStartSuccess && (
                        <span className="ml-2 text-green-600 text-xs flex items-center">
                          <CheckCircle size={14} className="mr-1" /> Saved
                        </span>
                      )}
                    </div>
                  )}
                </div>
                {studyStartError && (
                  <div className="text-red-500 text-xs">{studyStartError}</div>
                )}
                <div>Device: {summary.device_model || 'Unknown'} ({summary.os_version || 'Unknown'})</div>

                {/* App Distribution Toggle */}
                <button
                  onClick={() => setShowDistPanel(!showDistPanel)}
                  className="mt-1 text-xs text-blue-600 hover:text-blue-800 font-medium"
                >
                  {showDistPanel ? 'Hide' : 'Show'} App Distribution
                </button>
              </div>
            )}
          </div>

          {/* App Distribution Panel */}
          {showDistPanel && (
            <div className="bg-indigo-50 border border-indigo-200 rounded-lg p-4 mb-4">
              <h3 className="text-sm font-semibold text-indigo-800 mb-3">App Distribution</h3>

              <div className="grid grid-cols-2 gap-3 mb-3">
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Email for invite</label>
                  <input
                    type="email"
                    value={distEmail}
                    onChange={(e) => setDistEmail(e.target.value)}
                    placeholder="participant@email.com"
                    className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500"
                  />
                  <p className="text-xs text-gray-400 mt-0.5">iOS requires a Google-linked email</p>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Device type
                    {distManualOverride && <span className="text-amber-600 ml-1">(manually set)</span>}
                  </label>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setDistDeviceType('ios')}
                      className={`flex-1 py-1.5 text-sm font-medium rounded border transition-colors ${
                        distDeviceType === 'ios'
                          ? 'bg-blue-600 text-white border-blue-600'
                          : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'
                      }`}
                    >
                      iOS
                    </button>
                    <button
                      onClick={() => setDistDeviceType('android')}
                      className={`flex-1 py-1.5 text-sm font-medium rounded border transition-colors ${
                        distDeviceType === 'android'
                          ? 'bg-green-600 text-white border-green-600'
                          : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'
                      }`}
                    >
                      Android
                    </button>
                  </div>
                </div>
              </div>

              {/* Status messages */}
              {distError && (
                <div className="text-red-600 text-xs mb-2 bg-red-50 rounded p-2">{distError}</div>
              )}
              {distSuccess && (
                <div className="text-green-600 text-xs mb-2 bg-green-50 rounded p-2">{distSuccess}</div>
              )}
              {distInviteStatus === 'sent' && (
                <div className="text-indigo-600 text-xs mb-2">
                  Last invite sent: {distInviteSentAt ? new Date(distInviteSentAt).toLocaleString() : 'Unknown'}
                </div>
              )}

              {/* Action buttons */}
              <div className="flex gap-2">
                <button
                  onClick={saveDistribution}
                  disabled={distSaving}
                  className="flex items-center px-3 py-1.5 text-sm bg-gray-600 text-white rounded hover:bg-gray-700 disabled:opacity-50"
                >
                  <Save size={14} className="mr-1" />
                  {distSaving ? 'Saving...' : 'Save'}
                </button>
                <button
                  onClick={sendInvite}
                  disabled={distSending || !distEmail || !distDeviceType}
                  className="flex items-center px-3 py-1.5 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
                >
                  {distSending ? 'Sending...' : `Send ${distDeviceType ? distDeviceType.toUpperCase() : ''} Invite`}
                </button>
              </div>
            </div>
          )}

          {/* Compliance Badge + Notification Panel */}
          {summary && (
            <div className="flex items-center gap-3 mb-4">
              {/* Compliance badge */}
              {complianceData?.threeDay?.needs_notification && (
                <span className="px-3 py-1 bg-amber-500 text-white text-xs font-bold rounded-full animate-pulse"
                  title="Low compliance — consider sending a notification">
                  ⚠ Low Compliance ({complianceData?.threeDay?.compliance_pct ?? 0}%)
                </span>
              )}
              {complianceData?.weekly && (
                <span className={`px-2 py-1 text-xs font-medium rounded ${
                  complianceData.weekly.level === 'high' ? 'bg-green-100 text-green-800' :
                  complianceData.weekly.level === 'medium' ? 'bg-blue-100 text-blue-800' :
                  'bg-amber-100 text-amber-800'
                }`}>
                  {complianceData.weekly.emoji} Weekly: {complianceData.weekly.compliance_pct}%
                </span>
              )}
              <button onClick={() => { setShowCompliancePanel(!showCompliancePanel); if (!showCompliancePanel) previewNotification(); }}
                className="text-xs text-purple-600 hover:text-purple-800 font-medium">
                {showCompliancePanel ? 'Hide' : 'Send'} Notification
              </button>
            </div>
          )}

          {showCompliancePanel && (
            <div className="bg-purple-50 border border-purple-200 rounded-lg p-4 mb-4">
              <h3 className="text-sm font-semibold text-purple-800 mb-3">Send Compliance Notification</h3>

              <div className="grid grid-cols-3 gap-3 mb-3">
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Category</label>
                  <select value={notifCategory} onChange={e => { setNotifCategory(e.target.value); setNotifPreview(null); }}
                    className="w-full border rounded px-2 py-1.5 text-sm bg-white">
                    <option value="ema">EMA Low Compliance</option>
                    <option value="screenshots">Screenshot Low Compliance</option>
                    <option value="weekly">Weekly Report</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Delivery</label>
                  <div className="flex gap-2">
                    <label className="flex items-center text-xs">
                      <input type="checkbox" checked={notifDelivery.includes('email')}
                        onChange={e => setNotifDelivery(d => e.target.checked ? [...d, 'email'] : d.filter(x => x !== 'email'))}
                        className="mr-1" /> Email
                    </label>
                    <label className="flex items-center text-xs">
                      <input type="checkbox" checked={notifDelivery.includes('push')}
                        onChange={e => setNotifDelivery(d => e.target.checked ? [...d, 'push'] : d.filter(x => x !== 'push'))}
                        className="mr-1" /> Push
                    </label>
                  </div>
                </div>
                <div>
                  <button onClick={previewNotification}
                    className="mt-4 px-3 py-1.5 bg-purple-100 text-purple-700 text-xs rounded hover:bg-purple-200">
                    🔄 New Variant
                  </button>
                </div>
              </div>

              {/* Editable message */}
              {notifPreview && (
                <div className="bg-white border rounded p-3 mb-3">
                  <label className="block text-xs font-medium text-gray-500 mb-1">Subject (editable)</label>
                  <input
                    value={notifPreview.subject}
                    onChange={e => setNotifPreview(p => ({...p, subject: e.target.value}))}
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm mb-2 font-semibold"
                  />
                  <label className="block text-xs font-medium text-gray-500 mb-1">Message (editable — supports HTML: &lt;b&gt;bold&lt;/b&gt;, &lt;i&gt;italic&lt;/i&gt;, &lt;u&gt;underline&lt;/u&gt;)</label>
                  {/* Formatting toolbar */}
                  <div className="flex gap-1 mb-1">
                    {[
                      { label: 'B', tag: 'b', title: 'Bold', style: 'font-bold' },
                      { label: 'I', tag: 'i', title: 'Italic', style: 'italic' },
                      { label: 'U', tag: 'u', title: 'Underline', style: 'underline' },
                    ].map(fmt => (
                      <button key={fmt.tag} title={fmt.title}
                        onClick={() => {
                          const ta = document.getElementById('notif-body-editor');
                          if (ta) {
                            const start = ta.selectionStart;
                            const end = ta.selectionEnd;
                            const text = notifPreview.body;
                            const selected = text.substring(start, end);
                            const wrapped = `<${fmt.tag}>${selected}</${fmt.tag}>`;
                            const newText = text.substring(0, start) + wrapped + text.substring(end);
                            setNotifPreview(p => ({...p, body: newText}));
                          }
                        }}
                        className={`px-2 py-0.5 text-xs border rounded hover:bg-purple-100 ${fmt.style}`}>
                        {fmt.label}
                      </button>
                    ))}
                    <button title="Line break"
                      onClick={() => {
                        const ta = document.getElementById('notif-body-editor');
                        if (ta) {
                          const pos = ta.selectionStart;
                          const text = notifPreview.body;
                          const newText = text.substring(0, pos) + '<br>' + text.substring(pos);
                          setNotifPreview(p => ({...p, body: newText}));
                        }
                      }}
                      className="px-2 py-0.5 text-xs border rounded hover:bg-purple-100">
                      BR
                    </button>
                  </div>
                  <textarea
                    id="notif-body-editor"
                    value={notifPreview.body}
                    onChange={e => setNotifPreview(p => ({...p, body: e.target.value}))}
                    rows={8}
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm font-mono"
                  />
                  {/* HTML Preview */}
                  <details className="mt-2">
                    <summary className="text-xs text-purple-600 cursor-pointer">Preview formatted message</summary>
                    <div className="mt-1 p-3 bg-gray-50 border rounded text-sm"
                      dangerouslySetInnerHTML={{ __html: notifPreview.body.replace(/\n/g, '<br>') }}
                    />
                  </details>
                </div>
              )}

              {/* Result */}
              {notifResult && (
                <div className={`text-xs mb-2 p-2 rounded ${notifResult.success ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
                  {notifResult.success ? `Sent: ${notifResult.subject}` : `Error: ${notifResult.error}`}
                </div>
              )}

              <button onClick={sendNotification} disabled={notifSending || !notifPreview}
                className="px-4 py-2 bg-purple-600 text-white text-sm font-medium rounded hover:bg-purple-700 disabled:opacity-50">
                {notifSending ? 'Sending...' : 'Send This Notification'}
              </button>

              {/* Communication History */}
              <div className="mt-4 pt-3 border-t border-purple-200">
                <h4 className="text-xs font-bold text-purple-700 mb-2">
                  Communication History
                  {complianceData?.notificationHistory?.length > 0 &&
                    ` (${complianceData.notificationHistory.length})`}
                </h4>
                {(!complianceData?.notificationHistory || complianceData.notificationHistory.length === 0) ? (
                  <div className="text-xs text-gray-400 italic">No notifications sent yet</div>
                ) : (
                  <div className="space-y-2 max-h-60 overflow-y-auto">
                    {complianceData.notificationHistory.map((notif, idx) => {
                      const categoryLabels = { ema: 'EMA Compliance', screenshots: 'Screenshot Compliance', weekly: 'Weekly Report' };
                      const categoryColors = { ema: 'bg-blue-100 text-blue-700', screenshots: 'bg-orange-100 text-orange-700', weekly: 'bg-green-100 text-green-700' };
                      const sentDate = notif.sentAt ? new Date(notif.sentAt) : null;
                      const daysAgo = sentDate ? Math.floor((Date.now() - sentDate.getTime()) / (1000 * 60 * 60 * 24)) : null;

                      return (
                        <div key={idx} className="bg-white border border-purple-100 rounded p-2">
                          <div className="flex items-center justify-between mb-1">
                            <div className="flex items-center gap-2">
                              <span className={`px-1.5 py-0.5 text-[10px] font-medium rounded ${categoryColors[notif.category] || 'bg-gray-100 text-gray-700'}`}>
                                {categoryLabels[notif.category] || notif.category}
                              </span>
                              {notif.deliveryMethods?.map((m, i) => (
                                <span key={i} className="text-[10px] text-gray-400">
                                  {m === 'email' ? '📧' : m === 'push' ? '📱' : m}
                                </span>
                              ))}
                            </div>
                            <span className="text-[10px] text-gray-400">
                              {sentDate ? (
                                daysAgo === 0 ? 'Today' :
                                daysAgo === 1 ? 'Yesterday' :
                                `${daysAgo}d ago`
                              ) : ''}
                            </span>
                          </div>
                          <div className="text-xs text-gray-700 font-medium truncate" title={notif.subject}>
                            {notif.subject || 'No subject'}
                          </div>
                          <div className="text-[10px] text-gray-400 mt-0.5">
                            {sentDate ? sentDate.toLocaleString('en-US', {
                              month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'
                            }) : ''} — by {notif.sentBy || 'unknown'}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="relative">
            <button
              onClick={() => setShowExportOptions(!showExportOptions)}
              disabled={exportLoading}
              className="flex items-center px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:opacity-50"
            >
              <Download size={18} className="mr-2" />
              {exportLoading ? 'Exporting...' : 'Export Data'}
              <ChevronRight size={16} className={`ml-2 transform transition-transform ${showExportOptions ? 'rotate-90' : ''}`} />
            </button>

            {/* Export Options Dropdown */}
            {showExportOptions && !exportLoading && (
              <div className="absolute right-0 mt-2 w-72 bg-white rounded-lg shadow-lg border z-10">
                <div className="p-2">
                  {[1, 2, 3].map(level => (
                    <button
                      key={level}
                      onClick={() => handleExportClick(level)}
                      className="w-full text-left p-3 rounded-md hover:bg-gray-100 transition-colors"
                    >
                      <div className="font-medium text-gray-800">
                        Level {level}: {exportLevelDescriptions[level].name}
                        {level === 3 && <span className="ml-2 text-orange-500 text-xs">(Large)</span>}
                      </div>
                      <div className="text-sm text-gray-500">
                        {exportLevelDescriptions[level].desc}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {exportError && (
          <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
            {exportError}
          </div>
        )}

        {/* Active Export Status */}
        {activeExport && activeExport.status !== 'completed' && (
          <div className="mt-3 p-4 bg-blue-50 border border-blue-200 rounded">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center">
                {activeExport.status === 'processing' ? (
                  <Loader2 className="animate-spin text-blue-500 mr-2" size={18} />
                ) : activeExport.status === 'failed' ? (
                  <XCircle className="text-red-500 mr-2" size={18} />
                ) : (
                  <Clock className="text-blue-500 mr-2" size={18} />
                )}
                <span className="font-medium text-gray-800">
                  Level 3 Export: {activeExport.status === 'processing' ? 'Processing...' : activeExport.status === 'failed' ? 'Failed' : 'Queued'}
                </span>
              </div>
              {activeExport.status === 'failed' && (
                <button
                  onClick={() => setActiveExport(null)}
                  className="text-gray-500 hover:text-gray-700 text-xs"
                >
                  Dismiss
                </button>
              )}
            </div>

            {activeExport.status === 'processing' && (
              <>
                <div className="w-full bg-gray-200 rounded-full h-2 mb-2">
                  <div
                    className="bg-blue-500 h-2 rounded-full transition-all duration-300"
                    style={{ width: `${activeExport.progress || 0}%` }}
                  />
                </div>
                <div className="text-sm text-gray-600">
                  {activeExport.progress ? `${activeExport.progress}% complete` : 'Starting...'}
                  {activeExport.screenshots_processed !== undefined && (
                    <span className="ml-2">
                      ({activeExport.screenshots_processed}/{activeExport.screenshots_total || '?'} screenshots)
                    </span>
                  )}
                </div>
              </>
            )}

            {activeExport.status === 'pending' && (
              <div className="text-sm text-gray-600">
                Export queued. This may take 5-15 minutes for large datasets with screenshots.
              </div>
            )}

            {activeExport.status === 'failed' && (
              <div className="text-sm text-red-600">
                {activeExport.error || 'Export failed. Please try again.'}
              </div>
            )}
          </div>
        )}

        {/* Export Download Ready */}
        {exportDownload && (
          <div className="mt-3 p-3 bg-green-50 border border-green-200 rounded text-green-700 text-sm flex items-center justify-between">
            <div className="flex items-center">
              <CheckCircle className="mr-2" size={18} />
              <a href={exportDownload.url} className="underline font-medium" download>
                Download: {exportDownload.filename}
              </a>
            </div>
            <button
              onClick={() => {
                setExportDownload(null);
                setActiveExport(null);
              }}
              className="text-gray-500 hover:text-gray-700 text-xs"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Data Freshness Indicator */}
        <div className="mt-4 pt-4 border-t flex items-center justify-between text-sm">
          <div className="text-gray-600">
            <strong>Live Data:</strong> Fetched on page load.
            {lastUpdated && (
              <span className="ml-2">
                Last updated: {lastUpdated.toLocaleString('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit', second: '2-digit', hour12: true })} EST
              </span>
            )}
          </div>
          <button
            onClick={fetchSummary}
            disabled={loading}
            className="flex items-center px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 text-xs"
          >
            <RefreshCw size={14} className={`mr-1 ${loading ? 'animate-spin' : ''}`} />
            {loading ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>
      </div>

      {/* Summary Stats - Key Metrics First */}
      <div className="grid grid-cols-5 gap-4 mb-6">
        {/* EMAs/Check-ins - Primary Metric */}
        <div className="bg-green-50 border-2 border-green-200 rounded-lg shadow p-4">
          <div className="text-gray-600 text-sm mb-1 font-medium">Total EMAs Complete</div>
          <div className="text-3xl font-bold" style={{ color: COLORS.green }}>{totalCheckins}</div>
        </div>
        {/* Reddit Screenshots */}
        <div className="bg-white rounded-lg shadow p-4 border-l-4" style={{ borderLeftColor: PLATFORM_COLORS.reddit }}>
          <div className="flex items-center text-gray-500 text-sm mb-1">
            <Camera size={14} className="mr-1" style={{ color: PLATFORM_COLORS.reddit }} /> Reddit Screenshots
          </div>
          <div className="text-2xl font-bold" style={{ color: PLATFORM_COLORS.reddit }}>
            {dailySummary.reduce((sum, d) => sum + (d.reddit || 0), 0).toLocaleString()}
          </div>
        </div>
        {/* Twitter/X Screenshots */}
        <div className="bg-white rounded-lg shadow p-4 border-l-4" style={{ borderLeftColor: PLATFORM_COLORS.twitter }}>
          <div className="flex items-center text-gray-500 text-sm mb-1">
            <Camera size={14} className="mr-1" style={{ color: PLATFORM_COLORS.twitter }} /> X Screenshots
          </div>
          <div className="text-2xl font-bold" style={{ color: PLATFORM_COLORS.twitter }}>
            {dailySummary.reduce((sum, d) => sum + (d.twitter || 0), 0).toLocaleString()}
          </div>
        </div>
        {/* Crisis Days */}
        <div className={`rounded-lg shadow p-4 ${
          dailySummary.some(d => d.crisis_indicated)
            ? 'bg-red-50 border-2 border-red-300'
            : 'bg-white'
        }`}>
          <div className="flex items-center text-gray-500 text-sm mb-1">
            <AlertTriangle size={14} className="mr-1" /> Crisis Days
          </div>
          <div className={`text-2xl font-bold ${
            dailySummary.filter(d => d.crisis_indicated).length > 0 ? 'text-red-600' : 'text-green-600'
          }`}>
            {dailySummary.filter(d => d.crisis_indicated).length}
          </div>
        </div>
        {/* Safety Alerts */}
        <div className="bg-white rounded-lg shadow p-4">
          <div className="flex items-center text-gray-500 text-sm mb-1">
            <AlertTriangle size={14} className="mr-1" /> Safety Alerts
          </div>
          <div className="text-2xl font-bold" style={{ color: totalAlerts > 0 ? COLORS.red : COLORS.green }}>
            {totalAlerts}
          </div>
        </div>
      </div>

      {/* Loading State */}
      {loading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="animate-spin text-blue-500 mr-3" size={32} />
          <span className="text-gray-600">Loading participant data...</span>
        </div>
      )}

      {/* Error State */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">
          <strong>Error:</strong> {error}
        </div>
      )}

      {/* Daily Summary Table */}
      {!loading && !error && summary && (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <div className="px-6 py-4 border-b bg-gray-50">
            <h2 className="text-lg font-semibold text-gray-800">Daily Summary</h2>
            <p className="text-sm text-gray-500">Click on a date to view detailed data for that day</p>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-gray-600">Date</th>
                  <th className="px-4 py-3 text-center text-sm font-semibold text-gray-600 bg-green-50">EMAs</th>
                  <th className="px-4 py-3 text-center text-sm font-semibold" style={{ color: PLATFORM_COLORS.reddit }}>Reddit</th>
                  <th className="px-4 py-3 text-center text-sm font-semibold" style={{ color: PLATFORM_COLORS.twitter }}>X</th>
                  <th className="px-4 py-3 text-center text-sm font-semibold text-red-600">Crisis</th>
                  <th className="px-4 py-3 text-center text-sm font-semibold text-gray-600">Total Shots</th>
                  <th className="px-4 py-3 text-center text-sm font-semibold text-gray-600">Alerts</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {dailySummary.slice().reverse().map((day, idx) => (
                  <tr
                    key={idx}
                    className={`hover:bg-blue-50 cursor-pointer transition-colors ${
                      day.crisis_indicated ? 'bg-red-50' : ''
                    }`}
                    onClick={() => goToDayView(currentParticipantId, day.date)}
                  >
                    <td className="px-4 py-3 font-medium text-blue-600 hover:underline">
                      {day.date}
                    </td>
                    {/* EMAs - Primary Column */}
                    <td className="px-4 py-3 text-center bg-green-50">
                      <span
                        className={`px-3 py-1 rounded-full text-sm font-bold ${
                          day.checkins >= 3
                            ? 'bg-green-200 text-green-800'
                            : day.checkins > 0
                            ? 'bg-orange-200 text-orange-800'
                            : 'bg-red-100 text-red-600'
                        }`}
                      >
                        {day.checkins}/3
                      </span>
                    </td>
                    {/* Reddit Screenshots */}
                    <td className="px-4 py-3 text-center">
                      <span className="font-medium" style={{ color: PLATFORM_COLORS.reddit }}>
                        {day.reddit || 0}
                      </span>
                    </td>
                    {/* Twitter/X Screenshots */}
                    <td className="px-4 py-3 text-center">
                      <span className="font-medium" style={{ color: PLATFORM_COLORS.twitter }}>
                        {day.twitter || 0}
                      </span>
                    </td>
                    {/* Crisis Flag */}
                    <td className="px-4 py-3 text-center">
                      {day.crisis_indicated ? (
                        <span className="px-2 py-1 rounded bg-red-500 text-white text-xs font-bold animate-pulse">
                          YES
                        </span>
                      ) : (
                        <span className="text-gray-400">—</span>
                      )}
                    </td>
                    {/* Total Screenshots */}
                    <td className={`px-4 py-3 text-center ${getActivityClass(day.screenshots, 50)}`}>
                      {day.screenshots}
                    </td>
                    {/* Safety Alerts */}
                    <td className="px-4 py-3 text-center">
                      {day.safety_alerts > 0 ? (
                        <span className="px-2 py-1 rounded-full bg-red-100 text-red-800 text-xs font-medium">
                          {day.safety_alerts}
                        </span>
                      ) : (
                        <span className="text-gray-400">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {dailySummary.length === 0 && (
            <div className="text-center py-12 text-gray-500">
              No data recorded for this participant yet.
            </div>
          )}
        </div>
      )}

      {/* Level 3 Export Confirmation Modal - at root level for proper z-index */}
      {showExportConfirm && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4 p-6">
            <div className="flex items-center mb-4">
              <AlertTriangle className="text-orange-500 mr-3" size={28} />
              <h3 className="text-lg font-bold text-gray-800">Full Export Warning</h3>
            </div>

            <div className="mb-4 text-gray-600 space-y-3">
              <p>
                <strong>Level 3 exports include all screenshots</strong> and can be very large
                ({totalScreenshots.toLocaleString()} screenshots for this participant).
              </p>
              <p className="text-orange-600 font-medium">
                This may:
              </p>
              <ul className="list-disc list-inside text-sm space-y-1 text-orange-700">
                <li>Take 5-15 minutes or longer to generate</li>
                <li>Incur significant Firebase read/download costs</li>
                <li>Result in a large ZIP file (potentially 100MB+)</li>
              </ul>
              <p className="text-sm">
                Consider using <strong>Level 2</strong> if you only need OCR text data without images.
              </p>
            </div>

            <div className="flex space-x-3">
              <button
                onClick={() => {
                  setShowExportConfirm(false);
                  setPendingExportLevel(null);
                }}
                className="flex-1 px-4 py-2 bg-gray-200 text-gray-700 rounded-md hover:bg-gray-300"
              >
                Cancel
              </button>
              <button
                onClick={() => executeExport(pendingExportLevel)}
                className="flex-1 px-4 py-2 bg-orange-500 text-white rounded-md hover:bg-orange-600 font-medium"
              >
                Proceed with Export
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Mark Inactive Confirmation Modal */}
      {showInactiveConfirm && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4 p-6">
            <div className="flex items-center mb-4">
              <AlertTriangle className="text-orange-500 mr-3" size={28} />
              <h3 className="text-lg font-bold text-gray-800">Mark Participant Inactive</h3>
            </div>

            <div className="mb-4 text-gray-600 space-y-3">
              <p>
                Are you sure you want to mark <strong>{currentParticipantId}</strong> as inactive?
              </p>
              <p className="text-sm">
                This will move them to the bottom of the participant list.
                You can reactivate them at any time by clicking the status badge again.
              </p>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Reason (optional):
                </label>
                <input
                  type="text"
                  value={inactiveReason}
                  onChange={(e) => setInactiveReason(e.target.value)}
                  placeholder="e.g., Dropped out, Device issue, etc."
                  className="w-full px-3 py-2 border rounded-md text-sm"
                />
              </div>
            </div>

            <div className="flex space-x-3">
              <button
                onClick={() => {
                  setShowInactiveConfirm(false);
                  setInactiveReason('');
                }}
                className="flex-1 px-4 py-2 bg-gray-200 text-gray-700 rounded-md hover:bg-gray-300"
              >
                Cancel
              </button>
              <button
                onClick={() => handleToggleActiveStatus(false)}
                disabled={activeStatusSaving}
                className="flex-1 px-4 py-2 bg-orange-500 text-white rounded-md hover:bg-orange-600 font-medium disabled:opacity-50"
              >
                {activeStatusSaving ? 'Saving...' : 'Mark Inactive'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ParticipantDetailScreen;
