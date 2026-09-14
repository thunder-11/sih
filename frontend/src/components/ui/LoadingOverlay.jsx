import { useState, useEffect, useRef } from 'react';

/**
 * Real Investigation Loading Overlay
 * 
 * Features:
 * - Scoped strictly to its parent container (position: absolute, inset: 0).
 * - Large percentage counter with smooth RAF progress interpolation.
 * - Connected to actual backend tracing events (real progress).
 * - Smooth upward clip-path reveal (inset 0 0 100% 0) upon 100% completion.
 * - Zero pointer-events blocking once dismissed.
 * - Does NOT block the rest of the application.
 */
export function LoadingOverlay({
  active = false,
  progress = 0,
  stageMessage = '',
  walletAddress = '',
  chain = '',
  isError = false,
  onComplete,
  children,
}) {
  const [displayedPercent, setDisplayedPercent] = useState(0);
  const [isClipping, setIsClipping] = useState(false);
  const [showContent, setShowContent] = useState(!active);
  const [isOverlayVisible, setIsOverlayVisible] = useState(active);

  const currentValRef = useRef(0);
  const targetValRef = useRef(progress || 0);
  const rafRef = useRef(null);
  const isCompletingRef = useRef(false);
  const prevActiveRef = useRef(false);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  // Handle active state transitions
  useEffect(() => {
    if (active && !prevActiveRef.current) {
      // Starting a new loading investigation
      isCompletingRef.current = false;
      setIsOverlayVisible(true);
      setIsClipping(false);
      setShowContent(false);
      currentValRef.current = 0;
      setDisplayedPercent(0);
      targetValRef.current = Math.max(progress || 0, 15);
    } else if (active && prevActiveRef.current) {
      // Ongoing loading: update target without resetting current value!
      targetValRef.current = Math.min(95, Math.max(currentValRef.current, progress || 0));
    } else if (!active && prevActiveRef.current) {
      // Completed loading: smoothly interpolate to 100%
      targetValRef.current = 100;
    }
    prevActiveRef.current = active;
  }, [active, progress]);

  // Handle error dismissal
  useEffect(() => {
    if (isError) {
      isCompletingRef.current = false;
      setIsOverlayVisible(false);
      setIsClipping(false);
      setShowContent(true);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    }
  }, [isError]);

  // Smooth RAF progress interpolation & guaranteed completion dismiss
  useEffect(() => {
    if (!isOverlayVisible) return;

    const animate = () => {
      const current = currentValRef.current;
      const target = targetValRef.current;
      const diff = target - current;

      if (Math.abs(diff) > 0.4) {
        // Fast dynamic step when jumping to 100%, smooth near target
        const step = diff > 0 ? Math.max(1.2, diff * 0.18) : diff * 0.2;
        const next = Math.min(100, current + step);
        currentValRef.current = next;
        setDisplayedPercent(Math.round(next));
        rafRef.current = requestAnimationFrame(animate);
      } else {
        currentValRef.current = target;
        setDisplayedPercent(Math.round(target));

        if (target >= 100 && !isCompletingRef.current) {
          isCompletingRef.current = true;
          // Trigger clipping reveal
          setTimeout(() => {
            setIsClipping(true);
            setTimeout(() => {
              setShowContent(true);
              setIsOverlayVisible(false);
              isCompletingRef.current = false;
              onCompleteRef.current?.();
            }, 420);
          }, 120);
        } else if (!isCompletingRef.current) {
          rafRef.current = requestAnimationFrame(animate);
        }
      }
    };

    rafRef.current = requestAnimationFrame(animate);

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [isOverlayVisible]);

  const overlayElement = isOverlayVisible ? (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        zIndex: 40,
        backgroundColor: '#05070a',
        backgroundImage: `
          radial-gradient(circle at 85% 85%, rgba(200, 109, 59, 0.15), transparent 45%),
          radial-gradient(circle at 20% 30%, rgba(14, 165, 233, 0.08), transparent 40%),
          linear-gradient(rgba(255, 255, 255, 0.02) 1px, transparent 1px),
          linear-gradient(90deg, rgba(255, 255, 255, 0.02) 1px, transparent 1px)
        `,
        backgroundSize: '100% 100%, 100% 100%, 32px 32px, 32px 32px',
        clipPath: isClipping ? 'inset(0 0 100% 0)' : 'inset(0 0 0% 0)',
        pointerEvents: isClipping ? 'none' : 'auto',
        transition: 'clip-path 0.45s cubic-bezier(0.16, 1, 0.3, 1)',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        padding: 'clamp(1.2rem, 2.5vw, 2.5rem)',
        color: '#ffffff',
        userSelect: 'none',
        borderRadius: 'inherit',
        overflow: 'hidden',
      }}
    >
      {/* Top Header Information inside Graph Container */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, zIndex: 2 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div
            style={{
              width: 34,
              height: 34,
              borderRadius: 8,
              background: 'rgba(200, 109, 59, 0.15)',
              border: '1px solid rgba(200, 109, 59, 0.4)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '1.1rem',
              flexShrink: 0,
            }}
          >
            ⚡
          </div>
          <div>
            <div style={{ fontSize: '0.72rem', fontWeight: 900, letterSpacing: '1.5px', color: 'var(--accent-copper, #c86d3b)', textTransform: 'uppercase' }}>
              ARGUS FORENSIC ENGINE
            </div>
            <div style={{ fontSize: '1.05rem', fontWeight: 800, color: '#f8fafc', letterSpacing: '-0.02em', marginTop: 1 }}>
              Autonomous Value-Weighted Graph Trace
            </div>
          </div>
        </div>

        {walletAddress && (
          <div
            style={{
              padding: '6px 14px',
              background: 'rgba(15, 23, 42, 0.85)',
              border: '1px solid rgba(255, 255, 255, 0.12)',
              borderRadius: 6,
              fontFamily: 'var(--font-mono, monospace)',
              fontSize: '0.75rem',
              color: 'var(--accent-copper-light, #f0a742)',
              maxWidth: 380,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
            }}
          >
            <span style={{ color: '#94a3b8', marginRight: 6 }}>TARGET:</span>
            {chain ? `[${chain}] ` : ''}{walletAddress}
          </div>
        )}
      </div>

      {/* Center / Middle Status Indicator */}
      <div style={{ maxWidth: 540, zIndex: 2 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
          <span
            style={{
              display: 'inline-block',
              width: 7,
              height: 7,
              borderRadius: '50%',
              background: 'var(--accent-copper, #c86d3b)',
              boxShadow: '0 0 10px var(--accent-copper, #c86d3b)',
              animation: 'pulse 1.5s infinite',
            }}
          />
          <span style={{ fontSize: '0.72rem', fontWeight: 700, letterSpacing: '1px', textTransform: 'uppercase', color: '#94a3b8' }}>
            LIVE BFS DISCOVERY PIPELINE
          </span>
        </div>

        <div
          style={{
            fontSize: 'clamp(0.95rem, 1.8vw, 1.35rem)',
            fontWeight: 600,
            color: '#e2e8f0',
            lineHeight: 1.35,
            letterSpacing: '-0.01em',
          }}
        >
          {stageMessage || 'Analyzing on-chain transaction trails and entity attributions…'}
        </div>

        {/* Subtle Progress Bar */}
        <div
          style={{
            width: '100%',
            height: 3,
            background: 'rgba(255, 255, 255, 0.08)',
            borderRadius: 2,
            marginTop: 18,
            overflow: 'hidden',
            position: 'relative',
          }}
        >
          <div
            style={{
              height: '100%',
              width: `${displayedPercent}%`,
              background: 'linear-gradient(90deg, #0ea5e9, var(--accent-copper, #c86d3b), var(--accent-gold, #f59e0b))',
              boxShadow: '0 0 10px rgba(200, 109, 59, 0.8)',
              transition: 'width 0.15s ease-out',
            }}
          />
        </div>
      </div>

      {/* Bottom Right Giant Percentage Counter */}
      <div
        style={{
          position: 'absolute',
          right: 'clamp(1.2rem, 2.5vw, 2.5rem)',
          bottom: 'clamp(0.8rem, 2vw, 1.8rem)',
          fontSize: 'clamp(3.5rem, 8vw, 7.5rem)',
          fontWeight: 900,
          fontFamily: 'var(--font-mono, "JetBrains Mono", monospace)',
          lineHeight: 0.85,
          letterSpacing: '-0.04em',
          background: 'linear-gradient(145deg, #ffffff 30%, var(--accent-copper-light, #f0a742) 75%, var(--accent-copper, #c86d3b) 100%)',
          WebkitBackgroundClip: 'text',
          WebkitTextFillColor: 'transparent',
          textShadow: '0 0 80px rgba(200, 109, 59, 0.25)',
          display: 'flex',
          alignItems: 'flex-start',
          zIndex: 1,
          pointerEvents: 'none',
        }}
      >
        <span>{displayedPercent}</span>
        <span style={{ fontSize: '0.45em', opacity: 0.7, marginLeft: '0.05em' }}>%</span>
      </div>
    </div>
  ) : null;

  if (children) {
    return (
      <div style={{ position: 'relative', width: '100%', height: '100%', overflow: 'hidden' }}>
        <div
          style={{
            opacity: showContent ? 1 : 0,
            transform: showContent ? 'translateY(0)' : 'translateY(16px)',
            transition: 'opacity 0.45s cubic-bezier(0.16, 1, 0.3, 1), transform 0.45s cubic-bezier(0.16, 1, 0.3, 1)',
            width: '100%',
            height: '100%',
          }}
        >
          {children}
        </div>
        {overlayElement}
      </div>
    );
  }

  return overlayElement;
}

export default LoadingOverlay;
