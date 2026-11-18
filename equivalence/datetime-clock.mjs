// Read the original public prompt/clock owners through the authenticated source loader.
export async function runDatetimeClock(input, source) {
  const clock = await source("src/agents/current-time.ts");
  const dates = await source("src/agents/date-time.ts");
  const hostTimezone = dates.resolveUserTimezone();
  const hostTimeFormat = dates.resolveUserTimeFormat();
  return {hostTimezone, hostTimeFormat, instants: input.instants.map(({iso, zone}) => {
    const timestampMs = Date.parse(iso);
    const instant = new Date(timestampMs);
    const label = dates.resolveUserTimezone(zone);
    const config = {agents: {defaults: {userTimezone: zone}}};
    return {iso, timestampMs, resolved: clock.resolveCronStyleNow(config, timestampMs),
      twelveHour: dates.formatUserTime(instant, label, "12"),
      twentyFourHour: dates.formatUserTime(instant, label, "24"),
      refreshed: clock.appendCronStyleCurrentTimeLine(input.text, config, timestampMs)};
  })};
}
