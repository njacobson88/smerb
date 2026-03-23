// InstallPage.js - App installation instructions for participants
// Accessible without authentication at /install

import React, { useState, useEffect } from 'react';
import { Smartphone, Download, Shield, CheckCircle, ChevronDown, ChevronUp } from 'lucide-react';

const API_BASE_URL = process.env.REACT_APP_LOCAL === 'true'
  ? "http://localhost:8080"
  : (process.env.REACT_APP_API_URL || "https://socialscope-dashboard-api-436153481478.us-central1.run.app");

const InstallPage = () => {
  const [installLinks, setInstallLinks] = useState(null);
  const [platform, setPlatform] = useState('auto');
  const [expandedSection, setExpandedSection] = useState(null);

  // Detect platform
  useEffect(() => {
    const ua = navigator.userAgent.toLowerCase();
    if (/iphone|ipad|ipod/.test(ua)) {
      setPlatform('ios');
    } else if (/android/.test(ua)) {
      setPlatform('android');
    }
  }, []);

  // Fetch install links
  useEffect(() => {
    fetch(`${API_BASE_URL}/api/install/links`)
      .then(r => r.json())
      .then(data => setInstallLinks(data))
      .catch(() => {});
  }, []);

  const toggleSection = (section) => {
    setExpandedSection(expandedSection === section ? null : section);
  };

  return (
    <div className="min-h-screen bg-gradient-to-b from-blue-50 to-white">
      {/* Header */}
      <div className="bg-gradient-to-r from-blue-600 to-purple-600 text-white py-12 px-4">
        <div className="max-w-2xl mx-auto text-center">
          <Smartphone size={48} className="mx-auto mb-4 opacity-90" />
          <h1 className="text-3xl font-bold mb-2">Install SocialScope</h1>
          <p className="text-blue-100 text-lg">
            Social Media Research Platform — Dartmouth College
          </p>
        </div>
      </div>

      <div className="max-w-2xl mx-auto px-4 py-8">
        {/* Platform tabs */}
        <div className="flex rounded-lg overflow-hidden border border-gray-200 mb-8">
          <button
            onClick={() => setPlatform('ios')}
            className={`flex-1 py-3 font-medium text-center transition-colors ${
              platform === 'ios'
                ? 'bg-blue-600 text-white'
                : 'bg-white text-gray-600 hover:bg-gray-50'
            }`}
          >
            iPhone / iPad
          </button>
          <button
            onClick={() => setPlatform('android')}
            className={`flex-1 py-3 font-medium text-center transition-colors ${
              platform === 'android'
                ? 'bg-green-600 text-white'
                : 'bg-white text-gray-600 hover:bg-gray-50'
            }`}
          >
            Android
          </button>
        </div>

        {/* iOS Instructions */}
        {platform === 'ios' && (
          <div className="space-y-4">
            {/* Download button */}
            {installLinks?.ios_url && (
              <a
                href={installLinks.ios_url}
                className="block w-full bg-blue-600 text-white text-center py-4 rounded-lg font-semibold text-lg hover:bg-blue-700 transition-colors"
              >
                <Download size={20} className="inline mr-2 -mt-1" />
                Download for iPhone
                {installLinks.ios_version && (
                  <span className="text-blue-200 text-sm ml-2">v{installLinks.ios_version}</span>
                )}
              </a>
            )}

            <div className="bg-white rounded-lg shadow-sm border p-6">
              <h2 className="text-xl font-semibold mb-4">Installation Steps</h2>

              <div className="space-y-4">
                <Step number={1} title="Download the app">
                  <p>Tap the download button above. When prompted by your browser, tap <strong>"Install"</strong> or <strong>"Download"</strong>.</p>
                </Step>

                <Step number={2} title="Trust the enterprise certificate">
                  <p>After downloading, you need to trust the app's certificate before it will open:</p>
                  <ol className="list-decimal list-inside mt-2 space-y-1 text-gray-700">
                    <li>Open <strong>Settings</strong> on your iPhone</li>
                    <li>Go to <strong>General</strong></li>
                    <li>Scroll down and tap <strong>VPN & Device Management</strong></li>
                    <li>Find <strong>"Dartmouth College"</strong> under Enterprise Apps</li>
                    <li>Tap it, then tap <strong>"Trust"</strong></li>
                    <li>Confirm by tapping <strong>"Trust"</strong> again</li>
                  </ol>
                </Step>

                <Step number={3} title="Open SocialScope">
                  <p>Return to your home screen and tap the <strong>SocialScope</strong> icon to open the app.</p>
                </Step>

                <Step number={4} title="Enter your Participant ID">
                  <p>Enter the 9-digit Participant ID provided by the research team. You'll need to enter it twice to confirm.</p>
                </Step>
              </div>
            </div>

            {/* Troubleshooting */}
            <div className="bg-white rounded-lg shadow-sm border overflow-hidden">
              <button
                onClick={() => toggleSection('ios-trouble')}
                className="w-full px-6 py-4 flex items-center justify-between text-left"
              >
                <span className="font-semibold text-gray-700">Troubleshooting</span>
                {expandedSection === 'ios-trouble' ? <ChevronUp size={20} /> : <ChevronDown size={20} />}
              </button>
              {expandedSection === 'ios-trouble' && (
                <div className="px-6 pb-4 text-sm text-gray-600 space-y-3">
                  <div>
                    <p className="font-medium text-gray-800">App won't open / "Untrusted Enterprise Developer"</p>
                    <p>Follow Step 2 above to trust the Dartmouth College certificate in Settings.</p>
                  </div>
                  <div>
                    <p className="font-medium text-gray-800">Download won't start</p>
                    <p>Make sure you're using Safari (not Chrome) to download. Enterprise apps must be installed through Safari on iOS.</p>
                  </div>
                  <div>
                    <p className="font-medium text-gray-800">"Cannot connect to [server]"</p>
                    <p>Make sure you have an active internet connection and try again.</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Android Instructions */}
        {platform === 'android' && (
          <div className="space-y-4">
            {/* Download button */}
            {installLinks?.android_url && (
              <a
                href={installLinks.android_url}
                className="block w-full bg-green-600 text-white text-center py-4 rounded-lg font-semibold text-lg hover:bg-green-700 transition-colors"
              >
                <Download size={20} className="inline mr-2 -mt-1" />
                Download for Android
                {installLinks.android_version && (
                  <span className="text-green-200 text-sm ml-2">v{installLinks.android_version}</span>
                )}
              </a>
            )}

            <div className="bg-white rounded-lg shadow-sm border p-6">
              <h2 className="text-xl font-semibold mb-4">Installation Steps</h2>

              <div className="space-y-4">
                <Step number={1} title="Download the APK">
                  <p>Tap the download button above. The file will download to your phone.</p>
                </Step>

                <Step number={2} title="Allow installation from this source">
                  <p>When you try to open the downloaded file, Android may ask you to allow installations from this source:</p>
                  <ol className="list-decimal list-inside mt-2 space-y-1 text-gray-700">
                    <li>Tap <strong>"Settings"</strong> when prompted</li>
                    <li>Toggle on <strong>"Allow from this source"</strong></li>
                    <li>Go back and tap <strong>"Install"</strong></li>
                  </ol>
                  <p className="mt-2 text-sm text-gray-500">
                    This is required because the app is not from the Google Play Store.
                  </p>
                </Step>

                <Step number={3} title="Open SocialScope">
                  <p>Once installed, tap <strong>"Open"</strong> or find <strong>SocialScope</strong> in your app drawer.</p>
                </Step>

                <Step number={4} title="Enter your Participant ID">
                  <p>Enter the 9-digit Participant ID provided by the research team. You'll need to enter it twice to confirm.</p>
                </Step>
              </div>
            </div>

            {/* Troubleshooting */}
            <div className="bg-white rounded-lg shadow-sm border overflow-hidden">
              <button
                onClick={() => toggleSection('android-trouble')}
                className="w-full px-6 py-4 flex items-center justify-between text-left"
              >
                <span className="font-semibold text-gray-700">Troubleshooting</span>
                {expandedSection === 'android-trouble' ? <ChevronUp size={20} /> : <ChevronDown size={20} />}
              </button>
              {expandedSection === 'android-trouble' && (
                <div className="px-6 pb-4 text-sm text-gray-600 space-y-3">
                  <div>
                    <p className="font-medium text-gray-800">"Install blocked" or "Unknown sources"</p>
                    <p>Go to Settings {">"} Security {">"} Install unknown apps, and enable for your browser.</p>
                  </div>
                  <div>
                    <p className="font-medium text-gray-800">"App not installed"</p>
                    <p>Make sure you have enough storage space and that you don't have a conflicting version already installed. Try uninstalling any old version first.</p>
                  </div>
                  <div>
                    <p className="font-medium text-gray-800">Can't find the downloaded file</p>
                    <p>Check your Downloads folder or notification tray for the download notification.</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* No download links available */}
        {!installLinks?.ios_url && !installLinks?.android_url && (
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-6 text-center">
            <Shield size={32} className="mx-auto mb-3 text-amber-500" />
            <p className="text-amber-800 font-medium">Downloads not yet available</p>
            <p className="text-amber-700 text-sm mt-2">
              The research team is preparing the app for distribution.
              Please check back later or contact the study team for assistance.
            </p>
          </div>
        )}

        {/* Footer */}
        <div className="mt-12 pt-8 border-t text-center text-sm text-gray-500">
          <p>SocialScope Research Study</p>
          <p className="mt-1">Dartmouth College</p>
          <p className="mt-2">
            If you need help installing the app, please contact the research team.
          </p>
        </div>
      </div>
    </div>
  );
};

// Step component for numbered instructions
const Step = ({ number, title, children }) => (
  <div className="flex gap-4">
    <div className="flex-shrink-0 w-8 h-8 bg-blue-100 text-blue-700 rounded-full flex items-center justify-center font-bold text-sm">
      {number}
    </div>
    <div className="flex-1">
      <h3 className="font-medium text-gray-900 mb-1">{title}</h3>
      <div className="text-gray-600 text-sm">{children}</div>
    </div>
  </div>
);

export default InstallPage;
