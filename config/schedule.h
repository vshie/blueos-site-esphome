// BlueOS relay scheduler — shared by blueos-relay.yaml (this repo) and the
// bundled copy in blueos-site-esphome/config/schedule.h. Keep both in sync.
//
// Design goals (see BlueOS-HA-node/PLAN.md + blueos-site-stack/blueos-site-ui
// MQTT schema docs):
//   - Per-relay daily on/off time-of-day window + optional day-of-week mask.
//   - Schedule state lives in RAM only; durability comes from MQTT retained
//     messages on blueos/relay/schedule/relay_<N>/set (broker replays the
//     retained "set" to the device on every (re)subscribe), NOT flash — this
//     avoids flash wear from frequent schedule edits and keeps the ESP side
//     simple.
//   - Edge-triggered actuation: the relay is only commanded when the
//     scheduled on/off window transitions, so a manual MQTT override
//     (blueos/relay/switch/relay_<N>/command) between edges is not fought by
//     the scheduler until the next scheduled transition.
#pragma once

#include <array>
#include <cstdio>
#include <cstdlib>
#include <string>

namespace blueos_schedule {

constexpr int NUM_RELAYS = 6;

struct RelaySchedule {
  bool enabled = false;
  int on_min = 6 * 60;    // minutes since local midnight, default 06:00
  int off_min = 18 * 60;  // default 18:00
  // bit0=Sunday .. bit6=Saturday (ESPHome ESPTime::day_of_week: 1=Sunday..7=Saturday)
  uint8_t days_mask = 0x7F;
};

inline std::array<RelaySchedule, NUM_RELAYS> &schedules() {
  static std::array<RelaySchedule, NUM_RELAYS> instance;
  return instance;
}

// Parses "HH:MM" into minutes-since-midnight; returns `fallback` on any
// malformed input so a bad MQTT payload can't corrupt the schedule.
inline int parse_hhmm(const std::string &s, int fallback) {
  int h = -1, m = -1;
  if (std::sscanf(s.c_str(), "%d:%d", &h, &m) == 2 && h >= 0 && h < 24 && m >= 0 && m < 60) {
    return h * 60 + m;
  }
  return fallback;
}

inline std::string format_hhmm(int minutes_since_midnight) {
  int wrapped = ((minutes_since_midnight % 1440) + 1440) % 1440;
  char buf[6];
  std::snprintf(buf, sizeof(buf), "%02d:%02d", wrapped / 60, wrapped % 60);
  return std::string(buf);
}

// index 0 = Sunday .. index 6 = Saturday, '1' = active that day.
inline std::string days_to_string(uint8_t mask) {
  std::string out(7, '0');
  for (int i = 0; i < 7; i++) {
    if (mask & (1 << i))
      out[i] = '1';
  }
  return out;
}

inline uint8_t days_from_string(const std::string &s, uint8_t fallback) {
  if (s.size() != 7)
    return fallback;
  uint8_t mask = 0;
  for (int i = 0; i < 7; i++) {
    if (s[i] == '1')
      mask |= (1 << i);
    else if (s[i] != '0')
      return fallback;  // malformed — keep previous value
  }
  return mask;
}

// True if `minute_of_day` falls inside the schedule's on/off window,
// handling windows that wrap past midnight (off_min < on_min). Does not
// consider `enabled` or the day mask — callers combine those separately.
inline bool in_time_window(const RelaySchedule &sc, int minute_of_day) {
  if (sc.on_min == sc.off_min)
    return false;
  if (sc.on_min < sc.off_min)
    return minute_of_day >= sc.on_min && minute_of_day < sc.off_min;
  return minute_of_day >= sc.on_min || minute_of_day < sc.off_min;
}

// day_of_week: ESPHome ESPTime convention, 1=Sunday..7=Saturday.
inline bool should_be_on(const RelaySchedule &sc, int minute_of_day, uint8_t day_of_week) {
  if (!sc.enabled)
    return false;
  uint8_t dow_bit = 1 << ((day_of_week - 1) % 7);
  if ((sc.days_mask & dow_bit) == 0)
    return false;
  return in_time_window(sc, minute_of_day);
}

// JSON body for blueos/relay/schedule/relay_<N>/state (and mirrored on /set).
inline std::string schedule_to_json(const RelaySchedule &sc) {
  char buf[128];
  std::snprintf(
      buf, sizeof(buf),
      "{\"enabled\":%s,\"on\":\"%s\",\"off\":\"%s\",\"days\":\"%s\"}",
      sc.enabled ? "true" : "false", format_hhmm(sc.on_min).c_str(),
      format_hhmm(sc.off_min).c_str(), days_to_string(sc.days_mask).c_str());
  return std::string(buf);
}

inline const char *schedule_state_topic(int index) {
  static const char *topics[NUM_RELAYS] = {
      "blueos/relay/schedule/relay_1/state", "blueos/relay/schedule/relay_2/state",
      "blueos/relay/schedule/relay_3/state", "blueos/relay/schedule/relay_4/state",
      "blueos/relay/schedule/relay_5/state", "blueos/relay/schedule/relay_6/state",
  };
  if (index < 0 || index >= NUM_RELAYS)
    return nullptr;
  return topics[index];
}

}  // namespace blueos_schedule
