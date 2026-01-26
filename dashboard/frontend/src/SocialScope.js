// SocialScope.js - Main Dashboard Application

import React, { useState, useEffect } from 'react';
import { Users, Download, AlertTriangle, LogOut, Settings } from 'lucide-react';
import OverallScreen from './OverallScreen';
import ParticipantDetailScreen from './ParticipantDetailScreen';
import DayDetailScreen from './DayDetailScreen';
import Login, { auth, signOut, onAuthStateChanged, getIdToken } from './Login';
import UserManagement from './UserManagement';

// API Configuration
// In production, REACT_APP_API_URL should point to the Cloud Run service
// In development, use localhost
const isLocal = process.env.REACT_APP_LOCAL === 'true';
const API_BASE_URL = isLocal
  ? "http://localhost:8080"
  : (process.env.REACT_APP_API_URL || "https://socialscope-dashboard-api-436153481478.us-central1.run.app");

export { API_BASE_URL, getIdToken };

// Authenticated fetch helper - includes auth token in requests
export const authFetch = async (url, options = {}) => {
  const token = await getIdToken();
  const headers = {
    ...options.headers,
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return fetch(url, { ...options, headers });
};

const SocialScope = () => {
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
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

  const handleExport = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setDownloadUrl(null);

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
      setDownloadUrl(`${API_BASE_URL}${data.download_url}`);
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
      setLoading(false);
      setAbortController(null);
    }
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
                      {getLevelInfo(3).needs_background && (
                        <span className="ml-2 text-red-600">(Large export - may take time)</span>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </label>
          </div>
        </div>

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
                Generating Export...
              </span>
            ) : (
              'Export Data'
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

  const fetchAlerts = React.useCallback(async () => {
    setLoading(true);
    try {
      // Use dedicated cached safety-alerts endpoint for fast response
      const response = await authFetch(`${API_BASE_URL}/api/safety-alerts`);
      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to fetch alerts');
      }

      const data = await response.json();
      setAlerts(data.alerts || []);
      setCacheInfo({
        fromCache: data.fromCache,
        refreshedAt: data.refreshedAt,
      });
      setLastUpdated(new Date());
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    fetchAlerts();

    // Auto-refresh every 2 minutes for near real-time safety alert monitoring
    const interval = setInterval(fetchAlerts, 2 * 60 * 1000);
    return () => clearInterval(interval);
  }, [fetchAlerts]);

  if (loading && alerts.length === 0) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-blue-500 border-t-transparent"></div>
      </div>
    );
  }

  if (error && alerts.length === 0) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">
        Error loading alerts: {error}
      </div>
    );
  }

  return (
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
          <button
            onClick={fetchAlerts}
            disabled={loading}
            className="px-3 py-1 bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50 text-xs flex items-center"
          >
            {loading && <div className="animate-spin h-3 w-3 border-2 border-white border-t-transparent rounded-full mr-1"></div>}
            Refresh Now
          </button>
        </div>
      </div>

      <p className="text-gray-600 text-sm mb-4">
        SMS notifications are sent immediately when safety alerts are triggered.
        Configure recipients in the Users tab.
      </p>

      {alerts.length === 0 ? (
        <p className="text-gray-500 text-center py-8">No safety alerts recorded.</p>
      ) : (
        <div className="space-y-3">
          {alerts.map((alert, idx) => (
            <div
              key={idx}
              className={`flex items-center justify-between p-4 border rounded-lg ${
                alert.crisis_indicated
                  ? 'bg-red-100 border-red-400'
                  : 'bg-red-50 border-red-200'
              }`}
            >
              <div>
                <span className="font-medium text-gray-800">Participant: </span>
                <button
                  onClick={() => goToParticipantView(alert.participantId)}
                  className="text-blue-600 hover:underline"
                >
                  {alert.participantId}
                </button>
                <span className="text-gray-500 ml-4">{alert.date}</span>
                {alert.crisis_indicated && (
                  <span className="ml-3 px-2 py-0.5 bg-red-600 text-white text-xs font-bold rounded animate-pulse">
                    CRISIS
                  </span>
                )}
              </div>
              <span className="bg-red-500 text-white px-3 py-1 rounded-full text-sm font-medium">
                {alert.count} alert{alert.count > 1 ? 's' : ''}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};


export default SocialScope;
