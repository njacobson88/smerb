// ParticipantDetailScreen.js - Single Participant Daily View

import React, { useState, useEffect, useCallback } from 'react';
import { ChevronLeft, ChevronRight, Download, Loader2, Camera, FileText, AlertTriangle, RefreshCw } from 'lucide-react';
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

  // Handle data export
  const handleExport = async (level = exportLevel) => {
    setExportLoading(true);
    setExportError(null);
    setExportDownload(null);
    setShowExportOptions(false);

    try {
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
      setExportDownload({
        url: `${API_BASE_URL}${data.download_url}`,
        filename: data.filename
      });
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
            <h1 className="text-2xl font-bold text-gray-800 mb-2">
              Participant: {currentParticipantId}
            </h1>
            {summary && (
              <div className="text-gray-600 text-sm space-y-1">
                <div>Study Start: {summary.study_start_date || 'Unknown'}</div>
                <div>Device: {summary.device_model || 'Unknown'} ({summary.os_version || 'Unknown'})</div>
              </div>
            )}
          </div>

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
                      onClick={() => handleExport(level)}
                      className="w-full text-left p-3 rounded-md hover:bg-gray-100 transition-colors"
                    >
                      <div className="font-medium text-gray-800">
                        Level {level}: {exportLevelDescriptions[level].name}
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

        {exportDownload && (
          <div className="mt-3 p-3 bg-green-50 border border-green-200 rounded text-green-700 text-sm flex items-center justify-between">
            <a href={exportDownload.url} className="underline font-medium" download>
              Download: {exportDownload.filename}
            </a>
            <button
              onClick={() => setExportDownload(null)}
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
    </div>
  );
};

export default ParticipantDetailScreen;
