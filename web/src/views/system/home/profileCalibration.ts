/** Calibration belongs to this exact engineering PDF; positions are ring edges,
 * not the insertion origins of rotated ring-number labels. */
export const PROFILE_CALIBRATION = {
  source: '/static/home/changle-geology-profile.pdf',
  sha256: 'cb7b79b71e2f8098175539424087b9d601baee067709d230f40c59277abd5c0e',
  pdfWidth: 9524,
  startRing: 0,
  endRing: 2800,
  startX: 1165.117010888432,
  xPerRing: 2.831871170529,
} as const;

export function ringPositionPercent(ring: number, position: 'midpoint' | 'end' = 'midpoint') {
  const c = PROFILE_CALIBRATION;
  const bounded = Math.min(c.endRing, Math.max(c.startRing, ring));
  const offset = position === 'midpoint' && bounded > 0 ? bounded - 0.5 : bounded;
  return (c.startX + offset * c.xPerRing) / c.pdfWidth * 100;
}
