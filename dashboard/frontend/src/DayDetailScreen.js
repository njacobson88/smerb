// DayDetailScreen.js - Single Day Detail View for One Participant

import React, { useState, useEffect, useCallback } from 'react';
import {
  ChevronLeft, ChevronRight, Download, Loader2,
  Camera, FileText, CheckCircle, Clock, AlertTriangle, ExternalLink, RefreshCw
} from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  AreaChart, Area, Legend
} from 'recharts';
import { API_BASE_URL, authFetch } from './SocialScope';

// Color constants
const COLORS = {
  green: "#006164",
  lightGreen: "#57C4AD",
  orange: "#EDA247",
  red: "#DB4325",
  blue: "#4A6CF7",
  purple: "#7C3AED",
  gray: "#9CA3AF",
};

// Platform colors for charts
const PLATFORM_COLORS = {
  reddit: "#FF4500",
  twitter: "#1DA1F2",
  other: "#6B7280",
};

// Format hour for display
const formatHour = (hour) => {
  if (hour === 0) return '12 AM';
  if (hour === 12) return '12 PM';
  if (hour < 12) return `${hour} AM`;
  return `${hour - 12} PM`;
};

// Format response values (handles strings that are actually numbers/booleans)
const formatResponseValue = (value) => {
  if (value === null || value === undefined) return '-';

  // Handle actual booleans
  if (typeof value === 'boolean') {
    return value ? 'Yes' : 'No';
  }

  // Handle string representations of booleans
  if (typeof value === 'string') {
    const lowerVal = value.toLowerCase();
    if (lowerVal === 'true') return 'Yes';
    if (lowerVal === 'false') return 'No';

    // Check if it's a numeric string
    const numVal = parseFloat(value);
    if (!isNaN(numVal)) {
      // If it looks like a percentage/score (0-100 range with decimals)
      if (numVal >= 0 && numVal <= 100 && value.includes('.')) {
        return numVal.toFixed(1);
      }
      // Otherwise return as-is for integers or simple numbers
      return Number.isInteger(numVal) ? numVal.toString() : numVal.toFixed(1);
    }

    // Return string as-is
    return value;
  }

  // Handle actual numbers
  if (typeof value === 'number') {
    return Number.isInteger(value) ? value.toString() : value.toFixed(1);
  }

  return String(value);
};

// Format question key to readable label
const formatQuestionLabel = (key) => {
  // Special labels for SI-related fields
  const siLabels = {
    'desire_intensity': 'SI Desire Intensity',
    'safety_alert_response': 'Safety Alert Response',
    'intention_strength': 'SI Intention Strength',
    'ability_safe': 'Ability to Stay Safe',
    'thoughts_past_4hrs': 'SI Thoughts (Past 4 hrs)',
    'thoughts_duration': 'SI Thoughts Duration',
    'thoughts_intent': 'SI Thoughts Intent',
  };

  if (siLabels[key]) {
    return siLabels[key];
  }

  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase());
};

// SI-related fields to show in safety alerts box
const SI_RELATED_FIELDS = [
  'desire_intensity',
  'safety_alert_response',
  'intention_strength',
  'ability_safe',
  'thoughts_past_4hrs',
  'thoughts_duration',
  'thoughts_intent',
];

// Thoughts duration mapping (based on EMA questions)
const THOUGHTS_DURATION_LABELS = {
  1: 'A few seconds',
  2: 'A few minutes',
  3: 'Less than an hour',
  4: 'More than an hour',
  5: 'Most of the day',
};

// Format SI response values with special handling
const formatSIResponseValue = (key, value) => {
  if (value === null || value === undefined) return '-';

  // Special handling for thoughts_duration
  if (key === 'thoughts_duration') {
    const numVal = typeof value === 'number' ? value : parseInt(value);
    if (THOUGHTS_DURATION_LABELS[numVal]) {
      return `${numVal} - ${THOUGHTS_DURATION_LABELS[numVal]}`;
    }
  }

  // Special handling for thoughts_past_4hrs
  if (key === 'thoughts_past_4hrs') {
    if (value === true || value === 'true') return 'Yes - Had SI thoughts';
    if (value === false || value === 'false') return 'No';
    return String(value);
  }

  // Special handling for safety_alert_response
  if (key === 'safety_alert_response') {
    if (value === true || value === 'true') return 'Yes - Needs help';
    if (value === false || value === 'false') return 'No - Can stay safe';
    return String(value);
  }

  // Handle actual booleans
  if (typeof value === 'boolean') {
    return value ? 'Yes' : 'No';
  }

  // Handle numbers (scores 0-100)
  if (typeof value === 'number') {
    if (value >= 0 && value <= 100) {
      return `${value.toFixed(1)}/100`;
    }
    return value.toString();
  }

  // Handle string numbers
  if (typeof value === 'string') {
    const numVal = parseFloat(value);
    if (!isNaN(numVal) && numVal >= 0 && numVal <= 100) {
      return `${numVal.toFixed(1)}/100`;
    }
  }

  return String(value);
};


const DayDetailScreen = ({
  participantId,
  date,
  goToOverallView,
  goToParticipantView,
  goToDayView
}) => {
  const [dayData, setDayData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);

  // Parse date for navigation
  const parseDate = (dateStr) => {
    const [y, m, d] = dateStr.split('-').map(Number);
    return new Date(y, m - 1, d);
  };

  const formatDate = (d) => {
    const yy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    return `${yy}-${mm}-${dd}`;
  };

  // Navigate to previous/next day
  const goToPrevDay = useCallback(() => {
    const current = parseDate(date);
    current.setDate(current.getDate() - 1);
    goToDayView(participantId, formatDate(current));
  }, [date, participantId, goToDayView]);

  const goToNextDay = useCallback(() => {
    const current = parseDate(date);
    current.setDate(current.getDate() + 1);
    const tomorrow = new Date();
    tomorrow.setHours(0, 0, 0, 0);
    if (current < tomorrow) {
      goToDayView(participantId, formatDate(current));
    }
  }, [date, participantId, goToDayView]);

  // Check if we can go to next day
  const canGoNext = () => {
    const current = parseDate(date);
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return current < today;
  };

  // Fetch day data
  const fetchDayData = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await authFetch(
        `${API_BASE_URL}/api/participant/${participantId}/day/${date}`
      );

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `Server responded with ${response.status}`);
      }

      const data = await response.json();
      setDayData(data);
      setLastUpdated(new Date());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [participantId, date]);

  useEffect(() => {
    if (participantId && date) {
      fetchDayData();
    }
  }, [participantId, date, fetchDayData]);

  // Prepare hourly chart data
  const prepareHourlyData = () => {
    if (!dayData?.hourly_activity) return [];

    return Array.from({ length: 24 }, (_, hour) => {
      const hourData = dayData.hourly_activity[hour] || {};
      return {
        hour,
        hourLabel: formatHour(hour),
        screenshots: hourData.screenshots || 0,
        ocrWords: hourData.ocr_words || 0,
        reddit: hourData.reddit || 0,
        twitter: hourData.twitter || 0,
      };
    });
  };

  // Prepare platform breakdown data
  const preparePlatformData = () => {
    if (!dayData?.platform_breakdown) return [];

    return Object.entries(dayData.platform_breakdown).map(([platform, data]) => ({
      platform,
      screenshots: data.screenshots || 0,
      ocrWords: data.ocr_words || 0,
    }));
  };

  const hourlyData = prepareHourlyData();
  const platformData = preparePlatformData();

  // Format day of week
  const dayOfWeek = date ? parseDate(date).toLocaleDateString('en-US', { weekday: 'long' }) : '';

  return (
    <div className="day-detail-screen">
      {/* Navigation Breadcrumb */}
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center space-x-2 text-sm">
          <button
            onClick={goToOverallView}
            className="text-blue-600 hover:text-blue-800 hover:underline"
          >
            Overview
          </button>
          <ChevronRight size={14} className="text-gray-400" />
          <button
            onClick={() => goToParticipantView(participantId)}
            className="text-blue-600 hover:text-blue-800 hover:underline"
          >
            {participantId}
          </button>
          <ChevronRight size={14} className="text-gray-400" />
          <span className="text-gray-600">{date}</span>
        </div>

        <div className="flex items-center space-x-2">
          <button
            onClick={goToPrevDay}
            className="px-3 py-2 bg-gray-100 hover:bg-gray-200 rounded-md"
          >
            <ChevronLeft size={18} />
          </button>
          <span className="text-gray-600 text-sm px-2">{dayOfWeek}</span>
          <button
            onClick={goToNextDay}
            disabled={!canGoNext()}
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
            <h1 className="text-2xl font-bold text-gray-800 mb-1">
              {date}
            </h1>
            <p className="text-gray-600">
              Participant: <span className="font-medium">{participantId}</span>
            </p>
          </div>

          {dayData && (
            <div className="flex items-center space-x-6">
              {/* Crisis Flag - Most Important */}
              {dayData.crisis_indicated && (
                <div className="bg-red-100 border-2 border-red-500 rounded-lg px-4 py-2 animate-pulse">
                  <div className="flex items-center text-red-700 font-bold">
                    <AlertTriangle size={20} className="mr-2" />
                    CRISIS INDICATED
                  </div>
                </div>
              )}
              {/* Check-ins/EMAs - Primary Metric */}
              <div className="text-center border-2 border-green-200 rounded-lg px-4 py-2 bg-green-50">
                <div className="flex items-center text-gray-600 text-sm mb-1">
                  <CheckCircle size={14} className="mr-1" /> EMAs Complete
                </div>
                <div className="text-3xl font-bold" style={{
                  color: (dayData.checkins?.length || 0) >= 3 ? COLORS.green :
                         (dayData.checkins?.length || 0) > 0 ? COLORS.orange : COLORS.red
                }}>
                  {dayData.checkins?.length || 0}/3
                </div>
              </div>
              {/* Reddit Screenshots - Key Platform */}
              <div className="text-center border rounded-lg px-4 py-2" style={{ borderColor: PLATFORM_COLORS.reddit }}>
                <div className="flex items-center text-gray-600 text-sm mb-1">
                  <Camera size={14} className="mr-1" style={{ color: PLATFORM_COLORS.reddit }} /> Reddit
                </div>
                <div className="text-2xl font-bold" style={{ color: PLATFORM_COLORS.reddit }}>
                  {dayData.reddit_screenshots || 0}
                </div>
              </div>
              {/* Twitter/X Screenshots - Key Platform */}
              <div className="text-center border rounded-lg px-4 py-2" style={{ borderColor: PLATFORM_COLORS.twitter }}>
                <div className="flex items-center text-gray-600 text-sm mb-1">
                  <Camera size={14} className="mr-1" style={{ color: PLATFORM_COLORS.twitter }} /> X (Twitter)
                </div>
                <div className="text-2xl font-bold" style={{ color: PLATFORM_COLORS.twitter }}>
                  {dayData.twitter_screenshots || 0}
                </div>
              </div>
              {/* Total Screenshots */}
              <div className="text-center">
                <div className="flex items-center text-gray-500 text-sm mb-1">
                  <Camera size={14} className="mr-1" /> Total
                </div>
                <div className="text-xl font-bold text-gray-600">
                  {dayData.total_screenshots || 0}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Data Freshness Indicator */}
      <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg text-sm flex items-center justify-between">
        <div className="text-blue-800">
          <strong>Live Data:</strong> Fetched on page load.
          {lastUpdated && (
            <span className="ml-2">
              Last updated: {lastUpdated.toLocaleString('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit', second: '2-digit', hour12: true })} EST
            </span>
          )}
        </div>
        <button
          onClick={fetchDayData}
          disabled={loading}
          className="flex items-center px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 text-xs"
        >
          <RefreshCw size={14} className={`mr-1 ${loading ? 'animate-spin' : ''}`} />
          {loading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {/* Loading State */}
      {loading && !dayData && (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="animate-spin text-blue-500 mr-3" size={32} />
          <span className="text-gray-600">Loading day data...</span>
        </div>
      )}

      {/* Error State */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">
          <strong>Error:</strong> {error}
        </div>
      )}

      {/* Main Content */}
      {!loading && !error && dayData && (
        <div className="space-y-6">
          {/* Safety Alerts (if any) - Shows ONLY SI-related fields */}
          {dayData.safety_alerts?.length > 0 && (
            <div className="bg-red-50 border-2 border-red-300 rounded-lg p-4">
              <div className="flex items-center text-red-700 font-semibold mb-3">
                <AlertTriangle size={20} className="mr-2" />
                Safety Alerts - SI Risk Indicators ({dayData.safety_alerts.length})
              </div>
              <div className="space-y-3">
                {dayData.safety_alerts.map((alert, idx) => {
                  // Filter to ONLY SI-related fields
                  const siResponses = alert.responses
                    ? Object.entries(alert.responses).filter(([key]) => SI_RELATED_FIELDS.includes(key))
                    : [];

                  return (
                    <div key={idx} className="bg-white border border-red-200 rounded p-4 shadow-sm">
                      <div className="flex items-center justify-between mb-3">
                        <div className="text-sm font-medium text-gray-700">
                          <Clock size={14} className="inline mr-1" />
                          {alert.time}
                        </div>
                        {alert.handled && (
                          <span className="px-2 py-1 bg-green-100 text-green-700 text-xs rounded font-medium">
                            SMS Sent
                          </span>
                        )}
                      </div>
                      {/* Display ONLY SI-related responses */}
                      {siResponses.length > 0 ? (
                        <div className="grid grid-cols-2 gap-x-6 gap-y-3">
                          {siResponses.map(([key, value], rIdx) => (
                            <div key={rIdx} className="border-l-3 border-red-400 pl-3 py-1 bg-red-50/50 rounded-r">
                              <div className="text-xs text-red-600 font-medium mb-0.5">
                                {formatQuestionLabel(key)}
                              </div>
                              <div className="font-semibold text-gray-800">
                                {formatSIResponseValue(key, value)}
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="text-gray-500 text-sm italic">
                          SI fields not yet answered at time of alert (only desire_intensity threshold was reached)
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Hourly Activity Chart */}
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-lg font-semibold text-gray-800 mb-4">Hourly Activity</h2>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={hourlyData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                  <XAxis
                    dataKey="hourLabel"
                    tick={{ fontSize: 10 }}
                    interval={2}
                  />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: 'white',
                      border: '1px solid #E5E7EB',
                      borderRadius: '8px',
                    }}
                  />
                  <Legend />
                  <Area
                    type="monotone"
                    dataKey="screenshots"
                    name="Screenshots"
                    stackId="1"
                    stroke={COLORS.blue}
                    fill={COLORS.blue}
                    fillOpacity={0.6}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Platform Breakdown Chart */}
          <div className="grid grid-cols-2 gap-6">
            <div className="bg-white rounded-lg shadow p-6">
              <h2 className="text-lg font-semibold text-gray-800 mb-4">Platform Activity</h2>
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={hourlyData.filter(h => h.reddit > 0 || h.twitter > 0)}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                    <XAxis dataKey="hourLabel" tick={{ fontSize: 10 }} />
                    <YAxis tick={{ fontSize: 11 }} />
                    <Tooltip />
                    <Legend />
                    <Bar
                      dataKey="reddit"
                      name="Reddit"
                      fill={PLATFORM_COLORS.reddit}
                      radius={[2, 2, 0, 0]}
                    />
                    <Bar
                      dataKey="twitter"
                      name="Twitter"
                      fill={PLATFORM_COLORS.twitter}
                      radius={[2, 2, 0, 0]}
                    />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="bg-white rounded-lg shadow p-6">
              <h2 className="text-lg font-semibold text-gray-800 mb-4">Platform Summary</h2>
              <div className="space-y-4">
                {platformData.length > 0 ? (
                  platformData.map((p, idx) => (
                    <div key={idx} className="flex items-center justify-between">
                      <div className="flex items-center">
                        <div
                          className="w-3 h-3 rounded-full mr-3"
                          style={{
                            backgroundColor: PLATFORM_COLORS[p.platform.toLowerCase()] || PLATFORM_COLORS.other
                          }}
                        />
                        <span className="font-medium capitalize">{p.platform}</span>
                      </div>
                      <div className="text-right">
                        <div className="text-gray-800 font-medium">{p.screenshots} screenshots</div>
                        <div className="text-gray-500 text-sm">{p.ocrWords.toLocaleString()} words</div>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="text-gray-500 text-center py-4">No platform data available</div>
                )}
              </div>
            </div>
          </div>

          {/* Check-ins/EMAs Section */}
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-lg font-semibold text-gray-800 mb-4 flex items-center">
              <CheckCircle size={20} className="mr-2" style={{ color: COLORS.green }} />
              EMA Check-ins ({dayData.checkins?.length || 0}/3)
            </h2>

            {dayData.checkins?.length > 0 ? (
              <div className="space-y-4">
                {dayData.checkins.map((checkin, idx) => (
                  <div
                    key={idx}
                    className={`border rounded-lg p-4 ${
                      checkin.crisis_indicated
                        ? 'border-red-300 bg-red-50'
                        : 'border-gray-200 bg-gray-50'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center text-gray-600 text-sm">
                        <Clock size={14} className="mr-1" />
                        {checkin.time}
                        {checkin.selfInitiated && (
                          <span className="ml-2 px-2 py-0.5 bg-blue-100 text-blue-700 text-xs rounded">
                            Self-initiated
                          </span>
                        )}
                      </div>
                      {checkin.crisis_indicated && (
                        <span className="flex items-center px-2 py-1 bg-red-100 text-red-700 text-xs rounded font-medium">
                          <AlertTriangle size={12} className="mr-1" /> Crisis Indicated
                        </span>
                      )}
                    </div>
                    {/* Display responses as key-value pairs with SI-friendly labels */}
                    {checkin.responses && Object.keys(checkin.responses).length > 0 ? (
                      <div className="grid grid-cols-2 gap-x-6 gap-y-2">
                        {Object.entries(checkin.responses).map(([key, value], rIdx) => {
                          const isSIField = SI_RELATED_FIELDS.includes(key);
                          return (
                            <div key={rIdx} className={`text-sm border-l-2 pl-3 py-1 ${
                              isSIField ? 'border-red-300 bg-red-50/30' : 'border-gray-300'
                            }`}>
                              <div className={`text-xs mb-0.5 ${isSIField ? 'text-red-600 font-medium' : 'text-gray-500'}`}>
                                {formatQuestionLabel(key)}
                              </div>
                              <div className="font-medium text-gray-800">
                                {formatSIResponseValue(key, value)}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="text-gray-400 text-sm">No responses recorded</div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-8 text-gray-500">
                No check-ins recorded for this day
              </div>
            )}

            {/* Check-in schedule indicator */}
            <div className="mt-4 pt-4 border-t text-sm text-gray-500">
              Expected check-in times: 10:00 AM, 2:00 PM, 6:00 PM
            </div>
          </div>

          {/* Screenshot Timeline */}
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-lg font-semibold text-gray-800 mb-4">Screenshot Timeline</h2>
            <div className="grid grid-cols-24 gap-1">
              {hourlyData.map((hour, idx) => (
                <div
                  key={idx}
                  className="relative group"
                  title={`${hour.hourLabel}: ${hour.screenshots} screenshots`}
                >
                  <div
                    className={`h-8 rounded ${
                      hour.screenshots === 0
                        ? 'bg-gray-100'
                        : hour.screenshots < 3
                        ? 'bg-orange-200'
                        : hour.screenshots < 10
                        ? 'bg-green-200'
                        : 'bg-green-400'
                    }`}
                  />
                  <div className="text-center text-xs text-gray-400 mt-1">
                    {idx % 4 === 0 ? hour.hourLabel : ''}
                  </div>

                  {/* Tooltip */}
                  <div className="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 px-2 py-1 bg-gray-800 text-white text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none z-10">
                    {hour.hourLabel}: {hour.screenshots} screenshots
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-4 flex items-center justify-center space-x-4 text-xs text-gray-500">
              <span className="flex items-center">
                <div className="w-3 h-3 bg-gray-100 rounded mr-1" /> No activity
              </span>
              <span className="flex items-center">
                <div className="w-3 h-3 bg-orange-200 rounded mr-1" /> Low (1-2)
              </span>
              <span className="flex items-center">
                <div className="w-3 h-3 bg-green-200 rounded mr-1" /> Moderate (3-9)
              </span>
              <span className="flex items-center">
                <div className="w-3 h-3 bg-green-400 rounded mr-1" /> High (10+)
              </span>
            </div>
          </div>

          {/* OCR Words Chart */}
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-lg font-semibold text-gray-800 mb-4">OCR Word Extraction by Hour</h2>
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={hourlyData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                  <XAxis
                    dataKey="hourLabel"
                    tick={{ fontSize: 10 }}
                    interval={2}
                  />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip
                    formatter={(value) => [value.toLocaleString(), 'Words']}
                    contentStyle={{
                      backgroundColor: 'white',
                      border: '1px solid #E5E7EB',
                      borderRadius: '8px',
                    }}
                  />
                  <Bar
                    dataKey="ocrWords"
                    name="OCR Words"
                    fill={COLORS.purple}
                    radius={[4, 4, 0, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Session Details (if available) */}
          {dayData.sessions?.length > 0 && (
            <div className="bg-white rounded-lg shadow p-6">
              <h2 className="text-lg font-semibold text-gray-800 mb-4">Sessions</h2>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-gray-50 border-b">
                    <tr>
                      <th className="px-4 py-3 text-left text-sm font-semibold text-gray-600">Start Time</th>
                      <th className="px-4 py-3 text-left text-sm font-semibold text-gray-600">End Time</th>
                      <th className="px-4 py-3 text-center text-sm font-semibold text-gray-600">Duration</th>
                      <th className="px-4 py-3 text-center text-sm font-semibold text-gray-600">Screenshots</th>
                      <th className="px-4 py-3 text-center text-sm font-semibold text-gray-600">Platform</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {dayData.sessions.map((session, idx) => (
                      <tr key={idx} className="hover:bg-gray-50">
                        <td className="px-4 py-3 text-gray-800">{session.start_time}</td>
                        <td className="px-4 py-3 text-gray-800">{session.end_time}</td>
                        <td className="px-4 py-3 text-center text-gray-600">{session.duration}</td>
                        <td className="px-4 py-3 text-center font-medium">{session.screenshots}</td>
                        <td className="px-4 py-3 text-center">
                          <span
                            className="px-2 py-1 rounded-full text-xs font-medium"
                            style={{
                              backgroundColor: `${PLATFORM_COLORS[session.platform?.toLowerCase()] || PLATFORM_COLORS.other}20`,
                              color: PLATFORM_COLORS[session.platform?.toLowerCase()] || PLATFORM_COLORS.other
                            }}
                          >
                            {session.platform || 'Unknown'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default DayDetailScreen;
