// RiskAssessmentScreen.js - Full-page Risk Assessment Summary view
// Navigated to from ParticipantDetailScreen via button click.

import React from 'react';
import { ChevronLeft, Shield } from 'lucide-react';
import RiskAssessmentPanel from './RiskAssessmentPanel';

const RiskAssessmentScreen = ({ participantId, goToParticipantView }) => {
  return (
    <div className="space-y-4">
      {/* Header with back button */}
      <div className="flex items-center justify-between">
        <button
          onClick={() => goToParticipantView(participantId)}
          className="flex items-center gap-1 text-blue-600 hover:text-blue-800 text-sm font-medium"
        >
          <ChevronLeft size={18} />
          Back to {participantId}
        </button>
      </div>

      <div className="bg-white rounded-lg shadow overflow-hidden">
        <div className="px-6 py-4 border-b bg-gradient-to-r from-red-50 to-orange-50">
          <h1 className="text-xl font-bold text-gray-800 flex items-center gap-2">
            <Shield size={24} className="text-red-500" />
            Risk Assessment Summary
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Participant {participantId} — Live assessment from EMA, C-SSRS, safety plan, and contact info
          </p>
        </div>
        <div className="p-6">
          <RiskAssessmentPanel participantId={participantId} />
        </div>
      </div>
    </div>
  );
};

export default RiskAssessmentScreen;
