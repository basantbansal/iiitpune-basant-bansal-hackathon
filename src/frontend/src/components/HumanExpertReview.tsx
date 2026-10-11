import React, { useState, useEffect, useCallback } from 'react';
import { UserCheck, X, AlertCircle, CheckCircle2 } from 'lucide-react';

export interface ExpertReviewConfig {
  pricingNote: string;
  availabilityStatus: string;
  contactNumber: string | null;
  isServiceLive: boolean;
}

// Configurable defaults - unverified details left unpublished per compliance standards
const DEFAULT_EXPERT_CONFIG: ExpertReviewConfig = {
  pricingNote: 'Unpublished — confirmed prior to booking',
  availabilityStatus: 'Pilot in development (Analysts not on call)',
  contactNumber: null, // Left unpublished until verified
  isServiceLive: false,
};

interface HumanExpertReviewProps {
  config?: Partial<ExpertReviewConfig>;
  activeTicker?: string;
}

export default function HumanExpertReview({ config, activeTicker }: HumanExpertReviewProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [ticker, setTicker] = useState(activeTicker || 'GENERAL');
  const [contactEmail, setContactEmail] = useState('');
  const [notes, setNotes] = useState('');
  const [submitted, setSubmitted] = useState(false);

  const activeConfig: ExpertReviewConfig = {
    ...DEFAULT_EXPERT_CONFIG,
    ...config,
  };

  const handleClose = useCallback(() => {
    setIsOpen(false);
    setSubmitted(false);
  }, []);

  useEffect(() => {
    if (activeTicker) {
      setTicker(activeTicker);
    }
  }, [activeTicker]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        handleClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, handleClose]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitted(true);
  };

  return (
    <>
      {/* Human Expert Review CTA Card */}
      <div className="bg-surface border border-border/80 hover:border-primary/40 transition-colors rounded-lg p-5 mt-6 shadow-sm">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-start gap-3.5">
            <div className="p-2.5 rounded-lg bg-primary/10 border border-primary/20 text-primary shrink-0 mt-0.5">
              <UserCheck size={20} />
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h4 className="text-base font-semibold text-heading">
                  Want a second opinion?
                </h4>
                <span className="text-[10px] font-medium tracking-wider px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 font-mono uppercase">
                  Service Pilot
                </span>
              </div>
              <p className="text-sm text-gray-300 mt-1">
                AI helps you process news at scale. For complex or high-impact events, request a human expert review.
              </p>
              <p className="text-xs text-gray-400 mt-1.5 flex items-center gap-1.5">
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-400/90"></span>
                Optional paid service — availability and pricing confirmed before booking.
              </p>
            </div>
          </div>

          <div className="shrink-0 flex items-center md:self-center">
            <button
              onClick={() => setIsOpen(true)}
              className="w-full md:w-auto px-4 py-2 bg-primary hover:bg-blue-600 text-white text-sm font-medium rounded-lg transition-colors flex items-center justify-center gap-2 shadow-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
              aria-haspopup="dialog"
            >
              <UserCheck size={16} />
              Request Expert Review
            </button>
          </div>
        </div>
      </div>

      {/* Request / Demo Dialog */}
      {isOpen && (
        <div
          className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 overflow-y-auto"
          role="dialog"
          aria-modal="true"
          aria-labelledby="expert-review-title"
          onClick={(e) => {
            if (e.target === e.currentTarget) handleClose();
          }}
        >
          <div className="bg-surface border border-border rounded-xl max-w-lg w-full p-6 shadow-2xl relative my-8">
            {/* Close Button */}
            <button
              onClick={handleClose}
              className="absolute top-4 right-4 text-gray-400 hover:text-white p-1 rounded-md hover:bg-background/50 transition-colors"
              aria-label="Close dialog"
            >
              <X size={18} />
            </button>

            {/* Dialog Header */}
            <div className="flex items-center gap-3 mb-4">
              <div className="p-2 rounded-lg bg-primary/10 border border-primary/20 text-primary">
                <UserCheck size={20} />
              </div>
              <div>
                <h3 id="expert-review-title" className="text-lg font-bold text-heading">
                  Human Expert Review
                </h3>
                <span className="text-xs text-gray-400 font-mono">
                  Concept Demonstration • Second Opinion Workflow
                </span>
              </div>
            </div>

            {/* Prototype Notice Banner */}
            <div className="bg-amber-500/10 border border-amber-500/20 text-amber-300 text-xs p-3.5 rounded-lg mb-5 flex items-start gap-2.5 leading-relaxed">
              <AlertCircle size={16} className="shrink-0 mt-0.5 text-amber-400" />
              <div>
                <strong>Prototype Notice:</strong> Human risk analysts are not currently on call. This feature demonstrates the planned commercial workflow for human-in-the-loop auditability. Availability, accredited credentials, and pricing will be verified before commercial launch.
              </div>
            </div>

            {/* Status & Config Tiles */}
            <div className="grid grid-cols-2 gap-2.5 mb-5 text-xs">
              <div className="p-2.5 rounded bg-background border border-border">
                <span className="text-gray-400 block text-[11px]">Pricing Schedule</span>
                <span className="font-medium text-gray-200 mt-0.5 block">{activeConfig.pricingNote}</span>
              </div>
              <div className="p-2.5 rounded bg-background border border-border">
                <span className="text-gray-400 block text-[11px]">Service Status</span>
                <span className="font-medium text-amber-300 mt-0.5 block">{activeConfig.availabilityStatus}</span>
              </div>
              <div className="p-2.5 rounded bg-background border border-border col-span-2">
                <span className="text-gray-400 block text-[11px]">Desk Contact</span>
                <span className="font-medium text-gray-300 mt-0.5 block">
                  {activeConfig.contactNumber ? activeConfig.contactNumber : 'Unpublished (Contact line confirmed upon commercial onboarding)'}
                </span>
              </div>
            </div>

            {!submitted ? (
              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <label htmlFor="ticker-select" className="block text-xs font-medium text-gray-300 mb-1">
                    Event / Constituent Focus
                  </label>
                  <select
                    id="ticker-select"
                    value={ticker}
                    onChange={(e) => setTicker(e.target.value)}
                    className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-heading focus:outline-none focus:border-primary font-mono"
                  >
                    <option value="GENERAL">General Portfolio / Macro Overview</option>
                    <option value="AAPL">AAPL — Apple Inc.</option>
                    <option value="MSFT">MSFT — Microsoft Corp.</option>
                    <option value="NVDA">NVDA — NVIDIA Corp.</option>
                    <option value="AMZN">AMZN — Amazon.com Inc.</option>
                    <option value="GOOGL">GOOGL — Alphabet Inc.</option>
                    <option value="META">META — Meta Platforms Inc.</option>
                    <option value="TSLA">TSLA — Tesla Inc.</option>
                    <option value="JPM">JPM — JPMorgan Chase & Co.</option>
                    <option value="JNJ">JNJ — Johnson & Johnson</option>
                    <option value="XOM">XOM — Exxon Mobil Corp.</option>
                  </select>
                </div>

                <div>
                  <label htmlFor="contact-email" className="block text-xs font-medium text-gray-300 mb-1">
                    Requester Work Email <span className="text-gray-500 font-normal">(Optional for demo)</span>
                  </label>
                  <input
                    id="contact-email"
                    type="email"
                    placeholder="analyst@institution.com"
                    value={contactEmail}
                    onChange={(e) => setContactEmail(e.target.value)}
                    className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-heading placeholder-gray-600 focus:outline-none focus:border-primary"
                  />
                </div>

                <div>
                  <label htmlFor="review-notes" className="block text-xs font-medium text-gray-300 mb-1">
                    Specific Analysis Question or Context
                  </label>
                  <textarea
                    id="review-notes"
                    rows={3}
                    placeholder="e.g. Verify whether antitrust probe severity warrants full -5.0 pp underweight tilt..."
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-heading placeholder-gray-600 focus:outline-none focus:border-primary resize-none"
                  />
                </div>

                <div className="flex items-center justify-end gap-3 pt-2 border-t border-border/50">
                  <button
                    type="button"
                    onClick={handleClose}
                    className="px-3.5 py-1.5 text-xs text-gray-400 hover:text-white transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 bg-primary hover:bg-blue-600 text-white text-xs font-medium rounded-lg transition-colors flex items-center gap-1.5 shadow-sm"
                  >
                    <UserCheck size={14} />
                    Submit Demo Request
                  </button>
                </div>
              </form>
            ) : (
              <div className="text-center py-4 space-y-3">
                <div className="inline-flex p-3 rounded-full bg-success/10 border border-success/20 text-success">
                  <CheckCircle2 size={32} />
                </div>
                <h4 className="text-base font-bold text-heading">
                  Demo Request Simulated
                </h4>
                <p className="text-xs text-gray-300 max-w-sm mx-auto leading-relaxed">
                  Thank you for exploring the human-in-the-loop second opinion concept.
                  <span className="block mt-1 text-gray-400">
                    No actual booking was submitted and no charges apply. In a commercial deployment, this request would route to an accredited research desk with confirmed pricing.
                  </span>
                </p>
                <div className="pt-3">
                  <button
                    onClick={handleClose}
                    className="px-4 py-2 bg-surface border border-border hover:border-gray-500 text-white text-xs font-medium rounded-lg transition-colors"
                  >
                    Close Demo
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
