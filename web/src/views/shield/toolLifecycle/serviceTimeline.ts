/** Enrich only the selected interval; instance detail may contain other deployments. */
export function mergeServiceTimeline(segmentEvents: any[], detailEvents: any[]) {
  return segmentEvents.map(event => {
    const removal = event.event === 'REMOVE';
    const detail = detailEvents.find(candidate =>
      candidate.detail_id === event.detail_id &&
      (removal ? ['REMOVE_INSPECT', 'LEGACY_REMOVE'].includes(candidate.event) : ['INSTALL', 'LEGACY_INSTALL'].includes(candidate.event)) &&
      (!removal || candidate.pairing_confirmed !== false));
    return { ...detail, ...event };
  });
}
