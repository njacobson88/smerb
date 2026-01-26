// OverallScreen.js - All Participants Daily Overview

import React, { useState, useEffect, useCallback } from 'react';
import {
  User, Camera, FileText, CheckCircle, XCircle, AlertTriangle,
  ChevronLeft, ChevronRight, Loader2
} from 'lucide-react';
import { API_BASE_URL, authFetch } from './SocialScope';

// Color constants for status indicators
const COLORS = {
  green: "#006164",
  lightGreen: "#57C4AD",
  orange: "#EDA247",
  red: "#DB4325",
  gray: "#9CA3AF",
};

// Thresholds for status coloring
const THRESHOLDS = {
  screenshots: { good: 50, low: 10 },
  checkins: { good: 2, low: 1 },
};

// Status indicator for screenshots
const ScreenshotStatus = ({ count }) => {
  let color = COLORS.gray;
  if (count >= THRESHOLDS.screenshots.good) color = COLORS.green;
  else if (count >= THRESHOLDS.screenshots.low) color = COLORS.orange;
  else if (count > 0) color = COLORS.red;

  return (
    <div className="flex items-center space-x-1" title={`${count} screenshots`}>
      <Camera size={16} color={color} />
      <span style={{ color }} className="text-xs font-medium">{count}</span>
    </div>
  );
};

// Status indicator for check-ins
const CheckinStatus = ({ count, total = 3 }) => {
  let Icon = XCircle;
  let color = COLORS.red;

  if (count >= total) {
    Icon = CheckCircle;
    color = COLORS.green;
  } else if (count >= total - 1) {
    Icon = CheckCircle;
    color = COLORS.lightGreen;
  } else if (count > 0) {
    Icon = CheckCircle;
    color = COLORS.orange;
  }

  return (
    <div className="flex items-center" title={`${count}/${total} check-ins`}>
      <Icon size={18} color={color} />
    </div>
  );
};

// Safety alert indicator
const SafetyAlertIndicator = ({ count }) => {
  if (count === 0) return null;

  return (
    <div className="flex items-center" title={`${count} safety alert(s)`}>
      <AlertTriangle size={16} color={COLORS.red} fill={COLORS.red} />
    </div>
  );
};

// Crisis indicator - prominent red flag for "Yes" to crisis question
const CrisisIndicator = ({ crisis }) => {
  if (!crisis) return null;

  return (
    <div
      className="flex items-center bg-red-100 px-1 py-0.5 rounded animate-pulse"
      title="Participant indicated 'Yes' to crisis question"
    >
      <AlertTriangle size={14} color={COLORS.red} />
      <span className="text-xs font-bold text-red-700 ml-0.5">CRISIS</span>
    </div>
  );
};

// Platform screenshot indicators
const PlatformIndicator = ({ platform, count, color }) => {
  if (count === 0) return <span className="text-gray-300">—</span>;

  return (
    <div className="flex items-center justify-center" title={`${count} ${platform} screenshots`}>
      <span style={{ color }} className="text-xs font-medium">{count}</span>
    </div>
  );
};

// Compliance pill
const CompliancePill = ({ value }) => {
  const pct = Math.min(100, Math.max(0, value));
  let bg = COLORS.red;
  if (pct >= 80) bg = COLORS.green;
  else if (pct >= 50) bg = COLORS.orange;

  return (
    <div
      className="px-3 py-1 rounded-full text-white text-sm font-bold text-center"
      style={{ backgroundColor: bg, minWidth: '50px' }}
      title={`${pct}% compliance`}
    >
      {pct}%
    </div>
  );
};


const OverallScreen = ({ goToParticipantView, goToDayView, setParticipantList }) => {
  const [weekOffset, setWeekOffset] = useState(0);
  const [participants, setParticipants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [page, setPage] = useState(1);
  const [pagination, setPagination] = useState({ total: 0, total_pages: 1, page_size: 25 });
  const [cacheInfo, setCacheInfo] = useState({ fromCache: false, refreshedAt: null });
  const [refreshingCache, setRefreshingCache] = useState(false);
  const [cacheMessage, setCacheMessage] = useState(null);

  // Date formatting helpers
  const formatYMD = useCallback((d) => {
    const yy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    return `${yy}-${mm}-${dd}`;
  }, []);

  // Calculate week date range
  const getWeekDateRange = useCallback((offset = 0) => {
    const today = new Date();
    const endDate = new Date(today);
    endDate.setDate(today.getDate() - 1 - offset * 7);

    const startDate = new Date(endDate);
    startDate.setDate(endDate.getDate() - 6);

    return {
      startDate: formatYMD(startDate),
      endDate: formatYMD(endDate),
    };
  }, [formatYMD]);

  // Fetch participant data
  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);

    const { startDate, endDate } = getWeekDateRange(weekOffset);

    try {
      const response = await authFetch(
        `${API_BASE_URL}/api/overall_status?start_date=${startDate}&end_date=${endDate}&page=${page}&page_size=25`
      );

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `Server responded with ${response.status}`);
      }

      const data = await response.json();
      // Handle paginated response
      const participantData = data.participants || data;
      setParticipants(participantData);
      if (data.pagination) {
        setPagination(data.pagination);
      }
      if (data.cache) {
        setCacheInfo(data.cache);
      }
      setParticipantList(participantData.map(p => p.id));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [weekOffset, page, getWeekDateRange, setParticipantList]);

  // Manual cache refresh with double confirmation
  const handleRefreshCache = async () => {
    const firstConfirm = window.confirm(
      'Refresh the dashboard cache?\n\n' +
      'This will recompute statistics for all participants from the last 14 days.\n' +
      'This may take 1-2 minutes and incurs Firestore read costs.'
    );
    if (!firstConfirm) return;

    const secondConfirm = window.confirm(
      'Are you sure?\n\n' +
      'Click OK to start the cache refresh.\n' +
      'The page will reload automatically when complete.'
    );
    if (!secondConfirm) return;

    setRefreshingCache(true);
    setCacheMessage(null);

    try {
      const response = await authFetch(`${API_BASE_URL}/api/admin/refresh-cache`, {
        method: 'POST',
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to refresh cache');
      }

      const data = await response.json();
      setCacheMessage(`Cache refreshed! ${data.participantCount} participants updated.`);

      // Reload data after short delay
      setTimeout(() => {
        fetchData();
        setCacheMessage(null);
      }, 1500);
    } catch (err) {
      setCacheMessage(`Error: ${err.message}`);
    } finally {
      setRefreshingCache(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Reset to page 1 when week changes
  useEffect(() => {
    setPage(1);
  }, [weekOffset]);

  // Generate day headers for the week
  const { startDate } = getWeekDateRange(weekOffset);
  const [y, m, d] = startDate.split('-').map(Number);
  const start = new Date(y, m - 1, d);
  const dayHeaders = Array.from({ length: 7 }, (_, i) => {
    const day = new Date(start);
    day.setDate(start.getDate() + i);
    return {
      isoDate: formatYMD(day),
      dayOfWeek: day.toLocaleDateString('en-US', { weekday: 'short' }),
      dayOfMonth: day.getDate(),
    };
  });

  // Calculate average compliance
  const avgCompliance = participants.length > 0
    ? Math.round(participants.reduce((sum, p) => sum + (p.overallCompliance || 0), 0) / participants.length)
    : 0;

  const { startDate: displayStart, endDate: displayEnd } = getWeekDateRange(weekOffset);

  return (
    <div className="overall-screen">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-gray-800 mb-2">Participant Overview</h1>
        <p className="text-gray-600">Daily monitoring status for all enrolled participants</p>

        {/* Data Freshness Banner */}
        <div className={`mt-3 p-3 rounded-lg text-sm ${
          cacheInfo.fromCache
            ? 'bg-green-50 border border-green-200 text-green-800'
            : 'bg-yellow-50 border border-yellow-200 text-yellow-800'
        }`}>
          <div className="flex items-center justify-between">
            <div>
              {cacheInfo.fromCache ? (
                <>
                  <strong>Cached Data:</strong> Auto-refreshes hourly (on the hour).
                  {cacheInfo.refreshedAt && (
                    <span className="ml-2">
                      Last update: {new Date(cacheInfo.refreshedAt).toLocaleString('en-US', { timeZone: 'America/New_York', month: 'numeric', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', second: '2-digit', hour12: true })} EST
                    </span>
                  )}
                </>
              ) : (
                <>
                  <strong>Live Data:</strong> Cache not initialized - slower performance.
                </>
              )}
            </div>
            <div className="flex items-center space-x-2">
              <button
                onClick={fetchData}
                disabled={loading || refreshingCache}
                className={`px-3 py-1 text-white rounded disabled:opacity-50 text-xs ${
                  cacheInfo.fromCache ? 'bg-green-600 hover:bg-green-700' : 'bg-yellow-600 hover:bg-yellow-700'
                }`}
              >
                {loading ? 'Loading...' : 'Reload Page'}
              </button>
              <button
                onClick={handleRefreshCache}
                disabled={loading || refreshingCache}
                className="px-3 py-1 bg-purple-600 text-white rounded hover:bg-purple-700 disabled:opacity-50 text-xs"
                title="Recompute all participant statistics (admin only)"
              >
                {refreshingCache ? 'Refreshing Cache...' : 'Refresh Cache'}
              </button>
            </div>
          </div>
          {cacheMessage && (
            <div className={`mt-2 text-sm ${cacheMessage.startsWith('Error') ? 'text-red-600' : 'text-green-600'}`}>
              {cacheMessage}
            </div>
          )}
        </div>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="bg-white rounded-lg shadow p-4">
          <div className="text-sm text-gray-500">Total Participants</div>
          <div className="text-2xl font-bold text-gray-800">{pagination.total || participants.length}</div>
        </div>
        <div className="bg-white rounded-lg shadow p-4">
          <div className="text-sm text-gray-500">Average Check-in Compliance</div>
          <div className="text-2xl font-bold" style={{ color: avgCompliance >= 80 ? COLORS.green : avgCompliance >= 50 ? COLORS.orange : COLORS.red }}>
            {avgCompliance}%
          </div>
        </div>
        <div className="bg-white rounded-lg shadow p-4">
          <div className="text-sm text-gray-500">Week Screenshots</div>
          <div className="text-2xl font-bold text-gray-800">
            {participants.reduce((sum, p) => sum + (p.weeklyScreenshots || 0), 0).toLocaleString()}
          </div>
        </div>
      </div>

      {/* Week Navigation */}
      <div className="flex items-center justify-between mb-4 bg-white rounded-lg shadow px-4 py-3">
        <button
          onClick={() => setWeekOffset(weekOffset + 1)}
          className="flex items-center px-3 py-2 text-gray-600 hover:bg-gray-100 rounded-md transition-colors"
        >
          <ChevronLeft size={20} className="mr-1" /> Previous 7 Days
        </button>
        <span className="font-medium text-gray-700">
          {displayStart} to {displayEnd}
        </span>
        <button
          onClick={() => setWeekOffset(Math.max(0, weekOffset - 1))}
          disabled={weekOffset === 0}
          className="flex items-center px-3 py-2 text-gray-600 hover:bg-gray-100 rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Next 7 Days <ChevronRight size={20} className="ml-1" />
        </button>
      </div>

      {/* Legend */}
      <div className="bg-gray-50 rounded-lg p-3 mb-4 flex flex-wrap gap-4 text-sm">
        <div className="flex items-center gap-2">
          <Camera size={14} color={COLORS.green} />
          <span>Screenshots (≥50 good)</span>
        </div>
        <div className="flex items-center gap-2">
          <CheckCircle size={14} color={COLORS.green} />
          <span>Check-ins complete</span>
        </div>
        <div className="flex items-center gap-2">
          <CheckCircle size={14} color={COLORS.orange} />
          <span>Partial check-ins</span>
        </div>
        <div className="flex items-center gap-2">
          <XCircle size={14} color={COLORS.red} />
          <span>No check-ins</span>
        </div>
        <div className="flex items-center gap-2">
          <AlertTriangle size={14} color={COLORS.red} fill={COLORS.red} />
          <span>Safety alert</span>
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

      {/* Data Table */}
      {!loading && !error && (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-gray-600">Participant</th>
                  {dayHeaders.map((d, i) => (
                    <th key={i} className="px-2 py-3 text-center text-sm font-semibold text-gray-600">
                      <div>{d.dayOfWeek}</div>
                      <div className="text-xs text-gray-400">{d.isoDate.slice(5)}</div>
                    </th>
                  ))}
                  <th className="px-3 py-3 text-center text-sm font-semibold text-gray-600">
                    <div>Weekly</div>
                    <div className="text-xs text-gray-400">EMAs</div>
                  </th>
                  <th className="px-3 py-3 text-center text-sm font-semibold" style={{ color: '#FF4500' }}>
                    <div>Reddit</div>
                    <div className="text-xs text-gray-400">shots</div>
                  </th>
                  <th className="px-3 py-3 text-center text-sm font-semibold" style={{ color: '#1DA1F2' }}>
                    <div>X</div>
                    <div className="text-xs text-gray-400">shots</div>
                  </th>
                  <th className="px-4 py-3 text-center text-sm font-semibold text-gray-600">Compliance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {participants.map((participant) => {
                  const dailyStatusMap = {};
                  (participant.dailyStatus || []).forEach(d => {
                    dailyStatusMap[d.date] = d;
                  });

                  return (
                    <tr key={participant.id} className="hover:bg-gray-50">
                      {/* Participant ID */}
                      <td className="px-4 py-3">
                        <button
                          onClick={() => goToParticipantView(participant.id)}
                          className="flex items-center text-blue-600 hover:text-blue-800 hover:underline"
                        >
                          <User size={16} className="mr-2 text-gray-400" />
                          {participant.id}
                        </button>
                      </td>

                      {/* Daily Status Cells */}
                      {dayHeaders.map((dayHeader, idx) => {
                        const dayData = dailyStatusMap[dayHeader.isoDate];
                        const studyStart = participant.study_start_date;

                        // Check if day is before study start
                        if (studyStart && dayHeader.isoDate < studyStart) {
                          return (
                            <td key={idx} className="px-2 py-3 text-center text-gray-400 text-xs italic">
                              —
                            </td>
                          );
                        }

                        if (!dayData) {
                          return (
                            <td key={idx} className="px-2 py-3 text-center text-gray-300">
                              —
                            </td>
                          );
                        }

                        return (
                          <td
                            key={idx}
                            className="px-2 py-3 cursor-pointer hover:bg-blue-50 transition-colors"
                            onClick={() => goToDayView(participant.id, dayHeader.isoDate)}
                            title={`Click for details - ${dayHeader.isoDate}`}
                          >
                            <div className="flex flex-col items-center space-y-1">
                              <CheckinStatus count={dayData.checkins || 0} />
                              <ScreenshotStatus count={dayData.screenshots || 0} />
                              <CrisisIndicator crisis={dayData.crisis_indicated} />
                              <SafetyAlertIndicator count={dayData.safety_alerts || 0} />
                            </div>
                          </td>
                        );
                      })}

                      {/* Weekly EMAs */}
                      <td className="px-3 py-3 text-center">
                        <div className={`text-lg font-bold ${
                          (participant.weeklyCheckins || 0) >= 14 ? 'text-green-600' :
                          (participant.weeklyCheckins || 0) >= 7 ? 'text-orange-500' : 'text-red-500'
                        }`}>
                          {participant.weeklyCheckins || 0}
                          <span className="text-xs text-gray-400 font-normal">/21</span>
                        </div>
                      </td>

                      {/* Weekly Reddit Screenshots */}
                      <td className="px-3 py-3 text-center">
                        <span className="text-lg font-medium" style={{ color: '#FF4500' }}>
                          {participant.weeklyReddit || 0}
                        </span>
                      </td>

                      {/* Weekly Twitter/X Screenshots */}
                      <td className="px-3 py-3 text-center">
                        <span className="text-lg font-medium" style={{ color: '#1DA1F2' }}>
                          {participant.weeklyTwitter || 0}
                        </span>
                      </td>

                      {/* Overall Compliance */}
                      <td className="px-4 py-3 text-center">
                        <CompliancePill value={participant.overallCompliance || 0} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {participants.length === 0 && (
            <div className="text-center py-12 text-gray-500">
              No participants found. Participants will appear here once they enroll.
            </div>
          )}

          {/* Pagination Controls */}
          {pagination.total_pages > 1 && (
            <div className="flex items-center justify-between px-4 py-3 bg-gray-50 border-t">
              <div className="text-sm text-gray-600">
                Showing {((page - 1) * pagination.page_size) + 1} - {Math.min(page * pagination.page_size, pagination.total)} of {pagination.total} participants
              </div>
              <div className="flex items-center space-x-2">
                <button
                  onClick={() => setPage(Math.max(1, page - 1))}
                  disabled={page === 1}
                  className="px-3 py-1 border rounded-md text-sm hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Previous
                </button>
                <span className="text-sm text-gray-600">
                  Page {page} of {pagination.total_pages}
                </span>
                <button
                  onClick={() => setPage(Math.min(pagination.total_pages, page + 1))}
                  disabled={page === pagination.total_pages}
                  className="px-3 py-1 border rounded-md text-sm hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default OverallScreen;
