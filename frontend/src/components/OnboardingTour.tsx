import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { NEW_SIGNUP_KEY } from '../auth/AuthContext';
import styles from './OnboardingTour.module.css';

interface TourStep {
  target?: string;
  title: string;
  body: string;
}

const STEPS: TourStep[] = [
  {
    target: 'create-agent-btn',
    title: 'Create an agent',
    body: 'Create an AI agent with its own knowledge base — upload documents and start chatting right away.',
  },
  {
    target: 'create-chatbot-btn',
    title: 'Create a chatbot',
    body: 'Orchestrate multiple agents behind one conversation, each handling what it does best.',
  },
  {
    target: 'token-balance',
    title: 'Your token balance',
    body: 'Every conversation spends tokens from this balance. Keep an eye on it here.',
  },
  {
    target: 'nav-menu',
    title: 'Your account',
    body: 'Manage your session and log out from here whenever you need to.',
  },
  {
    title: 'Share your agent',
    body: 'Open any agent and hit "Get shareable link" to create a public chat link or an embeddable widget snippet — no account required for whoever you send it to.',
  },
];

const POPOVER_WIDTH = 320;
const GAP = 14;
const SPOTLIGHT_PADDING = 8;
const DIM_BACKGROUND = 'rgba(12, 14, 18, 0.78)';

interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

function measure(target: string): Rect | null {
  const el = document.querySelector(`[data-tour="${target}"]`);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { top: r.top, left: r.left, width: r.width, height: r.height };
}

interface OnboardingTourProps {
  active: boolean;
  onClose: () => void;
}

export function OnboardingTour({ active, onClose }: OnboardingTourProps) {
  const [stepIndex, setStepIndex] = useState(0);
  const [rect, setRect] = useState<Rect | null>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (active) setStepIndex(0);
  }, [active]);

  useLayoutEffect(() => {
    if (!active) return undefined;
    const target = STEPS[stepIndex].target;
    if (!target) {
      setRect(null);
      return undefined;
    }
    function recompute() {
      setRect(measure(target!));
    }
    recompute();
    window.addEventListener('resize', recompute);
    return () => window.removeEventListener('resize', recompute);
  }, [active, stepIndex]);

  useEffect(() => {
    if (active) popoverRef.current?.focus();
  }, [active, stepIndex, rect]);

  useEffect(() => {
    if (!active) return undefined;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') finish();
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  function finish() {
    // Harmless no-op when the tour was started manually rather than via
    // the signup flag -- there's nothing to remove in that case.
    localStorage.removeItem(NEW_SIGNUP_KEY);
    onClose();
  }

  function next() {
    if (stepIndex === STEPS.length - 1) {
      finish();
    } else {
      setStepIndex((i) => i + 1);
    }
  }

  const step = STEPS[stepIndex];
  if (!active) return null;
  if (step.target && !rect) return null;

  const spotlightStyle = rect
    ? {
        top: rect.top - SPOTLIGHT_PADDING,
        left: rect.left - SPOTLIGHT_PADDING,
        width: rect.width + SPOTLIGHT_PADDING * 2,
        height: rect.height + SPOTLIGHT_PADDING * 2,
      }
    : undefined;

  const popoverStyle = rect
    ? {
        top: rect.top + rect.height + SPOTLIGHT_PADDING + GAP,
        left: Math.min(Math.max(rect.left, 16), Math.max(window.innerWidth - POPOVER_WIDTH - 16, 16)),
      }
    : {
        top: '50%',
        left: '50%',
        transform: 'translate(-50%, -50%)',
      };

  return (
    <div className={styles.blocker} style={rect ? undefined : { background: DIM_BACKGROUND }}>
      {spotlightStyle && <div className={styles.spotlight} style={spotlightStyle} />}
      <div
        className={styles.popover}
        style={popoverStyle}
        role="dialog"
        aria-modal="true"
        aria-label={step.title}
        tabIndex={-1}
        ref={popoverRef}
      >
        <p className={styles.step}>
          {stepIndex + 1} of {STEPS.length}
        </p>
        <h3>{step.title}</h3>
        <p className={styles.body}>{step.body}</p>
        <div className={styles.actions}>
          <button type="button" className="btn btn-ghost" onClick={finish}>
            Skip
          </button>
          <button type="button" className="btn btn-primary" onClick={next}>
            {stepIndex === STEPS.length - 1 ? 'Finish' : 'Next'}
          </button>
        </div>
      </div>
    </div>
  );
}
