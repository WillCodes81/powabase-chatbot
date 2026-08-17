import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { NEW_SIGNUP_KEY } from '../auth/AuthContext';
import styles from './OnboardingTour.module.css';

interface TourStep {
  target: string;
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
];

const POPOVER_WIDTH = 320;
const GAP = 14;
const SPOTLIGHT_PADDING = 8;

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

export function OnboardingTour() {
  const [active, setActive] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);
  const [rect, setRect] = useState<Rect | null>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (localStorage.getItem(NEW_SIGNUP_KEY) === 'true') setActive(true);
  }, []);

  useLayoutEffect(() => {
    if (!active) return;
    function recompute() {
      setRect(measure(STEPS[stepIndex].target));
    }
    recompute();
    window.addEventListener('resize', recompute);
    return () => window.removeEventListener('resize', recompute);
  }, [active, stepIndex]);

  useEffect(() => {
    if (active && rect) popoverRef.current?.focus();
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
    localStorage.removeItem(NEW_SIGNUP_KEY);
    setActive(false);
  }

  function next() {
    if (stepIndex === STEPS.length - 1) {
      finish();
    } else {
      setStepIndex((i) => i + 1);
    }
  }

  if (!active || !rect) return null;

  const step = STEPS[stepIndex];

  const spotlightStyle = {
    top: rect.top - SPOTLIGHT_PADDING,
    left: rect.left - SPOTLIGHT_PADDING,
    width: rect.width + SPOTLIGHT_PADDING * 2,
    height: rect.height + SPOTLIGHT_PADDING * 2,
  };

  const rawLeft = rect.left;
  const maxLeft = Math.max(window.innerWidth - POPOVER_WIDTH - 16, 16);
  const popoverStyle = {
    top: rect.top + rect.height + SPOTLIGHT_PADDING + GAP,
    left: Math.min(Math.max(rawLeft, 16), maxLeft),
  };

  return (
    <div className={styles.blocker}>
      <div className={styles.spotlight} style={spotlightStyle} />
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
