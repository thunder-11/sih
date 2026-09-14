/**
 * AnimatedNumber.jsx
 * Shared count-up component — 0 → value in 1.5s (easeOut).
 * Uses framer-motion: useMotionValue + useTransform + animate.
 *
 * Props:
 *   value          {number}  Target number
 *   prefix         {string}  Prepended string e.g. '₹' or '$'
 *   suffix         {string}  Appended string  e.g. '%'
 *   decimals       {number}  Decimal places to show (default 0)
 *   toLocaleString {bool}    Apply .toLocaleString() to the integer part
 *   duration       {number}  Animation duration in seconds (default 1.5)
 */
import { useEffect } from 'react';
import { motion, useMotionValue, useTransform, animate } from 'framer-motion';

export default function AnimatedNumber({
  value = 0,
  prefix = '',
  suffix = '',
  decimals = 0,
  toLocaleString = false,
  duration = 1.5,
}) {
  const count = useMotionValue(0);

  const display = useTransform(count, (latest) => {
    const factor = Math.pow(10, decimals);
    const rounded = Math.round(latest * factor) / factor;
    let str = decimals > 0 ? rounded.toFixed(decimals) : String(Math.round(rounded));
    if (toLocaleString) {
      str = Math.round(rounded).toLocaleString();
    }
    return `${prefix}${str}${suffix}`;
  });

  useEffect(() => {
    const controls = animate(count, value, { duration, ease: 'easeOut' });
    return () => controls.stop();
  }, [value, duration, count]);

  return <motion.span>{display}</motion.span>;
}
