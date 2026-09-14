import { useState, useEffect, useRef } from 'react';

/**
 * Real Investigation Loading Overlay
 * 
 * Features:
 * - Minimalist, high-impact aesthetic with ultra-large percentage counter in bottom-right.
 * - Smooth RAF progress interpolation connected to actual backend tracing events.
 * - Smooth upward clip-path reveal (inset 0 0 100% 0) upon 100% completion.
 * - Zero pointer-events blocking once dismissed.
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
  const targetValRef = useRef(progress);
  const rafRef = useRef(null);
  const completeTimerRef = useRef(null);

  // Update target progress
  useEffect(() => {
    targetValRef.current = Math.min(100, Math.max(0, progress));
  }, [progress]);

  // Handle active state changes & reset on new investigation
  useEffect(() => {
    if (active) {
      setIsOverlayVisible(true);
      setIsClipping(false);
      setShowContent(false);
      currentValRef.current = 0;
      setDisplayedPercent(0);
      targetValRef.current = Math.max(progress, 5); // Start at minimum 5% when active
    } else if (isError) {
      // Immediate exit on error
      setIsOverlayVisible(false);
      setIsClipping(false);
      setShowContent(true);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    }
  }, [active, isError]);

  // Smooth RAF interpolation from current to target
  useEffect(() => {
    if (!isOverlayVisible) return;

    const animate = () => {
      const current = currentValRef.current;
      const target = targetValRef.current;
      const diff = target - current;

      if (Math.abs(diff) > 0.4) {
        // Dynamic easing: faster for large gaps, smooth near target
        const step = diff > 0 ? Math.max(0.6, diff * 0.12) : diff * 0.2;
        const next = Math.min(100, current + step);
        currentValRef.current = next;
        setDisplayedPercent(Math.round(next));
        rafRef.current = requestAnimationFrame(animate);
      } else {
        currentValRef.current = target;
        setDisplayedPercent(Math.round(target));

        // When reached 100% and trace is complete
        if (target >= 100 && !isClipping) {
          if (completeTimerRef.current) clearTimeout(completeTimerRef.current);
          completeTimerRef.current = setTimeout(() => {
            setIsClipping(true);
            setTimeout(() => {
              setShowContent(true);
              setIsOverlayVisible(false);
              onComplete?.();
            }, 450);
          }, 180);
        } else {
          rafRef.current = requestAnimationFrame(animate);
        }
      }
    };

    rafRef.current = requestAnimationFrame(animate);

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      if (completeTimerRef.current) clearTimeout(completeTimerRef.current);
    };
  }, [isOverlayVisible, isClipping, onComplete]);

  return (
    <>
      {/* Loading Overlay Backdrop */}
      {isOverlayVisible && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 99999,
            backgroundColor: '#05070a',
            backgroundImage: `
              radial-gradient(circle at 85% 85%, rgba(200, 109, 59, 0.15), transparent 45%),
              radial-gradient(circle at 20% 30%, rgba(14, 165, 233, 0.08), transparent 40%),
              linear-gradient(rgba(255, 255, 255, 0.02) 1px, transparent 1px),
              linear-gradient(90deg, rgba(255, 255, 255, 0.02) 1px, transparent 1px)
            `,
            backgroundSize: '100% 100%, 100% 100%, 40px 40px, 40px 40px',
            clipPath: isClipping ? 'inset(0 0 100% 0)' : 'inset(0 0 0% 0)',
            pointerEvents: isClipping ? 'none' : 'auto',
            transition: 'clip-path 0.45s cubic-bezier(0.16, 1, 0.3, 1)',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
            padding: 'clamp(2rem, 5vw, 4rem)',
            color: '#ffffff',
            userSelect: 'none',
          }}
        >
          {/* Top Header Information */}
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
              <div
                style={{
                  width: 38,
                  height: 38,
                  borderRadius: 10,
                  background: 'rgba(200, 109, 59, 0.15)',
                  border: '1px solid rgba(200, 109, 59, 0.4)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '1.2rem',
                }}
              >
                ⚡
              </div>
              <div>
                <div style={{ fontSize: '0.8rem', fontWeight: 900, letterSpacing: '2px', color: 'var(--accent-copper, #c86d3b)', textTransform: 'uppercase' }}>
                  ARGUS FORENSIC ENGINE
                </div>
                <div style={{ fontSize: '1.25rem', fontWeight: 800, color: '#f8fafc', letterSpacing: '-0.02em', marginTop: 2 }}>
                  Autonomous Value-Weighted Graph Trace
                </div>
              </div>
            </div>

            {walletAddress && (
              <div
                style={{
                  padding: '8px 16px',
                  background: 'rgba(15, 23, 42, 0.8)',
                  border: '1px solid rgba(255, 255, 255, 0.1)',
                  borderRadius: 8,
                  fontFamily: 'var(--font-mono, monospace)',
                  fontSize: '0.8rem',
                  color: 'var(--accent-copper-light, #f0a742)',
                  maxWidth: 420,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                <span style={{ color: '#94a3b8', marginRight: 6 }}>TARGET:</span>
                {chain ? `[${chain}] ` : ''}{walletAddress}
              </div>
            )}
          </div>

          {/* Center / Middle Status Indicator */}
          <div style={{ maxWidth: 640 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
              <span
                style={{
                  display: 'inline-block',
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: 'var(--accent-copper, #c86d3b)',
                  boxShadow: '0 0 12px var(--accent-copper, #c86d3b)',
                  animation: 'pulse 1.5s infinite',
                }}
              />
              <span style={{ fontSize: '0.8rem', fontWeight: 700, letterSpacing: '1px', textTransform: 'uppercase', color: '#94a3b8' }}>
                LIVE BFS DISCOVERY PIPELINE
              </span>
            </div>

            <div
              style={{
                fontSize: 'clamp(1.1rem, 2.2vw, 1.6rem)',
                fontWeight: 600,
                color: '#e2e8f0',
                lineHeight: 1.4,
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
                marginTop: 24,
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
              right: 'clamp(1.5rem, 3vw, 4rem)',
              bottom: 'clamp(1.5rem, 3vw, 4rem)',
              fontSize: 'clamp(4.5rem, 12vw, 15rem)',
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
            }}
          >
            <span>{displayedPercent}</span>
            <span style={{ fontSize: '0.45em', opacity: 0.7, marginLeft: '0.05em' }}>%</span>
          </div>
        </div>
      )}

      {/* Page Content underneath */}
      <div
        style={{
          opacity: showContent ? 1 : 0,
          transform: showContent ? 'translateY(0)' : 'translateY(24px)',
          transition: 'opacity 0.5s cubic-bezier(0.16, 1, 0.3, 1), transform 0.5s cubic-bezier(0.16, 1, 0.3, 1)',
          width: '100%',
          height: '100%',
        }}
      >
        {children}
      </div>
    </>
  );
}

export default LoadingOverlay;
