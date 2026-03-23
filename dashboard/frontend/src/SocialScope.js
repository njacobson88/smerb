// SocialScope.js - Main Dashboard Application

import React, { useState, useEffect } from 'react';
import { Users, Download, AlertTriangle, LogOut, Settings, Clock } from 'lucide-react';
import OverallScreen from './OverallScreen';
import ParticipantDetailScreen from './ParticipantDetailScreen';
import DayDetailScreen from './DayDetailScreen';
import Login, { auth, signOut, onAuthStateChanged, getIdToken } from './Login';
import UserManagement from './UserManagement';
import InstallPage from './InstallPage';

// API Configuration
// In production, REACT_APP_API_URL should point to the Cloud Run service
// In development, use localhost
const isLocal = process.env.REACT_APP_LOCAL === 'true';
const API_BASE_URL = isLocal
  ? "http://localhost:8080"
  : (process.env.REACT_APP_API_URL || "https://socialscope-dashboard-api-436153481478.us-central1.run.app");

export { API_BASE_URL, getIdToken };

// Global callback for network blocked detection — set by SocialScope component
let onNetworkBlocked = null;
export const setNetworkBlockedHandler = (handler) => { onNetworkBlocked = handler; };

// Authenticated fetch helper - includes auth token in requests
export const authFetch = async (url, options = {}) => {
  const token = await getIdToken();
  const headers = {
    ...options.headers,
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  let response;
  try {
    response = await fetch(url, { ...options, headers });
  } catch (fetchErr) {
    // Network-level failure (e.g. CORS block from 403 preflight)
    if (onNetworkBlocked) onNetworkBlocked();
    throw fetchErr;
  }

  // Detect IP whitelist block from backend
  if (response.status === 403) {
    const cloned = response.clone();
    const data = await cloned.json().catch(() => ({}));
    if (data.error === 'Access denied' || data.message?.includes('Dartmouth')) {
      if (onNetworkBlocked) onNetworkBlocked();
      throw new Error('Dartmouth network required');
    }
  }

  return response;
};

const SocialScope = () => {
  // Route /install to the install page (no auth required, for participants)
  if (window.location.pathname === '/install') {
    return <InstallPage />;
  }
  return <SocialScopeDashboard />;
};

const SocialScopeDashboard = () => {
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [networkBlocked, setNetworkBlocked] = useState(false);
  const [environment, setEnvironment] = useState(null);
  const [activeTab, setActiveTab] = useState('overall');
  const [selectedParticipant, setSelectedParticipant] = useState(null);
  const [selectedDate, setSelectedDate] = useState(null);
  const [participantList, setParticipantList] = useState([]);

  // Listen for auth state changes
  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (currentUser) => {
      setUser(currentUser);
      setAuthLoading(false);
    });
    return () => unsubscribe();
  }, []);

  // Register global network-blocked handler
  useEffect(() => {
    setNetworkBlockedHandler(() => setNetworkBlocked(true));
    return () => setNetworkBlockedHandler(null);
  }, []);

  // Fetch environment for dev banner
  useEffect(() => {
    fetch(`${API_BASE_URL}/api/config/environment`)
      .then(r => r.json())
      .then(d => setEnvironment(d.environment))
      .catch(() => {});
  }, []);

  // Handle logout
  const handleLogout = async () => {
    try {
      await signOut(auth);
      setUser(null);
    } catch (error) {
      console.error('Logout error:', error);
    }
  };

  // Show loading while checking auth state
  if (authLoading) {
    return (
      <div className="min-h-screen bg-gray-100 flex items-center justify-center">
        <div className="text-gray-600">Loading...</div>
      </div>
    );
  }

  // Show network blocked screen
  if (networkBlocked) {
    return (
      <div className="min-h-screen bg-gray-100 flex items-center justify-center">
        <div className="bg-white rounded-lg shadow-lg p-8 max-w-md w-full text-center">
          <h1 className="text-3xl font-bold bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent mb-4">
            SocialScope
          </h1>
          <div className="bg-amber-50 border border-amber-200 rounded-md p-4 mb-6">
            <div className="flex justify-center mb-3">
              <AlertTriangle size={32} className="text-amber-500" />
            </div>
            <p className="text-amber-800 font-medium text-lg">Dartmouth Network Required</p>
            <p className="text-amber-700 text-sm mt-2">
              The SocialScope dashboard is only accessible from the Dartmouth network.
              Please connect to <strong>Dartmouth WiFi</strong> or the <strong>Dartmouth VPN</strong> and try again.
            </p>
          </div>
          <div className="space-y-3">
            <button
              onClick={() => { setNetworkBlocked(false); window.location.reload(); }}
              className="w-full bg-gradient-to-r from-blue-600 to-purple-600 text-white font-medium py-3 rounded-md hover:from-blue-700 hover:to-purple-700 transition-all"
            >
              Retry Connection
            </button>
            <button
              onClick={handleLogout}
              className="w-full text-gray-500 hover:text-gray-700 text-sm font-medium py-2"
            >
              Sign Out
            </button>
          </div>
          <div className="mt-6 pt-4 border-t text-sm text-gray-500">
            <p>Dartmouth College</p>
          </div>
        </div>
      </div>
    );
  }

  // Show login if not authenticated
  if (!user) {
    return <Login onLoginSuccess={setUser} />;
  }

  // Navigation handlers
  const goToOverallView = () => {
    setSelectedParticipant(null);
    setSelectedDate(null);
    setActiveTab('overall');
  };

  const goToParticipantView = (participantId) => {
    setSelectedParticipant(participantId);
    setSelectedDate(null);
    setActiveTab('participant');
  };

  const goToDayView = (participantId, date) => {
    setSelectedParticipant(participantId);
    setSelectedDate(date);
    setActiveTab('day');
  };

  return (
    <div className="min-h-screen bg-gray-100">
      {/* Dev Environment Banner */}
      {environment === 'dev' && (
        <div className="bg-orange-500 text-white text-center py-2 font-bold text-sm">
          DEV ENVIRONMENT — Data in dev_ collections
        </div>
      )}
      {/* Header */}
      <header className="bg-gradient-to-r from-blue-600 to-purple-600 shadow-lg">
        <nav className="container mx-auto px-4 py-4 flex justify-between items-center">
          <div className="flex items-center space-x-3">
            <div className="text-2xl font-bold text-white">SocialScope</div>
            <span className="text-blue-200 text-sm">Research Dashboard</span>
          </div>
          <div className="flex items-center space-x-4">
            <div className="flex space-x-2">
            <button
              onClick={() => { goToOverallView(); setActiveTab('overall'); }}
              className={`flex items-center px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                activeTab === 'overall'
                  ? 'bg-white text-blue-600'
                  : 'text-white hover:bg-white/20'
              }`}
            >
              <Users size={18} className="mr-2" /> Overview
            </button>
            <button
              onClick={() => setActiveTab('export')}
              className={`flex items-center px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                activeTab === 'export'
                  ? 'bg-white text-blue-600'
                  : 'text-white hover:bg-white/20'
              }`}
            >
              <Download size={18} className="mr-2" /> Export
            </button>
            <button
              onClick={() => setActiveTab('alerts')}
              className={`flex items-center px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                activeTab === 'alerts'
                  ? 'bg-white text-blue-600'
                  : 'text-white hover:bg-white/20'
              }`}
            >
              <AlertTriangle size={18} className="mr-2" /> Safety Alerts
            </button>
            <button
              onClick={() => setActiveTab('users')}
              className={`flex items-center px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                activeTab === 'users'
                  ? 'bg-white text-blue-600'
                  : 'text-white hover:bg-white/20'
              }`}
            >
              <Settings size={18} className="mr-2" /> Users
            </button>
            </div>
            {/* User info and logout */}
            <div className="flex items-center space-x-3 ml-4 pl-4 border-l border-white/30">
              <span className="text-white/80 text-sm">{user.email}</span>
              <button
                onClick={handleLogout}
                className="flex items-center px-3 py-2 rounded-md text-sm font-medium text-white/80 hover:text-white hover:bg-white/20 transition-colors"
                title="Sign out"
              >
                <LogOut size={18} />
              </button>
            </div>
          </div>
        </nav>
      </header>

      {/* Main Content */}
      <main className="container mx-auto px-4 py-8">
        {activeTab === 'overall' && (
          <OverallScreen
            goToParticipantView={goToParticipantView}
            goToDayView={goToDayView}
            setParticipantList={setParticipantList}
          />
        )}

        {activeTab === 'participant' && selectedParticipant && (
          <ParticipantDetailScreen
            participantId={selectedParticipant}
            participantList={participantList}
            goToOverallView={goToOverallView}
            goToParticipantView={goToParticipantView}
            goToDayView={goToDayView}
          />
        )}

        {activeTab === 'day' && selectedParticipant && selectedDate && (
          <DayDetailScreen
            participantId={selectedParticipant}
            date={selectedDate}
            goToOverallView={goToOverallView}
            goToParticipantView={goToParticipantView}
            goToDayView={goToDayView}
          />
        )}

        {activeTab === 'export' && (
          <ExportScreen />
        )}

        {activeTab === 'alerts' && (
          <AlertsScreen goToParticipantView={goToParticipantView} />
        )}

        {activeTab === 'users' && (
          <UserManagement currentUser={user} />
        )}
      </main>

      {/* Footer */}
      <footer className="bg-gray-800 text-gray-400 py-4 mt-8">
        <div className="container mx-auto px-4 text-center text-sm">
          SocialScope Dashboard - Dartmouth College
          <br />
          <span className="text-gray-500">Access restricted to Dartmouth network</span>
        </div>
      </footer>
    </div>
  );
};


// Export Screen Component
const ExportScreen = () => {
  const [participantId, setParticipantId] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [exportLevel, setExportLevel] = useState(1);
  const [loading, setLoading] = useState(false);
  const [estimating, setEstimating] = useState(false);
  const [error, setError] = useState(null);
  const [downloadUrl, setDownloadUrl] = useState(null);
  const [estimate, setEstimate] = useState(null);
  const [abortController, setAbortController] = useState(null);
  // Async export state
  const [asyncJobId, setAsyncJobId] = useState(null);
  const [asyncStatus, setAsyncStatus] = useState(null);
  // My exports state
  const [myExports, setMyExports] = useState([]);
  const [loadingExports, setLoadingExports] = useState(true);

  // Fetch estimate when participant ID changes
  const fetchEstimate = async () => {
    if (!participantId.trim()) {
      setEstimate(null);
      return;
    }

    setEstimating(true);
    setError(null);

    try {
      const params = new URLSearchParams({ participant_id: participantId });
      if (startDate) params.append('start_date', startDate);
      if (endDate) params.append('end_date', endDate);

      const response = await authFetch(`${API_BASE_URL}/api/export/estimate?${params}`);

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to get estimate');
      }

      const data = await response.json();
      setEstimate(data);
    } catch (err) {
      if (err.name !== 'AbortError') {
        setError(err.message);
      }
    } finally {
      setEstimating(false);
    }
  };

  // Debounce estimate fetching
  React.useEffect(() => {
    const timer = setTimeout(() => {
      if (participantId.trim()) {
        fetchEstimate();
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [participantId, startDate, endDate]);

  // Fetch user's export jobs
  const fetchMyExports = async () => {
    try {
      const response = await authFetch(`${API_BASE_URL}/api/export/jobs`);
      if (response.ok) {
        const data = await response.json();
        console.log('[My Exports] Fetched jobs:', data.jobs?.length || 0, data.jobs);
        setMyExports(data.jobs || []);
      } else {
        console.error('[My Exports] Failed to fetch:', response.status);
      }
    } catch (err) {
      console.error('[My Exports] Error fetching exports:', err);
    } finally {
      setLoadingExports(false);
    }
  };

  // Cancel an export job
  const handleCancelExport = async (jobId) => {
    try {
      const response = await authFetch(`${API_BASE_URL}/api/export/jobs/${jobId}`, {
        method: 'DELETE',
      });
      if (response.ok) {
        // Refresh the exports list
        fetchMyExports();
      } else {
        const errData = await response.json().catch(() => ({}));
        console.error('Failed to cancel export:', errData.detail);
      }
    } catch (err) {
      console.error('Failed to cancel export:', err);
    }
  };

  React.useEffect(() => {
    fetchMyExports();
    // Refresh every 10 seconds if there are pending/processing jobs
    const interval = setInterval(() => {
      if (myExports.some(j => j.status === 'pending' || j.status === 'processing')) {
        fetchMyExports();
      }
    }, 10000);
    return () => clearInterval(interval);
  }, [myExports.length]);

  // Poll for async job status
  React.useEffect(() => {
    if (!asyncJobId) return;

    const pollStatus = async () => {
      try {
        const response = await authFetch(`${API_BASE_URL}/api/export/jobs/${asyncJobId}`);
        if (response.ok) {
          const data = await response.json();
          setAsyncStatus(data);

          if (data.status === 'completed') {
            setDownloadUrl(data.downloadUrl);
            setLoading(false);
          } else if (data.status === 'failed') {
            setError(data.error || 'Export failed');
            setLoading(false);
          }
        }
      } catch (err) {
        console.error('Failed to poll job status:', err);
      }
    };

    // Poll every 5 seconds while job is active
    const interval = setInterval(() => {
      if (asyncStatus?.status === 'pending' || asyncStatus?.status === 'processing') {
        pollStatus();
      }
    }, 5000);

    // Initial poll
    pollStatus();

    return () => clearInterval(interval);
  }, [asyncJobId, asyncStatus?.status]);

  const handleExport = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setDownloadUrl(null);
    setAsyncJobId(null);
    setAsyncStatus(null);

    // For Level 3, use async export
    if (exportLevel === 3) {
      try {
        const response = await authFetch(`${API_BASE_URL}/api/export/async`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            participant_id: participantId,
            export_level: exportLevel,
            start_date: startDate || null,
            end_date: endDate || null,
          }),
        });

        if (!response.ok) {
          const errData = await response.json().catch(() => ({}));
          throw new Error(errData.detail || 'Failed to start export');
        }

        const data = await response.json();
        setAsyncJobId(data.jobId);
        setAsyncStatus({ status: 'pending' });
        setLoading(false);
        // Refresh My Exports list after a brief delay to ensure Firestore write completes
        setTimeout(() => {
          fetchMyExports();
        }, 1000);
      } catch (err) {
        setError(err.message);
        setLoading(false);
      }
      return;
    }

    // For Level 1 & 2, use synchronous export
    const controller = new AbortController();
    setAbortController(controller);

    try {
      const params = new URLSearchParams({
        participant_id: participantId,
        export_level: exportLevel.toString()
      });
      if (startDate) params.append('start_date', startDate);
      if (endDate) params.append('end_date', endDate);

      const response = await authFetch(`${API_BASE_URL}/api/export?${params}`, {
        signal: controller.signal
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || 'Export failed');
      }

      const data = await response.json();
      // Handle both absolute URLs (signed Firebase Storage) and relative paths
      const url = data.download_url;
      setDownloadUrl(url?.startsWith('http') ? url : `${API_BASE_URL}${url}`);
    } catch (err) {
      if (err.name !== 'AbortError') {
        setError(err.message);
      }
    } finally {
      setLoading(false);
      setAbortController(null);
    }
  };

  const handleCancel = () => {
    if (abortController) {
      abortController.abort();
    }
    setLoading(false);
    setAbortController(null);
    setAsyncJobId(null);
    setAsyncStatus(null);
  };

  const getLevelInfo = (level) => {
    if (!estimate?.estimates) return null;
    return estimate.estimates[`level${level}`];
  };

  return (
    <div className="bg-white rounded-lg shadow-md p-6 max-w-2xl mx-auto">
      <h2 className="text-2xl font-bold text-gray-800 mb-6">Export Participant Data</h2>

      <form onSubmit={handleExport} className="space-y-6">
        {/* Participant ID */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Participant ID
          </label>
          <input
            type="text"
            value={participantId}
            onChange={(e) => setParticipantId(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            placeholder="e.g., abc123"
            required
          />
        </div>

        {/* Date Range */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Start Date (optional)
            </label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              End Date (optional)
            </label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
          </div>
        </div>

        {/* Estimate Loading */}
        {estimating && (
          <div className="text-sm text-gray-500 flex items-center">
            <div className="animate-spin h-4 w-4 border-2 border-blue-500 border-t-transparent rounded-full mr-2"></div>
            Calculating export sizes...
          </div>
        )}

        {/* Data Summary */}
        {estimate && !estimating && (
          <div className="bg-gray-50 rounded-lg p-4 border">
            <div className="text-sm text-gray-600 mb-3">
              <strong>Data Summary:</strong> {estimate.event_count} events, {estimate.screenshot_count} screenshots, {estimate.ema_count} EMAs, {estimate.alert_count} alerts
            </div>
          </div>
        )}

        {/* Export Level Selection */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-3">
            Export Level
          </label>
          <div className="space-y-3">
            {/* Level 1 */}
            <label className={`block p-4 border rounded-lg cursor-pointer transition-colors ${
              exportLevel === 1 ? 'border-blue-500 bg-blue-50' : 'border-gray-200 hover:border-gray-300'
            }`}>
              <div className="flex items-start">
                <input
                  type="radio"
                  name="exportLevel"
                  value={1}
                  checked={exportLevel === 1}
                  onChange={() => setExportLevel(1)}
                  className="mt-1 mr-3"
                />
                <div className="flex-1">
                  <div className="font-medium text-gray-800">Level 1: Metadata + EMA + Alerts</div>
                  <div className="text-sm text-gray-500">Participant info, EMA responses, and safety alerts</div>
                  {getLevelInfo(1) && (
                    <div className="text-sm text-blue-600 mt-1">
                      Est. size: {getLevelInfo(1).size_display} • {getLevelInfo(1).time_display}
                    </div>
                  )}
                </div>
              </div>
            </label>

            {/* Level 2 */}
            <label className={`block p-4 border rounded-lg cursor-pointer transition-colors ${
              exportLevel === 2 ? 'border-blue-500 bg-blue-50' : 'border-gray-200 hover:border-gray-300'
            }`}>
              <div className="flex items-start">
                <input
                  type="radio"
                  name="exportLevel"
                  value={2}
                  checked={exportLevel === 2}
                  onChange={() => setExportLevel(2)}
                  className="mt-1 mr-3"
                />
                <div className="flex-1">
                  <div className="font-medium text-gray-800">Level 2: Level 1 + Events + OCR</div>
                  <div className="text-sm text-gray-500">All screenshot events with extracted text data</div>
                  {getLevelInfo(2) && (
                    <div className="text-sm text-blue-600 mt-1">
                      Est. size: {getLevelInfo(2).size_display} • {getLevelInfo(2).time_display}
                    </div>
                  )}
                </div>
              </div>
            </label>

            {/* Level 3 */}
            <label className={`block p-4 border rounded-lg cursor-pointer transition-colors ${
              exportLevel === 3 ? 'border-blue-500 bg-blue-50' : 'border-gray-200 hover:border-gray-300'
            }`}>
              <div className="flex items-start">
                <input
                  type="radio"
                  name="exportLevel"
                  value={3}
                  checked={exportLevel === 3}
                  onChange={() => setExportLevel(3)}
                  className="mt-1 mr-3"
                />
                <div className="flex-1">
                  <div className="font-medium text-gray-800">Level 3: Full Export with Screenshots</div>
                  <div className="text-sm text-gray-500">Everything including all screenshot images</div>
                  {getLevelInfo(3) && (
                    <div className="text-sm text-orange-600 mt-1">
                      Est. size: {getLevelInfo(3).size_display} • {getLevelInfo(3).time_display}
                    </div>
                  )}
                  <div className="mt-2 p-2 bg-yellow-50 border border-yellow-200 rounded text-xs text-yellow-800">
                    ⚠️ Large export - runs in background. Check "My Exports" below for status.
                  </div>
                </div>
              </div>
            </label>
          </div>
        </div>


        {/* Async Export Progress */}
        {asyncStatus && (asyncStatus.status === 'pending' || asyncStatus.status === 'processing') && (
          <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
            <div className="flex items-center mb-2">
              <div className="animate-spin h-5 w-5 border-2 border-blue-500 border-t-transparent rounded-full mr-3"></div>
              <span className="font-medium text-blue-800">
                {asyncStatus.status === 'pending' && 'Starting export...'}
                {asyncStatus.status === 'processing' && 'Processing export...'}
              </span>
            </div>
            {asyncStatus.screenshotTotal > 0 && (
              <div className="mt-2">
                <div className="text-sm text-blue-700 mb-1">
                  Downloading screenshots: {asyncStatus.screenshotProgress || 0} / {asyncStatus.screenshotTotal}
                </div>
                <div className="w-full bg-blue-200 rounded-full h-2">
                  <div
                    className="bg-blue-600 h-2 rounded-full transition-all"
                    style={{ width: `${((asyncStatus.screenshotProgress || 0) / asyncStatus.screenshotTotal) * 100}%` }}
                  ></div>
                </div>
              </div>
            )}
            <p className="text-xs text-blue-600 mt-2">
              This may take several minutes. Check "My Exports" below for status.
            </p>
          </div>
        )}

        {/* Export / Cancel Buttons */}
        <div className="flex gap-3">
          <button
            type="submit"
            disabled={loading || !participantId}
            className="flex-1 bg-blue-600 text-white font-medium py-3 rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? (
              <span className="flex items-center justify-center">
                <div className="animate-spin h-5 w-5 border-2 border-white border-t-transparent rounded-full mr-2"></div>
                {exportLevel === 3 ? 'Export in Progress...' : 'Generating Export...'}
              </span>
            ) : (
              exportLevel === 3 ? 'Start Background Export' : 'Export Data'
            )}
          </button>

          {loading && (
            <button
              type="button"
              onClick={handleCancel}
              className="px-6 py-3 bg-red-100 text-red-700 font-medium rounded-md hover:bg-red-200 transition-colors"
            >
              Cancel
            </button>
          )}
        </div>
      </form>

      {/* Error Message */}
      {error && (
        <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-md text-red-700">
          {error}
        </div>
      )}

      {/* Download Link */}
      {downloadUrl && (
        <div className="mt-4 p-4 bg-green-50 border border-green-200 rounded-md">
          <p className="text-green-700 mb-2 font-medium">Export ready!</p>
          <a
            href={downloadUrl}
            className="inline-flex items-center px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700"
            download
          >
            <Download size={18} className="mr-2" />
            Download ZIP file
          </a>
        </div>
      )}

      {/* My Exports Section */}
      <div className="mt-8 border-t pt-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-4 flex items-center">
          <Clock size={20} className="mr-2" />
          My Exports
        </h3>

        {loadingExports ? (
          <div className="text-gray-500 text-sm">Loading exports...</div>
        ) : myExports.length === 0 ? (
          <div className="text-gray-500 text-sm p-4 bg-gray-50 rounded-lg text-center">
            No exports yet. Start an export above.
          </div>
        ) : (
          <div className="space-y-3">
            {myExports.map((job) => (
              <div
                key={job.jobId}
                className={`p-4 rounded-lg border ${
                  job.status === 'completed' ? 'bg-green-50 border-green-200' :
                  job.status === 'failed' ? 'bg-red-50 border-red-200' :
                  'bg-blue-50 border-blue-200'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div>
                    <div className="font-medium text-gray-800">
                      {job.participantId} - Level {job.exportLevel}
                    </div>
                    <div className="text-xs text-gray-500">
                      Started: {job.createdAt ? new Date(job.createdAt).toLocaleString('en-US', {
                        timeZone: 'America/New_York',
                        month: 'short', day: 'numeric',
                        hour: 'numeric', minute: '2-digit', hour12: true
                      }) : 'Unknown'} EST
                    </div>
                  </div>
                  <div className="text-right">
                    {job.status === 'completed' && (
                      <a
                        href={job.downloadUrl}
                        className="inline-flex items-center px-3 py-1 bg-green-600 text-white text-sm rounded hover:bg-green-700"
                        download
                      >
                        <Download size={14} className="mr-1" />
                        Download
                      </a>
                    )}
                    {job.status === 'processing' && (
                      <div className="text-blue-700">
                        <div className="flex items-center text-sm font-medium">
                          <div className="animate-spin h-4 w-4 border-2 border-blue-500 border-t-transparent rounded-full mr-2"></div>
                          Processing...
                        </div>
                        {job.screenshotTotal > 0 && (
                          <div className="text-xs mt-1">
                            {job.screenshotProgress || 0}/{job.screenshotTotal} screenshots
                          </div>
                        )}
                        {job.timeEstimate && (
                          <div className="text-xs text-blue-600">{job.timeEstimate}</div>
                        )}
                        <button
                          onClick={() => handleCancelExport(job.jobId)}
                          className="mt-2 px-2 py-1 text-xs bg-red-100 text-red-700 rounded hover:bg-red-200"
                        >
                          Cancel
                        </button>
                      </div>
                    )}
                    {job.status === 'pending' && (
                      <div className="text-blue-600 text-sm">
                        <div className="flex items-center">
                          <div className="animate-pulse h-2 w-2 bg-blue-500 rounded-full mr-2"></div>
                          Queued...
                        </div>
                        <button
                          onClick={() => handleCancelExport(job.jobId)}
                          className="mt-2 px-2 py-1 text-xs bg-red-100 text-red-700 rounded hover:bg-red-200"
                        >
                          Cancel
                        </button>
                      </div>
                    )}
                    {job.status === 'cancelled' && (
                      <div className="text-gray-500 text-sm">
                        Cancelled
                      </div>
                    )}
                    {job.status === 'failed' && (
                      <div className="text-red-600 text-sm">
                        Failed: {job.error || 'Unknown error'}
                      </div>
                    )}
                  </div>
                </div>
                {/* Progress bar for processing jobs */}
                {job.status === 'processing' && job.screenshotTotal > 0 && (
                  <div className="mt-2 w-full bg-blue-200 rounded-full h-1.5">
                    <div
                      className="bg-blue-600 h-1.5 rounded-full transition-all"
                      style={{ width: `${((job.screenshotProgress || 0) / job.screenshotTotal) * 100}%` }}
                    ></div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};


// Alerts Screen Component
const AlertsScreen = ({ goToParticipantView }) => {
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [cacheInfo, setCacheInfo] = useState(null);

  // On-call roster state
  const [roster, setRoster] = useState({});
  const [rosterEditing, setRosterEditing] = useState(null);
  const [rosterForm, setRosterForm] = useState({ name: '', email: '', phone: '' });
  const [rosterSaving, setRosterSaving] = useState(false);
  const [dashboardUsers, setDashboardUsers] = useState([]);

  // Follow-ups state
  const [followups, setFollowups] = useState([]);

  // Disposition logging state
  const [expandedAlert, setExpandedAlert] = useState(null);
  const [dispositionForm, setDispositionForm] = useState({ disposition: '', notes: '', outreach_method: '' });
  const [dispositionSaving, setDispositionSaving] = useState(false);
  const [dispositionSuccess, setDispositionSuccess] = useState(null);

  const fetchAlerts = React.useCallback(async () => {
    setLoading(true);
    try {
      const response = await authFetch(`${API_BASE_URL}/api/safety-alerts`);
      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to fetch alerts');
      }
      const data = await response.json();
      setAlerts(data.alerts || []);
      setCacheInfo({ fromCache: data.fromCache, refreshedAt: data.refreshedAt });
      setLastUpdated(new Date());
      setError(null);
    } catch (err) { setError(err.message); } finally { setLoading(false); }
  }, []);

  const fetchRoster = React.useCallback(async () => {
    try {
      const res = await authFetch(`${API_BASE_URL}/api/oncall/roster`);
      if (res.ok) { const data = await res.json(); setRoster(data.roster || {}); }
    } catch (e) { /* ignore */ }
  }, []);

  const fetchFollowups = React.useCallback(async () => {
    try {
      const res = await authFetch(`${API_BASE_URL}/api/followups/upcoming`);
      if (res.ok) { const data = await res.json(); setFollowups(data.followups || []); }
    } catch (e) { /* ignore */ }
  }, []);

  const fetchDashboardUsers = React.useCallback(async () => {
    try {
      const res = await authFetch(`${API_BASE_URL}/api/admin/users`);
      if (res.ok) { const data = await res.json(); setDashboardUsers(data.users || []); }
    } catch (e) { /* non-admin may not have access, that's ok */ }
  }, []);

  React.useEffect(() => {
    fetchAlerts();
    fetchRoster();
    fetchFollowups();
    fetchDashboardUsers();
    const interval = setInterval(fetchAlerts, 2 * 60 * 1000);
    return () => clearInterval(interval);
  }, [fetchAlerts, fetchRoster, fetchFollowups, fetchDashboardUsers]);

  const saveRosterRole = async (role) => {
    setRosterSaving(true);
    try {
      const res = await authFetch(`${API_BASE_URL}/api/oncall/roster`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role, ...rosterForm }),
      });
      if (res.ok) {
        await fetchRoster();
        setRosterEditing(null);
        setRosterForm({ name: '', email: '', phone: '' });
      }
    } catch (e) { /* ignore */ }
    finally { setRosterSaving(false); }
  };

  const logDisposition = async (alertId) => {
    if (!dispositionForm.disposition) return;
    setDispositionSaving(true);
    try {
      const res = await authFetch(`${API_BASE_URL}/api/safety-events/${alertId}/disposition`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          safety_event_id: alertId,
          disposition: dispositionForm.disposition,
          notes: dispositionForm.notes,
          outreach_method: dispositionForm.outreach_method,
        }),
      });
      if (res.ok) {
        setDispositionSuccess(alertId);
        setDispositionForm({ disposition: '', notes: '', outreach_method: '' });
        setTimeout(() => setDispositionSuccess(null), 5000);
        // Also create follow-ups if it was a real event
        if (['contacted_safe', 'contacted_needs_support', 'escalated_988', 'escalated_er'].includes(dispositionForm.disposition)) {
          await authFetch(`${API_BASE_URL}/api/safety-events/${alertId}/create-followups`, { method: 'POST' });
          fetchFollowups();
        }
      }
    } catch (e) { /* ignore */ }
    finally { setDispositionSaving(false); }
  };

  const startEditRole = (role) => {
    const current = roster[role] || {};
    setRosterForm({ name: current.name || '', email: current.email || '', phone: current.phone || '' });
    setRosterEditing(role);
  };

  if (loading && alerts.length === 0) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-blue-500 border-t-transparent"></div>
      </div>
    );
  }

  return (
    <div className="space-y-6">

      {/* On-Call Roster */}
      <div className="bg-white rounded-lg shadow-md p-6">
        <h2 className="text-lg font-bold text-gray-800 mb-3 flex items-center">
          <Clock className="mr-2 text-blue-500" size={20} />
          On-Call Roster
        </h2>
        <p className="text-gray-500 text-xs mb-3">
          When a safety alert fires, primary on-call is paged first. If no response in 15 min, backup is paged. After 30 min, PI is paged.
        </p>
        <div className="grid grid-cols-3 gap-4">
          {['primary', 'backup', 'pi'].map((role) => {
            const person = roster[role];
            const isEditing = rosterEditing === role;
            const labels = { primary: 'Primary On-Call', backup: 'Backup On-Call', pi: 'PI (Escalation)' };
            const colors = { primary: 'border-blue-400 bg-blue-50', backup: 'border-amber-400 bg-amber-50', pi: 'border-red-400 bg-red-50' };

            return (
              <div key={role} className={`border-2 rounded-lg p-4 ${colors[role]}`}>
                <div className="text-xs font-bold text-gray-500 uppercase mb-2">{labels[role]}</div>
                {isEditing ? (
                  <div className="space-y-2">
                    {/* Dropdown to select from dashboard users */}
                    <select
                      value={rosterForm.email}
                      onChange={e => {
                        const selectedEmail = e.target.value;
                        if (selectedEmail === '__manual__') {
                          setRosterForm({ name: '', email: '', phone: '' });
                        } else {
                          const user = dashboardUsers.find(u => u.email === selectedEmail);
                          setRosterForm(f => ({
                            ...f,
                            email: selectedEmail,
                            name: f.name || selectedEmail.split('@')[0].replace(/\./g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
                          }));
                        }
                      }}
                      className="w-full border rounded px-2 py-1 text-sm bg-white"
                    >
                      <option value="">Select team member...</option>
                      {dashboardUsers.map(u => (
                        <option key={u.email} value={u.email}>{u.email} ({u.role})</option>
                      ))}
                      <option value="__manual__">Enter manually...</option>
                    </select>
                    <input value={rosterForm.name} onChange={e => setRosterForm(f => ({...f, name: e.target.value}))}
                      placeholder="Display name" className="w-full border rounded px-2 py-1 text-sm" />
                    <input value={rosterForm.email} onChange={e => setRosterForm(f => ({...f, email: e.target.value}))}
                      placeholder="Email (editable)" className="w-full border rounded px-2 py-1 text-sm" />
                    <input value={rosterForm.phone} onChange={e => setRosterForm(f => ({...f, phone: e.target.value}))}
                      placeholder="Phone (10 digits, for SMS alerts)" className="w-full border rounded px-2 py-1 text-sm" />
                    <div className="flex gap-2">
                      <button onClick={() => saveRosterRole(role)} disabled={rosterSaving || !rosterForm.name || !rosterForm.email}
                        className="px-3 py-1 bg-blue-600 text-white text-xs rounded hover:bg-blue-700 disabled:opacity-50">
                        {rosterSaving ? 'Saving...' : 'Save'}
                      </button>
                      <button onClick={() => setRosterEditing(null)}
                        className="px-3 py-1 bg-gray-300 text-gray-700 text-xs rounded hover:bg-gray-400">Cancel</button>
                    </div>
                  </div>
                ) : person ? (
                  <div>
                    <div className="font-semibold text-gray-800">{person.name}</div>
                    <div className="text-xs text-gray-600">{person.email}</div>
                    {person.phone && <div className="text-xs text-gray-600">{person.phone}</div>}
                    <button onClick={() => startEditRole(role)}
                      className="mt-2 text-xs text-blue-600 hover:text-blue-800">Edit</button>
                  </div>
                ) : (
                  <div>
                    <div className="text-gray-400 text-sm italic">Not assigned</div>
                    <button onClick={() => startEditRole(role)}
                      className="mt-2 text-xs text-blue-600 hover:text-blue-800">Assign</button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Upcoming Follow-ups */}
      {followups.length > 0 && (
        <div className="bg-white rounded-lg shadow-md p-6">
          <h2 className="text-lg font-bold text-gray-800 mb-3 flex items-center">
            <Clock className="mr-2 text-amber-500" size={20} />
            Upcoming Follow-ups ({followups.length})
          </h2>
          <div className="space-y-2">
            {followups.map((fu, idx) => {
              const scheduledDate = fu.scheduledAt ? new Date(fu.scheduledAt) : null;
              return (
                <div key={idx} className={`flex items-center justify-between p-3 border rounded-lg ${fu.isOverdue ? 'bg-red-50 border-red-300' : 'bg-amber-50 border-amber-200'}`}>
                  <div>
                    <span className="font-medium">{fu.label} follow-up</span>
                    <span className="mx-2">—</span>
                    <button onClick={() => goToParticipantView(fu.participantId)} className="text-blue-600 hover:underline">
                      {fu.participantId}
                    </button>
                    {fu.isOverdue && <span className="ml-2 px-2 py-0.5 bg-red-600 text-white text-xs font-bold rounded">OVERDUE</span>}
                  </div>
                  <div className="text-sm text-gray-500">
                    {scheduledDate ? scheduledDate.toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : 'Unknown'}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Safety Alerts */}
      <div className="bg-white rounded-lg shadow-md p-6">
        <h2 className="text-2xl font-bold text-gray-800 mb-4 flex items-center">
          <AlertTriangle className="mr-2 text-red-500" size={24} />
          Safety Alerts
        </h2>

        {/* Data Freshness Banner */}
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-800">
          <div className="flex items-center justify-between">
            <div>
              <strong>Auto-refreshing every 2 minutes</strong> for near real-time monitoring.
              {cacheInfo?.fromCache && cacheInfo.refreshedAt && (
                <span className="ml-2">
                  Cache updated: {new Date(cacheInfo.refreshedAt).toLocaleString('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit', hour12: true })} EST
                </span>
              )}
              {lastUpdated && (
                <span className="ml-2 text-red-600">
                  (Loaded: {lastUpdated.toLocaleString('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit', second: '2-digit', hour12: true })} EST)
                </span>
              )}
              {loading && <span className="ml-2 text-red-600 animate-pulse">(Refreshing...)</span>}
            </div>
            <button onClick={fetchAlerts} disabled={loading}
              className="px-3 py-1 bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50 text-xs flex items-center">
              {loading && <div className="animate-spin h-3 w-3 border-2 border-white border-t-transparent rounded-full mr-1"></div>}
              Refresh Now
            </button>
          </div>
        </div>

        <p className="text-gray-600 text-sm mb-4">
          SMS notifications are sent immediately when safety alerts are triggered.
          Configure recipients in the Users tab.
        </p>

        {error && alerts.length === 0 ? (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">Error: {error}</div>
        ) : alerts.length === 0 ? (
          <p className="text-gray-500 text-center py-8">No safety alerts recorded.</p>
        ) : (
          <div className="space-y-3">
            {alerts.map((alert, idx) => {
              const alertKey = `${alert.participantId}_${alert.date}`;
              const isExpanded = expandedAlert === alertKey;
              const wasResolved = dispositionSuccess === alertKey;

              return (
                <div key={idx} className={`border rounded-lg overflow-hidden ${
                  alert.crisis_indicated ? 'border-red-400' : 'border-red-200'
                }`}>
                  {/* Alert header — clickable to expand */}
                  <div
                    onClick={() => setExpandedAlert(isExpanded ? null : alertKey)}
                    className={`flex items-center justify-between p-4 cursor-pointer hover:bg-red-100 transition-colors ${
                      alert.crisis_indicated ? 'bg-red-100' : 'bg-red-50'
                    }`}
                  >
                    <div>
                      <span className="font-medium text-gray-800">Participant: </span>
                      <button onClick={(e) => { e.stopPropagation(); goToParticipantView(alert.participantId); }} className="text-blue-600 hover:underline">
                        {alert.participantId}
                      </button>
                      <span className="text-gray-500 ml-4">{alert.date}</span>
                      {alert.crisis_indicated && (
                        <span className="ml-3 px-2 py-0.5 bg-red-600 text-white text-xs font-bold rounded animate-pulse">CRISIS</span>
                      )}
                      {wasResolved && (
                        <span className="ml-3 px-2 py-0.5 bg-green-600 text-white text-xs font-bold rounded">RESPONDED</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="bg-red-500 text-white px-3 py-1 rounded-full text-sm font-medium">
                        {alert.count} alert{alert.count > 1 ? 's' : ''}
                      </span>
                      <span className="text-gray-400 text-xs">{isExpanded ? '▲' : '▼'}</span>
                    </div>
                  </div>

                  {/* Expanded: Disposition logging panel */}
                  {isExpanded && (
                    <div className="p-4 bg-white border-t border-red-200">
                      <h4 className="text-sm font-bold text-gray-700 mb-3">Log Response (stops escalation timer)</h4>

                      <div className="grid grid-cols-3 gap-3 mb-3">
                        <div>
                          <label className="block text-xs font-medium text-gray-500 mb-1">Disposition</label>
                          <select value={dispositionForm.disposition}
                            onChange={e => setDispositionForm(f => ({...f, disposition: e.target.value}))}
                            className="w-full border rounded px-2 py-1.5 text-sm bg-white">
                            <option value="">Select...</option>
                            <option value="contacted_safe">Contacted — Participant is safe</option>
                            <option value="contacted_needs_support">Contacted — Needs support/referral</option>
                            <option value="unable_to_reach">Unable to reach participant</option>
                            <option value="false_alarm">False alarm / Accidental</option>
                            <option value="escalated_988">Escalated to 988</option>
                            <option value="escalated_er">Escalated to ER / 911</option>
                          </select>
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-gray-500 mb-1">Outreach Method</label>
                          <select value={dispositionForm.outreach_method}
                            onChange={e => setDispositionForm(f => ({...f, outreach_method: e.target.value}))}
                            className="w-full border rounded px-2 py-1.5 text-sm bg-white">
                            <option value="">Select...</option>
                            <option value="phone_call">Phone call</option>
                            <option value="sms">SMS</option>
                            <option value="email">Email</option>
                            <option value="in_person">In person</option>
                            <option value="automated_ivr">Automated IVR call</option>
                          </select>
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-gray-500 mb-1">Notes</label>
                          <input value={dispositionForm.notes}
                            onChange={e => setDispositionForm(f => ({...f, notes: e.target.value}))}
                            placeholder="Brief notes..."
                            className="w-full border rounded px-2 py-1.5 text-sm" />
                        </div>
                      </div>

                      <button
                        onClick={() => logDisposition(alertKey)}
                        disabled={dispositionSaving || !dispositionForm.disposition}
                        className="px-4 py-2 bg-green-600 text-white text-sm font-medium rounded hover:bg-green-700 disabled:opacity-50"
                      >
                        {dispositionSaving ? 'Saving...' : 'Log Response & Stop Escalation'}
                      </button>

                      <p className="text-xs text-gray-400 mt-2">
                        Logging a response stops the escalation timer (backup/PI won't be paged).
                        For serious events, follow-up schedule (24h/48h/72h/7d) will be auto-created.
                      </p>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};


export default SocialScope;
