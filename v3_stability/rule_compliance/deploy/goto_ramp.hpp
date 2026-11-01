#ifndef GOTO_RAMP_HPP
#define GOTO_RAMP_HPP

#include <algorithm>
#include <cmath>

namespace goto_motion {

template <typename Point>
inline bool finitePoint(const Point& point) {
    return std::isfinite(point.x) && std::isfinite(point.y) && std::isfinite(point.z);
}

template <typename Point>
inline bool finiteSegment(const Point& from, const Point& to) {
    const double dx = to.x - from.x;
    const double dy = to.y - from.y;
    const double dz = to.z - from.z;
    return finitePoint(from) && finitePoint(to) &&
           std::isfinite(std::hypot(dx, dy, dz));
}

inline double normalizedYaw(double yaw) {
    return std::remainder(yaw, 2.0 * std::acos(-1.0));
}

// Discard missed time rather than catching up with a large command after a stall.
inline double boundedDt(double elapsed_seconds) {
    return std::max(0.0, std::min(elapsed_seconds, 0.1));
}

template <typename Point>
bool advancePosition(Point& command, const Point& goal, double speed, double dt) {
    const double dx = goal.x - command.x;
    const double dy = goal.y - command.y;
    const double dz = goal.z - command.z;
    const double distance = std::hypot(dx, dy, dz);
    const double step = speed * boundedDt(dt);
    if (distance <= step) {
        command = goal;
        return true;
    }
    const double fraction = step / distance;
    command.x += dx * fraction;
    command.y += dy * fraction;
    command.z += dz * fraction;
    return false;
}

}  // namespace goto_motion
#endif
